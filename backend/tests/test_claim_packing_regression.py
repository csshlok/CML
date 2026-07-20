from __future__ import annotations

import pytest

from scripts.backend.check_claim_packing_regression import compare_claim_packing_reports


def _report(*, recall: float = 0.98, containment: float = 0.50, tokens: float = 9000, over: int = 0) -> dict:
    return {
        "protocol": "claim-first-longmemeval-offline-analysis-v1",
        "question_count": 500,
        "macro_answer_session_recall": recall,
        "normalized_gold_containment_rate": containment,
        "mean_packed_prompt_tokens_estimate": tokens,
        "packed_over_budget_count": over,
    }


def _typed_report(*, preference_containment: float = 0.8, multi_recall: float = 0.9) -> dict:
    report = _report()
    report["by_question_type"] = {
        "single-session-preference": {
            "macro_answer_session_recall": 1.0,
            "normalized_gold_containment_rate": preference_containment,
        },
        "multi-session": {
            "macro_answer_session_recall": multi_recall,
            "normalized_gold_containment_rate": 0.7,
        },
    }
    return report


def test_claim_packing_regression_accepts_bounded_candidate() -> None:
    result = compare_claim_packing_reports(
        _report(), _report(recall=0.979, containment=0.495, tokens=9100)
    )

    assert result["passed"] is True
    assert all(result["checks"].values())


def test_claim_packing_regression_reports_each_failed_gate() -> None:
    result = compare_claim_packing_reports(
        _report(), _report(recall=0.95, containment=0.45, tokens=9500, over=1)
    )

    assert result["passed"] is False
    assert set(key for key, passed in result["checks"].items() if not passed) == {
        "budget", "answer_session_recall", "gold_containment", "mean_prompt_tokens"
    }


def test_claim_packing_regression_rejects_mismatched_sample_sizes() -> None:
    candidate = _report()
    candidate["question_count"] = 30

    with pytest.raises(ValueError, match="question counts differ"):
        compare_claim_packing_reports(_report(), candidate)


def test_claim_packing_regression_catches_priority_type_regression() -> None:
    baseline = _typed_report()
    candidate = _typed_report(preference_containment=0.7, multi_recall=0.85)
    candidate["protocol"] = "claim-consolidated-longmemeval-offline-analysis-v1"

    result = compare_claim_packing_reports(baseline, candidate)

    assert result["passed"] is False
    assert result["checks"]["single-session-preference_containment"] is False
    assert result["checks"]["multi-session_recall"] is False
