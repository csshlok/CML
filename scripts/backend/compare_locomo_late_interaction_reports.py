from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.backend.analyze_locomo_candidate_depth import analyze


def compare(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    min_top10_improvement: float = 0.03,
    max_category_drop: float = 0.01,
    max_zero_at_50_increase: int = 0,
    max_p95_seconds: float = 0.85,
    max_index_size_ratio: float = 16.0,
) -> dict[str, Any]:
    baseline = analyze(baseline_report, [10, 30, 50])
    candidate = analyze(candidate_report, [10, 30, 50])
    if baseline["question_count"] != candidate["question_count"]:
        raise ValueError("baseline and candidate question counts differ")
    baseline_cutoffs = {row["cutoff"]: row for row in baseline["cutoffs"]}
    candidate_cutoffs = {row["cutoff"]: row for row in candidate["cutoffs"]}
    improvement = candidate_cutoffs[10]["macro_recall"] - baseline_cutoffs[10]["macro_recall"]
    category_drops = {
        category: baseline_cutoffs[10]["recall_by_category"][category]
        - candidate_cutoffs[10]["recall_by_category"][category]
        for category in baseline_cutoffs[10]["recall_by_category"]
    }
    zero_change = (
        candidate_cutoffs[50]["zero_recall_count"] - baseline_cutoffs[50]["zero_recall_count"]
    )
    p95_seconds = float(candidate["latency"]["p95_seconds"])
    index_ratio = float(candidate_report["index"]["late_interaction_to_dense_ratio"])
    checks = {
        "top10_recall_improvement": improvement >= min_top10_improvement,
        "category_non_regression": max(category_drops.values(), default=0.0) <= max_category_drop,
        "zero_at_50_non_regression": zero_change <= max_zero_at_50_increase,
        "p95_latency": p95_seconds <= max_p95_seconds,
        "index_size": index_ratio <= max_index_size_ratio,
    }
    return {
        "schema_version": 1,
        "question_count": baseline["question_count"],
        "passed": all(checks.values()),
        "checks": checks,
        "top10_recall_improvement": round(improvement, 6),
        "top10_category_drops": {key: round(value, 6) for key, value in category_drops.items()},
        "zero_at_50_change": zero_change,
        "candidate_p95_seconds": p95_seconds,
        "index_size_ratio": index_ratio,
        "thresholds": {
            "min_top10_improvement": min_top10_improvement,
            "max_category_drop": max_category_drop,
            "max_zero_at_50_increase": max_zero_at_50_increase,
            "max_p95_seconds": max_p95_seconds,
            "max_index_size_ratio": max_index_size_ratio,
        },
        "baseline": {"cutoffs": baseline["cutoffs"], "latency": baseline["latency"]},
        "candidate": {"cutoffs": candidate["cutoffs"], "latency": candidate["latency"]},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate a LoCoMo late-interaction candidate.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
