from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ATOMIC_MEMORY_V2_CONTRACT_VERSION = "atomic-memory-v2-contract-v4-atomic-memory-text"

SpeakerRole = Literal["user", "assistant", "tool"]
EntityKind = Literal[
    "person",
    "organization",
    "place",
    "project",
    "product",
    "document",
    "service",
    "object",
    "concept",
    "other",
]
AssertionMode = Literal["asserted", "negated", "hypothetical", "uncertain"]
EvidenceKind = Literal["entity", "alias", "event", "relation"]
PropositionKind = Literal["entity", "alias", "event", "relation"]
PropositionValueKind = Literal[
    "speaker",
    "person",
    "organization",
    "place",
    "project",
    "product",
    "document",
    "service",
    "object",
    "concept",
    "other",
    "literal",
    "none",
]
PropositionModality = Literal[
    "asserted",
    "completed",
    "ongoing",
    "planned",
    "proposed",
    "recommended",
    "hypothetical",
    "negated",
    "uncertain",
    "unknown",
]
EventStatus = Literal[
    "completed",
    "ongoing",
    "planned",
    "proposed",
    "recommended",
    "hypothetical",
    "negated",
    "uncertain",
    "unknown",
]

_SPACE_RE = re.compile(r"\s+")
_KEY_RE = re.compile(r"[^a-z0-9]+")
_RESERVED_ENTITY_REFS = {"user", "assistant", "tool"}
_COMPLETED_ACTION_BLOCK_RE = re.compile(
    r"\b(should|could|might|plans?|planning|wants?|would|if|recommend(?:ed|s)?|"
    r"suggest(?:ed|s)?|propos(?:e|ed|es)|did not|didn't|do not|don't|never|"
    r"not(?!\s+only\b))\b",
    re.IGNORECASE,
)
_ASSERTED_RELATION_BLOCK_RE = re.compile(
    r"\b(might|would|if|did not|didn't|do not|don't|never|not(?!\s+only\b))\b",
    re.IGNORECASE,
)


class CandidateCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=0)
    excerpt: str = Field(min_length=1, max_length=1200)
    source_turn_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> "CandidateCitation":
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("citation_offsets_must_be_supplied_together")
        if (
            self.start_char is not None
            and self.end_char is not None
            and self.end_char <= self.start_char
        ):
            raise ValueError("citation_end_char_must_exceed_start_char")
        return self


class EntityMentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention_id: str = Field(min_length=1)
    citation: CandidateCitation
    surface_text: str = Field(min_length=1, max_length=160)
    entity_kind: EntityKind
    categories: list[str] = Field(default_factory=list, max_length=6)
    alias_of_mention_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class EventParticipantCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    entity_ref: str | None = None
    literal_value: str | None = None

    @model_validator(mode="after")
    def exactly_one_value(self) -> "EventParticipantCandidate":
        if bool(self.entity_ref) == bool(self.literal_value):
            raise ValueError("participant_requires_exactly_one_value")
        return self


class QuantityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str = Field(min_length=1)
    role: str = Field(min_length=1)
    approximate: bool = False


class EventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    citation: CandidateCitation
    event_type: str = Field(min_length=1)
    status: EventStatus
    participants: list[EventParticipantCandidate] = Field(min_length=1, max_length=12)
    same_as_event_id: str | None = None
    event_date: str | None = None
    quantities: list[QuantityCandidate] = Field(default_factory=list, max_length=8)
    attributes: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)


class RelationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_id: str = Field(min_length=1)
    citation: CandidateCitation
    subject_ref: str
    predicate: str = Field(min_length=1)
    object_ref: str | None = None
    object_text: str | None = None
    assertion_mode: AssertionMode = "asserted"
    quantity: QuantityCandidate | None = None
    valid_from: str | None = None
    supersession_scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def exactly_one_object(self) -> "RelationCandidate":
        if bool(self.object_ref) == bool(self.object_text):
            raise ValueError("relation_requires_exactly_one_object")
        return self


class TableCellCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str = Field(min_length=1)
    citation: CandidateCitation
    table_id: str = Field(min_length=1)
    row_label: str = Field(min_length=1)
    column_label: str = Field(min_length=1)
    value_text: str = Field(min_length=1)
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class AtomicMemoryV2SessionCandidate(BaseModel):
    """Untrusted model proposal. It intentionally contains no closure or canonical IDs."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    entities: list[EntityMentionCandidate] = Field(default_factory=list, max_length=48)
    events: list[EventCandidate] = Field(default_factory=list, max_length=48)
    relations: list[RelationCandidate] = Field(default_factory=list, max_length=48)
    table_cells: list[TableCellCandidate] = Field(default_factory=list, max_length=64)


class AtomicMemoryV2Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[AtomicMemoryV2SessionCandidate] = Field(min_length=1, max_length=1)


class AtomicMemoryV2EntityPassResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    entities: list[EntityMentionCandidate] = Field(default_factory=list, max_length=16)


class AtomicMemoryV2EventPassResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    events: list[EventCandidate] = Field(default_factory=list, max_length=16)


class AtomicMemoryV2RelationTablePassResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    relations: list[RelationCandidate] = Field(default_factory=list, max_length=24)
    table_cells: list[TableCellCandidate] = Field(default_factory=list, max_length=64)


class AtomicMemoryV2EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(min_length=1)
    citation: CandidateCitation
    memory_text: str = Field(min_length=1, max_length=600)
    attributed_to: SpeakerRole
    evidence_kinds: list[EvidenceKind] = Field(min_length=1, max_length=4)
    confidence: float = Field(ge=0.0, le=1.0)


class AtomicMemoryV2EvidencePassResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    spans: list[AtomicMemoryV2EvidenceSpan] = Field(default_factory=list, max_length=32)


class AtomicMemoryV2FlatParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    value_text: str = Field(min_length=1, max_length=160)
    value_kind: PropositionValueKind
    categories: list[str] = Field(max_length=6)


class AtomicMemoryV2FlatProposition(BaseModel):
    """A cited semantic statement with no model-owned graph identifiers."""

    model_config = ConfigDict(extra="forbid")

    proposition_id: str = Field(min_length=1)
    memory_text: str = Field(min_length=1, max_length=600)
    evidence_span_id: str | None = Field(default=None, min_length=1)
    citation: CandidateCitation | None = None
    proposition_kind: PropositionKind
    predicate: str = Field(min_length=1, max_length=80)
    modality: PropositionModality
    subject_text: str = Field(max_length=160)
    subject_kind: PropositionValueKind
    subject_categories: list[str] = Field(max_length=6)
    subject_role: str = Field(default="subject", min_length=1, max_length=80)
    object_text: str = Field(max_length=240)
    object_kind: PropositionValueKind
    object_categories: list[str] = Field(max_length=6)
    object_role: str = Field(default="object", min_length=1, max_length=80)
    participants: list[AtomicMemoryV2FlatParticipant] = Field(
        default_factory=list, max_length=12
    )
    event_date: str | None = None
    quantities: list[QuantityCandidate] = Field(default_factory=list, max_length=8)
    supersession_scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_one_citation_source(self) -> AtomicMemoryV2FlatProposition:
        if (self.evidence_span_id is None) == (self.citation is None):
            raise ValueError("exactly_one_of_evidence_span_id_or_citation_is_required")
        return self


class AtomicMemoryV2PropositionPassResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    propositions: list[AtomicMemoryV2FlatProposition] = Field(
        default_factory=list, max_length=48
    )


class NormalizedCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_index: int
    speaker: SpeakerRole
    excerpt: str
    source_turn_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class NormalizedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_key: str
    canonical_name: str
    entity_kind: EntityKind
    aliases: list[str]
    categories: list[str]
    source_mention_ids: list[str]
    citations: list[NormalizedCitation]


class NormalizedParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    entity_key: str | None = None
    literal_value: str | None = None


class NormalizedQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    role: str
    approximate: bool = False


class NormalizedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_key: str
    event_identity_key: str
    event_type: str
    status: EventStatus
    participants: list[NormalizedParticipant]
    event_date: str | None = None
    quantities: list[NormalizedQuantity] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    citation: NormalizedCitation
    confidence: float


class NormalizedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_key: str
    subject_key: str
    predicate: str
    object_key: str | None = None
    object_text: str | None = None
    assertion_mode: AssertionMode
    quantity: NormalizedQuantity | None = None
    valid_from: str | None = None
    supersession_key: str | None = None
    citation: NormalizedCitation
    confidence: float


class NormalizedTableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_key: str
    table_key: str
    row_label: str
    column_label: str
    value_text: str
    row_index: int | None = None
    column_index: int | None = None
    citation: NormalizedCitation
    confidence: float


class CompilerCoverageAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible_turn_indices: list[int]
    processed_turn_indices: list[int]
    source_coverage_complete: bool
    extraction_complete: bool
    output_truncated: bool
    rejected_candidate_count: int
    closed_category_scopes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AtomicMemoryV2NormalizedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = ATOMIC_MEMORY_V2_CONTRACT_VERSION
    session_id: str
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entities: list[NormalizedEntity] = Field(default_factory=list)
    events: list[NormalizedEvent] = Field(default_factory=list)
    relations: list[NormalizedRelation] = Field(default_factory=list)
    table_cells: list[NormalizedTableCell] = Field(default_factory=list)
    coverage: CompilerCoverageAttestation
    invalid_by_reason: dict[str, int] = Field(default_factory=dict)


def atomic_memory_v2_json_schema() -> dict:
    """Return the constrained response schema accepted from the model."""
    return AtomicMemoryV2Response.model_json_schema()


def atomic_memory_v2_entity_pass_json_schema() -> dict:
    return AtomicMemoryV2EntityPassResponse.model_json_schema()


def atomic_memory_v2_event_pass_json_schema() -> dict:
    return AtomicMemoryV2EventPassResponse.model_json_schema()


def atomic_memory_v2_relation_table_pass_json_schema() -> dict:
    return AtomicMemoryV2RelationTablePassResponse.model_json_schema()


def atomic_memory_v2_evidence_pass_json_schema() -> dict:
    return AtomicMemoryV2EvidencePassResponse.model_json_schema()


def atomic_memory_v2_proposition_pass_json_schema() -> dict:
    return AtomicMemoryV2PropositionPassResponse.model_json_schema()


def compile_atomic_memory_v2_evidence(
    session: dict,
    response: AtomicMemoryV2EvidencePassResponse,
) -> tuple[object, dict[str, int]]:
    """Compile the simple v2 evidence pass into the production atomic envelope.

    The model owns only the short, question-independent memory text and an exact
    citation proposal. IDs, source hashes, offsets, source roles, and persistence
    fields are deterministic. The return type is kept as ``object`` here to avoid
    coupling the v2 contract models to the legacy storage envelope at import time.
    """
    from backend.app.core.atomic_memory import (
        AtomicCitation,
        AtomicFact,
        AtomicSessionExtraction,
        AtomicSourceUnitCoverage,
    )

    session_id = str(session.get("session_id") or "")
    if response.session_id != session_id:
        raise ValueError("evidence_candidate_session_mismatch")
    session_date = str(session.get("date") or "")
    turns = list(session.get("turns") or [])
    source_hash = source_content_hash(session)
    invalid: Counter[str] = Counter()
    facts: list[AtomicFact] = []
    fact_ids_by_turn: defaultdict[int, list[str]] = defaultdict(list)
    seen: set[str] = set()
    deterministic_turn_indices = atomic_memory_v2_deterministic_turn_indices(session)

    for span in response.spans:
        citation = _repair_citation(session, span.citation)
        turn_index = int(citation.turn_index)
        if not 0 <= turn_index < len(turns):
            invalid["citation_turn_out_of_range"] += 1
            continue
        if turn_index in deterministic_turn_indices:
            invalid["deterministic_turn_owned"] += 1
            continue
        content = str(turns[turn_index].get("content") or "")
        excerpt = str(citation.excerpt or "").strip()
        if not excerpt or excerpt not in content:
            invalid["citation_excerpt_not_exact"] += 1
            continue
        source_role = str(turns[turn_index].get("role") or "")
        if source_role not in _RESERVED_ENTITY_REFS:
            invalid["citation_speaker_invalid"] += 1
            continue
        memory_text = " ".join(str(span.memory_text).split())
        if not memory_text:
            invalid["memory_text_empty"] += 1
            continue
        identity = _fingerprint(
            "v2-evidence",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "excerpt": excerpt,
                "memory_text": memory_text,
                "attributed_to": span.attributed_to,
            },
        )
        if identity in seen:
            invalid["duplicate_memory"] += 1
            continue
        seen.add(identity)
        fact_id = f"v2-{identity[:24]}"
        evidence_kinds = sorted(set(span.evidence_kinds))
        fact_kind = (
            "event"
            if "event" in evidence_kinds
            else "relationship"
            if "relation" in evidence_kinds or "alias" in evidence_kinds
            else "attribute"
        )
        facts.append(
            AtomicFact(
                fact_id=fact_id,
                citation=AtomicCitation(
                    session_id=session_id,
                    turn_index=turn_index,
                    speaker=source_role,
                    session_date=session_date,
                    excerpt=excerpt,
                    source_content_hash=source_hash,
                ),
                subject=str(span.attributed_to),
                predicate="memory_statement",
                object_text=memory_text,
                fact_kind=fact_kind,
                assertion_mode="asserted",
                observed_date=session_date,
                qualifiers={
                    "atomic_origin": "semantic_v2_evidence",
                    "evidence_kinds": ",".join(evidence_kinds),
                    "source_start_char": str(citation.start_char or content.find(excerpt)),
                    "source_end_char": str(
                        citation.end_char
                        or (content.find(excerpt) + len(excerpt))
                    ),
                },
                confidence=float(span.confidence),
            )
        )
        fact_ids_by_turn[turn_index].append(fact_id)

    source_units: list[AtomicSourceUnitCoverage] = []
    for turn_index, turn in enumerate(turns):
        content = str(turn.get("content") or "").strip()
        role = str(turn.get("role") or "")
        if not content or role not in _RESERVED_ENTITY_REFS:
            continue
        source_units.append(
            AtomicSourceUnitCoverage(
                unit_id=f"v2-turn-{turn_index}",
                turn_index=turn_index,
                speaker=role,
                excerpt_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                status=(
                    "facts_extracted"
                    if fact_ids_by_turn.get(turn_index)
                    else "processed_no_fact"
                ),
                fact_ids=fact_ids_by_turn.get(turn_index, []),
            )
        )
    return (
        AtomicSessionExtraction(
            session_id=session_id,
            facts=facts,
            source_units=source_units,
        ),
        dict(sorted(invalid.items())),
    )


def atomic_memory_v2_session_windows(
    session: dict,
    *,
    max_source_chars: int,
) -> list[dict]:
    """Split a session into bounded turn windows while retaining global provenance."""
    if max_source_chars < 512:
        raise ValueError("max_source_chars_must_be_at_least_512")
    pieces: list[dict] = []
    for turn_index, turn in enumerate(session.get("turns") or []):
        content = str(turn.get("content") or "")
        if not content:
            continue
        for offset in range(0, len(content), max_source_chars):
            chunk = content[offset : offset + max_source_chars]
            pieces.append(
                {
                    "role": str(turn.get("role") or ""),
                    "content": chunk,
                    "source_turn_id": str(
                        turn.get("source_turn_id")
                        if turn.get("source_turn_id") is not None
                        else turn_index
                    ),
                    "source_char_start": int(
                        turn.get("source_char_start") or 0
                    )
                    + offset,
                    "_global_turn_index": turn_index,
                }
            )
    windows: list[dict] = []
    current: list[dict] = []
    current_chars = 0
    for piece in pieces:
        piece_chars = len(piece["content"])
        if current and current_chars + piece_chars > max_source_chars:
            windows.append(
                {
                    "session_id": str(session["session_id"]),
                    "date": str(session["date"]),
                    "turns": current,
                }
            )
            current = []
            current_chars = 0
        current.append(piece)
        current_chars += piece_chars
    if current:
        windows.append(
            {
                "session_id": str(session["session_id"]),
                "date": str(session["date"]),
                "turns": current,
            }
        )
    return windows


def merge_atomic_memory_v2_evidence_windows(
    session: dict,
    window_results: Iterable[tuple[dict, object, dict[str, int]]],
) -> tuple[object, dict[str, int]]:
    """Translate bounded-window facts back to the unchanged full session."""
    from backend.app.core.atomic_memory import (
        AtomicSessionExtraction,
        AtomicSourceUnitCoverage,
    )

    full_hash = source_content_hash(session)
    invalid: Counter[str] = Counter()
    facts = []
    seen: set[tuple[int, str, str, str]] = set()
    facts_by_turn: defaultdict[int, list[str]] = defaultdict(list)
    for window, extraction, reasons in window_results:
        invalid.update(reasons)
        for fact in extraction.facts:
            local_turn_index = fact.citation.turn_index
            if not 0 <= local_turn_index < len(window["turns"]):
                invalid["window_turn_out_of_range"] += 1
                continue
            global_turn_index = int(
                window["turns"][local_turn_index]["_global_turn_index"]
            )
            key = (
                global_turn_index,
                fact.object_text.casefold(),
                fact.citation.excerpt,
                fact.subject,
            )
            if key in seen:
                invalid["duplicate_window_memory"] += 1
                continue
            seen.add(key)
            fact_id = _fingerprint(
                "v2-evidence-global",
                {
                    "session_id": session["session_id"],
                    "turn_index": global_turn_index,
                    "memory_text": fact.object_text,
                    "excerpt": fact.citation.excerpt,
                    "subject": fact.subject,
                },
            )
            citation = fact.citation.model_copy(
                update={
                    "turn_index": global_turn_index,
                    "source_content_hash": full_hash,
                }
            )
            translated = fact.model_copy(
                update={"fact_id": f"v2-{fact_id[:24]}", "citation": citation}
            )
            facts.append(translated)
            facts_by_turn[global_turn_index].append(translated.fact_id)

    source_units: list[AtomicSourceUnitCoverage] = []
    for turn_index, turn in enumerate(session.get("turns") or []):
        content = str(turn.get("content") or "").strip()
        role = str(turn.get("role") or "")
        if not content or role not in _RESERVED_ENTITY_REFS:
            continue
        source_units.append(
            AtomicSourceUnitCoverage(
                unit_id=f"v2-turn-{turn_index}",
                turn_index=turn_index,
                speaker=role,
                excerpt_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                status=(
                    "facts_extracted"
                    if facts_by_turn.get(turn_index)
                    else "processed_no_fact"
                ),
                fact_ids=facts_by_turn.get(turn_index, []),
            )
        )
    return (
        AtomicSessionExtraction(
            session_id=str(session["session_id"]),
            facts=facts,
            source_units=source_units,
        ),
        dict(sorted(invalid.items())),
    )


def _session_payload(session: dict) -> dict:
    return {
        "session_id": str(session["session_id"]),
        "date": str(session["date"]),
        "turns": list(session["turns"]),
    }


def atomic_memory_v2_evidence_pass_prompt(session: dict) -> str:
    return (
        "Extract question-independent durable memories from CURRENT session turns as strict "
        "JSON matching the schema. Return no prose. Work turn by turn and clause by clause and emit one memory "
        "per independently meaningful durable fact. Preserve speaker, polarity, modality, dates, "
        "and quantities. Do not combine completed, planned, uncertain, or negated actions into "
        "one memory. The citation must be the shortest exact contiguous source clause or sentence "
        "that supports the memory; copy it exactly and use its zero-based turn_index. Omit "
        "source_turn_id, start_char, and end_char: the deterministic compiler owns identifiers "
        "and offsets. memory_text is a self-contained natural "
        "language statement that will survive after the conversation is gone: replace pronouns "
        "with source-supported referents, preserve names, categories, quantities, dates, negation, "
        "uncertainty, plans, recommendations, and speaker attribution, and resolve an alias only "
        "when the text supports the identity. Ground relative dates against the session date when "
        "the result is unambiguous. attributed_to is the speaker whose durable fact, action, state, "
        "or recommendation is being recorded; do not treat an assistant echo as a new user fact. "
        "Prioritize facts about the user and their world. Do not store generic assistant teaching, "
        "tutorials, worked examples, background knowledge, boilerplate suggestions, or enumerated "
        "advice as conversational memory. Store assistant-authored content only when it is a "
        "specific commitment, decision, or individualized recommendation that would matter in a "
        "future conversation with this user. "
        "Do not store the conversational act of asking, thanking, agreeing, mentioning, noting, or "
        "acknowledging when the underlying durable fact can be stored instead. Do not turn a request "
        "for advice into an intention to perform the requested action. Atomicity pattern: a source "
        "saying that its speaker completed one activity and may do a second activity produces two "
        "spans, one completed and one uncertain. A source that names a relative and then states "
        "where that person lives produces separate identity and residence spans. Never copy a "
        "compound source sentence as one memory merely because one citation supports it. Rewrite "
        "first- and second-person references as user or assistant according to attributed_to so "
        "memory_text remains unambiguous outside the conversation. One citation may support "
        "multiple independent memory records. evidence_kinds contains each applicable kind at most "
        "once. Include entities and their "
        "ordinary semantic types when context supports them. Skip greetings, content-free filler, "
        "and visibly structured tables or lists because the deterministic compiler handles those. "
        "Use [] only when no durable memory exists.\nSession:\n"
        + json.dumps(_session_payload(session), ensure_ascii=False, separators=(",", ":"))
    )


def atomic_memory_v2_proposition_pass_prompt(
    session: dict,
    spans: Iterable[AtomicMemoryV2EvidenceSpan],
) -> str:
    span_payload = [span.model_dump(mode="json") for span in spans]
    return (
        "Convert every supplied atomic memory into one or more flat cited propositions as strict "
        "JSON matching the schema. Return no prose. Process each span independently, then audit that "
        "every nonduplicate span produced its underlying world fact. For every proposition, output "
        "memory_text as one concise, self-contained natural-language sentence expressing only that "
        "proposition. Resolve conversational pronouns to user, assistant, tool, or a supported named "
        "referent. Never copy multiple independent claims into one proposition memory_text. The "
        "supplied span memory_text is the semantic source for resolved "
        "references and ordinary categories; the exact session text is the authority for citations "
        "and surface values. Do not silently drop a memory: every span must be represented by at "
        "least one proposition unless it is an exact duplicate. proposition_id is only a unique "
        "local label and must never be used as a graph or entity reference. Copy "
        "subject_text, object_text, and participant value_text as short exact phrases from the "
        "cited source whenever they name an entity; use speaker with user, assistant, or tool for "
        "conversation participants, literal for non-entity values, and none for an unused side. "
        "Use one entity proposition for each durable named entity or description. Use alias only "
        "when two exact phrases explicitly refer to the same entity; subject is the best name and "
        "object is the alias. Add a short lowercase category only when the source explicitly "
        "supports that category; do not infer a category from a name alone. "
        "Always include subject_text, subject_kind, subject_categories, object_text, object_kind, "
        "and object_categories. Omit optional fields when they do not apply. subject_role and "
        "object_role are needed only when the default subject/object labels lose a useful semantic "
        "role. participants contains only additional participants not already represented by the "
        "subject or object; never pad it with user, assistant, tool, none, punctuation, or duplicates. "
        "Each named entity used by a fact must have an "
        "entity proposition or a typed participant/value in that fact. "
        "For events, predicate is a concise snake_case action type for the underlying activity rather "
        "than a conversational or mental wrapper. A planned activity uses the activity as predicate "
        "and planned as modality; do not use plan as its predicate. Likewise, never use ask, say, "
        "mention, note, acknowledge, remember, want, or consider as the predicate when the memory "
        "states a more useful underlying fact or activity. "
        "Choose it from the meaning of the supplied memory instead of matching a fixed domain list. "
        "Modality preserves completed, "
        "ongoing, planned, proposed, recommended, hypothetical, negated, uncertain, or unknown, "
        "and participants describe each participant's source-supported semantic role rather than "
        "inventing one from a fixed domain list. Advice, "
        "possibilities, questions, plans, and negations are never completed. Recommendations and "
        "proposals are events, not relations. For durable states and preferences, use a relation "
        "with asserted, negated, hypothetical, or uncertain modality. Use a concise snake_case "
        "relation predicate supported by the supplied memory. "
        "Use an explicit supersession_scope only for a replaceable current value. Every entity or "
        "literal participant and every relation object must be copied from the cited source, except "
        "the reserved speaker values user, assistant, and tool. Preserve typed "
        "quantities and dates. Set evidence_span_id to the supplied span_id that supports each "
        "proposition and omit citation; never regenerate or copy citation text in this pass. Prefer the "
        "meaning already made self-contained in the supplied span memory_text instead of "
        "reinterpreting the raw "
        "conversation. Do not produce "
        "table or list records and do not repeat the same fact as both an event and relation.\n"
        "Evidence spans:\n"
        + json.dumps(span_payload, ensure_ascii=False, separators=(",", ":"))
        + "\nSession:\n"
        + json.dumps(_session_payload(session), ensure_ascii=False, separators=(",", ":"))
    )


def atomic_memory_v2_entity_pass_prompt(session: dict) -> str:
    return (
        "Extract only real entity mentions as strict JSON matching the schema. Return no prose. "
        "Use the shortest exact surface phrase from the source, never a sentence and never isolated "
        "grammar words. Emit one record for every distinct referring phrase, including a title, "
        "description, or shortened name that refers to an entity already emitted; connect the later "
        "record with alias_of_mention_id. Do not make an entity its own alias. A record may represent "
        "a person, organization, place, project, product, document, service, object, or durable "
        "concept. Add a short lowercase category only when the surrounding source explicitly "
        "states or describes it. Do not infer a category from a name, honorific, or benchmark-shaped "
        "vocabulary, and do not use entity_kind as a substitute for source evidence. Add categories "
        "to an alias only when the source independently supports them. "
        "Link alias_of_mention_id only when the text supports same identity. Every citation excerpt "
        "must be exact and turn_index is zero-based. Do not extract user/assistant/tool as entities. "
        "Use [] when there are no named or durable entities.\nSession:\n"
        + json.dumps(_session_payload(session), ensure_ascii=False, separators=(",", ":"))
    )


def _entity_catalog(entities: Iterable[EntityMentionCandidate]) -> list[dict]:
    return [
        {
            "mention_id": entity.mention_id,
            "surface_text": entity.surface_text,
            "entity_kind": entity.entity_kind,
            "categories": entity.categories,
        }
        for entity in entities
    ]


def atomic_memory_v2_event_pass_prompt(
    session: dict,
    entities: Iterable[EntityMentionCandidate],
) -> str:
    return (
        "Extract only actions, occurrences, and state-changing events as strict JSON matching the "
        "schema. Return no prose. Use a concise snake_case event_type derived from the supplied "
        "source meaning, not a fixed domain list. Status must preserve completed, ongoing, planned, "
        "proposed, recommended, hypothetical, negated, uncertain, or unknown. Advice, wants, plans, "
        "questions, possibilities, and negations are never completed. Every event needs participant "
        "roles. entity_ref must be user/assistant/tool or an ID in the supplied entity catalog; use "
        "literal_value instead when no catalog entity exists, never both. Participant role describes "
        "the participant's explicitly supported function in the event, not a role guessed from its "
        "entity category. Link every explicitly participating catalog entity; do not replace a "
        "named person with assistant or tool. Extract an explicitly negated occurrence as a separate "
        "negated event when it matters, even when another event appears in the same sentence. Cite an "
        "exact excerpt from the cited turn with zero-based turn_index; never cite a turn that does not "
        "exist. Preserve dates and typed quantities. Do not emit relationships or "
        "table cells. Use [] only when the source truly contains no event or recommendation.\n"
        "Entity catalog:\n"
        + json.dumps(_entity_catalog(entities), ensure_ascii=False, separators=(",", ":"))
        + "\nSession:\n"
        + json.dumps(_session_payload(session), ensure_ascii=False, separators=(",", ":"))
    )


def atomic_memory_v2_relation_table_pass_prompt(
    session: dict,
    entities: Iterable[EntityMentionCandidate],
) -> str:
    return (
        "Extract durable non-event relationships and actual table cells as strict JSON matching the "
        "schema. Return no prose. For a relationship, subject_ref must be user/assistant/tool or an "
        "ID in the supplied entity catalog. Use object_ref for a catalog entity OR object_text for a "
        "literal value, never both. Preserve negation, uncertainty, preference direction, typed "
        "quantities, valid_from, and a stable supersession_scope for replaceable current states. Do "
        "not duplicate an action or occurrence as a relation. Do not invent object_ref values: use "
        "object_text unless the object is user/assistant/tool or an ID in the catalog. Create "
        "table_cells only when the source visibly contains a table, delimited rows and columns, or an "
        "explicit row/column record. Never turn prose into a table. For each data cell, row_label "
        "is the row's identifying value, column_label is the header above that cell, and value_text "
        "is that cell's value; do not emit header cells as data. Every citation excerpt is exact and "
        "turn_index is zero-based and must exist in the session. Use empty arrays when "
        "that record type is absent.\n"
        "Entity catalog:\n"
        + json.dumps(_entity_catalog(entities), ensure_ascii=False, separators=(",", ":"))
        + "\nSession:\n"
        + json.dumps(_session_payload(session), ensure_ascii=False, separators=(",", ":"))
    )


def atomic_memory_v2_prompt(session: dict) -> str:
    payload = _session_payload(session)
    return (
        "Extract question-independent durable memory as one strict JSON object matching the schema. "
        "Return exactly one session and no prose. Always include entities, events, relations, and "
        "table_cells arrays; use [] when that record type is absent. Extract only facts explicitly "
        "supported by the source.\n"
        "Citation: exact contiguous excerpt plus zero-based turn_index. Entity surface_text must be "
        "the shortest exact entity phrase, never a sentence. Use categories only when the source "
        "explicitly supports them. Link aliases only when identity is "
        "explicit.\n"
        "Events: use a concise snake_case action type, status, and participants. Each participant "
        "uses entity_ref OR literal_value, never both. Reserved refs are user, assistant, and tool; "
        "all other refs must name an emitted mention_id. Advice, wants, plans, possibilities, and "
        "negations are never completed. Link repeated descriptions with same_as_event_id.\n"
        "Relations: use object_ref OR object_text, never both. Preserve assertion mode, typed "
        "quantities, dates, and supersession scope. Create table_cells only for an actual table or "
        "explicit row/column record, with the linked row label, column header, and cell value. Never "
        "turn prose into a table. Do not invent canonical IDs or closure; the backend owns both.\n"
        "Session:\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


_PROPOSITION_ENTITY_KINDS = {
    "person",
    "organization",
    "place",
    "project",
    "product",
    "document",
    "service",
    "object",
    "concept",
    "other",
}
_EVENT_STATUSES = {
    "completed",
    "ongoing",
    "planned",
    "proposed",
    "recommended",
    "hypothetical",
    "negated",
    "uncertain",
    "unknown",
}
_ASSERTION_MODES = {"asserted", "negated", "hypothetical", "uncertain"}
_MARKDOWN_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_ORDERED_LIST_ITEM_RE = re.compile(
    r"(?:^|\s)(?:\d+|[a-zA-Z])[.)]\s+(.+?)(?=(?:\s+(?:\d+|[a-zA-Z])[.)]\s+)|$)"
)


def _repair_citation(session: dict, citation: CandidateCitation) -> CandidateCitation:
    turns = list(session["turns"])
    excerpt = citation.excerpt.strip()
    if (
        citation.source_turn_id is not None
        and citation.start_char is not None
        and citation.end_char is not None
    ):
        anchored_turns = [
            (index, turn)
            for index, turn in enumerate(turns)
            if str(turn.get("source_turn_id")) == citation.source_turn_id
        ]
        if len(anchored_turns) == 1:
            turn_index, turn = anchored_turns[0]
            content = str(turn.get("content") or "")
            base_offset = int(turn.get("source_char_start") or 0)
            local_start = citation.start_char - base_offset
            local_end = citation.end_char - base_offset
            if 0 <= local_start < local_end <= len(content):
                anchored_excerpt = content[local_start:local_end]
                if anchored_excerpt == excerpt:
                    return CandidateCitation(
                        turn_index=turn_index,
                        excerpt=anchored_excerpt,
                        source_turn_id=citation.source_turn_id,
                        start_char=citation.start_char,
                        end_char=citation.end_char,
                    )
    if citation.turn_index < len(turns):
        turn = turns[citation.turn_index]
        content = str(turn.get("content") or "")
        offset = content.find(excerpt)
        if offset >= 0:
            base_offset = int(turn.get("source_char_start") or 0)
            return CandidateCitation(
                turn_index=citation.turn_index,
                excerpt=content[offset : offset + len(excerpt)],
                source_turn_id=str(
                    turn.get("source_turn_id")
                    if turn.get("source_turn_id") is not None
                    else citation.source_turn_id or citation.turn_index
                ),
                start_char=base_offset + offset,
                end_char=base_offset + offset + len(excerpt),
            )
    matches: list[tuple[int, str, int]] = []
    for turn_index, turn in enumerate(turns):
        content = str(turn.get("content") or "")
        offset = content.find(excerpt)
        if offset >= 0:
            matches.append(
                (turn_index, content[offset : offset + len(excerpt)], offset)
            )
    if len(matches) == 1:
        turn_index, matched_excerpt, offset = matches[0]
        turn = turns[turn_index]
        base_offset = int(turn.get("source_char_start") or 0)
        return CandidateCitation(
            turn_index=turn_index,
            excerpt=matched_excerpt,
            source_turn_id=str(
                turn.get("source_turn_id")
                if turn.get("source_turn_id") is not None
                else turn_index
            ),
            start_char=base_offset + offset,
            end_char=base_offset + offset + len(matched_excerpt),
        )
    return citation


def _narrow_citation(
    citation: CandidateCitation,
    values: Iterable[str],
) -> CandidateCitation:
    targets = [normalize_text(value) for value in values if normalize_text(value)]
    if not targets:
        return citation
    protected = re.sub(
        r"\b(Dr|Prof|Mr|Mrs|Ms|Mx|Sr|Jr|St)\.",
        lambda match: f"{match.group(1)}<atomic-period>",
        citation.excerpt,
        flags=re.IGNORECASE,
    )
    protected = re.sub(
        r",\s+(?:(?:but|although|however)\s+|and\s+(?=(?:I|we)(?:\b|['’])))",
        "<atomic-contrast>",
        protected,
        flags=re.IGNORECASE,
    )
    clauses = [
        match.group(0)
        .replace("<atomic-period>", ".")
        .replace("<atomic-contrast>", "")
        .strip()
        for match in re.finditer(
            r"(?:(?!<atomic-contrast>)[^;.!?])+(?:<atomic-contrast>|[;.!?]|$)",
            protected,
        )
        if match.group(0).strip()
    ]
    if len(clauses) < 2:
        return citation
    scored = [
        (sum(target in normalize_text(clause) for target in targets), -len(clause), clause)
        for clause in clauses
    ]
    score, _negative_length, clause = max(scored)
    if score <= 0 or len(clause) >= len(citation.excerpt):
        return citation
    relative_offset = citation.excerpt.find(clause)
    start_char = (
        citation.start_char + relative_offset
        if citation.start_char is not None and relative_offset >= 0
        else None
    )
    return CandidateCitation(
        turn_index=citation.turn_index,
        excerpt=clause,
        source_turn_id=citation.source_turn_id,
        start_char=start_char,
        end_char=(start_char + len(clause) if start_char is not None else None),
    )


def _canonical_proposition_predicate(
    predicate: str,
) -> str:
    """Normalize syntax only; semantic predicate selection belongs to the extractor."""
    return normalize_key(predicate)


def _repaired_modality(
    proposition_kind: str,
    predicate: str,
    modality: PropositionModality,
    citation: CandidateCitation,
) -> PropositionModality:
    """Apply domain-independent safety downgrades from explicit source scope."""
    if proposition_kind not in {"event", "relation"}:
        return modality
    source = normalize_text(citation.excerpt)
    if re.search(
        r"\b(?:do not|don't|does not|doesn't|did not|didn't|never)\b", source
    ):
        return "negated"
    if re.search(r"\b(?:might|may|possibly|perhaps|nothing is decided|not decided)\b", source):
        return "uncertain"
    if re.search(r"\b(?:if|would|could have|might have)\b", source):
        return "hypothetical"
    if source.rstrip().endswith("?") or re.search(
        r"\b(?:can you|could you|how can|wondering|looking for (?:advice|help))\b",
        source,
    ):
        return "proposed"
    if re.search(
        r"\b(?:plan|planning|intend|intending|itinerary|will|i'll|we'll|"
        r"consider|considering|aim|aiming)\b",
        source,
    ):
        return "planned"
    if re.search(r"\b(?:recommend|recommended|should|suggest|suggested|advis(?:e|ed))\b", source):
        return "recommended"
    if re.search(r"\b(?:am|is|are)\s+(?:currently\s+)?\w+ing\b", source):
        return "ongoing"
    return modality


def _normalized_participant_role(proposed_role: str) -> str:
    """Normalize a model-proposed role without inferring domain semantics."""
    return normalize_key(proposed_role) or "participant"


def _normalized_proposition_quantities(
    quantities: Iterable[QuantityCandidate],
) -> list[QuantityCandidate]:
    normalized: list[QuantityCandidate] = []
    for quantity in quantities:
        role = normalize_key(quantity.role)
        unit = normalize_key(quantity.unit)
        normalized.append(
            QuantityCandidate(
                value=quantity.value,
                unit=unit,
                role=role,
                approximate=quantity.approximate,
            )
        )
    return normalized


def _source_surface(value: str, citation: CandidateCitation) -> str:
    value = value.strip()
    if not value:
        return ""
    offset = citation.excerpt.casefold().find(value.casefold())
    if offset >= 0:
        return citation.excerpt[offset : offset + len(value)]
    return ""


def _source_surface_with_determiner(value: str, citation: CandidateCitation) -> str:
    surface = _source_surface(value, citation)
    if not surface:
        return ""
    expanded = _source_surface(f"the {surface}", citation)
    if expanded:
        return expanded
    return surface


def _speaker_reference(
    value: str,
    citation: CandidateCitation,
    session: dict,
) -> str | None:
    normalized = normalize_text(value)
    if normalized in _RESERVED_ENTITY_REFS:
        return normalized
    if citation.turn_index < 0 or citation.turn_index >= len(session["turns"]):
        return None
    speaker = str(session["turns"][citation.turn_index].get("role") or "")
    if normalized in {"i", "me", "my", "myself", "we", "our", "ourselves"}:
        return speaker if speaker in _RESERVED_ENTITY_REFS else None
    if normalized in {"you", "your", "yourself"}:
        if speaker == "assistant":
            return "user"
        if speaker == "user":
            return "assistant"
    return None


def _markdown_table_candidates(session: dict) -> list[TableCellCandidate]:
    cells: list[TableCellCandidate] = []
    for turn_index, turn in enumerate(session["turns"]):
        content = str(turn.get("content") or "")
        lines = content.splitlines()
        line_index = 0
        table_number = 0
        while line_index + 2 < len(lines):
            headers = [cell.strip() for cell in lines[line_index].strip().strip("|").split("|")]
            separators = [
                cell.strip() for cell in lines[line_index + 1].strip().strip("|").split("|")
            ]
            if (
                len(headers) < 2
                or len(headers) != len(separators)
                or not all(_MARKDOWN_SEPARATOR_CELL_RE.fullmatch(cell) for cell in separators)
            ):
                line_index += 1
                continue
            data_lines: list[str] = []
            cursor = line_index + 2
            while cursor < len(lines) and "|" in lines[cursor]:
                data_lines.append(lines[cursor])
                cursor += 1
            if not data_lines:
                line_index += 1
                continue
            excerpt = "\n".join(lines[line_index:cursor])
            if len(excerpt) > 1200:
                line_index = cursor
                continue
            table_id = f"structured-table-{turn_index}-{table_number}"
            for row_offset, data_line in enumerate(data_lines, start=1):
                values = [cell.strip() for cell in data_line.strip().strip("|").split("|")]
                if len(values) != len(headers) or not values[0]:
                    continue
                for column_index in range(1, len(headers)):
                    if not headers[column_index] or not values[column_index]:
                        continue
                    cells.append(
                        TableCellCandidate(
                            cell_id=f"{table_id}-{row_offset}-{column_index}",
                            citation=CandidateCitation(
                                turn_index=turn_index, excerpt=excerpt
                            ),
                            table_id=table_id,
                            row_label=values[0],
                            column_label=headers[column_index],
                            value_text=values[column_index],
                            row_index=row_offset,
                            column_index=column_index,
                            confidence=1.0,
                        )
                    )
            table_number += 1
            line_index = cursor
    return cells


def _ordered_list_items(content: str) -> tuple[str, list[str]] | None:
    if len(content) > 1200:
        return None
    if re.search(
        r"```|<(?:html|head|body|script|style|form|div)\b",
        content,
        re.IGNORECASE,
    ):
        return None
    if ":" not in content:
        return None
    label, remainder = content.split(":", 1)
    if not label.strip() or len(label.strip()) > 80:
        return None
    items = [
        match.group(1).strip().rstrip(".;")
        for match in _ORDERED_LIST_ITEM_RE.finditer(remainder.strip())
        if match.group(1).strip().rstrip(".;")
    ]
    return (label.strip(), items) if len(items) >= 2 else None


def atomic_memory_v2_deterministic_turn_indices(session: dict) -> set[int]:
    indices = {
        cell.citation.turn_index for cell in _markdown_table_candidates(session)
    }
    indices.update(
        turn_index
        for turn_index, turn in enumerate(session["turns"])
        if _ordered_list_items(str(turn.get("content") or "")) is not None
    )
    return indices


def compile_atomic_memory_v2_propositions(
    session: dict,
    response: AtomicMemoryV2PropositionPassResponse,
    evidence_spans: Iterable[AtomicMemoryV2EvidenceSpan] = (),
) -> AtomicMemoryV2SessionCandidate:
    """Compile flat text propositions into the existing untrusted candidate contract."""
    session_id = str(session["session_id"])
    if response.session_id != session_id:
        raise ValueError("proposition_candidate_session_mismatch")

    entities: list[EntityMentionCandidate] = []
    events: list[EventCandidate] = []
    relations: list[RelationCandidate] = []
    mention_by_surface: dict[tuple[str, str], EntityMentionCandidate] = {}
    citation_by_span_id = {span.span_id: span.citation for span in evidence_spans}
    deterministic_turn_indices = atomic_memory_v2_deterministic_turn_indices(session)

    def ensure_mention(
        value: str,
        kind: str,
        categories: Iterable[str],
        citation: CandidateCitation,
    ) -> EntityMentionCandidate | None:
        categories = tuple(categories)
        if kind not in _PROPOSITION_ENTITY_KINDS:
            return None
        surface = _source_surface(value, citation)
        if not surface:
            return None
        key = (normalize_text(surface), kind)
        enriched_categories = {str(item) for item in categories if str(item).strip()}
        existing = mention_by_surface.get(key)
        if existing is not None:
            existing.categories = sorted(
                set(existing.categories).union(enriched_categories)
            )
            return existing
        mention = EntityMentionCandidate(
            mention_id=f"m{len(entities) + 1}",
            citation=citation,
            surface_text=surface,
            entity_kind=kind,
            categories=sorted(enriched_categories),
            confidence=1.0,
        )
        entities.append(mention)
        mention_by_surface[key] = mention
        return mention

    def value_reference(
        value: str,
        kind: str,
        categories: Iterable[str],
        citation: CandidateCitation,
    ) -> tuple[str | None, str | None]:
        speaker_reference = _speaker_reference(value, citation, session)
        if kind == "speaker" or speaker_reference:
            return speaker_reference, None
        mention = ensure_mention(value, kind, categories, citation)
        if mention is not None:
            return mention.mention_id, None
        if kind in _PROPOSITION_ENTITY_KINDS:
            return None, None
        literal = value.strip()
        return (None, literal or None)

    seen_proposition_ids: set[str] = set()
    for proposition in response.propositions:
        if proposition.proposition_id in seen_proposition_ids:
            continue
        seen_proposition_ids.add(proposition.proposition_id)
        source_citation = proposition.citation
        if proposition.evidence_span_id is not None:
            source_citation = citation_by_span_id.get(proposition.evidence_span_id)
            if source_citation is None:
                raise ValueError(
                    f"unknown_evidence_span_id:{proposition.evidence_span_id}"
                )
        if source_citation is None:
            raise ValueError("proposition_citation_source_missing")
        if source_citation.turn_index in deterministic_turn_indices:
            continue
        citation = _repair_citation(session, source_citation)
        if proposition.proposition_kind in {"event", "relation"}:
            citation = _narrow_citation(
                citation,
                [
                    proposition.subject_text,
                    proposition.object_text,
                    *(participant.value_text for participant in proposition.participants),
                ],
            )
        subject_kind = proposition.subject_kind
        object_kind = proposition.object_kind
        subject_categories = list(proposition.subject_categories)
        object_categories = list(proposition.object_categories)
        subject_text = proposition.subject_text
        object_text = proposition.object_text
        expanded_object = _source_surface_with_determiner(object_text, citation)
        if expanded_object:
            object_text = expanded_object
        predicate = _canonical_proposition_predicate(proposition.predicate)
        modality = _repaired_modality(
            proposition.proposition_kind,
            predicate,
            proposition.modality,
            citation,
        )
        quantities = _normalized_proposition_quantities(proposition.quantities)
        proposition_kind = proposition.proposition_kind
        if proposition_kind == "relation" and modality in {
            "completed",
            "ongoing",
            "planned",
            "proposed",
            "recommended",
        }:
            proposition_kind = "event"
        subject = ensure_mention(
            subject_text,
            subject_kind,
            subject_categories,
            citation,
        )
        obj = ensure_mention(
            object_text,
            object_kind,
            object_categories,
            citation,
        )

        if proposition_kind == "entity":
            continue
        if proposition_kind == "alias":
            if subject is not None and obj is not None and subject.mention_id != obj.mention_id:
                obj.alias_of_mention_id = subject.mention_id
            continue
        if proposition_kind == "event":
            participants: list[EventParticipantCandidate] = []
            for participant in proposition.participants:
                participant_value = participant.value_text
                participant_categories = set(participant.categories)
                if normalize_text(participant_value) == normalize_text(subject_text):
                    participant_categories.update(subject_categories)
                if normalize_text(participant_value) in {
                    normalize_text(proposition.object_text),
                    normalize_text(object_text),
                }:
                    participant_categories.update(object_categories)
                    if normalize_text(participant_value) == normalize_text(
                        proposition.object_text
                    ):
                        participant_value = object_text
                entity_ref, literal_value = value_reference(
                    participant_value,
                    participant.value_kind,
                    participant_categories,
                    citation,
                )
                semantic_role = _normalized_participant_role(participant.role)
                if entity_ref:
                    participants.append(
                        EventParticipantCandidate(
                            role=semantic_role, entity_ref=entity_ref
                        )
                    )
                elif literal_value:
                    participants.append(
                        EventParticipantCandidate(
                            role=semantic_role, literal_value=literal_value
                        )
                    )
            participant_values = {
                normalize_text(participant.value_text)
                for participant in proposition.participants
            }
            for value, kind, categories, role in (
                    (
                        subject_text,
                        subject_kind,
                        subject_categories,
                        proposition.subject_role,
                    ),
                    (
                        object_text,
                        object_kind,
                        object_categories,
                        proposition.object_role,
                    ),
                ):
                    if not value.strip() or normalize_text(value) in participant_values:
                        continue
                    entity_ref, literal_value = value_reference(
                        value, kind, categories, citation
                    )
                    semantic_role = _normalized_participant_role(role)
                    if entity_ref:
                        participants.append(
                            EventParticipantCandidate(
                                role=semantic_role, entity_ref=entity_ref
                            )
                        )
                    elif literal_value:
                        participants.append(
                            EventParticipantCandidate(
                                role=semantic_role, literal_value=literal_value
                            )
                        )
            source_role = (
                str(session["turns"][citation.turn_index].get("role") or "")
                if 0 <= citation.turn_index < len(session["turns"])
                else ""
            )
            source_reference: str | None = None
            if re.search(r"\b(?:i|me|my|we|our)\b", citation.excerpt, re.IGNORECASE):
                source_reference = source_role if source_role in _RESERVED_ENTITY_REFS else None
            elif source_role == "assistant" and re.search(
                r"\b(?:you|your)\b", citation.excerpt, re.IGNORECASE
            ):
                source_reference = "user"
            if source_reference and not any(
                participant.entity_ref == source_reference for participant in participants
            ):
                participants.append(
                    EventParticipantCandidate(
                        role="actor",
                        entity_ref=source_reference,
                    )
                )
            if not participants and source_role in _RESERVED_ENTITY_REFS:
                participants.append(
                    EventParticipantCandidate(role="source", entity_ref=source_role)
                )
            if not participants:
                continue
            status = (
                modality
                if modality in _EVENT_STATUSES
                else "unknown"
            )
            events.append(
                EventCandidate(
                    event_id=f"e{len(events) + 1}",
                    citation=citation,
                    event_type=predicate,
                    status=status,
                    participants=participants,
                    event_date=proposition.event_date,
                    quantities=quantities,
                    confidence=proposition.confidence,
                )
            )
            continue

        source_role = (
            str(session["turns"][citation.turn_index].get("role") or "")
            if 0 <= citation.turn_index < len(session["turns"])
            else ""
        )
        subject_ref, _ = value_reference(
            subject_text,
            subject_kind,
            subject_categories,
            citation,
        )
        if not subject_ref:
            if source_role in _RESERVED_ENTITY_REFS:
                subject_ref = source_role
        object_ref, object_text = value_reference(
            object_text,
            object_kind,
            object_categories,
            citation,
        )
        supersession_scope = proposition.supersession_scope
        if not subject_ref or not (object_ref or object_text):
            continue
        assertion_mode = (
            modality
            if modality in _ASSERTION_MODES
            else "asserted"
        )
        relations.append(
            RelationCandidate(
                relation_id=f"r{len(relations) + 1}",
                citation=citation,
                subject_ref=subject_ref,
                predicate=predicate,
                object_ref=object_ref,
                object_text=object_text,
                assertion_mode=assertion_mode,
                quantity=quantities[0] if quantities else None,
                valid_from=proposition.event_date,
                supersession_scope=supersession_scope,
                confidence=proposition.confidence,
            )
        )

    for turn_index, turn in enumerate(session["turns"]):
        content = str(turn.get("content") or "")
        ordered_list = _ordered_list_items(content)
        if ordered_list is None:
            continue
        label, items = ordered_list
        citation = CandidateCitation(turn_index=turn_index, excerpt=content)
        list_mention = ensure_mention(label, "document", [], citation)
        if list_mention is None:
            continue
        for item in items:
            relations.append(
                RelationCandidate(
                    relation_id=f"r{len(relations) + 1}",
                    citation=citation,
                    subject_ref=list_mention.mention_id,
                    predicate="includes_item",
                    object_text=item,
                    assertion_mode="asserted",
                    confidence=1.0,
                )
            )

    return AtomicMemoryV2SessionCandidate(
        session_id=session_id,
        entities=entities,
        events=events,
        relations=relations,
        table_cells=_markdown_table_candidates(session),
    )


def source_content_hash(session: dict) -> str:
    encoded = json.dumps(
        {
            "session_id": session["session_id"],
            "date": session["date"],
            "turns": session["turns"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip()).casefold()


def normalize_key(value: str) -> str:
    return _KEY_RE.sub("_", normalize_text(value)).strip("_") or "unknown"


def normalize_category(value: str) -> str:
    return normalize_key(value)


def _literal_supported_by_citation(value: str, citation: NormalizedCitation) -> bool:
    """Require model-proposed literal values to be recoverable from exact evidence."""
    normalized_value = normalize_text(value)
    return bool(
        normalized_value
        and normalized_value in normalize_text(citation.excerpt)
    )


def _fingerprint(prefix: str, payload: dict) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _candidate_citation(
    session: dict,
    citation: CandidateCitation,
    *,
    included_roles: set[str],
) -> tuple[NormalizedCitation | None, str | None]:
    turns = session["turns"]
    if citation.turn_index >= len(turns):
        return None, "citation_turn_out_of_range"
    turn = turns[citation.turn_index]
    role = str(turn.get("role") or "")
    if role not in {"user", "assistant", "tool"}:
        return None, "citation_role_invalid"
    if role not in included_roles:
        return None, "citation_role_out_of_scope"
    content = str(turn.get("content") or "")
    local_offset = content.find(citation.excerpt)
    if local_offset < 0:
        return None, "citation_excerpt_not_exact"
    base_offset = int(turn.get("source_char_start") or 0)
    source_turn_id = str(
        turn.get("source_turn_id")
        if turn.get("source_turn_id") is not None
        else citation.source_turn_id or citation.turn_index
    )
    return (
        NormalizedCitation(
            session_id=str(session["session_id"]),
            turn_index=citation.turn_index,
            speaker=role,
            excerpt=citation.excerpt,
            source_turn_id=source_turn_id,
            start_char=base_offset + local_offset,
            end_char=base_offset + local_offset + len(citation.excerpt),
            source_content_hash=source_content_hash(session),
        ),
        None,
    )


def _canonical_surface(mentions: list[EntityMentionCandidate]) -> str:
    def score(mention: EntityMentionCandidate) -> tuple[int, int, str]:
        surface = mention.surface_text.strip()
        generic = normalize_text(surface).split(" ", 1)[0] in {
            "a", "an", "my", "our", "the", "their", "this", "your",
        }
        named = any(character.isupper() for character in surface)
        return (int(named and not generic), len(surface), normalize_text(surface))

    return max(mentions, key=score).surface_text.strip()


def _entity_key(kind: EntityKind, canonical_name: str) -> str:
    return f"entity:{kind}:{normalize_key(canonical_name)}"


def _resolve_ref(reference: str, mention_to_entity: dict[str, str]) -> str | None:
    if reference in _RESERVED_ENTITY_REFS:
        return reference
    return mention_to_entity.get(reference)


def normalize_atomic_memory_v2(
    session: dict,
    candidate: AtomicMemoryV2SessionCandidate,
    *,
    included_roles: set[str] | None = None,
    processed_turn_indices: Iterable[int] | None = None,
    extraction_complete: bool = True,
    output_truncated: bool = False,
    category_classification_complete: bool = False,
    category_scopes: Iterable[str] = (),
) -> AtomicMemoryV2NormalizedSession:
    """Validate and normalize an untrusted semantic proposal deterministically."""
    if candidate.session_id != str(session["session_id"]):
        raise ValueError("semantic_candidate_session_mismatch")
    roles = included_roles or {"user", "assistant", "tool"}
    invalid: Counter[str] = Counter()

    mention_by_id: dict[str, EntityMentionCandidate] = {}
    mention_citations: dict[str, NormalizedCitation] = {}
    for mention in candidate.entities:
        if mention.mention_id in mention_by_id:
            invalid["duplicate_mention_id"] += 1
            continue
        citation, reason = _candidate_citation(session, mention.citation, included_roles=roles)
        if reason:
            invalid[reason] += 1
            continue
        if normalize_text(mention.surface_text) not in normalize_text(citation.excerpt):
            invalid["entity_surface_not_in_citation"] += 1
            continue
        mention_by_id[mention.mention_id] = mention
        mention_citations[mention.mention_id] = citation

    parent = {mention_id: mention_id for mention_id in mention_by_id}

    def root(mention_id: str) -> str:
        while parent[mention_id] != mention_id:
            parent[mention_id] = parent[parent[mention_id]]
            mention_id = parent[mention_id]
        return mention_id

    for mention_id, mention in mention_by_id.items():
        alias = mention.alias_of_mention_id
        if not alias:
            continue
        if alias not in mention_by_id:
            invalid["alias_reference_missing"] += 1
            continue
        if mention.entity_kind != mention_by_id[alias].entity_kind:
            invalid["alias_kind_mismatch"] += 1
            continue
        left, right = root(mention_id), root(alias)
        if left != right:
            parent[left] = right

    groups: defaultdict[str, list[EntityMentionCandidate]] = defaultdict(list)
    for mention_id, mention in mention_by_id.items():
        groups[root(mention_id)].append(mention)

    normalized_entities: list[NormalizedEntity] = []
    mention_to_entity: dict[str, str] = {}
    for mentions in groups.values():
        canonical_name = _canonical_surface(mentions)
        kind = mentions[0].entity_kind
        key = _entity_key(kind, canonical_name)
        categories = sorted(
            {
                normalize_category(category)
                for mention in mentions
                for category in mention.categories
                if normalize_category(category)
            }
        )
        source_ids = sorted(mention.mention_id for mention in mentions)
        for mention_id in source_ids:
            mention_to_entity[mention_id] = key
        normalized_entities.append(
            NormalizedEntity(
                entity_key=key,
                canonical_name=canonical_name,
                entity_kind=kind,
                aliases=sorted({mention.surface_text.strip() for mention in mentions}),
                categories=categories,
                source_mention_ids=source_ids,
                citations=[mention_citations[mention_id] for mention_id in source_ids],
            )
        )
    normalized_entities.sort(key=lambda item: item.entity_key)

    normalized_events: list[NormalizedEvent] = []
    event_by_id: dict[str, EventCandidate] = {}
    for event in candidate.events:
        if event.event_id in event_by_id:
            invalid["duplicate_event_id"] += 1
            continue
        event_by_id[event.event_id] = event
    event_parent = {event_id: event_id for event_id in event_by_id}

    def event_root(event_id: str) -> str:
        while event_parent[event_id] != event_id:
            event_parent[event_id] = event_parent[event_parent[event_id]]
            event_id = event_parent[event_id]
        return event_id

    invalid_event_aliases: set[str] = set()
    for event_id, event in event_by_id.items():
        alias = event.same_as_event_id
        if not alias:
            continue
        if alias not in event_by_id:
            invalid["event_identity_reference_missing"] += 1
            invalid_event_aliases.add(event_id)
            continue
        left, right = event_root(event_id), event_root(alias)
        if left != right:
            event_parent[left] = right
    event_groups: defaultdict[str, list[EventCandidate]] = defaultdict(list)
    for event_id, event in event_by_id.items():
        if event_id not in invalid_event_aliases:
            event_groups[event_root(event_id)].append(event)
    event_identity_keys: dict[str, str] = {}
    for events in event_groups.values():
        descriptor = {
            "session_id": session["session_id"],
            "events": sorted(
                (
                    normalize_key(event.event_type),
                    event.citation.turn_index,
                    normalize_text(event.citation.excerpt),
                )
                for event in events
            ),
        }
        identity_key = _fingerprint("event-identity", descriptor)
        for event in events:
            event_identity_keys[event.event_id] = identity_key

    for event_id, event in event_by_id.items():
        if event_id in invalid_event_aliases:
            continue
        citation, reason = _candidate_citation(session, event.citation, included_roles=roles)
        if reason:
            invalid[reason] += 1
            continue
        if event.status == "completed" and _COMPLETED_ACTION_BLOCK_RE.search(citation.excerpt):
            invalid["completed_event_not_supported_by_modality"] += 1
            continue
        participants: list[NormalizedParticipant] = []
        missing_ref = False
        for participant in event.participants:
            resolved = (
                _resolve_ref(participant.entity_ref, mention_to_entity)
                if participant.entity_ref
                else None
            )
            if participant.entity_ref and not resolved:
                invalid["event_participant_reference_missing"] += 1
                missing_ref = True
                break
            if (
                participant.literal_value
                and not _literal_supported_by_citation(
                    participant.literal_value, citation
                )
            ):
                invalid["event_literal_not_in_citation"] += 1
                missing_ref = True
                break
            participants.append(
                NormalizedParticipant(
                    role=normalize_key(participant.role),
                    entity_key=resolved,
                    literal_value=participant.literal_value,
                )
            )
        if missing_ref:
            continue
        event_type = normalize_key(event.event_type)
        quantities = [
            NormalizedQuantity(
                value=quantity.value,
                unit=normalize_key(quantity.unit),
                role=normalize_key(quantity.role),
                approximate=quantity.approximate,
            )
            for quantity in event.quantities
        ]
        payload = {
            "session_id": session["session_id"],
            "type": event_type,
            "status": event.status,
            "date": event.event_date,
            "participants": [item.model_dump(mode="json") for item in participants],
            "quantities": [item.model_dump(mode="json") for item in quantities],
            "citation": citation.model_dump(mode="json"),
        }
        normalized_events.append(
            NormalizedEvent(
                event_key=_fingerprint("event", payload),
                event_identity_key=event_identity_keys[event.event_id],
                event_type=event_type,
                status=event.status,
                participants=participants,
                event_date=event.event_date,
                quantities=quantities,
                attributes={normalize_key(k): str(v) for k, v in event.attributes.items()},
                citation=citation,
                confidence=event.confidence,
            )
        )
    normalized_events.sort(key=lambda item: item.event_key)

    normalized_relations: list[NormalizedRelation] = []
    relation_ids: set[str] = set()
    for relation in candidate.relations:
        if relation.relation_id in relation_ids:
            invalid["duplicate_relation_id"] += 1
            continue
        relation_ids.add(relation.relation_id)
        citation, reason = _candidate_citation(session, relation.citation, included_roles=roles)
        if reason:
            invalid[reason] += 1
            continue
        if (
            relation.assertion_mode == "asserted"
            and _ASSERTED_RELATION_BLOCK_RE.search(citation.excerpt)
        ):
            invalid["asserted_relation_not_supported_by_modality"] += 1
            continue
        subject = _resolve_ref(relation.subject_ref, mention_to_entity)
        object_key = (
            _resolve_ref(relation.object_ref, mention_to_entity)
            if relation.object_ref
            else None
        )
        if not subject:
            invalid["relation_subject_reference_missing"] += 1
            continue
        if relation.object_ref and not object_key:
            invalid["relation_object_reference_missing"] += 1
            continue
        if (
            relation.object_text
            and not _literal_supported_by_citation(relation.object_text, citation)
        ):
            invalid["relation_literal_not_in_citation"] += 1
            continue
        predicate = normalize_key(relation.predicate)
        quantity = (
            NormalizedQuantity(
                value=relation.quantity.value,
                unit=normalize_key(relation.quantity.unit),
                role=normalize_key(relation.quantity.role),
                approximate=relation.quantity.approximate,
            )
            if relation.quantity
            else None
        )
        supersession_key = (
            f"supersession:{subject}:{normalize_key(relation.supersession_scope)}"
            if relation.supersession_scope
            else None
        )
        payload = {
            "subject": subject,
            "predicate": predicate,
            "object_key": object_key,
            "object_text": relation.object_text,
            "mode": relation.assertion_mode,
            "quantity": quantity.model_dump(mode="json") if quantity else None,
            "valid_from": relation.valid_from,
            "supersession_key": supersession_key,
            "citation": citation.model_dump(mode="json"),
        }
        normalized_relations.append(
            NormalizedRelation(
                relation_key=_fingerprint("relation", payload),
                subject_key=subject,
                predicate=predicate,
                object_key=object_key,
                object_text=relation.object_text,
                assertion_mode=relation.assertion_mode,
                quantity=quantity,
                valid_from=relation.valid_from,
                supersession_key=supersession_key,
                citation=citation,
                confidence=relation.confidence,
            )
        )
    normalized_relations.sort(key=lambda item: item.relation_key)

    normalized_cells: list[NormalizedTableCell] = []
    cell_ids: set[str] = set()
    for cell in candidate.table_cells:
        if cell.cell_id in cell_ids:
            invalid["duplicate_table_cell_id"] += 1
            continue
        cell_ids.add(cell.cell_id)
        citation, reason = _candidate_citation(session, cell.citation, included_roles=roles)
        if reason:
            invalid[reason] += 1
            continue
        if not all(
            _literal_supported_by_citation(value, citation)
            for value in (cell.row_label, cell.column_label, cell.value_text)
        ):
            invalid["table_value_not_in_citation"] += 1
            continue
        table_key = _fingerprint(
            "table",
            {
                "session_id": session["session_id"],
                "turn_index": citation.turn_index,
                "local_table_id": normalize_key(cell.table_id),
            },
        )
        payload = {
            "table": table_key,
            "row": normalize_text(cell.row_label),
            "column": normalize_text(cell.column_label),
            "value": normalize_text(cell.value_text),
            "citation": citation.model_dump(mode="json"),
        }
        normalized_cells.append(
            NormalizedTableCell(
                cell_key=_fingerprint("cell", payload),
                table_key=table_key,
                row_label=cell.row_label.strip(),
                column_label=cell.column_label.strip(),
                value_text=cell.value_text.strip(),
                row_index=cell.row_index,
                column_index=cell.column_index,
                citation=citation,
                confidence=cell.confidence,
            )
        )
    normalized_cells.sort(key=lambda item: item.cell_key)

    eligible = [
        index
        for index, turn in enumerate(session["turns"])
        if str(turn.get("role") or "") in roles
    ]
    processed = sorted(set(processed_turn_indices if processed_turn_indices is not None else eligible))
    rejected_count = sum(invalid.values())
    coverage_complete = (
        extraction_complete
        and not output_truncated
        and rejected_count == 0
        and processed == eligible
    )
    closed_scopes = (
        sorted({normalize_category(scope) for scope in category_scopes})
        if coverage_complete and category_classification_complete
        else []
    )
    reasons = []
    if not extraction_complete:
        reasons.append("extraction_incomplete")
    if output_truncated:
        reasons.append("output_truncated")
    if processed != eligible:
        reasons.append("source_turns_incomplete")
    if rejected_count:
        reasons.append("invalid_candidates_present")
    if category_scopes and not category_classification_complete:
        reasons.append("category_classification_incomplete")

    return AtomicMemoryV2NormalizedSession(
        session_id=str(session["session_id"]),
        source_content_hash=source_content_hash(session),
        entities=normalized_entities,
        events=normalized_events,
        relations=normalized_relations,
        table_cells=normalized_cells,
        coverage=CompilerCoverageAttestation(
            eligible_turn_indices=eligible,
            processed_turn_indices=processed,
            source_coverage_complete=coverage_complete,
            extraction_complete=extraction_complete,
            output_truncated=output_truncated,
            rejected_candidate_count=rejected_count,
            closed_category_scopes=closed_scopes,
            reasons=reasons,
        ),
        invalid_by_reason=dict(sorted(invalid.items())),
    )


def semantic_signatures(normalized: AtomicMemoryV2NormalizedSession) -> set[str]:
    """Produce stable diagnostic signatures from normalized semantic records."""
    entity_names = {entity.entity_key: normalize_text(entity.canonical_name) for entity in normalized.entities}
    entity_names.update({key: key for key in _RESERVED_ENTITY_REFS})
    signatures: set[str] = set()
    for entity in normalized.entities:
        name = normalize_text(entity.canonical_name)
        signatures.add(f"entity|{name}|{entity.entity_kind}")
        signatures.update(f"category|{name}|{category}" for category in entity.categories)
        signatures.update(
            f"alias|{name}|{normalize_text(alias)}" for alias in entity.aliases
        )
    for event in normalized.events:
        signatures.add(f"event|{event.event_type}|{event.status}")
        for participant in event.participants:
            value = (
                entity_names.get(participant.entity_key or "", participant.entity_key or "")
                if participant.entity_key
                else normalize_text(participant.literal_value or "")
            )
            signatures.add(
                f"event_participant|{event.event_type}|{event.status}|{participant.role}|{value}"
            )
        for quantity in event.quantities:
            signatures.add(
                "quantity|event|"
                f"{event.event_type}|{quantity.role}|{format(quantity.value, '.15g')}|{quantity.unit}"
            )
    for relation in normalized.relations:
        subject = entity_names.get(relation.subject_key, relation.subject_key)
        obj = (
            entity_names.get(relation.object_key or "", relation.object_key or "")
            if relation.object_key
            else normalize_text(relation.object_text or "")
        )
        signatures.add(
            f"relation|{relation.predicate}|{subject}|{obj}|{relation.assertion_mode}"
        )
        if relation.quantity:
            signatures.add(
                "quantity|relation|"
                f"{relation.predicate}|{relation.quantity.role}|"
                f"{format(relation.quantity.value, '.15g')}|{relation.quantity.unit}"
            )
        if relation.supersession_key:
            signatures.add(f"supersession|{relation.predicate}|{subject}")
    for cell in normalized.table_cells:
        signatures.add(
            "table|"
            + "|".join(
                [
                    normalize_text(cell.row_label),
                    normalize_text(cell.column_label),
                    normalize_text(cell.value_text),
                ]
            )
        )
    return signatures
