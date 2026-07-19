from __future__ import annotations

from scripts.backend.analyze_locomo_reranker_latency import analyze


def test_latency_analysis_distinguishes_query_size_from_runtime_outliers() -> None:
    dataset = [
        {
            "sample_id": "conv-1",
            "conversation": {
                "session_1_date_time": "2025-01-01",
                "session_1": [
                    {"dia_id": "D1:1", "speaker": "A", "text": "short"},
                    {"dia_id": "D1:2", "speaker": "B", "text": "a longer document"},
                ],
            },
        }
    ]
    retrieval = {
        "results": [
            {
                "question_id": "q1",
                "question": "short question",
                "retrieved": [{"source_id": "locomo:conv-1:D1:1"}],
            },
            {
                "question_id": "q2",
                "question": "a somewhat longer question",
                "retrieved": [{"source_id": "locomo:conv-1:D1:2"}],
            },
        ]
    }
    depth_one = {
        "protocol": {"candidate_depth": 1},
        "results": [
            {"question_id": "q1", "reranker_seconds": 0.1},
            {"question_id": "q2", "reranker_seconds": 0.9},
        ],
    }
    second = {
        "protocol": {"candidate_depth": 1},
        "results": [
            {"question_id": "q1", "reranker_seconds": 0.2},
            {"question_id": "q2", "reranker_seconds": 0.8},
        ],
    }

    result = analyze(dataset, retrieval, [depth_one, second])

    assert result["runs"][0]["latency_seconds"]["p95"] == 0.9
    assert result["runs"][0]["p95_outlier_characteristics"]["question_ids"] == ["q2"]
    assert result["comparisons"][0]["p95_outlier_jaccard"] == 1.0
