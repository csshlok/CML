from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


PROTOCOL = "atomic-extractor-checkpoint-promotion-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply preregistered development/validation promotion controls to a "
            "fine-tuned atomic extractor checkpoint."
        )
    )
    parser.add_argument("--training-run-manifest", type=Path, required=True)
    parser.add_argument("--development-report", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--baseline-validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-validation-f1-delta", type=float, default=0.02)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _single_candidate(report: dict) -> dict:
    rows = report.get("reports") or []
    if len(rows) != 1:
        raise ValueError("exactly_one_candidate_report_required")
    return rows[0]


def build_promotion_report(
    training: dict,
    development: dict,
    validation: dict,
    baseline_validation: dict,
    *,
    minimum_validation_f1_delta: float,
) -> dict:
    failures: list[str] = []
    if training.get("protocol") != "atomic-extractor-qwen3-4b-qlora-v1":
        failures.append("unexpected_training_protocol")
    if training.get("status") != "completed":
        failures.append("training_not_completed")
    if development.get("evaluation_role") != "development":
        failures.append("development_report_role_invalid")
    if validation.get("evaluation_role") != "validation":
        failures.append("validation_report_role_invalid")
    if baseline_validation.get("evaluation_role") != "validation":
        failures.append("baseline_validation_report_role_invalid")
    if validation.get("fixture_sha256") != baseline_validation.get("fixture_sha256"):
        failures.append("validation_fixture_hash_mismatch")
    if validation.get("gate_version") != baseline_validation.get("gate_version"):
        failures.append("validation_gate_version_mismatch")

    development_candidate = _single_candidate(development)
    validation_candidate = _single_candidate(validation)
    baseline_candidate = _single_candidate(baseline_validation)
    if not (development_candidate.get("gate") or {}).get("passed"):
        failures.append("development_semantic_gate_failed")
    if not (validation_candidate.get("gate") or {}).get("passed"):
        failures.append("validation_semantic_gate_failed")
    f1_delta = float(validation_candidate.get("micro_f1") or 0.0) - float(
        baseline_candidate.get("micro_f1") or 0.0
    )
    precision_delta = float(
        validation_candidate.get("micro_precision") or 0.0
    ) - float(baseline_candidate.get("micro_precision") or 0.0)
    recall_delta = float(validation_candidate.get("micro_recall") or 0.0) - float(
        baseline_candidate.get("micro_recall") or 0.0
    )
    if f1_delta < minimum_validation_f1_delta:
        failures.append("validation_f1_delta_below_preregistered_minimum")
    if precision_delta < 0:
        failures.append("validation_precision_regressed")
    if recall_delta < 0:
        failures.append("validation_recall_regressed")

    return {
        "protocol": PROTOCOL,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkpoint_candidate": validation_candidate.get("candidate"),
        "baseline_candidate": baseline_candidate.get("candidate"),
        "development_gate_passed": bool(
            (development_candidate.get("gate") or {}).get("passed")
        ),
        "validation_gate_passed": bool(
            (validation_candidate.get("gate") or {}).get("passed")
        ),
        "validation_deltas": {
            "micro_precision": round(precision_delta, 6),
            "micro_recall": round(recall_delta, 6),
            "micro_f1": round(f1_delta, 6),
        },
        "minimum_validation_f1_delta": minimum_validation_f1_delta,
        "holdout_authorized": not failures,
        "reader_benchmark_authorized": False,
        "reader_benchmark_blocker": (
            "A new sealed holdout and cached offline retrieval/failure replay must "
            "both pass before any paid reader benchmark."
        ),
        "failures": sorted(set(failures)),
    }


def main() -> int:
    args = parse_args()
    paths = (
        args.training_run_manifest,
        args.development_report,
        args.validation_report,
        args.baseline_validation_report,
    )
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    report = build_promotion_report(
        *payloads,
        minimum_validation_f1_delta=args.minimum_validation_f1_delta,
    )
    report["inputs"] = [
        {"path": str(path), "sha256": _sha256(path)} for path in paths
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["holdout_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
