from __future__ import annotations

import json
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.context_memory import get_context_memory
from backend.app.core.context_packets import build_bridge_context_packet, render_context_packet
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import embed_text
from backend.app.core.turbovec_runtime import semantic_search_results


def export_context_layer_report(
    vault_id: str,
    *,
    cluster_id: str | None = None,
    queries: list[str] | None = None,
    limit: int = 5,
) -> dict:
    selected_queries = [query.strip() for query in (queries or _default_queries(vault_id)) if query.strip()]
    rows = []
    for query in selected_queries:
        row = _context_layer_row(vault_id, query=query, cluster_id=cluster_id, limit=limit)
        rows.append(row)

    avg_savings = round(sum(row["packet_savings_percent"] for row in rows) / max(len(rows), 1), 2) if rows else 0.0
    max_savings = round(max((row["packet_savings_percent"] for row in rows), default=0.0), 2)
    min_savings = round(min((row["packet_savings_percent"] for row in rows), default=0.0), 2)
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
    }


def _context_layer_row(vault_id: str, *, query: str, cluster_id: str | None, limit: int) -> dict:
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

    ordered_sources = []
    sources_by_id = {row["id"]: _source_snippet_from_row(row) for row in source_rows}
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
    return {
        "query": query,
        "result_count": len(results),
        "cluster_count": len(cluster_rows),
        "memory_item_count": len(memory_items),
        "working_memory_present": bool(str(working_memory.get("summary") or "").strip()),
        "raw_payload_bytes": raw_bytes,
        "packet_bytes": packet_bytes,
        "packet_savings_percent": savings_percent,
        "expansion_handle_count": len(packet["evidence"]),
        "source_titles": [item["title"] for item in packet["evidence"]],
    }


def _default_queries(vault_id: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT title, summary
            FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (vault_id,),
        ).fetchall()
    queries = []
    for row in rows:
        title = str(row["title"] or "").strip()
        summary = " ".join(str(row["summary"] or "").split())
        query = title or summary[:80]
        if query:
            queries.append(query)
    return queries or ["project context", "bridge context", "chat memory"]


def _source_snippet_from_row(row) -> dict:
    source = dict_from_row(row)
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
        "",
        "| Query | Results | Memory items | Working memory | Raw bytes | Packet bytes | Savings |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["query"].replace("|", "/"),
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
