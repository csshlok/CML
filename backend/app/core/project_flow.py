from __future__ import annotations

import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass

from backend.app.core.cluster_bundle import build_cluster_bundle_context
from backend.app.core.database import connect, dict_from_row
from backend.app.core.encrypted_storage import load_source_content_fields
from backend.app.core.project_graph import GraphQueryError
from backend.app.core.project_flow_analysis import build_flow_analysis


FLOW_VERSION = 2
FLOW_MAX_STEPS = 8
FLOW_MAX_CANDIDATE_NODES = 160
FLOW_MAX_EXAMINED_EDGES = 800
FLOW_MAX_ALTERNATIVES = 3
FLOW_TIMEOUT_MS = 500
FLOW_CANDIDATE_TIMEOUT_MS = 350
FLOW_RETRIEVAL_TIMEOUT_MS = 300

_EXECUTION_EDGES = {"calls", "dispatches", "http_request", "dispatches_job", "sends_ipc", "emits_event"}
_ENTRY_EDGES = {"defines_route", "handles_ipc", "listens_event", "reads_data", "handles_failure"}
_SUPPORTING_EDGES = {
    "uses_schema", "configured_by", "registers_router", "imports", "reads_data",
    "writes_data", "raises_failure", "tested_by",
}
_RETRIEVAL_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="odin-flow-retrieval")
_RETRIEVAL_CAPACITY = threading.BoundedSemaphore(4)
_QUERY_STOPWORDS = {
    "a", "an", "and", "architecture", "code", "codebase", "diagram", "does", "explain",
    "flow", "for", "from", "how", "in", "is", "it", "map", "me", "of", "project",
    "show", "system", "the", "this", "through", "to", "trace", "visualize", "what", "where",
    "with", "work", "works", "into", "throughout", "executes", "produces", "reaches",
    "data", "stored", "component", "function", "method", "file",
    "api", "request", "requests",
    "change", "changes", "affect", "affected", "coverage", "test", "tests",
    "can", "while", "processed", "process", "fail", "failure", "error", "exception",
    "fallback", "retry", "recover", "recovery",
}

_LENS_PATTERNS = (
    ("impact", re.compile(r"\b(impact|blast radius|depends on|affect|affected|changes?|downstream)\b", re.I)),
    ("lineage", re.compile(r"\b(data lineage|lineage|stored|database|persist|read|write|transform)\b", re.I)),
    ("security", re.compile(r"\b(security|untrusted|validate|authorize|authentication|permission|secret|sensitive)\b", re.I)),
    ("failure", re.compile(r"\b(fail|failure|error|exception|fallback|retry|rollback|recover|cancel)\b", re.I)),
    ("async", re.compile(r"\b(async|background|job|queue|event|ipc|worker|spawn)\b", re.I)),
    ("tests", re.compile(r"\b(test|tests|coverage|covered)\b", re.I)),
    ("release", re.compile(r"\b(release|version|snapshot|regression|since|previous)\b", re.I)),
    ("architecture", re.compile(r"\b(architecture|drift|decision|module|router|registration)\b", re.I)),
    ("health", re.compile(r"\b(dead code|unused|unreferenced|coupling|hotspot|cycle)\b", re.I)),
    ("documentation", re.compile(r"\b(document|documentation|onboard|walkthrough)\b", re.I)),
)


@dataclass(frozen=True)
class _Transition:
    edge: dict
    source: str
    target: str
    display_reversed: bool = False


def project_flow_view(
    project_id: str,
    *,
    query: str,
    max_steps: int = FLOW_MAX_STEPS,
    max_candidate_nodes: int = FLOW_MAX_CANDIDATE_NODES,
    max_examined_edges: int = FLOW_MAX_EXAMINED_EDGES,
    timeout_ms: int = FLOW_TIMEOUT_MS,
) -> dict:
    """Build a bounded, evidence-backed explanation over active Odin snapshots."""
    normalized_query = " ".join(str(query or "").split()).strip()
    if not normalized_query:
        raise GraphQueryError("A flow question is required.")
    step_limit = max(2, min(int(max_steps), FLOW_MAX_STEPS))
    node_limit = max(20, min(int(max_candidate_nodes), FLOW_MAX_CANDIDATE_NODES))
    edge_limit = max(50, min(int(max_examined_edges), FLOW_MAX_EXAMINED_EDGES))
    traversal_budget_ms = max(50, min(int(timeout_ms), 2_000))
    started = time.perf_counter()
    lens = _flow_lens(normalized_query)

    with connect() as conn:
        project_row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)
        ).fetchone()
        if project_row is None:
            raise KeyError(project_id)
        project = dict_from_row(project_row)
        structure_snapshot_id = str(
            project.get("active_structure_snapshot_id") or project.get("active_snapshot_id") or ""
        )
        retrieval_snapshot_id = str(
            project.get("active_retrieval_snapshot_id") or project.get("active_snapshot_id") or ""
        )
        if not structure_snapshot_id:
            raise GraphQueryError("Project has no active structure snapshot.")

    retrieval_evidence, retrieval_warning, retrieval_ms = _retrieve_semantic_evidence(
        project, normalized_query, timeout_ms=FLOW_RETRIEVAL_TIMEOUT_MS,
    )

    with connect() as conn:
        (
            candidates,
            candidate_scores,
            candidate_reasons,
            anchor_order,
            candidate_ms,
            candidate_timed_out,
        ) = _find_flow_candidates(
            conn,
            project_id=project_id,
            snapshot_id=structure_snapshot_id,
            query=normalized_query,
            evidence=retrieval_evidence,
            limit=min(node_limit, 72),
            timeout_ms=FLOW_CANDIDATE_TIMEOUT_MS,
        )

        candidate_payloads = [
            {
                **_public_node(node),
                "match_score": round(candidate_scores[str(node["id"])], 3),
                "match_reasons": sorted(candidate_reasons.get(str(node["id"]), set())),
            }
            for node in candidates[:8]
        ]

        if not candidates:
            return _empty_result(
                project,
                normalized_query,
                structure_snapshot_id,
                retrieval_snapshot_id,
                status="not_found",
                candidates=[],
                warnings=[
                    *([retrieval_warning] if retrieval_warning else []),
                    "No indexed symbol or source matched this flow question.",
                ],
                started=started,
                limits=_limits(
                    step_limit, node_limit, edge_limit, traversal_budget_ms,
                    FLOW_CANDIDATE_TIMEOUT_MS, FLOW_RETRIEVAL_TIMEOUT_MS,
                ),
                lens=lens,
                diagnostics={
                    "retrieval_ms": retrieval_ms,
                    "candidate_ms": candidate_ms,
                    "traversal_ms": 0.0,
                    "candidate_timed_out": candidate_timed_out,
                },
            )

        ambiguous = len(candidates) > 1 and (
            candidate_scores[str(candidates[0]["id"])]
            - candidate_scores[str(candidates[1]["id"])]
            < 4.0
        )
        traversal_started = time.perf_counter()
        flows, examined_edges, timed_out = _build_ranked_flows(
            conn,
            project_id=project_id,
            snapshot_id=structure_snapshot_id,
            seeds=candidates[:8],
            candidate_scores=candidate_scores,
            anchor_order=anchor_order,
            query=normalized_query,
            lens=lens,
            max_steps=step_limit,
            max_nodes=node_limit,
            max_edges=edge_limit,
            timeout_ms=traversal_budget_ms,
            started=traversal_started,
        )
        traversal_ms = round((time.perf_counter() - traversal_started) * 1000, 3)
        evidence_by_source = _evidence_by_source(retrieval_evidence)
        source_ids = list(dict.fromkeys(
            str(node.get("source_id") or "")
            for flow in flows
            for node in flow["nodes"]
            if str(node.get("source_id") or "")
        ))[:12]
        source_semantics = _load_source_semantics(conn, project, source_ids)

    public_flows = [
        _public_flow(
            flow,
            lens=lens,
            source_semantics=source_semantics,
            evidence_by_source=evidence_by_source,
        )
        for flow in flows[: FLOW_MAX_ALTERNATIVES + 1]
    ]
    analysis = build_flow_analysis(
        project_id, structure_snapshot_id, lens=lens, flows=public_flows,
    )
    warnings = [warning for warning in [retrieval_warning] if warning]
    if candidate_timed_out:
        warnings.append("Candidate search reached its time limit; the strongest indexed matches were retained.")
    changed_count = int(project.get("changed_file_count") or 0)
    stale = changed_count > 0 or str(project.get("structure_status") or "") == "stale"
    if stale:
        warnings.append(
            f"Based on the last indexed snapshot; {changed_count} local "
            f"{'file has' if changed_count == 1 else 'files have'} changed."
        )
    if timed_out:
        warnings.append("Flow traversal reached its time limit and returned the best bounded result.")
    if not public_flows:
        warnings.append("Relevant components were found, but no verified execution path connects them.")

    if ambiguous and not public_flows:
        status = "ambiguous"
    elif public_flows and (stale or timed_out):
        status = "partial"
    elif public_flows:
        status = "found"
    else:
        status = "partial"
    return {
        "version": FLOW_VERSION,
        "project_id": project_id,
        "query": normalized_query,
        "lens": lens,
        "status": status,
        "structure_snapshot_id": structure_snapshot_id,
        "retrieval_snapshot_id": retrieval_snapshot_id,
        "indexed_commit": project.get("indexed_commit"),
        "primary_flow": public_flows[0] if public_flows else None,
        "alternatives": public_flows[1 : FLOW_MAX_ALTERNATIVES + 1],
        "candidates": candidate_payloads,
        "analysis": analysis,
        "freshness": {
            "structure_status": str(project.get("structure_status") or "unknown"),
            "retrieval_status": str(project.get("retrieval_status") or "unknown"),
            "changed_file_count": changed_count,
            "includes_unindexed_changes": False,
        },
        "warnings": warnings,
        "limits": _limits(
            step_limit, node_limit, edge_limit, traversal_budget_ms,
            FLOW_CANDIDATE_TIMEOUT_MS, FLOW_RETRIEVAL_TIMEOUT_MS,
        ),
        "diagnostics": {
            "candidate_nodes": len(candidates),
            "examined_edges": examined_edges,
            "retrieval_ms": retrieval_ms,
            "candidate_ms": candidate_ms,
            "traversal_ms": traversal_ms,
            "candidate_timed_out": candidate_timed_out,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }


def project_flow_markdown(view: dict) -> str:
    lines = [
        "# Odin Semantic Flow",
        "",
        f"Question: {view.get('query') or 'Project flow'}",
        f"Status: {view.get('status') or 'unknown'}",
        f"Indexed commit: {view.get('indexed_commit') or 'folder snapshot'}",
        "",
    ]
    flow = view.get("primary_flow")
    if not flow:
        lines.extend(["No verified execution flow was found.", ""])
    else:
        lines.extend([f"## {flow['title']}", ""])
        for step in flow.get("steps") or []:
            node = step["node"]
            location = node.get("relative_path") or "project"
            if node.get("start_line"):
                location += f":{node['start_line']}"
            lines.append(f"{step['ordinal']}. **{node['label']}** — {step['role_summary']} ({location})")
            connection = step.get("connection_to_next")
            if connection:
                lines.append(
                    f"   - {connection['label']}; {connection['confidence']} confidence"
                    + (f" at line {connection['source_line']}" if connection.get("source_line") else "")
                )
    warnings = view.get("warnings") or []
    analysis = view.get("analysis") or {}
    observations = analysis.get("observations") or []
    if observations:
        lines.extend(["", f"## {analysis.get('title') or 'Supporting signals'}", ""])
        lines.extend(
            f"- **{item.get('label') or 'Signal'}** — {item.get('detail') or ''}"
            for item in observations
        )
    if warnings:
        lines.extend(["", "## Limitations", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines).strip() + "\n"


def _retrieve_semantic_evidence(
    project: dict, query: str, *, timeout_ms: int,
) -> tuple[list[dict], str, float]:
    started = time.perf_counter()
    if not _RETRIEVAL_CAPACITY.acquire(blocking=False):
        return [], "Semantic retrieval is busy; this flow uses indexed structure only.", 0.0
    future = _RETRIEVAL_EXECUTOR.submit(_build_flow_retrieval, project, query)
    future.add_done_callback(lambda _future: _RETRIEVAL_CAPACITY.release())
    try:
        evidence = future.result(timeout=max(0.05, timeout_ms / 1000))
        return evidence, "", round((time.perf_counter() - started) * 1000, 3)
    except FutureTimeoutError:
        future.cancel()
        return (
            [],
            "Semantic retrieval exceeded its time budget; this flow uses indexed structure only.",
            round((time.perf_counter() - started) * 1000, 3),
        )
    except Exception:
        # Flow remains structurally useful when embeddings or optional derived state are unavailable.
        return (
            [],
            "Semantic retrieval was unavailable; this flow uses indexed structure only.",
            round((time.perf_counter() - started) * 1000, 3),
        )


def _build_flow_retrieval(project: dict, query: str) -> list[dict]:
    bundle = build_cluster_bundle_context(
        vault_id=str(project["vault_id"]),
        cluster_id=str(project.get("primary_cluster_id") or "") or None,
        query=query,
        token_budget=8,
        mode="context",
    )
    return [
        item for item in (bundle.get("evidence") or [])
        if str(item.get("source_id") or "")
    ][:8]


def _find_flow_candidates(
    conn,
    *,
    project_id: str,
    snapshot_id: str,
    query: str,
    evidence: list[dict],
    limit: int,
    timeout_ms: int,
) -> tuple[list[dict], dict[str, float], dict[str, set[str]], dict[str, int], float, bool]:
    started = time.perf_counter()
    terms = _query_terms(query)
    scores: dict[str, float] = {}
    reasons: dict[str, set[str]] = {}
    anchor_order: dict[str, int] = {}
    rows_by_id: dict[str, dict] = {}
    timed_out = False

    if terms:
        exact_rows = conn.execute(
            f"""
            SELECT n.*, COALESCE(pss.file_role, 'source') AS file_role,
                   COALESCE(metrics.pagerank, 0) AS pagerank
            FROM code_nodes n
            LEFT JOIN project_snapshot_sources pss
              ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
            LEFT JOIN project_graph_metrics metrics
              ON metrics.project_id = n.project_id AND metrics.snapshot_id = n.snapshot_id
             AND metrics.node_id = n.id
            WHERE n.project_id = ? AND n.snapshot_id = ?
              AND n.display_label COLLATE NOCASE IN ({','.join('?' for _ in terms)})
            ORDER BY n.qualified_id LIMIT ?
            """,
            [project_id, snapshot_id, *[term.casefold() for term in terms], limit],
        ).fetchall()
        term_positions = {term.casefold(): index for index, term in enumerate(terms)}
        for row in exact_rows:
            node = dict_from_row(row)
            node_id = str(node["id"])
            position = term_positions.get(str(node["display_label"]).casefold(), len(terms))
            rows_by_id[node_id] = node
            scores[node_id] = 240.0 - (position * 18.0)
            reasons.setdefault(node_id, set()).add("Exact symbol match")
            anchor_order[node_id] = position

    signal_terms = sorted(
        terms,
        key=lambda term: (
            -int("_" in term or "-" in term or any(char.isupper() for char in term)),
            -len(term),
            terms.index(term),
        ),
    )[:2]
    if signal_terms and len(rows_by_id) < limit and (time.perf_counter() - started) * 1000 < timeout_ms:
        clauses = []
        params: list[object] = [project_id, snapshot_id]
        for term in signal_terms:
            wildcard = f"%{term}%"
            clauses.append("(n.display_label LIKE ? OR n.qualified_id LIKE ? OR n.relative_path LIKE ?)")
            params.extend([wildcard, wildcard, wildcard])
        params.append(min(48, limit))
        deadline = started + timeout_ms / 1000
        conn.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 2_000)
        try:
            rows = conn.execute(
                f"""
                SELECT n.*, COALESCE(pss.file_role, 'source') AS file_role,
                       COALESCE(metrics.pagerank, 0) AS pagerank
                FROM code_nodes n
                LEFT JOIN project_snapshot_sources pss
                  ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
                LEFT JOIN project_graph_metrics metrics
                  ON metrics.project_id = n.project_id AND metrics.snapshot_id = n.snapshot_id
                 AND metrics.node_id = n.id
                WHERE n.project_id = ? AND n.snapshot_id = ? AND ({' OR '.join(clauses)})
                ORDER BY CASE WHEN n.display_label COLLATE NOCASE IN ({','.join('?' for _ in signal_terms)})
                              THEN 0 ELSE 1 END,
                         length(n.display_label), n.qualified_id
                LIMIT ?
                """,
                [*params[:-1], *[term.casefold() for term in signal_terms], params[-1]],
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "interrupted" not in str(exc).casefold():
                raise
            rows = []
            timed_out = True
        finally:
            conn.set_progress_handler(None, 0)
        for rank, row in enumerate(rows):
            node = dict_from_row(row)
            node_id = str(node["id"])
            rows_by_id.setdefault(node_id, node)
            lexical = max(
                _lexical_score(node, term, term_index=terms.index(term), rank=rank)
                for term in signal_terms
            )
            scores[node_id] = max(scores.get(node_id, float("-inf")), lexical)
            for term in signal_terms:
                if _node_matches_term(node, term):
                    reasons.setdefault(node_id, set()).add(f"Matched {term}")

    semantic_nodes = _semantic_candidate_nodes(
        conn,
        project_id=project_id,
        snapshot_id=snapshot_id,
        evidence=evidence,
        limit=min(24, limit),
    )
    for rank, node in enumerate(semantic_nodes):
        node_id = str(node["id"])
        rows_by_id.setdefault(node_id, node)
        scores[node_id] = scores.get(node_id, 0.0) + max(38.0 - rank, 12.0)
        reasons.setdefault(node_id, set()).add("Matched semantic project evidence")

    candidates = list(rows_by_id.values())
    for node in candidates:
        scores[str(node["id"])] = (
            scores.get(str(node["id"]), 0.0)
            + _candidate_bonus(node)
            + _candidate_phrase_bonus(node, query)
        )
    candidates.sort(key=lambda node: (-scores[str(node["id"])], str(node["qualified_id"])))
    for node in candidates:
        node_id = str(node["id"])
        if node_id in anchor_order:
            continue
        matching_positions = [index for index, term in enumerate(terms) if _node_matches_term(node, term)]
        if matching_positions:
            anchor_order[node_id] = min(matching_positions)
    return (
        candidates[:limit], scores, reasons, anchor_order,
        round((time.perf_counter() - started) * 1000, 3), timed_out,
    )


def _semantic_candidate_nodes(conn, *, project_id: str, snapshot_id: str, evidence: list[dict], limit: int) -> list[dict]:
    if not evidence:
        return []
    source_ids = list(dict.fromkeys(str(item.get("source_id") or "") for item in evidence))[:8]
    evidence_ranges = []
    for item in evidence:
        source_id = str(item.get("source_id") or "")
        line_start = item.get("line_start")
        if not source_id or line_start is None:
            continue
        start = max(1, int(line_start))
        evidence_ranges.append((source_id, start, max(start, int(item.get("line_end") or start))))

    selected: dict[str, dict] = {}
    if evidence_ranges:
        range_clauses = [
            "(n.source_id = ? AND n.start_line <= ? AND COALESCE(n.end_line, n.start_line) >= ?)"
            for _ in evidence_ranges
        ]
        range_params = [value for source_id, start, end in evidence_ranges for value in (source_id, end, start)]
        rows = conn.execute(
            f"""
            SELECT n.*, COALESCE(pss.file_role, 'source') AS file_role
            FROM code_nodes n
            LEFT JOIN project_snapshot_sources pss
              ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
            WHERE n.project_id = ? AND n.snapshot_id = ?
              AND ({' OR '.join(range_clauses)})
            ORDER BY CASE n.kind WHEN 'route' THEN 0 WHEN 'function' THEN 1 WHEN 'method' THEN 2
                                  WHEN 'class' THEN 3 WHEN 'file' THEN 4 ELSE 5 END,
                     n.start_line, n.qualified_id
            LIMIT ?
            """,
            [project_id, snapshot_id, *range_params, limit],
        ).fetchall()
        selected.update((str(row["id"]), dict_from_row(row)) for row in rows)

    fallback_limit = max(0, limit - len(selected))
    if fallback_limit:
        rows = conn.execute(
            f"""
            SELECT n.*, COALESCE(pss.file_role, 'source') AS file_role
            FROM code_nodes n
            LEFT JOIN project_snapshot_sources pss
              ON pss.snapshot_id = n.snapshot_id AND pss.relative_path = n.relative_path
            WHERE n.project_id = ? AND n.snapshot_id = ?
              AND n.source_id IN ({','.join('?' for _ in source_ids)})
            ORDER BY CASE n.kind WHEN 'route' THEN 0 WHEN 'function' THEN 1 WHEN 'method' THEN 2
                                  WHEN 'class' THEN 3 WHEN 'file' THEN 4 ELSE 5 END,
                     n.start_line, n.qualified_id
            LIMIT ?
            """,
            [project_id, snapshot_id, *source_ids, fallback_limit + len(selected)],
        ).fetchall()
        for row in rows:
            if len(selected) >= limit:
                break
            selected.setdefault(str(row["id"]), dict_from_row(row))

    evidence_by_source = _evidence_by_source(evidence)
    ranked = []
    for node in selected.values():
        overlap = 0
        for item in evidence_by_source.get(str(node.get("source_id") or ""), []):
            line_start = item.get("line_start")
            line_end = item.get("line_end")
            if line_start is None or node.get("start_line") is None:
                continue
            evidence_end = int(line_end or line_start)
            node_end = int(node.get("end_line") or node["start_line"])
            if int(line_start) <= node_end and evidence_end >= int(node["start_line"]):
                overlap = max(overlap, 2)
        ranked.append((overlap, node.get("kind") != "file", node))
    ranked.sort(key=lambda item: (-item[0], -int(item[1]), str(item[2]["qualified_id"])))
    return [item[2] for item in ranked[:limit]]


def _build_ranked_flows(
    conn,
    *,
    project_id: str,
    snapshot_id: str,
    seeds: list[dict],
    candidate_scores: dict[str, float],
    anchor_order: dict[str, int],
    query: str,
    lens: str,
    max_steps: int,
    max_nodes: int,
    max_edges: int,
    timeout_ms: int,
    started: float,
) -> tuple[list[dict], int, bool]:
    paths: list[dict] = []
    examined_edge_ids: set[str] = set()
    visited_node_ids: set[str] = set()
    timed_out = False
    query_terms = _query_terms(query)
    anchor_ids = set(anchor_order)
    sorted_seeds = sorted(
        seeds[:10],
        key=lambda node: (
            anchor_order.get(str(node["id"]), 999),
            -candidate_scores.get(str(node["id"]), 0.0),
            str(node["qualified_id"]),
        ),
    )
    ordered_seeds = []
    deferred = []
    seen_labels: set[str] = set()
    for seed in sorted_seeds:
        label = str(seed.get("display_label") or "").casefold()
        if label in seen_labels:
            deferred.append(seed)
        else:
            seen_labels.add(label)
            ordered_seeds.append(seed)
    ordered_seeds.extend(deferred)
    for seed in ordered_seeds[:6]:
        if (time.perf_counter() - started) * 1000 >= timeout_ms:
            timed_out = True
            break
        route_prefix = _route_prefix(conn, project_id, snapshot_id, seed)
        initial_nodes = route_prefix[0] if route_prefix else [seed]
        initial_transitions = route_prefix[1] if route_prefix else []
        initial_matches = _path_query_terms(initial_nodes, query_terms)
        direction_bonus = max(
            0.0,
            (len(query_terms) - anchor_order.get(str(seed["id"]), len(query_terms))) * 140.0,
        )
        beam = [{
            "nodes": initial_nodes,
            "transitions": initial_transitions,
            "score": candidate_scores[str(seed["id"])] + len(initial_matches) * 8.0 + direction_bonus,
            "query_terms": initial_matches,
            "anchors": {str(node["id"]) for node in initial_nodes if str(node["id"]) in anchor_ids},
        }]
        completed = []
        while beam:
            next_beam = []
            for path in beam:
                if (time.perf_counter() - started) * 1000 >= timeout_ms:
                    timed_out = True
                    completed.append(path)
                    continue
                if len(path["nodes"]) >= max_steps:
                    completed.append(path)
                    continue
                current = path["nodes"][-1]
                transitions = _outgoing_flow_transitions(
                    conn, project_id, snapshot_id, str(current["id"]), lens=lens,
                )
                choices = []
                path_ids = {str(node["id"]) for node in path["nodes"]}
                for transition in transitions:
                    edge_id = str(transition.edge["id"])
                    if edge_id not in examined_edge_ids:
                        if len(examined_edge_ids) >= max_edges:
                            break
                        examined_edge_ids.add(edge_id)
                    if transition.target in path_ids:
                        continue
                    target = _node_by_id(conn, project_id, snapshot_id, transition.target)
                    if target is None:
                        continue
                    visited_node_ids.add(str(target["id"]))
                    if len(visited_node_ids) > max_nodes:
                        break
                    new_terms = {
                        term for term in query_terms
                        if term not in path["query_terms"] and _node_matches_term(target, term)
                    }
                    target_id = str(target["id"])
                    new_anchor = target_id in anchor_ids and target_id not in path["anchors"]
                    edge_score = _edge_score(str(transition.edge["edge_type"]), lens, transition.display_reversed)
                    if transition.edge.get("confidence_class") == "user_confirmed":
                        edge_score += 5.0
                    choices.append({
                        "nodes": [*path["nodes"], target],
                        "transitions": [*path["transitions"], transition],
                        "score": (
                            path["score"] + edge_score + _candidate_bonus(target)
                            + len(new_terms) * 26.0
                            + (90.0 + candidate_scores.get(target_id, 0.0) * 0.75 if new_anchor else 0.0)
                        ),
                        "query_terms": path["query_terms"] | new_terms,
                        "anchors": path["anchors"] | ({target_id} if new_anchor else set()),
                    })
                    if new_anchor and len(choices[-1]["query_terms"]) >= 2:
                        completed.append(choices.pop())
                if choices:
                    next_beam.extend(choices)
                else:
                    completed.append(path)
            if timed_out or len(visited_node_ids) > max_nodes or len(examined_edge_ids) >= max_edges:
                break
            if not next_beam:
                break
            next_beam.sort(key=lambda item: (-_ranked_path_score(item), _path_signature(item)))
            beam = next_beam[:6]
        completed.extend(beam)
        completed = [item for item in completed if item["transitions"]]
        completed.sort(key=lambda item: (-_ranked_path_score(item), _path_signature(item)))
        paths.extend(completed[:2])
    unique: dict[tuple[str, ...], dict] = {}
    for path in paths:
        signature = tuple(str(node["id"]) for node in path["nodes"])
        existing = unique.get(signature)
        if existing is None or path["score"] > existing["score"]:
            unique[signature] = path
    ranked = sorted(
        unique.values(),
        key=lambda item: (-_ranked_path_score(item), _path_signature(item)),
    )
    return ranked[: FLOW_MAX_ALTERNATIVES + 1], len(examined_edge_ids), timed_out


def _route_prefix(conn, project_id: str, snapshot_id: str, seed: dict) -> tuple[list[dict], list[_Transition]] | None:
    if str(seed.get("kind") or "") == "route":
        row = conn.execute(
            """
            SELECT * FROM code_edges
            WHERE project_id = ? AND snapshot_id = ? AND target_node_id = ?
              AND edge_type = 'defines_route' AND confidence_class IN ('extracted', 'user_confirmed')
            ORDER BY id LIMIT 1
            """,
            (project_id, snapshot_id, seed["id"]),
        ).fetchone()
        if row:
            edge = dict_from_row(row)
            handler = _node_by_id(conn, project_id, snapshot_id, str(edge["source_node_id"]))
            if handler:
                return [seed, handler], [_Transition(edge, str(seed["id"]), str(handler["id"]), True)]
    row = conn.execute(
        """
        SELECT e.*, route.*
        FROM code_edges e JOIN code_nodes route ON route.id = e.target_node_id
        WHERE e.project_id = ? AND e.snapshot_id = ? AND e.source_node_id = ?
          AND e.edge_type = 'defines_route' AND e.confidence_class IN ('extracted', 'user_confirmed')
        ORDER BY e.id LIMIT 1
        """,
        (project_id, snapshot_id, seed["id"]),
    ).fetchone()
    if row:
        route = _node_by_id(conn, project_id, snapshot_id, str(row["target_node_id"]))
        edge = {key: row[key] for key in row.keys() if key in {
            "id", "source_node_id", "target_node_id", "edge_type", "evidence_source_id",
            "source_line", "confidence_class",
        }}
        if route:
            return [route, seed], [_Transition(edge, str(route["id"]), str(seed["id"]), True)]
    return None


def _outgoing_flow_transitions(
    conn, project_id: str, snapshot_id: str, node_id: str, *, lens: str,
) -> list[_Transition]:
    edge_types = sorted(_edges_for_lens(lens))
    rows = conn.execute(
        f"""
        SELECT e.* FROM code_edges e
        JOIN code_nodes source ON source.id = e.source_node_id
        JOIN code_nodes target ON target.id = e.target_node_id
        WHERE e.project_id = ? AND e.snapshot_id = ? AND e.source_node_id = ?
          AND e.edge_type IN ({','.join('?' for _ in edge_types)})
          AND e.confidence_class IN ('extracted', 'user_confirmed')
          AND (e.edge_type <> 'contains' OR (
                source.kind NOT IN ('file', 'project')
                AND target.kind IN ('function', 'method', 'component', 'class', 'route')
          ))
        ORDER BY CASE e.edge_type WHEN 'calls' THEN 0 ELSE 1 END, e.id
        LIMIT 96
        """,
        [project_id, snapshot_id, node_id, *edge_types],
    ).fetchall()
    transitions = [
        _Transition(dict_from_row(row), node_id, str(row["target_node_id"])) for row in rows
    ]
    reverse_types = _reverse_edges_for_lens(lens)
    if reverse_types:
        incoming = conn.execute(
            f"""
            SELECT * FROM code_edges
            WHERE project_id = ? AND snapshot_id = ? AND target_node_id = ?
              AND edge_type IN ({','.join('?' for _ in reverse_types)})
              AND confidence_class IN ('extracted', 'user_confirmed')
            ORDER BY edge_type, id LIMIT 96
            """,
            [project_id, snapshot_id, node_id, *sorted(reverse_types)],
        ).fetchall()
        transitions.extend(
            _Transition(dict_from_row(row), node_id, str(row["source_node_id"]), True)
            for row in incoming
        )
    return transitions


def _node_by_id(conn, project_id: str, snapshot_id: str, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM code_nodes WHERE project_id = ? AND snapshot_id = ? AND id = ?",
        (project_id, snapshot_id, node_id),
    ).fetchone()
    return dict_from_row(row) if row else None


def _load_source_semantics(conn, project: dict, source_ids: list[str]) -> dict[str, dict]:
    if not source_ids:
        return {}
    rows = conn.execute(
        f"SELECT * FROM sources WHERE vault_id = ? AND id IN ({','.join('?' for _ in source_ids)})",
        [project["vault_id"], *source_ids],
    ).fetchall()
    result = {}
    for row in rows:
        source = dict_from_row(row)
        encrypted = load_source_content_fields(
            conn,
            vault_id=str(source["vault_id"]),
            source_id=str(source["id"]),
            fields=("summary",),
        )
        summary = str(encrypted.get("summary") or source.get("summary") or "").strip()
        quality = str(source.get("metadata_quality") or "fallback")
        if int(source.get("semantic_metadata_version") or 0) <= 0 and quality == "semantic":
            quality = "fallback"
        result[str(source["id"])] = {"summary": summary, "quality": quality}
    return result


def _public_flow(
    flow: dict,
    *,
    lens: str,
    source_semantics: dict[str, dict],
    evidence_by_source: dict[str, list[dict]],
) -> dict:
    steps = []
    for index, node in enumerate(flow["nodes"]):
        source_id = str(node.get("source_id") or "")
        semantics = source_semantics.get(source_id, {})
        source_summary = str(semantics.get("summary") or "").strip()
        semantic_quality = str(semantics.get("quality") or "unavailable")
        incoming = flow["transitions"][index - 1] if index > 0 else None
        outgoing = flow["transitions"][index] if index < len(flow["transitions"]) else None
        previous_node = flow["nodes"][index - 1] if index > 0 else None
        next_node = flow["nodes"][index + 1] if index + 1 < len(flow["nodes"]) else None
        explanation = _step_explanation(
            node,
            index=index,
            total=len(flow["nodes"]),
            previous_node=previous_node,
            next_node=next_node,
            incoming=incoming,
            outgoing=outgoing,
            lens=lens,
        )
        evidence = []
        for item in evidence_by_source.get(source_id, [])[:2]:
            if not _evidence_overlaps_node(item, node):
                continue
            evidence.append({
                "source_id": source_id,
                "relative_path": str(item.get("relative_path") or node.get("relative_path") or ""),
                "line_start": item.get("line_start") or node.get("start_line"),
                "line_end": item.get("line_end") or node.get("end_line"),
                "chunk_id": item.get("chunk_id"),
                "excerpt": str(item.get("snippet") or "")[:600],
                "basis": "semantic_retrieval",
            })
        if not evidence and source_id:
            evidence.append({
                "source_id": source_id,
                "relative_path": str(node.get("relative_path") or ""),
                "line_start": node.get("start_line"),
                "line_end": node.get("end_line"),
                "basis": "structure",
            })
        connection = None
        if index < len(flow["transitions"]):
            transition = flow["transitions"][index]
            edge = transition.edge
            connection = {
                "edge_id": str(edge["id"]),
                "type": str(edge["edge_type"]),
                "label": _relationship_label(str(edge["edge_type"]), transition.display_reversed),
                "confidence": str(edge.get("confidence_class") or "extracted"),
                "evidence_source_id": edge.get("evidence_source_id"),
                "source_line": edge.get("source_line"),
                "display_reversed": transition.display_reversed,
                "raw_source_node_id": str(edge["source_node_id"]),
                "raw_target_node_id": str(edge["target_node_id"]),
            }
        steps.append({
            "ordinal": index + 1,
            "node": _public_node(node),
            "plain_label": _plain_node_label(node),
            "role_summary": explanation["what_happens"],
            "what_happens": explanation["what_happens"],
            "why_it_matters": explanation["why_it_matters"],
            "technical_detail": _structural_summary(node),
            "source_context": source_summary[:320] if semantic_quality == "semantic" else "",
            "summary_scope": "symbol",
            "semantic_quality": semantic_quality,
            "evidence": evidence[:2],
            "connection_to_next": connection,
        })
    overview = _flow_overview(steps, lens)
    return {
        "id": "flow:" + ":".join(str(node["id"]) for node in flow["nodes"]),
        "title": f"{steps[0]['plain_label']} to {steps[-1]['plain_label']}",
        "overview": overview,
        "score": round(float(flow["score"]), 3),
        "steps": steps,
    }


def _step_explanation(
    node: dict,
    *,
    index: int,
    total: int,
    previous_node: dict | None,
    next_node: dict | None,
    incoming: _Transition | None,
    outgoing: _Transition | None,
    lens: str,
) -> dict[str, str]:
    label = _plain_node_label(node)
    next_label = _plain_node_label(next_node) if next_node else "the next part of the system"
    kind = str(node.get("kind") or "item")

    if outgoing is not None:
        edge_type = str(outgoing.edge.get("edge_type") or "")
        reversed_display = outgoing.display_reversed
        if edge_type == "contains":
            what = f"{label} hands the action to {next_label}, a local helper that performs the next part."
            why = "This separates what the user sees from the code that reacts to it."
        elif edge_type == "http_request":
            what = f"{label} sends a request to {next_label}."
            why = "This is the handoff from the current part of the app to an HTTP endpoint."
        elif edge_type == "defines_route" and reversed_display:
            what = f"The backend receives this request and directs it to {next_label}."
            why = "This chooses the server-side code responsible for the request."
        elif edge_type == "calls":
            what = f"{label} asks {next_label} to perform the next piece of work."
            why = "The responsibility moves to a smaller, focused part of the code."
        elif edge_type == "dispatches":
            what = f"{label} schedules {next_label} to continue the work."
            why = "The next step can run separately from the current operation."
        elif edge_type == "dispatches_job":
            what = f"{label} places work onto {next_label}."
            why = "The job can be processed in the background instead of blocking the user."
        elif edge_type in {"sends_ipc", "emits_event"}:
            what = f"{label} sends a message that {next_label} can react to."
            why = "This connects two parts of the application without calling them directly."
        elif edge_type in {"handles_ipc", "listens_event"} and reversed_display:
            what = f"{label} is picked up by {next_label}."
            why = "This is where the receiving side starts handling the message."
        elif edge_type in {"reads_data", "writes_data"} and reversed_display:
            action = "reads from" if edge_type == "reads_data" else "writes to"
            what = f"{next_label} {action} {label}."
            why = "This shows which code depends on this stored information."
        elif edge_type == "reads_data":
            what = f"{label} looks up information in {next_label}."
            why = "This supplies the saved data needed for the rest of the flow."
        elif edge_type == "writes_data":
            what = f"{label} saves or updates information in {next_label}."
            why = "This is the point where the result becomes stored data."
        elif edge_type in {"raises_failure", "handles_failure"}:
            what = f"{label} passes a possible failure to {next_label}."
            why = "This marks where the normal path can stop or be recovered."
        else:
            relationship = _relationship_label(edge_type, reversed_display)
            what = f"{label} {relationship} {next_label}."
            why = f"This verified relationship moves the {lens} story forward."
    elif kind == "data_store":
        what = f"The journey ends with the relevant information in {label}."
        why = "This is the durable data boundary reached by the flow."
    elif index == total - 1:
        what = f"{label} completes the last verified step Odin can see in this path."
        why = "Anything after this point was not connected by indexed evidence."
    elif incoming is not None and previous_node is not None:
        what = f"The work arrives at {label} from {_plain_node_label(previous_node)}."
        why = "This component owns the next responsibility in the journey."
    else:
        what = f"The journey begins at {label}."
        why = "This is the first component that matched the question and had a verified path."
    return {"what_happens": what, "why_it_matters": why}


def _flow_overview(steps: list[dict], lens: str) -> dict[str, str]:
    start = steps[0]["plain_label"]
    end = steps[-1]["plain_label"]
    middle = [step["plain_label"] for step in steps[1:-1]][:2]
    if middle:
        route = ", then ".join(middle)
        summary = f"It starts at {start}, moves through {route}, and reaches {end}."
    else:
        summary = f"It starts at {start} and reaches {end}."
    return {
        "answer": summary,
        "meaning": (
            f"Odin found {len(steps)} connected, evidence-backed steps for this {lens} question. "
            "Select any step to see the code and source location that support it."
        ),
    }


def _plain_node_label(node: dict | None) -> str:
    if not node:
        return "the next step"
    label = str(node.get("display_label") or node.get("label") or "this step").strip()
    if re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s", label):
        return label
    cleaned = re.sub(r"[_-]+", " ", label)
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if str(node.get("kind") or "") in {"function", "method"}:
        lowered = cleaned.casefold()
        if lowered == "submit":
            return "submit handler"
        if lowered.startswith("api "):
            return f"{cleaned[4:]} handler"
    return cleaned


def _evidence_overlaps_node(evidence: dict, node: dict) -> bool:
    evidence_start = evidence.get("line_start")
    node_start = node.get("start_line")
    if evidence_start is None or node_start is None:
        return False
    evidence_start = int(evidence_start)
    evidence_end = int(evidence.get("line_end") or evidence_start)
    node_start = int(node_start)
    node_end = int(node.get("end_line") or node_start)
    return evidence_start <= node_end and evidence_end >= node_start


def _public_node(node: dict) -> dict:
    return {
        "id": str(node["id"]),
        "qualified_id": str(node["qualified_id"]),
        "kind": str(node.get("kind") or "item"),
        "language": str(node.get("language") or ""),
        "label": str(node.get("display_label") or node.get("label") or node["qualified_id"]),
        "relative_path": str(node.get("relative_path") or ""),
        "start_line": node.get("start_line"),
        "end_line": node.get("end_line"),
        "signature": str(node.get("signature") or ""),
        "source_id": node.get("source_id"),
    }


def _query_terms(query: str) -> list[str]:
    values = re.findall(r"[A-Za-z_][A-Za-z0-9_-]{2,}", query)
    return list(dict.fromkeys(
        value.casefold() for value in values if value.casefold() not in _QUERY_STOPWORDS
    ))[:8]


def _flow_lens(query: str) -> str:
    for lens, pattern in _LENS_PATTERNS:
        if pattern.search(query):
            return lens
    return "execution"


def _edges_for_lens(lens: str) -> set[str]:
    edges = set(_EXECUTION_EDGES | _SUPPORTING_EDGES | {"contains"})
    if lens == "lineage":
        edges.update({"reads_data", "writes_data", "uses_schema"})
    elif lens == "failure":
        edges.update({"raises_failure", "handles_failure"})
    elif lens == "async":
        edges.update({"dispatches", "dispatches_job", "sends_ipc", "emits_event"})
    elif lens == "architecture":
        edges.update({"imports", "registers_router", "defines_route"})
    elif lens == "tests":
        edges.add("tested_by")
    return edges


def _reverse_edges_for_lens(lens: str) -> set[str]:
    # Boundary nodes point away from their handlers in the stored graph. Reversing
    # these edges makes a human-readable entrypoint -> handler flow possible.
    reverse = set(_ENTRY_EDGES)
    if lens in {"impact", "health", "tests"}:
        reverse.update({"calls", "dispatches", "imports", "tested_by"})
    if lens == "lineage":
        reverse.update({"writes_data", "uses_schema"})
    if lens == "async":
        reverse.update({"dispatches_job", "sends_ipc", "emits_event"})
    return reverse


def _edge_score(edge_type: str, lens: str, reversed_display: bool) -> float:
    base = {
        "calls": 18.0,
        "defines_route": 25.0,
        "http_request": 25.0,
        "dispatches": 22.0,
        "dispatches_job": 23.0,
        "sends_ipc": 23.0,
        "handles_ipc": 24.0,
        "emits_event": 20.0,
        "listens_event": 22.0,
        "reads_data": 18.0,
        "writes_data": 20.0,
        "raises_failure": 18.0,
        "handles_failure": 20.0,
        "registers_router": 14.0,
        "uses_schema": 12.0,
        "configured_by": 8.0,
        "imports": 5.0,
        "contains": 7.0,
        "tested_by": 12.0,
    }.get(edge_type, 4.0)
    preferred = {
        "impact": {"calls", "dispatches", "imports", "tested_by"},
        "lineage": {"reads_data", "writes_data", "uses_schema"},
        "failure": {"raises_failure", "handles_failure"},
        "async": {"dispatches", "dispatches_job", "sends_ipc", "handles_ipc", "emits_event", "listens_event"},
        "tests": {"tested_by", "calls", "imports"},
        "architecture": {"imports", "registers_router", "defines_route"},
    }.get(lens, _EXECUTION_EDGES | {"defines_route"})
    if edge_type in preferred:
        base += 16.0
    if reversed_display and lens not in {"impact", "health", "tests"}:
        base -= 2.0
    return base


def _ranked_path_score(path: dict) -> float:
    # Two independently matched question anchors are much stronger evidence than
    # a long path branching from a single fuzzy symbol.
    return (
        float(path.get("score") or 0.0)
        + len(path.get("anchors") or ()) * 70.0
        + len(path.get("query_terms") or ()) * 18.0
        - max(0, len(path.get("nodes") or ()) - 5) * 3.0
    )


def _path_query_terms(nodes: list[dict], terms: list[str]) -> set[str]:
    return {term for term in terms if any(_node_matches_term(node, term) for node in nodes)}


def _node_matches_term(node: dict, term: str) -> bool:
    needle = term.casefold()
    return any(
        needle in str(node.get(field) or "").casefold()
        for field in ("display_label", "qualified_id", "relative_path", "signature")
    )


def _lexical_score(node: dict, term: str, *, term_index: int, rank: int) -> float:
    label = str(node.get("display_label") or "").casefold()
    qualified = str(node.get("qualified_id") or "").casefold()
    path = str(node.get("relative_path") or "").casefold()
    score = 50.0 - (term_index * 2.0) - rank
    if label == term:
        score += 60.0
    elif label.startswith(term):
        score += 30.0
    elif term in label:
        score += 18.0
    if term in qualified:
        score += 12.0
    if term in path:
        score += 6.0
    return score


def _candidate_bonus(node: dict) -> float:
    kind_bonus = {"route": 22.0, "function": 18.0, "method": 17.0, "class": 10.0, "file": 4.0}
    score = kind_bonus.get(str(node.get("kind") or ""), 0.0)
    role = str(node.get("file_role") or "source")
    path = str(node.get("relative_path") or "").replace("\\", "/").casefold()
    if role in {"test", "fixture", "generated", "vendor"} or re.search(
        r"(^|/)(tests?|__tests__|fixtures?|generated|vendor)(/|$)", path
    ):
        score -= 40.0
    score += min(float(node.get("pagerank") or 0.0) * 10_000, 12.0)
    return score


def _candidate_phrase_bonus(node: dict, query: str) -> float:
    label = " ".join(str(node.get("display_label") or "").split()).casefold()
    normalized = " ".join(query.split()).casefold()
    if len(label) >= 4 and label in normalized:
        return 240.0
    qualified = str(node.get("qualified_id") or "").casefold()
    if len(qualified) >= 6 and qualified in normalized:
        return 80.0
    matched = sum(_node_matches_term(node, term) for term in _query_terms(query))
    return max(0, matched - 1) * 80.0


def _structural_summary(node: dict) -> str:
    kind = str(node.get("kind") or "item").replace("_", " ")
    signature = str(node.get("signature") or "").strip()
    if not signature:
        return f"Odin indexed this {kind} as part of the project flow."
    if signature.casefold().startswith((kind.casefold(), "function ", "class ", "def ")):
        return f"Indexed declaration: {signature}."
    return f"Indexed {kind} with signature {signature}."


def _relationship_label(edge_type: str, reversed_display: bool) -> str:
    if reversed_display:
        return {
            "defines_route": "handled by",
            "handles_ipc": "handled by",
            "listens_event": "handled by",
            "reads_data": "read by",
            "writes_data": "written by",
            "handles_failure": "handled by",
            "calls": "called by",
            "dispatches": "dispatched by",
            "imports": "imported by",
            "tested_by": "tests",
        }.get(edge_type, f"reverse {edge_type.replace('_', ' ')}")
    return {
        "calls": "calls",
        "dispatches": "dispatches",
        "http_request": "requests",
        "dispatches_job": "queues job",
        "sends_ipc": "sends IPC message",
        "handles_ipc": "handles IPC message",
        "emits_event": "emits event",
        "listens_event": "listens for event",
        "defines_route": "defines route",
        "registers_router": "registers router",
        "reads_data": "reads data",
        "writes_data": "writes data",
        "raises_failure": "may raise",
        "handles_failure": "handles failure",
        "tested_by": "tested by",
        "imports": "imports",
        "contains": "contains",
        "uses_schema": "uses schema",
        "configured_by": "configured by",
    }.get(edge_type, edge_type.replace("_", " "))


def _evidence_by_source(evidence: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for item in evidence:
        source_id = str(item.get("source_id") or "")
        if source_id:
            result.setdefault(source_id, []).append(item)
    return result


def _path_signature(path: dict) -> str:
    return "\0".join(str(node["id"]) for node in path["nodes"])


def _limits(
    max_steps: int,
    max_nodes: int,
    max_edges: int,
    timeout_ms: int,
    candidate_timeout_ms: int = FLOW_CANDIDATE_TIMEOUT_MS,
    retrieval_timeout_ms: int = FLOW_RETRIEVAL_TIMEOUT_MS,
) -> dict:
    return {
        "max_steps": max_steps,
        "max_candidate_nodes": max_nodes,
        "max_examined_edges": max_edges,
        "max_alternatives": FLOW_MAX_ALTERNATIVES,
        "timeout_ms": timeout_ms,
        "candidate_timeout_ms": candidate_timeout_ms,
        "retrieval_timeout_ms": retrieval_timeout_ms,
    }


def _empty_result(
    project: dict,
    query: str,
    structure_snapshot_id: str,
    retrieval_snapshot_id: str,
    *,
    status: str,
    candidates: list[dict],
    warnings: list[str],
    started: float,
    limits: dict,
    lens: str = "execution",
    diagnostics: dict | None = None,
) -> dict:
    return {
        "version": FLOW_VERSION,
        "project_id": str(project["id"]),
        "query": query,
        "lens": lens,
        "status": status,
        "structure_snapshot_id": structure_snapshot_id,
        "retrieval_snapshot_id": retrieval_snapshot_id,
        "indexed_commit": project.get("indexed_commit"),
        "primary_flow": None,
        "alternatives": [],
        "candidates": candidates,
        "analysis": {
            "lens": lens,
            "title": lens.replace("_", " ").title(),
            "summary": "No verified path was available for this lens.",
            "observations": [],
            "test_impact": {"status": "unknown", "exact_tests": [], "guessed_tests": []},
            "release_change": {"status": "unknown", "changed": [], "unchanged": []},
            "limitations": [],
        },
        "freshness": {
            "structure_status": str(project.get("structure_status") or "unknown"),
            "retrieval_status": str(project.get("retrieval_status") or "unknown"),
            "changed_file_count": int(project.get("changed_file_count") or 0),
            "includes_unindexed_changes": False,
        },
        "warnings": warnings,
        "limits": limits,
        "diagnostics": {
            "candidate_nodes": len(candidates),
            "examined_edges": 0,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            **(diagnostics or {}),
        },
    }
