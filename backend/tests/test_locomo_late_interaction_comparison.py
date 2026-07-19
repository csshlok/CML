from scripts.backend.compare_locomo_late_interaction_reports import compare


def _report(retrieved: list[str], *, p95: float = 0.2, ratio: float = 5.0) -> dict:
    return {
        "protocol": {"top_k": 50},
        "summary": {
            "mean_query_latency_seconds": p95 / 2,
            "p95_query_latency_seconds": p95,
        },
        "index": {"late_interaction_to_dense_ratio": ratio},
        "results": [
            {
                "question_id": "q1",
                "category": 1,
                "evidence": ["gold"],
                "latency_seconds": p95,
                "retrieved": [
                    {"source_id": value, "evidence_id": value} for value in retrieved
                ],
            }
        ],
    }


def test_late_interaction_gate_accepts_material_quality_gain() -> None:
    baseline = _report(["miss"] * 50)
    candidate = _report(["gold"] + (["miss"] * 49))
    result = compare(baseline, candidate)
    assert result["passed"] is True
    assert all(result["checks"].values())


def test_late_interaction_gate_rejects_latency_and_storage_excess() -> None:
    baseline = _report(["miss"] * 50)
    candidate = _report(["gold"] + (["miss"] * 49), p95=0.9, ratio=17.0)
    result = compare(baseline, candidate)
    assert result["passed"] is False
    assert result["checks"]["p95_latency"] is False
    assert result["checks"]["index_size"] is False
