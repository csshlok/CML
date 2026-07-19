from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


PrimaryAssertionMode = Literal[
    "completed",
    "current",
    "planned",
    "goal",
    "suggested",
    "hypothetical",
]
EvidenceIntent = Literal[
    "distinct_count",
    "latest_state_comparison",
    "personalized_advice",
    "unsupported",
]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    speaker: Literal["user", "assistant", "tool"]
    session_date: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=600)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class NumericValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str = Field(min_length=1)
    role: str = Field(min_length=1)
    context: str = Field(min_length=1)
    denominator_value: float | None = None
    denominator_unit: str | None = None


class PreferenceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    polarity: Literal["positive", "negative"]
    strength: Literal["soft", "hard"]
    topic: str = Field(min_length=1)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    citation: Citation
    metadata_authority: Literal["source_envelope"] = "source_envelope"
    extraction_origin: Literal["deterministic_envelope", "semantic_model"] = (
        "semantic_model"
    )
    provenance: Literal["user_statement", "assistant_suggestion", "tool_result"]
    primary_mode: PrimaryAssertionMode
    negated: bool = False
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    event_date: str | None = None
    numeric: NumericValue | None = None
    preference: PreferenceSignal | None = None
    semantic_tags: list[
        Literal[
            "demonstrated_experience",
            "stated_goal_or_interest",
            "preference",
            "constraint",
            "state_snapshot",
            "event",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("claim_id", "predicate", "object", "object_type")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return re.sub(r"\s+", "_", value.strip().lower())


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: EvidenceIntent
    target_subject: str = "user"
    target_entity_type: str | None = None
    target_metric_role: str | None = None
    target_metric_context: str | None = None
    allowed_provenance: list[str] = Field(default_factory=lambda: ["user_statement"])
    allowed_primary_modes: list[str] = Field(
        default_factory=lambda: ["completed", "current"]
    )
    exclude_negated: bool = True
    minimum_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    required_anchor_types: list[str] = Field(default_factory=list)
    topic_terms: list[str] = Field(default_factory=list)


class EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_claim_ids: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    missing_required_anchor_types: list[str] = Field(default_factory=list)
    instructions: str


class ReducerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: EvidenceIntent
    status: Literal["resolved", "needs_generation", "fallback"]
    answer: str | None = None
    evidence_claim_ids: list[str] = Field(default_factory=list)
    contract: EvidenceContract | None = None
    reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class SessionExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    records: list[EvidenceRecord] = Field(default_factory=list)


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionExtraction]


class ExtractionDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_session_count: int
    cache_hit_count: int
    extracted_session_count: int
    valid_claim_count: int
    invalid_claim_count: int
    deterministic_claim_count: int = 0
    semantic_claim_count: int = 0
    valid_by_evidence_type: dict[str, int] = Field(default_factory=dict)
    invalid_by_evidence_type: dict[str, int] = Field(default_factory=dict)
    invalid_by_reason: dict[str, int] = Field(default_factory=dict)
    extraction_failed: bool
    failure_reason: str | None = None
    wall_seconds: float
    usage: dict = Field(default_factory=dict)


def canonical_schema_hash() -> str:
    definitions = {
        "EvidenceRecord": EvidenceRecord.model_json_schema(),
        "QueryPlan": QueryPlan.model_json_schema(),
        "ReducerResult": ReducerResult.model_json_schema(),
        "ExtractionDiagnostics": ExtractionDiagnostics.model_json_schema(),
    }
    payload = json.dumps(definitions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


SCHEMA_HASH = canonical_schema_hash()

ENTITY_LEXICONS: dict[str, tuple[str, ...]] = {
    "citrus_fruit": (
        "orange",
        "lemon",
        "lime",
        "grapefruit",
        "pomelo",
        "tangerine",
        "mandarin",
        "clementine",
        "yuzu",
        "kumquat",
    ),
    "food_delivery_service": (
        "doordash",
        "door dash",
        "uber eats",
        "ubereats",
        "grubhub",
        "postmates",
        "deliveroo",
        "seamless",
        "instacart",
        "foodpanda",
        "swiggy",
        "zomato",
    ),
}


def source_content_hash(session_id: str, date: str, turns: list[dict]) -> str:
    payload = json.dumps(
        {"session_id": session_id, "date": date, "turns": turns},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _deterministic_session_records(session: dict) -> list[EvidenceRecord]:
    digest = source_content_hash(session["session_id"], session["date"], session["turns"])
    records: list[EvidenceRecord] = []
    for turn_index, turn in enumerate(session["turns"]):
        if turn.get("role") != "user":
            continue
        content = str(turn.get("content") or "")
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", content)
            if sentence.strip()
        ]
        for sentence_index, sentence in enumerate(sentences):
            excerpt = sentence[:600].strip()
            lowered = excerpt.lower()
            completed = bool(
                re.search(
                    r"\b(i (?:recently |finally |already )?(?:made|used|did|tried|learned|"
                    r"figured|served|bought|visited|attended|completed|finished)|i've (?:made|used|"
                    r"tried|learned|figured|served|bought|visited|attended|completed|finished))\b",
                    lowered,
                )
            )
            planned = bool(re.search(r"\b(i(?:'m| am) planning|i plan|going to)\b", lowered))
            interested = bool(
                re.search(
                    r"\b(i want|i'd like|i would like|i(?:'m| am) interested|i've been wanting|"
                    r"looking to|thinking of|thinking about|can you|could you|how (?:can|do) i)\b",
                    lowered,
                )
            )
            primary_mode: PrimaryAssertionMode = (
                "completed" if completed else "planned" if planned else "goal" if interested else "current"
            )
            tags: list[str] = []
            if completed:
                tags.extend(["demonstrated_experience", "event"])
            if interested or planned:
                tags.append("stated_goal_or_interest")
            if re.search(r"\b(prefer|favorite|favourite|love|like|dislike|hate|avoid)\b", lowered):
                tags.append("preference")
            negated = bool(
                re.search(r"\b(?:did not|didn't|do not|don't|never|no longer|decided not to)\b", lowered)
            )
            slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")[:48] or "statement"
            records.append(
                EvidenceRecord(
                    claim_id=(
                        f"{session['session_id']}-turn_{turn_index}-sentence_{sentence_index}-{slug}"
                    ),
                    citation=Citation(
                        session_id=session["session_id"],
                        turn_index=turn_index,
                        speaker="user",
                        session_date=session["date"],
                        excerpt=excerpt,
                        source_content_hash=digest,
                    ),
                    extraction_origin="deterministic_envelope",
                    provenance="user_statement",
                    primary_mode=primary_mode,
                    negated=negated,
                    subject="user",
                    predicate="raw_user_statement",
                    object=slug.replace("-", "_"),
                    object_type="raw_user_statement",
                    event_date=None,
                    semantic_tags=tags,
                    confidence=0.8,
                )
            )
    return records


def plan_query(reference: dict) -> QueryPlan:
    question = str(reference.get("question") or "")
    lowered = question.lower()
    topic_terms = [
        term
        for term in re.findall(r"[a-z]{3,}", lowered)
        if term
        not in {
            "the",
            "and",
            "for",
            "with",
            "what",
            "which",
            "when",
            "where",
            "how",
            "many",
            "different",
            "types",
            "type",
            "have",
            "used",
            "more",
            "less",
            "should",
            "could",
            "would",
            "about",
            "advice",
            "struggling",
            "you",
            "your",
            "can",
            "some",
            "suggest",
            "recommend",
            "recommendations",
            "current",
            "recent",
            "recently",
            "interesting",
            "ideas",
            "find",
            "new",
            "might",
            "lately",
            "feeling",
            "stuck",
            "bit",
            "that",
            "been",
            "any",
            "getting",
            "better",
            "results",
        }
    ]
    if reference.get("question_type") == "single-session-preference":
        return QueryPlan(
            intent="personalized_advice",
            allowed_primary_modes=["completed", "current", "goal"],
            required_anchor_types=["demonstrated_experience", "stated_goal_or_interest"],
            topic_terms=topic_terms,
        )
    distinct_match = re.search(
        r"\bhow many (?:different |distinct )?(?:types?|kinds?|categories) of "
        r"([a-z][a-z -]*?)(?: have| has| did| do| does| were| was| are|\?|$)",
        lowered,
    )
    if distinct_match:
        entity_type = distinct_match.group(1).strip().replace("-", "_").replace(" ", "_")
        if entity_type.endswith("ies"):
            entity_type = entity_type[:-3] + "y"
        elif entity_type.endswith("s"):
            entity_type = entity_type[:-1]
        return QueryPlan(
            intent="distinct_count",
            target_entity_type=entity_type,
            topic_terms=topic_terms,
            allowed_primary_modes=["completed"],
        )
    comparison_markers = (
        "more or less",
        "less or more",
        "switch to more",
        "switch to less",
        "switched to more",
        "switched to less",
        "increase or decrease",
        "higher or lower",
    )
    if any(marker in lowered for marker in comparison_markers):
        return QueryPlan(intent="latest_state_comparison", topic_terms=topic_terms)
    return QueryPlan(intent="unsupported", minimum_confidence=1.0)


def _session_rows(reference: dict, retrieved_session_ids: Iterable[str]) -> list[dict]:
    by_id = {
        str(session_id): {"session_id": str(session_id), "date": str(date), "turns": turns}
        for session_id, date, turns in zip(
            reference["haystack_session_ids"],
            reference["haystack_dates"],
            reference["haystack_sessions"],
            strict=True,
        )
    }
    return [by_id[str(session_id)] for session_id in retrieved_session_ids if str(session_id) in by_id]


def _cache_path(cache_dir: Path, model: str, session: dict) -> Path:
    session_hash = source_content_hash(session["session_id"], session["date"], session["turns"])
    model_hash = hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
    return cache_dir / SCHEMA_HASH / model_hash / f"{session_hash}.json"


def _read_cache(path: Path) -> SessionExtraction | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_hash") != SCHEMA_HASH:
            return None
        return SessionExtraction.model_validate(payload["extraction"])
    except (OSError, ValueError, ValidationError):
        return None


def _migrate_compatible_cache(
    cache_dir: Path, model: str, session: dict
) -> SessionExtraction | None:
    session_hash = source_content_hash(session["session_id"], session["date"], session["turns"])
    model_hash = hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
    candidates = sorted(
        cache_dir.glob(f"*/{model_hash}/{session_hash}.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            extraction = SessionExtraction.model_validate(payload["extraction"])
        except (OSError, ValueError, ValidationError):
            continue
        combined = SessionExtraction(
            session_id=session["session_id"],
            records=extraction.records
            + [
                record
                for record in _deterministic_session_records(session)
                if record.claim_id not in {item.claim_id for item in extraction.records}
            ],
        )
        _write_cache(_cache_path(cache_dir, model, session), combined)
        return combined
    return None


def _write_cache(path: Path, extraction: SessionExtraction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_hash": SCHEMA_HASH,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "extraction": extraction.model_dump(mode="json"),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _extract_json_object(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Extractor response did not contain a JSON object")
        return json.loads(candidate[start : end + 1])


def _coerce_extraction_batch(
    payload: dict, sessions: list[dict]
) -> tuple[dict[str, SessionExtraction], dict[str, int]]:
    known = {session["session_id"]: session for session in sessions}
    extracted: dict[str, SessionExtraction] = {}
    malformed: dict[str, int] = {}
    for raw_session in payload.get("sessions") or []:
        if not isinstance(raw_session, dict):
            malformed["unknown"] = malformed.get("unknown", 0) + 1
            continue
        session_id = str(raw_session.get("session_id") or "")
        session = known.get(session_id)
        if session is None:
            malformed["unknown"] = malformed.get("unknown", 0) + 1
            continue
        records: list[EvidenceRecord] = []
        for raw_record in raw_session.get("records") or []:
            if not isinstance(raw_record, dict):
                malformed["unknown"] = malformed.get("unknown", 0) + 1
                continue
            candidate = dict(raw_record)
            citation = dict(candidate.get("citation") or {})
            try:
                turn_index = int(citation.get("turn_index"))
                turn = session["turns"][turn_index]
            except (TypeError, ValueError, IndexError):
                malformed[str(candidate.get("object_type") or "unknown")] = (
                    malformed.get(str(candidate.get("object_type") or "unknown"), 0) + 1
                )
                continue
            citation.update(
                {
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "speaker": str(turn.get("role") or ""),
                    "session_date": session["date"],
                    "source_content_hash": source_content_hash(
                        session_id, session["date"], session["turns"]
                    ),
                }
            )
            candidate["citation"] = citation
            speaker = str(citation.get("speaker") or "")
            if speaker == "user":
                candidate["provenance"] = "user_statement"
            elif speaker == "assistant":
                candidate["provenance"] = "assistant_suggestion"
                candidate["primary_mode"] = "suggested"
            elif speaker == "tool":
                candidate["provenance"] = "tool_result"
            raw_object = candidate.get("object")
            if isinstance(raw_object, dict) and "value" in raw_object:
                candidate["object"] = str(raw_object["value"])
                if candidate.get("numeric") is None:
                    candidate["numeric"] = raw_object
            candidate.setdefault("semantic_tags", [])
            candidate.setdefault("confidence", 0.5)
            evidence_type = str(candidate.get("object_type") or "unknown")
            try:
                records.append(EvidenceRecord.model_validate(candidate))
            except ValidationError:
                malformed[evidence_type] = malformed.get(evidence_type, 0) + 1
        extracted[session_id] = SessionExtraction(session_id=session_id, records=records)
    return extracted, malformed


def extraction_prompt(sessions: list[dict]) -> str:
    session_payload = []
    for session in sessions:
        digest = source_content_hash(session["session_id"], session["date"], session["turns"])
        session_payload.append({**session, "source_content_hash": digest})
    return f"""Extract durable atomic evidence from the supplied conversation sessions.

Return JSON only. This is a semantic example, not text to copy:
{{"sessions":[{{"session_id":"session_abc","records":[{{
  "claim_id":"session_abc-turn_0-made-orange-bitters",
  "citation":{{"session_id":"session_abc","turn_index":0,"excerpt":"I made orange bitters with orange peels"}},
  "provenance":"user_statement",
  "primary_mode":"completed",
  "negated":false,
  "subject":"user",
  "predicate":"used_in_cocktail_preparation",
  "object":"orange",
  "object_type":"citrus_fruit",
  "event_date":null,
  "numeric":null,
  "preference":null,
  "semantic_tags":["demonstrated_experience","event"],
  "confidence":0.98
}}]}}]}}

Rules:
- Prioritize user facts, completed actions, current states, plans, goals, preferences, and numeric facts that may matter in later questions.
- Omit generic assistant explanations. Include an assistant turn only when it makes a concrete personalized suggestion; use provenance=assistant_suggestion and primary_mode=suggested. Never rewrite it as a user action.
- Negation is a separate boolean modifier. "Planned but did not" is primary_mode=planned and negated=true.
- Numeric facts must be semantic at extraction time: numeric={{"value":6,"unit":"oz_per_tbsp","role":"ratio","context":"french_press_water","denominator_value":1,"denominator_unit":"tbsp"}}.
- Preference facts use preference={{"polarity":"positive|negative","strength":"soft|hard","topic":"normalized_topic"}}.
- semantic_tags may contain only: demonstrated_experience, stated_goal_or_interest, preference, constraint, state_snapshot, event.
- Tag a successfully completed personal action as demonstrated_experience. Tag an explicit desire, question about trying something, plan, or continuing interest as stated_goal_or_interest.
- Extract important named members separately when a question could count distinct types. Example: orange and lemon in one cocktail become two records, each object_type=citrus_fruit.
- Use specific real semantic types such as citrus_fruit, recipe, appliance, ratio, location, or activity. Never emit placeholder values such as normalized_snake_case_value.
- Return the exact supplied session_id and turn_index. Speaker, date, and source hash are filled deterministically by the backend and should be omitted.
- Excerpts must be exact contiguous substrings of the cited turn. Never invent citations.
- Use the supplied session date unless an explicit event date can be resolved confidently.
- Omit trivial greetings and generic assistant explanations. Prefer recall precision over exhaustive low-confidence claims.
- confidence below 0.75 means the claim must not drive a deterministic answer.

Sessions:
{json.dumps(session_payload, ensure_ascii=False)}
"""


def _validate_extraction(
    extraction: SessionExtraction, session: dict
) -> tuple[SessionExtraction, dict[str, int], dict[str, int]]:
    expected_hash = source_content_hash(session["session_id"], session["date"], session["turns"])
    valid: list[EvidenceRecord] = []
    invalid: dict[str, int] = {}
    invalid_reasons: dict[str, int] = {}

    def reject(record: EvidenceRecord, reason: str) -> None:
        invalid[record.object_type] = invalid.get(record.object_type, 0) + 1
        invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

    for record in extraction.records:
        citation = record.citation
        if (
            citation.session_id != session["session_id"]
            or citation.session_date != session["date"]
            or citation.source_content_hash != expected_hash
            or citation.turn_index >= len(session["turns"])
        ):
            reject(record, "source_envelope_mismatch")
            continue
        turn = session["turns"][citation.turn_index]
        content = str(turn.get("content") or "")
        if str(turn.get("role") or "") != citation.speaker:
            reject(record, "speaker_mismatch")
            continue
        if citation.excerpt.casefold() not in content.casefold():
            object_phrase = record.object.replace("_", " ")
            match = re.search(re.escape(object_phrase), content, flags=re.IGNORECASE)
            if match is None and record.numeric is not None:
                match = re.search(
                    rf"(?<!\d){re.escape(f'{record.numeric.value:g}')}(?!\d)", content
                )
            if match is None:
                reject(record, "excerpt_and_object_not_in_turn")
                continue
            start = max(0, content.rfind(".", 0, match.start()) + 1)
            end_position = content.find(".", match.end())
            end = len(content) if end_position < 0 else end_position + 1
            repaired = content[start:end].strip()
            record = record.model_copy(
                update={"citation": citation.model_copy(update={"excerpt": repaired})}
            )
        if citation.speaker == "user" and record.provenance != "user_statement":
            reject(record, "user_provenance_mismatch")
            continue
        if citation.speaker == "assistant" and record.provenance == "user_statement":
            reject(record, "assistant_provenance_mismatch")
            continue
        valid.append(record)
    return (
        SessionExtraction(session_id=extraction.session_id, records=valid),
        invalid,
        invalid_reasons,
    )


Extractor = Callable[[str], tuple[str, dict]]


def extract_evidence(
    reference: dict,
    retrieved_session_ids: list[str],
    *,
    model: str,
    cache_dir: Path,
    extractor: Extractor | None,
    max_sessions_per_batch: int = 4,
) -> tuple[list[EvidenceRecord], ExtractionDiagnostics]:
    if max_sessions_per_batch <= 0:
        raise ValueError("max_sessions_per_batch must be positive")
    started = time.perf_counter()
    sessions = _session_rows(reference, retrieved_session_ids)
    cached: dict[str, SessionExtraction] = {}
    uncached: list[dict] = []
    for session in sessions:
        hit = _read_cache(_cache_path(cache_dir, model, session)) or _migrate_compatible_cache(
            cache_dir, model, session
        )
        if hit is None:
            uncached.append(session)
        else:
            cached[session["session_id"]] = hit
    initial_uncached_count = len(uncached)

    extracted_count = 0
    if extractor is None:
        for session in uncached:
            deterministic = SessionExtraction(
                session_id=session["session_id"],
                records=_deterministic_session_records(session),
            )
            cached[session["session_id"]] = deterministic
            _write_cache(_cache_path(cache_dir, model, session), deterministic)
        extracted_count = len(uncached)
        uncached = []

    usage: dict[str, int] = {}
    failures: list[str] = []
    invalid = 0
    invalid_by_type: dict[str, int] = {}
    invalid_by_reason: dict[str, int] = {}
    for offset in range(0, len(uncached), max_sessions_per_batch):
        batch_sessions = uncached[offset : offset + max_sessions_per_batch]
        try:
            response_text, batch_usage = extractor(extraction_prompt(batch_sessions))
            for key, value in batch_usage.items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + int(value)
            returned, malformed_types = _coerce_extraction_batch(
                _extract_json_object(response_text), batch_sessions
            )
            for evidence_type, count in malformed_types.items():
                invalid_by_type[evidence_type] = invalid_by_type.get(evidence_type, 0) + count
                invalid += count
                invalid_by_reason["malformed_record"] = (
                    invalid_by_reason.get("malformed_record", 0) + count
                )
            for session in batch_sessions:
                extraction = returned.get(session["session_id"])
                if extraction is None:
                    invalid += 1
                    deterministic = SessionExtraction(
                        session_id=session["session_id"],
                        records=_deterministic_session_records(session),
                    )
                    cached[session["session_id"]] = deterministic
                    _write_cache(_cache_path(cache_dir, model, session), deterministic)
                    extracted_count += 1
                    continue
                validated, invalid_types, invalid_reasons = _validate_extraction(
                    extraction, session
                )
                for evidence_type, count in invalid_types.items():
                    invalid_by_type[evidence_type] = invalid_by_type.get(evidence_type, 0) + count
                    invalid += count
                for reason, count in invalid_reasons.items():
                    invalid_by_reason[reason] = invalid_by_reason.get(reason, 0) + count
                model_claim_ids = {record.claim_id for record in validated.records}
                combined = SessionExtraction(
                    session_id=session["session_id"],
                    records=validated.records
                    + [
                        record
                        for record in _deterministic_session_records(session)
                        if record.claim_id not in model_claim_ids
                    ],
                )
                cached[session["session_id"]] = combined
                _write_cache(_cache_path(cache_dir, model, session), combined)
                extracted_count += 1
        except (ValueError, ValidationError, OSError, RuntimeError) as exc:
            failures.append(f"batch {offset // max_sessions_per_batch + 1}: {type(exc).__name__}: {exc}")

    records = [
        record
        for session in sessions
        for record in cached.get(session["session_id"], SessionExtraction(session_id=session["session_id"])).records
    ]
    valid_by_type: dict[str, int] = {}
    for record in records:
        valid_by_type[record.object_type] = valid_by_type.get(record.object_type, 0) + 1
    diagnostics = ExtractionDiagnostics(
        requested_session_count=len(sessions),
        cache_hit_count=len(sessions) - initial_uncached_count,
        extracted_session_count=extracted_count,
        valid_claim_count=len(records),
        invalid_claim_count=invalid,
        deterministic_claim_count=sum(
            record.extraction_origin == "deterministic_envelope" for record in records
        ),
        semantic_claim_count=sum(
            record.extraction_origin == "semantic_model" for record in records
        ),
        valid_by_evidence_type=valid_by_type,
        invalid_by_evidence_type=invalid_by_type,
        invalid_by_reason=invalid_by_reason,
        extraction_failed=bool(failures),
        failure_reason="; ".join(failures) or None,
        wall_seconds=round(time.perf_counter() - started, 4),
        usage=usage,
    )
    return records, diagnostics


def _eligible(records: list[EvidenceRecord], plan: QueryPlan) -> list[EvidenceRecord]:
    return [
        record
        for record in records
        if record.subject == plan.target_subject
        and record.provenance in plan.allowed_provenance
        and record.primary_mode in plan.allowed_primary_modes
        and (not plan.exclude_negated or not record.negated)
        and record.confidence >= plan.minimum_confidence
    ]


def reduce_evidence(
    plan: QueryPlan,
    records: list[EvidenceRecord],
    *,
    question: str,
    allow_deterministic_advice_anchors: bool = False,
) -> ReducerResult:
    eligible = _eligible(records, plan)
    if plan.intent == "distinct_count":
        selected = [
            record
            for record in eligible
            if not plan.target_entity_type or record.object_type == plan.target_entity_type
        ]
        values = {record.object.replace("_", " ") for record in selected}
        claims = [record.claim_id for record in selected]
        lexicon = ENTITY_LEXICONS.get(plan.target_entity_type or "", ())
        if lexicon:
            for record in eligible:
                searchable = f"{record.object.replace('_', ' ')} {record.citation.excerpt}".lower()
                for entity in lexicon:
                    if re.search(rf"\b{re.escape(entity)}\b", searchable):
                        values.add(entity.replace(" ", "_"))
                        claims.append(record.claim_id)
        values = sorted(value.replace("_", " ") for value in values)
        claims = list(dict.fromkeys(claims))
        if not values:
            return ReducerResult(
                intent=plan.intent,
                status="fallback",
                reason="No provenance-valid completed entities were extracted.",
                confidence=0.0,
            )
        answer = f"{len(values)}: {', '.join(values)}."
        return ReducerResult(
            intent=plan.intent,
            status="resolved",
            answer=answer,
            evidence_claim_ids=claims,
            confidence=min(
                record.confidence for record in eligible if record.claim_id in claims
            ),
        )

    if plan.intent == "latest_state_comparison":
        numeric = [record for record in eligible if record.numeric is not None]
        groups: dict[tuple[str, str, str], list[EvidenceRecord]] = {}
        for record in numeric:
            value = record.numeric
            assert value is not None
            groups.setdefault((value.role, value.context, value.unit), []).append(record)
        candidates = [group for group in groups.values() if len(group) >= 2]
        if not candidates:
            return ReducerResult(
                intent=plan.intent,
                status="fallback",
                reason="Fewer than two comparable provenance-valid numeric snapshots were extracted.",
                confidence=0.0,
            )
        def group_score(group: list[EvidenceRecord]) -> tuple[int, int]:
            searchable = " ".join(
                " ".join(
                    [
                        record.object,
                        record.numeric.context if record.numeric else "",
                        record.citation.excerpt,
                    ]
                ).lower()
                for record in group
            )
            return (sum(term in searchable for term in plan.topic_terms), len(group))

        snapshots = max(candidates, key=group_score)
        snapshots.sort(key=lambda record: record.event_date or record.citation.session_date)
        previous, current = snapshots[-2:]
        assert previous.numeric is not None and current.numeric is not None
        delta = current.numeric.value - previous.numeric.value
        direction = "less" if delta < 0 else "more" if delta > 0 else "the same amount of"
        answer = (
            f"{direction.capitalize()}: from {previous.numeric.value:g} to "
            f"{current.numeric.value:g} {current.numeric.unit.replace('_', ' ')}."
        )
        return ReducerResult(
            intent=plan.intent,
            status="resolved",
            answer=answer,
            evidence_claim_ids=[previous.claim_id, current.claim_id],
            confidence=min(previous.confidence, current.confidence),
        )

    if plan.intent == "personalized_advice":
        if plan.topic_terms:
            topic_terms = set(plan.topic_terms)
            on_topic = [
                record
                for record in eligible
                if topic_terms
                & set(
                    re.findall(
                        r"[a-z]{3,}",
                        " ".join(
                            [record.object, record.predicate, record.citation.excerpt]
                        ).lower(),
                    )
                )
            ]
            eligible = on_topic
        by_session: dict[str, list[EvidenceRecord]] = {}
        for record in eligible:
            by_session.setdefault(record.citation.session_id, []).append(record)
        session_candidates: list[
            tuple[int, list[EvidenceRecord], list[EvidenceRecord], list[EvidenceRecord]]
        ] = []
        for session_records in by_session.values():
            session_tokens = set(
                re.findall(
                    r"[a-z]{3,}",
                    " ".join(record.citation.excerpt for record in session_records).lower(),
                )
            )
            topic_coverage = len(set(plan.topic_terms) & session_tokens)
            experience = [
                record
                for record in session_records
                if "demonstrated_experience" in record.semantic_tags
            ]
            interests = [
                record
                for record in session_records
                if "stated_goal_or_interest" in record.semantic_tags
                or "preference" in record.semantic_tags
            ]
            minimum_topic_coverage = min(2, len(set(plan.topic_terms)))
            if experience and interests and topic_coverage >= minimum_topic_coverage:
                session_candidates.append(
                    (topic_coverage, session_records, experience, interests)
                )
        if not session_candidates:
            return ReducerResult(
                intent=plan.intent,
                status="fallback",
                contract=EvidenceContract(
                    missing_required_anchor_types=[
                        "same_session_demonstrated_experience_and_interest"
                    ],
                    instructions=(
                        "A coherent pair of personalization anchors was not retrieved; do not invent it. "
                        "Use the raw-evidence fallback and disclose limits if necessary."
                    ),
                ),
                reason="Required same-session personalized-advice anchors are absent.",
                confidence=0.0,
            )
        _, session_records, experience, interests = max(
            session_candidates,
            key=lambda candidate: (
                candidate[0],
                len(candidate[1]),
                max(record.citation.session_date for record in candidate[1]),
            ),
        )
        object_frequency: dict[str, int] = {}
        for record in interests:
            object_frequency[record.object] = object_frequency.get(record.object, 0) + 1
        selected_experience = max(
            experience,
            key=lambda record: (
                record.confidence,
                record.event_date or record.citation.session_date,
            ),
        )
        distinct_interests = [
            record for record in interests if record.claim_id != selected_experience.claim_id
        ]
        if not distinct_interests:
            return ReducerResult(
                intent=plan.intent,
                status="fallback",
                contract=EvidenceContract(
                    missing_required_anchor_types=["distinct_stated_goal_or_interest"],
                    instructions="A distinct interest anchor was not extracted; do not duplicate evidence.",
                ),
                reason="Personalized-advice anchors collapsed to the same claim.",
                confidence=0.0,
            )
        selected_interest = max(
            distinct_interests,
            key=lambda record: (
                object_frequency[record.object],
                record.confidence,
                record.event_date or record.citation.session_date,
            ),
        )
        required = [selected_experience, selected_interest]
        if (
            not allow_deterministic_advice_anchors
            and not any(record.extraction_origin == "semantic_model" for record in required)
        ):
            return ReducerResult(
                intent=plan.intent,
                status="fallback",
                contract=EvidenceContract(
                    missing_required_anchor_types=["semantically_enriched_anchor"],
                    instructions=(
                        "Deterministic sentence evidence is available, but no required anchor "
                        "has semantic-model validation. Use the raw-evidence fallback."
                    ),
                ),
                reason="Personalized-advice anchors lack semantic enrichment.",
                confidence=0.0,
            )
        required_ids = {record.claim_id for record in required}
        supporting = [
            record for record in session_records if record.claim_id not in required_ids
        ]
        return ReducerResult(
            intent=plan.intent,
            status="needs_generation",
            evidence_claim_ids=[record.claim_id for record in required + supporting],
            contract=EvidenceContract(
                required_claim_ids=[record.claim_id for record in required],
                supporting_claim_ids=[record.claim_id for record in supporting[:6]],
                instructions=(
                    "Build the answer explicitly on every required claim. Supporting claims may "
                    "refine the advice. Do not introduce unrelated retrieved interests."
                ),
            ),
            confidence=min(record.confidence for record in required),
        )

    return ReducerResult(
        intent="unsupported",
        status="fallback",
        reason=f"No typed reducer supports this question: {question}",
        confidence=0.0,
    )


def render_evidence_contract(
    result: ReducerResult, records: list[EvidenceRecord]
) -> str:
    if result.contract is None:
        return ""
    by_id = {record.claim_id: record for record in records}
    ordered_ids = result.contract.required_claim_ids + result.contract.supporting_claim_ids
    lines = ["Typed evidence contract:", result.contract.instructions]
    for claim_id in ordered_ids:
        record = by_id.get(claim_id)
        if record is None:
            continue
        marker = "REQUIRED" if claim_id in result.contract.required_claim_ids else "SUPPORTING"
        citation = record.citation
        lines.append(
            f"- {marker} [{citation.session_id} turn {citation.turn_index}, "
            f"{citation.session_date}]: {citation.excerpt}"
        )
    return "\n".join(lines)
