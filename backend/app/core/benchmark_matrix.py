from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.context_memory import get_context_memory
from backend.app.core.context_packets import build_bridge_context_packet, render_context_packet
from backend.app.core.context_reduction import build_context_reduction_plan, estimate_tokens, salient_excerpt
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import embed_text
from backend.app.core.encrypted_storage import source_from_encrypted_row
from backend.app.core.extraction import ExtractionError, extract_pages_from_path
from backend.app.core.pdf_pipeline import PdfPipelineError, extract_pdf_document_with_backend, pdf_parser_runtime_status
from backend.app.core.turbovec_runtime import semantic_search_results


def benchmark_pdf_parser_corpus(paths: list[str | Path], *, parsers: list[str] | None = None) -> dict:
    selected_parsers = parsers or ["builtin", "opendataloader_pdf"]
    rows = []
    parser_rollups: dict[str, dict[str, float | int]] = {}
    for parser_name in selected_parsers:
        parser_rollups[parser_name] = {
            "document_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_seconds": 0.0,
            "total_pages": 0,
            "total_chars": 0,
            "table_count": 0,
        }
        for raw_path in paths:
            source_path = Path(raw_path)
            started = time.perf_counter()
            try:
                document = extract_pdf_document_with_backend(source_path, parser_name)
                duration = time.perf_counter() - started
                parser = document.get("parser") or {}
                pages = document.get("pages") or []
                text = "\n\n".join(str(page) for page in pages)
                row = {
                    "parser": parser_name,
                    "path": str(source_path),
                    "status": "passed",
                    "seconds": round(duration, 4),
                    "page_count": len(pages),
                    "text_chars": len(text),
                    "table_count": len(parser.get("structured_tables") or []),
                    "mode": parser.get("mode") or "",
                    "issues": parser.get("issues") or [],
                }
                parser_rollups[parser_name]["success_count"] += 1
                parser_rollups[parser_name]["total_pages"] += len(pages)
                parser_rollups[parser_name]["total_chars"] += len(text)
                parser_rollups[parser_name]["table_count"] += len(parser.get("structured_tables") or [])
            except PdfPipelineError as exc:
                duration = time.perf_counter() - started
                row = {
                    "parser": parser_name,
                    "path": str(source_path),
                    "status": "failed",
                    "seconds": round(duration, 4),
                    "page_count": 0,
                    "text_chars": 0,
                    "table_count": 0,
                    "mode": "",
                    "issues": [str(exc)],
                }
                parser_rollups[parser_name]["failure_count"] += 1
            parser_rollups[parser_name]["document_count"] += 1
            parser_rollups[parser_name]["total_seconds"] += duration
            rows.append(row)
    report = {
        "report_id": f"pdf-benchmark-{uuid4()}",
        "generated_at": utc_now(),
        "runtime": pdf_parser_runtime_status(),
        "rows": rows,
        "parser_summaries": {
            name: _pdf_summary(name, rollup)
            for name, rollup in parser_rollups.items()
        },
    }
    return _write_benchmark_report("pdf-parser-benchmark", report)


def benchmark_ingestion_corpus(paths: list[str | Path], *, capture_payloads: bool = False) -> dict:
    rows = []
    captures: list[dict] = []
    type_rollups: dict[str, dict[str, float | int]] = {}
    for raw_path in paths:
        source_path = Path(raw_path)
        suffix = source_path.suffix.lower() or "unknown"
        started = time.perf_counter()
        try:
            title, pages = extract_pages_from_path(str(source_path))
            duration = time.perf_counter() - started
            text = "\n\n".join(pages)
            row = {
                "path": str(source_path),
                "title": title,
                "suffix": suffix,
                "status": "passed",
                "seconds": round(duration, 4),
                "page_count": len(pages),
                "text_chars": len(text),
            }
            if capture_payloads:
                captures.append(
                    {
                        "path": str(source_path),
                        "title": title,
                        "suffix": suffix,
                        "pages": pages,
                        "text": text,
                    }
                )
        except ExtractionError as exc:
            duration = time.perf_counter() - started
            row = {
                "path": str(source_path),
                "title": source_path.name,
                "suffix": suffix,
                "status": "failed",
                "seconds": round(duration, 4),
                "page_count": 0,
                "text_chars": 0,
                "error": str(exc),
            }
        rollup = type_rollups.setdefault(
            suffix,
            {"document_count": 0, "success_count": 0, "failure_count": 0, "total_seconds": 0.0, "text_chars": 0},
        )
        rollup["document_count"] += 1
        rollup["total_seconds"] += duration
        if row["status"] == "passed":
            rollup["success_count"] += 1
            rollup["text_chars"] += row["text_chars"]
        else:
            rollup["failure_count"] += 1
        rows.append(row)
    total_docs = len(rows)
    success_count = sum(1 for row in rows if row["status"] == "passed")
    total_seconds = round(sum(float(row["seconds"]) for row in rows), 4)
    report = {
        "report_id": f"ingestion-benchmark-{uuid4()}",
        "generated_at": utc_now(),
        "rows": rows,
        "operator_summary": {
            "document_count": total_docs,
            "success_count": success_count,
            "failure_count": total_docs - success_count,
            "total_seconds": total_seconds,
            "avg_seconds_per_document": round(total_seconds / max(total_docs, 1), 4),
            "type_breakdown": {
                suffix: {
                    **rollup,
                    "avg_seconds_per_document": round(float(rollup["total_seconds"]) / max(int(rollup["document_count"]), 1), 4),
                }
                for suffix, rollup in sorted(type_rollups.items())
            },
        },
        "product_summary": {
            "documents_ready_for_search": success_count,
            "import_success_rate_percent": round((success_count / max(total_docs, 1)) * 100.0, 2),
            "median_document_latency_seconds": _median(float(row["seconds"]) for row in rows if row["status"] == "passed"),
            "user_claims": [
                "Measures time-to-readable-text for each supported artifact type.",
                "Shows which formats are fast, brittle, or still failing under current packaging/runtime assumptions.",
            ],
        },
    }
    result = _write_benchmark_report("ingestion-benchmark", report)
    if capture_payloads:
        result["_captures"] = captures
    return result


def export_context_strategy_report(
    vault_id: str,
    *,
    cluster_id: str | None = None,
    queries: list[str | dict] | None = None,
    limit: int = 6,
    strict: bool = False,
) -> dict:
    query_specs = _normalize_query_specs(queries or _default_queries(vault_id))
    if strict:
        validate_context_benchmark_inputs(vault_id, cluster_id=cluster_id, query_specs=query_specs)
    rows = []
    for query_spec in query_specs:
        rows.append(_context_strategy_row(vault_id, query_spec=query_spec, cluster_id=cluster_id, limit=limit))
    if strict:
        total_hits = sum(int(row.get("result_count") or 0) for row in rows)
        if total_hits <= 0:
            raise RuntimeError(
                f"Context strategy benchmark for vault '{vault_id}' returned zero retrieval hits across {len(rows)} queries."
            )
    report = {
        "report_id": f"context-strategy-benchmark-{uuid4()}",
        "generated_at": utc_now(),
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "query_count": len(rows),
        "rows": rows,
        "operator_summary": {
            "average_raw_tokens": round(sum(row["raw_tokens"] for row in rows) / max(len(rows), 1), 2),
            "average_current_cml_tokens": round(sum(row["current_cml_tokens"] for row in rows) / max(len(rows), 1), 2),
            "average_current_cml_reduction_percent": round(
                sum(row["strategies"]["current_cml"]["reduction_percent"] for row in rows) / max(len(rows), 1), 2
            ),
        },
        "product_summary": {
            "warm_cache_average_reduction_percent": round(
                sum(row["strategies"]["context_caching"]["warm_reduction_percent"] for row in rows) / max(len(rows), 1),
                2,
            ),
            "best_average_strategy": _best_average_strategy(rows),
            "user_claims": [
                "Compares the current CML packet against repeat-turn cache hits and two aggressive reference compression policies.",
                "Separates first-turn compression from repeat-turn cache behavior so token savings claims stay honest.",
            ],
        },
    }
    return _write_benchmark_report("context-strategy-benchmark", report)


def validate_context_benchmark_inputs(
    vault_id: str,
    *,
    cluster_id: str | None = None,
    query_specs: list[dict] | None = None,
) -> None:
    normalized = query_specs or _normalize_query_specs(_default_queries(vault_id))
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise RuntimeError(f"Context strategy benchmark vault '{vault_id}' does not exist.")
        params: list[object] = [vault_id]
        cluster_clause = ""
        if cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, vault_id),
            ).fetchone()
            if cluster is None:
                raise RuntimeError(f"Cluster '{cluster_id}' does not exist in vault '{vault_id}'.")
            cluster_clause = " AND cluster_id = ?"
            params.append(cluster_id)
        source_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM sources WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL{cluster_clause}",
                params,
            ).fetchone()[0]
        )
        chunk_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM source_chunks WHERE vault_id = ?{cluster_clause}",
                params,
            ).fetchone()[0]
        )
    if source_count <= 0:
        raise RuntimeError(f"Context strategy benchmark vault '{vault_id}' has no indexed sources.")
    if chunk_count <= 0:
        raise RuntimeError(f"Context strategy benchmark vault '{vault_id}' has zero indexed chunks.")
    if not normalized:
        raise RuntimeError(f"Context strategy benchmark vault '{vault_id}' has no usable queries.")


def _context_strategy_row(vault_id: str, *, query_spec: dict, cluster_id: str | None, limit: int) -> dict:
    query = str(query_spec["prompt"])
    embedding = embed_text(query)
    search = semantic_search_results(vault_id, embedding, cluster_id=cluster_id, limit=max(1, min(limit, 12)))
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
        memory_items, working_memory = get_context_memory(conn, vault_id=vault_id, cluster_id=cluster_id, query=query)
        sources_by_id = {row["id"]: _source_snippet_from_row(conn, row) for row in source_rows}
    ordered_sources = []
    for source_id in source_ids:
        snippet = sources_by_id.get(source_id)
        if snippet:
            ordered_sources.append(snippet)
    raw_payload = {
        "query": query,
        "selected_clusters": [dict_from_row(row) for row in cluster_rows],
        "source_snippets": ordered_sources,
        "memory_items": memory_items,
        "working_memory": working_memory,
    }
    raw_tokens = estimate_tokens(json.dumps(raw_payload, ensure_ascii=False))
    base_packet = build_bridge_context_packet(
        query=query,
        context_request_id=f"benchmark-{uuid4()}",
        selected_clusters=[dict_from_row(row) for row in cluster_rows],
        source_snippets=ordered_sources,
        warnings=[],
        memory_items=memory_items,
        working_memory=working_memory,
    )
    current_text = render_context_packet(base_packet)
    current_tokens = estimate_tokens(current_text)
    current_plan = build_context_reduction_plan(
        prompt=query,
        citations=[
            {
                "source_id": item.get("id"),
                "source_title": item.get("title"),
                "snippet": item.get("snippet") or item.get("summary") or "",
                "score": 1.0,
            }
            for item in ordered_sources
        ],
        recent_turns=[],
        memory_items=memory_items,
        working_memory=working_memory,
        token_budget=max(1200, current_tokens),
        cluster_descriptions=[f"{row['name']} {row['description']}" for row in [dict_from_row(item) for item in cluster_rows]],
    )
    mem_u_tokens = _reference_strategy_tokens(query=query, memory_items=memory_items, working_memory=working_memory, ordered_sources=ordered_sources, mode="mem_u_style")
    context_mode_tokens = _reference_strategy_tokens(query=query, memory_items=memory_items, working_memory=working_memory, ordered_sources=ordered_sources, mode="context_mode_style")
    warm_cache_tokens = max(estimate_tokens(query) + 24, min(current_tokens, 96))
    return {
        "query": query,
        "result_count": len(results),
        "raw_tokens": raw_tokens,
        "current_cml_tokens": current_tokens,
        "current_cml_diagnostics": current_plan["diagnostics"],
        "strategies": {
            "current_cml": {
                "implementation": "product_code",
                "tokens": current_tokens,
                "reduction_percent": _reduction_percent(raw_tokens, current_tokens),
            },
            "context_caching": {
                "implementation": "product_reference_policy",
                "cold_tokens": current_tokens,
                "warm_tokens": warm_cache_tokens,
                "cold_reduction_percent": _reduction_percent(raw_tokens, current_tokens),
                "warm_reduction_percent": _reduction_percent(raw_tokens, warm_cache_tokens),
            },
            "mem_u_style": {
                "implementation": "reference_policy",
                "tokens": mem_u_tokens,
                "reduction_percent": _reduction_percent(raw_tokens, mem_u_tokens),
            },
            "context_mode_style": {
                "implementation": "reference_policy",
                "tokens": context_mode_tokens,
                "reduction_percent": _reduction_percent(raw_tokens, context_mode_tokens),
            },
        },
    }


def _reference_strategy_tokens(*, query: str, memory_items: list[dict], working_memory: dict, ordered_sources: list[dict], mode: str) -> int:
    if mode == "mem_u_style":
        memory_text = " ".join(str(item.get("summary") or "") for item in memory_items[:4])
        evidence_text = " ".join(salient_excerpt(str(item.get("snippet") or item.get("summary") or ""), prompt=query, token_budget=40) for item in ordered_sources[:2])
        payload = "\n".join([query, str(working_memory.get("summary") or ""), memory_text, evidence_text]).strip()
        return estimate_tokens(payload)
    evidence = [
        f"{item.get('title')}: {salient_excerpt(str(item.get('snippet') or item.get('summary') or ''), prompt=query, token_budget=24)}"
        for item in ordered_sources[:3]
    ]
    payload = "\n".join([query, *evidence]).strip()
    return estimate_tokens(payload)


def _pdf_summary(name: str, rollup: dict[str, float | int]) -> dict:
    document_count = int(rollup["document_count"])
    return {
        "parser": name,
        "document_count": document_count,
        "success_count": int(rollup["success_count"]),
        "failure_count": int(rollup["failure_count"]),
        "total_seconds": round(float(rollup["total_seconds"]), 4),
        "avg_seconds_per_document": round(float(rollup["total_seconds"]) / max(document_count, 1), 4),
        "avg_pages_per_document": round(int(rollup["total_pages"]) / max(document_count, 1), 2),
        "avg_chars_per_document": round(int(rollup["total_chars"]) / max(document_count, 1), 2),
        "table_count": int(rollup["table_count"]),
    }


def _best_average_strategy(rows: list[dict]) -> str:
    scores: dict[str, float] = {"current_cml": 0.0, "mem_u_style": 0.0, "context_mode_style": 0.0}
    for row in rows:
        for key in scores:
            scores[key] += float(row["strategies"][key]["reduction_percent"])
    return max(scores, key=scores.get) if scores else "current_cml"


def _reduction_percent(raw_tokens: int, final_tokens: int) -> float:
    return round(max(0.0, (1.0 - (final_tokens / max(raw_tokens, 1))) * 100.0), 2)


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
    prompts = prompts or ["project context", "browser extension", "pdf ingestion"]
    return [{"prompt": prompt} for prompt in prompts[:5]]


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
            if prompt:
                normalized.append({"prompt": prompt})
    return normalized


def _write_benchmark_report(prefix: str, payload: dict) -> dict:
    output_dir = get_settings().data_dir / "benchmark-reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_id = str(payload.get("report_id") or f"{prefix}-{uuid4()}")
    json_path = output_dir / f"{report_id}.json"
    md_path = output_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(_report_markdown(prefix, payload), encoding="utf-8")
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    return payload


def _report_markdown(prefix: str, payload: dict) -> str:
    lines = [
        f"# {prefix}",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        f"- Report id: {payload.get('report_id')}",
    ]
    if "operator_summary" in payload:
        lines.append(f"- Operator summary: {json.dumps(payload['operator_summary'], ensure_ascii=False)}")
    if "product_summary" in payload:
        lines.append(f"- Product summary: {json.dumps(payload['product_summary'], ensure_ascii=False)}")
    if "parser_summaries" in payload:
        lines.append(f"- Parser summaries: {json.dumps(payload['parser_summaries'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _median(values) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return round(ordered[midpoint], 4)
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2.0, 4)
