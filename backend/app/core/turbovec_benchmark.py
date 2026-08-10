from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.api.routes.sources import create_source_from_path
from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, init_db, utc_now
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text, reindex_source_chunks
from backend.app.schemas import SourcePathCreate

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency in some environments
    psutil = None

try:
    from turbovec import IdMapIndex
except ImportError:  # pragma: no cover - benchmark can still run current baseline
    IdMapIndex = None


@dataclass(frozen=True)
class BenchmarkChunkRow:
    chunk_id: str
    source_id: str
    title: str
    text: str
    embedding: str
    page_number: int | None = None


def discover_pdf_files(
    roots: list[str],
    *,
    max_files: int | None = None,
    exclude_roots: list[str] | None = None,
) -> list[Path]:
    if isinstance(roots, str):  # type: ignore[unreachable]
        roots = [roots]
    if isinstance(exclude_roots, str):  # type: ignore[unreachable]
        exclude_roots = [exclude_roots]
    discovered: list[Path] = []
    seen: set[str] = set()
    excluded = {
        str(Path(root).expanduser().resolve()).lower()
        for root in (exclude_roots or [])
        if root
    }
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.lower().endswith(".pdf"):
                    continue
                path = Path(dirpath) / filename
                resolved = path.resolve()
                normalized = str(resolved).lower()
                if normalized in seen:
                    continue
                if any(normalized.startswith(prefix) for prefix in excluded):
                    continue
                seen.add(normalized)
                discovered.append(path)
                if max_files is not None and len(discovered) >= max_files:
                    return discovered
    return discovered


def ensure_benchmark_vault(vault_id: str = "vault-benchmark-real") -> str:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (vault_id, "Real Vault Benchmark", str(settings.data_dir), now, now),
        )
    return vault_id


def warm_embedding_runtime() -> dict[str, Any]:
    started = time.perf_counter()
    vector = embed_text("cml turbovec benchmark warmup query")
    return {
        "dimensions": len(vector),
        "seconds": round(time.perf_counter() - started, 4),
    }


def ingest_pdf_corpus(pdf_paths: list[Path], *, vault_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    imported = 0
    failed: list[dict[str, str]] = []
    for path in pdf_paths:
        try:
            create_source_from_path(SourcePathCreate(vault_id=vault_id, path=str(path)))
            imported += 1
        except Exception as exc:  # pragma: no cover - depends on local corpus/runtime
            failed.append({"path": str(path), "error": str(exc)[:500]})
    return {
        "requested_files": len(pdf_paths),
        "imported_files": imported,
        "failed_files": len(failed),
        "failures": failed[:100],
        "seconds": round(time.perf_counter() - started, 4),
    }


def load_chunk_rows(vault_id: str) -> list[BenchmarkChunkRow]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                chunks.id AS chunk_id,
                chunks.source_id,
                chunks.text,
                chunks.embedding,
                sources.title AS title,
                pages.page_number
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            LEFT JOIN source_pages pages ON pages.id = chunks.page_id
            WHERE chunks.vault_id = ?
              AND sources.deleted_at IS NULL
              AND sources.state = 'indexed'
            ORDER BY chunks.created_at ASC
            """,
            (vault_id,),
        ).fetchall()
    return [
        BenchmarkChunkRow(
            chunk_id=str(row["chunk_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"] or ""),
            text=str(row["text"] or ""),
            embedding=str(row["embedding"] or ""),
            page_number=int(row["page_number"]) if row["page_number"] is not None else None,
        )
        for row in rows
    ]


def reindex_vault_sources(vault_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL
            ORDER BY created_at ASC
            """,
            (vault_id,),
        ).fetchall()
        chunks_indexed = 0
        for row in rows:
            chunks_indexed += reindex_source_chunks(conn, dict_from_row(row))
    return {
        "sources_indexed": len(rows),
        "chunks_indexed": chunks_indexed,
        "seconds": round(time.perf_counter() - started, 4),
    }


def sampled_queries(rows: list[BenchmarkChunkRow], *, limit: int = 20) -> list[str]:
    if not rows:
        return []
    sample_size = max(1, min(limit, len(rows)))
    step = max(1, math.floor(len(rows) / sample_size))
    queries: list[str] = []
    for index in range(0, len(rows), step):
        query = _query_from_text(rows[index].text)
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= sample_size:
            break
    return queries


def benchmark_current_scan(rows: list[BenchmarkChunkRow], queries: list[str], *, top_k: int = 10) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    search_latencies_ms: list[float] = []
    total_latencies_ms: list[float] = []
    embedding_latencies_ms: list[float] = []
    for query in queries:
        embed_started = time.perf_counter()
        query_vector = embed_text(query)
        embedding_ms = round((time.perf_counter() - embed_started) * 1000, 3)
        started = time.perf_counter()
        scored: list[tuple[float, str]] = []
        for row in rows:
            semantic = cosine_similarity(query_vector, decode_embedding(row.embedding))
            if semantic > 0:
                scored.append((semantic, row.chunk_id))
        scored.sort(key=lambda item: item[0], reverse=True)
        search_ms = round((time.perf_counter() - started) * 1000, 3)
        total_ms = round(embedding_ms + search_ms, 3)
        search_latencies_ms.append(search_ms)
        total_latencies_ms.append(total_ms)
        embedding_latencies_ms.append(embedding_ms)
        results.append(
            {
                "query": query,
                "embedding_ms": embedding_ms,
                "search_ms": search_ms,
                "total_ms": total_ms,
                "top_chunk_ids": [chunk_id for _score, chunk_id in scored[:top_k]],
            }
        )
    return _benchmark_summary("current_scan", search_latencies_ms, total_latencies_ms, embedding_latencies_ms, results)


def benchmark_turbovec_scan(
    rows: list[BenchmarkChunkRow],
    queries: list[str],
    *,
    top_k: int = 10,
    bit_width: int = 4,
    allowlist_chunk_ids: list[str] | None = None,
    persist_path: str | None = None,
) -> dict[str, Any]:
    if IdMapIndex is None:
        raise RuntimeError("turbovec is not installed in this Python environment")
    if not rows:
        return {
            "engine": "turbovec",
            "bit_width": bit_width,
            "query_count": 0,
            "latency_ms": {"min": 0.0, "median": 0.0, "max": 0.0, "avg": 0.0},
            "results": [],
            "build_seconds": 0.0,
            "persisted_index_bytes": 0,
            "allowlist_size": 0,
        }

    vectors = np.ascontiguousarray(np.array([decode_embedding(row.embedding) for row in rows], dtype=np.float32))
    if vectors.shape[1] <= 0 or vectors.shape[1] % 8 != 0:
        raise RuntimeError(f"turbovec requires embedding dimensions to be a positive multiple of 8, got {vectors.shape[1]}")
    ids = np.ascontiguousarray(np.array([stable_u64(row.chunk_id) for row in rows], dtype=np.uint64))
    id_lookup = {stable_u64(row.chunk_id): row.chunk_id for row in rows}
    row_index_by_id = {stable_u64(row.chunk_id): index for index, row in enumerate(rows)}

    build_started = time.perf_counter()
    index = IdMapIndex(dim=vectors.shape[1], bit_width=bit_width)
    index.add_with_ids(vectors, ids)
    index.prepare()
    build_seconds = round(time.perf_counter() - build_started, 4)

    allowlist: np.ndarray | None = None
    if allowlist_chunk_ids:
        allowlist = np.ascontiguousarray(
            np.array([stable_u64(chunk_id) for chunk_id in allowlist_chunk_ids], dtype=np.uint64)
        )

    persisted_index_bytes = 0
    if persist_path:
        output = Path(persist_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        index.write(str(output))
        if output.exists():
            persisted_index_bytes = output.stat().st_size

    results: list[dict[str, Any]] = []
    search_latencies_ms: list[float] = []
    total_latencies_ms: list[float] = []
    embedding_latencies_ms: list[float] = []
    for query in queries:
        embed_started = time.perf_counter()
        query_array = np.ascontiguousarray(np.array([embed_text(query)], dtype=np.float32))
        embedding_ms = round((time.perf_counter() - embed_started) * 1000, 3)
        started = time.perf_counter()
        candidate_k = min(
            int(len(allowlist)) if allowlist is not None else len(rows),
            max(top_k * 25, 50),
        )
        _scores, result_ids = index.search(
            query_array, k=candidate_k, allowlist=allowlist
        )
        approximate_ids = result_ids[0].tolist() if len(result_ids) > 0 else []
        reranked: list[tuple[float, int]] = []
        for value in approximate_ids:
            stable_id = int(value)
            row_index = row_index_by_id.get(stable_id)
            if row_index is None:
                continue
            score = cosine_similarity(query_array[0].tolist(), vectors[row_index].tolist())
            if score > 0:
                reranked.append((score, stable_id))
        reranked.sort(key=lambda item: item[0], reverse=True)
        top_ids = [id_lookup[value] for _score, value in reranked[:top_k]]
        search_ms = round((time.perf_counter() - started) * 1000, 3)
        total_ms = round(embedding_ms + search_ms, 3)
        search_latencies_ms.append(search_ms)
        total_latencies_ms.append(total_ms)
        embedding_latencies_ms.append(embedding_ms)
        results.append(
            {
                "query": query,
                "embedding_ms": embedding_ms,
                "search_ms": search_ms,
                "total_ms": total_ms,
                "top_chunk_ids": top_ids,
                "score_count": len(reranked),
                "candidate_count": len(reranked),
                "approximate_candidate_count": len(approximate_ids),
            }
        )
    summary = _benchmark_summary("turbovec", search_latencies_ms, total_latencies_ms, embedding_latencies_ms, results)
    summary.update(
        {
            "bit_width": bit_width,
            "build_seconds": build_seconds,
            "persisted_index_bytes": persisted_index_bytes,
            "allowlist_size": int(len(allowlist)) if allowlist is not None else len(rows),
        }
    )
    return summary


def overlap_report(current: dict[str, Any], candidate: dict[str, Any], *, top_k: int = 10) -> dict[str, Any]:
    current_by_query = {item["query"]: item for item in current.get("results", [])}
    overlaps: list[dict[str, Any]] = []
    for item in candidate.get("results", []):
        baseline = current_by_query.get(item["query"])
        if baseline is None:
            continue
        baseline_ids = list(baseline.get("top_chunk_ids", []))[:top_k]
        candidate_ids = list(item.get("top_chunk_ids", []))[:top_k]
        shared = len(set(baseline_ids) & set(candidate_ids))
        overlaps.append(
            {
                "query": item["query"],
                "shared_at_k": shared,
                "overlap_ratio": round(shared / max(1, min(len(baseline_ids), top_k)), 4),
            }
        )
    ratios = [item["overlap_ratio"] for item in overlaps]
    return {
        "top_k": top_k,
        "queries_compared": len(overlaps),
        "avg_overlap_ratio": round(statistics.fmean(ratios), 4) if ratios else 0.0,
        "min_overlap_ratio": min(ratios) if ratios else 0.0,
        "overlaps": overlaps,
    }


def corpus_stats(rows: list[BenchmarkChunkRow]) -> dict[str, Any]:
    embedding_lengths = [len(row.embedding.encode("utf-8")) for row in rows]
    text_lengths = [len(row.text.encode("utf-8")) for row in rows]
    source_ids = {row.source_id for row in rows}
    return {
        "source_count": len(source_ids),
        "chunk_count": len(rows),
        "avg_embedding_bytes": round(statistics.fmean(embedding_lengths), 2) if embedding_lengths else 0.0,
        "avg_chunk_text_bytes": round(statistics.fmean(text_lengths), 2) if text_lengths else 0.0,
        "total_embedding_bytes": int(sum(embedding_lengths)),
        "total_chunk_text_bytes": int(sum(text_lengths)),
    }


def process_metrics() -> dict[str, Any]:
    if psutil is None:
        return {"rss_bytes": None, "cpu_seconds": None}
    process = psutil.Process(os.getpid())
    cpu_times = process.cpu_times()
    return {
        "rss_bytes": int(process.memory_info().rss),
        "cpu_seconds": round(float(cpu_times.user + cpu_times.system), 4),
    }


def projected_costs(
    *,
    chunk_count: int,
    avg_embedding_bytes: float,
    avg_chunk_text_bytes: float,
    dim: int = 384,
    bit_width: int = 4,
) -> dict[str, Any]:
    current_embedding_bytes = int(chunk_count * avg_embedding_bytes)
    current_text_bytes = int(chunk_count * avg_chunk_text_bytes)
    turbovec_vector_bytes = int((chunk_count * dim * bit_width) / 8)
    turbovec_norm_bytes = int(chunk_count * 4)
    turbovec_total_bytes = turbovec_vector_bytes + turbovec_norm_bytes + (chunk_count * 8)
    dot_products = chunk_count * dim
    return {
        "chunk_count": chunk_count,
        "current_architecture": {
            "embedding_storage_bytes_estimate": current_embedding_bytes,
            "chunk_text_bytes_estimate": current_text_bytes,
            "query_complexity": f"O({chunk_count} * {dim}) exact scan plus JSON decode",
            "dot_product_multiply_adds_per_query": dot_products,
        },
        "turbovec_4bit_projection": {
            "index_bytes_estimate": turbovec_total_bytes,
            "query_complexity": "compressed SIMD ANN/rerank over allowed ids",
            "vector_code_bytes_only": turbovec_vector_bytes,
            "norm_bytes": turbovec_norm_bytes,
            "id_table_bytes": chunk_count * 8,
        },
        "notes": [
            "The current-architecture estimate is based on average stored embedding JSON bytes from the measured corpus.",
            "The turbovec estimate is an inference from the documented .tvim format plus 4-bit packed-code math.",
        ],
    }


def stable_u64(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()[:8]
    candidate = int.from_bytes(digest, "little", signed=False)
    return candidate or 1


def _query_from_text(text: str, token_limit: int = 6) -> str:
    tokens = [token.strip(".,:;!?()[]{}<>\"'").lower() for token in text.split()]
    tokens = [token for token in tokens if len(token) >= 4]
    if not tokens:
        return ""
    return " ".join(tokens[:token_limit])


def _latency_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "min": min(values),
        "median": round(statistics.median(values), 3),
        "max": max(values),
        "avg": round(statistics.fmean(values), 3),
    }


def _benchmark_summary(
    engine: str,
    search_latencies_ms: list[float],
    total_latencies_ms: list[float],
    embedding_latencies_ms: list[float],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "engine": engine,
        "query_count": len(results),
        "search_latency_ms": _latency_stats(search_latencies_ms),
        "total_latency_ms": _latency_stats(total_latencies_ms),
        "embedding_latency_ms": _latency_stats(embedding_latencies_ms),
        "results": results,
    }


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
