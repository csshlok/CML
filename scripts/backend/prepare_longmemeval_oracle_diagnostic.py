from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path


DEFAULT_RECOVERY_BY_TYPE = {
    "multi-session": 5,
    "temporal-reasoning": 4,
    "knowledge-update": 1,
    "single-session-preference": 1,
    "other": 1,
}
DEFAULT_CONTROL_BY_TYPE = {
    "multi-session": 3,
    "temporal-reasoning": 2,
    "knowledge-update": 1,
    "single-session-preference": 1,
    "other": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a development-only LongMemEval panel for gold-session, raw-context, "
            "and stronger-reader bottleneck diagnostics."
        )
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--independent", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20_260_723)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _type_bucket(question_type: str, allocation: dict[str, int]) -> str:
    return question_type if question_type in allocation else "other"


def _sample_strata(
    *,
    rng: random.Random,
    rows: list[dict],
    allocation: dict[str, int],
    label: str,
) -> list[dict]:
    selected: list[dict] = []
    for bucket, count in allocation.items():
        eligible = [
            row
            for row in rows
            if _type_bucket(str(row.get("question_type") or ""), allocation) == bucket
        ]
        if len(eligible) < count:
            raise RuntimeError(
                f"Need {count} {label} rows in {bucket}, found {len(eligible)}"
            )
        selected.extend(
            rng.sample(
                sorted(eligible, key=lambda row: str(row["question_id"])),
                count,
            )
        )
    return selected


def prepare(
    *,
    retrieval: dict,
    primary_rows: list[dict],
    independent_rows: list[dict],
    seed: int,
) -> tuple[dict, dict, dict]:
    primary = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in primary_rows
    }
    independent = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in independent_rows
    }
    eligible: list[dict] = []
    for source in retrieval["results"]:
        question_id = str(source["question_id"])
        if (
            source.get("abstention")
            or float(source.get("recall_at_k") or 0.0) != 1.0
        ):
            continue
        if question_id not in primary or question_id not in independent:
            raise RuntimeError(f"Missing baseline judgment for {question_id}")
        eligible.append(
            {
                **source,
                "baseline_primary_correct": primary[question_id],
                "baseline_independent_correct": independent[question_id],
            }
        )

    recoveries = [
        row
        for row in eligible
        if not row["baseline_primary_correct"]
        and not row["baseline_independent_correct"]
    ]
    controls = [
        row
        for row in eligible
        if row["baseline_primary_correct"] and row["baseline_independent_correct"]
    ]
    rng = random.Random(seed)
    selected_recoveries = _sample_strata(
        rng=rng,
        rows=recoveries,
        allocation=DEFAULT_RECOVERY_BY_TYPE,
        label="recovery",
    )
    selected_controls = _sample_strata(
        rng=rng,
        rows=controls,
        allocation=DEFAULT_CONTROL_BY_TYPE,
        label="control",
    )

    selected: list[dict] = []
    recovery_ids = {str(row["question_id"]) for row in selected_recoveries}
    for row in selected_recoveries + selected_controls:
        selected.append(
            {
                **row,
                "diagnostic_stratum": (
                    "baseline_dual_incorrect"
                    if str(row["question_id"]) in recovery_ids
                    else "baseline_dual_correct_control"
                ),
            }
        )
    selected.sort(key=lambda row: str(row["question_id"]))

    protocol = {
        **(retrieval.get("protocol") or {}),
        "selection": "development-only deterministic oracle diagnostic panel",
        "seed": seed,
        "answer_text_used_for_selection": False,
        "benchmark_specific_lexical_routing": False,
        "eligibility": [
            "not an abstention question",
            "complete gold-session retrieval at top-k",
            "dual-judge baseline failure or dual-judge baseline control",
        ],
        "recovery_by_type": DEFAULT_RECOVERY_BY_TYPE,
        "control_by_type": DEFAULT_CONTROL_BY_TYPE,
        "promotion_eligible": False,
    }
    base = {
        **{key: value for key, value in retrieval.items() if key not in {"results", "protocol"}},
        "protocol": protocol,
        "summary": {
            "question_count": len(selected),
            "recovery_count": len(selected_recoveries),
            "control_count": len(selected_controls),
            "question_type_counts": dict(
                Counter(str(row.get("question_type") or "") for row in selected)
            ),
        },
        "results": selected,
    }
    oracle_rows = []
    for row in selected:
        gold_ids = [str(item) for item in row.get("answer_session_ids") or []]
        oracle_rows.append(
            {
                **row,
                "retrieved_session_ids": gold_ids,
                "found_session_ids": gold_ids,
                "rank": gold_ids,
                "recall_at_k": 1.0,
                "any_evidence_at_k": bool(gold_ids),
            }
        )
    oracle = {
        **base,
        "protocol": {
            **protocol,
            "context_arm": "answer-aware gold sessions only",
            "answer_session_ids_used_for_context": True,
            "promotion_eligible": False,
        },
        "results": oracle_rows,
    }
    manifest = {
        "protocol": "longmemeval-oracle-diagnostic-panel-v1",
        "seed": seed,
        "question_ids": [str(row["question_id"]) for row in selected],
        "recovery_question_ids": sorted(recovery_ids),
        "control_question_ids": sorted(
            str(row["question_id"])
            for row in selected
            if str(row["question_id"]) not in recovery_ids
        ),
        "promotion_eligible": False,
    }
    return base, oracle, manifest


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    baseline, oracle, manifest = prepare(
        retrieval=retrieval,
        primary_rows=_jsonl(args.primary),
        independent_rows=_jsonl(args.independent),
        seed=args.seed,
    )
    manifest["source_hashes"] = {
        "retrieval_sha256": _sha256(args.retrieval),
        "primary_sha256": _sha256(args.primary),
        "independent_sha256": _sha256(args.independent),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "retrieved": (args.output_dir / "retrieved-panel.json", baseline),
        "gold": (args.output_dir / "gold-session-panel.json", oracle),
        "manifest": (args.output_dir / "manifest.json", manifest),
    }
    for path, payload in outputs.values():
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                **baseline["summary"],
                "output_dir": str(args.output_dir),
                "question_ids": manifest["question_ids"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
