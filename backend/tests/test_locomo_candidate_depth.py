from __future__ import annotations

from scripts.backend.analyze_locomo_candidate_depth import analyze


def _row(question_id: str, gold: list[str], retrieved: list[str], *, category: int = 1) -> dict:
    return {
        "question_id": question_id,
        "sample_id": "conv-1",
        "category": category,
        "evidence": gold,
        "retrieved": [
            {"sample_id": "conv-1", "evidence_id": value}
            for value in retrieved
        ],
        "latency_seconds": 0.1,
    }


def test_candidate_depth_separates_generation_and_ranking_failures() -> None:
    rows = [
        _row("ranked", ["D2:1"], ["D1:1", "D2:1", "D3:1"]),
        _row("missing", ["D9:1"], ["D1:1", "D2:1", "D3:1"]),
        _row("partial", ["D1:1", "D9:1"], ["D1:1", "D2:1", "D3:1"]),
    ]

    result = analyze({"results": rows}, [1, 3])

    decomposition = result["failure_decomposition"]
    assert decomposition["ranking_recoverable_between_10_and_max_count"] == 0
    assert decomposition["candidate_generation_zero_at_max_question_ids"] == ["missing"]
    assert decomposition["partial_evidence_at_max_question_ids"] == ["partial"]
    assert result["cutoffs"][0]["macro_recall"] == 0.166667


def test_session_diversity_policy_is_measured_not_assumed() -> None:
    rows = [
        _row(
            "same-session-gold",
            ["D1:1", "D1:2"],
            ["D1:1", "D1:2", "D2:1", "D3:1", "D4:1", "D5:1", "D6:1", "D7:1", "D8:1", "D9:1"],
        )
    ]

    result = analyze({"results": rows}, [10])

    grid = {row["max_per_session"]: row for row in result["session_diversity_grid"]}
    assert grid[1]["macro_recall_at_10"] == 0.5
    assert grid[2]["macro_recall_at_10"] == 1.0


def test_zero_at_max_characterization_compares_query_and_gold_traits() -> None:
    rows = [
        {
            **_row("missing", ["D1:1"], ["D2:1"], category=2),
            "question": "When did she visit the museum?",
        },
        {
            **_row("found", ["D2:1"], ["D2:1"], category=1),
            "question": "Which museum did Alice visit?",
        },
    ]
    dataset = [
        {
            "sample_id": "conv-1",
            "conversation": {
                "session_1": [
                    {"dia_id": "D1:1", "text": "Alice visited it on Monday."},
                    {"dia_id": "D2:1", "text": "Alice visited the science museum."},
                ]
            },
        }
    ]

    result = analyze({"results": rows}, [1], dataset=dataset)

    characterization = result["zero_at_max_characterization"]
    assert characterization["zero_group"]["question_count"] == 1
    assert characterization["zero_group"]["temporal_marker_rate"] == 1.0
    assert characterization["by_conversation"][0]["zero_at_max_rate"] == 0.5
