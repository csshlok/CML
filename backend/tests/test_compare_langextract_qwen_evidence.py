from __future__ import annotations

from scripts.backend.compare_langextract_qwen_evidence import (
    _candidate_metrics,
    _duplicate_count,
    interval_to_turn,
    render_session,
)


def test_render_session_maps_exact_intervals_back_to_source_turns() -> None:
    session = {
        "turns": [
            {"role": "user", "content": "I live in Pune.", "source_turn_id": "u1"},
            {"role": "assistant", "content": "That is useful.", "source_turn_id": "a1"},
        ]
    }
    rendered, ranges = render_session(session)
    start = rendered.index("live in Pune")
    end = start + len("live in Pune")

    mapped = interval_to_turn(start, end, ranges)

    assert mapped is not None
    turn, local_start, local_end = mapped
    assert turn["turn_index"] == 0
    assert turn["source_turn_id"] == "u1"
    assert turn["content"][local_start:local_end] == "live in Pune"


def test_interval_mapping_rejects_turn_markers_and_cross_turn_spans() -> None:
    session = {
        "turns": [
            {"role": "user", "content": "One"},
            {"role": "assistant", "content": "Two"},
        ]
    }
    rendered, ranges = render_session(session)

    assert interval_to_turn(0, len("[TURN 0"), ranges) is None
    assert interval_to_turn(
        rendered.index("One"), rendered.index("Two") + len("Two"), ranges
    ) is None


def test_duplicate_count_is_case_and_whitespace_insensitive() -> None:
    assert (
        _duplicate_count(
            [
                "The user lives in Pune.",
                "  the USER lives in Pune. ",
                "The user owns a cat.",
            ]
        )
        == 1
    )


def test_candidate_metrics_use_retained_grounded_predictions_and_nearest_rank_p95() -> None:
    fixtures = [
        {
            "status": "accepted",
            "prediction_count": 2,
            "grounded_prediction_count": 2,
            "duplicate_memory_count": 1,
            "output_truncated": False,
            "wall_seconds": seconds,
        }
        for seconds in (1.0, 2.0, 3.0, 4.0, 100.0)
    ]

    metrics = _candidate_metrics(fixtures, peak_gpu_memory_mib=4516)

    assert metrics["accepted_citation_validity_rate"] == 1.0
    assert metrics["p95_wall_seconds"] == 100.0
    assert metrics["peak_gpu_memory_mib"] == 4516
