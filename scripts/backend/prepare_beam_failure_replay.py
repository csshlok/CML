from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROTOCOL = "beam-cached-paired-flip-replay-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the adjudicated paired flips from a completed BEAM development "
            "run into a small checkpointable replay set. Makes no model or API calls."
        )
    )
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _labels(rows: list[dict]) -> dict[tuple[str, str], bool]:
    return {
        (str(row["arm"]), str(row["question_id"])): bool(row["correct"])
        for row in rows
    }


def final_labels(
    primary_rows: list[dict],
    independent_rows: list[dict],
    adjudicated_rows: list[dict],
) -> dict[tuple[str, str], bool]:
    primary = _labels(primary_rows)
    independent = _labels(independent_rows)
    adjudicated = _labels(adjudicated_rows)
    if set(primary) != set(independent):
        raise ValueError("primary_and_independent_judge_keys_differ")
    final: dict[tuple[str, str], bool] = {}
    for key, primary_label in primary.items():
        independent_label = independent[key]
        if primary_label == independent_label:
            final[key] = primary_label
        elif key in adjudicated:
            final[key] = adjudicated[key]
        else:
            raise ValueError(f"unadjudicated_disagreement:{key[0]}:{key[1]}")
    return final


def build_replay(
    questions: list[dict],
    final: dict[tuple[str, str], bool],
) -> tuple[list[dict], dict]:
    by_id = {str(row["question_id"]): row for row in questions}
    question_ids = sorted({question_id for _, question_id in final})
    cases: list[dict] = []
    for question_id in question_ids:
        baseline = final[("baseline", question_id)]
        candidate = final[("candidate", question_id)]
        if baseline == candidate:
            continue
        question = by_id[question_id]
        cases.append(
            {
                "question_id": question_id,
                "category": str(question["category"]),
                "prior_baseline_correct": baseline,
                "prior_candidate_correct": candidate,
                "flip_kind": "candidate_win" if candidate else "baseline_win",
            }
        )
    selected = [by_id[row["question_id"]] for row in cases]
    manifest = {
        "protocol": PROTOCOL,
        "evaluation_role": "development",
        "case_count": len(cases),
        "candidate_win_count": sum(row["flip_kind"] == "candidate_win" for row in cases),
        "baseline_win_count": sum(row["flip_kind"] == "baseline_win" for row in cases),
        "cases": cases,
        "use_policy": (
            "Development-only regression replay. May be run locally or with cached "
            "responses repeatedly, but never used as training data or headline accuracy."
        ),
    }
    return selected, manifest


def main() -> int:
    args = parse_args()
    primary_path = args.source_run_dir / "judged-kimi.jsonl"
    independent_path = args.source_run_dir / "judged-openai.jsonl"
    adjudicated_path = args.source_run_dir / "adjudicated-openai.jsonl"
    source_paths = (primary_path, independent_path, adjudicated_path, args.questions)
    final = final_labels(
        _load_jsonl(primary_path),
        _load_jsonl(independent_path),
        _load_jsonl(adjudicated_path),
    )
    questions = _load_jsonl(args.questions)
    selected, manifest = build_replay(questions, final)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    questions_path = args.output_dir / "failure-replay-questions.jsonl"
    questions_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in selected
        ),
        encoding="utf-8",
    )
    manifest["source_artifacts"] = [
        {"path": str(path), "sha256": _sha256(path)} for path in source_paths
    ]
    manifest["questions_sha256"] = _sha256(questions_path)
    (args.output_dir / "failure-replay-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
