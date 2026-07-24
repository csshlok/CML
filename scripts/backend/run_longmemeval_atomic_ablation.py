from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory import (  # noqa: E402
    ATOMIC_MEMORY_VERSION,
    AtomicFact,
    compile_semantic_atomic_session,
    estimate_atomic_tokens,
    evaluate_deterministic_operation,
    export_semantic_normalization_jobs,
    extract_atomic_memory,
    import_semantic_normalization_results,
    load_atomic_session_cache,
    pack_atomic_facts,
    plan_atomic_query,
    render_deterministic_operation,
    retrieve_atomic_session_ids,
    route_atomic_question,
    source_content_hash,
    store_atomic_session_cache,
    validate_atomic_contract,
)
from backend.app.core.claim_evidence_packing import (  # noqa: E402
    SessionEnvelope,
    pack_claim_evidence,
)
from scripts.backend.evaluate_vault_longmemeval_api import (  # noqa: E402
    ProviderContentFilterError,
    _chat,
    _provider,
    _provider_cost,
    _usage,
)
from scripts.backend.evaluate_vault_longmemeval_local import (  # noqa: E402
    _answer_prompt,
    _judge_prompt,
)


QUESTION_TYPES = (
    "knowledge-update",
    "multi-session",
    "single-session-assistant",
    "single-session-preference",
    "single-session-user",
    "temporal-reasoning",
)
_WRITE_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen LongMemEval write-time atomic-memory ablation."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark"),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/atomic-memory-v1"),
    )
    parser.add_argument(
        "--phase",
        choices=(
            "freeze", "label", "extract", "semantic-export", "semantic-import",
            "coverage", "evaluate", "all",
        ),
        default="all",
    )
    parser.add_argument("--questions-per-type", type=int, default=10)
    parser.add_argument(
        "--selection-mode",
        choices=("pilot-balanced", "representative"),
        default="representative",
        help=(
            "Representative is the only headline/evaluation mode. pilot-balanced "
            "intentionally oversamples baseline failures and is diagnostic-only."
        ),
    )
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--selection-seed", type=int, default=20260720)
    parser.add_argument(
        "--exclude-manifest",
        type=Path,
        action="append",
        default=[],
        help="Repeatable frozen manifest whose question IDs must not enter this run.",
    )
    parser.add_argument(
        "--semantic-jobs-path", type=Path,
        help="JSONL job/result path for asynchronous semantic normalization.",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--extractor-provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--extractor-model", default="kimi-k2.6")
    parser.add_argument(
        "--semantic-extraction",
        action="store_true",
        help="Augment the lossless compiler with model-normalized facts.",
    )
    parser.add_argument("--reader-provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--primary-judge-provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument("--independent-judge-provider", choices=("kimi", "openai"), default="openai")
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--extraction-max-tokens", type=int, default=8_192)
    parser.add_argument(
        "--extraction-max-source-chars",
        type=int,
        default=16_000,
        help="Maximum source characters sent in one bounded semantic request.",
    )
    parser.add_argument(
        "--extraction-max-facts-per-chunk",
        type=int,
        default=48,
        help="Maximum durable facts requested from each bounded source chunk.",
    )
    parser.add_argument(
        "--extraction-roles",
        choices=("all", "user"),
        default="all",
        help="Question-independent source roles eligible for semantic extraction.",
    )
    parser.add_argument("--sessions-per-extraction-batch", type=int, default=2)
    parser.add_argument(
        "--max-extraction-sessions",
        type=int,
        default=0,
        help="Debug-only cap; zero extracts every session in the configured scope.",
    )
    parser.add_argument(
        "--atomic-extraction-scope",
        choices=("full-haystack", "retrieved-only"),
        default="full-haystack",
        help=(
            "Question-independent extraction defaults to the full haystack. "
            "retrieved-only is retained solely for circularity diagnostics."
        ),
    )
    parser.add_argument(
        "--diagnostic-reference-matcher",
        action="store_true",
        help=(
            "Enable the legacy LongMemEval-specific deterministic answer matcher for "
            "diagnostics only. It never controls the default promotion decision."
        ),
    )
    parser.add_argument("--answer-max-tokens", type=int, default=512)
    parser.add_argument("--fact-token-budget", type=int, default=9_000)
    parser.add_argument("--claim-first-token-budget", type=int, default=10_000)
    parser.add_argument("--hybrid-fact-token-budget", type=int, default=3_500)
    parser.add_argument("--hybrid-raw-token-budget", type=int, default=6_000)
    parser.add_argument(
        "--evaluation-arms",
        default="facts-only,hybrid",
        help="Comma-separated subset of facts-only, hybrid, adaptive.",
    )
    parser.add_argument("--minimum-evidence-recall", type=float, default=0.98)
    parser.add_argument("--minimum-packed-evidence-recall", type=float, default=0.95)
    parser.add_argument("--minimum-atomic-question-completeness", type=float, default=0.95)
    parser.add_argument("--minimum-temporal-anchor-recall", type=float, default=0.98)
    parser.add_argument("--minimum-direct-fact-recall", type=float, default=1.0)
    parser.add_argument("--minimum-source-unit-coverage", type=float, default=1.0)
    parser.add_argument("--minimum-atomic-activation-rate", type=float, default=0.10)
    parser.add_argument("--maximum-atomic-false-safe-count", type=int, default=0)
    parser.add_argument(
        "--force-coverage-recompute",
        action="store_true",
        help="Ignore a matching content-addressed coverage-stage artifact.",
    )
    parser.add_argument(
        "--impact-question-id",
        action="append",
        default=[],
        help="Recompute only this question and merge with --base-coverage; repeatable.",
    )
    parser.add_argument(
        "--base-coverage",
        type=Path,
        help="Existing complete coverage report used by an impact-only replay.",
    )
    parser.add_argument("--minimum-labeled-question-rate", type=float, default=0.95)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _load_evidence_labels(run_dir: Path) -> list[dict]:
    merged = {
        row["question_id"]: row
        for row in _load_jsonl(run_dir / "answer-blind-oracle-evidence-labels-v2.jsonl")
    }
    manual_path = run_dir / "manual-answer-blind-oracle-evidence-labels-v2.json"
    if manual_path.exists():
        for row in json.loads(manual_path.read_text(encoding="utf-8")):
            merged[row["question_id"]] = row
    return list(merged.values())


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_inputs(root: Path) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    dataset = json.loads((root / "longmemeval_s_cleaned.json").read_text(encoding="utf-8"))
    retrieval_report = json.loads(
        (root / "longmemeval-full500-retrieval.json").read_text(encoding="utf-8")
    )
    retrieval = {row["question_id"]: row for row in retrieval_report["results"]}
    references = {row["question_id"]: row for row in dataset}
    return dataset, references, retrieval


def freeze_manifest(args: argparse.Namespace) -> dict:
    args.run_dir.mkdir(parents=True, exist_ok=True)
    path = args.run_dir / "manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("selection_mode", "representative") != args.selection_mode:
            raise RuntimeError("Frozen manifest uses a different selection mode")
        if args.selection_mode == "pilot-balanced" and (
            manifest["questions_per_type"] != args.questions_per_type
        ):
            raise RuntimeError("Frozen manifest uses a different questions-per-type value")
        if args.selection_mode == "representative" and (
            manifest["question_count"] != args.sample_size
        ):
            raise RuntimeError("Frozen manifest uses a different representative sample size")
        return manifest

    dataset, _, retrieval = _load_inputs(args.artifact_dir)
    primary = {
        row["question_id"]: bool(row["autoeval_label"]["label"])
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.kimi-evaluated.jsonl"
        )
    }
    independent = {
        row["question_id"]: bool(row["autoeval_label"]["label"])
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.openai-evaluated.jsonl"
        )
    }
    excluded_ids: set[str] = set()
    for excluded_path in args.exclude_manifest:
        excluded_manifest = json.loads(excluded_path.read_text(encoding="utf-8"))
        excluded_ids.update(
            item["question_id"] for item in excluded_manifest.get("questions") or []
        )
    all_eligible = [
        row
        for row in dataset
        if row["question_id"] not in excluded_ids
        and not retrieval[row["question_id"]]["abstention"]
        and retrieval[row["question_id"]]["any_evidence_at_k"]
    ]
    selected: list[dict] = []
    if args.selection_mode == "representative":
        if args.sample_size > len(all_eligible):
            raise RuntimeError("Representative sample is larger than the eligible pool")
        positions = {row["question_id"]: index for index, row in enumerate(dataset)}
        chosen = random.Random(args.selection_seed).sample(all_eligible, args.sample_size)
        chosen.sort(key=lambda row: positions[row["question_id"]])
        for row in chosen:
            selected.append(
                {
                    "question_id": row["question_id"],
                    "question_type": row["question_type"],
                    "split": "evaluation",
                    "baseline_dual_correct": bool(
                        primary[row["question_id"]] and independent[row["question_id"]]
                    ),
                    "retrieved_session_ids": retrieval[row["question_id"]][
                        "retrieved_session_ids"
                    ],
                    "answer_session_ids": row["answer_session_ids"],
                }
            )
    else:
        for question_type in QUESTION_TYPES:
            eligible = [
            row
            for row in all_eligible
            if row["question_type"] == question_type
            ]
            failures = [
                row
                for row in eligible
                if not (primary[row["question_id"]] and independent[row["question_id"]])
            ]
            controls = [
                row
                for row in eligible
                if primary[row["question_id"]] and independent[row["question_id"]]
            ]
            failure_count = min(args.questions_per_type // 2, len(failures))
            control_count = args.questions_per_type - failure_count
            chosen = failures[:failure_count] + controls[:control_count]
            if len(chosen) != args.questions_per_type:
                raise RuntimeError(f"Not enough eligible questions for {question_type}")
            for index, row in enumerate(chosen):
                split = "development" if index % 2 == 0 else "evaluation"
                selected.append(
                    {
                        "question_id": row["question_id"],
                        "question_type": question_type,
                        "split": split,
                        "baseline_dual_correct": bool(
                            primary[row["question_id"]]
                            and independent[row["question_id"]]
                        ),
                        "retrieved_session_ids": retrieval[row["question_id"]][
                            "retrieved_session_ids"
                        ],
                        "answer_session_ids": row["answer_session_ids"],
                    }
                )
    manifest = {
        "protocol": "longmemeval-atomic-memory-frozen-ablation-v2",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selection_mode": args.selection_mode,
        "questions_per_type": args.questions_per_type,
        "selection_seed": args.selection_seed if args.selection_mode == "representative" else None,
        "excluded_question_count": len(excluded_ids),
        "selection": (
            "seeded representative sample from retrieval-hit answerable questions, "
            "restored to official dataset order"
            if args.selection_mode == "representative"
            else "official order; per type up to 50% dual-judge claim-first failures, "
            "then dual-judge controls; retrieval-hit answerable questions only"
        ),
        "selection_is_headline_eligible": args.selection_mode == "representative",
        "selection_warning": (
            None
            if args.selection_mode == "representative"
            else (
                "Diagnostic-only sample intentionally enriched for baseline failures; "
                "must not be reported as representative accuracy."
            )
        ),
        "question_count": len(selected),
        "questions": selected,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _session_rows(reference: dict, session_ids: list[str]) -> list[dict]:
    by_id = {
        str(session_id): {
            "session_id": str(session_id),
            "date": str(date),
            "turns": turns,
        }
        for session_id, date, turns in zip(
            reference["haystack_session_ids"],
            reference["haystack_dates"],
            reference["haystack_sessions"],
            strict=True,
        )
    }
    return [by_id[session_id] for session_id in session_ids if session_id in by_id]


def _extraction_session_ids(
    args: argparse.Namespace,
    reference: dict,
    retrieved_session_ids: list[str],
) -> list[str]:
    if getattr(args, "atomic_extraction_scope", "full-haystack") == "retrieved-only":
        return retrieved_session_ids
    return [str(session_id) for session_id in reference["haystack_session_ids"]]


def _evidence_label_prompt(reference: dict) -> str:
    gold_sessions = _session_rows(reference, reference["answer_session_ids"])
    return f"""Identify the minimal source evidence needed to answer this memory question.

This is answer-blind oracle annotation, not memory extraction. You are given the
question and the benchmark-designated source sessions, but never the reference answer.
Return JSON only:
{{"evidence":[{{"session_id":"...","turn_index":0,"speaker":"user|assistant",
"excerpt":"exact contiguous source quotation","role":"what this span proves"}}]}}

Rules:
- Every excerpt must be an exact contiguous substring of the cited turn.
- Include every distinct span required for counts, comparisons, updates, or synthesis.
- Prefer the smallest self-contained quotation that still proves the fact.
- Do not cite text merely because it is in a gold session.

Question: {reference['question']}
Benchmark-designated source sessions:
{json.dumps(gold_sessions, ensure_ascii=False)}
"""


def _parse_json(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])


def _repair_excerpt(content: str, proposed: str) -> str | None:
    if proposed in content:
        return proposed
    folded_position = content.casefold().find(proposed.casefold())
    if folded_position >= 0:
        return content[folded_position : folded_position + len(proposed)]
    candidates = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+|\n+", content)
        if item.strip()
    ]
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda item: difflib.SequenceMatcher(
            None, " ".join(proposed.casefold().split()), " ".join(item.casefold().split())
        ).ratio(),
    )
    ratio = difflib.SequenceMatcher(
        None, " ".join(proposed.casefold().split()), " ".join(best.casefold().split())
    ).ratio()
    return best if ratio >= 0.72 else None


def label_evidence(
    args: argparse.Namespace, manifest: dict, references: dict[str, dict]
) -> list[dict]:
    # Use a new cache path so answer-aware v1 annotations cannot be silently reused.
    path = args.run_dir / "answer-blind-oracle-evidence-labels-v2.jsonl"
    existing = {row["question_id"]: row for row in _load_jsonl(path)}
    provider = _provider(args.extractor_provider, args.extractor_model)
    fallback_provider = (
        _provider("openai", "gpt-5.4")
        if provider.name != "openai"
        else _provider("kimi", "kimi-k2.6")
    )

    def label(item: dict) -> dict:
        question_id = item["question_id"]
        reference = references[question_id]
        sessions = {
            session["session_id"]: session
            for session in _session_rows(reference, reference["answer_session_ids"])
        }
        valid: list[dict] = []
        invalid = 0
        usage: Counter[str] = Counter()
        attempt_providers = (provider, provider, fallback_provider)
        for attempt, attempt_provider in enumerate(attempt_providers):
            retry_note = (
                "\nYour previous annotation yielded no valid exact quotation. "
                "Copy excerpts directly without changing punctuation."
                if attempt
                else ""
            )
            try:
                response = _chat(
                    attempt_provider,
                    _evidence_label_prompt(reference) + retry_note,
                    max_tokens=4_096,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                usage.update(_usage(response))
                payload = _parse_json(response["choices"][0]["message"]["content"])
            except (
                ProviderContentFilterError,
                json.JSONDecodeError,
                KeyError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                invalid += 1
                continue
            for raw in payload.get("evidence") or []:
                try:
                    session = sessions[str(raw["session_id"])]
                    turn_index = int(raw["turn_index"])
                    turn = session["turns"][turn_index]
                    proposed = str(raw["excerpt"])
                except (KeyError, TypeError, ValueError, IndexError):
                    invalid += 1
                    continue
                excerpt = _repair_excerpt(str(turn.get("content") or ""), proposed)
                if excerpt is None:
                    invalid += 1
                    continue
                candidate = {
                    "session_id": session["session_id"],
                    "turn_index": turn_index,
                    "speaker": str(turn.get("role") or ""),
                    "excerpt": excerpt,
                    "role": str(raw.get("role") or ""),
                }
                if candidate not in valid:
                    valid.append(candidate)
            if valid:
                break
        row = {
            "annotation_protocol": "answer-blind-gold-session-oracle-v2",
            "question_id": question_id,
            "question_type": item["question_type"],
            "split": item["split"],
            "evidence": valid,
            "invalid_label_count": invalid,
            "usage": dict(usage),
        }
        _append_jsonl(path, row)
        return row

    pending = [
        item
        for item in manifest["questions"]
        if item["question_id"] not in existing
        or not existing[item["question_id"]].get("evidence")
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(label, item) for item in pending]
        for position, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            existing[row["question_id"]] = row
            print(f"labeled {position}/{len(pending)}: {row['question_id']}", flush=True)
    merged = {row["question_id"]: row for row in _load_evidence_labels(args.run_dir)}
    return [merged[item["question_id"]] for item in manifest["questions"]]


def extract_sessions(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
) -> None:
    provider = (
        _provider(args.extractor_provider, args.extractor_model)
        if args.semantic_extraction
        else None
    )
    cache_dir = args.run_dir / "fact-cache"
    unique: dict[str, dict] = {}
    for item in manifest["questions"]:
        reference = references[item["question_id"]]
        for session in _session_rows(
            reference,
            _extraction_session_ids(args, reference, item["retrieved_session_ids"]),
        ):
            digest = source_content_hash(session["session_id"], session["date"], session["turns"])
            unique[digest] = session

    cache_model = _semantic_cache_model(args)
    ledger_path = args.run_dir / "semantic-extraction-ledger.jsonl"
    failure_path = args.run_dir / "semantic-extraction-failures.jsonl"
    existing_ledger = {
        (str(row.get("source_content_hash") or ""), str(row.get("cache_model") or "")): row
        for row in _load_jsonl(ledger_path)
    }

    def extract(session: dict) -> tuple[str, int, int, dict]:
        cached = load_atomic_session_cache(
            cache_dir=cache_dir,
            model=cache_model,
            session=session,
        )
        if cached is not None:
            return session["session_id"], len(cached.facts), 1, {}
        request_count = 0

        def model(prompt: str) -> tuple[str, dict]:
            nonlocal request_count
            if provider is None:
                raise RuntimeError("Semantic extraction provider is disabled")
            request_count += 1
            response = _chat(
                provider,
                prompt,
                max_tokens=args.extraction_max_tokens,
                timeout=args.timeout,
                retries=args.retries,
            )
            return response["choices"][0]["message"]["content"], _usage(response)

        started = time.perf_counter()
        extraction, invalid_reasons, usage = compile_semantic_atomic_session(
            session,
            extractor=model,
            max_source_chars=args.extraction_max_source_chars,
            included_roles=(
                {"user"} if args.extraction_roles == "user" else None
            ),
            max_facts_per_chunk=args.extraction_max_facts_per_chunk,
        )
        store_atomic_session_cache(
            extraction,
            cache_dir=cache_dir,
            model=cache_model,
            session=session,
        )
        row = {
            "session_id": session["session_id"],
            "source_content_hash": source_content_hash(
                session["session_id"], session["date"], session["turns"]
            ),
            "provider": provider.name if provider is not None else "deterministic",
            "model": provider.model if provider is not None else cache_model,
            "cache_model": cache_model,
            "source_role_scope": args.extraction_roles,
            "max_source_chars": args.extraction_max_source_chars,
            "max_facts_per_chunk": args.extraction_max_facts_per_chunk,
            "request_count": request_count,
            "fact_count": len(extraction.facts),
            "invalid_fact_count": sum(invalid_reasons.values()),
            "invalid_reasons": invalid_reasons,
            "usage": usage,
            "wall_seconds": round(time.perf_counter() - started, 4),
        }
        _append_jsonl(ledger_path, row)
        return session["session_id"], len(extraction.facts), 0, row

    sessions = list(unique.values())
    if args.max_extraction_sessions > 0:
        sessions = sessions[: args.max_extraction_sessions]
    if provider is None:
        facts, diagnostics = extract_atomic_memory(
            sessions,
            model="deterministic-lossless-v1",
            cache_dir=cache_dir,
            extractor=None,
        )
        if diagnostics.extraction_failed:
            raise RuntimeError(diagnostics.failure_reason)
        print(
            json.dumps(
                {
                    "protocol": "deterministic-atomic-extraction-v1",
                    "requested_session_count": len(sessions),
                    "fact_count": len(facts),
                    "cache_hit_count": diagnostics.cache_hit_count,
                },
                indent=2,
            )
        )
        return
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract, session): session for session in sessions}
        for position, future in enumerate(as_completed(futures), start=1):
            session = futures[future]
            try:
                session_id, fact_count, cache_hit, row = future.result()
            except (OSError, RuntimeError, ValueError) as exc:
                failure = {
                    "session_id": session["session_id"],
                    "source_content_hash": source_content_hash(
                        session["session_id"], session["date"], session["turns"]
                    ),
                    "cache_model": cache_model,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
                _append_jsonl(failure_path, failure)
                print(
                    f"failed session {position}/{len(sessions)}: "
                    f"{session['session_id']} {type(exc).__name__}",
                    flush=True,
                )
                continue
            if row:
                key = (row["source_content_hash"], row["cache_model"])
                existing_ledger[key] = row
            print(
                f"extracted session {position}/{len(sessions)}: {session_id} "
                f"facts={fact_count} cache_hit={cache_hit}",
                flush=True,
            )
    rows = [
        row
        for (source_hash, model), row in existing_ledger.items()
        if model == cache_model and source_hash in unique
    ]
    usages = [row.get("usage") or {} for row in rows]
    failed_hashes = {
        str(row.get("source_content_hash") or "")
        for row in _load_jsonl(failure_path)
        if row.get("cache_model") == cache_model
    }
    summary = {
        "protocol": "bounded-semantic-extraction-v1",
        "provider": provider.name if provider is not None else "deterministic",
        "model": provider.model if provider is not None else cache_model,
        "cache_model": cache_model,
        "source_role_scope": args.extraction_roles,
        "extraction_scope": getattr(args, "atomic_extraction_scope", "full-haystack"),
        "requested_session_count": len(sessions),
        "completed_session_count": len(rows),
        "failed_session_count": len(
            failed_hashes
            - {str(row.get("source_content_hash") or "") for row in rows}
        ),
        "request_count": sum(int(row.get("request_count") or 0) for row in rows),
        "fact_count": sum(int(row.get("fact_count") or 0) for row in rows),
        "invalid_fact_count": sum(
            int(row.get("invalid_fact_count") or 0) for row in rows
        ),
        "wall_seconds_sum": round(
            sum(float(row.get("wall_seconds") or 0.0) for row in rows), 4
        ),
        "cost": _provider_cost(provider, usages) if provider is not None else {},
    }
    (args.run_dir / "semantic-extraction-report.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


def _semantic_cache_model(args: argparse.Namespace) -> str:
    if not args.semantic_extraction:
        return "deterministic-lossless-v1"
    return (
        f"{args.extractor_provider}:{args.extractor_model}:bounded-v3:"
        f"chars={args.extraction_max_source_chars}:"
        f"facts={args.extraction_max_facts_per_chunk}:roles={args.extraction_roles}"
    )


def _unique_extraction_sessions(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in manifest["questions"]:
        reference = references[item["question_id"]]
        for session in _session_rows(
            reference,
            _extraction_session_ids(args, reference, item["retrieved_session_ids"]),
        ):
            digest = source_content_hash(
                session["session_id"], session["date"], session["turns"]
            )
            unique[digest] = session
    return list(unique.values())


def semantic_queue_phase(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
) -> dict:
    if args.semantic_jobs_path is None:
        raise ValueError("--semantic-jobs-path is required for semantic queue phases")
    sessions = _unique_extraction_sessions(args, manifest, references)
    cache_dir = args.run_dir / "fact-cache"
    if args.phase == "semantic-export":
        return export_semantic_normalization_jobs(
            sessions,
            model=args.extractor_model,
            cache_dir=cache_dir,
            output_path=args.semantic_jobs_path,
        )
    return import_semantic_normalization_results(
        args.semantic_jobs_path,
        model=args.extractor_model,
        cache_dir=cache_dir,
    )


def _cached_facts(
    args: argparse.Namespace, reference: dict, retrieved_session_ids: list[str]
) -> tuple[list[AtomicFact], dict]:
    sessions = _session_rows(
        reference,
        _extraction_session_ids(args, reference, retrieved_session_ids),
    )

    def require_complete_semantic_cache(_prompt: str) -> tuple[str, dict]:
        raise RuntimeError("Semantic atomic extraction cache is incomplete")

    facts, diagnostics = extract_atomic_memory(
        sessions,
        model=_semantic_cache_model(args),
        cache_dir=args.run_dir / "fact-cache",
        extractor=require_complete_semantic_cache if args.semantic_extraction else None,
    )
    if diagnostics.extraction_failed:
        raise RuntimeError(diagnostics.failure_reason)
    return facts, diagnostics.model_dump(mode="json")


def _atomic_retrieval_session_ids(
    args: argparse.Namespace,
    question: str,
    facts: list[AtomicFact],
    retrieved_session_ids: list[str],
) -> tuple[list[str], list[str]]:
    if getattr(args, "atomic_extraction_scope", "full-haystack") == "retrieved-only":
        return list(retrieved_session_ids), []
    atomic_ids = retrieve_atomic_session_ids(
        question,
        facts,
        limit=max(1, len(retrieved_session_ids)),
    )
    combined = list(dict.fromkeys([*retrieved_session_ids, *atomic_ids]))
    raw_ids = set(retrieved_session_ids)
    newly_recovered = [
        session_id
        for session_id in atomic_ids
        if session_id not in raw_ids
    ]
    return combined, newly_recovered


def _spans_overlap(source: str, left: str, right: str) -> bool:
    left_start = source.find(left)
    right_start = source.find(right)
    if left_start < 0 or right_start < 0:
        return False
    overlap = max(
        0,
        min(left_start + len(left), right_start + len(right))
        - max(left_start, right_start),
    )
    return overlap / max(1, min(len(left), len(right))) >= 0.5


def _claim_first_context(
    reference: dict, retrieved_session_ids: list[str], token_budget: int
) -> tuple[str, dict]:
    sessions = [
        SessionEnvelope(
            session_id=session["session_id"],
            date=session["date"],
            turns=session["turns"],
            retrieval_rank=rank,
        )
        for rank, session in enumerate(_session_rows(reference, retrieved_session_ids))
    ]
    return pack_claim_evidence(
        question=reference["question"],
        sessions=sessions,
        token_budget=token_budget,
        question_type="",
        consolidate=False,
    )


def _excerpt_in_context(excerpt: str, context: str) -> bool:
    normalized_excerpt = " ".join(excerpt.casefold().split())
    normalized_context = " ".join(context.casefold().split())
    if normalized_excerpt in normalized_context:
        return True
    excerpt_terms = set(re.findall(r"[a-z0-9]+", normalized_excerpt))
    context_terms = set(re.findall(r"[a-z0-9]+", normalized_context))
    return bool(excerpt_terms) and len(excerpt_terms & context_terms) / len(excerpt_terms) >= 0.9


def _deterministic_reference_match(
    question: str, answer: str, operation: dict
) -> bool | None:
    """Legacy LongMemEval diagnostic; disabled by default and never used for routing.

    The state-comparison rules were introduced after the benchmark format was known.
    They are therefore unsuitable for promotion or general-accuracy claims and are
    retained only to compare historical diagnostic artifacts.
    """
    if not operation.get("requested") or not operation.get("resolved"):
        return None
    operation_name = str(operation.get("operation") or "")
    result = str(operation.get("result") or "")
    answer_text = str(answer or "")
    if operation_name == "current_state":
        answer_numbers = re.findall(r"-?\d+(?:\.\d+)?", answer_text.replace(",", ""))
        result_numbers = re.findall(r"-?\d+(?:\.\d+)?", result.replace(",", ""))
        if answer_numbers:
            return any(number in result_numbers for number in answer_numbers)
        normalized_answer = " ".join(re.findall(r"[a-z0-9]+", answer_text.casefold()))
        normalized_result = " ".join(re.findall(r"[a-z0-9]+", result.casefold()))
        if normalized_answer and normalized_result and (
            normalized_answer in normalized_result or normalized_result in normalized_answer
        ):
            return True
        return None
    if operation_name == "state_comparison" and answer_text.strip().casefold() in {"yes", "yes."}:
        if re.search(r"\b(higher|increase|more)\b", question, re.I):
            return result.casefold().startswith("increased")
        if re.search(r"\b(lower|decrease|less)\b", question, re.I):
            return result.casefold().startswith("decreased")
        return None
    if operation_name not in {
        "sum", "average", "difference", "date_difference", "declared_cardinality"
    }:
        return None
    answer_values = [
        float(value)
        for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", answer_text.replace(",", ""))
    ]
    result_values = [
        float(value)
        for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", result.replace(",", ""))
    ]
    if not answer_values or not result_values:
        return None
    return any(math.isclose(result_values[0], expected, rel_tol=1e-6, abs_tol=1e-6) for expected in answer_values)


def coverage_report(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
    labels: list[dict],
    *,
    impact_question_ids: set[str] | None = None,
    base_report: dict | None = None,
) -> dict:
    label_map = {row["question_id"]: row for row in labels}
    baseline_hypotheses = {
        row["question_id"]: row
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.hypotheses.jsonl"
        )
    }
    if impact_question_ids:
        if base_report is None:
            raise ValueError("Impact-only coverage requires a base report")
        rows = []
        for row in base_report["rows"]:
            if row["question_id"] in impact_question_ids:
                continue
            migrated = dict(row)
            # v5 cache entries cannot be written without a terminal outcome for
            # every deterministic source unit; older reports simply omitted the
            # aggregate field.
            migrated.setdefault(
                "source_coverage_complete",
                base_report.get("atomic_memory_version") == ATOMIC_MEMORY_VERSION,
            )
            rows.append(migrated)
    else:
        rows = []
    total_usage: Counter[str] = Counter()
    for item in manifest["questions"]:
        if impact_question_ids and item["question_id"] not in impact_question_ids:
            continue
        reference = references[item["question_id"]]
        facts, diagnostics = _cached_facts(args, reference, item["retrieved_session_ids"])
        atomic_session_ids, newly_recovered_session_ids = (
            _atomic_retrieval_session_ids(
                args,
                reference["question"],
                facts,
                item["retrieved_session_ids"],
            )
        )
        total_usage.update(diagnostics.get("usage") or {})
        source_sessions = {
            session["session_id"]: session
            for session in _session_rows(reference, atomic_session_ids)
        }
        required = label_map[item["question_id"]]["evidence"]
        covered = 0
        query_plan = plan_atomic_query(reference["question"])
        atomic_context, packing_metadata = pack_atomic_facts(
            reference["question"],
            facts,
            atomic_session_ids,
            token_budget=args.fact_token_budget,
            plan=query_plan,
        )
        selected_ids = set(
            packing_metadata.get("satisfied_fact_ids")
            or packing_metadata["selected_fact_ids"]
        )
        route = route_atomic_question(
            reference["question"],
            retrieved_session_count=len(atomic_session_ids),
            plan=query_plan,
        )
        contract = validate_atomic_contract(
            query_plan, facts, selected_ids, packing_metadata
        )
        operation = evaluate_deterministic_operation(
            reference["question"],
            facts,
            selected_ids,
            plan=query_plan,
            operand_fact_ids=contract.operand_fact_ids,
        )
        operation_safe = not operation.requested or operation.resolved
        operation_reference_match = (
            _deterministic_reference_match(
                reference["question"],
                reference["answer"],
                operation.model_dump(mode="json"),
            )
            if getattr(args, "diagnostic_reference_matcher", False)
            else None
        )
        atomic_active = (
            route.path == "atomic"
            and contract.safe
            and operation_safe
        )
        claim_context = ""
        if not atomic_active:
            claim_context, _ = _claim_first_context(
                reference, item["retrieved_session_ids"], args.claim_first_token_budget
            )
        packed_covered = 0
        effective_covered = 0
        missed_packed_evidence: list[dict] = []
        for evidence in required:
            session = source_sessions.get(evidence["session_id"])
            if session is None:
                continue
            source = str(session["turns"][evidence["turn_index"]].get("content") or "")
            matching = [
                fact
                for fact in facts
                if (
                fact.citation.session_id == evidence["session_id"]
                and fact.citation.turn_index == evidence["turn_index"]
                and _spans_overlap(source, evidence["excerpt"], fact.citation.excerpt)
                )
            ]
            if matching:
                covered += 1
            if any(fact.fact_id in selected_ids for fact in matching):
                packed_covered += 1
            elif matching:
                missed_packed_evidence.append(
                    {
                        "session_id": evidence["session_id"],
                        "turn_index": evidence["turn_index"],
                        "role": evidence["role"],
                        "excerpt": evidence["excerpt"],
                    }
                )
            if (
                atomic_active
                and any(fact.fact_id in selected_ids for fact in matching)
            ) or (
                not atomic_active
                and _excerpt_in_context(evidence["excerpt"], claim_context)
            ):
                effective_covered += 1
        effective_context = atomic_context if atomic_active else claim_context
        baseline_prompt_tokens = int(
            baseline_hypotheses[item["question_id"]].get("reader_prompt_tokens") or 0
        )
        expected_prompt_tokens = (
            estimate_atomic_tokens(_answer_prompt(reference, effective_context))
            if atomic_active
            else baseline_prompt_tokens
        )
        rows.append(
            {
                "question_id": item["question_id"],
                "question_type": item["question_type"],
                "split": item["split"],
                "required_evidence_count": len(required),
                "covered_evidence_count": covered,
                "packed_covered_evidence_count": packed_covered,
                "effective_covered_evidence_count": effective_covered,
                "all_evidence_covered": bool(required) and covered == len(required),
                "all_evidence_packed": bool(required)
                and packed_covered == len(required),
                "all_effective_evidence_packed": bool(required)
                and effective_covered == len(required),
                "route_candidate": route.path,
                "route_reason": route.reason,
                "query_plan": query_plan.model_dump(mode="json"),
                "raw_retrieved_session_ids": item["retrieved_session_ids"],
                "atomic_candidate_session_ids": atomic_session_ids,
                "newly_recovered_atomic_session_ids": newly_recovered_session_ids,
                "contract": contract.model_dump(mode="json"),
                "effective_path": "atomic" if atomic_active else "claim-first",
                "fallback_reasons": [
                    *contract.reasons,
                    *(
                        [operation.fallback_reason]
                        if operation.requested and not operation.resolved
                        else []
                    ),
                ],
                "operation": operation.model_dump(mode="json"),
                "operation_reference_match": operation_reference_match,
                "fact_count": len(facts),
                "packed_fact_count": packing_metadata["selected_fact_count"],
                "packed_tokens_estimate": packing_metadata["packed_tokens_estimate"],
                "effective_tokens_estimate": estimate_atomic_tokens(effective_context),
                "expected_prompt_tokens": expected_prompt_tokens,
                "baseline_prompt_tokens": baseline_prompt_tokens,
                "missed_packed_evidence": missed_packed_evidence,
                "invalid_fact_count": diagnostics["invalid_fact_count"],
                "source_coverage_complete": diagnostics.get(
                    "source_coverage_complete", False
                ),
            }
        )
    required_count = sum(row["required_evidence_count"] for row in rows)
    covered_count = sum(row["covered_evidence_count"] for row in rows)
    packed_covered_count = sum(row["packed_covered_evidence_count"] for row in rows)
    effective_covered_count = sum(
        row["effective_covered_evidence_count"] for row in rows
    )
    atomic_rows = [row for row in rows if row["effective_path"] == "atomic"]
    labeled_atomic_rows = [
        row for row in atomic_rows if row["required_evidence_count"] > 0
    ]
    atomic_candidate_rows = [row for row in rows if row["route_candidate"] == "atomic"]
    temporal_rows = [row for row in rows if row["question_type"] == "temporal-reasoning"]
    direct_rows = [row for row in rows if row["question_type"] == "single-session-user"]
    baseline_prompt_values = [
        int(baseline_hypotheses[row["question_id"]].get("reader_prompt_tokens") or 0)
        for row in rows
        if row["question_id"] in baseline_hypotheses
    ]
    baseline_mean_prompt = statistics.mean(baseline_prompt_values)
    expected_mean_prompt = statistics.mean(
        row["expected_prompt_tokens"] for row in rows
    )
    report = {
        "protocol": "longmemeval-answer-blind-oracle-coverage-v2",
        "annotation_protocol": "answer-blind-gold-session-oracle-v2",
        "metric_scope": (
            "Coverage against answer-blind evidence annotated inside benchmark-designated "
            "source sessions. This is oracle-source coverage, not independent retrieval "
            "accuracy."
        ),
        "extraction_scope": getattr(args, "atomic_extraction_scope", "full-haystack"),
        "diagnostic_reference_matcher_enabled": getattr(
            args, "diagnostic_reference_matcher", False
        ),
        "atomic_independent_retrieval_enabled": (
            getattr(args, "atomic_extraction_scope", "full-haystack")
            == "full-haystack"
        ),
        "atomic_memory_version": ATOMIC_MEMORY_VERSION,
        "question_count": len(rows),
        "labeled_question_count": sum(
            row["required_evidence_count"] > 0 for row in rows
        ),
        "labeled_question_rate": round(
            sum(row["required_evidence_count"] > 0 for row in rows) / len(rows), 6
        ),
        "required_evidence_count": required_count,
        "covered_evidence_count": covered_count,
        "answer_blind_oracle_evidence_recall": (
            round(covered_count / required_count, 6) if required_count else 0.0
        ),
        # Compatibility alias. The protocol and metric_scope above make the oracle
        # provenance explicit for older report consumers.
        "evidence_recall": round(covered_count / required_count, 6) if required_count else 0.0,
        "packed_evidence_count": packed_covered_count,
        "packed_evidence_recall": (
            round(packed_covered_count / required_count, 6) if required_count else 0.0
        ),
        "effective_evidence_recall": (
            round(effective_covered_count / required_count, 6)
            if required_count else 0.0
        ),
        "question_complete_rate": round(
            sum(row["all_evidence_covered"] for row in rows) / len(rows), 6
        ),
        "question_packed_complete_rate": round(
            sum(row["all_evidence_packed"] for row in rows) / len(rows), 6
        ),
        "atomic_used_question_count": len(atomic_rows),
        "atomic_labeled_question_count": len(labeled_atomic_rows),
        "atomic_unlabeled_question_count": len(atomic_rows) - len(labeled_atomic_rows),
        "atomic_candidate_question_count": len(atomic_candidate_rows),
        "atomic_activation_rate": round(len(atomic_rows) / len(rows), 6),
        "claim_first_fallback_question_count": len(rows) - len(atomic_rows),
        "atomic_new_session_recovery_count": sum(
            len(row["newly_recovered_atomic_session_ids"]) for row in rows
        ),
        "atomic_questions_with_new_session_recovery": sum(
            bool(row["newly_recovered_atomic_session_ids"]) for row in rows
        ),
        "atomic_routed_question_complete_rate": round(
            sum(row["all_evidence_packed"] for row in labeled_atomic_rows)
            / len(labeled_atomic_rows),
            6,
        ) if labeled_atomic_rows else 1.0,
        "atomic_false_safe_count": sum(
            not row["all_evidence_packed"] for row in labeled_atomic_rows
        ),
        "diagnostic_operation_reference_mismatch_count": sum(
            row["operation_reference_match"] is False for row in atomic_rows
        ),
        "deterministic_operation_checked_count": sum(
            row["operation_reference_match"] is not None for row in atomic_rows
        ),
        "deterministic_operation_correct_count": sum(
            row["operation_reference_match"] is True for row in atomic_rows
        ),
        "effective_question_complete_rate": round(
            sum(row["all_effective_evidence_packed"] for row in rows) / len(rows), 6
        ),
        "temporal_anchor_recall": round(
            sum(row["covered_evidence_count"] for row in temporal_rows)
            / max(1, sum(row["required_evidence_count"] for row in temporal_rows)),
            6,
        ),
        "temporal_effective_evidence_recall": round(
            sum(row["effective_covered_evidence_count"] for row in temporal_rows)
            / max(1, sum(row["required_evidence_count"] for row in temporal_rows)),
            6,
        ),
        "direct_fact_recall": round(
            sum(row["effective_covered_evidence_count"] for row in direct_rows)
            / max(1, sum(row["required_evidence_count"] for row in direct_rows)),
            6,
        ),
        "baseline_mean_reader_prompt_tokens": round(baseline_mean_prompt, 2),
        "expected_mean_reader_prompt_tokens": round(expected_mean_prompt, 2),
        "expected_tokens_below_claim_first": expected_mean_prompt < baseline_mean_prompt,
        "mean_fact_count": round(statistics.mean(row["fact_count"] for row in rows), 2),
        "mean_packed_tokens_estimate": round(
            statistics.mean(row["packed_tokens_estimate"] for row in rows), 2
        ),
        "invalid_fact_count": sum(row["invalid_fact_count"] for row in rows),
        "source_coverage_complete_rate": round(
            sum(row.get("source_coverage_complete", False) for row in rows) / len(rows), 6
        ),
        "impact_only_recomputed_question_count": (
            len(impact_question_ids) if impact_question_ids else len(rows)
        ),
        "rows": rows,
    }
    (args.run_dir / "coverage.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return report


def _coverage_stage_fingerprint(
    args: argparse.Namespace, manifest: dict, labels: list[dict]
) -> str:
    code_paths = (
        Path(__file__),
        REPO_ROOT / "backend/app/core/atomic_memory.py",
        REPO_ROOT / "backend/app/core/claim_semantics.py",
        REPO_ROOT / "backend/app/core/claim_evidence_packing.py",
    )
    impact_ids = set(getattr(args, "impact_question_id", []))
    base_coverage = (
        json.loads(args.base_coverage.read_text(encoding="utf-8"))
        if getattr(args, "base_coverage", None) is not None
        else None
    )
    stable_base_payload = (
        {
            "rows": [
                row for row in base_coverage["rows"]
                if row["question_id"] not in impact_ids
            ]
        }
        if base_coverage is not None
        else None
    )
    payload = {
        "protocol": "atomic-memory-answer-blind-coverage-stage-v2",
        "atomic_memory_version": ATOMIC_MEMORY_VERSION,
        "manifest": manifest,
        "labels": sorted(labels, key=lambda row: row["question_id"]),
        "configuration": {
            "fact_token_budget": args.fact_token_budget,
            "claim_first_token_budget": args.claim_first_token_budget,
            "semantic_extraction": args.semantic_extraction,
            "extractor_model": args.extractor_model if args.semantic_extraction else None,
            "semantic_cache_model": _semantic_cache_model(args),
            "atomic_extraction_scope": getattr(
                args, "atomic_extraction_scope", "full-haystack"
            ),
            "diagnostic_reference_matcher": getattr(
                args, "diagnostic_reference_matcher", False
            ),
            "impact_question_ids": sorted(impact_ids),
            "base_coverage_sha256": (
                hashlib.sha256(
                    json.dumps(
                        stable_base_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if stable_base_payload is not None
                else None
            ),
        },
        "code_sha256": {
            str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in code_paths
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def cached_coverage_report(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
    labels: list[dict],
) -> dict:
    fingerprint = _coverage_stage_fingerprint(args, manifest, labels)
    stage_path = args.run_dir / "coverage-stage" / f"{fingerprint}.json"
    output_path = args.run_dir / "coverage.json"
    if stage_path.exists() and not args.force_coverage_recompute:
        shutil.copyfile(stage_path, output_path)
        report = json.loads(stage_path.read_text(encoding="utf-8"))
        print(json.dumps({
            "coverage_stage_cache_hit": True,
            "coverage_stage_fingerprint": fingerprint,
            "coverage_path": str(output_path),
        }, indent=2))
        return report
    impact_ids = set(args.impact_question_id)
    base_report = (
        json.loads(args.base_coverage.read_text(encoding="utf-8"))
        if args.base_coverage is not None
        else None
    )
    report = coverage_report(
        args,
        manifest,
        references,
        labels,
        impact_question_ids=impact_ids or None,
        base_report=base_report,
    )
    report["coverage_stage_fingerprint"] = fingerprint
    report["coverage_stage_cache_hit"] = False
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    stage_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _reader_context(
    args: argparse.Namespace,
    arm: str,
    reference: dict,
    retrieved_session_ids: list[str],
) -> tuple[str, dict]:
    facts, extraction = _cached_facts(args, reference, retrieved_session_ids)
    atomic_session_ids, newly_recovered_session_ids = _atomic_retrieval_session_ids(
        args,
        reference["question"],
        facts,
        retrieved_session_ids,
    )
    if arm in {"facts-only", "adaptive"}:
        query_plan = plan_atomic_query(reference["question"])
        context, metadata = pack_atomic_facts(
            reference["question"],
            facts,
            atomic_session_ids,
            token_budget=args.fact_token_budget,
            plan=query_plan,
        )
        selected_ids = metadata.get("satisfied_fact_ids") or metadata["selected_fact_ids"]
        contract = validate_atomic_contract(
            query_plan, facts, selected_ids, metadata
        )
        operation = evaluate_deterministic_operation(
            reference["question"],
            facts,
            selected_ids,
            plan=query_plan,
            operand_fact_ids=contract.operand_fact_ids,
        )
        rendered_operation = render_deterministic_operation(operation)
        if rendered_operation:
            context = rendered_operation + "\n\n" + context
        return context, {
            **metadata,
            "query_plan": query_plan.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
            "operation": operation.model_dump(mode="json"),
            "extraction": extraction,
            "raw_retrieved_session_ids": retrieved_session_ids,
            "atomic_candidate_session_ids": atomic_session_ids,
            "newly_recovered_atomic_session_ids": newly_recovered_session_ids,
        }
    if arm != "hybrid":
        raise ValueError(f"Unsupported arm: {arm}")
    fact_context, fact_metadata = pack_atomic_facts(
        reference["question"],
        facts,
        atomic_session_ids,
        token_budget=args.hybrid_fact_token_budget,
    )
    sessions = [
        SessionEnvelope(
            session_id=session["session_id"],
            date=session["date"],
            turns=session["turns"],
            retrieval_rank=rank,
        )
        for rank, session in enumerate(_session_rows(reference, retrieved_session_ids))
    ]
    raw_context, raw_metadata = pack_claim_evidence(
        question=reference["question"],
        sessions=sessions,
        token_budget=args.hybrid_raw_token_budget,
        question_type="",
        consolidate=False,
    )
    context = (
        "WRITE-TIME ATOMIC FACTS:\n"
        + fact_context
        + "\n\nBOUNDED RAW CITED EVIDENCE:\n"
        + raw_context
    )
    return context, {
        "packing": "atomic-memory-v1-plus-claim-first-v3",
        "fact": fact_metadata,
        "raw": raw_metadata,
        "extraction": extraction,
        "raw_retrieved_session_ids": retrieved_session_ids,
        "atomic_candidate_session_ids": atomic_session_ids,
        "newly_recovered_atomic_session_ids": newly_recovered_session_ids,
    }


def _adaptive_decision(
    args: argparse.Namespace,
    item: dict,
    reference: dict,
) -> tuple[bool, dict]:
    question = str(reference.get("question") or "")
    query_plan = plan_atomic_query(question)
    route = route_atomic_question(
        question,
        retrieved_session_count=len(item["retrieved_session_ids"]),
        plan=query_plan,
    )
    if route.path != "atomic":
        return False, {"route": route.model_dump(mode="json")}
    _, metadata = _reader_context(
        args, "adaptive", reference, item["retrieved_session_ids"]
    )
    operation = metadata["operation"]
    operation_safe = not operation["requested"] or operation["resolved"]
    contract = metadata["contract"]
    use_atomic = bool(contract["safe"] and operation_safe)
    return use_atomic, {
        "route": route.model_dump(mode="json"),
        "packing": metadata,
        "fallback_reasons": [
            *contract["reasons"],
            *(
                [operation["fallback_reason"]]
                if operation["requested"] and not operation["resolved"]
                else []
            ),
        ],
    }


def _answer_arm(
    args: argparse.Namespace,
    provider,
    arm: str,
    items: list[dict],
    references: dict[str, dict],
) -> list[dict]:
    path = args.run_dir / f"{arm}-answers.jsonl"
    existing = {row["question_id"]: row for row in _load_jsonl(path)}

    def prepare(item: dict) -> dict:
        reference = references[item["question_id"]]
        context, metadata = _reader_context(
            args, arm, reference, item["retrieved_session_ids"]
        )
        prompt = _answer_prompt(reference, context)
        stage_payload = {
            "stage": "reader-answer-v2-bounded-length-retry",
            "question_id": item["question_id"],
            "arm": arm,
            "provider": getattr(provider, "name", "unknown"),
            "model": getattr(provider, "model", "unknown"),
            "max_tokens": args.answer_max_tokens,
            "length_retry_max_tokens": min(args.answer_max_tokens * 2, 1_024),
            "prompt": prompt,
        }
        fingerprint = hashlib.sha256(
            json.dumps(stage_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "item": item,
            "reference": reference,
            "metadata": metadata,
            "prompt": prompt,
            "stage_fingerprint": fingerprint,
        }

    def answer(prepared: dict) -> dict:
        item = prepared["item"]
        try:
            responses = []
            response = _chat(
                provider,
                prepared["prompt"],
                max_tokens=args.answer_max_tokens,
                timeout=args.timeout,
                retries=args.retries,
            )
            responses.append(response)
            if response["choices"][0].get("finish_reason") == "length":
                response = _chat(
                    provider,
                    prepared["prompt"],
                    max_tokens=min(args.answer_max_tokens * 2, 1_024),
                    timeout=args.timeout,
                    retries=args.retries,
                )
                responses.append(response)
            hypothesis = response["choices"][0]["message"]["content"].strip()
            finish_reason = response["choices"][0].get("finish_reason")
            usage_counter: Counter[str] = Counter()
            for attempt in responses:
                usage_counter.update(_usage(attempt))
            usage = dict(usage_counter)
            content_filtered = False
        except ProviderContentFilterError:
            hypothesis = "The provider rejected the supplied evidence, so no answer was produced."
            finish_reason = "content_filter"
            usage = {}
            content_filtered = True
        row = {
            "question_id": item["question_id"],
            "question_type": item["question_type"],
            "arm": arm,
            "hypothesis": hypothesis,
            "finish_reason": finish_reason,
            "content_filtered": content_filtered,
            "attempt_count": len(responses) if not content_filtered else 1,
            "usage": usage,
            "context_metadata": prepared["metadata"],
            "stage_fingerprint": prepared["stage_fingerprint"],
        }
        _append_jsonl(path, row)
        return row

    prepared_items = [prepare(item) for item in items]
    pending = [
        prepared
        for prepared in prepared_items
        if existing.get(prepared["item"]["question_id"], {}).get("stage_fingerprint")
        != prepared["stage_fingerprint"]
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(answer, prepared) for prepared in pending]
        for position, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            existing[row["question_id"]] = row
            print(f"answered {arm} {position}/{len(pending)}: {row['question_id']}", flush=True)
    return [existing[item["question_id"]] for item in items]


def _judge_arm(
    args: argparse.Namespace,
    provider,
    arm: str,
    answers: list[dict],
    references: dict[str, dict],
) -> list[dict]:
    path = args.run_dir / f"{arm}-{provider.name}-judgments.jsonl"
    existing = {row["question_id"]: row for row in _load_jsonl(path)}

    def prepare(answer: dict) -> dict:
        reference = references[answer["question_id"]]
        prompt = _judge_prompt(reference, answer["hypothesis"])
        payload = {
            "stage": "judge-answer-v1",
            "question_id": answer["question_id"],
            "arm": arm,
            "provider": getattr(provider, "name", "unknown"),
            "model": getattr(provider, "model", "unknown"),
            "answer_fingerprint": answer.get("stage_fingerprint"),
            "hypothesis_sha256": hashlib.sha256(
                str(answer.get("hypothesis") or "").encode("utf-8")
            ).hexdigest(),
            "prompt": prompt,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"answer": answer, "prompt": prompt, "stage_fingerprint": fingerprint}

    def judge(prepared: dict) -> dict:
        answer = prepared["answer"]
        try:
            response = _chat(
                provider,
                prepared["prompt"],
                max_tokens=16,
                timeout=args.timeout,
                retries=args.retries,
            )
            raw = response["choices"][0]["message"]["content"].strip()
            label = raw.casefold().startswith("yes")
            usage = _usage(response)
            content_filtered = False
        except ProviderContentFilterError:
            raw = "content_filter"
            label = False
            usage = {}
            content_filtered = True
        row = {
            "question_id": answer["question_id"],
            "arm": arm,
            "provider": provider.name,
            "label": label,
            "raw": raw,
            "content_filtered": content_filtered,
            "usage": usage,
            "stage_fingerprint": prepared["stage_fingerprint"],
        }
        _append_jsonl(path, row)
        return row

    prepared_answers = [prepare(answer) for answer in answers]
    pending = [
        prepared
        for prepared in prepared_answers
        if existing.get(prepared["answer"]["question_id"], {}).get("stage_fingerprint")
        != prepared["stage_fingerprint"]
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(judge, prepared) for prepared in pending]
        for position, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            existing[row["question_id"]] = row
            print(
                f"judged {arm}/{provider.name} {position}/{len(pending)}: "
                f"{row['question_id']}={row['label']}",
                flush=True,
            )
    return [existing[answer["question_id"]] for answer in answers]


def evaluate(
    args: argparse.Namespace,
    manifest: dict,
    references: dict[str, dict],
) -> dict:
    items = [item for item in manifest["questions"] if item["split"] == "evaluation"]
    reader = _provider(args.reader_provider, args.reader_model)
    primary = _provider(args.primary_judge_provider, args.primary_judge_model)
    independent = _provider(
        args.independent_judge_provider, args.independent_judge_model
    )
    baseline_answers = {
        row["question_id"]: row
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.hypotheses.jsonl"
        )
    }
    saved_primary = {
        row["question_id"]: bool(row["autoeval_label"]["label"])
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.kimi-evaluated.jsonl"
        )
    }
    saved_independent = {
        row["question_id"]: bool(row["autoeval_label"]["label"])
        for row in _load_jsonl(
            args.artifact_dir / "longmemeval-claim-first-10k-v2-full500.openai-evaluated.jsonl"
        )
    }
    arm_results: dict[str, dict] = {
        "claim-first": {
            "answers": [baseline_answers[item["question_id"]] for item in items],
            "primary": [saved_primary[item["question_id"]] for item in items],
            "independent": [saved_independent[item["question_id"]] for item in items],
        }
    }
    requested_arms = tuple(
        arm.strip() for arm in args.evaluation_arms.split(",") if arm.strip()
    )
    unsupported = set(requested_arms) - {"facts-only", "hybrid", "adaptive"}
    if unsupported or not requested_arms:
        raise ValueError(f"Unsupported or empty evaluation arms: {sorted(unsupported)}")
    for arm in requested_arms:
        if arm == "adaptive":
            decisions = {
                item["question_id"]: _adaptive_decision(
                    args, item, references[item["question_id"]]
                )
                for item in items
            }
            generated_items = [
                item for item in items if decisions[item["question_id"]][0]
            ]
            generated_answers = _answer_arm(
                args, reader, arm, generated_items, references
            )
            generated_by_id = {
                answer["question_id"]: answer for answer in generated_answers
            }
            answers = []
            for item in items:
                question_id = item["question_id"]
                if not decisions[question_id][0]:
                    baseline = baseline_answers[question_id]
                    answers.append(
                        {
                            "question_id": question_id,
                            "question_type": item["question_type"],
                            "arm": arm,
                            "hypothesis": baseline["hypothesis"],
                            "finish_reason": baseline.get("reader_finish_reason"),
                            "content_filtered": bool(
                                baseline.get("reader_content_filtered")
                            ),
                            "usage": {
                                "prompt_tokens": int(
                                    baseline.get("reader_prompt_tokens") or 0
                                )
                            },
                            "context_metadata": {
                                "packing": "claim-first-reused-by-adaptive-router",
                                "reused_frozen_baseline": True,
                                **decisions[question_id][1],
                            },
                        }
                    )
                else:
                    answers.append(generated_by_id[question_id])
            primary_rows = _judge_arm(
                args, primary, arm, generated_answers, references
            )
            independent_rows = _judge_arm(
                args, independent, arm, generated_answers, references
            )
            primary_by_id = {row["question_id"]: row["label"] for row in primary_rows}
            independent_by_id = {
                row["question_id"]: row["label"] for row in independent_rows
            }
            arm_results[arm] = {
                "answers": answers,
                "primary": [
                    saved_primary[item["question_id"]]
                    if not decisions[item["question_id"]][0]
                    else primary_by_id[item["question_id"]]
                    for item in items
                ],
                "independent": [
                    saved_independent[item["question_id"]]
                    if not decisions[item["question_id"]][0]
                    else independent_by_id[item["question_id"]]
                    for item in items
                ],
            }
            continue
        answers = _answer_arm(args, reader, arm, items, references)
        primary_rows = _judge_arm(args, primary, arm, answers, references)
        independent_rows = _judge_arm(args, independent, arm, answers, references)
        arm_results[arm] = {
            "answers": answers,
            "primary": [row["label"] for row in primary_rows],
            "independent": [row["label"] for row in independent_rows],
        }

    summary: dict[str, dict] = {}
    for arm, result in arm_results.items():
        dual = [
            primary_label and independent_label
            for primary_label, independent_label in zip(
                result["primary"], result["independent"], strict=True
            )
        ]
        summary[arm] = {
            "question_count": len(items),
            "primary_accuracy": round(sum(result["primary"]) / len(items), 6),
            "independent_accuracy": round(sum(result["independent"]) / len(items), 6),
            "dual_judge_accuracy": round(sum(dual) / len(items), 6),
            "dual_judge_correct_count": sum(dual),
            "dual_judge_accuracy_by_type": {
                question_type: round(
                    sum(
                        label
                        for item, label in zip(items, dual, strict=True)
                        if item["question_type"] == question_type
                    )
                    / sum(item["question_type"] == question_type for item in items),
                    6,
                )
                for question_type in QUESTION_TYPES
                if any(item["question_type"] == question_type for item in items)
            },
        }
        if arm == "claim-first":
            summary[arm]["mean_reader_prompt_tokens"] = round(
                statistics.mean(
                    int(answer.get("reader_prompt_tokens") or 0)
                    for answer in result["answers"]
                ),
                2,
            )
        else:
            prompt_tokens = [
                int(answer["usage"].get("prompt_tokens") or 0) for answer in result["answers"]
            ]
            summary[arm]["mean_reader_prompt_tokens"] = round(
                statistics.mean(prompt_tokens), 2
            )
            summary[arm]["reader_content_filter_count"] = sum(
                bool(answer.get("content_filtered")) for answer in result["answers"]
            )

    baseline_dual = [
        saved_primary[item["question_id"]] and saved_independent[item["question_id"]]
        for item in items
    ]
    for arm in requested_arms:
        arm_dual = [
            primary_label and independent_label
            for primary_label, independent_label in zip(
                arm_results[arm]["primary"], arm_results[arm]["independent"], strict=True
            )
        ]
        summary[arm]["wins_vs_claim_first"] = sum(
            new and not old for old, new in zip(baseline_dual, arm_dual, strict=True)
        )
        summary[arm]["losses_vs_claim_first"] = sum(
            old and not new for old, new in zip(baseline_dual, arm_dual, strict=True)
        )
        summary[arm]["win_question_ids"] = [
            item["question_id"]
            for item, old, new in zip(items, baseline_dual, arm_dual, strict=True)
            if new and not old
        ]
        summary[arm]["loss_question_ids"] = [
            item["question_id"]
            for item, old, new in zip(items, baseline_dual, arm_dual, strict=True)
            if old and not new
        ]
        wins = summary[arm]["wins_vs_claim_first"]
        losses = summary[arm]["losses_vs_claim_first"]
        discordant = wins + losses
        tail = min(wins, losses)
        exact_p = (
            min(
                1.0,
                2.0 * sum(
                    math.comb(discordant, index) * (0.5 ** discordant)
                    for index in range(tail + 1)
                ),
            )
            if discordant else 1.0
        )
        retained_controls = sum(baseline_dual)
        regression_rate = losses / retained_controls if retained_controls else 0.0
        family_regressions = {
            question_type: round(
                summary[arm]["dual_judge_accuracy_by_type"][question_type]
                - summary["claim-first"]["dual_judge_accuracy_by_type"][question_type],
                6,
            )
            for question_type in summary[arm]["dual_judge_accuracy_by_type"]
        }
        promotion_failures: list[str] = []
        if manifest.get("selection_mode") != "representative":
            promotion_failures.append(
                "diagnostic pilot-balanced selection is not promotion-eligible"
            )
        if wins <= losses:
            promotion_failures.append("paired wins do not exceed losses")
        if regression_rate > 0.02:
            promotion_failures.append("previously-correct regression exceeds 2%")
        if any(delta < -0.02 for delta in family_regressions.values()):
            promotion_failures.append("a question family regressed by more than 2%")
        if summary[arm]["mean_reader_prompt_tokens"] > summary["claim-first"]["mean_reader_prompt_tokens"]:
            promotion_failures.append("mean reader prompt tokens exceed claim-first")
        summary[arm]["mcnemar_exact_p_value"] = round(exact_p, 6)
        summary[arm]["previously_correct_regression_rate"] = round(regression_rate, 6)
        summary[arm]["accuracy_delta_by_type"] = family_regressions
        summary[arm]["statistically_credible_improvement"] = exact_p < 0.05 and wins > losses
        summary[arm]["promotion_passed"] = not promotion_failures
        summary[arm]["promotion_failures"] = promotion_failures

    report = {
        "protocol": "longmemeval-frozen-three-arm-atomic-memory-v2",
        "evaluation_question_count": len(items),
        "headline_eligible": manifest.get("selection_mode") == "representative",
        "selection_note": (
            "seeded representative held-out sample; pilot questions excluded"
            if manifest.get("selection_mode") == "representative"
            else "balanced recovery/control pilot; not a full-500 headline score"
        ),
        "summary": summary,
    }
    (args.run_dir / "ablation-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    args = parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args)
    _, references, _ = _load_inputs(args.artifact_dir)
    if args.phase == "freeze":
        print(json.dumps({"question_count": manifest["question_count"]}, indent=2))
        return
    if args.phase in {"semantic-export", "semantic-import"}:
        print(json.dumps(semantic_queue_phase(args, manifest, references), indent=2))
        return
    labels: list[dict] = []
    if args.phase in {"label", "all"}:
        labels = label_evidence(args, manifest, references)
        if args.phase == "label":
            return
    if args.phase in {"extract", "all"}:
        extract_sessions(args, manifest, references)
        if args.phase == "extract":
            return
    if not labels:
        labels = _load_evidence_labels(args.run_dir)
    if args.phase in {"coverage", "all"}:
        coverage = cached_coverage_report(args, manifest, references, labels)
        if args.phase == "coverage":
            return
        if coverage["evidence_recall"] < args.minimum_evidence_recall:
            raise RuntimeError(
                "Stored evidence recall failed the configured promotion gate: "
                f"{coverage['evidence_recall']:.4f} < {args.minimum_evidence_recall:.4f}"
            )
        if coverage["labeled_question_rate"] < args.minimum_labeled_question_rate:
            raise RuntimeError(
                "Evidence-label coverage failed the configured promotion gate: "
                f"{coverage['labeled_question_rate']:.4f} < "
                f"{args.minimum_labeled_question_rate:.4f}"
            )
        if (
            coverage["atomic_routed_question_complete_rate"]
            < args.minimum_atomic_question_completeness
        ):
            raise RuntimeError(
                "Atomic-routed question completeness failed the promotion gate: "
                f"{coverage['atomic_routed_question_complete_rate']:.4f} < "
                f"{args.minimum_atomic_question_completeness:.4f}"
            )
        if coverage["atomic_false_safe_count"] > args.maximum_atomic_false_safe_count:
            raise RuntimeError(
                "Atomic false-safe packets exceeded the configured gate: "
                f"{coverage['atomic_false_safe_count']} > "
                f"{args.maximum_atomic_false_safe_count}"
            )
        if coverage["atomic_activation_rate"] < args.minimum_atomic_activation_rate:
            raise RuntimeError(
                "Atomic activation is too low for a meaningful reader evaluation: "
                f"{coverage['atomic_activation_rate']:.4f} < "
                f"{args.minimum_atomic_activation_rate:.4f}"
            )
        if coverage["temporal_anchor_recall"] < args.minimum_temporal_anchor_recall:
            raise RuntimeError(
                "Temporal/date anchor recall failed the promotion gate: "
                f"{coverage['temporal_anchor_recall']:.4f} < "
                f"{args.minimum_temporal_anchor_recall:.4f}"
            )
        if coverage["direct_fact_recall"] < args.minimum_direct_fact_recall:
            raise RuntimeError(
                "Direct fact recall failed the promotion gate: "
                f"{coverage['direct_fact_recall']:.4f} < "
                f"{args.minimum_direct_fact_recall:.4f}"
            )
        if coverage["source_coverage_complete_rate"] < args.minimum_source_unit_coverage:
            raise RuntimeError(
                "Source-unit compiler coverage failed the promotion gate: "
                f"{coverage['source_coverage_complete_rate']:.4f} < "
                f"{args.minimum_source_unit_coverage:.4f}"
            )
        if not coverage["expected_tokens_below_claim_first"]:
            raise RuntimeError("Expected prompt tokens are not below claim-first")
    if args.phase in {"evaluate", "all"}:
        evaluate(args, manifest, references)


if __name__ == "__main__":
    main()
