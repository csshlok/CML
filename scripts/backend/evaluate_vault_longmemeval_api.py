from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_local import (
    _answer_prompt,
    _judge_prompt,
    _load_jsonl,
    _metrics,
    _pack_retrieved_context,
    _reader_route,
    _routed_answer_prompt,
    _structured_answer_prompt,
    _structured_answer_prompt_v2,
    _write_jsonl,
)
from backend.app.core.typed_evidence import (
    SCHEMA_HASH as TYPED_EVIDENCE_SCHEMA_HASH,
    extract_evidence,
    plan_query,
    reduce_evidence,
    render_evidence_contract,
)
from backend.app.core.claim_evidence_packing import (
    CLAIM_PACKER_VERSION,
    SessionEnvelope,
    estimate_claim_tokens,
    pack_claim_evidence,
)
from backend.app.core.context_reduction import estimate_tokens


SCHEMA_VERSION = 2
READER_PROTOCOL = "longmemeval-official-noncot-chronological-session-reader-v3"
STRUCTURED_READER_PROTOCOL = "longmemeval-structured-evidence-reader-v1"
STRUCTURED_READER_V2_PROTOCOL = "longmemeval-structured-evidence-reader-v2"
ROUTED_READER_PROTOCOL = "longmemeval-routed-evidence-reader-v5"
TYPED_EVIDENCE_READER_PROTOCOL = "longmemeval-typed-evidence-reader-v2"
JUDGE_PROTOCOL_VERSION = "longmemeval-official-prompts-strict-binary-v2"


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key_env: str
    input_price_per_million: float
    output_price_per_million: float
    cached_input_price_per_million: float | None = None


class ProviderContentFilterError(RuntimeError):
    """The provider refused the benchmark prompt before generating a response."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate saved Vault LongMemEval retrieval with Kimi as the reader and "
            "primary judge, plus an independent OpenAI judge."
        )
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--question-id",
        action="append",
        default=[],
        help="Evaluate only the named question ID; may be repeated.",
    )
    parser.add_argument("--max-context-chars", type=int, default=200_000)
    parser.add_argument(
        "--context-packing",
        choices=("complete-sessions-v2", "claim-first-v1"),
        default="complete-sessions-v2",
    )
    parser.add_argument(
        "--reader-token-budget",
        type=int,
        default=0,
        help="Hard estimated prompt budget. Required for claim-first-v1.",
    )
    parser.add_argument(
        "--reader-budget-safety-factor",
        type=float,
        default=1.0,
        help=(
            "Optional additional fraction of the provider budget available to the "
            "conservative local estimator."
        ),
    )
    parser.add_argument("--max-answer-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reader-provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument(
        "--reader-prompt",
        choices=("official", "structured", "structured-v2", "routed-v4", "typed-v1"),
        default="official",
    )
    parser.add_argument(
        "--typed-evidence-cache",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/typed-evidence-cache"),
    )
    parser.add_argument("--typed-extraction-max-tokens", type=int, default=8_192)
    parser.add_argument(
        "--primary-judge-provider", choices=("kimi", "openai"), default="kimi"
    )
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument(
        "--independent-judge-provider", choices=("kimi", "openai"), default="openai"
    )
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    return parser.parse_args()


def _provider(name: str, model: str) -> Provider:
    if name == "kimi":
        return Provider(
            name="kimi",
            base_url="https://api.moonshot.ai/v1",
            model=model,
            api_key_env="KIMI_API_KEY",
            input_price_per_million=0.95,
            output_price_per_million=4.0,
            cached_input_price_per_million=0.16,
        )
    if name == "openai":
        prices = {
            "gpt-4o-mini": (0.15, 0.60, 0.075),
            "gpt-5.4": (2.5, 15.0, 0.25),
            "gpt-5.4-2026-03-05": (2.5, 15.0, 0.25),
        }
        input_price, output_price, cached_price = prices.get(
            model, (2.5, 15.0, 0.25)
        )
        return Provider(
            name="openai",
            base_url="https://api.openai.com/v1",
            model=model,
            api_key_env="OPENAI_API_KEY",
            input_price_per_million=input_price,
            output_price_per_million=output_price,
            cached_input_price_per_million=cached_price,
        )
    raise ValueError(f"Unsupported provider: {name}")


def _chat(
    provider: Provider,
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
    retries: int,
) -> dict:
    api_key = os.environ.get(provider.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{provider.api_key_env} is not set")
    body: dict[str, object] = {
        "model": provider.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": max_tokens,
    }
    if provider.name == "kimi":
        body["thinking"] = {"type": "disabled"}
    elif provider.name == "openai" and provider.model.startswith("gpt-5"):
        body["reasoning_effort"] = "none"
    request = Request(
        provider.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1_000]
            if exc.code == 400 and (
                "content_filter" in detail.casefold()
                or "high risk" in detail.casefold()
            ):
                raise ProviderContentFilterError(
                    f"{provider.name} rejected the prompt through its content filter"
                ) from exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt >= retries:
                raise RuntimeError(
                    f"{provider.name} returned HTTP {exc.code}: {detail}"
                ) from exc
        except (URLError, TimeoutError) as exc:
            if attempt >= retries:
                reason = getattr(exc, "reason", str(exc))
                raise RuntimeError(f"{provider.name} request failed: {reason}") from exc
        time.sleep(min(8.0, 2.0**attempt))
    raise AssertionError("unreachable")


def _usage(response: dict) -> dict:
    usage = response.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cached_tokens = int(
        usage.get("cached_tokens")
        or ((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
        or 0
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ensure_manifest(path: Path, payload: dict) -> dict:
    manifest = {**payload, "fingerprint": _fingerprint(payload)}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != manifest:
            raise RuntimeError(
                f"Checkpoint manifest mismatch at {path}. Use a new --output path "
                "for a different dataset, selection, prompt, model, or budget."
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _finish_reason(response: dict) -> str:
    choices = response.get("choices") or []
    return str((choices[0] if choices else {}).get("finish_reason") or "")


def _parse_binary_verdict(verdict: str) -> bool:
    normalized = re.sub(r"[^a-z]+", "", verdict.casefold())
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise RuntimeError(f"Judge returned a non-binary verdict: {verdict!r}")


def _wilson_interval(correct: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    proportion = correct / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _cohen_kappa(left: list[bool], right: list[bool]) -> float | None:
    if not left or len(left) != len(right):
        return None
    observed = statistics.fmean(a == b for a, b in zip(left, right, strict=True))
    left_yes = statistics.fmean(left)
    right_yes = statistics.fmean(right)
    expected = left_yes * right_yes + (1 - left_yes) * (1 - right_yes)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return round((observed - expected) / (1 - expected), 4)


def _checkpoint(path: Path, rows: list[dict]) -> None:
    _write_jsonl(path, rows)


def _usage_attempts(rows: list[dict], *, kind: str) -> list[dict]:
    history_key = f"{kind}_attempt_history"
    usage_key = f"{kind}_usage"
    usages: list[dict] = []
    for row in rows:
        history = row.get(history_key) or []
        if history:
            usages.extend(item["usage"] for item in history)
        else:
            usages.append(row[usage_key])
    return usages


def _typed_contract_prompt(reference: dict, contract: str) -> str:
    return f"""Answer the user's request using only the validated typed evidence contract.

Rules:
- Every REQUIRED claim must materially shape the answer.
- SUPPORTING claims may refine the answer when relevant.
- Do not invent preferences, experiences, constraints, or current external facts.
- If the contract reports missing required evidence, state the personalization limit.
- Return a concise, useful answer without mentioning these instructions.

{contract}

Current date: {reference.get('question_date', '')}
Question: {reference['question']}
Answer:"""


def _reader_protocol(reader_prompt: str) -> str:
    return {
        "official": READER_PROTOCOL,
        "structured": STRUCTURED_READER_PROTOCOL,
        "structured-v2": STRUCTURED_READER_V2_PROTOCOL,
        "routed-v4": ROUTED_READER_PROTOCOL,
        "typed-v1": TYPED_EVIDENCE_READER_PROTOCOL,
    }[reader_prompt]


def _claim_sessions(reference: dict, retrieved_ids: list[str]) -> list[SessionEnvelope]:
    sessions_by_id: dict[str, list[tuple[str, list[dict]]]] = {}
    for session_id, date, turns in zip(
        reference["haystack_session_ids"],
        reference["haystack_dates"],
        reference["haystack_sessions"],
        strict=True,
    ):
        sessions_by_id.setdefault(str(session_id), []).append((str(date), turns))
    sessions: list[SessionEnvelope] = []
    for rank, session_id in enumerate(retrieved_ids):
        for date, turns in sessions_by_id.get(str(session_id), []):
            sessions.append(
                SessionEnvelope(
                    session_id=str(session_id),
                    date=date,
                    turns=turns,
                    retrieval_rank=rank,
                )
            )
    return sessions


def _pack_reader_context(
    args: argparse.Namespace,
    reference: dict,
    retrieved_ids: list[str],
) -> tuple[str, dict]:
    full_context, full_meta = _pack_retrieved_context(
        reference, retrieved_ids, args.max_context_chars
    )
    context_packing = getattr(args, "context_packing", "complete-sessions-v2")
    reader_token_budget = int(getattr(args, "reader_token_budget", 0) or 0)
    if context_packing == "complete-sessions-v2":
        return full_context, {
            **full_meta,
            "prepack_prompt_tokens_estimate": estimate_tokens(
                _routed_answer_prompt(reference, full_context)
            ),
        }
    if reader_token_budget <= 0:
        raise ValueError("--reader-token-budget must be positive for claim-first-v1")
    prompt_builder = {
        "official": _answer_prompt,
        "structured": _structured_answer_prompt,
        "structured-v2": _structured_answer_prompt_v2,
        "routed-v4": _routed_answer_prompt,
        "typed-v1": _routed_answer_prompt,
    }[getattr(args, "reader_prompt", "official")]
    overhead = estimate_claim_tokens(prompt_builder(reference, ""))
    safety_factor = float(
        getattr(args, "reader_budget_safety_factor", 1.0) or 1.0
    )
    packing_target = max(256, int(reader_token_budget * safety_factor))
    # Token estimation is intentionally provider-independent and therefore not exactly
    # additive across prompt sections. Reserve a small fixed boundary margin so an
    # otherwise valid packet cannot cross the public budget by one or two tokens.
    evidence_budget = max(256, packing_target - overhead - 32)
    context, claim_meta = pack_claim_evidence(
        question=reference["question"],
        sessions=_claim_sessions(reference, retrieved_ids),
        token_budget=evidence_budget,
        question_type=str(reference.get("question_type") or ""),
    )
    return context, {
        **claim_meta,
        "context_chars": len(context),
        "unbounded_context_chars": int(full_meta["unbounded_context_chars"]),
        "prepack_prompt_tokens_estimate": estimate_claim_tokens(
            prompt_builder(reference, full_context)
        ),
        "packed_prompt_tokens_estimate": estimate_claim_tokens(
            prompt_builder(reference, context)
        ),
        "prompt_overhead_tokens_estimate": overhead,
        "reader_budget_safety_factor": safety_factor,
        "packing_target_tokens_estimate": packing_target,
        "evidence_token_budget": evidence_budget,
        "complete_session_candidate_count": int(full_meta["candidate_session_count"]),
    }


def _generate(
    args: argparse.Namespace,
    provider: Provider,
    selected: list[dict],
    references: dict[str, dict],
    path: Path,
    run_fingerprint: str,
) -> list[dict]:
    candidates = {
        row["question_id"]: row
        for row in _load_jsonl(path)
        if row.get("reader_model") == provider.model
        and row.get("run_fingerprint") == run_fingerprint
        and int(row.get("max_context_chars", args.max_context_chars))
        == args.max_context_chars
    }
    existing = {
        question_id: row
        for question_id, row in candidates.items()
        if row.get("reader_finish_reason") != "length"
        or int(row.get("max_answer_tokens") or args.max_answer_tokens) >= 2_048
    }
    continuations = {
        question_id: row
        for question_id, row in candidates.items()
        if question_id not in existing
    }
    for position, retrieval in enumerate(selected, start=1):
        question_id = retrieval["question_id"]
        if question_id in existing:
            continue
        reference = references[question_id]
        context, context_meta = _pack_reader_context(
            args, reference, retrieval["retrieved_session_ids"]
        )
        started = time.perf_counter()
        continuation = continuations.get(question_id)
        token_budget = (
            max(
                args.max_answer_tokens,
                int(continuation.get("max_answer_tokens") or args.max_answer_tokens) * 2,
            )
            if continuation
            else args.max_answer_tokens
        )
        attempt_history: list[dict] = list(
            (continuation or {}).get("reader_attempt_history") or []
        )
        content_filtered = False
        reader_prompt = getattr(args, "reader_prompt", "official")
        typed_plan = plan_query(reference) if reader_prompt == "typed-v1" else None
        typed_records = []
        typed_result = None
        extraction_diagnostics = None
        typed_prompt: str | None = None
        rendered_prompt = ""
        if typed_plan is not None and typed_plan.intent != "unsupported":
            def semantic_extractor(prompt: str) -> tuple[str, dict]:
                extraction_response = _chat(
                    provider,
                    prompt,
                    max_tokens=args.typed_extraction_max_tokens,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                return (
                    extraction_response["choices"][0]["message"]["content"].strip(),
                    _usage(extraction_response),
                )

            typed_records, extraction_diagnostics = extract_evidence(
                reference,
                retrieval["retrieved_session_ids"],
                model=provider.model,
                cache_dir=args.typed_evidence_cache,
                extractor=semantic_extractor,
            )
            typed_result = reduce_evidence(
                typed_plan, typed_records, question=reference["question"]
            )
            if typed_result.status == "needs_generation":
                typed_prompt = _typed_contract_prompt(
                    reference, render_evidence_contract(typed_result, typed_records)
                )
        while True:
            if typed_result is not None and typed_result.status == "resolved":
                response = {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": typed_result.answer or ""},
                        }
                    ],
                    "usage": {},
                }
            else:
                try:
                    prompt_builders = {
                        "official": _answer_prompt,
                        "structured": _structured_answer_prompt,
                        "structured-v2": _structured_answer_prompt_v2,
                        "routed-v4": _routed_answer_prompt,
                        "typed-v1": _routed_answer_prompt,
                    }
                    prompt = typed_prompt or prompt_builders[reader_prompt](reference, context)
                    rendered_prompt = prompt
                    response = _chat(
                        provider,
                        prompt,
                        max_tokens=token_budget,
                        timeout=args.timeout,
                        retries=args.retries,
                    )
                except ProviderContentFilterError:
                    content_filtered = True
                    response = {
                        "choices": [
                            {
                                "finish_reason": "content_filter",
                                "message": {
                                    "content": "[Reader refused the prompt through its content filter.]"
                                },
                            }
                        ],
                        "usage": {},
                    }
            attempt_history.append(
                {
                    "max_answer_tokens": token_budget,
                    "finish_reason": _finish_reason(response),
                    "usage": _usage(response),
                }
            )
            if _finish_reason(response) != "length" or token_budget >= 2_048:
                break
            token_budget = max(512, token_budget * 2)
        row = {
            "question_id": question_id,
            "hypothesis": response["choices"][0]["message"]["content"].strip(),
            "question_type": reference["question_type"],
            "retrieved_session_ids": retrieval["retrieved_session_ids"],
            **context_meta,
            "reader_provider": provider.name,
            "reader_model": provider.model,
            "reader_protocol": _reader_protocol(reader_prompt),
            "reader_route": (
                _reader_route(reference)
                if reader_prompt in {"routed-v4", "typed-v1"}
                else None
            ),
            "typed_evidence_schema_hash": (
                TYPED_EVIDENCE_SCHEMA_HASH if reader_prompt == "typed-v1" else None
            ),
            "typed_evidence_intent": typed_plan.intent if typed_plan is not None else None,
            "typed_evidence_status": typed_result.status if typed_result is not None else None,
            "typed_evidence_confidence": (
                typed_result.confidence if typed_result is not None else None
            ),
            "typed_evidence_claim_ids": (
                typed_result.evidence_claim_ids if typed_result is not None else []
            ),
            "typed_evidence_records": [
                record.model_dump(mode="json") for record in typed_records
            ],
            "typed_evidence_reason": typed_result.reason if typed_result is not None else None,
            "typed_extraction": (
                extraction_diagnostics.model_dump(mode="json")
                if extraction_diagnostics is not None
                else None
            ),
            "run_fingerprint": run_fingerprint,
            "max_context_chars": args.max_context_chars,
            "max_answer_tokens": token_budget,
            "reader_attempt_count": len(attempt_history),
            "reader_attempt_history": attempt_history,
            "reader_billed_prompt_tokens": sum(
                int((attempt.get("usage") or {}).get("prompt_tokens") or 0)
                for attempt in attempt_history
            ),
            "reader_wall_seconds": round(time.perf_counter() - started, 4),
            "reader_usage": _usage(response),
            "reader_prompt_tokens": int(_usage(response).get("prompt_tokens") or 0),
            "rendered_prompt_tokens_estimate": estimate_claim_tokens(rendered_prompt),
            "reader_token_budget": int(getattr(args, "reader_token_budget", 0) or 0),
            "reader_prompt_over_budget": bool(
                getattr(args, "reader_token_budget", 0)
                and int(_usage(response).get("prompt_tokens") or 0)
                > int(getattr(args, "reader_token_budget", 0))
            ),
            "reader_finish_reason": _finish_reason(response),
            "reader_content_filtered": content_filtered,
        }
        existing[question_id] = row
        continuations.pop(question_id, None)
        _checkpoint(
            path,
            [
                existing.get(item["question_id"])
                or continuations[item["question_id"]]
                for item in selected
                if item["question_id"] in existing
                or item["question_id"] in continuations
            ],
        )
        print(f"reader {position}/{len(selected)} {question_id}", flush=True)
    return [existing[item["question_id"]] for item in selected]


def _judge(
    args: argparse.Namespace,
    provider: Provider,
    hypotheses: list[dict],
    references: dict[str, dict],
    path: Path,
    run_fingerprint: str,
) -> list[dict]:
    protocol = f"{JUDGE_PROTOCOL_VERSION}-{provider.name}-{provider.model}"
    hypothesis_by_id = {str(row["question_id"]): row for row in hypotheses}
    existing = {
        row["question_id"]: row
        for row in _load_jsonl(path)
        if (row.get("autoeval_label") or {}).get("protocol") == protocol
        and str(row["question_id"]) in hypothesis_by_id
        and row.get("hypothesis")
        == hypothesis_by_id[str(row["question_id"])].get("hypothesis")
    }
    for position, hypothesis in enumerate(hypotheses, start=1):
        question_id = hypothesis["question_id"]
        if question_id in existing:
            continue
        started = time.perf_counter()
        judge_attempt_history: list[dict] = []
        judge_content_filtered = False
        for verdict_attempt in range(2):
            try:
                response = _chat(
                    provider,
                    _judge_prompt(references[question_id], hypothesis["hypothesis"]),
                    max_tokens=10,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            except ProviderContentFilterError:
                judge_content_filtered = True
                response = {
                    "choices": [
                        {
                            "finish_reason": "content_filter",
                            "message": {"content": "No"},
                        }
                    ],
                    "usage": {},
                }
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
            "judge_content_filtered": judge_content_filtered,
        }
        existing[question_id] = row
        _checkpoint(path, [existing[item["question_id"]] for item in hypotheses if item["question_id"] in existing])
        print(f"{provider.name} judge {position}/{len(hypotheses)} {question_id}: {verdict}", flush=True)
    return [existing[item["question_id"]] for item in hypotheses]


def _provider_cost(provider: Provider, usages: list[dict]) -> dict:
    prompt = sum(int(item.get("prompt_tokens") or 0) for item in usages)
    completion = sum(int(item.get("completion_tokens") or 0) for item in usages)
    cached = sum(int(item.get("cached_tokens") or 0) for item in usages)
    cost = (
        prompt * provider.input_price_per_million
        + completion * provider.output_price_per_million
    ) / 1_000_000
    cached_rate = (
        provider.cached_input_price_per_million
        if provider.cached_input_price_per_million is not None
        else provider.input_price_per_million
    )
    cache_adjusted_cost = (
        (prompt - cached) * provider.input_price_per_million
        + cached * cached_rate
        + completion * provider.output_price_per_million
    ) / 1_000_000
    return {
        "provider": provider.name,
        "model": provider.model,
        "input_usd_per_million": provider.input_price_per_million,
        "output_usd_per_million": provider.output_price_per_million,
        "cached_input_usd_per_million": cached_rate,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens_reported": cached,
        "estimated_usd_at_uncached_rate": round(cost, 6),
        "estimated_usd_with_reported_cache": round(cache_adjusted_cost, 6),
        "pricing_verified_at": "2026-07-17",
        "pricing_source": (
            "https://platform.kimi.ai/docs/pricing/chat-k26"
            if provider.name == "kimi"
            else "https://developers.openai.com/api/docs/pricing"
        ),
    }


def _typed_evidence_metrics(
    selected: list[dict], hypotheses: list[dict], primary: list[dict], independent: list[dict]
) -> dict | None:
    typed_rows = [row for row in hypotheses if row.get("typed_evidence_intent")]
    if not typed_rows:
        return None
    selected_by_id = {str(row["question_id"]): row for row in selected}
    primary_by_id = {str(row["question_id"]): row for row in primary}
    independent_by_id = {str(row["question_id"]): row for row in independent}
    diagnostics = [row["typed_extraction"] for row in typed_rows if row.get("typed_extraction")]
    requested_sessions = sum(int(row["requested_session_count"]) for row in diagnostics)
    cache_hits = sum(int(row["cache_hit_count"]) for row in diagnostics)
    valid_claims = sum(int(row["valid_claim_count"]) for row in diagnostics)
    invalid_claims = sum(int(row["invalid_claim_count"]) for row in diagnostics)
    valid_by_type: dict[str, int] = {}
    invalid_by_type: dict[str, int] = {}
    invalid_by_reason: dict[str, int] = {}
    for diagnostic in diagnostics:
        for evidence_type, count in diagnostic.get("valid_by_evidence_type", {}).items():
            valid_by_type[evidence_type] = valid_by_type.get(evidence_type, 0) + int(count)
        for evidence_type, count in diagnostic.get("invalid_by_evidence_type", {}).items():
            invalid_by_type[evidence_type] = invalid_by_type.get(evidence_type, 0) + int(count)
        for reason, count in diagnostic.get("invalid_by_reason", {}).items():
            invalid_by_reason[reason] = invalid_by_reason.get(reason, 0) + int(count)
    resolved = [row for row in typed_rows if row.get("typed_evidence_status") == "resolved"]
    disagreement_ids: list[str] = []
    comparable_count = 0
    for row in resolved:
        question_id = str(row["question_id"])
        baseline = selected_by_id.get(question_id, {})
        if not all(
            key in baseline
            for key in ("baseline_primary_correct", "baseline_independent_correct")
        ):
            continue
        comparable_count += 1
        baseline_consensus = bool(baseline["baseline_primary_correct"]) and bool(
            baseline["baseline_independent_correct"]
        )
        typed_consensus = bool(
            primary_by_id[question_id]["autoeval_label"]["label"]
        ) and bool(independent_by_id[question_id]["autoeval_label"]["label"])
        if baseline_consensus != typed_consensus:
            disagreement_ids.append(question_id)
    return {
        "schema_hash": TYPED_EVIDENCE_SCHEMA_HASH,
        "eligible_question_count": len(typed_rows),
        "intent_counts": {
            intent: sum(row.get("typed_evidence_intent") == intent for row in typed_rows)
            for intent in sorted({str(row["typed_evidence_intent"]) for row in typed_rows})
        },
        "status_counts": {
            status: sum(row.get("typed_evidence_status") == status for row in typed_rows)
            for status in ("resolved", "needs_generation", "fallback")
        },
        "deterministic_answer_coverage": round(len(resolved) / len(typed_rows), 4),
        "extraction_failure_count": sum(bool(row.get("extraction_failed")) for row in diagnostics),
        "requested_session_count": requested_sessions,
        "cache_hit_count": cache_hits,
        "cache_hit_rate": round(cache_hits / requested_sessions, 4) if requested_sessions else None,
        "valid_claim_count": valid_claims,
        "invalid_claim_count": invalid_claims,
        "stored_citation_validity_rate": 1.0 if valid_claims else None,
        "claim_acceptance_rate": round(valid_claims / (valid_claims + invalid_claims), 4)
        if valid_claims + invalid_claims
        else None,
        "valid_by_evidence_type": valid_by_type,
        "invalid_by_evidence_type": invalid_by_type,
        "invalid_by_reason": invalid_by_reason,
        "reducer_disagreement_comparable_count": comparable_count,
        "reducer_disagreement_count": len(disagreement_ids),
        "reducer_disagreement_rate": round(len(disagreement_ids) / comparable_count, 4)
        if comparable_count
        else None,
        "reducer_disagreement_question_ids": disagreement_ids[:20],
    }


def _budget_accuracy_metrics(
    hypotheses: list[dict],
    primary: list[dict],
    independent: list[dict],
    *,
    budget: int,
) -> dict:
    primary_by_id = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in primary
    }
    independent_by_id = {
        str(row["question_id"]): bool(row["autoeval_label"]["label"])
        for row in independent
    }

    def billed_prompt_tokens(row: dict) -> int:
        attempts = row.get("reader_attempt_history") or []
        if attempts:
            return sum(
                int((attempt.get("usage") or {}).get("prompt_tokens") or 0)
                for attempt in attempts
            )
        return int(
            row.get("reader_billed_prompt_tokens")
            or row.get("reader_prompt_tokens")
            or 0
        )

    def groups(field: str, *, value_fn=None) -> dict:
        token_value = value_fn or (lambda row: int(row.get(field) or 0))
        output: dict[str, dict] = {}
        for label, over in (("over_budget", True), ("under_or_at_budget", False)):
            rows = [
                row
                for row in hypotheses
                if (token_value(row) > budget) is over
            ]
            question_ids = [str(row["question_id"]) for row in rows]
            primary_correct = sum(primary_by_id[item] for item in question_ids)
            independent_correct = sum(independent_by_id[item] for item in question_ids)
            count = len(rows)
            output[label] = {
                "question_count": count,
                "primary_correct_count": primary_correct,
                "primary_accuracy": round(primary_correct / count, 4) if count else None,
                "primary_accuracy_percent": round(primary_correct * 100 / count, 2) if count else None,
                "primary_wilson_95": _wilson_interval(primary_correct, count),
                "independent_correct_count": independent_correct,
                "independent_accuracy": round(independent_correct / count, 4) if count else None,
                "independent_accuracy_percent": round(independent_correct * 100 / count, 2) if count else None,
                "independent_wilson_95": _wilson_interval(independent_correct, count),
                "mean_final_reader_prompt_tokens": round(
                    statistics.fmean(int(row.get("reader_prompt_tokens") or 0) for row in rows),
                    2,
                ) if rows else None,
                "mean_grouping_tokens": round(
                    statistics.fmean(token_value(row) for row in rows), 2
                ) if rows else None,
                "question_ids": question_ids,
            }
        over_accuracy = output["over_budget"]["primary_accuracy"]
        under_accuracy = output["under_or_at_budget"]["primary_accuracy"]
        output["primary_accuracy_gap_over_minus_under"] = (
            round(over_accuracy - under_accuracy, 4)
            if over_accuracy is not None and under_accuracy is not None
            else None
        )
        return output

    return {
        "reader_token_budget": budget,
        "classification_note": (
            "prepack groups classify the complete-session prompt before compression; "
            "packed-estimate groups use the deterministic local estimator; actual groups "
            "use provider-reported final-attempt reader prompt tokens; all-attempt groups "
            "sum provider-reported prompt tokens across retries and therefore represent "
            "billed input per benchmark question."
        ),
        "prepack_complete_session_prompt": groups("prepack_prompt_tokens_estimate"),
        "packed_prompt_estimate": groups("packed_prompt_tokens_estimate"),
        "actual_reader_prompt": groups("reader_prompt_tokens"),
        "all_reader_attempts_billed": groups(
            "reader_billed_prompt_tokens", value_fn=billed_prompt_tokens
        ),
    }


def _holdout_gate_metrics(
    selected: list[dict],
    primary: list[dict],
    independent: list[dict],
    protocol: dict,
    hypotheses: list[dict] | None = None,
) -> dict | None:
    if not selected:
        return None
    stratum_key = (
        "holdout_stratum"
        if all("holdout_stratum" in row for row in selected)
        else "v2_holdout_stratum"
        if all("v2_holdout_stratum" in row for row in selected)
        else None
    )
    if stratum_key is None:
        return None
    primary_by_id = {str(row["question_id"]): row for row in primary}
    independent_by_id = {str(row["question_id"]): row for row in independent}
    outcomes: list[dict] = []
    for row in selected:
        question_id = str(row["question_id"])
        dual_correct = bool(primary_by_id[question_id]["autoeval_label"]["label"]) and bool(
            independent_by_id[question_id]["autoeval_label"]["label"]
        )
        outcomes.append({**row, "dual_judge_correct": dual_correct})

    controls = [
        row
        for row in outcomes
        if row.get("baseline_primary_correct")
        and row.get("baseline_independent_correct")
    ]
    recovery = [
        row
        for row in outcomes
        if not row.get("baseline_primary_correct")
        and not row.get("baseline_independent_correct")
    ]
    retained = sum(bool(row["dual_judge_correct"]) for row in controls)
    recovered = sum(bool(row["dual_judge_correct"]) for row in recovery)
    gates = protocol.get("pass_gates") or {}
    required_retained = int(gates.get("required_retained") or math.ceil(0.9 * len(controls)))
    required_recovered = int(gates.get("required_recovered") or math.ceil(0.3 * len(recovery)))
    strata: dict[str, dict] = {}
    for name in sorted({str(row[stratum_key]) for row in outcomes}):
        rows = [row for row in outcomes if str(row[stratum_key]) == name]
        correct = sum(bool(row["dual_judge_correct"]) for row in rows)
        strata[name] = {
            "correct": correct,
            "count": len(rows),
            "rate": round(correct / len(rows), 4),
        }
    minimum_control_retention = gates.get("minimum_control_stratum_retention")
    control_strata = {
        name: value for name, value in strata.items() if name.startswith("baseline_correct")
    }
    control_strata_gate = (
        all(value["rate"] >= float(minimum_control_retention) for value in control_strata.values())
        if minimum_control_retention is not None
        else True
    )
    agreement = statistics.fmean(
        bool(left["autoeval_label"]["label"])
        == bool(right["autoeval_label"]["label"])
        for left, right in zip(primary, independent, strict=True)
    )
    minimum_agreement = gates.get("minimum_judge_agreement")
    agreement_gate = (
        agreement >= float(minimum_agreement) if minimum_agreement is not None else True
    )

    efficiency: dict | None = None
    efficiency_gate = True
    if hypotheses and all("baseline_reader_prompt_tokens" in row for row in selected):
        baseline_prompt_tokens = sum(
            int(row["baseline_reader_prompt_tokens"]) for row in selected
        )
        current_prompt_tokens = sum(
            int(attempt.get("usage", {}).get("prompt_tokens") or 0)
            for row in hypotheses
            for attempt in (
                row.get("reader_attempt_history")
                or [{"usage": row.get("reader_usage") or {}}]
            )
        ) + sum(
            int(((row.get("typed_extraction") or {}).get("usage") or {}).get("prompt_tokens") or 0)
            for row in hypotheses
        )
        baseline_mean_latency = statistics.fmean(
            float(row["baseline_reader_wall_seconds"]) for row in selected
        )
        current_mean_latency = statistics.fmean(
            float(row.get("reader_wall_seconds") or 0.0) for row in hypotheses
        )
        prompt_ratio = current_prompt_tokens / baseline_prompt_tokens
        latency_ratio = current_mean_latency / baseline_mean_latency
        maximum_prompt_ratio = float(gates.get("maximum_prompt_token_ratio") or math.inf)
        maximum_latency_ratio = float(gates.get("maximum_mean_latency_ratio") or math.inf)
        efficiency_gate = (
            prompt_ratio <= maximum_prompt_ratio
            and latency_ratio <= maximum_latency_ratio
        )
        efficiency = {
            "baseline_prompt_tokens": baseline_prompt_tokens,
            "current_prompt_tokens": current_prompt_tokens,
            "prompt_token_ratio": round(prompt_ratio, 4),
            "maximum_prompt_token_ratio": maximum_prompt_ratio,
            "baseline_mean_latency_seconds": round(baseline_mean_latency, 4),
            "current_mean_latency_seconds": round(current_mean_latency, 4),
            "mean_latency_ratio": round(latency_ratio, 4),
            "maximum_mean_latency_ratio": maximum_latency_ratio,
            "gate_passed": efficiency_gate,
        }

    route_mismatches: list[str] = []
    if hypotheses:
        selected_by_id = {str(row["question_id"]): row for row in selected}
        route_mismatches = [
            str(row["question_id"])
            for row in hypotheses
            if selected_by_id[str(row["question_id"])].get("expected_reader_route")
            and row.get("reader_route")
            != selected_by_id[str(row["question_id"])]["expected_reader_route"]
        ]

    retention_gate = retained >= required_retained
    recovery_gate = recovered >= required_recovered
    promotion_gate = (
        retention_gate
        and recovery_gate
        and control_strata_gate
        and agreement_gate
        and efficiency_gate
        and not route_mismatches
    )
    return {
        "baseline_correct_retained": retained,
        "baseline_correct_count": len(controls),
        "retention_rate": round(retained / len(controls), 4),
        "required_retained": required_retained,
        "retention_gate_passed": retention_gate,
        "baseline_incorrect_recovered": recovered,
        "baseline_incorrect_count": len(recovery),
        "recovery_rate": round(recovered / len(recovery), 4),
        "required_recovered": required_recovered,
        "recovery_gate_passed": recovery_gate,
        "minimum_control_stratum_retention": minimum_control_retention,
        "control_strata_gate_passed": control_strata_gate,
        "judge_agreement": round(agreement, 4),
        "minimum_judge_agreement": minimum_agreement,
        "judge_agreement_gate_passed": agreement_gate,
        "efficiency": efficiency,
        "route_mismatch_question_ids": route_mismatches,
        "promotion_gate_passed": promotion_gate,
        "strata": strata,
    }


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    references_list = json.loads(args.dataset.read_text(encoding="utf-8"))
    references = {item["question_id"]: item for item in references_list}
    requested_ids = {str(item) for item in args.question_id}
    selected = (
        [
            row
            for row in retrieval["results"]
            if str(row["question_id"]) in requested_ids
        ]
        if requested_ids
        else retrieval["results"][: args.limit or None]
    )
    if args.context_packing == "claim-first-v1" and args.reader_token_budget <= 0:
        raise RuntimeError("claim-first-v1 requires --reader-token-budget")
    if not 0 < args.reader_budget_safety_factor <= 1:
        raise RuntimeError("--reader-budget-safety-factor must be greater than 0 and at most 1")
    if not selected:
        raise RuntimeError("The retrieval artifact contains no selected questions")
    missing_requested_ids = requested_ids - {
        str(item["question_id"]) for item in selected
    }
    if missing_requested_ids:
        raise RuntimeError(
            "The retrieval artifact is missing requested question IDs: "
            + ", ".join(sorted(missing_requested_ids))
        )
    selected_ids = [str(item["question_id"]) for item in selected]
    if len(selected_ids) != len(set(selected_ids)):
        raise RuntimeError("The retrieval artifact contains duplicate question IDs")
    missing_references = [question_id for question_id in selected_ids if question_id not in references]
    if missing_references:
        raise RuntimeError(
            f"The dataset is missing {len(missing_references)} retrieved question IDs"
        )
    reader = _provider(args.reader_provider, args.reader_model)
    primary_judge = _provider(args.primary_judge_provider, args.primary_judge_model)
    independent_judge = _provider(
        args.independent_judge_provider, args.independent_judge_model
    )

    stem = args.output.with_suffix("")
    manifest_path = stem.with_name(stem.name + ".manifest.json")
    manifest = _ensure_manifest(
        manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "dataset_sha256": _file_sha256(args.dataset),
            "retrieval_sha256": _file_sha256(args.retrieval),
            "selected_question_ids": selected_ids,
            "selected_question_ids_sha256": _fingerprint(selected_ids),
            "reader_protocol": _reader_protocol(args.reader_prompt),
            "typed_evidence_schema_hash": (
                TYPED_EVIDENCE_SCHEMA_HASH
                if args.reader_prompt == "typed-v1"
                else None
            ),
            "typed_extraction_max_tokens": (
                args.typed_extraction_max_tokens
                if args.reader_prompt == "typed-v1"
                else None
            ),
            "judge_protocol": JUDGE_PROTOCOL_VERSION,
            "reader": {"provider": reader.name, "model": reader.model},
            "primary_judge": {
                "provider": primary_judge.name,
                "model": primary_judge.model,
            },
            "independent_judge": {
                "provider": independent_judge.name,
                "model": independent_judge.model,
            },
            "max_context_chars": args.max_context_chars,
            "context_packing": args.context_packing,
            "reader_token_budget": args.reader_token_budget,
            "reader_budget_safety_factor": args.reader_budget_safety_factor,
            "max_answer_tokens": args.max_answer_tokens,
        },
    )
    reader_run_fingerprint = manifest["fingerprint"]
    hypotheses_path = stem.with_name(stem.name + ".hypotheses.jsonl")
    primary_path = stem.with_name(
        stem.name
        + (
            ".kimi-evaluated.jsonl"
            if primary_judge.name == "kimi" and independent_judge.name == "openai"
            else ".primary-evaluated.jsonl"
        )
    )
    independent_path = stem.with_name(
        stem.name
        + (
            ".openai-evaluated.jsonl"
            if primary_judge.name == "kimi" and independent_judge.name == "openai"
            else ".independent-evaluated.jsonl"
        )
    )
    hypotheses = _generate(
        args, reader, selected, references, hypotheses_path, reader_run_fingerprint
    )
    hypotheses_sha256 = _fingerprint(
        [(row["question_id"], row["hypothesis"]) for row in hypotheses]
    )
    primary_run_fingerprint = _fingerprint(
        [reader_run_fingerprint, hypotheses_sha256, primary_judge.name, primary_judge.model]
    )
    independent_run_fingerprint = _fingerprint(
        [reader_run_fingerprint, hypotheses_sha256, independent_judge.name, independent_judge.model]
    )
    primary = _judge(
        args,
        primary_judge,
        hypotheses,
        references,
        primary_path,
        primary_run_fingerprint,
    )
    independent = _judge(
        args,
        independent_judge,
        hypotheses,
        references,
        independent_path,
        independent_run_fingerprint,
    )

    primary_metrics = _metrics(primary, references)
    independent_metrics = _metrics(independent, references)
    primary_metrics["containment_answers_rejected_by_judge"] = primary_metrics.pop(
        "containment_answers_rejected_by_self_judge"
    )
    independent_metrics["containment_answers_rejected_by_judge"] = independent_metrics.pop(
        "containment_answers_rejected_by_self_judge"
    )
    primary_metrics["judge_protocol"] = primary[0]["autoeval_label"]["protocol"] if primary else None
    independent_metrics["judge_protocol"] = (
        independent[0]["autoeval_label"]["protocol"] if independent else None
    )
    pairs = list(zip(primary, independent, strict=True))
    agreement = [
        left["autoeval_label"]["label"] == right["autoeval_label"]["label"]
        for left, right in pairs
    ]
    primary_labels = [bool(row["autoeval_label"]["label"]) for row in primary]
    independent_labels = [bool(row["autoeval_label"]["label"]) for row in independent]
    reader_usage = _usage_attempts(hypotheses, kind="reader")
    extraction_usage = [
        row["typed_extraction"]["usage"]
        for row in hypotheses
        if row.get("typed_extraction") and row["typed_extraction"].get("usage")
    ]
    primary_usage = _usage_attempts(primary, kind="judge")
    independent_usage = _usage_attempts(independent, kind="judge")
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "question_count": len(selected),
        "run_fingerprint": reader_run_fingerprint,
        "dataset_sha256": manifest["dataset_sha256"],
        "retrieval_sha256": manifest["retrieval_sha256"],
        "retrieval_macro_recall_at_k": round(
            statistics.fmean(
                float(row["recall_at_k"])
                for row in selected
                if row.get("recall_at_k") is not None
            ),
            6,
        ),
        "retrieval_top_k": int((retrieval.get("protocol") or {}).get("top_k") or 10),
        "reader": {"provider": reader.name, "model": reader.model},
        "primary_judge": primary_metrics,
        "independent_judge": independent_metrics,
        "judge_agreement": round(statistics.fmean(agreement), 4) if agreement else None,
        "judge_cohen_kappa": _cohen_kappa(primary_labels, independent_labels),
        "judge_disagreement_question_ids": [
            left["question_id"]
            for left, right in pairs
            if left["autoeval_label"]["label"] != right["autoeval_label"]["label"]
        ],
        "usage_and_estimated_cost": {
            f"{reader.name}_typed_extraction": _provider_cost(reader, extraction_usage),
            f"{reader.name}_reader": _provider_cost(reader, reader_usage),
            f"{primary_judge.name}_primary_judge": _provider_cost(
                primary_judge, primary_usage
            ),
            f"{independent_judge.name}_independent_judge": _provider_cost(
                independent_judge, independent_usage
            ),
        },
        "max_context_chars": args.max_context_chars,
        "max_answer_tokens": args.max_answer_tokens,
        "context": {
            "packing": (
                CLAIM_PACKER_VERSION
                if args.context_packing == "claim-first-v1"
                else "rank-selected-complete-chronological-sessions-v2"
            ),
            "reader_token_budget": args.reader_token_budget,
            "reader_budget_safety_factor": args.reader_budget_safety_factor,
            "truncated_question_count": sum(
                bool(row.get("context_truncated")) for row in hypotheses
            ),
            "max_chars_used": max(int(row.get("context_chars") or 0) for row in hypotheses),
            "max_unbounded_chars": max(
                int(row.get("unbounded_context_chars") or 0) for row in hypotheses
            ),
            "mean_packed_prompt_tokens_estimate": round(
                statistics.fmean(
                    int(row.get("packed_prompt_tokens_estimate") or 0)
                    for row in hypotheses
                ),
                2,
            ),
            "mean_prepack_prompt_tokens_estimate": round(
                statistics.fmean(
                    int(row.get("prepack_prompt_tokens_estimate") or 0)
                    for row in hypotheses
                ),
                2,
            ),
        },
        "reader_length_finish_count": sum(
            row.get("reader_finish_reason") == "length" for row in hypotheses
        ),
        "reader_content_filter_count": sum(
            bool(row.get("reader_content_filtered")) for row in hypotheses
        ),
        "primary_judge_content_filter_count": sum(
            bool(row.get("judge_content_filtered")) for row in primary
        ),
        "independent_judge_content_filter_count": sum(
            bool(row.get("judge_content_filtered")) for row in independent
        ),
    }
    typed_metrics = _typed_evidence_metrics(selected, hypotheses, primary, independent)
    if typed_metrics is not None:
        report["typed_evidence"] = typed_metrics
    if args.reader_token_budget:
        report["budget_accuracy"] = _budget_accuracy_metrics(
            hypotheses,
            primary,
            independent,
            budget=args.reader_token_budget,
        )
    holdout_gates = _holdout_gate_metrics(
        selected,
        primary,
        independent,
        retrieval.get("protocol") or {},
        hypotheses,
    )
    if holdout_gates is not None:
        report["holdout_gates"] = holdout_gates
    for metrics in (report["primary_judge"], report["independent_judge"]):
        metrics["accuracy_wilson_95"] = _wilson_interval(
            int(metrics["correct_count"]), int(metrics["question_count"])
        )
    report["usage_and_estimated_cost"]["total_estimated_usd"] = round(
        sum(
            item["estimated_usd_at_uncached_rate"]
            for item in report["usage_and_estimated_cost"].values()
            if isinstance(item, dict)
        ),
        6,
    )
    report["usage_and_estimated_cost"]["total_estimated_usd_with_reported_cache"] = round(
        sum(
            item["estimated_usd_with_reported_cache"]
            for item in report["usage_and_estimated_cost"].values()
            if isinstance(item, dict)
            and "estimated_usd_with_reported_cache" in item
        ),
        6,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
