from __future__ import annotations

import time
import re
from collections import deque
from pathlib import PurePosixPath

from backend.app.core.database import connect, dict_from_row


ALLOWED_TRAVERSAL_EDGES = {
    "calls",
    "configured_by",
    "contains",
    "defines_route",
    "depends_on_package",
    "exports",
    "extends",
    "implements",
    "imports",
    "references",
    "reexports",
    "tested_by",
    "uses_schema",
}
DEFAULT_PATH_EDGES = ALLOWED_TRAVERSAL_EDGES - {"contains", "depends_on_package"}
GRAPH_VIEW_EDGES = DEFAULT_PATH_EDGES | {"contains"}


class GraphQueryError(ValueError):
    pass


def graph_summary(project_id: str) -> dict:
    with connect() as conn:
        project = _active_project(conn, project_id)
        snapshot_id = _structure_snapshot_id(project)
        node_rows = conn.execute(
            "SELECT kind, COUNT(*) AS total FROM code_nodes WHERE project_id = ? AND snapshot_id = ? GROUP BY kind",
            (project_id, snapshot_id),
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT edge_type, COUNT(*) AS total FROM code_edges WHERE project_id = ? AND snapshot_id = ? GROUP BY edge_type",
            (project_id, snapshot_id),
        ).fetchall()
        language_rows = conn.execute(
            """
            SELECT language, COUNT(*) AS total FROM code_nodes
            WHERE project_id = ? AND snapshot_id = ? AND language <> ''
            GROUP BY language ORDER BY total DESC
            """,
            (project_id, snapshot_id),
        ).fetchall()
        area_rows = conn.execute(
            """
            SELECT id, qualified_id, kind, display_label, relative_path, signature
            FROM code_nodes
            WHERE project_id = ? AND snapshot_id = ? AND kind IN ('package', 'module', 'class', 'route')
            ORDER BY kind, display_label LIMIT 50
            """,
            (project_id, snapshot_id),
        ).fetchall()
        return {
            "project_id": project_id,
            "snapshot_id": snapshot_id,
            "indexed_commit": project["indexed_commit"],
            "node_count": sum(int(row["total"]) for row in node_rows),
            "edge_count": sum(int(row["total"]) for row in edge_rows),
            "nodes_by_kind": {row["kind"]: int(row["total"]) for row in node_rows},
            "edges_by_type": {row["edge_type"]: int(row["total"]) for row in edge_rows},
            "languages": {row["language"]: int(row["total"]) for row in language_rows},
            "major_areas": [dict_from_row(row) for row in area_rows],
        }


def find_nodes(project_id: str, query: str, *, kinds: list[str] | None = None, limit: int = 25) -> list[dict]:
    needle = query.strip()
    if not needle:
        raise GraphQueryError("Node query is required.")
    bounded_limit = max(1, min(int(limit), 100))
    with connect() as conn:
        project = _active_project(conn, project_id)
        params: list[object] = [project_id, _structure_snapshot_id(project), f"%{needle}%", f"%{needle}%"]
        kind_clause = ""
        if kinds:
            allowed = [kind.strip() for kind in kinds if kind.strip()]
            if allowed:
                kind_clause = f" AND kind IN ({','.join('?' for _ in allowed)})"
                params.extend(allowed)
        params.extend([needle, bounded_limit])
        rows = conn.execute(
            f"""
            SELECT id, qualified_id, kind, language, display_label, relative_path,
                   start_line, end_line, signature, source_id
            FROM code_nodes
            WHERE project_id = ? AND snapshot_id = ?
              AND (display_label LIKE ? OR qualified_id LIKE ?)
              {kind_clause}
            ORDER BY
              CASE WHEN lower(display_label) = lower(?) THEN 0 ELSE 1 END,
              length(display_label), qualified_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict_from_row(row) for row in rows]


def node_neighbors(
    project_id: str,
    node_id: str,
    *,
    edge_types: list[str] | None = None,
    limit: int = 100,
) -> dict:
    allowed_edges = _allowed_edges(edge_types)
    bounded_limit = max(1, min(int(limit), 300))
    with connect() as conn:
        project = _active_project(conn, project_id)
        node = _node(conn, project_id, _structure_snapshot_id(project), node_id)
        placeholders = ",".join("?" for _ in allowed_edges)
        rows = conn.execute(
            f"""
            SELECT e.id AS edge_id, e.edge_type, e.confidence_class, e.source_line,
                   e.source_node_id, e.target_node_id,
                   n.id, n.qualified_id, n.kind, n.language, n.display_label,
                   n.relative_path, n.start_line, n.end_line, n.signature, n.source_id
            FROM code_edges e
            JOIN code_nodes n ON n.id = CASE WHEN e.source_node_id = ? THEN e.target_node_id ELSE e.source_node_id END
            WHERE e.project_id = ? AND e.snapshot_id = ?
              AND (e.source_node_id = ? OR e.target_node_id = ?)
              AND e.edge_type IN ({placeholders})
              AND e.confidence_class IN ('extracted', 'user_confirmed')
            ORDER BY e.edge_type, n.display_label LIMIT ?
            """,
            [node_id, project_id, _structure_snapshot_id(project), node_id, node_id, *allowed_edges, bounded_limit],
        ).fetchall()
        return {"node": node, "neighbors": [dict_from_row(row) for row in rows]}


def shortest_path(
    project_id: str,
    source_query: str,
    target_query: str,
    *,
    max_depth: int = 4,
    max_nodes: int = 1000,
    max_edges: int = 2000,
    timeout_ms: int = 500,
    edge_types: list[str] | None = None,
) -> dict:
    depth_limit = max(1, min(int(max_depth), 6))
    node_limit = max(10, min(int(max_nodes), 2000))
    edge_limit = max(10, min(int(max_edges), 10000))
    time_limit_ms = max(25, min(int(timeout_ms), 2000))
    allowed_edges = sorted(DEFAULT_PATH_EDGES) if not edge_types else _allowed_edges(edge_types)
    with connect() as conn:
        project = _active_project(conn, project_id)
        snapshot_id = _structure_snapshot_id(project)
        source = _resolve_unique_node(conn, project_id, snapshot_id, source_query)
        target = _resolve_unique_node(conn, project_id, snapshot_id, target_query)
        if source["id"] == target["id"]:
            return {"status": "found", "path": [source], "edges": [], "visited_nodes": 1, "elapsed_ms": 0.0}
        placeholders = ",".join("?" for _ in allowed_edges)
        started = time.perf_counter()
        queue = deque([(source["id"], 0)])
        previous: dict[str, tuple[str, dict] | None] = {source["id"]: None}
        examined_edges: set[str] = set()
        status = "not_found"
        while queue:
            if (time.perf_counter() - started) * 1000 > time_limit_ms:
                status = "timeout"
                break
            current, depth = queue.popleft()
            if depth >= depth_limit:
                continue
            edge_rows = conn.execute(
                f"""
                SELECT id, source_node_id, target_node_id, edge_type, confidence_class,
                       evidence_source_id, source_line
                FROM code_edges
                WHERE project_id = ? AND snapshot_id = ?
                  AND (source_node_id = ? OR target_node_id = ?)
                  AND edge_type IN ({placeholders})
                  AND confidence_class IN ('extracted', 'user_confirmed')
                ORDER BY edge_type, id
                """,
                [project_id, snapshot_id, current, current, *allowed_edges],
            ).fetchall()
            for row in edge_rows:
                edge = dict_from_row(row)
                examined_edges.add(edge["id"])
                if len(examined_edges) > edge_limit:
                    status = "edge_budget_exceeded"
                    queue.clear()
                    break
                neighbor = edge["target_node_id"] if edge["source_node_id"] == current else edge["source_node_id"]
                if neighbor in previous:
                    continue
                previous[neighbor] = (current, edge)
                if len(previous) > node_limit:
                    status = "node_budget_exceeded"
                    queue.clear()
                    break
                if neighbor == target["id"]:
                    status = "found"
                    queue.clear()
                    break
                queue.append((neighbor, depth + 1))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        if status != "found":
            return {
                "status": status,
                "path": [],
                "edges": [],
                "visited_nodes": len(previous),
                "examined_edges": len(examined_edges),
                "elapsed_ms": elapsed_ms,
            }
        node_ids: list[str] = []
        edges: list[dict] = []
        cursor = target["id"]
        while cursor != source["id"]:
            node_ids.append(cursor)
            parent, edge = previous[cursor]
            edges.append(edge)
            cursor = parent
        node_ids.append(source["id"])
        node_ids.reverse()
        edges.reverse()
        node_map = {
            row["id"]: dict_from_row(row)
            for row in conn.execute(
                f"""
                SELECT id, qualified_id, kind, language, display_label, relative_path,
                       start_line, end_line, signature, source_id
                FROM code_nodes WHERE id IN ({','.join('?' for _ in node_ids)})
                """,
                node_ids,
            ).fetchall()
        }
        return {
            "status": "found",
            "path": [node_map[node_id] for node_id in node_ids],
            "edges": edges,
            "visited_nodes": len(previous),
            "examined_edges": len(examined_edges),
            "elapsed_ms": elapsed_ms,
            "snapshot_id": snapshot_id,
            "indexed_commit": project["indexed_commit"],
        }


def graph_view(
    project_id: str,
    *,
    mode: str = "graph",
    query: str = "",
    root: str = "",
    max_depth: int = 2,
    max_nodes: int = 120,
    edge_types: list[str] | None = None,
) -> dict:
    """Return a bounded, evidence-backed projection suitable for UI and LLM clients."""
    normalized_mode = mode.strip().casefold()
    if normalized_mode not in {"graph", "tree"}:
        raise GraphQueryError("Graph view mode must be 'graph' or 'tree'.")
    node_limit = max(10, min(int(max_nodes), 300))
    depth_limit = max(1, min(int(max_depth), 4))
    with connect() as conn:
        project = _active_project(conn, project_id)
        snapshot_id = _structure_snapshot_id(project)
        if normalized_mode == "tree":
            nodes, edges, truncated = _tree_projection(
                conn, project_id, snapshot_id, query=query, root=root, max_nodes=node_limit
            )
        else:
            allowed_edges = sorted(GRAPH_VIEW_EDGES) if not edge_types else _allowed_edges(edge_types)
            nodes, edges, truncated = _graph_projection(
                conn,
                project_id,
                snapshot_id,
                query=query,
                root=root,
                max_depth=depth_limit,
                max_nodes=node_limit,
                edge_types=allowed_edges,
            )
        return {
            "version": 1,
            "project_id": project_id,
            "snapshot_id": snapshot_id,
            "indexed_commit": project["indexed_commit"],
            "mode": normalized_mode,
            "query": query.strip(),
            "root": root.strip(),
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "limits": {"max_nodes": node_limit, "max_depth": depth_limit},
            "warnings": ["This is a bounded projection, not the entire project graph."] if truncated else [],
        }


def graph_view_markdown(view: dict) -> str:
    """Serialize a graph projection into a compact, model-friendly evidence packet."""
    lines = [
        f"# Odin {str(view['mode']).title()} Context",
        "",
        f"Project: {view['project_id']}",
        f"Snapshot: {view['snapshot_id']}",
        f"Indexed commit: {view.get('indexed_commit') or 'folder snapshot'}",
        f"Scope: {view.get('query') or view.get('root') or 'major project areas'}",
        f"Bounded: {'yes' if view.get('truncated') else 'no'}",
        "",
        "## Nodes",
    ]
    for node in view["nodes"]:
        location = str(node.get("relative_path") or "")
        if node.get("start_line"):
            location += f":{node['start_line']}"
        lines.append(f"- [{node['id']}] {node['kind']} {node['label']} ({location or 'project'})")
    lines.extend(["", "## Relationships"])
    for edge in view["edges"]:
        evidence = ""
        if edge.get("source_line"):
            evidence = f" at line {edge['source_line']}"
        lines.append(
            f"- [{edge['source']}] --{edge['type']}--> [{edge['target']}]"
            f" ({edge.get('confidence', 'extracted')}{evidence})"
        )
    if view.get("warnings"):
        lines.extend(["", "## Notes", *[f"- {warning}" for warning in view["warnings"]]])
    return "\n".join(lines) + "\n"


def _graph_projection(
    conn,
    project_id: str,
    snapshot_id: str,
    *,
    query: str,
    root: str,
    max_depth: int,
    max_nodes: int,
    edge_types: list[str],
) -> tuple[list[dict], list[dict], bool]:
    seeds = _projection_seeds(conn, project_id, snapshot_id, query=query, root=root, limit=min(12, max_nodes))
    if not seeds:
        return [], [], False
    selected: dict[str, dict] = {row["id"]: row for row in seeds}
    seen_edges: dict[str, dict] = {}
    truncated = False
    frontier = list(selected)
    for _depth in range(max_depth):
        if not frontier:
            break
        remaining = max_nodes - len(selected)
        if remaining <= 0:
            truncated = True
            break
        frontier_placeholders = ",".join("?" for _ in frontier)
        edge_placeholders = ",".join("?" for _ in edge_types)
        edge_budget = max(50, remaining * 5)
        rows = conn.execute(
            f"""
            SELECT e.id, e.source_node_id, e.target_node_id, e.edge_type,
                   e.confidence_class, e.evidence_source_id, e.source_line
            FROM code_edges e
            WHERE e.project_id = ? AND e.snapshot_id = ?
              AND (e.source_node_id IN ({frontier_placeholders})
                   OR e.target_node_id IN ({frontier_placeholders}))
              AND e.edge_type IN ({edge_placeholders})
              AND e.confidence_class IN ('extracted', 'user_confirmed')
            ORDER BY CASE e.edge_type WHEN 'calls' THEN 0 WHEN 'imports' THEN 1 ELSE 2 END, e.id
            LIMIT ?
            """,
            [project_id, snapshot_id, *frontier, *frontier, *edge_types, edge_budget + 1],
        ).fetchall()
        if len(rows) > edge_budget:
            truncated = True
        candidates = [dict_from_row(row) for row in rows[:edge_budget]]
        new_ids: list[str] = []
        for item in candidates:
            for candidate_id in (item["source_node_id"], item["target_node_id"]):
                if candidate_id not in selected and candidate_id not in new_ids:
                    if len(new_ids) >= remaining:
                        truncated = True
                        break
                    new_ids.append(candidate_id)
        if new_ids:
            node_rows = conn.execute(
                f"""
                SELECT id, qualified_id, kind, language, display_label, relative_path,
                       start_line, end_line, signature, source_id
                FROM code_nodes WHERE project_id = ? AND snapshot_id = ?
                  AND id IN ({','.join('?' for _ in new_ids)})
                """,
                [project_id, snapshot_id, *new_ids],
            ).fetchall()
            selected.update({row["id"]: _view_node(dict_from_row(row)) for row in node_rows})
        for item in candidates:
            if item["source_node_id"] in selected and item["target_node_id"] in selected:
                seen_edges[item["id"]] = _view_edge(item)
        frontier = [node_id for node_id in new_ids if node_id in selected]
    connected_ids = {
        node_id
        for edge in seen_edges.values()
        for node_id in (edge["source"], edge["target"])
    }
    nodes = [
        selected[node_id] for node_id in selected
        if not seen_edges or node_id in connected_ids
    ]
    return nodes, list(seen_edges.values()), truncated


def _tree_projection(
    conn,
    project_id: str,
    snapshot_id: str,
    *,
    query: str,
    root: str,
    max_nodes: int,
) -> tuple[list[dict], list[dict], bool]:
    params: list[object] = [project_id, snapshot_id]
    clauses = ["project_id = ?", "snapshot_id = ?", "kind <> 'project'"]
    scope = root.strip().replace("\\", "/").strip("/")
    if scope:
        clauses.append("relative_path LIKE ?")
        params.append(f"{scope}%")
    if query.strip():
        clauses.append("(display_label LIKE ? OR qualified_id LIKE ? OR relative_path LIKE ?)")
        needle = f"%{query.strip()}%"
        params.extend([needle, needle, needle])
    else:
        clauses.append("kind = 'file'")
    params.append(max_nodes + 1)
    rows = conn.execute(
        f"""
        SELECT id, qualified_id, kind, language, display_label, relative_path,
               start_line, end_line, signature, source_id
        FROM code_nodes WHERE {' AND '.join(clauses)}
        ORDER BY relative_path, CASE kind WHEN 'file' THEN 0 WHEN 'module' THEN 1 ELSE 2 END,
                 start_line, display_label LIMIT ?
        """,
        params,
    ).fetchall()
    if not rows and query.strip():
        return _tree_projection(
            conn, project_id, snapshot_id, query="", root=root, max_nodes=max_nodes
        )
    truncated = len(rows) > max_nodes
    code_nodes = [dict_from_row(row) for row in rows[:max_nodes]]
    nodes: dict[str, dict] = {
        f"project:{project_id}": {
            "id": f"project:{project_id}", "qualified_id": project_id, "kind": "project",
            "language": "", "label": "Project", "relative_path": "", "start_line": None,
            "end_line": None, "signature": "", "source_id": None,
        }
    }
    edges: list[dict] = []
    files: dict[str, str] = {}
    for item in code_nodes:
        path = str(item.get("relative_path") or "").replace("\\", "/")
        parent = f"project:{project_id}"
        parts = PurePosixPath(path).parts
        for index in range(max(0, len(parts) - 1)):
            directory = "/".join(parts[: index + 1])
            directory_id = f"dir:{directory}"
            if directory_id not in nodes:
                nodes[directory_id] = {
                    "id": directory_id, "qualified_id": directory, "kind": "directory",
                    "language": "", "label": parts[index], "relative_path": directory,
                    "start_line": None, "end_line": None, "signature": "", "source_id": None,
                }
                edges.append(_contains_edge(parent, directory_id))
            parent = directory_id
        node = _view_node(item)
        nodes[node["id"]] = node
        if item["kind"] == "file":
            files[path] = node["id"]
            edges.append(_contains_edge(parent, node["id"]))
        else:
            edges.append(_contains_edge(files.get(path, parent), node["id"]))
    if len(nodes) > max_nodes:
        keep = set(list(nodes)[:max_nodes])
        nodes = {key: value for key, value in nodes.items() if key in keep}
        edges = [edge for edge in edges if edge["source"] in keep and edge["target"] in keep]
        truncated = True
    return list(nodes.values()), edges, truncated


def _projection_seeds(conn, project_id: str, snapshot_id: str, *, query: str, root: str, limit: int) -> list[dict]:
    stopwords = {
        "architecture", "codebase", "dependency", "diagram", "display", "draw", "for",
        "graph", "please", "project", "relationship", "render", "repository", "show",
        "structure", "the", "tree", "visualize",
    }
    terms = [
        term for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)
        if term.casefold() not in stopwords
    ][:6]
    scope = root.strip().replace("\\", "/").strip("/")
    scope_clause = " AND n.relative_path LIKE ?" if scope else ""
    scope_params: list[object] = [f"{scope}%"] if scope else []
    selected: dict[str, dict] = {}
    if terms:
        per_term_limit = max(3, (limit + len(terms) - 1) // len(terms))
        for term in terms:
            needle = term[:4] if len(term) > 6 else term
            wildcard = f"%{needle}%"
            rows = conn.execute(
                f"""
                SELECT n.id, n.qualified_id, n.kind, n.language, n.display_label, n.relative_path,
                       n.start_line, n.end_line, n.signature, n.source_id
                FROM code_nodes n
                WHERE n.project_id = ? AND n.snapshot_id = ? {scope_clause}
                  AND (n.display_label LIKE ? OR n.qualified_id LIKE ? OR n.relative_path LIKE ?)
                ORDER BY CASE
                           WHEN lower(n.display_label) = lower(?) THEN 0
                           WHEN lower(n.display_label) LIKE lower(?) THEN 1
                           WHEN lower(n.relative_path) LIKE lower(?) THEN 2
                           ELSE 3 END,
                         CASE WHEN n.relative_path LIKE 'backend/tests/%'
                                    OR n.relative_path LIKE 'apps/%/tests/%'
                                    OR n.relative_path LIKE '%/__tests__/%' THEN 1 ELSE 0 END,
                         CASE n.kind WHEN 'class' THEN 0 WHEN 'route' THEN 1 WHEN 'function' THEN 2
                              WHEN 'module' THEN 3 WHEN 'file' THEN 4 ELSE 5 END,
                         length(n.display_label), n.display_label
                LIMIT ?
                """,
                [
                    project_id, snapshot_id, *scope_params, wildcard, wildcard, wildcard,
                    term, f"{needle}%", f"%/{needle}%", per_term_limit,
                ],
            ).fetchall()
            for row in rows:
                item = _view_node(dict_from_row(row))
                selected.setdefault(item["id"], item)
                if len(selected) >= limit:
                    return list(selected.values())
        if selected:
            return list(selected.values())
    rows = conn.execute(
        f"""
        WITH endpoints AS (
            SELECT source_node_id AS node_id FROM code_edges
            WHERE project_id = ? AND snapshot_id = ?
              AND edge_type <> 'depends_on_package'
              AND confidence_class IN ('extracted', 'user_confirmed')
            UNION ALL
            SELECT target_node_id AS node_id FROM code_edges
            WHERE project_id = ? AND snapshot_id = ?
              AND edge_type <> 'depends_on_package'
              AND confidence_class IN ('extracted', 'user_confirmed')
        ), degree AS (
            SELECT node_id, COUNT(*) AS total FROM endpoints GROUP BY node_id
        )
        SELECT n.id, n.qualified_id, n.kind, n.language, n.display_label, n.relative_path,
               n.start_line, n.end_line, n.signature, n.source_id
        FROM code_nodes n
        JOIN degree d ON d.node_id = n.id
        WHERE n.project_id = ? AND n.snapshot_id = ? {scope_clause}
          AND n.kind NOT IN ('configuration_key', 'package', 'project')
        ORDER BY CASE WHEN n.relative_path LIKE 'backend/tests/%'
                           OR n.relative_path LIKE 'apps/%/tests/%'
                           OR n.relative_path LIKE '%/__tests__/%' THEN 1 ELSE 0 END,
                 d.total DESC,
                 CASE n.kind WHEN 'file' THEN 0 WHEN 'class' THEN 1 WHEN 'route' THEN 2 ELSE 3 END,
                 n.display_label LIMIT ?
        """,
        [project_id, snapshot_id, project_id, snapshot_id, project_id, snapshot_id, *scope_params, limit],
    ).fetchall()
    return [_view_node(dict_from_row(row)) for row in rows]


def _view_node(item: dict, *, node_id: str | None = None) -> dict:
    return {
        "id": node_id or item["id"],
        "qualified_id": item["qualified_id"],
        "kind": item["kind"],
        "language": item.get("language") or "",
        "label": item.get("display_label") or item.get("label") or item["qualified_id"],
        "relative_path": item.get("relative_path") or "",
        "start_line": item.get("start_line"),
        "end_line": item.get("end_line"),
        "signature": item.get("signature") or "",
        "source_id": item.get("source_id"),
    }


def _view_edge(item: dict) -> dict:
    return {
        "id": item["id"], "source": item["source_node_id"], "target": item["target_node_id"],
        "type": item["edge_type"], "confidence": item.get("confidence_class") or "extracted",
        "evidence_source_id": item.get("evidence_source_id"), "source_line": item.get("source_line"),
    }


def _contains_edge(source: str, target: str) -> dict:
    return {
        "id": f"contains:{source}:{target}", "source": source, "target": target,
        "type": "contains", "confidence": "extracted", "evidence_source_id": None, "source_line": None,
    }


def _active_project(conn, project_id: str):
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL",
        (project_id,),
    ).fetchone()
    if row is None:
        raise KeyError(project_id)
    if not (row["active_structure_snapshot_id"] or row["active_snapshot_id"]):
        raise GraphQueryError("Project has no active snapshot.")
    return row


def _structure_snapshot_id(project) -> str:
    return str(project["active_structure_snapshot_id"] or project["active_snapshot_id"])


def _node(conn, project_id: str, snapshot_id: str, node_id: str) -> dict:
    row = conn.execute(
        """
        SELECT id, qualified_id, kind, language, display_label, relative_path,
               start_line, end_line, signature, source_id
        FROM code_nodes WHERE id = ? AND project_id = ? AND snapshot_id = ?
        """,
        (node_id, project_id, snapshot_id),
    ).fetchone()
    if row is None:
        raise KeyError(node_id)
    return dict_from_row(row)


def _resolve_unique_node(conn, project_id: str, snapshot_id: str, query: str) -> dict:
    rows = conn.execute(
        """
        SELECT id, qualified_id, kind, language, display_label, relative_path,
               start_line, end_line, signature, source_id
        FROM code_nodes
        WHERE project_id = ? AND snapshot_id = ?
          AND (lower(display_label) = lower(?) OR lower(qualified_id) = lower(?))
        ORDER BY kind, qualified_id LIMIT 3
        """,
        (project_id, snapshot_id, query.strip(), query.strip()),
    ).fetchall()
    if not rows:
        raise GraphQueryError(f"No indexed node matches {query!r}.")
    if len(rows) > 1:
        labels = ", ".join(str(row["qualified_id"]) for row in rows)
        raise GraphQueryError(f"Node name is ambiguous. Use a qualified ID: {labels}")
    return dict_from_row(rows[0])


def _allowed_edges(requested: list[str] | None) -> list[str]:
    if not requested:
        return sorted(ALLOWED_TRAVERSAL_EDGES)
    normalized = {item.strip() for item in requested if item.strip()}
    unsupported = normalized - ALLOWED_TRAVERSAL_EDGES
    if unsupported:
        raise GraphQueryError(f"Unsupported edge types: {', '.join(sorted(unsupported))}")
    return sorted(normalized)
