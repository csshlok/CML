from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail CI when an offline LongMemEval claim-packing replay regresses."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--max-recall-drop", type=float, default=0.005)
    parser.add_argument("--max-containment-drop", type=float, default=0.01)
    parser.add_argument("--max-over-budget", type=int, default=0)
    parser.add_argument("--max-mean-token-increase-percent", type=float, default=2.0)
    parser.add_argument("--max-priority-type-recall-drop", type=float, default=0.01)
    parser.add_argument("--max-priority-type-containment-drop", type=float, default=0.02)
    return parser.parse_args()


def compare_claim_packing_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    max_recall_drop: float = 0.005,
    max_containment_drop: float = 0.01,
    max_over_budget: int = 0,
    max_mean_token_increase_percent: float = 2.0,
    max_priority_type_recall_drop: float = 0.01,
    max_priority_type_containment_drop: float = 0.02,
) -> dict[str, Any]:
    compatible_protocols = {
        "claim-first-longmemeval-offline-analysis-v1",
        "claim-consolidated-longmemeval-offline-analysis-v1",
    }
    for report_name, report in (("baseline", baseline), ("candidate", candidate)):
        if report.get("protocol") not in compatible_protocols:
            raise ValueError(f"{report_name} uses an incompatible protocol")
    if int(baseline.get("question_count") or 0) != int(candidate.get("question_count") or 0):
        raise ValueError("baseline and candidate question counts differ")

    baseline_recall = float(baseline["macro_answer_session_recall"])
    candidate_recall = float(candidate["macro_answer_session_recall"])
    baseline_containment = float(baseline["normalized_gold_containment_rate"])
    candidate_containment = float(candidate["normalized_gold_containment_rate"])
    baseline_tokens = float(baseline["mean_packed_prompt_tokens_estimate"])
    candidate_tokens = float(candidate["mean_packed_prompt_tokens_estimate"])
    recall_drop = baseline_recall - candidate_recall
    containment_drop = baseline_containment - candidate_containment
    token_change_percent = (
        100.0 * (candidate_tokens - baseline_tokens) / baseline_tokens
        if baseline_tokens
        else 0.0
    )
    checks = {
        "budget": int(candidate["packed_over_budget_count"]) <= int(max_over_budget),
        "answer_session_recall": recall_drop <= float(max_recall_drop),
        "gold_containment": containment_drop <= float(max_containment_drop),
        "mean_prompt_tokens": token_change_percent <= float(max_mean_token_increase_percent),
    }
    priority_deltas: dict[str, dict[str, float | None]] = {}
    baseline_types = baseline.get("by_question_type") or {}
    candidate_types = candidate.get("by_question_type") or {}
    for question_type in ("multi-session", "single-session-preference"):
        baseline_type = baseline_types.get(question_type)
        candidate_type = candidate_types.get(question_type)
        if not baseline_type or not candidate_type:
            continue
        recall_delta = _drop(
            baseline_type.get("macro_answer_session_recall"),
            candidate_type.get("macro_answer_session_recall"),
        )
        containment_delta = _drop(
            baseline_type.get("normalized_gold_containment_rate"),
            candidate_type.get("normalized_gold_containment_rate"),
        )
        checks[f"{question_type}_recall"] = (
            recall_delta is None or recall_delta <= max_priority_type_recall_drop
        )
        checks[f"{question_type}_containment"] = (
            containment_delta is None
            or containment_delta <= max_priority_type_containment_drop
        )
        priority_deltas[question_type] = {
            "recall_drop": round(recall_delta, 6) if recall_delta is not None else None,
            "containment_drop": round(containment_delta, 6) if containment_delta is not None else None,
        }
    return {
        "schema_version": 1,
        "question_count": int(candidate["question_count"]),
        "passed": all(checks.values()),
        "checks": checks,
        "candidate_over_budget_count": int(candidate["packed_over_budget_count"]),
        "recall_drop": round(recall_drop, 6),
        "containment_drop": round(containment_drop, 6),
        "mean_prompt_token_change_percent": round(token_change_percent, 3),
        "priority_type_deltas": priority_deltas,
    }


def _drop(baseline: object, candidate: object) -> float | None:
    if baseline is None or candidate is None:
        return None
    return float(baseline) - float(candidate)


def main() -> int:
    args = parse_args()
    result = compare_claim_packing_reports(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
        max_recall_drop=max(0.0, args.max_recall_drop),
        max_containment_drop=max(0.0, args.max_containment_drop),
        max_over_budget=max(0, args.max_over_budget),
        max_mean_token_increase_percent=max(0.0, args.max_mean_token_increase_percent),
        max_priority_type_recall_drop=max(0.0, args.max_priority_type_recall_drop),
        max_priority_type_containment_drop=max(
            0.0, args.max_priority_type_containment_drop
        ),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
