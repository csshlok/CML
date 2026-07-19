from __future__ import annotations

from scripts.backend.compare_locomo_embedding_reports import compare


def _report(order: list[str], *, latency: float = 0.1) -> dict:
    return {
        "protocol": {"embedding_model": "fixture"},
        "results": [
            {
                "question_id": "q1",
                "sample_id": "conv-1",
                "question": "Where?",
                "category": 1,
                "evidence": ["D1:50"],
                "latency_seconds": latency,
                "retrieved": [
                    {"sample_id": "conv-1", "evidence_id": evidence_id}
                    for evidence_id in order
                ],
            }
        ],
    }


def test_embedding_comparison_promotes_material_top10_gain() -> None:
    values = [f"D1:{index}" for index in range(1, 51)]
    baseline = _report(values)
    candidate = _report(["D1:50", *values[:-1]])

    result = compare(baseline, candidate, min_top10_improvement=0.5)

    assert result["passed"] is True
    assert result["top10_recall_improvement"] == 1.0


def test_embedding_comparison_rejects_latency_regression() -> None:
    values = [f"D1:{index}" for index in range(1, 51)]
    baseline = _report(values)
    candidate = _report(["D1:50", *values[:-1]], latency=0.2)

    result = compare(baseline, candidate, min_top10_improvement=0.5)

    assert result["passed"] is False
    assert result["checks"]["mean_latency"] is False
