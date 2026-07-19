from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


DEFAULT_SEED = "vault-memory-regression-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two saved Vault retrieval reports without model or API calls."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=100)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--max-recall-drop", type=float, default=0.01)
    parser.add_argument("--max-hit-rate-drop", type=float, default=0.01)
    return parser.parse_args()


def canonical_question_ids(
    rows: list[dict[str, Any]], count: int, *, seed: str = DEFAULT_SEED
) -> list[str]:
    question_ids = {str(row["question_id"]) for row in rows}
    ranked = sorted(
        question_ids,
        key=lambda question_id: (
            hashlib.sha256(f"{seed}:{question_id}".encode("utf-8")).hexdigest(),
            question_id,
        ),
    )
    return ranked[: max(1, min(int(count), len(ranked)))]


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    count: int,
    seed: str = DEFAULT_SEED,
    max_recall_drop: float = 0.01,
    max_hit_rate_drop: float = 0.01,
) -> dict[str, Any]:
    _assert_compatible_protocol(baseline, candidate)
    baseline_rows = _rows_by_id(baseline)
    candidate_rows = _rows_by_id(candidate)
    selected = canonical_question_ids(list(baseline_rows.values()), count, seed=seed)
    missing = [question_id for question_id in selected if question_id not in candidate_rows]
    if missing:
        raise RuntimeError(
            f"candidate report is missing {len(missing)} canonical questions"
        )

    baseline_metrics = _metrics([baseline_rows[value] for value in selected])
    candidate_metrics = _metrics([candidate_rows[value] for value in selected])
    recall_drop = baseline_metrics["macro_recall"] - candidate_metrics["macro_recall"]
    hit_rate_drop = baseline_metrics["any_evidence_hit_rate"] - candidate_metrics[
        "any_evidence_hit_rate"
    ]
    result = {
        "schema_version": 1,
        "seed": seed,
        "question_count": len(selected),
        "question_ids": selected,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "recall_drop": round(recall_drop, 6),
        "hit_rate_drop": round(hit_rate_drop, 6),
        "passed": recall_drop <= max_recall_drop
        and hit_rate_drop <= max_hit_rate_drop,
    }
    if not result["passed"]:
        raise RuntimeError(
            "memory retrieval regression: "
            f"recall drop={result['recall_drop']}, "
            f"hit-rate drop={result['hit_rate_drop']}"
        )
    return result


def _assert_compatible_protocol(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> None:
    baseline_protocol = baseline.get("protocol") or {}
    candidate_protocol = candidate.get("protocol") or {}
    for field in ("dataset_sha256", "selection_mode", "seed"):
        left = baseline_protocol.get(field)
        right = candidate_protocol.get(field)
        if left is not None and right is not None and left != right:
            raise RuntimeError(f"incompatible retrieval reports: {field} differs")


def _rows_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("results")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("retrieval report has no result rows")
    indexed = {str(row["question_id"]): row for row in rows}
    if len(indexed) != len(rows):
        raise RuntimeError("retrieval report contains duplicate question IDs")
    return indexed


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scorable = [row for row in rows if row.get("recall_at_k") is not None]
    if not scorable:
        raise RuntimeError("canonical set has no evidence-scored questions")
    recall = statistics.fmean(float(row["recall_at_k"]) for row in scorable)
    hit_rate = statistics.fmean(
        1.0 if row.get("any_evidence_at_k") else 0.0 for row in scorable
    )
    return {
        "evidence_question_count": len(scorable),
        "macro_recall": round(recall, 6),
        "any_evidence_hit_rate": round(hit_rate, 6),
    }


def main() -> int:
    args = parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = compare_reports(
        baseline,
        candidate,
        count=args.questions,
        seed=args.seed,
        max_recall_drop=max(0.0, args.max_recall_drop),
        max_hit_rate_drop=max(0.0, args.max_hit_rate_drop),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
