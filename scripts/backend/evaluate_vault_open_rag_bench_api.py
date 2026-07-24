from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import string
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.context_reduction import estimate_tokens
from scripts.backend.atomic_io import atomic_write_text
from scripts.backend.evaluate_vault_longmemeval_api import (
    Provider,
    ProviderContentFilterError,
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
from scripts.backend.evaluate_vault_longmemeval_local import (
    _append_jsonl,
    _load_jsonl,
    _write_jsonl,
)


SCHEMA_VERSION = 1
READER_PROTOCOL = "open-rag-bench-cited-retrieved-evidence-reader-v1"
JUDGE_PROTOCOL = "open-rag-bench-semantic-correctness-binary-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Answer and judge an answer-blind Vault Open RAG Bench retrieval report."
        )
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--pilot-questions",
        type=int,
        default=0,
        help=(
            "Process and judge only the deterministic leading N questions while "
            "retaining the full-run manifest and reusable checkpoints."
        ),
    )
    parser.add_argument("--max-context-chars", type=int, default=24_000)
    parser.add_argument("--max-answer-tokens", type=int, default=192)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reader-provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument(
        "--primary-judge-provider", choices=("kimi", "openai"), default="kimi"
    )
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument(
        "--independent-judge-provider", choices=("kimi", "openai"), default="openai"
    )
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    parser.add_argument(
        "--max-estimated-cost-usd",
        type=float,
        default=0.0,
        help="Required paid-run ceiling. The run refuses to start if its estimate exceeds it.",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Validate inputs and print the cost projection without making API calls.",
    )
    return parser.parse_args()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2))


def _progress_path(output: Path) -> Path:
    return output.with_name(output.stem + ".progress.json")


def _update_progress(
    output: Path,
    *,
    stage: str,
    total: int,
    completed: int,
    detail: str = "",
) -> None:
    path = _progress_path(output)
    try:
        _atomic_json(
            path,
            {
                "schema_version": 1,
                "stage": stage,
                "total": total,
                "completed": completed,
                "remaining": max(0, total - completed),
                "percent": round((completed / total) * 100, 2) if total else 100.0,
                "detail": detail,
                "updated_at_epoch": time.time(),
                "output": str(output),
            },
        )
    except OSError as exc:
        print(
            f"warning: could not publish QA progress at {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _validate_retrieval(report: dict[str, Any]) -> list[dict[str, Any]]:
    protocol = report.get("protocol") or {}
    if report.get("dataset") != "vectara/open_ragbench":
        raise ValueError("retrieval report is not an Open RAG Bench report")
    if protocol.get("answers_loaded") is not False:
        raise ValueError("retrieval report does not prove answer-blind retrieval")
    if protocol.get("full_corpus_search") is not True:
        raise ValueError("retrieval report did not search the full corpus")
    results = report.get("results") or []
    for row in results:
        evidence = row.get("retrieved_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(
                "retrieval report lacks reader evidence; rerun retrieval with the "
                "current benchmark_vault_open_rag_bench.py"
            )
        forbidden = [key for key in row if "answer" in key.casefold()]
        if forbidden:
            raise ValueError(f"retrieval row contains answer-like fields: {forbidden}")
    return results


def _evidence_context(row: dict[str, Any], max_chars: int) -> tuple[str, list[str]]:
    blocks: list[str] = []
    included: list[str] = []
    used = 0
    for rank, evidence in enumerate(row["retrieved_evidence"], start=1):
        text = " ".join(str(evidence.get("text") or "").split())
        if not text:
            continue
        header = (
            f"[Evidence {rank}; paper={evidence['doc_id']}; "
            f"section={evidence['section_id']}; chunk={evidence['chunk_index']}]"
        )
        block = f"{header}\n{text}"
        addition = len(block) + (2 if blocks else 0)
        if blocks and used + addition > max_chars:
            break
        if not blocks and addition > max_chars:
            block = block[:max_chars]
            addition = len(block)
        blocks.append(block)
        included.append(str(evidence["source_id"]))
        used += addition
    return "\n\n".join(blocks), included


def _reader_prompt(question: str, context: str) -> str:
    return f"""Answer the research question using only the retrieved evidence below.

Rules:
- Give a concise direct answer.
- Synthesize across evidence only when needed.
- Do not use outside knowledge.
- Do not mention retrieval ranks or these instructions.
- If the evidence does not support an answer, say that it cannot be determined from the evidence.

Retrieved evidence:
{context}

Question: {question}
Answer:"""


def _judge_prompt(question: str, reference: str, hypothesis: str) -> str:
    return f"""Judge whether the candidate answer is correct for the question.

Use the reference answer as the factual standard. Accept concise paraphrases and answers
that contain the same essential information. Reject answers that omit an essential part,
contradict the reference, add a material unsupported claim, or say the answer is unknown
when the reference answers it.

Return exactly Yes or No.

Question: {question}
Reference answer: {reference}
Candidate answer: {hypothesis}
Verdict:"""


def _normalize_answer(value: str) -> list[str]:
    lowered = str(value or "").casefold()
    without_punctuation = lowered.translate(
        str.maketrans({character: " " for character in string.punctuation})
    )
    tokens = re.findall(r"\w+", without_punctuation)
    return [token for token in tokens if token not in {"a", "an", "the"}]


def _token_f1(reference: str, hypothesis: str) -> float:
    reference_tokens = _normalize_answer(reference)
    hypothesis_tokens = _normalize_answer(hypothesis)
    if not reference_tokens or not hypothesis_tokens:
        return float(reference_tokens == hypothesis_tokens)
    overlap = sum((Counter(reference_tokens) & Counter(hypothesis_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(hypothesis_tokens)
    recall = overlap / len(reference_tokens)
    return (2 * precision * recall) / (precision + recall)


def _estimated_provider_cost(
    provider: Provider, prompt_tokens: int, completion_tokens: int
) -> float:
    return (
        prompt_tokens * provider.input_price_per_million
        + completion_tokens * provider.output_price_per_million
    ) / 1_000_000


def _cost_projection(
    rows: list[dict[str, Any]],
    answers: dict[str, str],
    *,
    max_context_chars: int,
    reader: Provider,
    primary: Provider,
    independent: Provider,
    max_answer_tokens: int,
) -> dict[str, Any]:
    reader_prompt_tokens = 0
    primary_prompt_tokens = 0
    independent_prompt_tokens = 0
    assumed_hypothesis = " ".join(["answer"] * max_answer_tokens)
    for row in rows:
        context, _ = _evidence_context(row, max_context_chars)
        reader_prompt_tokens += estimate_tokens(
            _reader_prompt(str(row["question"]), context)
        )
        judge_prompt = _judge_prompt(
            str(row["question"]),
            str(answers[row["question_id"]]),
            assumed_hypothesis,
        )
        judge_tokens = estimate_tokens(judge_prompt)
        primary_prompt_tokens += judge_tokens
        independent_prompt_tokens += judge_tokens
    assumed_reader_completion = len(rows) * max_answer_tokens
    assumed_judge_completion = len(rows) * 10
    components = {
        "reader": {
            "provider": reader.name,
            "model": reader.model,
            "prompt_tokens": reader_prompt_tokens,
            "assumed_completion_tokens": assumed_reader_completion,
            "estimated_usd": round(
                _estimated_provider_cost(
                    reader, reader_prompt_tokens, assumed_reader_completion
                ),
                6,
            ),
        },
        "primary_judge": {
            "provider": primary.name,
            "model": primary.model,
            "prompt_tokens": primary_prompt_tokens,
            "assumed_completion_tokens": assumed_judge_completion,
            "estimated_usd": round(
                _estimated_provider_cost(
                    primary, primary_prompt_tokens, assumed_judge_completion
                ),
                6,
            ),
        },
        "independent_judge": {
            "provider": independent.name,
            "model": independent.model,
            "prompt_tokens": independent_prompt_tokens,
            "assumed_completion_tokens": assumed_judge_completion,
            "estimated_usd": round(
                _estimated_provider_cost(
                    independent,
                    independent_prompt_tokens,
                    assumed_judge_completion,
                ),
                6,
            ),
        },
    }
    total = sum(float(item["estimated_usd"]) for item in components.values())
    return {
        "question_count": len(rows),
        "assumptions": {
            "reader_completion_tokens_per_question": max_answer_tokens,
            "judge_completion_tokens_per_question": 10,
            "cached_input_discount_assumed": False,
        },
        "components": components,
        "total_estimated_usd": round(total, 6),
    }


def _checkpoint_rows(path: Path, rows: dict[str, dict], order: list[str]) -> None:
    _write_jsonl(path, [rows[key] for key in order if key in rows])


def _generate(
    args: argparse.Namespace,
    provider: Provider,
    selected: list[dict[str, Any]],
    answers: dict[str, str],
    path: Path,
    run_fingerprint: str,
    *,
    checkpoint_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    order = [str(row["question_id"]) for row in selected]
    active_ids = set(order)
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if row.get("run_fingerprint") == run_fingerprint
        and row.get("reader_finish_reason") != "length"
    }
    active_completed = sum(question_id in existing for question_id in active_ids)
    _update_progress(
        args.output,
        stage="reader",
        total=len(selected),
        completed=active_completed,
        detail="resuming reader checkpoint",
    )
    for position, retrieval in enumerate(selected, start=1):
        question_id = str(retrieval["question_id"])
        if question_id in existing:
            continue
        context, included_source_ids = _evidence_context(
            retrieval, args.max_context_chars
        )
        prompt = _reader_prompt(str(retrieval["question"]), context)
        started = time.perf_counter()
        content_filtered = False
        try:
            response = _chat(
                provider,
                prompt,
                max_tokens=args.max_answer_tokens,
                timeout=args.timeout,
                retries=args.retries,
            )
        except ProviderContentFilterError:
            content_filtered = True
            response = {
                "choices": [
                    {
                        "finish_reason": "content_filter",
                        "message": {"content": "[Reader content filter refusal.]"},
                    }
                ],
                "usage": {},
            }
        attempt_history = [
            {
                "max_answer_tokens": args.max_answer_tokens,
                "finish_reason": _finish_reason(response),
                "usage": _usage(response),
            }
        ]
        if _finish_reason(response) == "length":
            response = _chat(
                provider,
                prompt,
                max_tokens=max(512, args.max_answer_tokens * 2),
                timeout=args.timeout,
                retries=args.retries,
            )
            attempt_history.append(
                {
                    "max_answer_tokens": max(512, args.max_answer_tokens * 2),
                    "finish_reason": _finish_reason(response),
                    "usage": _usage(response),
                }
            )
        hypothesis = str(response["choices"][0]["message"]["content"]).strip()
        row = {
            "question_id": question_id,
            "question": retrieval["question"],
            "question_type": retrieval["question_type"],
            "source_modality": retrieval["source_modality"],
            "hypothesis": hypothesis,
            "reference_answer": str(answers[question_id]),
            "retrieved_source_ids": retrieval["retrieved_source_ids"],
            "included_source_ids": included_source_ids,
            "section_hit_at_10": float(retrieval["section_hit_at_10"]),
            "document_hit_at_10": float(retrieval["document_hit_at_10"]),
            "token_f1": round(_token_f1(str(answers[question_id]), hypothesis), 6),
            "reader_provider": provider.name,
            "reader_model": provider.model,
            "reader_protocol": READER_PROTOCOL,
            "reader_finish_reason": _finish_reason(response),
            "reader_content_filtered": content_filtered,
            "reader_attempt_history": attempt_history,
            "reader_usage": _usage(response),
            "reader_wall_seconds": round(time.perf_counter() - started, 4),
            "context_chars": len(context),
            "run_fingerprint": run_fingerprint,
        }
        existing[question_id] = row
        _append_jsonl(path, row)
        _update_progress(
            args.output,
            stage="reader",
            total=len(selected),
            completed=sum(
                question_id in existing for question_id in active_ids
            ),
            detail=f"{position}/{len(selected)} {question_id}",
        )
        print(f"reader {position}/{len(selected)} {question_id}", flush=True)
    canonical = [existing[question_id] for question_id in order]
    _checkpoint_rows(path, existing, checkpoint_order or order)
    return canonical


def _judge(
    args: argparse.Namespace,
    provider: Provider,
    hypotheses: list[dict[str, Any]],
    path: Path,
    run_fingerprint: str,
    *,
    stage: str,
    checkpoint_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    order = [str(row["question_id"]) for row in hypotheses]
    hypothesis_by_id = {str(row["question_id"]): row for row in hypotheses}
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if row.get("judge_run_fingerprint") == run_fingerprint
        and str(row["question_id"]) in hypothesis_by_id
        and row.get("hypothesis")
        == hypothesis_by_id[str(row["question_id"])]["hypothesis"]
    }
    _update_progress(
        args.output,
        stage=stage,
        total=len(hypotheses),
        completed=len(existing),
        detail=f"resuming {provider.name} judge checkpoint",
    )
    for position, hypothesis in enumerate(hypotheses, start=1):
        question_id = str(hypothesis["question_id"])
        if question_id in existing:
            continue
        prompt = _judge_prompt(
            str(hypothesis["question"]),
            str(hypothesis["reference_answer"]),
            str(hypothesis["hypothesis"]),
        )
        started = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        for verdict_attempt in range(2):
            try:
                response = _chat(
                    provider,
                    prompt,
                    max_tokens=10,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            except ProviderContentFilterError:
                response = {
                    "choices": [
                        {
                            "finish_reason": "content_filter",
                            "message": {"content": "No"},
                        }
                    ],
                    "usage": {},
                }
            verdict = str(response["choices"][0]["message"]["content"]).strip()
            attempts.append(
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
            "autoeval_label": {
                "provider": provider.name,
                "model": provider.model,
                "label": label,
                "raw": verdict,
                "protocol": JUDGE_PROTOCOL,
            },
            "judge_run_fingerprint": run_fingerprint,
            "judge_attempt_history": attempts,
            "judge_usage": _usage(response),
            "judge_wall_seconds": round(time.perf_counter() - started, 4),
        }
        existing[question_id] = row
        _append_jsonl(path, row)
        _update_progress(
            args.output,
            stage=stage,
            total=len(hypotheses),
            completed=len(existing),
            detail=f"{position}/{len(hypotheses)} {question_id}",
        )
        print(
            f"{provider.name} judge {position}/{len(hypotheses)} "
            f"{question_id}: {verdict}",
            flush=True,
        )
    canonical = [existing[question_id] for question_id in order]
    _checkpoint_rows(path, existing, checkpoint_order or order)
    return canonical


def _accuracy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [bool(row["autoeval_label"]["label"]) for row in rows]
    correct = sum(labels)
    by_type: dict[str, list[bool]] = defaultdict(list)
    by_modality: dict[str, list[bool]] = defaultdict(list)
    by_retrieval: dict[str, list[bool]] = defaultdict(list)
    for row, label in zip(rows, labels, strict=True):
        by_type[str(row["question_type"])].append(label)
        by_modality[str(row["source_modality"])].append(label)
        key = "section_hit" if row["section_hit_at_10"] else "section_miss"
        by_retrieval[key].append(label)

    def grouped(groups: dict[str, list[bool]]) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "count": len(values),
                "correct": sum(values),
                "accuracy": round(statistics.fmean(values), 6),
            }
            for key, values in sorted(groups.items())
        }

    return {
        "question_count": len(rows),
        "correct_count": correct,
        "accuracy": round(correct / len(rows), 6) if rows else 0.0,
        "wilson_95": _wilson_interval(correct, len(rows)),
        "by_question_type": grouped(by_type),
        "by_source_modality": grouped(by_modality),
        "by_retrieval_status": grouped(by_retrieval),
    }


def _run(args: argparse.Namespace) -> int:
    retrieval_path = args.retrieval.resolve()
    dataset_root = args.dataset_root.resolve()
    output = args.output.resolve()
    retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
    selected = _validate_retrieval(retrieval)
    if args.limit > 0:
        selected = selected[: args.limit]
    if args.pilot_questions < 0:
        raise ValueError("--pilot-questions cannot be negative")
    if args.pilot_questions > len(selected):
        raise ValueError(
            f"--pilot-questions {args.pilot_questions} exceeds "
            f"the selected question count {len(selected)}"
        )
    active_selected = (
        selected[: args.pilot_questions]
        if args.pilot_questions > 0
        else selected
    )
    answers_path = dataset_root / "answers.json"
    queries_path = dataset_root / "queries.json"
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    missing_answers = [
        row["question_id"] for row in selected if row["question_id"] not in answers
    ]
    if missing_answers:
        raise ValueError(f"selected questions missing answers: {missing_answers}")

    reader = _provider(args.reader_provider, args.reader_model)
    primary = _provider(args.primary_judge_provider, args.primary_judge_model)
    independent = _provider(
        args.independent_judge_provider, args.independent_judge_model
    )
    projection = _cost_projection(
        active_selected,
        answers,
        max_context_chars=args.max_context_chars,
        reader=reader,
        primary=primary,
        independent=independent,
        max_answer_tokens=args.max_answer_tokens,
    )
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "retrieval_sha256": _file_sha256(retrieval_path),
        "answers_sha256": _file_sha256(answers_path),
        "queries_sha256": _file_sha256(queries_path),
        "question_ids": [row["question_id"] for row in selected],
        "reader": {"provider": reader.name, "model": reader.model},
        "primary_judge": {"provider": primary.name, "model": primary.model},
        "independent_judge": {
            "provider": independent.name,
            "model": independent.model,
        },
        "reader_protocol": READER_PROTOCOL,
        "judge_protocol": JUDGE_PROTOCOL,
        "max_context_chars": args.max_context_chars,
        "max_answer_tokens": args.max_answer_tokens,
    }
    manifest_path = output.with_name(output.stem + ".manifest.json")
    manifest = _ensure_manifest(manifest_path, manifest_payload)
    estimate_path = output.with_name(output.stem + ".cost-estimate.json")
    _atomic_json(
        estimate_path,
        {
            **projection,
            "run_fingerprint": manifest["fingerprint"],
            "retrieval": str(retrieval_path),
            "output": str(output),
        },
    )
    if args.estimate_only:
        _update_progress(
            output,
            stage="estimated",
            total=len(active_selected),
            completed=0,
            detail=f"estimated cost ${projection['total_estimated_usd']:.2f}",
        )
        print(json.dumps({**projection, "estimate_path": str(estimate_path)}, indent=2))
        return 0
    if args.max_estimated_cost_usd <= 0:
        raise RuntimeError(
            "Paid execution requires a positive --max-estimated-cost-usd ceiling."
        )
    if projection["total_estimated_usd"] > args.max_estimated_cost_usd:
        raise RuntimeError(
            f"Estimated cost ${projection['total_estimated_usd']:.2f} exceeds "
            f"the authorized ceiling ${args.max_estimated_cost_usd:.2f}."
        )
    for provider in {reader, primary, independent}:
        if not os.environ.get(provider.api_key_env, "").strip():
            raise RuntimeError(f"{provider.api_key_env} is not set")

    stem = output.with_suffix("")
    hypotheses_path = stem.with_name(stem.name + ".hypotheses.jsonl")
    primary_path = stem.with_name(stem.name + ".primary-evaluated.jsonl")
    independent_path = stem.with_name(stem.name + ".independent-evaluated.jsonl")
    hypotheses = _generate(
        args,
        reader,
        active_selected,
        answers,
        hypotheses_path,
        manifest["fingerprint"],
        checkpoint_order=[str(row["question_id"]) for row in selected],
    )
    incomplete_reader_ids = [
        row["question_id"]
        for row in hypotheses
        if row["reader_finish_reason"] == "length"
    ]
    if incomplete_reader_ids:
        raise RuntimeError(
            "Reader output remained truncated after recovery; checkpoints are preserved "
            f"but no final report will be produced: {incomplete_reader_ids[:20]}"
        )
    primary_fingerprint = _fingerprint(
        [
            manifest["fingerprint"],
            JUDGE_PROTOCOL,
            primary.name,
            primary.model,
        ]
    )
    independent_fingerprint = _fingerprint(
        [
            manifest["fingerprint"],
            JUDGE_PROTOCOL,
            independent.name,
            independent.model,
        ]
    )
    primary_rows = _judge(
        args,
        primary,
        hypotheses,
        primary_path,
        primary_fingerprint,
        stage="primary_judge",
        checkpoint_order=[str(row["question_id"]) for row in selected],
    )
    independent_rows = _judge(
        args,
        independent,
        hypotheses,
        independent_path,
        independent_fingerprint,
        stage="independent_judge",
        checkpoint_order=[str(row["question_id"]) for row in selected],
    )

    primary_labels = [
        bool(row["autoeval_label"]["label"]) for row in primary_rows
    ]
    independent_labels = [
        bool(row["autoeval_label"]["label"]) for row in independent_rows
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset": "vectara/open_ragbench",
        "question_count": len(active_selected),
        "full_question_count": len(selected),
        "evaluation_scope": {
            "kind": "deterministic_prefix_pilot" if args.pilot_questions else "full",
            "pilot_questions": args.pilot_questions or None,
            "reusable_for_full_run": True,
        },
        "run_fingerprint": manifest["fingerprint"],
        "retrieval_sha256": manifest_payload["retrieval_sha256"],
        "reader": {"provider": reader.name, "model": reader.model},
        "primary_judge": {
            "provider": primary.name,
            "model": primary.model,
            **_accuracy_summary(primary_rows),
        },
        "independent_judge": {
            "provider": independent.name,
            "model": independent.model,
            **_accuracy_summary(independent_rows),
        },
        "judge_agreement": round(
            statistics.fmean(
                left == right
                for left, right in zip(
                    primary_labels, independent_labels, strict=True
                )
            ),
            6,
        ),
        "judge_cohen_kappa": _cohen_kappa(
            primary_labels, independent_labels
        ),
        "mean_token_f1": round(
            statistics.fmean(row["token_f1"] for row in hypotheses), 6
        ),
        "retrieval_ceiling": {
            "section_hit_at_10": round(
                statistics.fmean(row["section_hit_at_10"] for row in hypotheses),
                6,
            ),
            "document_hit_at_10": round(
                statistics.fmean(row["document_hit_at_10"] for row in hypotheses),
                6,
            ),
        },
        "reader_finish_reason_counts": dict(
            sorted(Counter(row["reader_finish_reason"] for row in hypotheses).items())
        ),
        "cost_projection": projection,
        "usage_and_estimated_cost": {
            "reader": _provider_cost(
                reader, _usage_attempts(hypotheses, kind="reader")
            ),
            "primary_judge": _provider_cost(
                primary, _usage_attempts(primary_rows, kind="judge")
            ),
            "independent_judge": _provider_cost(
                independent, _usage_attempts(independent_rows, kind="judge")
            ),
        },
        "artifacts": {
            "manifest": str(manifest_path),
            "cost_estimate": str(estimate_path),
            "hypotheses": str(hypotheses_path),
            "primary_judgments": str(primary_path),
            "independent_judgments": str(independent_path),
        },
    }
    report["usage_and_estimated_cost"]["total_estimated_usd"] = round(
        sum(
            float(value["estimated_usd"])
            for value in report["usage_and_estimated_cost"].values()
            if isinstance(value, dict) and "estimated_usd" in value
        ),
        6,
    )
    _atomic_json(output, report)
    _update_progress(
        output,
        stage="complete",
        total=len(active_selected),
        completed=len(active_selected),
        detail=f"report written to {output}",
    )
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    return _run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
