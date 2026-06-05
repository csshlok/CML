import math
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text, tokenize
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


def scoring_ledger(vault_id: str, query: str, *, cluster_id: str | None = None, limit: int = 20) -> dict:
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
            {
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
                "source_class_weight": source_class_weight,
                "combined_score": round(combined, 4),
                "snippet": row["text"],
            }
        )
    ledger.sort(key=lambda item: item["combined_score"], reverse=True)
    return {
        "query": query,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "weights": {"semantic": 0.7, "bm25": 0.3},
        "source_class_weights": SOURCE_CLASS_WEIGHTS,
        "chunks_considered": len(rows),
        "results": ledger[: max(1, min(limit, 100))],
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
        rows = conn.execute(
            f"""
            SELECT
                chunks.id AS chunk_id,
                chunks.source_id,
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
              AND chunks.embedding_model_id = ?
              AND chunks.index_version = ?
              {cluster_clause}
            """,
            [params[0], selector["embedding_model_id"], selector["index_version"], *params[1:]],
        ).fetchall()
    return [dict(row) for row in rows]


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
