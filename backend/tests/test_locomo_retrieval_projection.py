from scripts.backend.project_locomo_retrieval_cutoff import project


def test_projection_recomputes_retrieval_metrics_at_requested_cutoff() -> None:
    report = {
        "protocol": {"top_k": 50},
        "results": [
            {
                "question_id": "q1",
                "evidence": ["gold", "later"],
                "retrieved": [
                    {"evidence_id": "gold"},
                    {"evidence_id": "miss"},
                    {"evidence_id": "later"},
                ],
                "found_evidence": ["gold", "later"],
                "recall_at_k": 1.0,
                "any_evidence_at_k": True,
            }
        ],
    }
    projected = project(report, 2)
    row = projected["results"][0]
    assert len(row["retrieved"]) == 2
    assert row["found_evidence"] == ["gold"]
    assert row["recall_at_k"] == 0.5
    assert projected["protocol"]["projection"]["ranking_unchanged"] is True
