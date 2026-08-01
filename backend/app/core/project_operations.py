from __future__ import annotations

import re
import json
from pathlib import Path

from backend.app.core.database import connect, dict_from_row
from backend.app.core.project_coverage import calculate_test_impact, get_project_coverage
from backend.app.core.project_decisions import list_project_decisions, refresh_project_decisions
from backend.app.core.project_git_intelligence import get_project_repository_state, refresh_git_intelligence
from backend.app.core.project_graph import find_nodes, graph_view
from backend.app.core.project_graph_intelligence import get_graph_intelligence, refresh_graph_intelligence
from backend.app.core.project_intelligence import get_project_intelligence
from backend.app.core.projects import inspect_project_changes


OPERATION_VERSION = "odin-project-operations-v1"
OPERATIONS = {"overview", "code_context", "project_state", "change_context", "blast_radius", "decisions", "coverage"}
_STATE_PATTERNS = (
    re.compile(r"\b(git|branch|head|working tree|worktree|uncommitted|staged|unstaged|dirty|status)\b", re.I),
    re.compile(r"\bwhat (?:has )?changed\b", re.I),
)


def route_project_intent(query: str, *, project_id: str | None) -> dict:
    """Route only when the caller has explicitly supplied a valid project scope."""
    if not project_id:
        return {"operation": None, "confidence": "none", "reason": "project_scope_required"}
    value = str(query).strip()
    if any(pattern.search(value) for pattern in _STATE_PATTERNS):
        return {"operation": "project_state", "confidence": "typed", "reason": "live_repository_state_language"}
    if re.search(r"\b(blast radius|impact of|what (?:uses|depends on)|downstream)\b", value, re.I):
        return {"operation": "blast_radius", "confidence": "typed", "reason": "dependency_impact_language"}
    if re.search(r"\b(decision|rationale|trade[ -]?off|why did we)\b", value, re.I):
        return {"operation": "decisions", "confidence": "typed", "reason": "decision_language"}
    if re.search(r"\b(test impact|which tests|coverage|covered lines?)\b", value, re.I):
        return {"operation": "coverage", "confidence": "typed", "reason": "test_coverage_language"}
    return {"operation": None, "confidence": "none", "reason": "use_code_retrieval"}


def run_project_operation(project_id: str, operation: str, *, query: str = "", target: str = "",
                          targets: list[str] | None = None,
                          changed_paths: list[str] | None = None, changed_lines: dict[str, list[int]] | None = None,
                          compact: bool = True) -> dict:
    if operation not in OPERATIONS: raise ValueError(f"Unsupported project operation: {operation}")
    target_values = list(dict.fromkeys([value.strip() for value in (targets or []) if value.strip()]))
    if operation == "blast_radius" and len(target_values) > 1:
        data = {"targets": [run_project_operation(project_id, operation, target=value, compact=compact)["data"] for value in target_values],
                "batched": True}
    elif operation == "overview":
        intelligence = get_project_intelligence(project_id)
        graph = get_graph_intelligence(project_id)
        data = {"synopsis": intelligence["interpretation"].get("deterministic_synopsis"),
                "identity": intelligence["identity"], "architecture": intelligence["architecture"],
                "freshness": intelligence["freshness"], "layers": intelligence["layers"],
                "key_areas": graph.get("communities", [])[:6], "execution_flows": graph.get("flows", [])[:5],
                "evidence": intelligence.get("evidence", [])[:8]}
    elif operation == "project_state": data = get_project_repository_state(project_id)
    elif operation == "change_context":
        changes = inspect_project_changes(project_id, max_paths=5000)
        state = get_project_repository_state(project_id)
        paths = list(changes.get("changed_paths") or [item["relative_path"] for item in state.get("live_state", {}).get("files", [])])
        data = {"changes": changes, "repository_state": state, "files": _change_details(project_id, paths),
                "test_impact": calculate_test_impact(project_id, changed_paths=paths),
                "unknowns": _change_unknowns(state)}
    elif operation == "blast_radius":
        target = target or (target_values[0] if target_values else "")
        if not target: raise ValueError("blast_radius requires a target symbol or path.")
        candidates = find_nodes(project_id, target, limit=8)
        if not candidates: data = {"status": "not_found", "target": target, "candidates": []}
        elif len(candidates) > 1 and not any(target == value.get("qualified_id") for value in candidates):
            data = {"status": "ambiguous", "target": target, "candidates": candidates}
        else:
            chosen = next((item for item in candidates if target == item.get("qualified_id")), candidates[0])
            view = graph_view(project_id, mode="graph", root=chosen["qualified_id"], query=target,
                              direction="inbound", max_depth=3, max_nodes=160)
            impacted_paths = sorted({node.get("relative_path") for node in view["nodes"] if node.get("relative_path")})
            data = {"status": "found", "target": chosen, "graph": view,
                    "test_impact": calculate_test_impact(project_id, changed_paths=impacted_paths)}
    elif operation == "decisions": data = list_project_decisions(project_id)
    elif operation == "coverage": data = (calculate_test_impact(project_id, changed_paths=changed_paths or [], changed_lines=changed_lines)
                                                   if changed_paths else get_project_coverage(project_id))
    else:
        candidates = []
        for term in _query_terms(query)[:6]:
            candidates.extend(find_nodes(project_id, term, limit=4))
        unique = {item["id"]: item for item in candidates}
        data = {"query": query, "structural_hits": list(unique.values())[:12],
                "next_step": "Use the project context endpoint for source excerpts and citations."}
    return {"version": OPERATION_VERSION, "project_id": project_id, "operation": operation,
            "display": "compact" if compact else "expanded", "data": data}


def refresh_project_intelligence_layers(project_id: str) -> dict:
    """Refresh independent layers; one unavailable optional layer cannot invalidate the active index."""
    outcomes = {}
    for name, callback in (("graph", refresh_graph_intelligence), ("git", refresh_git_intelligence),
                           ("decisions", refresh_project_decisions)):
        try: outcomes[name] = {"status": "ready", "result": callback(project_id)}
        except Exception as exc:  # optional derived layer boundary
            outcomes[name] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return outcomes


def enqueue_project_intelligence_layers(project_id: str, *, layers: list[str] | None = None,
                                        artifact_path: str = "", user_initiated: bool = False) -> dict:
    """Queue coalesced snapshot-bound refreshes while retaining every currently healthy layer."""
    from backend.app.core.background_jobs import enqueue_job, wake_background_worker

    mapping = {
        "overview": "project_intelligence_overview", "graph": "project_graph_metrics",
        "git": "project_git_intelligence", "decisions": "project_decision_refresh",
        "coverage": "project_coverage_ingest",
    }
    selected = list(dict.fromkeys(layers or ["graph", "git", "decisions"]))
    unknown = [layer for layer in selected if layer not in mapping]
    if unknown: raise ValueError(f"Unsupported intelligence layer: {unknown[0]}")
    if "coverage" in selected and not artifact_path:
        raise ValueError("Coverage refresh requires an LCOV artifact path.")
    with connect() as conn:
        project = conn.execute(
            "SELECT active_manifest_snapshot_id, active_snapshot_id FROM projects WHERE id=? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None: raise KeyError(project_id)
        snapshot_id = project["active_manifest_snapshot_id"] or project["active_snapshot_id"] or "unindexed"
        jobs = []
        for layer in selected:
            payload = {"project_id": project_id, "snapshot_id": snapshot_id}
            if layer == "coverage": payload["artifact_path"] = artifact_path
            artifact_key = ""
            if artifact_path:
                try:
                    stat = Path(artifact_path).resolve().stat()
                    artifact_key = f":{stat.st_size}:{stat.st_mtime_ns}"
                except OSError:
                    artifact_key = ":missing"
            jobs.append(enqueue_job(
                conn, job_type=mapping[layer], payload=payload,
                dedupe_key=f"{mapping[layer]}:{project_id}:{snapshot_id}{artifact_key}",
                scope_id=project_id, user_initiated=user_initiated,
            ))
    wake_background_worker()
    return {"project_id": project_id, "snapshot_id": snapshot_id, "jobs": jobs, "queued_layers": selected}


def _query_terms(query: str) -> list[str]:
    stop = {"about", "code", "does", "explain", "find", "from", "how", "project", "show", "that", "the", "this", "what", "where", "which", "with"}
    return [term for term in re.findall(r"[A-Za-z_][A-Za-z0-9_.:/-]{2,}", query) if term.casefold() not in stop]


def _change_details(project_id: str, paths: list[str]) -> list[dict]:
    normalized = [str(path).replace("\\", "/") for path in paths[:500]]
    if not normalized: return []
    with connect() as conn:
        project = conn.execute("SELECT active_structure_snapshot_id, active_snapshot_id FROM projects WHERE id=?", (project_id,)).fetchone()
        snapshot = project["active_structure_snapshot_id"] or project["active_snapshot_id"]
        git = conn.execute("SELECT id FROM project_git_snapshots WHERE project_id=? ORDER BY generated_at DESC LIMIT 1", (project_id,)).fetchone()
        items = []
        for path in normalized:
            nodes = conn.execute(
                """SELECT n.id, n.display_label, m.community_id, m.community_label FROM code_nodes n
                LEFT JOIN project_graph_metrics m ON m.node_id=n.id AND m.snapshot_id=n.snapshot_id
                WHERE n.project_id=? AND n.snapshot_id=? AND n.relative_path=? ORDER BY n.kind='file' DESC, n.start_line LIMIT 20""",
                (project_id, snapshot, path),
            ).fetchall()
            node_ids = [row["id"] for row in nodes]
            dependents = []
            if node_ids:
                dependents = [dict_from_row(row) for row in conn.execute(
                    f"""SELECT DISTINCT source.relative_path, e.edge_type, e.confidence_class
                    FROM code_edges e JOIN code_nodes source ON source.id=e.source_node_id
                    WHERE e.project_id=? AND e.snapshot_id=? AND e.target_node_id IN ({','.join('?' for _ in node_ids)})
                    AND e.edge_type IN ('imports','calls','references','exports') ORDER BY source.relative_path LIMIT 30""",
                    [project_id, snapshot, *node_ids],
                )]
            cochange = [dict_from_row(row) for row in conn.execute(
                """SELECT CASE WHEN source_path=? THEN target_path ELSE source_path END AS relative_path,
                touch_count, confidence_class, heuristic_label FROM project_cochange_edges
                WHERE git_snapshot_id=? AND (source_path=? OR target_path=?) ORDER BY touch_count DESC LIMIT 20""",
                (path, git["id"] if git else "", path, path),
            )] if git else []
            communities = sorted({row["community_label"] for row in nodes if row["community_label"]})
            reasons = ["Changed in the current repository state"]
            if dependents: reasons.append(f"{len(dependents)} structurally dependent file(s)")
            if cochange: reasons.append(f"{len(cochange)} historical co-change partner(s), not dependencies")
            items.append({"relative_path": path, "why_included": reasons, "communities": communities,
                          "structural_dependents": dependents, "cochange_partners": cochange})
    return items


def _change_unknowns(state: dict) -> list[str]:
    unknowns = []
    if state.get("status") != "ready": unknowns.append("Git history is unavailable.")
    if state.get("history_truncated"): unknowns.append("Git history was bounded; older co-change evidence is not included.")
    if state.get("shallow_history"): unknowns.append("This is a shallow clone, so history-derived signals are incomplete.")
    return unknowns
