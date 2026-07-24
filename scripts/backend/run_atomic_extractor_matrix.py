from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2EntityPassResponse,
    AtomicMemoryV2EventPassResponse,
    AtomicMemoryV2PropositionPassResponse,
    AtomicMemoryV2RelationTablePassResponse,
    AtomicMemoryV2Response,
    AtomicMemoryV2SessionCandidate,
    atomic_memory_v2_deterministic_turn_indices,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
    atomic_memory_v2_entity_pass_json_schema,
    atomic_memory_v2_entity_pass_prompt,
    atomic_memory_v2_event_pass_json_schema,
    atomic_memory_v2_event_pass_prompt,
    atomic_memory_v2_json_schema,
    atomic_memory_v2_prompt,
    atomic_memory_v2_proposition_pass_json_schema,
    atomic_memory_v2_proposition_pass_prompt,
    atomic_memory_v2_relation_table_pass_json_schema,
    atomic_memory_v2_relation_table_pass_prompt,
    compile_atomic_memory_v2_evidence,
    compile_atomic_memory_v2_propositions,
    normalize_atomic_memory_v2,
    semantic_signatures,
)


DEFAULT_FIXTURES = REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_extraction.json"
DEFAULT_GATES = REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_gates.json"
RUNNER_PROTOCOL = "atomic-memory-v2-extractor-matrix-v11-atomic-memory-text"


@dataclass(frozen=True)
class CandidateSpec:
    label: str
    model: str
    base_url: str


def parse_candidate(value: str) -> CandidateSpec:
    parts = value.split("|", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "candidate must be LABEL|MODEL|LOOPBACK_BASE_URL"
        )
    label, model, base_url = (part.strip() for part in parts)
    hostname = (urlparse(base_url).hostname or "").casefold()
    if hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise argparse.ArgumentTypeError("candidate endpoint must be loopback-only")
    return CandidateSpec(label=label, model=model, base_url=base_url.rstrip("/"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen Atomic Memory v2 extraction suite on local GPU models."
    )
    parser.add_argument(
        "--candidate",
        action="append",
        type=parse_candidate,
        required=True,
        help="Repeat LABEL|MODEL|LOOPBACK_BASE_URL for every candidate.",
    )
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/atomic-memory-v2-extractor-matrix"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=2_048)
    parser.add_argument("--max-pass-attempts", type=int, default=2)
    parser.add_argument(
        "--strategy",
        choices=("monolithic", "decomposed", "evidence", "propositions"),
        default="monolithic",
    )
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def load_fixture_bundle(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = payload.get("fixtures")
    minimum_count = int(payload.get("minimum_fixture_count") or 30)
    if minimum_count < 1:
        raise ValueError("atomic_v2_minimum_fixture_count_must_be_positive")
    if not isinstance(fixtures, list) or len(fixtures) < minimum_count:
        raise ValueError(
            f"atomic_v2_fixture_bundle_requires_at_least_{minimum_count}_fixtures"
        )
    identifiers = [str(item.get("id") or "") for item in fixtures]
    if any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("atomic_v2_fixture_ids_must_be_unique")
    for fixture in fixtures:
        session = fixture.get("session") or {}
        if not session.get("session_id") or not isinstance(session.get("turns"), list):
            raise ValueError(f"invalid fixture session: {fixture.get('id')}")
        if any(
            str(turn.get("role") or "") not in {"user", "assistant", "tool"}
            for turn in session["turns"]
        ):
            raise ValueError(f"invalid fixture source role: {fixture.get('id')}")
        if not isinstance(fixture.get("required"), list) or not isinstance(fixture.get("forbidden"), list):
            raise ValueError(f"invalid fixture signatures: {fixture.get('id')}")
        reference_memories = fixture.get("reference_memories")
        if reference_memories is not None and (
            not isinstance(reference_memories, list)
            or any(not str(item).strip() for item in reference_memories)
        ):
            raise ValueError(f"invalid reference memories: {fixture.get('id')}")
    return payload


def load_gate_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    thresholds = payload.get("thresholds")
    if not payload.get("gate_version") or not isinstance(thresholds, dict):
        raise ValueError("invalid_atomic_v2_gate_manifest")
    return payload


def cuda_preflight() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU extraction fallback is disabled")
    device = torch.device("cuda:0")
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    left = torch.randn((256, 256), device=device)
    right = torch.randn((256, 256), device=device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    value = left @ right
    torch.cuda.synchronize(device)
    return {
        "cuda_ready": True,
        "device": torch.cuda.get_device_name(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "free_mib": free_bytes // 1024**2,
        "total_mib": total_bytes // 1024**2,
        "smoke_seconds": round(time.perf_counter() - started, 6),
        "smoke_value": float(value[0, 0]),
        "cpu_fallback_allowed": False,
    }


class NvidiaMemorySampler:
    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "NvidiaMemorySampler":
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def peak_mib(self) -> int:
        return max(self.samples, default=0)

    def _sample_loop(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--id=0",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=creationflags,
                )
                values = [
                    int(line.strip())
                    for line in result.stdout.splitlines()
                    if line.strip().isdigit()
                ]
                if values:
                    self.samples.append(values[0])
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            self._stop.wait(self.interval_seconds)


def _post_chat(
    candidate: CandidateSpec,
    prompt: str,
    *,
    timeout: float,
    max_tokens: int,
    response_schema: dict,
) -> dict:
    payload = {
        "model": candidate.model,
        "messages": [
            {
                "role": "system",
                "content": "Compile cited conversational memory into strict JSON. Do not think aloud.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_object",
            "schema": response_schema,
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = Request(
        f"{candidate.base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_json_object(text: str) -> dict:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```json").removeprefix("```")
        candidate = candidate.removesuffix("```").strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(value, dict):
        raise ValueError("response_root_not_object")
    return value


def evaluate_fixture_response(
    fixture: dict,
    *,
    response_text: str,
    finish_reason: str | None,
    wall_seconds: float,
    peak_gpu_memory_mib: int,
) -> dict:
    required = set(map(str, fixture["required"]))
    forbidden = set(map(str, fixture["forbidden"]))
    session = fixture["session"]
    source_chars = sum(len(str(turn.get("content") or "")) for turn in session["turns"])
    source_tokens_estimate = max(1, math.ceil(source_chars / 4))
    base = {
        "fixture_id": fixture["id"],
        "critical": bool(fixture.get("critical")),
        "wall_seconds": round(wall_seconds, 6),
        "source_tokens_estimate": source_tokens_estimate,
        # A one-second fixed generation cost on a ten-token fixture must not be
        # reported as 100 seconds/1K. Normalize long sources while treating every
        # short fixture as one minimum 1K-token scheduling window.
        "seconds_per_1000_source_tokens": round(
            wall_seconds / max(1.0, source_tokens_estimate / 1000.0), 6
        ),
        "peak_gpu_memory_mib": int(peak_gpu_memory_mib),
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "schema_compliant": False,
        "candidate_item_count": 0,
        "accepted_item_count": 0,
        "citation_invalid_count": 0,
        "required_count": len(required),
        "required_hit_count": 0,
        "missing_required": sorted(required),
        "forbidden_hits": [],
        "false_completed_action_hits": [],
        "complete_pass": False,
        "error": None,
    }
    try:
        response = AtomicMemoryV2Response.model_validate(_parse_json_object(response_text))
        base["schema_compliant"] = True
        matches = [item for item in response.sessions if item.session_id == session["session_id"]]
        if len(response.sessions) != 1 or len(matches) != 1:
            raise ValueError("response_requires_exactly_one_matching_session")
        candidate = matches[0]
        candidate_count = (
            len(candidate.entities)
            + len(candidate.events)
            + len(candidate.relations)
            + len(candidate.table_cells)
        )
        normalized = normalize_atomic_memory_v2(
            session,
            candidate,
            processed_turn_indices=range(len(session["turns"])),
            extraction_complete=finish_reason != "length",
            output_truncated=finish_reason == "length",
        )
        signatures = semantic_signatures(normalized)
        hits = required & signatures
        forbidden_hits = forbidden & signatures
        citation_invalid = sum(
            count
            for reason, count in normalized.invalid_by_reason.items()
            if reason.startswith("citation_") or reason == "entity_surface_not_in_citation"
        )
        rejected = sum(normalized.invalid_by_reason.values())
        base.update(
            {
                "candidate_item_count": candidate_count,
                "accepted_item_count": max(0, candidate_count - rejected),
                "citation_invalid_count": citation_invalid,
                "required_hit_count": len(hits),
                "missing_required": sorted(required - hits),
                "forbidden_hits": sorted(forbidden_hits),
                "false_completed_action_hits": sorted(
                    item for item in forbidden_hits if "|completed" in item
                ),
                "invalid_by_reason": normalized.invalid_by_reason,
                "semantic_signatures": sorted(signatures),
            }
        )
        base["complete_pass"] = bool(
            not base["truncated"]
            and not base["missing_required"]
            and not base["forbidden_hits"]
            and not normalized.invalid_by_reason
        )
    except (ValueError, TypeError) as exc:
        base["error"] = f"{type(exc).__name__}:{str(exc)[:300]}"
    return base


def compose_decomposed_candidate(
    fixture: dict,
    *,
    entity_response_text: str,
    event_response_text: str,
    relation_table_response_text: str,
) -> AtomicMemoryV2SessionCandidate:
    session_id = str(fixture["session"]["session_id"])
    entities = AtomicMemoryV2EntityPassResponse.model_validate(
        _parse_json_object(entity_response_text)
    )
    events = AtomicMemoryV2EventPassResponse.model_validate(
        _parse_json_object(event_response_text)
    )
    relations = AtomicMemoryV2RelationTablePassResponse.model_validate(
        _parse_json_object(relation_table_response_text)
    )
    if {entities.session_id, events.session_id, relations.session_id} != {session_id}:
        raise ValueError("decomposed_pass_session_mismatch")
    return AtomicMemoryV2SessionCandidate(
        session_id=session_id,
        entities=entities.entities,
        events=events.events,
        relations=relations.relations,
        table_cells=relations.table_cells,
    )


def evaluate_decomposed_fixture_response(
    fixture: dict,
    *,
    passes: dict[str, dict],
    wall_seconds: float,
    peak_gpu_memory_mib: int,
) -> dict:
    finish_reasons = {
        name: str(record.get("finish_reason") or "")
        for name, record in passes.items()
    }
    truncated = any(reason == "length" for reason in finish_reasons.values())
    session_id = str(fixture["session"]["session_id"])
    pass_errors: dict[str, str] = {}

    def parse_pass(name: str, model_type: type[BaseModel]) -> BaseModel | None:
        try:
            parsed = model_type.model_validate(
                _parse_json_object(str(passes[name]["response_text"]))
            )
            if parsed.session_id != session_id:
                raise ValueError("decomposed_pass_session_mismatch")
            return parsed
        except (ValueError, TypeError, KeyError) as exc:
            pass_errors[name] = f"{type(exc).__name__}:{str(exc)[:300]}"
            return None

    entity_pass = parse_pass("entities", AtomicMemoryV2EntityPassResponse)
    event_pass = parse_pass("events", AtomicMemoryV2EventPassResponse)
    relation_pass = parse_pass(
        "relations_tables", AtomicMemoryV2RelationTablePassResponse
    )
    candidate = AtomicMemoryV2SessionCandidate(
        session_id=session_id,
        entities=entity_pass.entities if entity_pass is not None else [],
        events=event_pass.events if event_pass is not None else [],
        relations=relation_pass.relations if relation_pass is not None else [],
        table_cells=relation_pass.table_cells if relation_pass is not None else [],
    )
    combined = AtomicMemoryV2Response(sessions=[candidate]).model_dump_json()
    result = evaluate_fixture_response(
        fixture,
        response_text=combined,
        finish_reason="length" if truncated else "stop",
        wall_seconds=wall_seconds,
        peak_gpu_memory_mib=peak_gpu_memory_mib,
    )
    if pass_errors:
        result["schema_compliant"] = False
        result["complete_pass"] = False
        result["error"] = "decomposed_pass_errors:" + json.dumps(
            pass_errors, sort_keys=True, separators=(",", ":")
        )
    result["strategy"] = "decomposed"
    result["pass_errors"] = pass_errors
    result["pass_finish_reasons"] = finish_reasons
    result["pass_wall_seconds"] = {
        name: float(record.get("wall_seconds") or 0.0)
        for name, record in passes.items()
    }
    return result


def evaluate_proposition_fixture_response(
    fixture: dict,
    *,
    passes: dict[str, dict],
    wall_seconds: float,
    peak_gpu_memory_mib: int,
) -> dict:
    session_id = str(fixture["session"]["session_id"])
    finish_reasons = {
        name: str(record.get("finish_reason") or "")
        for name, record in passes.items()
    }
    truncated = any(reason == "length" for reason in finish_reasons.values())
    pass_errors: dict[str, str] = {}
    evidence: AtomicMemoryV2EvidencePassResponse | None = None
    proposition_response: AtomicMemoryV2PropositionPassResponse | None = None

    try:
        evidence = AtomicMemoryV2EvidencePassResponse.model_validate(
            _parse_json_object(str(passes["evidence"]["response_text"]))
        )
        if evidence.session_id != session_id:
            raise ValueError("evidence_pass_session_mismatch")
    except (ValueError, TypeError, KeyError) as exc:
        pass_errors["evidence"] = f"{type(exc).__name__}:{str(exc)[:300]}"

    try:
        proposition_response = AtomicMemoryV2PropositionPassResponse.model_validate(
            _parse_json_object(str(passes["propositions"]["response_text"]))
        )
        candidate = compile_atomic_memory_v2_propositions(
            fixture["session"],
            proposition_response,
            evidence.spans if evidence is not None else (),
        )
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        pass_errors["propositions"] = f"{type(exc).__name__}:{str(exc)[:300]}"
        candidate = compile_atomic_memory_v2_propositions(
            fixture["session"],
            AtomicMemoryV2PropositionPassResponse(
                session_id=session_id, propositions=[]
            ),
        )

    combined = AtomicMemoryV2Response(sessions=[candidate]).model_dump_json()
    result = evaluate_fixture_response(
        fixture,
        response_text=combined,
        finish_reason="length" if truncated else "stop",
        wall_seconds=wall_seconds,
        peak_gpu_memory_mib=peak_gpu_memory_mib,
    )
    if pass_errors:
        result["schema_compliant"] = False
        result["complete_pass"] = False
        result["error"] = "proposition_pass_errors:" + json.dumps(
            pass_errors, sort_keys=True, separators=(",", ":")
        )
    result["strategy"] = "propositions"
    result["pass_errors"] = pass_errors
    result["pass_finish_reasons"] = finish_reasons
    result["pass_wall_seconds"] = {
        name: float(record.get("wall_seconds") or 0.0)
        for name, record in passes.items()
    }
    memory_fact_count = len(evidence.spans) if evidence is not None else 0
    proposition_count = (
        len(proposition_response.propositions)
        if proposition_response is not None
        else 0
    )
    result["memory_fact_count"] = memory_fact_count
    result["evidence_memories"] = (
        [
            {
                "span_id": span.span_id,
                "memory_text": span.memory_text,
                "attributed_to": span.attributed_to,
                "evidence_kinds": span.evidence_kinds,
                "confidence": span.confidence,
                "citation": span.citation.model_dump(mode="json"),
            }
            for span in evidence.spans
        ]
        if evidence is not None
        else []
    )
    accepted_evidence_memories: list[dict] = []
    production_evidence_invalid: dict[str, int] = {}
    if evidence is not None:
        production_extraction, production_evidence_invalid = (
            compile_atomic_memory_v2_evidence(fixture["session"], evidence)
        )
        accepted_evidence_memories = [
            {
                "fact_id": fact.fact_id,
                "memory_text": fact.object_text,
                "attributed_to": fact.subject,
                "evidence_kinds": fact.qualifiers.get("evidence_kinds", "").split(","),
                "confidence": fact.confidence,
                "citation": {
                    "turn_index": fact.citation.turn_index,
                    "excerpt": fact.citation.excerpt,
                    "speaker": fact.citation.speaker,
                },
            }
            for fact in production_extraction.facts
        ]
    result["accepted_evidence_memories"] = accepted_evidence_memories
    result["production_evidence_invalid_by_reason"] = production_evidence_invalid
    evidence_by_id = (
        {span.span_id: span for span in evidence.spans}
        if evidence is not None
        else {}
    )
    result["proposition_memories"] = (
        [
            {
                "proposition_id": proposition.proposition_id,
                "memory_text": proposition.memory_text,
                "proposition_kind": proposition.proposition_kind,
                "predicate": proposition.predicate,
                "modality": proposition.modality,
                "confidence": proposition.confidence,
                "citation": (
                    proposition.citation.model_dump(mode="json")
                    if proposition.citation is not None
                    else evidence_by_id[proposition.evidence_span_id].citation.model_dump(
                        mode="json"
                    )
                ),
            }
            for proposition in proposition_response.propositions
            if proposition.citation is not None
            or proposition.evidence_span_id in evidence_by_id
        ]
        if proposition_response is not None
        else []
    )
    result["reference_memories"] = list(fixture.get("reference_memories") or [])
    result["proposition_count"] = proposition_count
    result["memory_to_proposition_ratio"] = (
        proposition_count / memory_fact_count if memory_fact_count else 0.0
    )
    return result


def evaluate_evidence_fixture_response(
    fixture: dict,
    *,
    passes: dict[str, dict],
    wall_seconds: float,
    peak_gpu_memory_mib: int,
) -> dict:
    """Evaluate exactly the one-pass representation used by production v2."""
    session_id = str(fixture["session"]["session_id"])
    evidence_record = passes["evidence"]
    finish_reason = str(evidence_record.get("finish_reason") or "")
    source_chars = sum(
        len(str(turn.get("content") or ""))
        for turn in fixture["session"]["turns"]
    )
    source_tokens_estimate = max(1, math.ceil(source_chars / 4))
    result = {
        "fixture_id": fixture["id"],
        "critical": bool(fixture.get("critical")),
        "strategy": "evidence",
        "wall_seconds": round(wall_seconds, 6),
        "source_tokens_estimate": source_tokens_estimate,
        "seconds_per_1000_source_tokens": round(
            wall_seconds / max(1.0, source_tokens_estimate / 1000.0),
            6,
        ),
        "peak_gpu_memory_mib": int(peak_gpu_memory_mib),
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "schema_compliant": False,
        "candidate_item_count": 0,
        "accepted_item_count": 0,
        "citation_invalid_count": 0,
        "required_count": len(fixture.get("required") or []),
        "required_hit_count": 0,
        "missing_required": sorted(map(str, fixture.get("required") or [])),
        "forbidden_hits": [],
        "false_completed_action_hits": [],
        "complete_pass": False,
        "production_pass": False,
        "error": None,
        "evidence_memories": [],
        "accepted_evidence_memories": [],
        "proposition_memories": [],
        "pass_finish_reasons": {"evidence": finish_reason},
        "pass_wall_seconds": {
            "evidence": float(evidence_record.get("wall_seconds") or 0.0)
        },
    }
    try:
        evidence = AtomicMemoryV2EvidencePassResponse.model_validate(
            _parse_json_object(str(evidence_record["response_text"]))
        )
        if evidence.session_id != session_id:
            raise ValueError("evidence_pass_session_mismatch")
        extraction, invalid = compile_atomic_memory_v2_evidence(
            fixture["session"], evidence
        )
        result["schema_compliant"] = True
        result["candidate_item_count"] = len(evidence.spans)
        result["accepted_item_count"] = len(extraction.facts)
        result["citation_invalid_count"] = sum(
            count
            for reason, count in invalid.items()
            if reason.startswith("citation_")
        )
        result["production_evidence_invalid_by_reason"] = invalid
        result["evidence_memories"] = [
            {
                "span_id": span.span_id,
                "memory_text": span.memory_text,
                "attributed_to": span.attributed_to,
                "evidence_kinds": span.evidence_kinds,
                "confidence": span.confidence,
                "citation": span.citation.model_dump(mode="json"),
            }
            for span in evidence.spans
        ]
        result["accepted_evidence_memories"] = [
            {
                "fact_id": fact.fact_id,
                "memory_text": fact.object_text,
                "attributed_to": fact.subject,
                "evidence_kinds": fact.qualifiers.get(
                    "evidence_kinds", ""
                ).split(","),
                "confidence": fact.confidence,
                "citation": {
                    "turn_index": fact.citation.turn_index,
                    "excerpt": fact.citation.excerpt,
                    "speaker": fact.citation.speaker,
                },
            }
            for fact in extraction.facts
        ]
        result["production_pass"] = bool(
            not result["truncated"]
            and not invalid
            and len(extraction.facts) == len(evidence.spans)
        )
        result["complete_pass"] = result["production_pass"]
    except (ValueError, TypeError, KeyError) as exc:
        result["error"] = f"{type(exc).__name__}:{str(exc)[:300]}"
    return result


def aggregate_candidate_results(results: list[dict]) -> dict:
    count = len(results)
    schema_count = sum(bool(row["schema_compliant"]) for row in results)
    candidate_items = sum(int(row["candidate_item_count"]) for row in results)
    accepted_items = sum(int(row["accepted_item_count"]) for row in results)
    citation_invalid = sum(int(row["citation_invalid_count"]) for row in results)
    required = sum(int(row["required_count"]) for row in results)
    required_hits = sum(int(row["required_hit_count"]) for row in results)
    critical = [row for row in results if row["critical"]]
    normalized_latencies = sorted(
        float(row["seconds_per_1000_source_tokens"]) for row in results
    )
    p95_index = max(0, math.ceil(len(normalized_latencies) * 0.95) - 1)
    return {
        "fixture_count": count,
        "response_schema_compliance_rate": schema_count / count if count else 0.0,
        "accepted_citation_validity_rate": (
            max(0, candidate_items - citation_invalid) / candidate_items
            if candidate_items
            else 0.0
        ),
        "required_signature_recall": required_hits / required if required else 0.0,
        "critical_fixture_complete_pass_rate": (
            sum(bool(row["complete_pass"]) for row in critical) / len(critical)
            if critical
            else 0.0
        ),
        "forbidden_signature_violation_count": sum(
            len(row["forbidden_hits"]) for row in results
        ),
        "false_completed_action_violation_count": sum(
            len(row["false_completed_action_hits"]) for row in results
        ),
        "failed_or_truncated_fixture_count": sum(
            bool(row["error"] or row["truncated"]) for row in results
        ),
        "p95_seconds_per_1000_source_tokens": (
            normalized_latencies[p95_index] if normalized_latencies else 0.0
        ),
        "mean_wall_seconds": statistics.fmean(
            float(row["wall_seconds"]) for row in results
        ) if results else 0.0,
        "peak_gpu_memory_mib": max(
            (int(row["peak_gpu_memory_mib"]) for row in results), default=0
        ),
        "candidate_item_count": candidate_items,
        "accepted_item_count": accepted_items,
    }


def evaluate_gates(metrics: dict, gate_manifest: dict) -> dict:
    thresholds = gate_manifest["thresholds"]
    checks: dict[str, bool] = {}
    for name, threshold in thresholds.items():
        if name.endswith("_min"):
            metric = name.removesuffix("_min")
            checks[name] = float(metrics.get(metric, 0.0)) >= float(threshold)
        elif name.endswith("_max"):
            metric = name.removesuffix("_max")
            checks[name] = float(metrics.get(metric, float("inf"))) <= float(threshold)
        else:
            raise ValueError(f"gate threshold must end in _min or _max: {name}")
    return {
        "gate_version": gate_manifest["gate_version"],
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def _artifact_path(
    output_dir: Path,
    candidate: CandidateSpec,
    fixture: dict,
    prompt: str,
    *,
    max_tokens: int,
    max_pass_attempts: int,
    strategy: str,
) -> Path:
    digest = hashlib.sha256(
        json.dumps(
            {
                "candidate": candidate.__dict__,
                "fixture": fixture,
                "prompt": prompt,
                "schemas": (
                    [
                        atomic_memory_v2_entity_pass_json_schema(),
                        atomic_memory_v2_event_pass_json_schema(),
                        atomic_memory_v2_relation_table_pass_json_schema(),
                    ]
                    if strategy == "decomposed"
                    else (
                        [
                            atomic_memory_v2_evidence_pass_json_schema(),
                            atomic_memory_v2_proposition_pass_json_schema(),
                        ]
                        if strategy == "propositions"
                        else [atomic_memory_v2_json_schema()]
                    )
                ),
                "strategy": strategy,
                "runner_protocol": RUNNER_PROTOCOL,
                "max_tokens": max_tokens,
                "max_pass_attempts": max_pass_attempts,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return output_dir / "responses" / normalize_label(candidate.label) / f"{digest}.json"


def normalize_label(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value.lower())
    return safe.strip("-") or "candidate"


def run_candidate(
    candidate: CandidateSpec,
    fixtures: list[dict],
    *,
    output_dir: Path,
    timeout: float,
    max_tokens: int,
    max_pass_attempts: int,
    refresh: bool,
    strategy: str,
) -> list[dict]:
    results: list[dict] = []
    for position, fixture in enumerate(fixtures, start=1):
        prompt = (
            atomic_memory_v2_entity_pass_prompt(fixture["session"])
            if strategy == "decomposed"
            else (
                atomic_memory_v2_evidence_pass_prompt(fixture["session"])
                if strategy in {"evidence", "propositions"}
                else atomic_memory_v2_prompt(fixture["session"])
            )
        )
        artifact = _artifact_path(
            output_dir,
            candidate,
            fixture,
            prompt,
            max_tokens=max_tokens,
            max_pass_attempts=max_pass_attempts,
            strategy=strategy,
        )
        deterministic_only = (
            strategy == "propositions"
            and bool(fixture["session"]["turns"])
            and atomic_memory_v2_deterministic_turn_indices(fixture["session"])
            == set(range(len(fixture["session"]["turns"])))
        )
        if deterministic_only:
            response_record = {
                "strategy": strategy,
                "passes": {
                    "evidence": {
                        "response_text": json.dumps(
                            {
                                "session_id": str(fixture["session"]["session_id"]),
                                "spans": [],
                            }
                        ),
                        "finish_reason": "deterministic",
                        "wall_seconds": 0.0,
                        "usage": {},
                    },
                    "propositions": {
                        "response_text": json.dumps(
                            {
                                "session_id": str(fixture["session"]["session_id"]),
                                "propositions": [],
                            }
                        ),
                        "finish_reason": "deterministic",
                        "wall_seconds": 0.0,
                        "usage": {},
                    },
                },
                "wall_seconds": 0.0,
                "peak_gpu_memory_mib": 0,
            }
        elif artifact.exists() and not refresh:
            response_record = json.loads(artifact.read_text(encoding="utf-8"))
        else:
            started = time.perf_counter()
            try:
                with NvidiaMemorySampler() as sampler:
                    if strategy in {"decomposed", "evidence", "propositions"}:
                        passes: dict[str, dict] = {}

                        def call_pass(
                            name: str,
                            pass_prompt: str,
                            schema: dict,
                            response_model: type[BaseModel],
                        ) -> dict:
                            pass_started = time.perf_counter()
                            attempts: list[dict] = []
                            record: dict = {}
                            for attempt in range(1, max_pass_attempts + 1):
                                attempt_prompt = pass_prompt
                                if attempt > 1:
                                    attempt_prompt += (
                                        "\nThe previous response was invalid. Return one bounded "
                                        "JSON object matching the schema, with no repetition or prose."
                                    )
                                response = _post_chat(
                                    candidate,
                                    attempt_prompt,
                                    timeout=timeout,
                                    max_tokens=max_tokens,
                                    response_schema=schema,
                                )
                                choice = response["choices"][0]
                                record = {
                                    "response_text": str(choice["message"]["content"]),
                                    "finish_reason": choice.get("finish_reason"),
                                    "wall_seconds": time.perf_counter() - pass_started,
                                    "usage": response.get("usage") or {},
                                    "attempt_count": attempt,
                                }
                                try:
                                    response_model.model_validate(
                                        _parse_json_object(record["response_text"])
                                    )
                                    break
                                except (ValueError, TypeError) as exc:
                                    attempts.append(
                                        {
                                            "attempt": attempt,
                                            "error": (
                                                f"{type(exc).__name__}:{str(exc)[:300]}"
                                            ),
                                        }
                                    )
                            if attempts:
                                record["invalid_attempts"] = attempts
                            passes[name] = record
                            return record

                        if strategy == "decomposed":
                            entity_record = call_pass(
                                "entities",
                                prompt,
                                atomic_memory_v2_entity_pass_json_schema(),
                                AtomicMemoryV2EntityPassResponse,
                            )
                            try:
                                entity_pass = AtomicMemoryV2EntityPassResponse.model_validate(
                                    _parse_json_object(entity_record["response_text"])
                                )
                                entity_catalog = entity_pass.entities
                            except (ValueError, TypeError):
                                entity_catalog = []
                            call_pass(
                                "events",
                                atomic_memory_v2_event_pass_prompt(
                                    fixture["session"], entity_catalog
                                ),
                                atomic_memory_v2_event_pass_json_schema(),
                                AtomicMemoryV2EventPassResponse,
                            )
                            call_pass(
                                "relations_tables",
                                atomic_memory_v2_relation_table_pass_prompt(
                                    fixture["session"], entity_catalog
                                ),
                                atomic_memory_v2_relation_table_pass_json_schema(),
                                AtomicMemoryV2RelationTablePassResponse,
                            )
                        else:
                            evidence_record = call_pass(
                                "evidence",
                                prompt,
                                atomic_memory_v2_evidence_pass_json_schema(),
                                AtomicMemoryV2EvidencePassResponse,
                            )
                            try:
                                evidence_pass = AtomicMemoryV2EvidencePassResponse.model_validate(
                                    _parse_json_object(evidence_record["response_text"])
                                )
                                evidence_spans = evidence_pass.spans
                            except (ValueError, TypeError):
                                evidence_spans = []
                            if strategy == "propositions":
                                call_pass(
                                    "propositions",
                                    atomic_memory_v2_proposition_pass_prompt(
                                        fixture["session"], evidence_spans
                                    ),
                                    atomic_memory_v2_proposition_pass_json_schema(),
                                    AtomicMemoryV2PropositionPassResponse,
                                )
                        response_record = {
                            "strategy": strategy,
                            "passes": passes,
                            "wall_seconds": time.perf_counter() - started,
                            "peak_gpu_memory_mib": sampler.peak_mib,
                        }
                    else:
                        response = _post_chat(
                            candidate,
                            prompt,
                            timeout=timeout,
                            max_tokens=max_tokens,
                            response_schema=atomic_memory_v2_json_schema(),
                        )
                        choice = response["choices"][0]
                        response_record = {
                            "strategy": "monolithic",
                            "response_text": str(choice["message"]["content"]),
                            "finish_reason": choice.get("finish_reason"),
                            "wall_seconds": time.perf_counter() - started,
                            "peak_gpu_memory_mib": sampler.peak_mib,
                            "usage": response.get("usage") or {},
                        }
                wall_seconds = time.perf_counter() - started
                response_record["wall_seconds"] = wall_seconds
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(
                    json.dumps(response_record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except (OSError, ValueError, KeyError, IndexError) as exc:
                response_record = {
                    "strategy": strategy,
                    "response_text": "",
                    "finish_reason": "request_error",
                    "wall_seconds": time.perf_counter() - started,
                    "peak_gpu_memory_mib": 0,
                    "request_error": f"{type(exc).__name__}:{str(exc)[:300]}",
                }
        if strategy == "decomposed" and response_record.get("passes"):
            evaluated = evaluate_decomposed_fixture_response(
                fixture,
                passes=response_record["passes"],
                wall_seconds=float(response_record["wall_seconds"]),
                peak_gpu_memory_mib=int(response_record["peak_gpu_memory_mib"]),
            )
        elif strategy == "evidence" and response_record.get("passes"):
            evaluated = evaluate_evidence_fixture_response(
                fixture,
                passes=response_record["passes"],
                wall_seconds=float(response_record["wall_seconds"]),
                peak_gpu_memory_mib=int(response_record["peak_gpu_memory_mib"]),
            )
        elif strategy == "propositions" and response_record.get("passes"):
            evaluated = evaluate_proposition_fixture_response(
                fixture,
                passes=response_record["passes"],
                wall_seconds=float(response_record["wall_seconds"]),
                peak_gpu_memory_mib=int(response_record["peak_gpu_memory_mib"]),
            )
        else:
            evaluated = evaluate_fixture_response(fixture, **{
                key: response_record[key]
                for key in (
                    "response_text",
                    "finish_reason",
                    "wall_seconds",
                    "peak_gpu_memory_mib",
                )
            })
            evaluated["strategy"] = strategy
        if response_record.get("request_error"):
            evaluated["error"] = response_record["request_error"]
        results.append(evaluated)
        print(
            f"{candidate.label} {position}/{len(fixtures)} {fixture['id']} "
            f"pass={evaluated['complete_pass']} seconds={evaluated['wall_seconds']:.2f}",
            flush=True,
        )
    return results


def main() -> int:
    args = parse_args()
    if args.max_pass_attempts < 1 or args.max_pass_attempts > 3:
        raise ValueError("max_pass_attempts_must_be_between_1_and_3")
    hardware = cuda_preflight()
    fixture_bundle = load_fixture_bundle(args.fixtures)
    gate_manifest = load_gate_manifest(args.gates)
    selected = set(args.fixture_id)
    fixtures = [
        fixture
        for fixture in fixture_bundle["fixtures"]
        if not selected or fixture["id"] in selected
    ]
    if selected - {fixture["id"] for fixture in fixtures}:
        raise ValueError("one or more requested fixture IDs do not exist")
    reports = []
    for candidate in args.candidate:
        results = run_candidate(
            candidate,
            fixtures,
            output_dir=args.output_dir,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            max_pass_attempts=args.max_pass_attempts,
            refresh=args.refresh,
            strategy=args.strategy,
        )
        metrics = aggregate_candidate_results(results)
        reports.append(
            {
                "candidate": candidate.__dict__,
                "strategy": args.strategy,
                "metrics": metrics,
                "gate": evaluate_gates(metrics, gate_manifest),
                "fixtures": results,
            }
        )
    report = {
        "protocol": RUNNER_PROTOCOL,
        "fixture_version": fixture_bundle["fixture_version"],
        "evaluation_role": str(
            fixture_bundle.get("evaluation_role") or "development"
        ),
        "gate_version": gate_manifest["gate_version"],
        "hardware": hardware,
        "fixture_count": len(fixtures),
        "strategy": args.strategy,
        "reports": reports,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "matrix-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "reports": [{"candidate": row["candidate"], "metrics": row["metrics"], "gate": row["gate"]} for row in reports]}, indent=2))
    print(f"wrote {output}")
    return 0 if all(row["gate"]["passed"] for row in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
