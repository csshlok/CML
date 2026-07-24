from __future__ import annotations

from unittest.mock import patch

from backend.app.core.embeddings import encode_embedding
from backend.app.core.retrieval_scoring import (
    _bm25_scores,
    _legacy_scoring_ledger,
    _prepare_rows,
    _prepared_bm25_scores,
    clear_prepared_retrieval_cache,
    scoring_ledger,
)


def _row(
    chunk_id: str,
    text: str,
    embedding: list[float],
    *,
    source_type: str = "note",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": f"source-{chunk_id}",
        "vault_id": "vault-test",
        "page_id": None,
        "cluster_id": None,
        "chunk_index": 0,
        "text": text,
        "embedding": encode_embedding(embedding),
        "source_title": f"Source {chunk_id}",
        "source_type": source_type,
        "tags": "[]",
        "page_number": None,
    }


def _rows() -> list[dict]:
    return [
        _row("a", "alpha alpha beta retrieval", [1.0, 0.0, 0.0]),
        _row("b", "beta gamma semantic search", [0.8, 0.6, 0.0]),
        _row(
            "c",
            "alpha transcript memory",
            [0.0, 1.0, 0.0],
            source_type="external_transcript",
        ),
    ]


def test_prepared_bm25_matches_legacy_formula_with_duplicate_query_terms() -> None:
    rows = _rows()
    query_tokens = ["alpha", "alpha", "search", "missing"]

    legacy = _bm25_scores(query_tokens, rows)
    prepared = _prepared_bm25_scores(query_tokens, _prepare_rows(rows))

    assert [round(float(value), 12) for value in prepared] == [
        round(float(legacy.get(row["chunk_id"], 0.0)), 12) for row in rows
    ]


def test_prepared_scorer_preserves_legacy_ranking_and_public_scores() -> None:
    rows = _rows()
    revision = ("vault-test", "revision-1")
    clear_prepared_retrieval_cache()
    with (
        patch(
            "backend.app.core.retrieval_scoring._chunk_revision",
            return_value=revision,
        ),
        patch(
            "backend.app.core.retrieval_scoring._chunk_rows",
            return_value=rows,
        ),
        patch(
            "backend.app.core.retrieval_scoring.embed_text",
            return_value=[0.8, 0.6, 0.0],
        ),
    ):
        legacy = _legacy_scoring_ledger("vault-test", "alpha search", limit=10)
        prepared = scoring_ledger("vault-test", "alpha search", limit=10)
        cached = scoring_ledger("vault-test", "alpha search", limit=10)

    comparable_keys = (
        "chunk_id",
        "semantic_score",
        "bm25_score",
        "source_class",
        "source_class_weight",
        "combined_score",
    )
    assert [
        {key: row[key] for key in comparable_keys} for row in prepared["results"]
    ] == [{key: row[key] for key in comparable_keys} for row in legacy["results"]]
    assert prepared["retrieval_index"]["cache_hit"] is False
    assert cached["retrieval_index"]["cache_hit"] is True


def test_prepared_cache_invalidates_when_corpus_revision_changes() -> None:
    rows = _rows()
    revision = ["revision-1"]
    clear_prepared_retrieval_cache()
    with (
        patch(
            "backend.app.core.retrieval_scoring._chunk_revision",
            side_effect=lambda *_args: ("vault-test", revision[0]),
        ),
        patch(
            "backend.app.core.retrieval_scoring._chunk_rows",
            side_effect=lambda *_args: list(rows),
        ),
        patch(
            "backend.app.core.retrieval_scoring.embed_text",
            return_value=[0.8, 0.6, 0.0],
        ),
    ):
        first = scoring_ledger("vault-test", "alpha", limit=10)
        rows.append(_row("d", "new alpha evidence", [0.9, 0.1, 0.0]))
        revision[0] = "revision-2"
        second = scoring_ledger("vault-test", "alpha", limit=10)

    assert first["chunks_considered"] == 3
    assert second["chunks_considered"] == 4
    assert second["retrieval_index"]["cache_hit"] is False
