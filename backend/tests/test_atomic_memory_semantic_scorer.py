from __future__ import annotations

import numpy as np

from scripts.backend.score_atomic_extraction_memories import (
    _compatible,
    _critical_slots,
    evaluate_semantic_gates,
    score_fixture_vectors,
)


def test_semantic_scorer_matches_each_prediction_at_most_once() -> None:
    result = score_fixture_vectors(
        ["The user repaired the lamp.", "The user painted the door."],
        ["The user repaired the lamp."],
        np.asarray([[0.99], [0.91]], dtype=np.float32),
        threshold=0.70,
    )

    assert result["match_count"] == 1
    assert result["precision"] == 1.0
    assert result["recall"] == 0.5


def test_semantic_scorer_protects_polarity_and_modality() -> None:
    assert not _compatible(
        "The user did not buy the bicycle.",
        "The user bought the bicycle.",
    )
    assert not _compatible(
        "The user plans to buy the bicycle.",
        "The user bought the bicycle.",
    )
    assert _compatible(
        "The user plans to buy the bicycle.",
        "The user will buy the bicycle.",
    )

    result = score_fixture_vectors(
        ["The user did not buy the bicycle."],
        ["The user bought the bicycle."],
        np.asarray([[0.99]], dtype=np.float32),
        threshold=0.70,
    )
    assert result["match_count"] == 0


def test_semantic_scorer_counts_empty_case_false_positives() -> None:
    clean = score_fixture_vectors(
        [],
        [],
        np.zeros((0, 0), dtype=np.float32),
        threshold=0.70,
    )
    noisy = score_fixture_vectors(
        [],
        ["The assistant gave generic advice."],
        np.zeros((0, 1), dtype=np.float32),
        threshold=0.70,
    )

    assert clean["precision"] == 1.0
    assert clean["recall"] == 1.0
    assert noisy["precision"] == 0.0
    assert noisy["recall"] == 0.0


def test_semantic_scorer_rejects_wrong_critical_fields() -> None:
    assert not _compatible(
        "The user paid 29 dollars per month.",
        "The user paid 99 dollars per month.",
    )
    assert not _compatible(
        "The assistant recommended rest.",
        "The user recommended rest.",
    )
    assert not _compatible(
        "The user visited Dr. Lee.",
        "The user visited Dr. Patel.",
    )
    assert _compatible(
        "The assistant recommended that the user rest.",
        "The assistant recommends that the user rest.",
    )
    assert _critical_slots("The user visited Dr. Lee on January 2, 2026.") == {
        "numbers": {"2", "2026"},
        "dates": {"january 2 2026"},
        "speakers": {"user"},
        "named_entities": {"dr lee"},
    }


def test_semantic_gate_evaluation_is_fail_closed() -> None:
    manifest = {
        "gate_version": "test",
        "thresholds": {
            "micro_f1_min": 0.8,
            "empty_fixture_false_positive_count_max": 0,
        },
    }

    passed = evaluate_semantic_gates(
        {"micro_f1": 0.81, "empty_fixture_false_positive_count": 0},
        manifest,
    )
    failed = evaluate_semantic_gates(
        {"micro_f1": 0.79, "empty_fixture_false_positive_count": 0},
        manifest,
    )

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert failed["failed_checks"] == ["micro_f1_min"]
