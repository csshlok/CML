from __future__ import annotations

import json
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.context_memory import get_context_memory
from backend.app.core.context_packets import build_bridge_context_packet, render_context_packet
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import embed_text
from backend.app.core.encrypted_storage import source_from_encrypted_row
from backend.app.core.turbovec_runtime import semantic_search_results


def export_context_layer_report(
    vault_id: str,
    *,
    cluster_id: str | None = None,
    queries: list[str | dict] | None = None,
    limit: int = 5,
) -> dict:
    selected_queries = _normalize_query_specs(queries or _default_queries(vault_id))
    rows = []
    for query_spec in selected_queries:
        row = _context_layer_row(vault_id, query_spec=query_spec, cluster_id=cluster_id, limit=limit)
        rows.append(row)

    avg_savings = round(sum(row["packet_savings_percent"] for row in rows) / max(len(rows), 1), 2) if rows else 0.0
    max_savings = round(max((row["packet_savings_percent"] for row in rows), default=0.0), 2)
    min_savings = round(min((row["packet_savings_percent"] for row in rows), default=0.0), 2)
    average_token_budget = round(sum(row["token_budget"] for row in rows) / max(len(rows), 1), 2) if rows else 0.0
    degraded_query_count = sum(1 for row in rows if row["partial_failure_mode"] != "none")
    hostile_detected_query_count = sum(1 for row in rows if row["hostile_instruction_detected"])
    analysis_mode_counts = _counts(row["analysis_mode"] for row in rows)
    partial_failure_counts = _counts(row["partial_failure_mode"] for row in rows)
    report_id = f"context-layer-report-{uuid4()}"
    payload = {
        "report_id": report_id,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "generated_at": utc_now(),
        "query_count": len(rows),
        "average_packet_savings_percent": avg_savings,
        "max_packet_savings_percent": max_savings,
        "min_packet_savings_percent": min_savings,
        "average_token_budget": average_token_budget,
        "degraded_query_count": degraded_query_count,
        "hostile_detected_query_count": hostile_detected_query_count,
        "analysis_mode_counts": analysis_mode_counts,
        "partial_failure_counts": partial_failure_counts,
        "rows": rows,
    }
    output_dir = get_settings().data_dir / "benchmark-reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report_id}.json"
    markdown_path = output_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(_context_layer_markdown(payload), encoding="utf-8")
    return {
        "report_id": report_id,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "query_count": len(rows),
        "average_packet_savings_percent": avg_savings,
        "average_token_budget": average_token_budget,
    }


def _context_layer_row(vault_id: str, *, query_spec: dict, cluster_id: str | None, limit: int) -> dict:
    query = str(query_spec["prompt"])
    expanded_analysis = bool(query_spec.get("expanded_analysis"))
    complete_analysis = bool(query_spec.get("complete_analysis"))
    search = semantic_search_results(
        vault_id,
        embed_text(query),
        cluster_id=cluster_id,
        limit=max(1, min(limit, 12)),
    )
    results = search.get("results") or []
    with connect() as conn:
        source_rows = []
        cluster_rows = []
        source_ids = []
        cluster_ids = []
        for result in results:
            source_id = str(result.get("source_id") or "")
            cluster_value = str(result.get("cluster_id") or "")
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
            if cluster_value and cluster_value not in cluster_ids:
                cluster_ids.append(cluster_value)
        if source_ids:
            source_rows = conn.execute(
                f"SELECT * FROM sources WHERE vault_id = ? AND id IN ({','.join('?' for _ in source_ids)})",
                [vault_id, *source_ids],
            ).fetchall()
        if cluster_ids:
            cluster_rows = conn.execute(
                f"SELECT * FROM clusters WHERE vault_id = ? AND id IN ({','.join('?' for _ in cluster_ids)})",
                [vault_id, *cluster_ids],
            ).fetchall()
        memory_items, working_memory = get_context_memory(
            conn,
            vault_id=vault_id,
            cluster_id=cluster_id,
            query=query,
        )
        sources_by_id = {row["id"]: _source_snippet_from_row(conn, row) for row in source_rows}

    ordered_sources = []
    for source_id in source_ids:
        snippet = sources_by_id.get(source_id)
        if snippet:
            ordered_sources.append(snippet)

    packet = build_bridge_context_packet(
        query=query,
        context_request_id=f"eval-{uuid4()}",
        selected_clusters=[dict_from_row(row) for row in cluster_rows],
        source_snippets=ordered_sources,
        warnings=[],
        memory_items=memory_items,
        working_memory=working_memory,
    )
    packet_text = render_context_packet(packet)
    raw_payload = {
        "query": query,
        "selected_clusters": [dict_from_row(row) for row in cluster_rows],
        "source_snippets": ordered_sources,
        "memory_items": memory_items,
        "working_memory": working_memory,
    }
    raw_bytes = len(json.dumps(raw_payload, ensure_ascii=False).encode("utf-8"))
    packet_bytes = len(packet_text.encode("utf-8"))
    savings_percent = round(max(0.0, ((raw_bytes - packet_bytes) / max(raw_bytes, 1)) * 100.0), 2)
    behavior = _behavior_row(
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        expanded_analysis=expanded_analysis,
        complete_analysis=complete_analysis,
    )
    return {
        "query": query,
        "requested_analysis_mode": (
            "complete_analysis" if complete_analysis else "expanded_analysis" if expanded_analysis else "standard"
        ),
        "result_count": len(results),
        "cluster_count": len(cluster_rows),
        "memory_item_count": len(memory_items),
        "working_memory_present": bool(str(working_memory.get("summary") or "").strip()),
        "raw_payload_bytes": raw_bytes,
        "packet_bytes": packet_bytes,
        "packet_savings_percent": savings_percent,
        "expansion_handle_count": len(packet["evidence"]),
        "source_titles": [item["title"] for item in packet["evidence"]],
        **behavior,
    }


def _default_queries(vault_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (vault_id,),
        ).fetchall()
        prompts = []
        for row in rows:
            source = source_from_encrypted_row(conn, row)
            title = str(source["title"] or "").strip()
            summary = " ".join(str(source["summary"] or "").split())
            query = title or summary[:80]
            if query:
                prompts.append(query)
    prompts = prompts or ["project context", "bridge context", "chat memory"]
    specs = [{"prompt": prompt} for prompt in prompts[:3]]
    primary = prompts[0]
    specs.append({"prompt": primary, "expanded_analysis": True})
    specs.append({"prompt": primary, "complete_analysis": True})
    return specs


def _normalize_query_specs(queries: list[str | dict]) -> list[dict]:
    normalized = []
    for query in queries:
        if isinstance(query, str):
            prompt = query.strip()
            if prompt:
                normalized.append({"prompt": prompt})
            continue
        if isinstance(query, dict):
            prompt = str(query.get("prompt") or query.get("query") or "").strip()
            if not prompt:
                continue
            normalized.append(
                {
                    "prompt": prompt,
                    "expanded_analysis": bool(query.get("expanded_analysis")),
                    "complete_analysis": bool(query.get("complete_analysis")),
                }
            )
    return normalized


def _behavior_row(
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    expanded_analysis: bool,
    complete_analysis: bool,
) -> dict:
    from backend.app.api.routes.chat import _build_retrieval_context
    from backend.app.schemas import ChatContextRequest

    context = _build_retrieval_context(
        ChatContextRequest(
            vault_id=vault_id,
            cluster_id=cluster_id,
            prompt=query,
            persist=False,
            expanded_analysis=expanded_analysis,
            complete_analysis=complete_analysis,
        ),
        synthesize=False,
    )
    coverage = context.get("coverage_ledger") or {}
    return {
        "intent": context.get("intent") or "unknown",
        "analysis_mode": coverage.get("analysis_mode") or "standard",
        "runtime_state": context.get("runtime_state"),
        "partial_failure_mode": coverage.get("partial_failure_mode") or "none",
        "trust_gate_mode": coverage.get("trust_gate_mode") or "normal",
        "token_budget": int(coverage.get("token_budget") or 0),
        "citations_selected": int(coverage.get("citations_selected") or 0),
        "warnings_count": len(context.get("warnings") or []),
        "contradiction_detected": bool(coverage.get("contradiction_detected")),
        "hostile_instruction_detected": bool(coverage.get("hostile_instruction_detected")),
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _source_snippet_from_row(conn, row) -> dict:
    source = source_from_encrypted_row(conn, row)
    snippet = str(source.get("summary") or source.get("extracted_text") or source.get("raw_text") or "").strip()
    return {
        "id": source["id"],
        "title": source["title"],
        "summary": source.get("summary") or "",
        "snippet": snippet[:420] + ("..." if len(snippet) > 420 else ""),
        "source_type": source.get("source_type") or "",
        "trust_tier": source.get("trust_tier") or "trusted_local",
        "cluster_id": source.get("cluster_id"),
    }


def _context_layer_markdown(payload: dict) -> str:
    lines = [
        "# Context Layer Report",
        "",
        f"- Vault: {payload['vault_id']}",
        f"- Query count: {payload['query_count']}",
        f"- Average packet savings: {payload['average_packet_savings_percent']}%",
        f"- Max packet savings: {payload['max_packet_savings_percent']}%",
        f"- Min packet savings: {payload['min_packet_savings_percent']}%",
        f"- Average token budget: {payload['average_token_budget']}",
        f"- Degraded query count: {payload['degraded_query_count']}",
        f"- Hostile-detected query count: {payload['hostile_detected_query_count']}",
        "",
        "| Query | Mode | Partial failure | Results | Memory items | Working memory | Raw bytes | Packet bytes | Savings |",
        "| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["query"].replace("|", "/"),
                    row["analysis_mode"],
                    row["partial_failure_mode"],
                    str(row["result_count"]),
                    str(row["memory_item_count"]),
                    "yes" if row["working_memory_present"] else "no",
                    str(row["raw_payload_bytes"]),
                    str(row["packet_bytes"]),
                    f"{row['packet_savings_percent']}%",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)
