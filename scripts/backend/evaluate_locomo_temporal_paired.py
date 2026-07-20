from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_locomo_api import (
    PRODUCTION_TEMPORAL_PROTOCOL,
    ProductionTemporalContext,
    _answer_prompt,
    _context,
    _conversation_turns,
    _judge_prompt,
    _official_locomo_score,
    _stemmer,
)
from scripts.backend.evaluate_vault_longmemeval_api import (
    _chat,
    _ensure_manifest,
    _file_sha256,
    _finish_reason,
    _fingerprint,
    _parse_binary_verdict,
    _provider,
    _provider_cost,
    _usage,
)
from scripts.backend.evaluate_vault_longmemeval_local import _load_jsonl, _write_jsonl


PROTOCOL = "locomo-temporal-activation-paired-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate only the frozen LoCoMo temporal activation set while reusing unchanged fallback outputs."
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--activation-source", type=Path, required=True)
    parser.add_argument("--baseline-hypotheses", type=Path, required=True)
    parser.add_argument("--baseline-primary-judgments", type=Path, required=True)
    parser.add_argument("--baseline-independent-judgments", type=Path, required=True)
    parser.add_argument("--temporal-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    parser.add_argument("--max-answer-tokens", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def _by_id(path: Path) -> dict[str, dict]:
    return {str(row["question_id"]): row for row in _load_jsonl(path)}


def _answer(response: dict) -> str:
    return str(response["choices"][0]["message"]["content"]).strip()


def _judge(provider, item: dict, hypothesis: str, args: argparse.Namespace) -> tuple[bool, dict]:
    attempts: list[dict] = []
    for _ in range(2):
        response = _chat(
            provider,
            _judge_prompt(item, hypothesis),
            max_tokens=10,
            timeout=args.timeout,
            retries=args.retries,
        )
        raw = _answer(response)
        attempts.append({"raw": raw, "usage": _usage(response), "finish_reason": _finish_reason(response)})
        try:
            return _parse_binary_verdict(raw), {"attempts": attempts, "usage": _usage(response)}
        except RuntimeError:
            continue
    raise RuntimeError(f"Judge returned no binary verdict for {item['question_id']}: {attempts}")


def _reader(provider, item: dict, context: str, args: argparse.Namespace) -> tuple[str, list[dict]]:
    token_budget = args.max_answer_tokens
    attempts: list[dict] = []
    while True:
        response = _chat(
            provider,
            _answer_prompt(item, context),
            max_tokens=token_budget,
            timeout=args.timeout,
            retries=args.retries,
        )
        finish_reason = _finish_reason(response)
        attempts.append(
            {
                "max_answer_tokens": token_budget,
                "finish_reason": finish_reason,
                "usage": _usage(response),
            }
        )
        if finish_reason != "length":
            return _answer(response), attempts
        if token_budget >= 768:
            raise RuntimeError(
                f"Reader remained length-limited at 768 tokens for {item['question_id']}"
            )
        token_budget = min(768, max(256, token_budget * 2))


def _checkpoint(path: Path, rows: dict[str, dict], ordered_ids: list[str]) -> None:
    _write_jsonl(path, [rows[item] for item in ordered_ids if item in rows])


def _paired_counts(rows: list[dict], key: str) -> dict:
    wins = sum(row[f"candidate_{key}"] and not row[f"baseline_{key}"] for row in rows)
    losses = sum(row[f"baseline_{key}"] and not row[f"candidate_{key}"] for row in rows)
    return {
        "baseline_correct": sum(row[f"baseline_{key}"] for row in rows),
        "candidate_correct": sum(row[f"candidate_{key}"] for row in rows),
        "wins": wins,
        "losses": losses,
        "net": wins - losses,
    }


def main() -> None:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    retrieval_by_id = {str(row["question_id"]): row for row in retrieval["results"]}
    activation_rows = _load_jsonl(args.activation_source)
    activation_ids = [
        str(row["question_id"])
        for row in activation_rows
        if bool((row.get("temporal_memory") or {}).get("contract_injected"))
    ]
    if not activation_ids:
        raise RuntimeError("The activation source contains no injected temporal contracts")

    baseline_hypotheses = _by_id(args.baseline_hypotheses)
    baseline_primary = _by_id(args.baseline_primary_judgments)
    baseline_independent = _by_id(args.baseline_independent_judgments)
    reader = _provider("kimi", args.reader_model)
    primary = _provider("kimi", args.primary_judge_model)
    independent = _provider("openai", args.independent_judge_model)
    stem = args.output.with_suffix("")
    manifest = _ensure_manifest(
        stem.with_name(stem.name + ".manifest.json"),
        {
            "protocol": PROTOCOL,
            "dataset_sha256": _file_sha256(args.dataset),
            "retrieval_sha256": _file_sha256(args.retrieval),
            "activation_source_sha256": _file_sha256(args.activation_source),
            "baseline_hypotheses_sha256": _file_sha256(args.baseline_hypotheses),
            "baseline_primary_sha256": _file_sha256(args.baseline_primary_judgments),
            "baseline_independent_sha256": _file_sha256(args.baseline_independent_judgments),
            "activation_ids": activation_ids,
            "production_temporal_protocol": PRODUCTION_TEMPORAL_PROTOCOL,
            "models": {
                "reader": reader.model,
                "primary_judge": primary.model,
                "independent_judge": independent.model,
            },
        },
    )
    checkpoint_path = stem.with_name(stem.name + ".paired.jsonl")
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(checkpoint_path)
        if row.get("run_fingerprint") == manifest["fingerprint"]
    }
    turns = _conversation_turns(dataset)
    temporal = ProductionTemporalContext(
        dataset=dataset,
        dataset_sha256=manifest["dataset_sha256"],
        database_path=args.temporal_db,
    )
    try:
        for position, question_id in enumerate(activation_ids, start=1):
            if question_id in existing:
                continue
            item = retrieval_by_id[question_id]
            baseline = baseline_hypotheses[question_id]
            base_context, _included = _context(item, turns)
            candidate_context, diagnostics = temporal.context(
                sample_id=str(item["sample_id"]),
                question=str(item["question"]),
                retrieved_context=base_context,
            )
            changed = bool(
                diagnostics.get("deterministic_answer")
                or diagnostics.get("contract_injected")
            )
            if not changed:
                candidate_hypothesis = str(baseline["hypothesis"])
                reader_attempts: list[dict] = []
                candidate_primary = bool(
                    baseline_primary[question_id]["autoeval_label"]["label"]
                )
                candidate_independent = bool(
                    baseline_independent[question_id]["autoeval_label"]["label"]
                )
                primary_usage: list[dict] = []
                independent_usage: list[dict] = []
            else:
                deterministic = str(diagnostics.get("deterministic_answer") or "").strip()
                if deterministic:
                    candidate_hypothesis = deterministic
                    reader_attempts = []
                else:
                    candidate_hypothesis, reader_attempts = _reader(
                        reader, item, candidate_context, args
                    )
                candidate_primary, primary_details = _judge(
                    primary, item, candidate_hypothesis, args
                )
                candidate_independent, independent_details = _judge(
                    independent, item, candidate_hypothesis, args
                )
                primary_usage = [attempt["usage"] for attempt in primary_details["attempts"]]
                independent_usage = [attempt["usage"] for attempt in independent_details["attempts"]]

            row = {
                "question_id": question_id,
                "sample_id": item["sample_id"],
                "category": item["category"],
                "question": item["question"],
                "answer": item["answer"],
                "changed_by_current_router": changed,
                "baseline_hypothesis": baseline["hypothesis"],
                "candidate_hypothesis": candidate_hypothesis,
                "baseline_primary": bool(baseline_primary[question_id]["autoeval_label"]["label"]),
                "candidate_primary": candidate_primary,
                "baseline_independent": bool(baseline_independent[question_id]["autoeval_label"]["label"]),
                "candidate_independent": candidate_independent,
                "temporal_memory": diagnostics,
                "reader_attempts": reader_attempts,
                "primary_usage": primary_usage,
                "independent_usage": independent_usage,
                "run_fingerprint": manifest["fingerprint"],
            }
            existing[question_id] = row
            _checkpoint(checkpoint_path, existing, activation_ids)
            print(
                f"paired {position}/{len(activation_ids)} {question_id}: "
                f"{'changed' if changed else 'reused'}",
                flush=True,
            )
    finally:
        temporal.close()

    rows = [existing[item] for item in activation_ids]
    stemmer = _stemmer()
    baseline_f1 = [
        _official_locomo_score(retrieval_by_id[row["question_id"]], row["baseline_hypothesis"], stemmer)
        for row in rows
    ]
    candidate_f1 = [
        _official_locomo_score(retrieval_by_id[row["question_id"]], row["candidate_hypothesis"], stemmer)
        for row in rows
    ]
    reader_usages = [
        attempt["usage"] for row in rows for attempt in row["reader_attempts"]
    ]
    primary_usages = [usage for row in rows for usage in row["primary_usage"]]
    independent_usages = [usage for row in rows for usage in row["independent_usage"]]
    report = {
        "protocol": PROTOCOL,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "activation_question_count": len(rows),
        "changed_question_count": sum(row["changed_by_current_router"] for row in rows),
        "reused_fallback_count": sum(not row["changed_by_current_router"] for row in rows),
        "official_f1": {
            "baseline": round(statistics.fmean(baseline_f1), 4),
            "candidate": round(statistics.fmean(candidate_f1), 4),
            "delta": round(statistics.fmean(candidate_f1) - statistics.fmean(baseline_f1), 4),
        },
        "primary_judge": _paired_counts(rows, "primary"),
        "independent_judge": _paired_counts(rows, "independent"),
        "reader_api_call_count": sum(len(row["reader_attempts"]) for row in rows),
        "primary_judge_api_call_count": len(primary_usages),
        "independent_judge_api_call_count": len(independent_usages),
        "cost": {
            "reader": _provider_cost(reader, reader_usages),
            "primary_judge": _provider_cost(primary, primary_usages),
            "independent_judge": _provider_cost(independent, independent_usages),
        },
        "checkpoint": str(checkpoint_path),
    }
    report["cost"]["total_estimated_usd"] = round(
        sum(
            item["estimated_usd_with_reported_cache"]
            for key, item in report["cost"].items()
            if key != "total_estimated_usd"
        ),
        6,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
