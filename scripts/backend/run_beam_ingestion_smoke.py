from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2PropositionPassResponse,
    _repair_citation,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
    atomic_memory_v2_proposition_pass_json_schema,
    atomic_memory_v2_proposition_pass_prompt,
    compile_atomic_memory_v2_propositions,
    normalize_atomic_memory_v2,
)
from scripts.backend.run_atomic_extractor_matrix import (  # noqa: E402
    CandidateSpec,
    NvidiaMemorySampler,
    _parse_json_object,
    _post_chat,
    cuda_preflight,
    parse_candidate,
)


DEFAULT_WINDOWS = Path(
    ".tmp/beam-ingestion-eval/frozen-v2/development-windows.jsonl"
)
DEFAULT_OUTPUT = Path(".tmp/beam-ingestion-eval/smoke-qwen3-4b/report.json")
RUNNER_PROTOCOL = "beam-atomic-memory-v2-structural-smoke-v5-atomic-memory-text"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an unscored structural extraction smoke test on BEAM development "
            "windows using a loopback CUDA model endpoint."
        )
    )
    parser.add_argument("--windows", type=Path, default=DEFAULT_WINDOWS)
    parser.add_argument("--candidate", type=parse_candidate)
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument(
        "--all-windows",
        action="store_true",
        help="Run every supplied development window in file order.",
    )
    parser.add_argument(
        "--max-uncached-windows",
        type=int,
        help=(
            "Stop after this many new model calls while retaining cached-window results. "
            "Useful for bounded CUDA server recycle batches."
        ),
    )
    parser.add_argument(
        "--quiet-cache-hits",
        action="store_true",
        help="Suppress per-window progress lines for cached responses.",
    )
    parser.add_argument(
        "--retry-failed-cache",
        action="store_true",
        help="Repeat cached schema/truncation failures while preserving successful caches.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--max-tokens", type=int, default=2_048)
    parser.add_argument(
        "--large-window-max-tokens",
        type=int,
        help="Generation ceiling used when a filtered window exceeds the char threshold.",
    )
    parser.add_argument(
        "--large-window-char-threshold",
        type=int,
        default=7_000,
    )
    parser.add_argument(
        "--evidence-citation-max-chars",
        type=int,
        default=400,
        help="Constrain generated citations to compact exact excerpts.",
    )
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        help=(
            "Run only the first-pass durable-memory extraction. This is the mode used "
            "for large retrieval/answering pilots; compiler quality is measured separately."
        ),
    )
    parser.add_argument(
        "--included-role",
        action="append",
        choices=("user", "assistant", "tool"),
        default=[],
        help="Role to send to extraction; repeat as needed. Defaults to every supported role.",
    )
    parser.add_argument(
        "--rescore-from",
        type=Path,
        help="Re-evaluate saved raw responses without running model inference.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".tmp/beam-ingestion-eval/extraction-cache"),
        help="Per-window response cache used for safe resume without repeated inference.",
    )
    return parser.parse_args()


def load_windows(path: Path) -> list[dict]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("beam_development_windows_are_empty")
    required = {"window_id", "conversation_id", "date", "turns"}
    for row in rows:
        if not required.issubset(row) or not isinstance(row["turns"], list):
            raise ValueError("invalid_beam_development_window")
    return rows


def select_windows(windows: list[dict], sample_size: int) -> list[dict]:
    """Select deterministic, conversation-diverse windows without reading sealed data."""
    if sample_size < 1:
        raise ValueError("sample_size_must_be_positive")
    ranked = sorted(
        windows,
        key=lambda row: hashlib.sha256(
            f"beam-smoke-v1:{row['window_id']}".encode()
        ).hexdigest(),
    )
    selected: list[dict] = []
    seen_conversations: set[str] = set()
    for row in ranked:
        conversation_id = str(row["conversation_id"])
        if conversation_id not in seen_conversations:
            selected.append(row)
            seen_conversations.add(conversation_id)
        if len(selected) == sample_size:
            return selected
    for row in ranked:
        if row not in selected:
            selected.append(row)
        if len(selected) == sample_size:
            break
    return selected


def _session(window: dict, included_roles: set[str]) -> tuple[dict, list[int]]:
    original_turn_indices = [
        index
        for index, turn in enumerate(window["turns"])
        if str(turn.get("role") or "") in included_roles
    ]
    turns = []
    for index in original_turn_indices:
        turn = dict(window["turns"][index])
        source_slice = dict(window["source_slices"][index])
        turn.update(
            {
                "source_turn_id": str(source_slice["source_turn_id"]),
                "source_char_start": int(source_slice["source_char_start"]),
                "source_char_end": int(source_slice["source_char_end"]),
            }
        )
        turns.append(turn)
    return {
        "session_id": str(window["window_id"]),
        "date": str(window["date"]),
        "turns": turns,
    }, original_turn_indices


def _citation_issues(
    session: dict,
    items: list[object],
    *,
    require_stable_anchor: bool = False,
) -> list[dict]:
    issues: list[dict] = []
    for item in items:
        citations = list(getattr(item, "citations", None) or [])
        direct_citation = getattr(item, "citation", None)
        if direct_citation is not None:
            citations.append(direct_citation)
        for citation in citations:
            index = citation.turn_index
            if index >= len(session["turns"]):
                issues.append({"turn_index": index, "reason": "turn_out_of_range"})
                continue
            content = str(session["turns"][index].get("content") or "")
            if citation.excerpt not in content:
                issues.append(
                    {
                        "turn_index": index,
                        "reason": "excerpt_not_exact_source_substring",
                        "excerpt": citation.excerpt,
                    }
                )
                continue
            if require_stable_anchor:
                turn = session["turns"][index]
                local_offset = content.find(citation.excerpt)
                expected_start = int(turn.get("source_char_start") or 0) + local_offset
                expected_turn_id = str(
                    turn.get("source_turn_id")
                    if turn.get("source_turn_id") is not None
                    else index
                )
                if citation.source_turn_id != expected_turn_id:
                    issues.append(
                        {
                            "turn_index": index,
                            "reason": "source_turn_id_mismatch",
                            "expected": expected_turn_id,
                            "actual": citation.source_turn_id,
                        }
                    )
                if (
                    citation.start_char != expected_start
                    or citation.end_char != expected_start + len(citation.excerpt)
                ):
                    issues.append(
                        {
                            "turn_index": index,
                            "reason": "source_offsets_mismatch",
                            "expected_start": expected_start,
                            "expected_end": expected_start + len(citation.excerpt),
                            "actual_start": citation.start_char,
                            "actual_end": citation.end_char,
                        }
                    )
    return issues


def _normalize_evidence_citations(
    session: dict, evidence: AtomicMemoryV2EvidencePassResponse
) -> AtomicMemoryV2EvidencePassResponse:
    normalized_spans = []
    for span in evidence.spans:
        citation = _repair_citation(session, span.citation)
        normalized_spans.append(span.model_copy(update={"citation": citation}))
    return evidence.model_copy(update={"spans": normalized_spans})


def _call_pass(
    candidate: CandidateSpec,
    prompt: str,
    schema: dict,
    *,
    timeout: float,
    max_tokens: int,
) -> dict:
    started = time.perf_counter()
    response = _post_chat(
        candidate,
        prompt,
        timeout=timeout,
        max_tokens=max_tokens,
        response_schema=schema,
    )
    choice = response["choices"][0]
    record = {
        "response_text": str(choice["message"]["content"]),
        "finish_reason": str(choice.get("finish_reason") or ""),
        "wall_seconds": time.perf_counter() - started,
        "usage": response.get("usage") or {},
    }
    return record


def _evidence_response_schema(citation_max_chars: int) -> dict:
    if citation_max_chars < 80 or citation_max_chars > 1_200:
        raise ValueError("evidence_citation_max_chars_must_be_between_80_and_1200")
    schema = atomic_memory_v2_evidence_pass_json_schema()
    citation_schema = schema["$defs"]["CandidateCitation"]
    citation_schema["properties"]["excerpt"]["maxLength"] = citation_max_chars
    citation_schema["properties"]["source_turn_id"] = {
        "type": "string",
        "minLength": 1,
    }
    citation_schema["properties"]["start_char"] = {
        "type": "integer",
        "minimum": 0,
    }
    citation_schema["properties"]["end_char"] = {
        "type": "integer",
        "minimum": 1,
    }
    citation_schema["required"] = list(
        dict.fromkeys(
            [
                *citation_schema.get("required", []),
                "source_turn_id",
                "start_char",
                "end_char",
            ]
        )
    )
    return schema


def _repair_evidence_payload_citations(session: dict, payload: dict) -> int:
    """Canonicalize only exact excerpts; never manufacture semantic grounding."""
    repair_count = 0
    turns = list(session["turns"])
    for span in payload.get("spans") or []:
        citation = span.get("citation") or {}
        excerpt = str(citation.get("excerpt") or "")
        if not excerpt or len(excerpt) > 1200:
            continue
        source_turn_id = citation.get("source_turn_id")
        matches = [
            (index, turn)
            for index, turn in enumerate(turns)
            if source_turn_id is not None
            and str(turn.get("source_turn_id")) == str(source_turn_id)
        ]
        matches = [
            (index, turn)
            for index, turn in matches
            if excerpt in str(turn.get("content") or "")
        ]
        if not matches:
            turn_index = citation.get("turn_index")
            if isinstance(turn_index, int) and 0 <= turn_index < len(turns):
                turn = turns[turn_index]
                if excerpt in str(turn.get("content") or ""):
                    matches = [(turn_index, turn)]
        if not matches:
            matches = [
                (index, turn)
                for index, turn in enumerate(turns)
                if excerpt in str(turn.get("content") or "")
            ]
        if len(matches) != 1:
            continue
        turn_index, turn = matches[0]
        content = str(turn.get("content") or "")
        local_start = content.find(excerpt)
        if local_start < 0:
            continue
        local_end = local_start + len(excerpt)
        base_offset = int(turn.get("source_char_start") or 0)
        canonical = {
            "turn_index": turn_index,
            "excerpt": excerpt,
            "source_turn_id": str(
                turn.get("source_turn_id")
                if turn.get("source_turn_id") is not None
                else turn_index
            ),
            "start_char": base_offset + local_start,
            "end_char": base_offset + local_end,
        }
        if citation != canonical:
            span["citation"] = canonical
            repair_count += 1
    return repair_count


def _repair_proposition_span_references(
    payload: dict,
    evidence: AtomicMemoryV2EvidencePassResponse,
) -> int:
    span_by_id = {span.span_id: span for span in evidence.spans}
    repairs = 0
    for proposition in payload.get("propositions") or []:
        proposed_span = proposition.get("evidence_span_id")
        if proposed_span in span_by_id:
            if proposition.pop("citation", None) is not None:
                repairs += 1
    return repairs


def run_window(
    candidate: CandidateSpec,
    window: dict,
    *,
    timeout: float,
    max_tokens: int,
    included_roles: set[str],
    evidence_only: bool = False,
    evidence_citation_max_chars: int = 400,
) -> dict:
    session, original_turn_indices = _session(window, included_roles)
    started = time.perf_counter()
    result: dict = {
        "window_id": window["window_id"],
        "conversation_id": window["conversation_id"],
        "input_turn_count": len(session["turns"]),
        "original_turn_indices": original_turn_indices,
        "input_char_count": sum(len(str(turn.get("content") or "")) for turn in session["turns"]),
        "schema_compliant": False,
        "structural_pass": False,
        "errors": [],
    }
    evidence_record: dict = {}
    proposition_record: dict = {}
    try:
        evidence_record = _call_pass(
            candidate,
            atomic_memory_v2_evidence_pass_prompt(session),
            _evidence_response_schema(evidence_citation_max_chars),
            timeout=timeout,
            max_tokens=max_tokens,
        )
        evidence_json = _parse_json_object(evidence_record["response_text"])
        evidence_payload_repair_count = _repair_evidence_payload_citations(
            session, evidence_json
        )
        evidence = AtomicMemoryV2EvidencePassResponse.model_validate(evidence_json)
        if evidence.session_id != session["session_id"]:
            raise ValueError("evidence_pass_session_mismatch")
        if evidence_only:
            truncated = evidence_record.get("finish_reason") == "length"
            model_citation_issues = _citation_issues(session, evidence.spans)
            normalized_evidence = _normalize_evidence_citations(session, evidence)
            normalized_citation_issues = _citation_issues(
                session,
                normalized_evidence.spans,
                require_stable_anchor=True,
            )
            result.update(
                {
                    "schema_compliant": True,
                    "structural_pass": bool(
                        not normalized_citation_issues and not truncated
                    ),
                    "evidence_span_count": len(evidence.spans),
                    "proposition_count": 0,
                    "entity_count": 0,
                    "event_count": 0,
                    "relation_count": 0,
                    "model_citation_issue_count": len(model_citation_issues),
                    "model_citation_issues": model_citation_issues,
                    "normalized_citation_issue_count": len(
                        normalized_citation_issues
                    ),
                    "normalized_citation_issues": normalized_citation_issues,
                    "compiler_rejected_count": 0,
                    "evidence_payload_repair_count": evidence_payload_repair_count,
                    "proposition_span_repair_count": 0,
                    "invalid_by_reason": {},
                    "output_truncated": truncated,
                    "coverage_reasons": ["compiler_pass_not_run"],
                    "normalized_memory": None,
                    "evidence_spans": normalized_evidence.model_dump(mode="json")[
                        "spans"
                    ],
                    "wall_seconds": time.perf_counter() - started,
                    "pass_wall_seconds": {
                        "evidence": float(evidence_record.get("wall_seconds") or 0.0),
                        "propositions": 0.0,
                    },
                    "finish_reasons": {
                        "evidence": str(evidence_record.get("finish_reason") or ""),
                        "propositions": "not_run",
                    },
                    "usage": {
                        "evidence": evidence_record.get("usage") or {},
                        "propositions": {},
                    },
                    "raw_responses": {
                        "evidence": evidence_record.get("response_text") or "",
                        "propositions": "",
                    },
                }
            )
            return result
        proposition_record = _call_pass(
            candidate,
            atomic_memory_v2_proposition_pass_prompt(session, evidence.spans),
            atomic_memory_v2_proposition_pass_json_schema(),
            timeout=timeout,
            max_tokens=max_tokens,
        )
        proposition_json = _parse_json_object(proposition_record["response_text"])
        proposition_span_repair_count = _repair_proposition_span_references(
            proposition_json, evidence
        )
        propositions = AtomicMemoryV2PropositionPassResponse.model_validate(
            proposition_json
        )
        if propositions.session_id != session["session_id"]:
            raise ValueError("proposition_pass_session_mismatch")
        candidate_memory = compile_atomic_memory_v2_propositions(
            session, propositions, evidence.spans
        )
        truncated = any(
            record.get("finish_reason") == "length"
            for record in (evidence_record, proposition_record)
        )
        normalized = normalize_atomic_memory_v2(
            session,
            candidate_memory,
            processed_turn_indices=range(len(session["turns"])),
            extraction_complete=not truncated,
            output_truncated=truncated,
        )
        model_citation_issues = _citation_issues(session, evidence.spans)
        model_citation_issues.extend(
            _citation_issues(session, propositions.propositions)
        )
        normalized_items = [
            *normalized.entities,
            *normalized.events,
            *normalized.relations,
            *normalized.table_cells,
        ]
        normalized_citation_issues = _citation_issues(
            session,
            normalized_items,
            require_stable_anchor=True,
        )
        result.update(
            {
                "schema_compliant": True,
                "evidence_span_count": len(evidence.spans),
                "proposition_count": len(propositions.propositions),
                "entity_count": len(normalized.entities),
                "event_count": len(normalized.events),
                "relation_count": len(normalized.relations),
                "model_citation_issue_count": len(model_citation_issues),
                "model_citation_issues": model_citation_issues,
                "normalized_citation_issue_count": len(normalized_citation_issues),
                "normalized_citation_issues": normalized_citation_issues,
                "compiler_rejected_count": normalized.coverage.rejected_candidate_count,
                "evidence_payload_repair_count": evidence_payload_repair_count,
                "proposition_span_repair_count": proposition_span_repair_count,
                "invalid_by_reason": normalized.invalid_by_reason,
                "output_truncated": truncated,
                "coverage_reasons": normalized.coverage.reasons,
                "normalized_memory": normalized.model_dump(mode="json"),
                "evidence_spans": evidence.model_dump(mode="json")["spans"],
                "proposition_memories": [
                    {
                        "proposition_id": proposition.proposition_id,
                        "memory_text": proposition.memory_text,
                        "proposition_kind": proposition.proposition_kind,
                        "predicate": proposition.predicate,
                        "modality": proposition.modality,
                        "attributed_to": str(
                            session["turns"][
                                (
                                    proposition.citation
                                    or next(
                                        span.citation
                                        for span in evidence.spans
                                        if span.span_id
                                        == proposition.evidence_span_id
                                    )
                                ).turn_index
                            ]["role"]
                        ),
                        "confidence": proposition.confidence,
                        "citation": (
                            proposition.citation.model_dump(mode="json")
                            if proposition.citation is not None
                            else next(
                                span.citation.model_dump(mode="json")
                                for span in evidence.spans
                                if span.span_id == proposition.evidence_span_id
                            )
                        ),
                    }
                    for proposition in propositions.propositions
                ],
            }
        )
        result["structural_pass"] = bool(
            not normalized_citation_issues
            and not truncated
            and normalized.coverage.rejected_candidate_count == 0
        )
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        result["errors"].append(f"{type(exc).__name__}:{str(exc)[:500]}")
    result.update(
        {
            "wall_seconds": time.perf_counter() - started,
            "pass_wall_seconds": {
                "evidence": float(evidence_record.get("wall_seconds") or 0.0),
                "propositions": float(proposition_record.get("wall_seconds") or 0.0),
            },
            "finish_reasons": {
                "evidence": str(evidence_record.get("finish_reason") or ""),
                "propositions": str(proposition_record.get("finish_reason") or ""),
            },
            "usage": {
                "evidence": evidence_record.get("usage") or {},
                "propositions": proposition_record.get("usage") or {},
            },
            "raw_responses": {
                "evidence": evidence_record.get("response_text") or "",
                "propositions": proposition_record.get("response_text") or "",
            },
        }
    )
    return result


def rescore_saved_report(
    source_report: Path,
    windows: list[dict],
    output: Path,
) -> int:
    report = json.loads(source_report.read_text(encoding="utf-8"))
    window_by_id = {str(row["window_id"]): row for row in windows}
    included_roles = set(
        report.get("extraction_scope", {}).get("included_roles")
        or ["user", "assistant", "tool"]
    )
    for result in report["results"]:
        window = window_by_id[str(result["window_id"])]
        try:
            rescore_result(window, result, included_roles)
        except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
            result["schema_compliant"] = False
            result["structural_pass"] = False
            result["errors"] = [f"{type(exc).__name__}:{str(exc)[:500]}"]
    results = report["results"]
    report["rescore"] = {
        "protocol": "beam-atomic-memory-v2-offline-rescore-v2-fail-closed",
        "source_report": str(source_report),
        "model_inference_repeated": False,
    }
    report["summary"].update(
        {
            "schema_compliant_count": sum(
                bool(row["schema_compliant"]) for row in results
            ),
            "structural_pass_count": sum(
                bool(row["structural_pass"]) for row in results
            ),
            "total_compiler_rejections": sum(
                int(row.get("compiler_rejected_count") or 0) for row in results
            ),
            "total_model_citation_issues": sum(
                int(row.get("model_citation_issue_count") or 0) for row in results
            ),
            "total_normalized_citation_issues": sum(
                int(row.get("normalized_citation_issue_count") or 0)
                for row in results
            ),
        }
    )
    report["summary"].pop("total_citation_issues", None)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report": str(output), **report["summary"]}, indent=2))
    return 0 if report["summary"]["structural_pass_count"] == len(results) else 1


def rescore_result(
    window: dict, result: dict, included_roles: set[str]
) -> dict:
    """Recompile cached model responses after deterministic compiler changes."""
    session, _ = _session(window, included_roles)
    evidence_payload = _parse_json_object(result["raw_responses"]["evidence"])
    evidence_payload_repair_count = _repair_evidence_payload_citations(
        session, evidence_payload
    )
    evidence = AtomicMemoryV2EvidencePassResponse.model_validate(evidence_payload)
    if not str(result["raw_responses"].get("propositions") or "").strip():
        model_issues = _citation_issues(session, evidence.spans)
        normalized_evidence = _normalize_evidence_citations(session, evidence)
        normalized_issues = _citation_issues(
            session,
            normalized_evidence.spans,
            require_stable_anchor=True,
        )
        truncated = result["finish_reasons"].get("evidence") == "length"
        result.update(
            {
                "schema_compliant": True,
                "structural_pass": bool(not normalized_issues and not truncated),
                "model_citation_issue_count": len(model_issues),
                "model_citation_issues": model_issues,
                "normalized_citation_issue_count": len(normalized_issues),
                "normalized_citation_issues": normalized_issues,
                "output_truncated": truncated,
                "evidence_payload_repair_count": evidence_payload_repair_count,
                "proposition_span_repair_count": 0,
                "evidence_spans": normalized_evidence.model_dump(mode="json")[
                    "spans"
                ],
            }
        )
        return result
    proposition_payload = _parse_json_object(result["raw_responses"]["propositions"])
    proposition_span_repair_count = _repair_proposition_span_references(
        proposition_payload, evidence
    )
    propositions = AtomicMemoryV2PropositionPassResponse.model_validate(
        proposition_payload
    )
    candidate_memory = compile_atomic_memory_v2_propositions(
        session, propositions, evidence.spans
    )
    truncated = any(
        reason == "length" for reason in result["finish_reasons"].values()
    )
    normalized = normalize_atomic_memory_v2(
        session,
        candidate_memory,
        processed_turn_indices=range(len(session["turns"])),
        extraction_complete=not truncated,
        output_truncated=truncated,
    )
    model_issues = _citation_issues(session, evidence.spans)
    model_issues.extend(_citation_issues(session, propositions.propositions))
    normalized_items = [
        *normalized.entities,
        *normalized.events,
        *normalized.relations,
        *normalized.table_cells,
    ]
    normalized_issues = _citation_issues(
        session,
        normalized_items,
        require_stable_anchor=True,
    )
    result.pop("citation_issue_count", None)
    result.pop("citation_issues", None)
    result.update(
        {
            "schema_compliant": True,
            "errors": [],
            "evidence_span_count": len(evidence.spans),
            "proposition_count": len(propositions.propositions),
            "model_citation_issue_count": len(model_issues),
            "model_citation_issues": model_issues,
            "normalized_citation_issue_count": len(normalized_issues),
            "normalized_citation_issues": normalized_issues,
            "compiler_rejected_count": normalized.coverage.rejected_candidate_count,
            "evidence_payload_repair_count": evidence_payload_repair_count,
            "proposition_span_repair_count": proposition_span_repair_count,
            "invalid_by_reason": normalized.invalid_by_reason,
            "normalized_memory": normalized.model_dump(mode="json"),
            "evidence_spans": evidence.model_dump(mode="json")["spans"],
            "proposition_memories": [
                {
                    "proposition_id": proposition.proposition_id,
                    "memory_text": proposition.memory_text,
                    "proposition_kind": proposition.proposition_kind,
                    "predicate": proposition.predicate,
                    "modality": proposition.modality,
                    "attributed_to": str(
                        session["turns"][
                            (
                                proposition.citation
                                or next(
                                    span.citation
                                    for span in evidence.spans
                                    if span.span_id == proposition.evidence_span_id
                                )
                            ).turn_index
                        ]["role"]
                    ),
                    "confidence": proposition.confidence,
                    "citation": (
                        proposition.citation.model_dump(mode="json")
                        if proposition.citation is not None
                        else next(
                            span.citation.model_dump(mode="json")
                            for span in evidence.spans
                            if span.span_id == proposition.evidence_span_id
                        )
                    ),
                }
                for proposition in propositions.propositions
            ],
            "output_truncated": truncated,
            "structural_pass": bool(
                not normalized_issues
                and not truncated
                and normalized.coverage.rejected_candidate_count == 0
            ),
        }
    )
    return result


def main() -> int:
    args = parse_args()
    windows = load_windows(args.windows)
    if args.rescore_from is not None:
        return rescore_saved_report(args.rescore_from, windows, args.output)
    if args.candidate is None:
        raise ValueError("candidate_is_required_for_model_inference")
    hardware = cuda_preflight()
    included_roles = set(args.included_role or ["user", "assistant", "tool"])
    selected = windows if args.all_windows else select_windows(windows, args.sample_size)
    results: list[dict] = []
    uncached_window_count = 0
    with NvidiaMemorySampler() as sampler:
        for index, window in enumerate(selected, start=1):
            filtered_session = _session(window, included_roles)[0]
            input_char_count = sum(
                len(str(turn.get("content") or ""))
                for turn in filtered_session["turns"]
            )
            effective_max_tokens = (
                args.large_window_max_tokens
                if args.large_window_max_tokens is not None
                and input_char_count >= args.large_window_char_threshold
                else args.max_tokens
            )
            cache_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "protocol": RUNNER_PROTOCOL,
                        "candidate": {
                            "label": args.candidate.label,
                            "model": args.candidate.model,
                            "base_url": args.candidate.base_url,
                        },
                        "max_tokens": effective_max_tokens,
                        "evidence_citation_max_chars": args.evidence_citation_max_chars,
                        "evidence_only": args.evidence_only,
                        "included_roles": sorted(included_roles),
                        "window": window,
                        "evidence_prompt": atomic_memory_v2_evidence_pass_prompt(
                            filtered_session
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            cache_path = args.cache_dir / f"{cache_fingerprint}.json"
            needs_inference = not cache_path.exists()
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("fingerprint") != cache_fingerprint:
                    raise RuntimeError("beam_extraction_cache_fingerprint_mismatch")
                result = cached["result"]
                try:
                    rescore_result(window, result, included_roles)
                except (KeyError, TypeError, ValueError):
                    pass
                needs_inference = bool(
                    args.retry_failed_cache
                    and (
                        not result.get("schema_compliant")
                        or not result.get("structural_pass")
                        or result.get("output_truncated")
                        or result.get("finish_reasons", {}).get("evidence")
                        == "length"
                    )
                )
                result["cache_hit"] = not needs_inference
            if needs_inference:
                if (
                    args.max_uncached_windows is not None
                    and uncached_window_count >= args.max_uncached_windows
                ):
                    break
                result = run_window(
                    args.candidate,
                    window,
                    timeout=args.timeout,
                    max_tokens=effective_max_tokens,
                    included_roles=included_roles,
                    evidence_only=args.evidence_only,
                    evidence_citation_max_chars=args.evidence_citation_max_chars,
                )
                result["cache_hit"] = False
                uncached_window_count += 1
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {"fingerprint": cache_fingerprint, "result": result},
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                temporary.replace(cache_path)
            if (
                not args.evidence_only
                and result.get("schema_compliant")
                and result.get("normalized_memory")
            ):
                first_normalized = json.dumps(
                    result["normalized_memory"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                replay = copy.deepcopy(result)
                rescore_result(window, replay, included_roles)
                second_normalized = json.dumps(
                    replay["normalized_memory"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                result["compiler_replay_idempotent"] = (
                    first_normalized == second_normalized
                )
                result["compiler_replay_sha256"] = hashlib.sha256(
                    second_normalized.encode("utf-8")
                ).hexdigest()
            results.append(result)
            if not (args.quiet_cache_hits and result["cache_hit"]):
                print(
                    f"{index}/{len(selected)} {window['window_id']} "
                    f"structural_pass={result['structural_pass']} "
                    f"seconds={result['wall_seconds']:.2f}",
                    flush=True,
                )
    wall_times = [float(row["wall_seconds"]) for row in results]
    report = {
        "protocol": RUNNER_PROTOCOL,
        "evaluation_kind": "unscored_structural_smoke_not_accuracy",
        "extraction_mode": "evidence_only" if args.evidence_only else "full_compiler",
        "paid_api_calls_used": False,
        "source_windows": str(args.windows),
        "source_windows_sha256": hashlib.sha256(args.windows.read_bytes()).hexdigest(),
        "selection": {
            "algorithm": "sha256_rank_one_per_conversation_then_fill-v1",
            "sample_size": len(selected),
            "window_ids": [row["window_id"] for row in results],
            "uncached_window_count": uncached_window_count,
            "complete": len(results) == len(selected),
        },
        "candidate": {
            "label": args.candidate.label,
            "model": args.candidate.model,
            "base_url": args.candidate.base_url,
        },
        "extraction_scope": {
            "included_roles": sorted(included_roles),
            "citation_turn_indices_are_relative_to_filtered_session": True,
        },
        "hardware": hardware,
        "summary": {
            "window_count": len(results),
            "schema_compliant_count": sum(bool(row["schema_compliant"]) for row in results),
            "structural_pass_count": sum(bool(row["structural_pass"]) for row in results),
            "total_evidence_spans": sum(int(row.get("evidence_span_count") or 0) for row in results),
            "total_propositions": sum(int(row.get("proposition_count") or 0) for row in results),
            "total_compiler_rejections": sum(int(row.get("compiler_rejected_count") or 0) for row in results),
            "total_model_citation_issues": sum(
                int(row.get("model_citation_issue_count") or 0) for row in results
            ),
            "total_normalized_citation_issues": sum(
                int(row.get("normalized_citation_issue_count") or 0)
                for row in results
            ),
            "compiler_replay_checked_count": sum(
                "compiler_replay_idempotent" in row for row in results
            ),
            "compiler_replay_idempotent_count": sum(
                bool(row.get("compiler_replay_idempotent")) for row in results
            ),
            "mean_wall_seconds": statistics.mean(wall_times) if wall_times else 0.0,
            "max_wall_seconds": max(wall_times, default=0.0),
            "peak_gpu_memory_mib": sampler.peak_mib,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report": str(args.output), **report["summary"]}, indent=2))
    return 0 if report["summary"]["structural_pass_count"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
