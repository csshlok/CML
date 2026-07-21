#!/usr/bin/env python3
"""Combine frozen atomic-memory coverage replays into a reader-run decision."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_REPORTS = (
    Path(".tmp/vault-odin-memory-benchmark/atomic-memory-representative-200/coverage.json"),
    Path(".tmp/vault-odin-memory-benchmark/atomic-memory-final-holdout-200/coverage.json"),
)
DEFAULT_OUTPUT = Path(
    ".tmp/vault-odin-memory-benchmark/atomic-memory-readiness.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether atomic-memory coverage is ready for paid reader evaluation."
    )
    parser.add_argument(
        "--coverage",
        type=Path,
        action="append",
        help="Coverage report to include; repeat for multiple frozen development sets.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-labeled-rate", type=float, default=0.95)
    parser.add_argument("--minimum-evidence-recall", type=float, default=0.98)
    parser.add_argument("--minimum-atomic-completeness", type=float, default=0.95)
    parser.add_argument("--minimum-temporal-recall", type=float, default=0.98)
    parser.add_argument("--minimum-direct-recall", type=float, default=1.0)
    parser.add_argument("--minimum-source-coverage", type=float, default=1.0)
    parser.add_argument("--minimum-activation-rate", type=float, default=0.10)
    parser.add_argument("--maximum-false-safe", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = args.coverage or list(DEFAULT_REPORTS)
    runs: list[dict] = []
    all_gates: list[bool] = []

    for path in paths:
        coverage = json.loads(path.read_text(encoding="utf-8"))
        gates = {
            "labeled_rate": coverage["labeled_question_rate"] >= args.minimum_labeled_rate,
            "stored_evidence_recall": coverage["evidence_recall"]
            >= args.minimum_evidence_recall,
            "atomic_completeness": coverage["atomic_routed_question_complete_rate"]
            >= args.minimum_atomic_completeness,
            "temporal_recall": coverage["temporal_anchor_recall"]
            >= args.minimum_temporal_recall,
            "direct_recall": coverage["direct_fact_recall"] >= args.minimum_direct_recall,
            "source_unit_coverage": coverage.get("source_coverage_complete_rate", 0.0)
            >= args.minimum_source_coverage,
            "tokens_below_control": coverage["expected_mean_reader_prompt_tokens"]
            < coverage["baseline_mean_reader_prompt_tokens"],
            "zero_false_safe": coverage["atomic_false_safe_count"]
            <= args.maximum_false_safe,
            "activation_rate": coverage["atomic_activation_rate"]
            >= args.minimum_activation_rate,
        }
        all_gates.extend(gates.values())
        runs.append(
            {
                "name": path.parent.name,
                "atomic_memory_version": coverage.get("atomic_memory_version", "unknown"),
                "coverage_path": str(path),
                "question_count": coverage["question_count"],
                "atomic_candidate_question_count": coverage[
                    "atomic_candidate_question_count"
                ],
                "atomic_used_question_count": coverage["atomic_used_question_count"],
                "atomic_activation_rate": coverage["atomic_activation_rate"],
                "atomic_false_safe_count": coverage["atomic_false_safe_count"],
                "atomic_question_completeness": coverage[
                    "atomic_routed_question_complete_rate"
                ],
                "evidence_recall": coverage["evidence_recall"],
                "temporal_anchor_recall": coverage["temporal_anchor_recall"],
                "direct_fact_recall": coverage["direct_fact_recall"],
                "source_coverage_complete_rate": coverage.get(
                    "source_coverage_complete_rate", 0.0
                ),
                "expected_mean_reader_prompt_tokens": coverage[
                    "expected_mean_reader_prompt_tokens"
                ],
                "baseline_mean_reader_prompt_tokens": coverage[
                    "baseline_mean_reader_prompt_tokens"
                ],
                "gates": gates,
            }
        )

    reader_evaluation_allowed = all(all_gates)
    failed = sorted(
        {
            gate
            for run in runs
            for gate, passed in run["gates"].items()
            if not passed
        }
    )
    report = {
        "protocol": "atomic-memory-question-only-readiness-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "atomic_memory_version": (
            runs[0].get("atomic_memory_version", "unknown") if runs else "unknown"
        ),
        "routing_inputs": ["raw_question", "retrieved_session_count"],
        "benchmark_question_type_used_for_routing": False,
        "generalization_fixture_case_count": 32,
        "metamorphic_variant_count": 128,
        "thresholds": {
            "minimum_labeled_rate": args.minimum_labeled_rate,
            "minimum_evidence_recall": args.minimum_evidence_recall,
            "minimum_atomic_completeness": args.minimum_atomic_completeness,
            "minimum_temporal_recall": args.minimum_temporal_recall,
            "minimum_direct_recall": args.minimum_direct_recall,
            "minimum_source_coverage": args.minimum_source_coverage,
            "minimum_activation_rate": args.minimum_activation_rate,
            "maximum_false_safe": args.maximum_false_safe,
        },
        "runs": runs,
        "reader_evaluation_allowed": reader_evaluation_allowed,
        "failed_gates": failed,
        "decision": "go" if reader_evaluation_allowed else "no-go",
        "decision_reason": (
            "All frozen coverage, safety, usefulness, and token gates passed."
            if reader_evaluation_allowed
            else "Reader evaluation is blocked until every failed gate passes on both frozen development sets."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if reader_evaluation_allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
