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
_PROJECTION_STOPWORDS = {
    "about", "all", "and", "are", "architecture", "code", "codebase", "could",
    "dependency", "diagram", "display", "does", "draw", "explain", "file", "files",
    "find", "for", "from", "generated", "give", "graph", "have", "how", "into", "is", "me",
    "open", "please", "project", "relationship", "render", "repository", "show", "shown", "source",
    "sources", "structure", "system", "that", "the", "this", "through", "tree", "using",
    "visualize", "what", "when", "where", "which", "why", "with", "work", "working", "works",
}
_GRAPH_VIEW_MAX_NODES = 2000


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
        wildcard = f"%{needle}%"
        params: list[object] = [
            project_id, _structure_snapshot_id(project), wildcard, wildcard, wildcard,
        ]
        kind_clause = ""
        if kinds:
            allowed = [kind.strip() for kind in kinds if kind.strip()]
            if allowed:
                kind_clause = f" AND n.kind IN ({','.join('?' for _ in allowed)})"
                params.extend(allowed)
        params.extend([needle, needle, bounded_limit])
        rows = conn.execute(
            f"""
            SELECT n.id, n.qualified_id, n.kind, n.language, n.display_label, n.relative_path,
                   n.start_line, n.end_line, n.signature, n.source_id,
                   COALESCE(pss.file_role, 'source') AS file_role
            FROM code_nodes n
            LEFT JOIN project_snapshot_sources pss
              ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
            WHERE n.project_id = ? AND n.snapshot_id = ?
              AND (n.display_label LIKE ? OR n.qualified_id LIKE ? OR n.relative_path LIKE ?)
              {kind_clause}
            ORDER BY
              CASE WHEN lower(n.display_label) = lower(?) THEN 0
                   WHEN lower(n.relative_path) = lower(?) THEN 1 ELSE 2 END,
              length(n.display_label), n.qualified_id
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
            if len(previous) >= node_limit:
                status = "node_budget_exceeded"
                break
            remaining_edges = edge_limit - len(examined_edges)
            if remaining_edges <= 0:
                status = "edge_budget_exceeded"
                break
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
                LIMIT ?
                """,
                [project_id, snapshot_id, current, current, *allowed_edges, remaining_edges + 1],
            ).fetchall()
            for row in edge_rows:
                edge = dict_from_row(row)
                if edge["id"] not in examined_edges and len(examined_edges) >= edge_limit:
                    status = "edge_budget_exceeded"
                    queue.clear()
                    break
                examined_edges.add(edge["id"])
                neighbor = edge["target_node_id"] if edge["source_node_id"] == current else edge["source_node_id"]
                if neighbor in previous:
                    continue
                if len(previous) >= node_limit:
                    status = "node_budget_exceeded"
                    queue.clear()
                    break
                previous[neighbor] = (current, edge)
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
    direction: str = "outbound",
) -> dict:
    """Return a bounded, evidence-backed projection suitable for UI and LLM clients."""
    # Older or partially activated projects build this optional layer on first map use.
    from backend.app.core.project_graph_intelligence import get_graph_intelligence
    graph_intelligence = get_graph_intelligence(project_id)
    normalized_mode = mode.strip().casefold()
    if normalized_mode not in {"graph", "tree"}:
        raise GraphQueryError("Graph view mode must be 'graph' or 'tree'.")
    normalized_direction = direction.strip().casefold()
    if normalized_direction not in {"outbound", "inbound", "balanced"}:
        raise GraphQueryError("Graph direction must be 'outbound', 'inbound', or 'balanced'.")
    node_limit = max(10, min(int(max_nodes), _GRAPH_VIEW_MAX_NODES))
    depth_ceiling = 2 if _projection_query_terms(query) else 4
    depth_limit = max(1, min(int(max_depth), depth_ceiling))
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
                direction=normalized_direction,
            )
        metric_node_ids = [str(node["id"]) for node in nodes if not str(node["id"]).startswith(("dir:", "project:"))]
        if metric_node_ids and graph_intelligence.get("status") == "ready":
            metric_rows = conn.execute(
                f"""SELECT node_id, pagerank, in_degree, out_degree, scc_id, scc_size,
                           community_id, community_label, is_cycle
                    FROM project_graph_metrics WHERE project_id = ? AND snapshot_id = ?
                      AND node_id IN ({','.join('?' for _ in metric_node_ids)})""",
                [project_id, snapshot_id, *metric_node_ids],
            ).fetchall()
            metrics = {row["node_id"]: dict_from_row(row) for row in metric_rows}
            for node in nodes:
                metric = metrics.get(node["id"])
                if metric:
                    node["centrality"] = float(metric["pagerank"])
                    node["in_degree"] = int(metric["in_degree"])
                    node["out_degree"] = int(metric["out_degree"])
                    node["community"] = {"id": metric["community_id"], "label": metric["community_label"]}
                    node["cycle"] = {"id": metric["scc_id"], "size": int(metric["scc_size"])} if metric["is_cycle"] else None
        project_totals = {
            "nodes": int(conn.execute(
                "SELECT COUNT(*) AS total FROM code_nodes WHERE project_id = ? AND snapshot_id = ?",
                (project_id, snapshot_id),
            ).fetchone()["total"] or 0),
            "edges": int(conn.execute(
                "SELECT COUNT(*) AS total FROM code_edges WHERE project_id = ? AND snapshot_id = ?",
                (project_id, snapshot_id),
            ).fetchone()["total"] or 0),
        }
        insights = _graph_insights(nodes, edges)
        return {
            "version": 1,
            "project_id": project_id,
            "snapshot_id": snapshot_id,
            "indexed_commit": project["indexed_commit"],
            "mode": normalized_mode,
            "query": query.strip(),
            "root": root.strip(),
            "direction": normalized_direction,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "limits": {"max_nodes": node_limit, "max_depth": depth_limit},
            "project_totals": project_totals,
            "warnings": ["This is a bounded projection, not the entire project graph."] if truncated else [],
            "insights": insights,
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
        "## Overview",
        str((view.get("insights") or {}).get("summary") or "No connected project areas were found."),
        "",
        "## Key areas",
    ]
    for area in (view.get("insights") or {}).get("key_areas") or []:
        lines.append(
            f"- {area['label']} ({area['kind']}, {area['connections']} relationships)"
            f" — {area.get('relative_path') or 'project root'}"
        )
    lines.extend([
        "",
        "## Flows",
    ])
    flows = (view.get("insights") or {}).get("flows") or []
    if flows:
        for flow in flows:
            lines.append(f"- {' → '.join(flow['steps'])}")
    else:
        lines.append("- No directed multi-step flow was present in this bounded view.")
    lines.extend([
        "",
        "## Nodes",
    ])
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
    direction: str,
) -> tuple[list[dict], list[dict], bool]:
    seeds = _projection_seeds(conn, project_id, snapshot_id, query=query, root=root, limit=min(12, max_nodes))
    if not seeds:
        return [], [], False
    selected: dict[str, dict] = {row["id"]: row for row in seeds}
    seed_ids = set(selected)
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
        direction_order = ""
        direction_params: list[str] = []
        if direction == "outbound":
            direction_order = f"CASE WHEN e.source_node_id IN ({frontier_placeholders}) THEN 0 ELSE 1 END,"
            direction_params = list(frontier)
        elif direction == "inbound":
            direction_order = f"CASE WHEN e.target_node_id IN ({frontier_placeholders}) THEN 0 ELSE 1 END,"
            direction_params = list(frontier)
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
            ORDER BY {direction_order}
                     CASE e.edge_type WHEN 'calls' THEN 0 WHEN 'imports' THEN 1
                         WHEN 'defines_route' THEN 2 ELSE 3 END, e.id
            LIMIT ?
            """,
            [
                project_id, snapshot_id, *frontier, *frontier, *edge_types,
                *direction_params, edge_budget + 1,
            ],
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
        if not seen_edges or node_id in connected_ids or node_id in seed_ids
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
    terms = _projection_query_terms(query)
    if terms:
        matches = []
        for term in terms:
            matches.append("(display_label LIKE ? OR qualified_id LIKE ? OR relative_path LIKE ?)")
            needle = f"%{term}%"
            params.extend([needle, needle, needle])
        clauses.append(f"({' OR '.join(matches)})")
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
    truncated = len(rows) > max_nodes
    code_nodes = [dict_from_row(row) for row in rows[:max_nodes]]
    if not code_nodes:
        return [], [], False
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
    terms = _projection_query_terms(query)
    scope = root.strip().replace("\\", "/").strip("/")
    scope_clause = " AND n.relative_path LIKE ?" if scope else ""
    scope_params: list[object] = [f"{scope}%"] if scope else []
    selected: dict[str, dict] = {}
    if terms:
        # Gather candidates for every meaningful query term before ranking. Returning
        # as soon as the first term filled the budget made question word order affect
        # the graph and allowed generic/test symbols to crowd out exact source symbols.
        # Pull enough candidates to let cross-term matches outrank exact but unrelated
        # single-term symbols (for example source_import_batch over model imports).
        per_term_limit = max(100, limit * 10)
        candidates_by_term: dict[str, list[dict]] = {term: [] for term in terms}
        for term in terms:
            needle = _projection_term_needle(term)
            wildcard = f"%{needle}%"
            rows = conn.execute(
                f"""
                SELECT n.id, n.qualified_id, n.kind, n.language, n.display_label, n.relative_path,
                       n.start_line, n.end_line, n.signature, n.source_id,
                       COALESCE(pss.file_role, 'source') AS file_role
                FROM code_nodes n
                LEFT JOIN project_snapshot_sources pss
                  ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
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
                raw = dict_from_row(row)
                item = {**_view_node(raw), "file_role": raw.get("file_role") or "source"}
                matched_terms = _matching_projection_terms(item, terms)
                if not matched_terms:
                    continue
                item["matched_terms"] = matched_terms
                selected.setdefault(item["id"], item)
                candidates_by_term[term].append(item)
        if selected:
            ranked = sorted(
                selected.values(),
                key=lambda item: (-_projection_seed_score(item, terms), item["qualified_id"]),
            )
            balanced: list[dict] = []
            balanced_ids: set[str] = set()
            per_term_quota = max(1, min(3, limit // max(1, len(terms))))
            for term in terms:
                term_ranked = sorted(
                    candidates_by_term[term],
                    key=lambda item: (-_projection_seed_score(item, terms), item["qualified_id"]),
                )
                for item in term_ranked[:per_term_quota]:
                    if item["id"] not in balanced_ids:
                        balanced.append(item)
                        balanced_ids.add(item["id"])
            # Preserve the cross-term balance above, then use the global ranking
            # to fill the remaining caller-approved capacity. The quota is a
            # diversity floor, not a hard three-seed ceiling.
            for item in ranked:
                if len(balanced) >= limit:
                    break
                if item["id"] not in balanced_ids:
                    balanced.append(item)
                    balanced_ids.add(item["id"])
            return [
                {key: value for key, value in item.items() if key != "file_role"}
                for item in balanced[:limit]
            ]
        return []
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
        [
            project_id,
            snapshot_id,
            project_id,
            snapshot_id,
            project_id,
            snapshot_id,
            *scope_params,
            min(limit, 6),
        ],
    ).fetchall()
    return [_view_node(dict_from_row(row)) for row in rows]


def _graph_insights(nodes: list[dict], edges: list[dict]) -> dict:
    """Build deterministic, traceable orientation hints for a bounded graph."""
    if not nodes:
        return {
            "summary": "No indexed project areas matched this view.",
            "key_areas": [],
            "flows": [],
            "node_kinds": {},
            "relationship_types": {},
            "component_count": 0,
        }
    node_by_id = {str(node["id"]): node for node in nodes}
    degree = {node_id: 0 for node_id in node_by_id}
    outgoing: dict[str, list[tuple[str, str, str]]] = {node_id: [] for node_id in node_by_id}
    undirected: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    relationship_types: dict[str, int] = {}
    node_kinds: dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("kind") or "other")
        node_kinds[kind] = node_kinds.get(kind, 0) + 1
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source not in node_by_id or target not in node_by_id:
            continue
        edge_type = str(edge.get("type") or "related")
        relationship_types[edge_type] = relationship_types.get(edge_type, 0) + 1
        degree[source] += 1
        degree[target] += 1
        outgoing[source].append((target, edge_type, str(edge.get("confidence") or "extracted")))
        undirected[source].add(target)
        undirected[target].add(source)

    key_areas = []
    for node_id in sorted(
        node_by_id,
        key=lambda candidate: (
            len(node_by_id[candidate].get("matched_terms") or []),
            float(node_by_id[candidate].get("centrality") or 0),
            degree[candidate],
            node_by_id[candidate].get("kind") in {"route", "file", "module", "class"},
            str(node_by_id[candidate].get("label") or ""),
        ),
        reverse=True,
    )[:6]:
        node = node_by_id[node_id]
        key_areas.append(
            {
                "id": node_id,
                "label": node.get("label") or node.get("qualified_id") or node_id,
                "kind": node.get("kind") or "item",
                "relative_path": node.get("relative_path") or "",
                "connections": degree[node_id],
                "centrality": float(node.get("centrality") or 0),
                "community": node.get("community"),
                "why": (
                    "Direct question match: " + ", ".join(node.get("matched_terms") or [])
                    if node.get("matched_terms")
                    else "High project-wide centrality"
                    if node.get("centrality")
                    else "Highly connected in this view"
                ),
            }
        )

    visited: set[str] = set()
    component_count = 0
    for node_id in node_by_id:
        if node_id in visited:
            continue
        component_count += 1
        frontier = [node_id]
        visited.add(node_id)
        while frontier:
            current = frontier.pop()
            for neighbor in undirected[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)

    flows: list[dict] = []
    flow_starts = [area["id"] for area in key_areas if outgoing[area["id"]]]
    for start in flow_starts:
        path = [start]
        edge_path: list[str] = []
        confidence_path: list[str] = []
        while len(path) < 5:
            choices = [
                (target, edge_type, confidence)
                for target, edge_type, confidence in outgoing[path[-1]]
                if target not in path
            ]
            if not choices:
                break
            target, edge_type, confidence = max(choices, key=lambda item: degree[item[0]])
            path.append(target)
            edge_path.append(edge_type)
            confidence_path.append(confidence)
        if len(path) < 3:
            continue
        signature = tuple(path)
        if any(tuple(flow["node_ids"]) == signature for flow in flows):
            continue
        flows.append(
            {
                "node_ids": path,
                "steps": [str(node_by_id[node_id].get("label") or node_id) for node_id in path],
                "relationships": edge_path,
                "confidence": "user_confirmed" if confidence_path and all(value == "user_confirmed" for value in confidence_path) else "extracted",
                "reason": "Follows " + ", then ".join(value.replace("_", " ") for value in edge_path) + " relationships found in the indexed code.",
            }
        )
        if len(flows) == 4:
            break

    top_relationship = max(relationship_types, key=relationship_types.get) if relationship_types else ""
    summary = (
        f"This view connects {len(nodes)} indexed items with {len(edges)} traceable relationships"
        f" across {component_count} {'area' if component_count == 1 else 'areas'}."
    )
    if top_relationship:
        summary += f" The most common relationship is {top_relationship.replace('_', ' ')}."
    return {
        "summary": summary,
        "key_areas": key_areas,
        "flows": flows,
        "node_kinds": node_kinds,
        "relationship_types": relationship_types,
        "component_count": component_count,
    }


def _projection_query_terms(query: str) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    focused_query = re.sub(
        r"\b(?:project|dependency|relationship)\s+map\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    for index, term in enumerate(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", focused_query)):
        folded = term.casefold()
        identifier_like = "_" in term or "$" in term or any(
            character.isupper() for character in term[1:]
        )
        if folded in _PROJECTION_STOPWORDS or (
            len(term) < 4 and not identifier_like and folded != "map"
        ):
            continue
        if folded in seen:
            continue
        seen.add(folded)
        candidates.append((0 if identifier_like else 1, index, term))
    candidates.sort()
    return [term for _priority, _index, term in candidates[:12]]


def _matching_projection_terms(node: dict, terms: list[str]) -> list[str]:
    haystack = " ".join(
        str(node.get(field) or "")
        for field in ("label", "display_label", "qualified_id", "relative_path", "signature")
    ).casefold()
    return [term for term in terms if _projection_term_needle(term) in haystack]


def _projection_term_needle(term: str) -> str:
    folded = term.casefold()
    domain_aliases = {
        "clustering": "cluster",
        "connections": "connection",
        "interpretation": "intelligence",
        "upload": "import",
    }
    return domain_aliases.get(folded, folded)


def _projection_seed_score(node: dict, terms: list[str]) -> int:
    """Rank exact, authoritative code symbols ahead of incidental text matches."""
    label = str(node.get("label") or node.get("display_label") or "").casefold()
    qualified = str(node.get("qualified_id") or "").casefold()
    path = str(node.get("relative_path") or "").replace("\\", "/").casefold()
    signature = str(node.get("signature") or "").casefold()
    score = 0
    for raw_term in terms:
        term = _projection_term_needle(raw_term)
        if label == term:
            score += 120
        elif label.startswith(term):
            score += 55
        elif term in label:
            score += 35
        if qualified == term or qualified.endswith(f":{term}") or qualified.endswith(f".{term}"):
            score += 70
        elif term in qualified:
            score += 18
        if term in signature:
            score += 14
        if term in path:
            score += 8
    kind_bonus = {
        "class": 18, "route": 17, "function": 16, "method": 15,
        "module": 10, "file": 8,
    }
    score += kind_bonus.get(str(node.get("kind") or ""), 0)
    file_role = str(node.get("file_role") or "source").casefold()
    if file_role in {"test", "fixture", "generated", "vendor"}:
        score -= 45
    if re.search(r"(^|/)(tests?|__tests__|fixtures?|generated|vendor)(/|$)", path):
        score -= 35
    return score


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
        **({"matched_terms": list(item["matched_terms"])} if item.get("matched_terms") else {}),
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
