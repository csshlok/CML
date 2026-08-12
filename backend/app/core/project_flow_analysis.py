from __future__ import annotations

import json

from backend.app.core.database import connect, dict_from_row
from backend.app.core.project_coverage import calculate_test_impact


_BOUNDARY_EDGE_TYPES = {
    "defines_route", "http_request", "dispatches_job", "sends_ipc", "handles_ipc",
    "emits_event", "listens_event", "reads_data", "writes_data", "raises_failure",
    "handles_failure",
}


def build_flow_analysis(
    project_id: str,
    snapshot_id: str,
    *,
    lens: str,
    flows: list[dict],
) -> dict:
    """Compose existing graph, metrics, coverage, decisions, and snapshots into one bounded view."""
    nodes = _selected_nodes(flows)
    node_ids = [node["id"] for node in nodes]
    paths = sorted({node["relative_path"] for node in nodes if node.get("relative_path")})
    observations: list[dict] = []
    limitations: list[str] = []

    with connect() as conn:
        metrics = _metrics(conn, project_id, snapshot_id, node_ids)
        boundaries = _boundaries(conn, project_id, snapshot_id, node_ids)
        decisions = _decisions(conn, project_id, paths)
        release = _release_delta(conn, project_id, snapshot_id, nodes)

    for boundary in boundaries[:12]:
        observations.append({
            "kind": "observed_boundary",
            "label": boundary["label"],
            "detail": f"{_human(boundary['edge_type'])} at {boundary['relative_path'] or 'project'}"
                      + (f":{boundary['source_line']}" if boundary.get("source_line") else ""),
            "confidence": boundary["confidence_class"],
            "paths": [boundary["relative_path"]] if boundary["relative_path"] else [],
        })

    hotspot = sorted(
        metrics.values(), key=lambda item: (-(item["in_degree"] + item["out_degree"]), -item["pagerank"])
    )
    for item in hotspot[:4]:
        if item["in_degree"] + item["out_degree"] < 2:
            continue
        observations.append({
            "kind": "coupling_signal",
            "label": item["label"],
            "detail": f"{item['in_degree']} incoming and {item['out_degree']} outgoing indexed relationships.",
            "confidence": "computed",
            "paths": [item["relative_path"]] if item["relative_path"] else [],
        })

    if lens in {"health", "impact"}:
        for item in metrics.values():
            if item["kind"] in {"function", "method", "class"} and item["in_degree"] == 0:
                observations.append({
                    "kind": "possible_unreferenced",
                    "label": item["label"],
                    "detail": "No incoming indexed relationship was observed. Dynamic or external callers may still exist.",
                    "confidence": "heuristic",
                    "paths": [item["relative_path"]] if item["relative_path"] else [],
                })

    for decision in decisions[:5]:
        observations.append({
            "kind": "architecture_decision",
            "label": decision["statement"],
            "detail": decision["rationale"] or "An active project decision governs this area.",
            "confidence": decision["confidence_class"],
            "paths": decision["paths"],
        })

    test_impact = calculate_test_impact(project_id, changed_paths=paths) if paths else {
        "status": "unknown", "exact_tests": [], "guessed_tests": [],
        "unknown_reason": "No source paths were selected by the flow.",
    }
    if lens == "tests" and test_impact.get("status") == "unknown":
        limitations.append(str(test_impact.get("unknown_reason") or "No coverage map is available."))
    if lens == "security":
        limitations.append(
            "This lens reports observed entrypoints and sinks; it does not claim a vulnerability or prove validation is absent."
        )
    if lens == "failure" and not any(
        item["edge_type"] in {"raises_failure", "handles_failure"} for item in boundaries
    ):
        limitations.append(
            "No explicit raise, catch, retry, or fallback boundary was observed on this path; runtime failures may still exist."
        )
    if lens == "health":
        limitations.append(
            "Unreferenced and coupling signals come from the indexed static graph; reflection and runtime wiring may not appear."
        )

    title = {
        "impact": "Change impact",
        "lineage": "Data lineage",
        "security": "Security boundaries",
        "failure": "Failure paths",
        "async": "Async boundaries",
        "tests": "Test relevance",
        "release": "Release comparison",
        "architecture": "Architecture context",
        "health": "Graph health",
        "documentation": "System walkthrough",
    }.get(lens, "Execution flow")
    return {
        "lens": lens,
        "title": title,
        "summary": _summary(lens, len(nodes), len(boundaries), len(observations)),
        "observations": observations[:20],
        "test_impact": test_impact,
        "release_change": release,
        "limitations": list(dict.fromkeys(limitations)),
    }


def _selected_nodes(flows: list[dict]) -> list[dict]:
    selected: dict[str, dict] = {}
    for flow in flows[:4]:
        for step in flow.get("steps") or []:
            node = step.get("node") or {}
            if node.get("id"):
                selected.setdefault(str(node["id"]), node)
    return list(selected.values())[:32]


def _metrics(conn, project_id: str, snapshot_id: str, node_ids: list[str]) -> dict[str, dict]:
    if not node_ids:
        return {}
    rows = conn.execute(
        f"""SELECT m.*, n.display_label AS label, n.relative_path, n.kind
            FROM project_graph_metrics m JOIN code_nodes n ON n.id = m.node_id
            WHERE m.project_id=? AND m.snapshot_id=?
              AND m.node_id IN ({','.join('?' for _ in node_ids)})""",
        [project_id, snapshot_id, *node_ids],
    ).fetchall()
    return {str(row["node_id"]): dict_from_row(row) for row in rows}


def _boundaries(conn, project_id: str, snapshot_id: str, node_ids: list[str]) -> list[dict]:
    if not node_ids:
        return []
    types = sorted(_BOUNDARY_EDGE_TYPES)
    rows = conn.execute(
        f"""SELECT e.edge_type, e.source_line, e.confidence_class,
                   COALESCE(target.display_label, source.display_label) AS label,
                   COALESCE(source.relative_path, target.relative_path, '') AS relative_path
            FROM code_edges e
            LEFT JOIN code_nodes source ON source.id=e.source_node_id
            LEFT JOIN code_nodes target ON target.id=e.target_node_id
            WHERE e.project_id=? AND e.snapshot_id=?
              AND (e.source_node_id IN ({','.join('?' for _ in node_ids)})
                   OR e.target_node_id IN ({','.join('?' for _ in node_ids)}))
              AND e.edge_type IN ({','.join('?' for _ in types)})
            ORDER BY e.edge_type, e.id LIMIT 24""",
        [project_id, snapshot_id, *node_ids, *node_ids, *types],
    ).fetchall()
    return [dict_from_row(row) for row in rows]


def _decisions(conn, project_id: str, paths: list[str]) -> list[dict]:
    if not paths:
        return []
    rows = conn.execute(
        """SELECT statement, rationale, governed_paths_json, confidence_class
           FROM project_decisions WHERE project_id=? AND status='active'
           ORDER BY updated_at DESC LIMIT 30""",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        try:
            decoded = json.loads(row["governed_paths_json"] or "[]")
        except (TypeError, ValueError):
            decoded = []
        governed = [str(value).replace("\\", "/") for value in decoded if isinstance(value, str)]
        matched = [path for path in paths if any(_path_matches(path, rule) for rule in governed)]
        if matched:
            result.append({**dict_from_row(row), "paths": matched[:6]})
    return result


def _release_delta(conn, project_id: str, snapshot_id: str, nodes: list[dict]) -> dict:
    previous = conn.execute(
        """SELECT id, git_commit, created_at FROM project_snapshots
           WHERE project_id=? AND id<>? AND structure_status IN ('ready', 'partial')
           ORDER BY created_at DESC LIMIT 1""",
        (project_id, snapshot_id),
    ).fetchone()
    if previous is None or not nodes:
        return {"status": "unknown", "changed": [], "unchanged": [], "previous_snapshot_id": None}
    qualified = [str(node["qualified_id"]) for node in nodes]
    old_rows = conn.execute(
        f"SELECT qualified_id, content_hash FROM code_nodes WHERE snapshot_id=? AND qualified_id IN ({','.join('?' for _ in qualified)})",
        [previous["id"], *qualified],
    ).fetchall()
    old = {str(row["qualified_id"]): str(row["content_hash"]) for row in old_rows}
    current_rows = conn.execute(
        f"SELECT qualified_id, content_hash FROM code_nodes WHERE snapshot_id=? AND qualified_id IN ({','.join('?' for _ in qualified)})",
        [snapshot_id, *qualified],
    ).fetchall()
    current = {str(row["qualified_id"]): str(row["content_hash"]) for row in current_rows}
    changed, unchanged = [], []
    for node in nodes:
        key = str(node["qualified_id"])
        if key in old and old[key] == current.get(key):
            unchanged.append(key)
        else:
            changed.append(key)
    return {
        "status": "ready", "changed": changed[:20], "unchanged": unchanged[:20],
        "previous_snapshot_id": str(previous["id"]), "previous_commit": previous["git_commit"],
    }


def _path_matches(path: str, rule: str) -> bool:
    path_value = path.replace("\\", "/").strip("/")
    rule_value = rule.replace("\\", "/").strip("/")
    return bool(rule_value) and (path_value == rule_value or path_value.startswith(rule_value + "/"))


def _human(value: str) -> str:
    return value.replace("_", " ")


def _summary(lens: str, nodes: int, boundaries: int, observations: int) -> str:
    if not nodes:
        return "No verified path was available for this lens."
    return (
        f"This {lens} lens connects {nodes} indexed components, "
        f"{boundaries} observed boundaries, and {observations} supporting signals."
    )
