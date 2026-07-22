from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ATOMIC_MEMORY_V2_CONTRACT_VERSION = "atomic-memory-v2-contract-v1"

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
_CATEGORY_ALIASES = {
    "academic": "educator",
    "attorney": "lawyer",
    "counselor": "therapist",
    "clinician": "doctor",
    "educator": "educator",
    "lawyer": "lawyer",
    "medical doctor": "doctor",
    "physician": "doctor",
    "professor": "educator",
}
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


class EntityMentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention_id: str = Field(min_length=1)
    citation: CandidateCitation
    surface_text: str = Field(min_length=1)
    entity_kind: EntityKind
    categories: list[str] = Field(default_factory=list)
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
    participants: list[EventParticipantCandidate] = Field(min_length=1)
    same_as_event_id: str | None = None
    event_date: str | None = None
    quantities: list[QuantityCandidate] = Field(default_factory=list)
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
    entities: list[EntityMentionCandidate] = Field(default_factory=list)
    events: list[EventCandidate] = Field(default_factory=list)
    relations: list[RelationCandidate] = Field(default_factory=list)
    table_cells: list[TableCellCandidate] = Field(default_factory=list)


class AtomicMemoryV2Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[AtomicMemoryV2SessionCandidate]


class NormalizedCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_index: int
    speaker: SpeakerRole
    excerpt: str
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


def atomic_memory_v2_prompt(session: dict) -> str:
    payload = {
        "session_id": str(session["session_id"]),
        "date": str(session["date"]),
        "turns": list(session["turns"]),
    }
    return (
        "Extract question-independent durable memory as strict JSON matching the supplied schema. "
        "Cite an exact contiguous excerpt and zero-based turn_index for every item. Emit entity "
        "mentions with everyday categories and explicit alias links only when the same-session text "
        "supports identity. Emit typed events with participant roles and status; advice, wants, and "
        "plans are never completed actions. Link repeated descriptions of one event with "
        "same_as_event_id. Preserve typed quantities and relationship supersession scopes. Emit "
        "explicit relationships and one table_cells item per "
        "linked row/header/value. Use user, assistant, or tool as reserved entity refs. Do not invent "
        "canonical IDs or claim completeness/closure; the backend owns both. Preserve negation, "
        "hypotheticals, uncertainty, dates, quantities, and exact names. JSON only.\nSession:\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
    category = normalize_text(value)
    if category.endswith("s") and not category.endswith("ss"):
        category = category[:-1]
    return _CATEGORY_ALIASES.get(category, category)


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
    if citation.excerpt not in str(turn.get("content") or ""):
        return None, "citation_excerpt_not_exact"
    return (
        NormalizedCitation(
            session_id=str(session["session_id"]),
            turn_index=citation.turn_index,
            speaker=role,
            excerpt=citation.excerpt,
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
    """Produce stable fixture-comparison signatures from normalized semantic records."""
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
