from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path


ENUMERATION_RE = re.compile(
    r"\b(how many|how often|number of|times did|occasions?|in total|"
    r"total (?:amount|cost|number|distance|weight|hours?))\b",
    re.IGNORECASE,
)
UPDATE_RE = re.compile(
    r"\b(now|current(?:ly)?|still|recent(?:ly)?|these days|anymore|latest|"
    r"upcoming|planning|usually|typical)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the preregistered LongMemEval structured-reader v2 holdout."
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--primary-baseline", type=Path, required=True)
    parser.add_argument("--independent-baseline", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20_260_718)
    parser.add_argument("--recovery-count", type=int, default=7)
    parser.add_argument("--control-count", type=int, default=18)
    parser.add_argument("--enumeration-controls", type=int, default=5)
    parser.add_argument("--update-controls", type=int, default=5)
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample(rng: random.Random, rows: list[dict], count: int, label: str) -> list[dict]:
    if len(rows) < count:
        raise RuntimeError(f"Need {count} {label} questions, found {len(rows)}")
    return rng.sample(sorted(rows, key=lambda row: str(row["question_id"])), count)


def main() -> int:
    args = parse_args()
    if args.enumeration_controls + args.update_controls > args.control_count:
        raise ValueError("Named control strata cannot exceed --control-count")

    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    primary = {row["question_id"]: row for row in _read_jsonl(args.primary_baseline)}
    independent = {
        row["question_id"]: row for row in _read_jsonl(args.independent_baseline)
    }
    excluded_ids: set[str] = set()
    for path in args.exclude:
        excluded = json.loads(path.read_text(encoding="utf-8"))
        excluded_ids.update(str(row["question_id"]) for row in excluded["results"])

    eligible: list[dict] = []
    for row in retrieval["results"]:
        question_id = str(row["question_id"])
        if (
            question_id in excluded_ids
            or row.get("question_type")
            not in {"multi-session", "single-session-preference"}
            or float(row.get("recall_at_k") or 0.0) != 1.0
        ):
            continue
        if question_id not in primary or question_id not in independent:
            raise RuntimeError(f"Missing baseline judgment for {question_id}")
        copy = dict(row)
        copy["baseline_primary_correct"] = bool(
            primary[question_id]["autoeval_label"]["label"]
        )
        copy["baseline_independent_correct"] = bool(
            independent[question_id]["autoeval_label"]["label"]
        )
        eligible.append(copy)

    recovery_pool = [
        row
        for row in eligible
        if not row["baseline_primary_correct"]
        and not row["baseline_independent_correct"]
    ]
    control_pool = [
        row
        for row in eligible
        if row["baseline_primary_correct"] and row["baseline_independent_correct"]
    ]
    rng = random.Random(args.seed)
    recovery = _sample(rng, recovery_pool, args.recovery_count, "recovery")
    enumeration = _sample(
        rng,
        [row for row in control_pool if ENUMERATION_RE.search(row["question"])],
        args.enumeration_controls,
        "enumeration-control",
    )
    selected_ids = {str(row["question_id"]) for row in enumeration}
    updates = _sample(
        rng,
        [
            row
            for row in control_pool
            if str(row["question_id"]) not in selected_ids
            and UPDATE_RE.search(row["question"])
        ],
        args.update_controls,
        "update-control",
    )
    selected_ids.update(str(row["question_id"]) for row in updates)
    fill = _sample(
        rng,
        [row for row in control_pool if str(row["question_id"]) not in selected_ids],
        args.control_count - len(enumeration) - len(updates),
        "general-control",
    )

    strata = {
        "baseline_incorrect_recovery": recovery,
        "baseline_correct_enumeration": enumeration,
        "baseline_correct_update": updates,
        "baseline_correct_general": fill,
    }
    selected: list[dict] = []
    for stratum, rows in strata.items():
        for row in rows:
            selected.append({**row, "v2_holdout_stratum": stratum})

    report = {
        **{key: value for key, value in retrieval.items() if key != "results"},
        "protocol": {
            **(retrieval.get("protocol") or {}),
            "selection": "preregistered structured-reader-v2 case-control holdout",
            "seed": args.seed,
            "source_retrieval_sha256": _sha256(args.retrieval),
            "primary_baseline_sha256": _sha256(args.primary_baseline),
            "independent_baseline_sha256": _sha256(args.independent_baseline),
            "excluded_question_ids": sorted(excluded_ids),
            "eligibility": [
                "multi-session or single-session-preference",
                "complete gold-session retrieval at top-k",
                "not present in structured-reader v1 failure or control sets",
            ],
            "strata": {name: len(rows) for name, rows in strata.items()},
            "pass_gates": {
                "baseline_correct_retention_min": 0.90,
                "baseline_incorrect_recovery_min": 0.30,
                "required_retained": 17,
                "required_recovered": 3,
            },
        },
        "summary": {
            "question_count": len(selected),
            "baseline_incorrect_count": len(recovery),
            "baseline_correct_count": len(enumeration) + len(updates) + len(fill),
            "enumeration_control_count": len(enumeration),
            "update_control_count": len(updates),
        },
        "results": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
