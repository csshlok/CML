from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import PurePosixPath
from typing import Iterable

from backend.app.core.database import connect, dict_from_row, utc_now


GRAPH_METRICS_VERSION = "odin-graph-intelligence-v1"
_AUTHORITY_EDGES = {
    "calls", "imports", "references", "exports", "defines_route", "implements", "inherits",
}
_FLOW_EDGES = {"calls", "defines_route", "imports", "references", "exports"}


def compute_graph_metrics(
    node_ids: Iterable[str],
    edges: Iterable[tuple[str, str]],
    *,
    iterations: int = 20,
    damping: float = 0.85,
) -> dict[str, dict]:
    """Compute bounded deterministic rank, degree, and SCC data without third-party graph code."""
    ordered = sorted(set(str(node_id) for node_id in node_ids))
    if not ordered:
        return {}
    node_set = set(ordered)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in ordered}
    reverse: dict[str, list[str]] = {node_id: [] for node_id in ordered}
    for source, target in sorted(set((str(a), str(b)) for a, b in edges)):
        if source not in node_set or target not in node_set or source == target:
            continue
        adjacency[source].append(target)
        reverse[target].append(source)
    rank = {node_id: 1.0 / len(ordered) for node_id in ordered}
    base = (1.0 - damping) / len(ordered)
    for _ in range(max(1, min(int(iterations), 50))):
        dangling = sum(rank[node_id] for node_id in ordered if not adjacency[node_id]) / len(ordered)
        next_rank = {}
        for node_id in ordered:
            incoming = sum(rank[parent] / len(adjacency[parent]) for parent in reverse[node_id])
            next_rank[node_id] = base + damping * (incoming + dangling)
        rank = next_rank
    scc_by_node = _strongly_connected_components(ordered, adjacency, reverse)
    sizes: dict[str, int] = defaultdict(int)
    for scc_id in scc_by_node.values():
        sizes[scc_id] += 1
    return {
        node_id: {
            "pagerank": round(rank[node_id], 12),
            "in_degree": len(reverse[node_id]),
            "out_degree": len(adjacency[node_id]),
            "scc_id": scc_by_node[node_id],
            "scc_size": sizes[scc_by_node[node_id]],
            "is_cycle": sizes[scc_by_node[node_id]] > 1,
        }
        for node_id in ordered
    }


def refresh_graph_intelligence(project_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        project_row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)
        ).fetchone()
        if project_row is None:
            raise KeyError(project_id)
        project = dict_from_row(project_row)
        snapshot_id = project.get("active_structure_snapshot_id") or project.get("active_snapshot_id")
        if not snapshot_id:
            return {"status": "unavailable", "reason": "No active structure snapshot."}
        nodes = [
            dict_from_row(row)
            for row in conn.execute(
                """
                SELECT id, qualified_id, kind, display_label, relative_path
                FROM code_nodes WHERE project_id = ? AND snapshot_id = ? ORDER BY id
                """,
                (project_id, snapshot_id),
            ).fetchall()
        ]
        edge_rows = [
            dict_from_row(row)
            for row in conn.execute(
                """
                SELECT id, source_node_id, target_node_id, edge_type, confidence_class
                FROM code_edges
                WHERE project_id = ? AND snapshot_id = ?
                  AND confidence_class IN ('extracted', 'user_confirmed')
                ORDER BY id
                """,
                (project_id, snapshot_id),
            ).fetchall()
        ]
        authority_edges = [
            (str(row["source_node_id"]), str(row["target_node_id"]))
            for row in edge_rows
            if str(row["edge_type"]) in _AUTHORITY_EDGES
        ]
        metrics = compute_graph_metrics((str(node["id"]) for node in nodes), authority_edges)
        community_by_node, communities = _communities(nodes)
        conn.execute(
            "DELETE FROM project_graph_metrics WHERE project_id = ? AND snapshot_id = ?",
            (project_id, snapshot_id),
        )
        conn.execute(
            "DELETE FROM project_graph_communities WHERE project_id = ? AND snapshot_id = ?",
            (project_id, snapshot_id),
        )
        conn.execute(
            "DELETE FROM project_execution_flows WHERE project_id = ? AND snapshot_id = ?",
            (project_id, snapshot_id),
        )
        for node in nodes:
            node_id = str(node["id"])
            metric = metrics[node_id]
            community = communities[community_by_node[node_id]]
            conn.execute(
                """
                INSERT INTO project_graph_metrics (
                    project_id, snapshot_id, node_id, pagerank, in_degree, out_degree,
                    scc_id, scc_size, community_id, community_label, is_cycle, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, snapshot_id, node_id, metric["pagerank"], metric["in_degree"],
                    metric["out_degree"], metric["scc_id"], metric["scc_size"],
                    community["id"], community["label"], int(metric["is_cycle"]), now,
                ),
            )
        for community in communities.values():
            conn.execute(
                """
                INSERT INTO project_graph_communities (
                    id, project_id, snapshot_id, label, root_path, node_count,
                    file_count, summary_json, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    community["id"], project_id, snapshot_id, community["label"],
                    community["root_path"], community["node_count"], community["file_count"],
                    json.dumps(community["summary"], sort_keys=True, separators=(",", ":")), now,
                ),
            )
        flows = _execution_flows(nodes, edge_rows, metrics, project.get("entrypoints") or _json(project.get("entrypoints_json"), []))
        for flow in flows:
            conn.execute(
                """
                INSERT INTO project_execution_flows (
                    id, project_id, snapshot_id, start_node_id, end_node_id, node_ids_json,
                    relationships_json, confidence_class, reason, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flow["id"], project_id, snapshot_id, flow["node_ids"][0], flow["node_ids"][-1],
                    json.dumps(flow["node_ids"], separators=(",", ":")),
                    json.dumps(flow["relationships"], separators=(",", ":")),
                    flow["confidence"], flow["reason"], now,
                ),
            )
        _publish_graph_layer(conn, project_id, snapshot_id, communities, metrics, flows, now)
    return {
        "status": "ready",
        "version": GRAPH_METRICS_VERSION,
        "snapshot_id": snapshot_id,
        "node_count": len(nodes),
        "edge_count": len(authority_edges),
        "community_count": len(communities),
        "cycle_count": len({item["scc_id"] for item in metrics.values() if item["is_cycle"]}),
        "flow_count": len(flows),
    }


def get_graph_intelligence(project_id: str, *, refresh_missing: bool = True) -> dict:
    with connect() as conn:
        project = conn.execute(
            "SELECT active_structure_snapshot_id, active_snapshot_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        snapshot_id = project["active_structure_snapshot_id"] or project["active_snapshot_id"]
        available_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
                ("project_graph_metrics", "project_graph_communities", "project_execution_flows"),
            )
        }
        if len(available_tables) != 3:
            return {
                "status": "unavailable",
                "version": GRAPH_METRICS_VERSION,
                "snapshot_id": snapshot_id,
                "metric_count": 0,
                "communities": [],
                "cycles": [],
                "flows": [],
                "unknown_reason": "Optional graph metrics are unavailable until database migrations complete.",
            }
        communities = [
            {
                **dict_from_row(row),
                "summary": _json(row["summary_json"], {}),
            }
            for row in conn.execute(
                """
                SELECT * FROM project_graph_communities
                WHERE project_id = ? AND snapshot_id = ?
                ORDER BY node_count DESC, root_path
                """,
                (project_id, snapshot_id),
            ).fetchall()
        ]
        cycles = [
            dict_from_row(row)
            for row in conn.execute(
                """
                SELECT metrics.scc_id, MAX(metrics.scc_size) AS node_count,
                       GROUP_CONCAT(nodes.display_label, ' → ') AS labels
                FROM project_graph_metrics metrics
                JOIN code_nodes nodes ON nodes.id = metrics.node_id
                WHERE metrics.project_id = ? AND metrics.snapshot_id = ? AND metrics.is_cycle = 1
                GROUP BY metrics.scc_id ORDER BY node_count DESC, metrics.scc_id LIMIT 50
                """,
                (project_id, snapshot_id),
            ).fetchall()
        ]
        flows = [
            {
                **dict_from_row(row),
                "node_ids": _json(row["node_ids_json"], []),
                "relationships": _json(row["relationships_json"], []),
            }
            for row in conn.execute(
                """
                SELECT * FROM project_execution_flows
                WHERE project_id = ? AND snapshot_id = ? ORDER BY id LIMIT 50
                """,
                (project_id, snapshot_id),
            ).fetchall()
        ]
        metric_count = conn.execute(
            "SELECT COUNT(*) AS total FROM project_graph_metrics WHERE project_id = ? AND snapshot_id = ?",
            (project_id, snapshot_id),
        ).fetchone()["total"]
    if not metric_count and snapshot_id and refresh_missing:
        try:
            refresh_graph_intelligence(project_id)
            return get_graph_intelligence(project_id, refresh_missing=False)
        except Exception as exc:
            return {
                "status": "failed", "version": GRAPH_METRICS_VERSION, "snapshot_id": snapshot_id,
                "metric_count": 0, "communities": [], "cycles": [], "flows": [],
                "unknown_reason": f"Graph intelligence could not be built: {type(exc).__name__}: {str(exc)[:240]}",
            }
    return {
        "status": "ready" if metric_count else "not_built",
        "version": GRAPH_METRICS_VERSION,
        "snapshot_id": snapshot_id,
        "metric_count": int(metric_count or 0),
        "communities": communities,
        "cycles": cycles,
        "flows": flows,
    }


def _strongly_connected_components(
    ordered: list[str], adjacency: dict[str, list[str]], reverse: dict[str, list[str]]
) -> dict[str, str]:
    visited: set[str] = set()
    finish: list[str] = []
    for start in ordered:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node_id, expanded = stack.pop()
            if expanded:
                finish.append(node_id)
                continue
            if node_id in visited:
                continue
            visited.add(node_id)
            stack.append((node_id, True))
            for target in reversed(adjacency[node_id]):
                if target not in visited:
                    stack.append((target, False))
    result: dict[str, str] = {}
    for start in reversed(finish):
        if start in result:
            continue
        members: list[str] = []
        stack = [start]
        result[start] = "pending"
        while stack:
            node_id = stack.pop()
            members.append(node_id)
            for parent in reverse[node_id]:
                if parent not in result:
                    result[parent] = "pending"
                    stack.append(parent)
        stable = "scc-" + hashlib.sha256("\0".join(sorted(members)).encode("utf-8")).hexdigest()[:16]
        for node_id in members:
            result[node_id] = stable
    return result


def _communities(nodes: list[dict]) -> tuple[dict[str, str], dict[str, dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        path = str(node.get("relative_path") or "").replace("\\", "/").strip("/")
        parts = PurePosixPath(path).parts
        if not parts:
            root = "(project root)"
        elif parts[0] in {"apps", "packages", "services", "libs"} and len(parts) > 1:
            root = "/".join(parts[:2])
        else:
            root = parts[0]
        grouped[root].append(node)
    communities: dict[str, dict] = {}
    by_node: dict[str, str] = {}
    for root, members in sorted(grouped.items()):
        community_id = "community-" + hashlib.sha256(root.casefold().encode("utf-8")).hexdigest()[:16]
        kinds: dict[str, int] = defaultdict(int)
        paths = set()
        for node in members:
            kinds[str(node.get("kind") or "other")] += 1
            paths.add(str(node.get("relative_path") or ""))
            by_node[str(node["id"])] = community_id
        label = "Project root" if root == "(project root)" else root
        communities[community_id] = {
            "id": community_id,
            "label": label,
            "root_path": "" if root == "(project root)" else root,
            "node_count": len(members),
            "file_count": len(paths),
            "summary": {
                "primary_kinds": [name for name, _count in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))[:4]],
                "description": f"{label} contains {len(members)} indexed code items across {len(paths)} files.",
            },
        }
    return by_node, communities


def _execution_flows(
    nodes: list[dict], edge_rows: list[dict], metrics: dict[str, dict], entrypoints: list[str]
) -> list[dict]:
    node_by_id = {str(node["id"]): node for node in nodes}
    outgoing: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in edge_rows:
        edge_type = str(edge["edge_type"])
        if edge_type not in _FLOW_EDGES:
            continue
        source, target = str(edge["source_node_id"]), str(edge["target_node_id"])
        if source in node_by_id and target in node_by_id:
            outgoing[source].append((target, edge_type, str(edge["confidence_class"])))
    entrypoint_set = {str(path).replace("\\", "/") for path in entrypoints}
    starts = [
        str(node["id"])
        for node in nodes
        if str(node.get("relative_path") or "").replace("\\", "/") in entrypoint_set
        and str(node.get("kind") or "") in {"file", "module", "route", "function"}
    ]
    if not starts:
        starts = [
            str(node["id"])
            for node in nodes
            if str(node.get("kind") or "") == "route" and outgoing.get(str(node["id"]))
        ]
    starts = sorted(set(starts), key=lambda node_id: (-metrics[node_id]["pagerank"], node_id))[:20]
    flows: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for start in starts:
        path = [start]
        relationships: list[str] = []
        confidences: list[str] = []
        while len(path) < 6:
            choices = [item for item in outgoing.get(path[-1], []) if item[0] not in path]
            if not choices:
                break
            target, relationship, confidence = max(
                choices, key=lambda item: (metrics[item[0]]["pagerank"], item[1], item[0])
            )
            path.append(target)
            relationships.append(relationship)
            confidences.append(confidence)
        if len(path) < 2 or tuple(path) in seen:
            continue
        seen.add(tuple(path))
        stable = hashlib.sha256("\0".join(path).encode("utf-8")).hexdigest()[:20]
        flows.append({
            "id": f"flow-{stable}",
            "node_ids": path,
            "relationships": relationships,
            "confidence": "user_confirmed" if confidences and all(item == "user_confirmed" for item in confidences) else "extracted",
            "reason": "Bounded execution-flow candidate from an indexed entry point or route using "
                      + ", then ".join(item.replace("_", " ") for item in relationships) + ".",
        })
        if len(flows) >= 20:
            break
    return flows


def _publish_graph_layer(conn, project_id: str, snapshot_id: str, communities: dict, metrics: dict, flows: list, now: str) -> None:
    row = conn.execute(
        """
        SELECT * FROM project_intelligence_snapshots
        WHERE project_id = ? AND structure_snapshot_id = ?
        ORDER BY generated_at DESC LIMIT 1
        """,
        (project_id, snapshot_id),
    ).fetchone()
    if row is None:
        return
    architecture = _json(row["architecture_json"], {})
    architecture.update({
        "community_count": len(communities),
        "cycle_count": len({item["scc_id"] for item in metrics.values() if item["is_cycle"]}),
        "execution_flow_count": len(flows),
        "communities": [
            {"id": item["id"], "label": item["label"], "root_path": item["root_path"], "node_count": item["node_count"]}
            for item in sorted(communities.values(), key=lambda value: (-value["node_count"], value["root_path"]))[:20]
        ],
    })
    layers = _json(row["layer_states_json"], {})
    layers["graph_intelligence"] = {
        "status": "ready", "version": GRAPH_METRICS_VERSION, "generated_at": now,
        "truncated": False, "unknown_reason": None,
    }
    conn.execute(
        "UPDATE project_intelligence_snapshots SET architecture_json = ?, layer_states_json = ? WHERE id = ?",
        (json.dumps(architecture, sort_keys=True, separators=(",", ":")), json.dumps(layers, sort_keys=True, separators=(",", ":")), row["id"]),
    )


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, type(default)) else default
