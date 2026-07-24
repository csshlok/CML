from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2PropositionPassResponse,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
    atomic_memory_v2_proposition_pass_json_schema,
    atomic_memory_v2_proposition_pass_prompt,
    compile_atomic_memory_v2_propositions,
    normalize_atomic_memory_v2,
)
from scripts.backend.prepare_atomic_extractor_training_data import (  # noqa: E402
    CorpusProvenance,
    TrainingCorpus,
    TrainingRecord,
    _canonical_json,
    _validate_session,
)


PROTOCOL = "openai-atomic-teacher-pilot-v1"
DEFAULT_INPUT = (
    REPO_ROOT
    / ".tmp/atomic-memory-training-sources/teacher-corpus-v1/source-sessions.jsonl"
)
DEFAULT_SOURCE_MANIFEST = (
    REPO_ROOT
    / ".tmp/atomic-memory-training-sources/teacher-corpus-v1/source-manifest.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / ".tmp/atomic-memory-training-sources/teacher-pilot-gpt56-sol-v1"
)
PRICES_PER_MILLION = {
    "gpt-5.6-sol": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a small, stratified OpenAI teacher-labeling pilot for atomic-memory "
            "evidence and proposition targets."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    parser.add_argument("--records-per-source", type=int, default=2)
    parser.add_argument("--selection-seed", type=int, default=20260723)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recipe_sha256(args: argparse.Namespace) -> str:
    recipe = {
        "protocol": PROTOCOL,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "selection_seed": args.selection_seed,
        "records_per_source": args.records_per_source,
        "max_output_tokens": args.max_output_tokens,
        "evidence_prompt_sha256": hashlib.sha256(
            atomic_memory_v2_evidence_pass_prompt(
                {"session_id": "recipe", "date": "", "turns": []}
            ).encode("utf-8")
        ).hexdigest(),
        "proposition_prompt_sha256": hashlib.sha256(
            atomic_memory_v2_proposition_pass_prompt(
                {"session_id": "recipe", "date": "", "turns": []}, []
            ).encode("utf-8")
        ).hexdigest(),
        "evidence_schema": atomic_memory_v2_evidence_pass_json_schema(),
        "proposition_schema": atomic_memory_v2_proposition_pass_json_schema(),
    }
    return hashlib.sha256(_canonical_json(recipe).encode("utf-8")).hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def select_stratified_records(
    rows: list[dict], *, per_source: int, seed: int
) -> list[dict]:
    if per_source < 1:
        raise ValueError("records_per_source_must_be_positive")
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["source_id"]), []).append(row)
    selected: list[dict] = []
    for source_id, source_rows in sorted(grouped.items()):
        ranked = sorted(
            source_rows,
            key=lambda row: hashlib.sha256(
                f"{seed}:{source_id}:{row['record_id']}".encode("utf-8")
            ).hexdigest(),
        )
        if len(ranked) < per_source:
            raise ValueError(
                f"source {source_id!r} has {len(ranked)} rows, needs {per_source}"
            )
        selected.extend(ranked[:per_source])
    return selected


def _strict_schema(value: object) -> object:
    """Convert Pydantic JSON Schema into OpenAI strict Structured Outputs form."""
    if isinstance(value, list):
        return [_strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {
        key: _strict_schema(item)
        for key, item in value.items()
        if key not in {"default", "title"}
    }
    if cleaned.get("type") == "object" or "properties" in cleaned:
        properties = cleaned.get("properties") or {}
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(properties)
    return cleaned


def _response_text(response: dict) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    texts: list[str] = []
    refusals: list[str] = []
    for item in response.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(str(content["text"]))
            if content.get("type") == "refusal" and content.get("refusal"):
                refusals.append(str(content["refusal"]))
    if refusals:
        raise RuntimeError("openai_refusal:" + " ".join(refusals)[:500])
    if not texts:
        raise ValueError("openai_response_has_no_output_text")
    return "".join(texts)


def _usage(response: dict) -> dict:
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": int(input_details.get("cached_tokens") or 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        "total_tokens": int(
            usage.get("total_tokens") or input_tokens + output_tokens
        ),
    }


def usage_cost_usd(model: str, usage: dict) -> float:
    if model not in PRICES_PER_MILLION:
        raise ValueError(f"no_frozen_price_for_model:{model}")
    prices = PRICES_PER_MILLION[model]
    cached = int(usage.get("cached_input_tokens") or 0)
    total_input = int(usage.get("input_tokens") or 0)
    uncached = max(0, total_input - cached)
    output = int(usage.get("output_tokens") or 0)
    return (
        uncached * prices["input"]
        + cached * prices["cached_input"]
        + output * prices["output"]
    ) / 1_000_000


def _post_response(
    *,
    model: str,
    prompt: str,
    schema_name: str,
    schema: dict,
    reasoning_effort: str,
    max_output_tokens: int,
    timeout: float,
    retries: int,
) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    body = {
        "model": model,
        "input": prompt,
        "reasoning": {"effort": reasoning_effort},
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": _strict_schema(schema),
            }
        },
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    request = Request(
        "https://api.openai.com/v1/responses",
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
            detail = exc.read().decode("utf-8", errors="replace")[:2_000]
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt >= retries:
                raise RuntimeError(
                    f"OpenAI returned HTTP {exc.code}: {detail}"
                ) from exc
        except (URLError, TimeoutError) as exc:
            if attempt >= retries:
                reason = getattr(exc, "reason", str(exc))
                raise RuntimeError(f"OpenAI request failed: {reason}") from exc
        time.sleep(min(8.0, 2.0**attempt))
    raise AssertionError("unreachable")


def _atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _canonical_citation(session: dict, citation: dict) -> tuple[dict, bool]:
    turns = list(session["turns"])
    excerpt = str(citation.get("excerpt") or "")
    turn_index = citation.get("turn_index")
    if not isinstance(turn_index, int) or not 0 <= turn_index < len(turns):
        raise ValueError("citation_turn_out_of_range")
    content = str(turns[turn_index].get("content") or "")
    start = content.find(excerpt)
    if not excerpt or start < 0:
        raise ValueError("citation_excerpt_not_exact")
    expected = {
        "turn_index": turn_index,
        "excerpt": excerpt,
        "source_turn_id": str(
            turns[turn_index].get("source_turn_id")
            if turns[turn_index].get("source_turn_id") is not None
            else turn_index
        ),
        "start_char": start,
        "end_char": start + len(excerpt),
    }
    return expected, citation != expected


def _canonicalize_evidence(
    session: dict, evidence: AtomicMemoryV2EvidencePassResponse
) -> tuple[AtomicMemoryV2EvidencePassResponse, int]:
    payload = evidence.model_dump(mode="json")
    repairs = 0
    for span in payload["spans"]:
        span["citation"], repaired = _canonical_citation(
            session, span["citation"]
        )
        repairs += int(repaired)
    return AtomicMemoryV2EvidencePassResponse.model_validate(payload), repairs


def _canonicalize_and_deduplicate_propositions(
    session: dict,
    propositions: AtomicMemoryV2PropositionPassResponse,
) -> tuple[AtomicMemoryV2PropositionPassResponse, int, int]:
    payload = propositions.model_dump(mode="json")
    repairs = 0
    deduplicated = 0
    seen_memories: set[str] = set()
    retained = []
    for proposition in payload["propositions"]:
        if proposition.get("citation") is not None:
            proposition["citation"], repaired = _canonical_citation(
                session, proposition["citation"]
            )
            repairs += int(repaired)
        memory_key = " ".join(str(proposition["memory_text"]).casefold().split())
        if memory_key in seen_memories:
            deduplicated += 1
            continue
        seen_memories.add(memory_key)
        retained.append(proposition)
    payload["propositions"] = retained
    return (
        AtomicMemoryV2PropositionPassResponse.model_validate(payload),
        repairs,
        deduplicated,
    )


def _assess_record(
    row: dict,
    record_result: dict,
) -> None:
    session = row["session"]
    evidence = AtomicMemoryV2EvidencePassResponse.model_validate(
        record_result["evidence"]["response"]
    )
    propositions = AtomicMemoryV2PropositionPassResponse.model_validate(
        record_result["propositions"]["response"]
    )
    evidence, evidence_repairs = _canonicalize_evidence(session, evidence)
    propositions, proposition_repairs, proposition_deduplications = (
        _canonicalize_and_deduplicate_propositions(session, propositions)
    )
    record_result["evidence"]["response"] = evidence.model_dump(mode="json")
    record_result["propositions"]["response"] = propositions.model_dump(mode="json")
    previous_normalization = record_result.get("mechanical_normalization") or {}
    record_result["mechanical_normalization"] = {
        "evidence_citation_repairs": max(
            evidence_repairs,
            int(previous_normalization.get("evidence_citation_repairs") or 0),
        ),
        "proposition_citation_repairs": max(
            proposition_repairs,
            int(previous_normalization.get("proposition_citation_repairs") or 0),
        ),
        "exact_duplicate_propositions_removed": max(
            proposition_deduplications,
            int(
                previous_normalization.get(
                    "exact_duplicate_propositions_removed"
                )
                or 0
            ),
        ),
    }
    training_record = TrainingRecord(
        record_id=row["record_id"],
        split_group=f"{row['source_id']}:{row['source_row_id']}",
        session=session,
        evidence_target=evidence,
        proposition_target=propositions,
    )
    quality_errors = _validate_session(training_record)
    compilation = _validate_compilation(session, evidence, propositions)
    record_result["quality_errors"] = quality_errors
    record_result["compilation"] = compilation
    if quality_errors or compilation["compiler_rejected_count"]:
        record_result["status"] = "review_required"
    else:
        record_result["status"] = "accepted"
    record_result.pop("error", None)


def _reassess_cached_records(
    checkpoint: dict, selected: list[dict]
) -> None:
    row_by_id = {row["record_id"]: row for row in selected}
    for record_id, result in (checkpoint.get("records") or {}).items():
        if record_id not in row_by_id:
            continue
        if result.get("evidence") and result.get("propositions"):
            try:
                _assess_record(row_by_id[record_id], result)
            except (ValueError, ValidationError) as exc:
                result["status"] = "failed"
                result["error"] = str(exc)[:2_000]


def _empty_checkpoint(args: argparse.Namespace, selected: list[dict]) -> dict:
    return {
        "protocol": PROTOCOL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "recipe_sha256": _recipe_sha256(args),
        "input_sha256": _sha256_file(args.input),
        "source_manifest_sha256": _sha256_file(args.source_manifest),
        "selected_record_ids": [row["record_id"] for row in selected],
        "records": {},
    }


def _load_or_create_checkpoint(
    path: Path, args: argparse.Namespace, selected: list[dict]
) -> dict:
    expected = _empty_checkpoint(args, selected)
    if not path.exists():
        return expected
    existing = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "protocol",
        "model",
        "reasoning_effort",
        "recipe_sha256",
        "input_sha256",
        "source_manifest_sha256",
        "selected_record_ids",
    ):
        if existing.get(key) != expected.get(key):
            raise ValueError(f"checkpoint_mismatch:{key}")
    return existing


def _checkpoint_usage(checkpoint: dict) -> tuple[dict, float]:
    totals: Counter = Counter()
    for record in (checkpoint.get("records") or {}).values():
        for pass_name in ("evidence", "propositions"):
            totals.update((record.get(pass_name) or {}).get("usage") or {})
    usage = dict(totals)
    return usage, usage_cost_usd(str(checkpoint["model"]), usage)


def _call_and_parse(
    *,
    args: argparse.Namespace,
    prompt: str,
    schema_name: str,
    schema: dict,
    model_type,
) -> tuple[object, dict]:
    started = time.perf_counter()
    response = _post_response(
        model=args.model,
        prompt=prompt,
        schema_name=schema_name,
        schema=schema,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout,
        retries=args.retries,
    )
    response_text = _response_text(response)
    parsed = model_type.model_validate_json(response_text)
    record = {
        "response_id": str(response.get("id") or ""),
        "status": str(response.get("status") or ""),
        "usage": _usage(response),
        "wall_seconds": round(time.perf_counter() - started, 4),
        "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        "response": parsed.model_dump(mode="json"),
    }
    return parsed, record


def _validate_compilation(
    session: dict,
    evidence: AtomicMemoryV2EvidencePassResponse,
    propositions: AtomicMemoryV2PropositionPassResponse,
) -> dict:
    compiled = compile_atomic_memory_v2_propositions(
        session, propositions, evidence.spans
    )
    normalized = normalize_atomic_memory_v2(
        session,
        compiled,
        processed_turn_indices=range(len(session["turns"])),
        extraction_complete=True,
        output_truncated=False,
    )
    return {
        "entity_count": len(normalized.entities),
        "event_count": len(normalized.events),
        "relation_count": len(normalized.relations),
        "table_cell_count": len(normalized.table_cells),
        "compiler_rejected_count": normalized.coverage.rejected_candidate_count,
        "invalid_by_reason": normalized.invalid_by_reason,
    }


def _pilot_corpus(
    args: argparse.Namespace, checkpoint: dict, selected: list[dict], cost: float
) -> dict:
    records: list[TrainingRecord] = []
    by_id = checkpoint["records"]
    for row in selected:
        result = by_id.get(row["record_id"]) or {}
        if result.get("status") != "accepted":
            continue
        records.append(
            TrainingRecord(
                record_id=row["record_id"],
                split_group=f"{row['source_id']}:{row['source_row_id']}",
                session=row["session"],
                evidence_target=AtomicMemoryV2EvidencePassResponse.model_validate(
                    result["evidence"]["response"]
                ),
                proposition_target=AtomicMemoryV2PropositionPassResponse.model_validate(
                    result["propositions"]["response"]
                ),
            )
        )
    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    provenance = CorpusProvenance(
        source_name="licensed-hugging-face-conversation-teacher-pilot",
        source_version=str(source_manifest["output"]["sha256"]),
        license="CC-BY-4.0 and Apache-2.0; per-record source license retained",
        teacher_model=args.model,
        teacher_provider="OpenAI Responses API",
        created_at=str(checkpoint["created_at"]),
        paid_cost_usd=round(cost, 8),
        source_uri="https://huggingface.co/datasets",
        generation_recipe_sha256=_recipe_sha256(args),
    )
    return TrainingCorpus(
        corpus_version="atomic-extractor-openai-teacher-pilot-v1",
        evaluation_role="training",
        provenance=provenance,
        records=records,
    ).model_dump(mode="json")


def main() -> int:
    args = parse_args()
    if args.model not in PRICES_PER_MILLION:
        raise ValueError(f"model_price_must_be_frozen:{args.model}")
    if args.max_cost_usd <= 0 or args.max_cost_usd > 10:
        raise ValueError("pilot_max_cost_usd_must_be_above_zero_and_at_most_10")
    if args.max_output_tokens < 1024 or args.max_output_tokens > 8192:
        raise ValueError("pilot_max_output_tokens_must_be_between_1024_and_8192")
    if not args.input.is_file() or not args.source_manifest.is_file():
        raise FileNotFoundError("teacher source corpus or manifest is missing")

    selected = select_stratified_records(
        _load_jsonl(args.input),
        per_source=args.records_per_source,
        seed=args.selection_seed,
    )
    maximum_calls = len(selected) * 2
    maximum_output_cost = (
        maximum_calls
        * args.max_output_tokens
        * PRICES_PER_MILLION[args.model]["output"]
        / 1_000_000
    )
    preflight = {
        "protocol": PROTOCOL,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "record_count": len(selected),
        "maximum_calls": maximum_calls,
        "max_cost_usd": args.max_cost_usd,
        "maximum_output_cost_usd": round(maximum_output_cost, 6),
        "selected": [
            {"record_id": row["record_id"], "source_id": row["source_id"]}
            for row in selected
        ],
    }
    if maximum_output_cost >= args.max_cost_usd:
        raise ValueError("configured_output_ceiling_alone_exceeds_cost_cap")
    if args.dry_run:
        print(json.dumps(preflight, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "checkpoint.json"
    checkpoint = _load_or_create_checkpoint(checkpoint_path, args, selected)
    checkpoint.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    _reassess_cached_records(checkpoint, selected)
    _atomic_write_json(checkpoint_path, checkpoint)
    _, current_cost = _checkpoint_usage(checkpoint)
    if current_cost >= args.max_cost_usd:
        raise RuntimeError("pilot_cost_cap_already_reached")

    for row in selected:
        record_id = row["record_id"]
        existing = checkpoint["records"].get(record_id) or {}
        if existing.get("status") in {"accepted", "review_required"}:
            continue
        session = row["session"]
        record_result = {
            "record_id": record_id,
            "source_id": row["source_id"],
            "source_row_id": row["source_row_id"],
            "source_license": row["source_license"],
            "status": "running",
        }
        checkpoint["records"][record_id] = record_result
        _atomic_write_json(checkpoint_path, checkpoint)
        try:
            evidence, evidence_record = _call_and_parse(
                args=args,
                prompt=atomic_memory_v2_evidence_pass_prompt(session),
                schema_name="atomic_memory_evidence",
                schema=atomic_memory_v2_evidence_pass_json_schema(),
                model_type=AtomicMemoryV2EvidencePassResponse,
            )
            if evidence.session_id != session["session_id"]:
                raise ValueError("evidence_session_id_mismatch")
            record_result["evidence"] = evidence_record
            checkpoint["records"][record_id] = record_result
            _atomic_write_json(checkpoint_path, checkpoint)
            _, current_cost = _checkpoint_usage(checkpoint)
            if current_cost >= args.max_cost_usd:
                raise RuntimeError("pilot_cost_cap_reached_after_evidence_pass")

            propositions, proposition_record = _call_and_parse(
                args=args,
                prompt=atomic_memory_v2_proposition_pass_prompt(
                    session, evidence.spans
                ),
                schema_name="atomic_memory_propositions",
                schema=atomic_memory_v2_proposition_pass_json_schema(),
                model_type=AtomicMemoryV2PropositionPassResponse,
            )
            if propositions.session_id != session["session_id"]:
                raise ValueError("proposition_session_id_mismatch")
            record_result["propositions"] = proposition_record
            _assess_record(row, record_result)
        except (RuntimeError, ValueError, ValidationError) as exc:
            record_result["status"] = "failed"
            record_result["error"] = str(exc)[:2_000]
            checkpoint["records"][record_id] = record_result
            _atomic_write_json(checkpoint_path, checkpoint)
            raise
        checkpoint["records"][record_id] = record_result
        _atomic_write_json(checkpoint_path, checkpoint)
        _, current_cost = _checkpoint_usage(checkpoint)
        if current_cost >= args.max_cost_usd:
            raise RuntimeError("pilot_cost_cap_reached")

    usage, current_cost = _checkpoint_usage(checkpoint)
    corpus = _pilot_corpus(args, checkpoint, selected, current_cost)
    corpus_path = args.output_dir / "teacher-labelled-pilot.json"
    _atomic_write_json(corpus_path, corpus)
    status_counts = Counter(
        record.get("status")
        for record in (checkpoint.get("records") or {}).values()
    )
    source_counts = Counter(
        record.get("source_id")
        for record in (checkpoint.get("records") or {}).values()
        if record.get("status") == "accepted"
    )
    accepted = [
        record
        for record in (checkpoint.get("records") or {}).values()
        if record.get("status") == "accepted"
    ]
    assessed = [
        record
        for record in (checkpoint.get("records") or {}).values()
        if record.get("status") in {"accepted", "review_required"}
    ]
    completed_count = status_counts["accepted"] + status_counts["review_required"]
    summary = {
        **preflight,
        "status": (
            "completed"
            if status_counts["accepted"] == len(selected)
            else "completed_with_review_items"
            if completed_count == len(selected)
            else "failed"
        ),
        "status_counts": dict(status_counts),
        "accepted_by_source": dict(source_counts),
        "usage": usage,
        "actual_cost_usd": round(current_cost, 8),
        "evidence_span_count": sum(
            len(record["evidence"]["response"]["spans"]) for record in accepted
        ),
        "proposition_count": sum(
            len(record["propositions"]["response"]["propositions"])
            for record in accepted
        ),
        "compiler_rejected_count": sum(
            int(record["compilation"]["compiler_rejected_count"])
            for record in assessed
        ),
        "training_safe_compiler_rejected_count": sum(
            int(record["compilation"]["compiler_rejected_count"])
            for record in accepted
        ),
        "mechanical_normalization": {
            "evidence_citation_repairs": sum(
                int(
                    record.get("mechanical_normalization", {}).get(
                        "evidence_citation_repairs", 0
                    )
                )
                for record in assessed
            ),
            "proposition_citation_repairs": sum(
                int(
                    record.get("mechanical_normalization", {}).get(
                        "proposition_citation_repairs", 0
                    )
                )
                for record in assessed
            ),
            "exact_duplicate_propositions_removed": sum(
                int(
                    record.get("mechanical_normalization", {}).get(
                        "exact_duplicate_propositions_removed", 0
                    )
                )
                for record in assessed
            ),
        },
        "review_required_count": status_counts["review_required"],
        "training_safe_record_count": len(accepted),
        "training_safe_rate": round(len(accepted) / len(selected), 6),
        "review_items": [
            {
                "record_id": record["record_id"],
                "quality_errors": record.get("quality_errors") or [],
                "compiler_rejected_count": int(
                    record.get("compilation", {}).get(
                        "compiler_rejected_count", 0
                    )
                ),
                "invalid_by_reason": record.get("compilation", {}).get(
                    "invalid_by_reason", {}
                ),
            }
            for record in assessed
            if record.get("status") == "review_required"
        ],
        "input_sha256": _sha256_file(args.input),
        "source_manifest_sha256": _sha256_file(args.source_manifest),
        "recipe_sha256": _recipe_sha256(args),
        "checkpoint_sha256": _sha256_file(checkpoint_path),
        "corpus": {
            "path": str(corpus_path),
            "sha256": _sha256_file(corpus_path),
            "record_count": len(corpus["records"]),
        },
        "human_review_required": True,
    }
    _atomic_write_json(args.output_dir / "pilot-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"].startswith("completed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
