from __future__ import annotations

from scripts.backend.analyze_locomo_reranker_policies import analyze


def _retrieval_row(question_id: str, retrieved: list[str], gold: list[str]) -> dict:
    return {
        "question_id": question_id,
        "sample_id": "conv-1",
        "category": 1,
        "evidence": gold,
        "recall_at_k": float(gold[0] in retrieved[:1]),
        "latency_seconds": 0.1,
        "retrieved": [
            {"source_id": f"source:{value}", "evidence_id": value, "score": 1.0 / rank}
            for rank, value in enumerate(retrieved, start=1)
        ],
    }


def _reranker_row(question_id: str, reranked: list[str], original: list[str]) -> dict:
    original_rank = {value: rank for rank, value in enumerate(original, start=1)}
    return {
        "question_id": question_id,
        "reranker_seconds": 0.1,
        "reranked_candidates": [
            {
                "source_id": f"source:{value}",
                "evidence_id": value,
                "retrieval_rank": original_rank[value],
                "retrieval_score": 1.0 / original_rank[value],
                "reranker_score": 1.0 / cross_rank,
            }
            for cross_rank, value in enumerate(reranked, start=1)
        ],
    }


def test_policy_gate_can_promote_a_bounded_reranker() -> None:
    original = ["D1:1", "D2:1"]
    retrieval = {"results": [_retrieval_row("q1", original, ["D2:1"])]}
    reranker = {"results": [_reranker_row("q1", ["D2:1", "D1:1"], original)]}

    result = analyze(
        retrieval,
        reranker,
        depths=[2],
        top_k=1,
        max_mean_total_seconds=0.5,
        max_p95_total_seconds=0.5,
        min_recall_improvement=0.5,
        max_category_drop=0.0,
    )

    assert result["promotion_gate_passed"] is True
    assert result["best_policy"]["macro_recall_at_k"] == 1.0


def test_policy_gate_rejects_excessive_total_latency() -> None:
    original = ["D1:1", "D2:1"]
    retrieval = {"results": [_retrieval_row("q1", original, ["D2:1"])]}
    reranker = {"results": [_reranker_row("q1", ["D2:1", "D1:1"], original)]}
    reranker["results"][0]["reranker_seconds"] = 1.0

    result = analyze(
        retrieval,
        reranker,
        depths=[2],
        top_k=1,
        max_mean_total_seconds=0.5,
        max_p95_total_seconds=0.5,
        min_recall_improvement=0.5,
        max_category_drop=0.0,
    )

    assert result["promotion_gate_passed"] is False
    assert result["best_policy"]["checks"]["mean_latency"] is False
