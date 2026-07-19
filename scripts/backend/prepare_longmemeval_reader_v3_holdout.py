from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_local import _reader_route


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a preregistered LongMemEval routed-reader holdout."
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--baseline-hypotheses", type=Path, required=True)
    parser.add_argument("--primary-baseline", type=Path, required=True)
    parser.add_argument("--independent-baseline", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20_260_719)
    parser.add_argument("--reader-version", choices=("v3", "v4"), default="v3")
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


def _usage_prompt_tokens(row: dict) -> int:
    attempts = row.get("reader_attempt_history") or []
    if attempts:
        return sum(
            int((attempt.get("usage") or {}).get("prompt_tokens") or 0)
            for attempt in attempts
        )
    return int((row.get("reader_usage") or {}).get("prompt_tokens") or 0)


def _sample(rng: random.Random, rows: list[dict], count: int, label: str) -> list[dict]:
    if len(rows) < count:
        raise RuntimeError(f"Need {count} {label} questions, found {len(rows)}")
    return rng.sample(sorted(rows, key=lambda row: str(row["question_id"])), count)


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    hypotheses = {row["question_id"]: row for row in _read_jsonl(args.baseline_hypotheses)}
    primary = {row["question_id"]: row for row in _read_jsonl(args.primary_baseline)}
    independent = {
        row["question_id"]: row for row in _read_jsonl(args.independent_baseline)
    }
    excluded_ids: set[str] = set()
    for path in args.exclude:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        excluded_ids.update(str(row["question_id"]) for row in artifact["results"])

    eligible: list[dict] = []
    for row in retrieval["results"]:
        question_id = str(row["question_id"])
        if (
            question_id in excluded_ids
            or row.get("abstention")
            or float(row.get("recall_at_k") or 0.0) != 1.0
        ):
            continue
        if (
            question_id not in hypotheses
            or question_id not in primary
            or question_id not in independent
        ):
            raise RuntimeError(f"Missing baseline data for {question_id}")
        baseline = hypotheses[question_id]
        eligible.append(
            {
                **row,
                "expected_reader_route": _reader_route(row),
                "baseline_primary_correct": bool(
                    primary[question_id]["autoeval_label"]["label"]
                ),
                "baseline_independent_correct": bool(
                    independent[question_id]["autoeval_label"]["label"]
                ),
                "baseline_reader_prompt_tokens": _usage_prompt_tokens(baseline),
                "baseline_reader_wall_seconds": float(
                    baseline.get("reader_wall_seconds") or 0.0
                ),
            }
        )

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
    recovery_aggregation = _sample(
        rng,
        [row for row in recovery_pool if row["expected_reader_route"] == "aggregation"],
        5,
        "aggregation recovery",
    )
    recovery_ids = {str(row["question_id"]) for row in recovery_aggregation}
    recovery_synthesis = _sample(
        rng,
        [
            row
            for row in recovery_pool
            if row["expected_reader_route"] == "synthesis-update"
            and str(row["question_id"]) not in recovery_ids
        ],
        5,
        "synthesis/update recovery",
    )

    control_preference = _sample(
        rng,
        [row for row in control_pool if row["expected_reader_route"] == "preference"],
        5,
        "preference control",
    )
    control_aggregation = _sample(
        rng,
        [row for row in control_pool if row["expected_reader_route"] == "aggregation"],
        5,
        "aggregation control",
    )
    control_update = _sample(
        rng,
        [
            row
            for row in control_pool
            if row["expected_reader_route"] == "synthesis-update"
            and row.get("question_type") == "knowledge-update"
        ],
        5,
        "knowledge-update control",
    )
    named_ids = {
        str(row["question_id"])
        for row in control_preference + control_aggregation + control_update
    }
    control_general = _sample(
        rng,
        [
            row
            for row in control_pool
            if row["expected_reader_route"] == "synthesis-update"
            and row.get("question_type") != "knowledge-update"
            and str(row["question_id"]) not in named_ids
        ],
        5,
        "general synthesis control",
    )

    strata = {
        "baseline_incorrect_aggregation": recovery_aggregation,
        "baseline_incorrect_synthesis_update": recovery_synthesis,
        "baseline_correct_preference": control_preference,
        "baseline_correct_aggregation": control_aggregation,
        "baseline_correct_knowledge_update": control_update,
        "baseline_correct_general_synthesis": control_general,
    }
    selected: list[dict] = []
    for stratum, rows in strata.items():
        for row in rows:
            selected.append({**row, "holdout_stratum": stratum})

    report = {
        **{key: value for key, value in retrieval.items() if key != "results"},
        "protocol": {
            **(retrieval.get("protocol") or {}),
            "selection": (
                f"preregistered routed-reader-{args.reader_version} untouched holdout"
            ),
            "seed": args.seed,
            "source_retrieval_sha256": _sha256(args.retrieval),
            "baseline_hypotheses_sha256": _sha256(args.baseline_hypotheses),
            "primary_baseline_sha256": _sha256(args.primary_baseline),
            "independent_baseline_sha256": _sha256(args.independent_baseline),
            "excluded_question_ids": sorted(excluded_ids),
            "eligibility": [
                "complete gold-session retrieval at top-k",
                "not an abstention question",
                "not present in structured-reader v1 or v2 development sets",
            ],
            "strata": {name: len(rows) for name, rows in strata.items()},
            "pass_gates": {
                "required_retained": 18,
                "required_recovered": 3,
                "minimum_control_stratum_retention": 0.80,
                "minimum_judge_agreement": 0.90,
                "maximum_prompt_token_ratio": 1.10,
                "maximum_mean_latency_ratio": 1.50,
            },
        },
        "summary": {
            "question_count": len(selected),
            "baseline_incorrect_count": 10,
            "baseline_correct_count": 20,
            "strata": {name: len(rows) for name, rows in strata.items()},
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
