from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


PROTOCOL = "atomic-reader-benchmark-authorization-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed final gate before any paid paired reader benchmark. "
            "This command authorizes; it never starts provider calls."
        )
    )
    parser.add_argument("--checkpoint-promotion", type=Path, required=True)
    parser.add_argument("--holdout-semantic-report", type=Path, required=True)
    parser.add_argument("--offline-replay-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _single_candidate(report: dict) -> dict:
    rows = report.get("reports") or []
    if len(rows) != 1:
        raise ValueError("exactly_one_holdout_candidate_required")
    return rows[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_authorization(
    promotion: dict,
    holdout: dict,
    offline: dict,
) -> dict:
    failures: list[str] = []
    if not promotion.get("holdout_authorized"):
        failures.append("checkpoint_not_authorized_for_holdout")
    if promotion.get("reader_benchmark_authorized"):
        failures.append("checkpoint_report_must_not_pre_authorize_reader_calls")
    if holdout.get("evaluation_role") != "holdout":
        failures.append("semantic_report_is_not_holdout")
    if not holdout.get("holdout_details_redacted"):
        failures.append("holdout_details_were_not_redacted")
    holdout_candidate = _single_candidate(holdout)
    if not (holdout_candidate.get("gate") or {}).get("passed"):
        failures.append("holdout_semantic_gate_failed")
    if offline.get("evaluation_role") != "development":
        failures.append("offline_replay_must_use_development_data")
    if offline.get("selection_mode") != "representative":
        failures.append("offline_replay_is_not_representative")
    if offline.get("atomic_extraction_scope") != "full-haystack":
        failures.append("offline_extraction_scope_is_not_full_haystack")
    if offline.get("cpu_model_fallback_allowed") is not False:
        failures.append("offline_replay_did_not_forbid_cpu_model_fallback")
    if not offline.get("promotion_passed"):
        failures.append("offline_replay_promotion_gate_failed")
    if int(offline.get("new_regression_count") or 0) != 0:
        failures.append("offline_replay_has_new_regressions")
    if int(offline.get("false_safe_activation_count") or 0) != 0:
        failures.append("offline_replay_has_false_safe_activation")
    if float(offline.get("predicted_accuracy_delta") or 0.0) <= 0:
        failures.append("offline_replay_does_not_predict_positive_accuracy_delta")
    if float(offline.get("candidate_packed_macro_recall") or 0.0) < float(
        offline.get("baseline_packed_macro_recall") or 0.0
    ):
        failures.append("offline_candidate_packed_recall_regressed")

    return {
        "protocol": PROTOCOL,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reader_benchmark_authorized": not failures,
        "paid_calls_started": False,
        "authorization_scope": (
            "One cost-capped representative paired reader/dual-judge run using the "
            "exact checkpoint and artifacts hashed below."
        ),
        "failures": sorted(set(failures)),
    }


def main() -> int:
    args = parse_args()
    paths = (
        args.checkpoint_promotion,
        args.holdout_semantic_report,
        args.offline_replay_report,
    )
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    try:
        report = build_authorization(*payloads)
    except ValueError as exc:
        print(str(exc))
        return 2
    report["inputs"] = [
        {"path": str(path), "sha256": _sha256(path)} for path in paths
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["reader_benchmark_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
