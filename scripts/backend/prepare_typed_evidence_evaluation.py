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

from backend.app.core.typed_evidence import SCHEMA_HASH, plan_query
from scripts.backend.evaluate_vault_longmemeval_local import _reader_route


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare leak-free typed-evidence development or fresh evaluation manifests."
    )
    parser.add_argument("--mode", choices=("development", "fresh"), required=True)
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline-hypotheses", type=Path, required=True)
    parser.add_argument("--primary-baseline", type=Path, required=True)
    parser.add_argument("--independent-baseline", type=Path, required=True)
    parser.add_argument("--development-artifact", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20_260_718)
    return parser.parse_args()


def _json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> dict[str, dict]:
    return {
        str(row["question_id"]): row
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _usage_prompt_tokens(row: dict) -> int:
    attempts = row.get("reader_attempt_history") or []
    if attempts:
        return sum(int((attempt.get("usage") or {}).get("prompt_tokens") or 0) for attempt in attempts)
    return int((row.get("reader_usage") or {}).get("prompt_tokens") or 0)


def _decorate(
    row: dict,
    references: dict[str, dict],
    hypotheses: dict[str, dict],
    primary: dict[str, dict],
    independent: dict[str, dict],
) -> dict:
    question_id = str(row["question_id"])
    reference = references[question_id]
    hypothesis = hypotheses[question_id]
    primary_correct = bool(primary[question_id]["autoeval_label"]["label"])
    independent_correct = bool(independent[question_id]["autoeval_label"]["label"])
    state = (
        "baseline_correct"
        if primary_correct and independent_correct
        else "baseline_incorrect"
        if not primary_correct and not independent_correct
        else "baseline_judge_disagreement"
    )
    intent = plan_query(reference).intent
    return {
        **row,
        "typed_evidence_intent": intent,
        "expected_reader_route": _reader_route(reference),
        "baseline_state": state,
        "baseline_primary_correct": primary_correct,
        "baseline_independent_correct": independent_correct,
        "baseline_hypothesis": hypothesis["hypothesis"],
        "baseline_reader_prompt_tokens": _usage_prompt_tokens(hypothesis),
        "baseline_reader_wall_seconds": float(hypothesis.get("reader_wall_seconds") or 0.0),
    }


def _sample(rng: random.Random, rows: list[dict], count: int) -> list[dict]:
    if len(rows) < count:
        raise RuntimeError(f"Need {count} rows, found {len(rows)}")
    return rng.sample(sorted(rows, key=lambda row: str(row["question_id"])), count)


def main() -> int:
    args = parse_args()
    retrieval = _json(args.retrieval)
    assert isinstance(retrieval, dict)
    references_list = _json(args.dataset)
    assert isinstance(references_list, list)
    references = {str(row["question_id"]): row for row in references_list}
    hypotheses = _jsonl(args.baseline_hypotheses)
    primary = _jsonl(args.primary_baseline)
    independent = _jsonl(args.independent_baseline)
    retrieval_by_id = {
        str(row["question_id"]): row for row in retrieval["results"]
    }

    development_ids: set[str] = set()
    artifact_hashes: dict[str, str] = {}
    for path in args.development_artifact:
        artifact = _json(path)
        assert isinstance(artifact, dict)
        development_ids.update(str(row["question_id"]) for row in artifact["results"])
        artifact_hashes[str(path)] = _sha256(path)

    eligible = [
        _decorate(row, references, hypotheses, primary, independent)
        for question_id, row in retrieval_by_id.items()
        if question_id in references
        and not row.get("abstention")
        and float(row.get("recall_at_k") or 0.0) == 1.0
    ]
    rng = random.Random(args.seed)
    if args.mode == "development":
        selected = [
            row
            for row in eligible
            if str(row["question_id"]) in development_ids
            and row["typed_evidence_intent"] != "unsupported"
        ]
        selection = "all typed-operation questions from previously inspected development artifacts"
        pass_gates = None
    else:
        untouched = [row for row in eligible if str(row["question_id"]) not in development_ids]
        typed = [row for row in untouched if row["typed_evidence_intent"] != "unsupported"]
        typed_controls = [row for row in typed if row["baseline_state"] == "baseline_correct"]
        typed_disagreements = [
            row for row in typed if row["baseline_state"] == "baseline_judge_disagreement"
        ]
        fallback_recovery = [
            row
            for row in untouched
            if row["typed_evidence_intent"] == "unsupported"
            and row["baseline_state"] == "baseline_incorrect"
        ]
        fallback_controls = [
            row
            for row in untouched
            if row["typed_evidence_intent"] == "unsupported"
            and row["baseline_state"] == "baseline_correct"
        ]
        selected = typed_controls + typed_disagreements + fallback_recovery
        selected += _sample(rng, fallback_controls, 30 - len(selected))
        for row in selected:
            row["holdout_stratum"] = (
                f"{row['baseline_state']}_"
                + ("typed" if row["typed_evidence_intent"] != "unsupported" else "fallback")
            )
        selection = "preregistered typed-v1 fresh holdout excluding every development artifact"
        control_count = sum(row["baseline_state"] == "baseline_correct" for row in selected)
        recovery_count = sum(row["baseline_state"] == "baseline_incorrect" for row in selected)
        pass_gates = {
            "required_retained": max(0, control_count - 2),
            "required_recovered": min(2, recovery_count),
            "minimum_control_stratum_retention": 0.75,
            "minimum_judge_agreement": 0.90,
            "maximum_prompt_token_ratio": 1.25,
            "maximum_mean_latency_ratio": 1.75,
        }

    if not selected:
        raise RuntimeError("Selection produced no questions")
    ids = [str(row["question_id"]) for row in selected]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Selection produced duplicate question IDs")
    selected.sort(key=lambda row: ids.index(str(row["question_id"])))
    protocol = {
        **(retrieval.get("protocol") or {}),
        "selection": selection,
        "seed": args.seed,
        "typed_evidence_schema_hash": SCHEMA_HASH,
        "source_retrieval_sha256": _sha256(args.retrieval),
        "dataset_sha256": _sha256(args.dataset),
        "baseline_hypotheses_sha256": _sha256(args.baseline_hypotheses),
        "primary_baseline_sha256": _sha256(args.primary_baseline),
        "independent_baseline_sha256": _sha256(args.independent_baseline),
        "development_artifact_hashes": artifact_hashes,
        "excluded_development_question_ids": sorted(development_ids),
    }
    if pass_gates is not None:
        protocol["pass_gates"] = pass_gates
    summary = {
        "question_count": len(selected),
        "typed_question_count": sum(row["typed_evidence_intent"] != "unsupported" for row in selected),
        "baseline_correct_count": sum(row["baseline_state"] == "baseline_correct" for row in selected),
        "baseline_incorrect_count": sum(row["baseline_state"] == "baseline_incorrect" for row in selected),
        "baseline_judge_disagreement_count": sum(
            row["baseline_state"] == "baseline_judge_disagreement" for row in selected
        ),
        "intent_counts": {
            intent: sum(row["typed_evidence_intent"] == intent for row in selected)
            for intent in sorted({str(row["typed_evidence_intent"]) for row in selected})
        },
    }
    output = {
        **{key: value for key, value in retrieval.items() if key != "results"},
        "protocol": protocol,
        "summary": summary,
        "results": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
