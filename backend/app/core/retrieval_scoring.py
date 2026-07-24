import math
import json
import os
import threading
import time
from array import array
from collections import OrderedDict
from collections import Counter, defaultdict
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text, tokenize
from backend.app.core.encrypted_storage import chunk_from_encrypted_row
from backend.app.core.vector_maintenance import active_embedding_selector


BM25_K1 = 1.5
BM25_B = 0.75
SOURCE_CLASS_WEIGHTS = {
    "document": 1.0,
    "external_artifact": 0.85,
    "external_transcript": 0.72,
    "chat_transcript": 0.65,
}


@dataclass(frozen=True)
class RetrievalFixture:
    query: str
    must_include_source_ids: tuple[str, ...] = ()
    must_exclude_source_ids: tuple[str, ...] = ()


DEFAULT_RETRIEVAL_FIXTURES = (
    RetrievalFixture(query="project context OCR packaging", must_include_source_ids=()),
    RetrievalFixture(query="bridge permissions active vault", must_include_source_ids=()),
    RetrievalFixture(query="chat transcript memory weighting", must_include_source_ids=()),
)

_PREPARED_CACHE_LIMIT = 1
_PREPARED_CACHE: OrderedDict[tuple, "PreparedRetrievalCorpus"] = OrderedDict()
_PREPARED_CACHE_LOCK = threading.RLock()


@dataclass
class TermPostings:
    indices: array
    frequencies: array


@dataclass
class PreparedRetrievalCorpus:
    rows: list[dict]
    embeddings: np.ndarray
    source_classes: list[str]
    source_class_weights: np.ndarray
    document_lengths: np.ndarray
    average_document_length: float
    postings: dict[str, TermPostings]
    preparation_seconds: float
    numeric_index_bytes: int


def scoring_ledger(vault_id: str, query: str, *, cluster_id: str | None = None, limit: int = 20) -> dict:
    if os.environ.get("CML_RETRIEVAL_SCORER", "prepared").strip().lower() == "legacy":
        return _legacy_scoring_ledger(vault_id, query, cluster_id=cluster_id, limit=limit)

    prepared, cache_hit = _prepared_corpus(vault_id, cluster_id)
    query_tokens = tokenize(query)
    query_vector = embed_text(query)
    semantic_scores = _prepared_semantic_scores(query_vector, prepared)
    lexical_scores = _prepared_bm25_scores(query_tokens, prepared)
    combined_scores = (
        (semantic_scores * 0.7) + (lexical_scores * 0.3)
    ) * prepared.source_class_weights
    result_limit = max(1, min(limit, 100))
    # The legacy scorer sorts the already rounded public score. Preserve that
    # behavior exactly, including stable row-order ties.
    ranked_indices = sorted(
        range(len(prepared.rows)),
        key=lambda index: round(float(combined_scores[index]), 4),
        reverse=True,
    )[:result_limit]
    results = [
        _ledger_item(
            prepared.rows[int(index)],
            semantic=float(semantic_scores[int(index)]),
            lexical=float(lexical_scores[int(index)]),
            source_class=prepared.source_classes[int(index)],
            combined=float(combined_scores[int(index)]),
        )
        for index in ranked_indices
    ]
    return {
        "query": query,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "weights": {"semantic": 0.7, "bm25": 0.3},
        "source_class_weights": SOURCE_CLASS_WEIGHTS,
        "chunks_considered": len(prepared.rows),
        "retrieval_index": {
            "kind": "prepared_exact_hybrid_v1",
            "cache_hit": cache_hit,
            "preparation_seconds": round(prepared.preparation_seconds, 4),
            "numeric_index_bytes": prepared.numeric_index_bytes,
        },
        "results": results,
    }


def _legacy_scoring_ledger(
    vault_id: str,
    query: str,
    *,
    cluster_id: str | None = None,
    limit: int = 20,
) -> dict:
    rows = _chunk_rows(vault_id, cluster_id)
    query_tokens = tokenize(query)
    query_vector = embed_text(query)
    bm25_scores = _bm25_scores(query_tokens, rows)
    ledger = []
    for row in rows:
        semantic = cosine_similarity(query_vector, decode_embedding(row["embedding"]))
        lexical = bm25_scores.get(row["chunk_id"], 0.0)
        source_class = _source_class(row)
        source_class_weight = SOURCE_CLASS_WEIGHTS[source_class]
        combined = ((semantic * 0.7) + (lexical * 0.3)) * source_class_weight
        ledger.append(
            _ledger_item(
                row,
                semantic=semantic,
                lexical=lexical,
                source_class=source_class,
                combined=combined,
            )
        )
    ledger.sort(key=lambda item: item["combined_score"], reverse=True)
    return {
        "query": query,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "weights": {"semantic": 0.7, "bm25": 0.3},
        "source_class_weights": SOURCE_CLASS_WEIGHTS,
        "chunks_considered": len(rows),
        "retrieval_index": {
            "kind": "legacy_exact_hybrid_v1",
            "cache_hit": False,
            "preparation_seconds": 0.0,
        },
        "results": ledger[: max(1, min(limit, 100))],
    }


def _ledger_item(
    row: dict,
    *,
    semantic: float,
    lexical: float,
    source_class: str,
    combined: float,
) -> dict:
    return {
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "source_type": row["source_type"],
        "cluster_id": row["cluster_id"],
        "chunk_id": row["chunk_id"],
        "page_id": row["page_id"],
        "page_number": row["page_number"],
        "chunk_index": row["chunk_index"],
        "semantic_score": round(semantic, 4),
        "bm25_score": round(lexical, 4),
        "source_class": source_class,
        "source_class_weight": SOURCE_CLASS_WEIGHTS[source_class],
        "combined_score": round(combined, 4),
        "snippet": row["text"],
    }


def compare_source_classes(vault_id: str, query: str, *, cluster_id: str | None = None, limit_per_class: int = 5) -> dict:
    ledger = scoring_ledger(vault_id, query, cluster_id=cluster_id, limit=100)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in ledger["results"]:
        grouped[item["source_class"]].append(item)
    return {
        "query": query,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "intent": "compare_source_classes",
        "groups": {
            source_class: items[: max(1, min(limit_per_class, 20))]
            for source_class, items in sorted(grouped.items())
        },
    }


def threshold_benchmark(
    vault_id: str,
    *,
    fixtures: list[dict] | None = None,
    thresholds: list[float] | None = None,
) -> dict:
    selected_fixtures = _normalize_fixtures(fixtures)
    selected_thresholds = thresholds or [0.15, 0.25, 0.35, 0.45, 0.55]
    rows = []
    for fixture in selected_fixtures:
        ledger = scoring_ledger(vault_id, fixture.query, limit=100)
        for threshold in selected_thresholds:
            passing = [item for item in ledger["results"] if item["combined_score"] >= threshold]
            source_ids = {item["source_id"] for item in passing}
            required = set(fixture.must_include_source_ids)
            excluded = set(fixture.must_exclude_source_ids)
            rows.append(
                {
                    "query": fixture.query,
                    "threshold": threshold,
                    "chunks_passing": len(passing),
                    "sources_passing": len(source_ids),
                    "required_sources_found": sorted(required & source_ids),
                    "required_sources_missing": sorted(required - source_ids),
                    "excluded_sources_found": sorted(excluded & source_ids),
                    "passes_fixture": bool(required <= source_ids and not (excluded & source_ids)),
                }
            )
    return {
        "vault_id": vault_id,
        "thresholds": selected_thresholds,
        "fixture_count": len(selected_fixtures),
        "rows": rows,
    }


def export_benchmark_report(vault_id: str, *, fixtures: list[dict] | None = None) -> dict:
    report = threshold_benchmark(vault_id, fixtures=fixtures)
    output_dir = get_settings().data_dir / "benchmark-reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_id = f"query-benchmark-{uuid4()}"
    json_path = output_dir / f"{report_id}.json"
    md_path = output_dir / f"{report_id}.md"
    payload = {**report, "generated_at": utc_now(), "report_id": report_id}
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(_benchmark_markdown(payload), encoding="utf-8")
    return {
        "report_id": report_id,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "row_count": len(report["rows"]),
    }


def retrieval_eval_fixtures() -> dict:
    return {
        "fixtures": [
            {
                "query": fixture.query,
                "must_include_source_ids": list(fixture.must_include_source_ids),
                "must_exclude_source_ids": list(fixture.must_exclude_source_ids),
            }
            for fixture in DEFAULT_RETRIEVAL_FIXTURES
        ]
    }


def _chunk_rows(vault_id: str, cluster_id: str | None) -> list[dict]:
    selector = active_embedding_selector()
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn,
            vault_id,
            embedding_model_id=selector["embedding_model_id"],
            index_version=selector["index_version"],
        )
        tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
        rows = conn.execute(
            f"""
            SELECT
                chunks.id AS chunk_id,
                chunks.source_id,
                chunks.vault_id,
                chunks.page_id,
                chunks.cluster_id,
                chunks.chunk_index,
                chunks.text,
                chunks.embedding,
                sources.title AS source_title,
                sources.source_type,
                sources.tags,
                pages.page_number
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            LEFT JOIN source_pages pages ON pages.id = chunks.page_id
            WHERE chunks.vault_id = ?
              AND sources.deleted_at IS NULL
              AND sources.state = 'indexed'
              {tuple_clause}
              {cluster_clause}
            """,
            [params[0], *tuple_params, *params[1:]],
        ).fetchall()
        return [chunk_from_encrypted_row(conn, row) for row in rows]


def _chunk_revision(vault_id: str, cluster_id: str | None) -> tuple:
    selector = active_embedding_selector()
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn,
            vault_id,
            embedding_model_id=selector["embedding_model_id"],
            index_version=selector["index_version"],
        )
        tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS chunk_count,
                COALESCE(MAX(chunks.indexed_at), '') AS max_indexed_at,
                COALESCE(MAX(chunks.created_at), '') AS max_chunk_created_at,
                COALESCE(MAX(sources.updated_at), '') AS max_source_updated_at,
                COALESCE(MAX(sources.deleted_at), '') AS max_source_deleted_at
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.vault_id = ?
              AND sources.deleted_at IS NULL
              AND sources.state = 'indexed'
              {tuple_clause}
              {cluster_clause}
            """,
            [params[0], *tuple_params, *params[1:]],
        ).fetchone()
    snapshot_key = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return (
        vault_id,
        cluster_id or "",
        selector["embedding_model_id"],
        selector["index_version"],
        snapshot_key,
        int(row["chunk_count"]),
        str(row["max_indexed_at"]),
        str(row["max_chunk_created_at"]),
        str(row["max_source_updated_at"]),
        str(row["max_source_deleted_at"]),
    )


def _prepared_corpus(
    vault_id: str, cluster_id: str | None
) -> tuple[PreparedRetrievalCorpus, bool]:
    revision = _chunk_revision(vault_id, cluster_id)
    with _PREPARED_CACHE_LOCK:
        cached = _PREPARED_CACHE.get(revision)
        if cached is not None:
            _PREPARED_CACHE.move_to_end(revision)
            return cached, True

        rows = _chunk_rows(vault_id, cluster_id)
        final_revision = _chunk_revision(vault_id, cluster_id)
        if final_revision != revision:
            rows = _chunk_rows(vault_id, cluster_id)
            revision = final_revision
        prepared = _prepare_rows(rows)
        _PREPARED_CACHE[revision] = prepared
        _PREPARED_CACHE.move_to_end(revision)
        while len(_PREPARED_CACHE) > _PREPARED_CACHE_LIMIT:
            _PREPARED_CACHE.popitem(last=False)
        return prepared, False


def _prepare_rows(rows: list[dict]) -> PreparedRetrievalCorpus:
    started = time.perf_counter()
    first_vector = decode_embedding(rows[0]["embedding"]) if rows else []
    dimension = len(first_vector)
    embeddings = np.empty((len(rows), dimension), dtype=np.float64)
    prepared_rows: list[dict] = []
    for index, row in enumerate(rows):
        vector = first_vector if index == 0 else decode_embedding(row["embedding"])
        if len(vector) != dimension:
            raise RuntimeError(
                "eligible retrieval chunks have inconsistent embedding dimensions: "
                f"{len(vector)} != {dimension}"
            )
        embeddings[index] = vector
        prepared_row = dict(row)
        prepared_row.pop("embedding", None)
        prepared_rows.append(prepared_row)
    source_classes = [_source_class(row) for row in prepared_rows]
    source_class_weights = np.asarray(
        [SOURCE_CLASS_WEIGHTS[source_class] for source_class in source_classes],
        dtype=np.float64,
    )
    document_lengths = np.zeros(len(rows), dtype=np.float64)
    postings: dict[str, TermPostings] = {}
    for index, row in enumerate(prepared_rows):
        counts = Counter(tokenize(row["text"]))
        document_lengths[index] = sum(counts.values())
        for token, frequency in counts.items():
            posting = postings.get(token)
            if posting is None:
                posting = TermPostings(array("I"), array("I"))
                postings[token] = posting
            posting.indices.append(index)
            posting.frequencies.append(frequency)
    average_document_length = (
        float(document_lengths.sum()) / max(len(rows), 1)
    )
    return PreparedRetrievalCorpus(
        rows=prepared_rows,
        embeddings=embeddings,
        source_classes=source_classes,
        source_class_weights=source_class_weights,
        document_lengths=document_lengths,
        average_document_length=average_document_length,
        postings=postings,
        preparation_seconds=time.perf_counter() - started,
        numeric_index_bytes=(
            int(embeddings.nbytes)
            + int(source_class_weights.nbytes)
            + int(document_lengths.nbytes)
            + sum(
                len(posting.indices) * posting.indices.itemsize
                + len(posting.frequencies) * posting.frequencies.itemsize
                for posting in postings.values()
            )
        ),
    )


def _prepared_semantic_scores(
    query_vector: list[float], prepared: PreparedRetrievalCorpus
) -> np.ndarray:
    if not prepared.rows:
        return np.zeros(0, dtype=np.float64)
    vector = np.asarray(query_vector, dtype=np.float64)
    if vector.shape != (prepared.embeddings.shape[1],):
        raise RuntimeError(
            "query embedding dimension does not match the active retrieval index: "
            f"{vector.shape} != {(prepared.embeddings.shape[1],)}"
        )
    return prepared.embeddings @ vector


def _prepared_bm25_scores(
    query_tokens: list[str], prepared: PreparedRetrievalCorpus
) -> np.ndarray:
    total_documents = len(prepared.rows)
    raw_scores = np.zeros(total_documents, dtype=np.float64)
    if not total_documents or not query_tokens:
        return raw_scores
    average_length = max(prepared.average_document_length, 1.0)
    for token, query_frequency in Counter(query_tokens).items():
        posting = prepared.postings.get(token)
        if posting is None:
            continue
        indices = np.frombuffer(posting.indices, dtype=np.uint32)
        frequencies = np.frombuffer(posting.frequencies, dtype=np.uint32).astype(
            np.float64
        )
        document_frequency = len(posting.indices)
        idf = math.log(
            1
            + (
                (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
        )
        denominator = frequencies + BM25_K1 * (
            1
            - BM25_B
            + BM25_B * (prepared.document_lengths[indices] / average_length)
        )
        raw_scores[indices] += (
            idf * ((frequencies * (BM25_K1 + 1)) / denominator) * query_frequency
        )
    max_score = float(raw_scores.max(initial=0.0))
    return raw_scores if max_score <= 0 else raw_scores / max_score


def clear_prepared_retrieval_cache() -> None:
    with _PREPARED_CACHE_LOCK:
        _PREPARED_CACHE.clear()


def _bm25_scores(query_tokens: list[str], rows: list[dict]) -> dict[str, float]:
    if not rows or not query_tokens:
        return {}
    documents = {row["chunk_id"]: tokenize(row["text"]) for row in rows}
    lengths = {chunk_id: len(tokens) for chunk_id, tokens in documents.items()}
    average_length = sum(lengths.values()) / max(len(lengths), 1)
    document_frequency: dict[str, int] = defaultdict(int)
    for tokens in documents.values():
        for token in set(tokens):
            document_frequency[token] += 1
    total_documents = len(documents)
    raw_scores: dict[str, float] = {}
    for chunk_id, tokens in documents.items():
        counts = Counter(tokens)
        length = max(lengths[chunk_id], 1)
        score = 0.0
        for token in query_tokens:
            frequency = counts.get(token, 0)
            if frequency == 0:
                continue
            idf = math.log(1 + ((total_documents - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5)))
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * (length / max(average_length, 1)))
            score += idf * ((frequency * (BM25_K1 + 1)) / denominator)
        raw_scores[chunk_id] = score
    max_score = max(raw_scores.values(), default=0.0)
    if max_score <= 0:
        return raw_scores
    return {chunk_id: score / max_score for chunk_id, score in raw_scores.items()}


def _source_class(row: dict) -> str:
    source_type = str(row.get("source_type") or "").lower()
    title = str(row.get("source_title") or "").lower()
    tags = _json_list(row.get("tags"))
    normalized_tags = {str(tag).lower() for tag in tags}
    if source_type in {"external_transcript", "mcp_external_turn"}:
        return "external_transcript"
    if source_type in {"external_artifact", "mcp_artifact"}:
        return "external_artifact"
    if "chat transcript" in title or {"chat", "transcript"} <= normalized_tags:
        return "chat_transcript"
    return "document"


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _benchmark_markdown(report: dict) -> str:
    lines = [
        "# Query Benchmark Report",
        "",
        f"- Report ID: `{report['report_id']}`",
        f"- Vault ID: `{report['vault_id']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Fixtures: `{report['fixture_count']}`",
        "",
        "| Query | Threshold | Chunks Passing | Sources Passing | Passes |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['query']} | {row['threshold']} | {row['chunks_passing']} | "
            f"{row['sources_passing']} | {row['passes_fixture']} |"
        )
    return "\n".join(lines) + "\n"


def _normalize_fixtures(fixtures: list[dict] | None) -> list[RetrievalFixture]:
    if not fixtures:
        return list(DEFAULT_RETRIEVAL_FIXTURES)
    normalized = []
    for fixture in fixtures:
        query = str(fixture.get("query") or "").strip()
        if not query:
            continue
        normalized.append(
            RetrievalFixture(
                query=query,
                must_include_source_ids=tuple(str(item) for item in fixture.get("must_include_source_ids", [])),
                must_exclude_source_ids=tuple(str(item) for item in fixture.get("must_exclude_source_ids", [])),
            )
        )
    return normalized or list(DEFAULT_RETRIEVAL_FIXTURES)
