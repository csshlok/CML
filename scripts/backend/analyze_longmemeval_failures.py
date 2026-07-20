from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_api import _pack_reader_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify LongMemEval failures without additional model calls."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reader-token-budget", type=int, default=10_000)
    parser.add_argument("--reader-budget-safety-factor", type=float, default=1.0)
    return parser.parse_args()


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _artifact_paths(report_path: Path) -> tuple[Path, Path, Path]:
    stem = report_path.with_suffix("")
    return (
        stem.with_name(stem.name + ".hypotheses.jsonl"),
        stem.with_name(stem.name + ".kimi-evaluated.jsonl"),
        stem.with_name(stem.name + ".openai-evaluated.jsonl"),
    )


def _question_family(question: str, question_type: str) -> str:
    if question_type == "temporal-reasoning" or re.search(
        r"\b(when|before|after|days?|weeks?|months?|years?|first|last)\b", question,
        re.IGNORECASE,
    ):
        return "temporal_resolution"
    if question_type == "knowledge-update" or re.search(
        r"\b(current|latest|now|still|updated|changed)\b", question, re.I
    ):
        return "supersession_or_latest_state"
    if question_type == "single-session-preference":
        return "preference_synthesis"
    if re.search(r"\b(how many|how much|total|combined|times)\b", question, re.I):
        return "numeric_aggregation"
    if question_type == "multi-session":
        return "cross_session_synthesis"
    return "entity_or_fact_selection"


def main() -> int:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    retrieval_payload = json.loads(args.retrieval.read_text(encoding="utf-8"))
    references = {
        str(row["question_id"]): row
        for row in json.loads(args.dataset.read_text(encoding="utf-8"))
    }
    retrieval = {
        str(row["question_id"]): row for row in retrieval_payload["results"]
    }
    hypotheses_path, primary_path, independent_path = _artifact_paths(args.report)
    hypotheses = {str(row["question_id"]): row for row in _jsonl(hypotheses_path)}
    primary = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in _jsonl(primary_path)
    }
    independent = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in _jsonl(independent_path)
    }
    runtime_args = SimpleNamespace(
        context_packing="claim-first-v1",
        reader_token_budget=args.reader_token_budget,
        reader_budget_safety_factor=args.reader_budget_safety_factor,
        max_context_chars=int(report.get("max_context_chars") or 200_000),
        reader_prompt="typed-v1",
    )

    rows: list[dict] = []
    for question_id, hypothesis in hypotheses.items():
        if primary[question_id] and independent[question_id]:
            continue
        reference = references[question_id]
        retrieved_ids = [
            str(item) for item in retrieval[question_id]["retrieved_session_ids"]
        ]
        context, context_meta = _pack_reader_context(
            runtime_args, reference, retrieved_ids
        )
        answer_ids = {str(item) for item in reference.get("answer_session_ids") or []}
        retrieved_set = set(retrieved_ids)
        included_set = {
            str(item) for item in context_meta.get("included_session_ids") or []
        }
        gold = _normalize(reference.get("answer"))
        gold_in_context = bool(gold and gold in _normalize(context))
        gold_in_hypothesis = bool(gold and gold in _normalize(hypothesis["hypothesis"]))
        if hypothesis.get("reader_content_filtered"):
            stage = "provider_refusal"
        elif hypothesis.get("reader_finish_reason") == "length":
            stage = "reader_truncation"
        elif answer_ids and not answer_ids.issubset(retrieved_set):
            stage = "retrieval_omission"
        elif answer_ids and not answer_ids.issubset(included_set):
            stage = "session_packing_omission"
        elif not gold_in_context:
            stage = "claim_selection_or_paraphrase"
        elif primary[question_id] != independent[question_id]:
            stage = "judge_disagreement"
        elif gold_in_hypothesis:
            stage = "judge_or_rubric_mismatch"
        else:
            stage = "reader_reasoning"
        rows.append(
            {
                "question_id": question_id,
                "question_type": reference.get("question_type"),
                "question": reference.get("question"),
                "gold_answer": reference.get("answer"),
                "hypothesis": hypothesis.get("hypothesis"),
                "primary_correct": primary[question_id],
                "independent_correct": independent[question_id],
                "failure_stage": stage,
                "question_family": _question_family(
                    str(reference.get("question") or ""),
                    str(reference.get("question_type") or ""),
                ),
                "answer_session_count": len(answer_ids),
                "answer_sessions_retrieved": len(answer_ids & retrieved_set),
                "answer_sessions_packed": len(answer_ids & included_set),
                "gold_literal_in_context": gold_in_context,
                "gold_literal_in_hypothesis": gold_in_hypothesis,
                "reader_prompt_tokens": int(
                    hypothesis.get("reader_prompt_tokens") or 0
                ),
            }
        )

    payload = {
        "protocol": "longmemeval-deterministic-failure-analysis-v2",
        "source_report": str(args.report),
        "question_count": int(report["question_count"]),
        "dual_judge_correct_count": sum(
            primary[item] and independent[item] for item in hypotheses
        ),
        "analyzed_failure_count": len(rows),
        "failure_stage_counts": dict(Counter(row["failure_stage"] for row in rows)),
        "question_family_counts": dict(Counter(row["question_family"] for row in rows)),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in payload.items() if key != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
