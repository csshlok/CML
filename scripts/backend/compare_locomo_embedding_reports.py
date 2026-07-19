from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.backend.analyze_locomo_candidate_depth import analyze


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply preregistered quality and latency gates to LoCoMo embedding reports."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-top10-improvement", type=float, default=0.03)
    parser.add_argument("--max-category-drop", type=float, default=0.01)
    parser.add_argument("--max-zero-at-50-increase", type=int, default=0)
    parser.add_argument("--max-latency-ratio", type=float, default=1.25)
    return parser.parse_args()


def compare(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    min_top10_improvement: float = 0.03,
    max_category_drop: float = 0.01,
    max_zero_at_50_increase: int = 0,
    max_latency_ratio: float = 1.25,
) -> dict[str, Any]:
    baseline = analyze(baseline_report, [10, 30, 50])
    candidate = analyze(candidate_report, [10, 30, 50])
    if baseline["question_count"] != candidate["question_count"]:
        raise ValueError("baseline and candidate question counts differ")
    baseline_cutoffs = {row["cutoff"]: row for row in baseline["cutoffs"]}
    candidate_cutoffs = {row["cutoff"]: row for row in candidate["cutoffs"]}
    top10_improvement = (
        candidate_cutoffs[10]["macro_recall"] - baseline_cutoffs[10]["macro_recall"]
    )
    category_drops = {
        category: baseline_cutoffs[10]["recall_by_category"][category]
        - candidate_cutoffs[10]["recall_by_category"][category]
        for category in baseline_cutoffs[10]["recall_by_category"]
    }
    baseline_zero = baseline_cutoffs[50]["zero_recall_count"]
    candidate_zero = candidate_cutoffs[50]["zero_recall_count"]
    mean_ratio = candidate["latency"]["mean_seconds"] / baseline["latency"]["mean_seconds"]
    p95_ratio = candidate["latency"]["p95_seconds"] / baseline["latency"]["p95_seconds"]
    checks = {
        "top10_recall_improvement": top10_improvement >= min_top10_improvement,
        "category_non_regression": max(category_drops.values(), default=0.0) <= max_category_drop,
        "zero_at_50_non_regression": candidate_zero - baseline_zero <= max_zero_at_50_increase,
        "mean_latency": mean_ratio <= max_latency_ratio,
        "p95_latency": p95_ratio <= max_latency_ratio,
    }
    return {
        "schema_version": 1,
        "question_count": baseline["question_count"],
        "passed": all(checks.values()),
        "checks": checks,
        "top10_recall_improvement": round(top10_improvement, 6),
        "top10_category_drops": {
            key: round(value, 6) for key, value in category_drops.items()
        },
        "zero_at_50_change": candidate_zero - baseline_zero,
        "mean_latency_ratio": round(mean_ratio, 4),
        "p95_latency_ratio": round(p95_ratio, 4),
        "baseline": {
            "embedding_model": (baseline_report.get("protocol") or {}).get("embedding_model"),
            "cutoffs": baseline["cutoffs"],
            "latency": baseline["latency"],
        },
        "candidate": {
            "embedding_model": (candidate_report.get("protocol") or {}).get("embedding_model"),
            "cutoffs": candidate["cutoffs"],
            "latency": candidate["latency"],
        },
    }


def main() -> int:
    args = parse_args()
    payload = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
        min_top10_improvement=max(0.0, args.min_top10_improvement),
        max_category_drop=max(0.0, args.max_category_drop),
        max_zero_at_50_increase=max(0, args.max_zero_at_50_increase),
        max_latency_ratio=max(1.0, args.max_latency_ratio),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
