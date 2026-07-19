from __future__ import annotations

import argparse
import json
import re
import statistics
import string
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_api import (
    SCHEMA_VERSION,
    Provider,
    _chat,
    _cohen_kappa,
    _ensure_manifest,
    _file_sha256,
    _fingerprint,
    _finish_reason,
    _parse_binary_verdict,
    _provider,
    _provider_cost,
    _usage,
    _usage_attempts,
    _wilson_interval,
)
from scripts.backend.evaluate_vault_longmemeval_local import _load_jsonl, _write_jsonl


READER_PROTOCOL = "locomo-official-dialog-rag-short-answer-v1"
JUDGE_PROTOCOL = "locomo-gold-answer-strict-binary-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate saved Vault LOCOMO retrieval using the official short-answer "
            "reader prompt, official token-F1, and two diagnostic LLM judges."
        )
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-answer-tokens", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    return parser.parse_args()


def _conversation_turns(dataset: list[dict]) -> dict[str, dict[str, str]]:
    turns_by_sample: dict[str, dict[str, str]] = {}
    for sample in dataset:
        sample_id = str(sample["sample_id"])
        turns: dict[str, str] = {}
        conversation = sample["conversation"]
        for key, session_turns in conversation.items():
            if (
                not key.startswith("session_")
                or key.endswith("_date_time")
                or not isinstance(session_turns, list)
            ):
                continue
            date = str(conversation.get(f"{key}_date_time") or "")
            for turn in session_turns:
                content = f'{turn.get("speaker", "")} said, "{turn.get("text", "")}"'
                caption = str(turn.get("blip_caption") or "").strip()
                if caption:
                    content += f" and shared {caption}"
                turns[str(turn["dia_id"])] = f"{date}: {content}"
        turns_by_sample[sample_id] = turns
    return turns_by_sample


def _context(row: dict, turns_by_sample: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    sample_id = str(row["sample_id"])
    sample_turns = turns_by_sample[sample_id]
    blocks: list[str] = []
    included: list[str] = []
    for hit in row["retrieved"]:
        if str(hit.get("sample_id")) != sample_id:
            raise RuntimeError(
                f"Cross-conversation retrieval hit for {row['question_id']}: {hit}"
            )
        evidence_id = str(hit["evidence_id"])
        if evidence_id not in sample_turns:
            raise RuntimeError(
                f"Unknown retrieved dialog ID {evidence_id} for {row['question_id']}"
            )
        blocks.append(sample_turns[evidence_id])
        included.append(evidence_id)
    return "\n".join(blocks), included


def _answer_prompt(row: dict, context: str) -> str:
    question = str(row["question"])
    if int(row["category"]) == 2:
        question += " Use DATE of CONVERSATION to answer with an approximate date."
    return f"""{context}

Based on the above context, write an answer in the form of a short phrase for the following question. Answer with exact words from the context whenever possible.

Question: {question} Short answer:
"""


def _judge_prompt(row: dict, hypothesis: str) -> str:
    return f"""I will give you a question, a correct answer, and a response from a model. Answer yes only if the model response contains the correct answer or an equivalent answer. Answer no if it contradicts the correct answer, omits required parts, or is unsupported. Return yes or no only.

Question: {row['question']}

Correct Answer: {row['answer']}

Model Response: {hypothesis}

Is the model response correct?"""


def _stemmer():
    try:
        from nltk.stem import PorterStemmer
    except ImportError as exc:
        raise RuntimeError(
            "The official LOCOMO token-F1 requires nltk. Install it in the benchmark "
            "environment with: python -m pip install nltk"
        ) from exc
    return PorterStemmer()


def _normalize_answer(value: object) -> str:
    text = str(value).replace(",", "").lower()
    text = "".join(character for character in text if character not in string.punctuation)
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def _official_f1_score(prediction: str, answer: str, stemmer) -> float:
    predicted = [stemmer.stem(word) for word in _normalize_answer(prediction).split()]
    gold = [stemmer.stem(word) for word in _normalize_answer(answer).split()]
    common = Counter(predicted) & Counter(gold)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall)


def _official_locomo_score(row: dict, prediction: str, stemmer) -> float:
    category = int(row["category"])
    answer = str(row["answer"])
    if category == 3:
        answer = answer.split(";")[0].strip()
    if category == 1:
        predictions = [value.strip() for value in prediction.split(",")]
        answers = [value.strip() for value in answer.split(",")]
        return statistics.fmean(
            max(_official_f1_score(candidate, gold, stemmer) for candidate in predictions)
            for gold in answers
        )
    if category in {2, 3, 4}:
        return _official_f1_score(prediction, answer, stemmer)
    raise RuntimeError(
        "Category 5 is a separate adversarial abstention task and cannot be mixed "
        "into the standard LOCOMO QA score"
    )


def _checkpoint(path: Path, rows: dict[str, dict], selected_ids: list[str]) -> None:
    _write_jsonl(path, [rows[question_id] for question_id in selected_ids if question_id in rows])


def _generate(
    args: argparse.Namespace,
    provider: Provider,
    selected: list[dict],
    turns_by_sample: dict[str, dict[str, str]],
    path: Path,
    run_fingerprint: str,
) -> list[dict]:
    selected_ids = [str(row["question_id"]) for row in selected]
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if row.get("run_fingerprint") == run_fingerprint
    }
    for position, item in enumerate(selected, start=1):
        question_id = str(item["question_id"])
        previous = existing.get(question_id)
        if previous and previous.get("reader_finish_reason") != "length":
            continue
        context, included = _context(item, turns_by_sample)
        started = time.perf_counter()
        token_budget = (
            max(256, args.max_answer_tokens * 2)
            if previous and previous.get("reader_finish_reason") == "length"
            else args.max_answer_tokens
        )
        attempt_history = list((previous or {}).get("reader_attempt_history") or [])
        response = _chat(
            provider,
            _answer_prompt(item, context),
            max_tokens=token_budget,
            timeout=args.timeout,
            retries=args.retries,
        )
        attempt_history.append(
            {
                "max_answer_tokens": token_budget,
                "finish_reason": _finish_reason(response),
                "usage": _usage(response),
            }
        )
        row = {
            "question_id": question_id,
            "sample_id": item["sample_id"],
            "category": item["category"],
            "question": item["question"],
            "answer": item["answer"],
            "hypothesis": response["choices"][0]["message"]["content"].strip(),
            "retrieved_evidence_ids": included,
            "context_chars": len(context),
            "reader_provider": provider.name,
            "reader_model": provider.model,
            "reader_protocol": READER_PROTOCOL,
            "run_fingerprint": run_fingerprint,
            "max_answer_tokens": token_budget,
            "reader_attempt_count": len(attempt_history),
            "reader_attempt_history": attempt_history,
            "reader_wall_seconds": round(time.perf_counter() - started, 4),
            "reader_usage": _usage(response),
            "reader_finish_reason": _finish_reason(response),
        }
        existing[question_id] = row
        _checkpoint(path, existing, selected_ids)
        print(f"reader {position}/{len(selected)} {question_id}", flush=True)
    return [existing[question_id] for question_id in selected_ids]


def _judge(
    args: argparse.Namespace,
    provider: Provider,
    hypotheses: list[dict],
    path: Path,
    run_fingerprint: str,
) -> list[dict]:
    selected_ids = [str(row["question_id"]) for row in hypotheses]
    protocol = f"{JUDGE_PROTOCOL}-{provider.name}-{provider.model}"
    hypothesis_by_id = {str(row["question_id"]): row for row in hypotheses}
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if (row.get("autoeval_label") or {}).get("protocol") == protocol
        and str(row["question_id"]) in hypothesis_by_id
        and row.get("hypothesis")
        == hypothesis_by_id[str(row["question_id"])].get("hypothesis")
    }
    for position, hypothesis in enumerate(hypotheses, start=1):
        question_id = str(hypothesis["question_id"])
        if question_id in existing:
            continue
        started = time.perf_counter()
        judge_attempt_history: list[dict] = []
        for verdict_attempt in range(2):
            response = _chat(
                provider,
                _judge_prompt(hypothesis, hypothesis["hypothesis"]),
                max_tokens=10,
                timeout=args.timeout,
                retries=args.retries,
            )
            verdict = response["choices"][0]["message"]["content"].strip()
            judge_attempt_history.append(
                {
                    "raw": verdict,
                    "finish_reason": _finish_reason(response),
                    "usage": _usage(response),
                }
            )
            try:
                label = _parse_binary_verdict(verdict)
                break
            except RuntimeError:
                if verdict_attempt == 1:
                    raise
        row = {
            **hypothesis,
            "judge_run_fingerprint": run_fingerprint,
            "judge_input_fingerprint": _fingerprint(
                [protocol, question_id, hypothesis["hypothesis"]]
            ),
            "autoeval_label": {
                "provider": provider.name,
                "model": provider.model,
                "label": label,
                "raw": verdict,
                "protocol": protocol,
            },
            "judge_wall_seconds": round(time.perf_counter() - started, 4),
            "judge_usage": _usage(response),
            "judge_finish_reason": _finish_reason(response),
            "judge_attempt_count": len(judge_attempt_history),
            "judge_attempt_history": judge_attempt_history,
        }
        existing[question_id] = row
        _checkpoint(path, existing, selected_ids)
        print(f"{provider.name} judge {position}/{len(hypotheses)} {question_id}: {verdict}", flush=True)
    return [existing[question_id] for question_id in selected_ids]


def _judge_metrics(rows: list[dict]) -> dict:
    labels = [bool(row["autoeval_label"]["label"]) for row in rows]
    by_category: dict[int, list[bool]] = defaultdict(list)
    for row, label in zip(rows, labels, strict=True):
        by_category[int(row["category"])].append(label)
    return {
        "question_count": len(rows),
        "correct_count": sum(labels),
        "accuracy": round(statistics.fmean(labels), 4) if labels else None,
        "accuracy_wilson_95": _wilson_interval(sum(labels), len(labels)),
        "accuracy_by_category": {
            str(category): {
                "accuracy": round(statistics.fmean(values), 4),
                "count": len(values),
            }
            for category, values in sorted(by_category.items())
        },
        "protocol": rows[0]["autoeval_label"]["protocol"] if rows else None,
    }


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    selected = retrieval["results"][: args.limit or None]
    if not selected:
        raise RuntimeError("The retrieval artifact contains no selected questions")
    if any(int(row["category"]) == 5 for row in selected):
        raise RuntimeError(
            "Standard LOCOMO QA input contains category 5. Rebuild retrieval with "
            "--category-scope standard; evaluate adversarial abstention separately."
        )
    if any(not str(row.get("answer") or "").strip() for row in selected):
        raise RuntimeError("Standard LOCOMO QA input contains a blank gold answer")
    selected_ids = [str(row["question_id"]) for row in selected]
    if len(selected_ids) != len(set(selected_ids)):
        raise RuntimeError("The retrieval artifact contains duplicate question IDs")

    reader = _provider("kimi", args.reader_model)
    primary_judge = _provider("kimi", args.primary_judge_model)
    independent_judge = _provider("openai", args.independent_judge_model)
    stem = args.output.with_suffix("")
    manifest = _ensure_manifest(
        stem.with_name(stem.name + ".manifest.json"),
        {
            "schema_version": SCHEMA_VERSION,
            "dataset_sha256": _file_sha256(args.dataset),
            "retrieval_sha256": _file_sha256(args.retrieval),
            "selected_question_ids": selected_ids,
            "selected_question_ids_sha256": _fingerprint(selected_ids),
            "reader_protocol": READER_PROTOCOL,
            "judge_protocol": JUDGE_PROTOCOL,
            "reader": {"provider": reader.name, "model": reader.model},
            "primary_judge": {
                "provider": primary_judge.name,
                "model": primary_judge.model,
            },
            "independent_judge": {
                "provider": independent_judge.name,
                "model": independent_judge.model,
            },
            "max_answer_tokens": args.max_answer_tokens,
        },
    )
    run_fingerprint = manifest["fingerprint"]
    hypotheses_path = stem.with_name(stem.name + ".hypotheses.jsonl")
    primary_path = stem.with_name(stem.name + ".kimi-evaluated.jsonl")
    independent_path = stem.with_name(stem.name + ".openai-evaluated.jsonl")
    hypotheses = _generate(
        args,
        reader,
        selected,
        _conversation_turns(dataset),
        hypotheses_path,
        run_fingerprint,
    )
    hypotheses_sha256 = _fingerprint(
        [(row["question_id"], row["hypothesis"]) for row in hypotheses]
    )
    primary = _judge(
        args,
        primary_judge,
        hypotheses,
        primary_path,
        _fingerprint([run_fingerprint, hypotheses_sha256, primary_judge.model]),
    )
    independent = _judge(
        args,
        independent_judge,
        hypotheses,
        independent_path,
        _fingerprint([run_fingerprint, hypotheses_sha256, independent_judge.model]),
    )

    stemmer = _stemmer()
    official_scores = [
        _official_locomo_score(row, row["hypothesis"], stemmer) for row in hypotheses
    ]
    official_by_category: dict[int, list[float]] = defaultdict(list)
    for row, score in zip(hypotheses, official_scores, strict=True):
        official_by_category[int(row["category"])].append(score)
    primary_labels = [bool(row["autoeval_label"]["label"]) for row in primary]
    independent_labels = [bool(row["autoeval_label"]["label"]) for row in independent]
    agreement = [
        left == right
        for left, right in zip(primary_labels, independent_labels, strict=True)
    ]
    retrieval_scores = [
        float(row["recall_at_k"])
        for row in selected
        if row.get("recall_at_k") is not None
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_fingerprint": run_fingerprint,
        "question_count": len(selected),
        "category_scope": "standard (categories 1-4)",
        "dataset_sha256": manifest["dataset_sha256"],
        "retrieval_sha256": manifest["retrieval_sha256"],
        "retrieval_macro_recall_at_k": round(statistics.fmean(retrieval_scores), 6),
        "retrieval_top_k": int((retrieval.get("protocol") or {}).get("top_k") or 10),
        "official_locomo_token_f1": round(statistics.fmean(official_scores), 4),
        "official_locomo_token_f1_by_category": {
            str(category): {
                "f1": round(statistics.fmean(scores), 4),
                "count": len(scores),
            }
            for category, scores in sorted(official_by_category.items())
        },
        "primary_judge": _judge_metrics(primary),
        "independent_judge": _judge_metrics(independent),
        "judge_agreement": round(statistics.fmean(agreement), 4),
        "judge_cohen_kappa": _cohen_kappa(primary_labels, independent_labels),
        "judge_disagreement_question_ids": [
            row["question_id"]
            for row, left, right in zip(
                hypotheses, primary_labels, independent_labels, strict=True
            )
            if left != right
        ],
        "reader_length_finish_count": sum(
            row.get("reader_finish_reason") == "length" for row in hypotheses
        ),
        "context_chars": {
            "mean": round(
                statistics.fmean(int(row["context_chars"]) for row in hypotheses), 1
            ),
            "max": max(int(row["context_chars"]) for row in hypotheses),
        },
        "comparison_note": (
            "The official token-F1 is reproducible. The binary judges are diagnostic; "
            "Graphify's unpublished atomic-key-fact files and sample manifest prevent "
            "an exact reproduction of its 45.3% judge score."
        ),
        "usage_and_estimated_cost": {
            "kimi_reader": _provider_cost(
                reader, _usage_attempts(hypotheses, kind="reader")
            ),
            "kimi_primary_judge": _provider_cost(
                primary_judge, _usage_attempts(primary, kind="judge")
            ),
            "openai_independent_judge": _provider_cost(
                independent_judge, _usage_attempts(independent, kind="judge")
            ),
        },
    }
    report["usage_and_estimated_cost"]["total_estimated_usd"] = round(
        sum(
            value["estimated_usd_at_uncached_rate"]
            for value in report["usage_and_estimated_cost"].values()
            if isinstance(value, dict)
        ),
        6,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
