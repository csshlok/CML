from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = (
    REPO_ROOT / "backend/tests/fixtures/atomic_extractor_candidates.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select the smallest distributable extractor that passed every frozen gate."
    )
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/atomic-memory-v2-extractor-matrix/selection-report.json"),
    )
    return parser.parse_args()


def build_selection_report(matrix_reports: list[dict], inventory: dict) -> dict:
    metadata = {
        str(candidate["label"]): candidate
        for candidate in inventory.get("candidates") or []
    }
    summaries = []
    seen: set[str] = set()
    gate_versions: set[str] = set()
    protocols: set[str] = set()
    for matrix in matrix_reports:
        protocols.add(str(matrix.get("protocol") or ""))
        gate_versions.add(str(matrix.get("gate_version") or ""))
        evaluation_role = str(matrix.get("evaluation_role") or "development")
        if int(matrix.get("fixture_count") or 0) < 30:
            raise ValueError("selection_requires_complete_30_fixture_reports")
        for result in matrix.get("reports") or []:
            label = str((result.get("candidate") or {}).get("label") or "")
            if not label or label in seen:
                raise ValueError("selection_candidate_labels_must_be_unique")
            if label not in metadata:
                raise ValueError(f"candidate_missing_from_inventory:{label}")
            seen.add(label)
            candidate = metadata[label]
            gate_passed = bool((result.get("gate") or {}).get("passed"))
            distribution_eligible = bool(candidate["default_distribution_eligible"])
            rejection_reasons = []
            if not gate_passed:
                rejection_reasons.append("frozen_quality_gates_failed")
            if not distribution_eligible:
                rejection_reasons.append("license_not_default_distribution_eligible")
            if evaluation_role != "holdout":
                rejection_reasons.append("independent_holdout_required")
            summaries.append(
                {
                    **candidate,
                    "evaluation_role": evaluation_role,
                    "metrics": result.get("metrics") or {},
                    "gate": result.get("gate") or {},
                    "selectable": (
                        gate_passed
                        and distribution_eligible
                        and evaluation_role == "holdout"
                    ),
                    "rejection_reasons": rejection_reasons,
                }
            )
    if len(protocols) != 1 or len(gate_versions) != 1:
        raise ValueError("selection_reports_must_share_protocol_and_gate_version")
    selectable = [row for row in summaries if row["selectable"]]
    selected = min(
        selectable,
        key=lambda row: (float(row["parameter_count_b"]), str(row["label"])),
        default=None,
    )
    return {
        "protocol": "atomic-extractor-default-selection-v1",
        "matrix_protocol": next(iter(protocols)),
        "gate_version": next(iter(gate_versions)),
        "inventory_version": inventory["inventory_version"],
        "selection_status": "selected" if selected else "no_candidate_passed",
        "selected_candidate": selected["label"] if selected else None,
        "candidate_count": len(summaries),
        "candidates": sorted(
            summaries, key=lambda row: float(row["parameter_count_b"])
        ),
    }


def main() -> int:
    args = parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    matrices = [
        json.loads(report.read_text(encoding="utf-8")) for report in args.report
    ]
    selection = build_selection_report(matrices, inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(selection, indent=2))
    print(f"wrote {args.output}")
    return 0 if selection["selection_status"] == "selected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
