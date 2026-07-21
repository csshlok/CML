#!/usr/bin/env python3
"""Diff atomic coverage reports and isolate materially changed questions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROW_FIELDS = (
    "route_candidate",
    "effective_path",
    "all_evidence_packed",
    "all_effective_evidence_packed",
    "expected_prompt_tokens",
    "packed_tokens_estimate",
)
SUMMARY_FIELDS = (
    "evidence_recall",
    "packed_evidence_recall",
    "atomic_used_question_count",
    "atomic_activation_rate",
    "atomic_false_safe_count",
    "atomic_routed_question_complete_rate",
    "temporal_anchor_recall",
    "direct_fact_recall",
    "expected_mean_reader_prompt_tokens",
)


def _operation(row: dict) -> str:
    return str((row.get("query_plan") or {}).get("operation") or "")


def _contract(row: dict) -> tuple:
    contract = row.get("contract") or {}
    return (
        bool(contract.get("safe")),
        tuple(contract.get("missing_slots") or []),
        tuple(contract.get("operand_fact_ids") or []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    old_rows = {row["question_id"]: row for row in before["rows"]}
    new_rows = {row["question_id"]: row for row in after["rows"]}
    changed: list[dict] = []
    for question_id in sorted(old_rows.keys() | new_rows.keys()):
        old = old_rows.get(question_id)
        new = new_rows.get(question_id)
        if old is None or new is None:
            changed.append({"question_id": question_id, "change": "added_or_removed"})
            continue
        differences = {
            field: {"before": old.get(field), "after": new.get(field)}
            for field in ROW_FIELDS
            if old.get(field) != new.get(field)
        }
        if _operation(old) != _operation(new):
            differences["operation"] = {
                "before": _operation(old),
                "after": _operation(new),
            }
        if _contract(old) != _contract(new):
            differences["contract"] = {
                "before": {
                    "safe": _contract(old)[0],
                    "missing_slots": list(_contract(old)[1]),
                    "operand_fact_ids": list(_contract(old)[2]),
                },
                "after": {
                    "safe": _contract(new)[0],
                    "missing_slots": list(_contract(new)[1]),
                    "operand_fact_ids": list(_contract(new)[2]),
                },
            }
        if differences:
            changed.append(
                {
                    "question_id": question_id,
                    "question_type": new.get("question_type"),
                    "differences": differences,
                }
            )
    summary = {
        field: {
            "before": before.get(field),
            "after": after.get(field),
            "delta": (
                round(float(after[field]) - float(before[field]), 6)
                if isinstance(before.get(field), (int, float))
                and isinstance(after.get(field), (int, float))
                else None
            ),
        }
        for field in SUMMARY_FIELDS
    }
    report = {
        "protocol": "atomic-memory-packet-diff-v1",
        "before": str(args.before),
        "after": str(args.after),
        "changed_question_count": len(changed),
        "unchanged_question_count": len(new_rows) - len(changed),
        "reader_impact_question_ids": [
            row["question_id"]
            for row in changed
            if "differences" in row
            and any(
                field in row["differences"]
                for field in ("effective_path", "contract", "expected_prompt_tokens")
            )
        ],
        "summary": summary,
        "changed_questions": changed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "changed_question_count", "unchanged_question_count", "reader_impact_question_ids", "summary"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
