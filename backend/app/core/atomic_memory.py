from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.core.claim_semantics import extract_structured_claims


ATOMIC_MEMORY_VERSION = "atomic-memory-v8"
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_QUESTION_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "did", "do", "does", "for",
    "from", "had", "has", "have", "how", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "that", "the", "to", "was", "were", "what", "when",
    "where", "which", "who", "with", "you", "your",
}
_CROSS_SESSION_QUERY_RE = re.compile(
    r"\b(how many|total|combined|all (?:the )?|which (?:ones|places|people|items)|"
    r"chronological|in order|over time|changed|change|latest|current|before|after|"
    r"first|second|third|fourth|fifth|most recent)\b",
    re.IGNORECASE,
)
_AGGREGATION_QUERY_RE = re.compile(
    r"\b(how many|total|combined|all|both|which|list|compare|comparison|"
    r"across|over time|changed|change|latest|current|earliest|most recent|"
    r"in common|different|difference|average|sum)\b",
    re.IGNORECASE,
)
_DATE_QUERY_RE = re.compile(
    r"\b(when|date|day|week|month|year|before|after|earliest|latest|elapsed|how long)\b",
    re.IGNORECASE,
)
_QUANTITY_QUERY_RE = re.compile(
    r"\b(how many|how much|total|sum|average|difference|more|most|less|"
    r"price|cost|age|number|amount|limit|gain|growth|followers?|money|spend|spent)\b",
    re.IGNORECASE,
)
_STATE_QUERY_RE = re.compile(
    r"\b(current|currently|now|latest|recent|recently|changed|change|update|"
    r"updated|no longer|increase|increased|decrease|decreased|raised|reduced|"
    r"before|used to|formerly|previously)\b",
    re.IGNORECASE,
)

QueryOperation = Literal[
    "direct_lookup",
    "current_state",
    "state_comparison",
    "aggregate_list",
    "distinct_count",
    "numeric_sum",
    "numeric_average",
    "numeric_difference",
    "temporal_difference",
    "event_order",
    "unknown",
]


class AtomicQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: QueryOperation
    target_terms: list[str] = Field(default_factory=list)
    quantity_subject_terms: list[str] = Field(default_factory=list)
    subject_scope: Literal["user", "assistant", "any"] = "any"
    required_slots: list[str] = Field(default_factory=list)
    atomic_eligible: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
_EXPLICIT_CALCULATION_RE = re.compile(
    r"\b(average|sum|total|difference|how much more|how much less|"
    r"how many|elapsed|earliest|latest|current|currently|now)\b",
    re.IGNORECASE,
)


class AtomicRouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Literal["atomic", "claim-first"]
    reason: str
    plan: AtomicQueryPlan


class AtomicContractResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    safe: bool
    operation: QueryOperation
    filled_slots: dict[str, list[str]] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    operand_fact_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class DeterministicOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested: bool = False
    resolved: bool = False
    operation: str | None = None
    result: str | None = None
    operand_fact_ids: list[str] = Field(default_factory=list)
    citation_labels: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None


class AtomicCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    speaker: Literal["user", "assistant", "tool"]
    session_date: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=1200)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AtomicQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str = Field(min_length=1)
    role: str = Field(min_length=1)


class AtomicFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1)
    citation: AtomicCitation
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    fact_kind: Literal[
        "identity",
        "attribute",
        "event",
        "state",
        "preference",
        "plan",
        "relationship",
        "recommendation",
        "list_item",
        "quantity",
        "other",
    ]
    assertion_mode: Literal["asserted", "negated", "hypothetical"] = "asserted"
    event_date: str | None = None
    observed_date: str = Field(min_length=1)
    quantity: AtomicQuantity | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)
    supersession_key: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class AtomicSourceUnitCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    speaker: Literal["user", "assistant", "tool"]
    excerpt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["facts_extracted", "processed_no_fact"]
    fact_ids: list[str] = Field(default_factory=list)


class AtomicSessionExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    facts: list[AtomicFact] = Field(default_factory=list)
    source_units: list[AtomicSourceUnitCoverage] = Field(default_factory=list)


class AtomicExtractionDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_session_count: int
    cache_hit_count: int
    extracted_session_count: int
    valid_fact_count: int
    invalid_fact_count: int
    invalid_by_reason: dict[str, int] = Field(default_factory=dict)
    deduplicated_fact_count: int
    source_unit_count: int = 0
    covered_source_unit_count: int = 0
    source_coverage_complete: bool = False
    extraction_failed: bool
    failure_reason: str | None = None
    wall_seconds: float
    usage: dict[str, int] = Field(default_factory=dict)


def source_content_hash(session_id: str, date: str, turns: list[dict]) -> str:
    payload = json.dumps(
        {"session_id": session_id, "date": date, "turns": turns},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_extraction_prompt(sessions: list[dict]) -> str:
    payload = [
        {
            "session_id": session["session_id"],
            "date": session["date"],
            "turns": session["turns"],
        }
        for session in sessions
    ]
    return f"""Compile the supplied conversations into durable, atomic memory facts.

This is WRITE-TIME extraction. You do not know any future question. Preserve facts that
could plausibly answer one later. Return JSON only in this shape:

{{"sessions":[{{"session_id":"s1","facts":[{{
  "fact_id":"s1-t2-f1",
  "citation":{{"turn_index":2,"excerpt":"exact contiguous source quotation"}},
  "subject":"user",
  "predicate":"graduated_with_degree",
  "object_text":"Business Administration",
  "fact_kind":"attribute",
  "assertion_mode":"asserted",
  "event_date":null,
  "quantity":null,
  "qualifiers":{{}},
  "supersession_key":null,
  "confidence":0.98
}}]}}]}}

Rules:
- Extract concrete facts from BOTH user and assistant turns. Assistant answers, named
  recommendations, generated lists, schedules, descriptions, and concrete explanations
  are memories too. Do not reduce every assistant fact to a suggestion.
- Split compound statements, enumerations, tables, and multiple quantities into separate
  atomic facts. Preserve list position in qualifiers when present.
- Preserve named entities, attributes, relationships, locations, actions, outcomes,
  quantities with units and roles, preferences, plans, constraints, and state changes.
- subject identifies who or what the fact is about. Use "user" only for the conversation
  user; otherwise use the explicit person, organization, object, or topic.
- event_date is the resolved event date only when explicit or safely resolvable from the
  session date. observed_date is filled by the backend and must be omitted.
- supersession_key groups replaceable states such as user:employer or user:home_city.
  Leave it null for events and facts that can coexist.
- assertion_mode distinguishes asserted, negated, and hypothetical information.
- quantity is null or {{"value":3,"unit":"items","role":"items_to_pick_up"}}.
- fact_kind must be one of identity, attribute, event, state, preference, plan,
  relationship, recommendation, list_item, quantity, other.
- Every excerpt must be an exact, contiguous substring of the cited turn and must contain
  enough text to support the fact. Never invent or paraphrase a citation.
- Do not extract greetings, boilerplate cautions, generic conversational filler, or facts
  stated only inside an obviously hypothetical example.
- Prefer recall for concrete information, but never infer an unsupported fact.

Sessions:
{json.dumps(payload, ensure_ascii=False)}
"""


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
            raise ValueError("Atomic extractor response did not contain a JSON object")
        return json.loads(candidate[start : end + 1])


def _cache_path(cache_dir: Path, model: str, session: dict) -> Path:
    digest = source_content_hash(session["session_id"], session["date"], session["turns"])
    model_hash = hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
    return cache_dir / ATOMIC_MEMORY_VERSION / model_hash / f"{digest}.json"


def _read_cache(path: Path) -> AtomicSessionExtraction | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != ATOMIC_MEMORY_VERSION:
            return None
        return AtomicSessionExtraction.model_validate(payload["extraction"])
    except (OSError, ValueError, ValidationError):
        return None


def _write_cache(path: Path, extraction: AtomicSessionExtraction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": ATOMIC_MEMORY_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "extraction": extraction.model_dump(mode="json"),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _coerce_and_validate(
    raw_session: dict,
    session: dict,
) -> tuple[AtomicSessionExtraction, Counter[str]]:
    invalid: Counter[str] = Counter()
    digest = source_content_hash(session["session_id"], session["date"], session["turns"])
    facts: list[AtomicFact] = []
    for raw_fact in raw_session.get("facts") or []:
        if not isinstance(raw_fact, dict):
            invalid["malformed_fact"] += 1
            continue
        candidate = dict(raw_fact)
        citation = dict(candidate.get("citation") or {})
        try:
            turn_index = int(citation["turn_index"])
            turn = session["turns"][turn_index]
        except (KeyError, TypeError, ValueError, IndexError):
            invalid["invalid_turn_index"] += 1
            continue
        citation.update(
            {
                "session_id": session["session_id"],
                "turn_index": turn_index,
                "speaker": str(turn.get("role") or ""),
                "session_date": session["date"],
                "source_content_hash": digest,
            }
        )
        candidate["citation"] = citation
        candidate["observed_date"] = session["date"]
        candidate.setdefault("assertion_mode", "asserted")
        candidate.setdefault("event_date", None)
        candidate.setdefault("quantity", None)
        candidate.setdefault("qualifiers", {})
        candidate.setdefault("supersession_key", None)
        candidate.setdefault("confidence", 0.5)
        try:
            fact = AtomicFact.model_validate(candidate)
        except ValidationError:
            invalid["schema_validation"] += 1
            continue
        content = str(turn.get("content") or "")
        if fact.citation.excerpt not in content:
            invalid["excerpt_not_exact"] += 1
            continue
        facts.append(fact)
    return AtomicSessionExtraction(session_id=session["session_id"], facts=facts), invalid


def deduplicate_atomic_facts(facts: Iterable[AtomicFact]) -> tuple[list[AtomicFact], int]:
    output: list[AtomicFact] = []
    positions: dict[tuple[str, int, str, str, str, str], int] = {}
    removed = 0
    for fact in facts:
        key = (
            fact.citation.session_id,
            fact.citation.turn_index,
            " ".join(fact.subject.casefold().split()),
            " ".join(fact.predicate.casefold().split()),
            " ".join(fact.object_text.casefold().split()),
            fact.assertion_mode,
        )
        position = positions.get(key)
        if position is None:
            positions[key] = len(output)
            output.append(fact)
            continue
        removed += 1
        if fact.confidence > output[position].confidence:
            output[position] = fact
    return output, removed


AtomicExtractor = Callable[[str], tuple[str, dict]]

_SMALL_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_SCALE_WORDS = {"hundred": 100, "thousand": 1000}
_NUMBER_WORD_SET = set(_SMALL_NUMBER_WORDS) | set(_NUMBER_SCALE_WORDS) | {
    "and",
    "dozen",
}


def _parse_number_words(words: list[str]) -> float | None:
    if not words or all(word == "and" for word in words):
        return None
    if words == ["dozen"]:
        return 12.0
    total = 0
    current = 0
    saw_number = False
    for word in words:
        if word == "and":
            continue
        if word == "dozen":
            current += 12
            saw_number = True
        elif word in _SMALL_NUMBER_WORDS:
            current += _SMALL_NUMBER_WORDS[word]
            saw_number = True
        elif word == "hundred":
            current = max(1, current) * 100
            saw_number = True
        elif word == "thousand":
            total += max(1, current) * 1000
            current = 0
            saw_number = True
        else:
            return None
    return float(total + current) if saw_number else None


_UNIT_WORDS = {
    "cup", "cups", "day", "days", "dollar", "dollars", "engineer", "engineers",
    "euro", "euros", "follower", "followers", "foot", "feet", "gallon", "gallons",
    "hour", "hours", "liter", "liters", "litre", "litres",
    "item", "items", "kilometer", "kilometers", "km", "meter", "meters", "mile",
    "miles", "minute", "minutes", "month", "months", "person", "people", "pound",
    "pounds", "session", "sessions", "week", "weeks", "year", "years",
}
_CURRENCY_SYMBOLS = {"$": "dollars", "€": "euros", "£": "pounds"}


def _quantity_unit(text: str, span: tuple[int, int]) -> str:
    before = text[: span[0]].rstrip()
    after = text[span[1] :].lstrip(" -–—")
    if before and before[-1] in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[before[-1]]
    if after.startswith("%"):
        return "percent"
    unit_match = re.match(r"([A-Za-z][A-Za-z_/-]{0,30})", after)
    if unit_match and unit_match.group(1).casefold() in _UNIT_WORDS:
        return unit_match.group(1).casefold()
    lowered = text.casefold()
    if re.search(
        r"\b(age|aged|older|year-old|years old|birthday|turned|mom|mother|dad|"
        r"father|parent|parents|grandparent|grandparents)\b",
        lowered,
    ):
        return "years"
    if re.search(r"[$€£]|\b(spent|cost|costs|price|paid|budget|fare|worth)\b", lowered):
        return "currency"
    return "number"


def _extract_quantities(text: str) -> list[tuple[AtomicQuantity, tuple[int, int]]]:
    results: list[tuple[AtomicQuantity, tuple[int, int]]] = []
    occupied: list[tuple[int, int]] = []
    for numeric in re.finditer(
        r"(?<![\w.])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:s\b)?(?![\w.])",
        text,
    ):
        results.append(
            (
                AtomicQuantity(
                    value=float(numeric.group(1).replace(",", "")),
                    unit=_quantity_unit(text, numeric.span()),
                    role="mentioned_quantity",
                ),
                numeric.span(),
            )
        )
        occupied.append(numeric.span())
    tokens = list(re.finditer(r"[A-Za-z]+", text))
    for start in range(len(tokens)):
        first = tokens[start].group(0).casefold()
        if first not in _NUMBER_WORD_SET or first == "and":
            continue
        words: list[str] = []
        end = start
        while end < len(tokens) and tokens[end].group(0).casefold() in _NUMBER_WORD_SET:
            words.append(tokens[end].group(0).casefold())
            end += 1
        value = _parse_number_words(words)
        if value is None:
            continue
        span_end = tokens[end - 1].end()
        span = (tokens[start].start(), span_end)
        if any(max(span[0], left) < min(span[1], right) for left, right in occupied):
            continue
        results.append(
            (
                AtomicQuantity(
                    value=value,
                    unit=_quantity_unit(text, span),
                    role="mentioned_quantity",
                ),
                span,
            )
        )
        occupied.append(span)
    results.sort(key=lambda item: item[1])
    return results


def _extract_quantity(text: str) -> tuple[AtomicQuantity, tuple[int, int]] | None:
    quantities = _extract_quantities(text)
    return quantities[0] if quantities else None


def _quantity_context(text: str, span: tuple[int, int]) -> str:
    """Return the local clause supporting one quantity in a compound sentence."""
    boundaries = [0, len(text)]
    for match in re.finditer(r"[;.!?]|,?\s+\b(?:but|whereas|while)\b\s+", text, re.I):
        boundaries.extend([match.start(), match.end()])
    left = max(boundary for boundary in boundaries if boundary <= span[0])
    right = min(boundary for boundary in boundaries if boundary >= span[1])
    return text[left:right].strip(" ,;.!?-") or text


_COUNT_ASSERTION_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:now|currently|recently|just)\s+)?"
    r"(?:have|own|lead|visited|watched|completed|attended|bought|read|met|tried|saw)\s*$",
    re.IGNORECASE,
)
_COUNTER_SNAPSHOT_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:now|currently)\s+)?(?:have|own|lead)\s*$",
    re.IGNORECASE,
)
_CATEGORY_BOUNDARIES = {
    "and", "are", "at", "because", "but", "contain", "contains", "did", "during",
    "for", "from", "had", "has", "in", "on", "that", "the", "this", "those",
    "was", "were", "which", "who", "with",
}


def _canonical_entity_category(value: str) -> str:
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z]+", value)]
    if not tokens:
        return ""
    return _canonical_term(tokens[-1])


def _count_category(text: str, span: tuple[int, int]) -> str:
    words: list[str] = []
    for token in re.findall(r"[A-Za-z]+", text[span[1] :])[:5]:
        if token.casefold() in _CATEGORY_BOUNDARIES:
            break
        words.append(token)
    return _canonical_entity_category(" ".join(words))


def _quantity_semantics(
    text: str,
    quantity: AtomicQuantity,
    span: tuple[int, int],
) -> tuple[AtomicQuantity, dict[str, str], str | None]:
    prefix = text[: span[0]]
    if not _COUNT_ASSERTION_RE.search(prefix):
        return quantity, {}, None
    category = _count_category(text, span)
    if not category:
        return quantity, {}, None
    typed = quantity.model_copy(
        update={"unit": category, "role": "declared_cardinality"}
    )
    snapshot = bool(_COUNTER_SNAPSHOT_RE.search(prefix))
    qualifiers = {
        "closed_world_category": "true",
        "entity_category": category,
        "quantity_role": "declared_cardinality",
        **({"counter_snapshot": "true"} if snapshot else {}),
    }
    key = f"user:current_quantity:{category}" if snapshot else None
    return typed, qualifiers, key


def _counter_delta(unit: str) -> tuple[str, str] | None:
    match = re.search(
        r"\bI\s+(?:(?:just|recently)\s+)?"
        r"(?:started|added|bought|acquired|adopted|hired|opened|created)\s+"
        r"(?:a|an|one)\s+(?:new\s+)?(?P<category>[A-Za-z]+(?:\s+[A-Za-z]+){0,2}?)"
        r"(?=\s+(?:at|because|for|in|on|with)\b|[.!?]|$)",
        unit,
        re.IGNORECASE,
    )
    if not match:
        return None
    category = _canonical_entity_category(match.group("category"))
    return (match.group(0), category) if category else None


def _source_units(content: str) -> list[str]:
    units: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith(("|", "- ", "* ", "+ "))
            or re.match(r"^\d+[.)]\s+", stripped)
            or len(stripped) <= 240
        ):
            units.append(stripped)
        else:
            units.extend(
                sentence.strip()
                for sentence in re.split(r"(?<=[.!?])\s+", stripped)
                if sentence.strip()
            )
    seen: set[str] = set()
    output: list[str] = []
    for unit in units:
        chunks = (
            [unit]
            if len(unit) <= 1200
            else [unit[offset : offset + 1200] for offset in range(0, len(unit), 1200)]
        )
        for chunk in chunks:
            normalized = " ".join(chunk.casefold().split())
            if not normalized or normalized in seen or re.fullmatch(r"[#*_\-| :]+", chunk):
                continue
            seen.add(normalized)
            output.append(chunk)
    return output


def _resolve_explicit_date(text: str, observed_date: str) -> str | None:
    from datetime import date, timedelta

    observed_match = re.match(r"(\d{4})/(\d{2})/(\d{2})", observed_date)
    if not observed_match:
        return None
    observed = date(*(int(part) for part in observed_match.groups()))
    iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if iso:
        try:
            return date(*(int(part) for part in iso.groups())).isoformat()
        except ValueError:
            return None
    months = {
        name: index
        for index, name in enumerate(
            ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
            start=1,
        )
    }
    named = re.search(
        r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b",
        text,
        re.I,
    )
    if named:
        try:
            return date(
                int(named.group(3) or observed.year),
                months[named.group(1).casefold()],
                int(named.group(2)),
            ).isoformat()
        except ValueError:
            return None
    lowered = text.casefold()
    if re.search(r"\byesterday\b", lowered):
        return (observed - timedelta(days=1)).isoformat()
    ago = re.search(r"\b(\d+)\s+(days?|weeks?)\s+ago\b", lowered)
    if ago:
        multiplier = 7 if ago.group(2).startswith("week") else 1
        return (observed - timedelta(days=int(ago.group(1)) * multiplier)).isoformat()
    if re.search(r"\btoday\b", lowered):
        return observed.isoformat()
    return None


def _source_coverage(session: dict, facts: list[AtomicFact]) -> list[AtomicSourceUnitCoverage]:
    coverage: list[AtomicSourceUnitCoverage] = []
    for turn_index, turn in enumerate(session["turns"]):
        speaker = str(turn.get("role") or "")
        if speaker not in {"user", "assistant", "tool"}:
            continue
        for unit_index, unit in enumerate(_source_units(str(turn.get("content") or ""))):
            supporting = [
                fact.fact_id
                for fact in facts
                if fact.citation.turn_index == turn_index
                and (
                    fact.citation.excerpt in unit
                    or unit in fact.citation.excerpt
                )
            ]
            coverage.append(
                AtomicSourceUnitCoverage(
                    unit_id=f"{session['session_id']}-t{turn_index}-u{unit_index}",
                    turn_index=turn_index,
                    speaker=speaker,
                    excerpt_hash=hashlib.sha256(unit.encode("utf-8")).hexdigest(),
                    status="facts_extracted" if supporting else "processed_no_fact",
                    fact_ids=supporting,
                )
            )
    return coverage


def deterministic_atomic_facts(session: dict) -> list[AtomicFact]:
    """Create a lossless, question-independent atomic envelope at write time."""
    digest = source_content_hash(session["session_id"], session["date"], session["turns"])
    facts: list[AtomicFact] = []
    for turn_index, turn in enumerate(session["turns"]):
        speaker = str(turn.get("role") or "")
        if speaker not in {"user", "assistant", "tool"}:
            continue
        content = str(turn.get("content") or "")
        bounded_units = _source_units(content)
        for unit_index, unit in enumerate(bounded_units):
            extracted_quantities = _extract_quantities(unit)
            quantity_details = [
                (*_quantity_semantics(unit, extracted, span), span)
                for extracted, span in extracted_quantities
            ]
            quantity = quantity_details[0][0] if quantity_details else None
            quantity_qualifiers = quantity_details[0][1] if quantity_details else {}
            quantity_key = quantity_details[0][2] if quantity_details else None
            fact_kind: str = "quantity" if quantity else "other"
            if unit.startswith("|"):
                fact_kind = "list_item"
            elif re.match(r"^(?:[-*+] |\d+[.)]\s+)", unit):
                fact_kind = "list_item"
            elif re.search(r"\b(prefer|favorite|favourite|love|like|dislike|hate|avoid)\b", unit, re.I):
                fact_kind = "preference"
            elif re.search(r"\b(plan|planning|going to|want to|would like to)\b", unit, re.I):
                fact_kind = "plan"
            elif re.search(
                r"\b(now|currently|used to|no longer|changed|updated|increased|"
                r"decreased|raised|reduced|cut back|limit|switched|moved from|"
                r"went from|previously|formerly)\b",
                unit,
                re.I,
            ):
                fact_kind = "state"
            if quantity_key:
                fact_kind = "state"
            assertion_mode = (
                "hypothetical"
                if re.search(r"\b(if|could|would|might|hypothetical)\b", unit, re.I)
                else "negated"
                if re.search(r"\b(no longer|did not|didn't|do not|don't|never)\b", unit, re.I)
                else "asserted"
            )
            facts.append(
                AtomicFact(
                    fact_id=f"{session['session_id']}-t{turn_index}-u{unit_index}",
                    citation=AtomicCitation(
                        session_id=session["session_id"],
                        turn_index=turn_index,
                        speaker=speaker,
                        session_date=session["date"],
                        excerpt=unit,
                        source_content_hash=digest,
                    ),
                    subject="user" if speaker == "user" else speaker,
                    predicate="stated",
                    object_text=unit,
                    fact_kind=fact_kind,
                    assertion_mode=assertion_mode,
                    observed_date=session["date"],
                    quantity=quantity,
                    qualifiers={
                        "atomic_origin": "deterministic_lossless",
                        **(
                            {"normalized_quantity": f"{quantity.value:g} {quantity.unit}"}
                            if quantity is not None
                            else {}
                        ),
                        **(
                            {"quantity_context": _quantity_context(unit, extracted_quantities[0][1])}
                            if extracted_quantities
                            else {}
                        ),
                        **quantity_qualifiers,
                        **(
                            {"state_signal": "true"}
                            if fact_kind == "state"
                            else {}
                        ),
                    },
                    supersession_key=quantity_key,
                    confidence=0.8,
                )
            )
            for quantity_index, (
                additional_quantity,
                additional_qualifiers,
                additional_key,
                additional_span,
            ) in enumerate(
                quantity_details[1:], start=1
            ):
                facts.append(
                    AtomicFact(
                        fact_id=(
                            f"{session['session_id']}-t{turn_index}-u{unit_index}"
                            f"-q{quantity_index}"
                        ),
                        citation=AtomicCitation(
                            session_id=session["session_id"],
                            turn_index=turn_index,
                            speaker=speaker,
                            session_date=session["date"],
                            excerpt=unit,
                            source_content_hash=digest,
                        ),
                        subject="user" if speaker == "user" else speaker,
                        predicate=f"stated_quantity_{quantity_index}",
                        object_text=unit,
                        fact_kind="quantity" if fact_kind == "other" else fact_kind,
                        assertion_mode=assertion_mode,
                        observed_date=session["date"],
                        quantity=additional_quantity,
                        qualifiers={
                            "atomic_origin": "deterministic_lossless",
                            "normalized_quantity": (
                                f"{additional_quantity.value:g} {additional_quantity.unit}"
                            ),
                            "quantity_index": str(quantity_index),
                            "quantity_context": _quantity_context(
                                unit, additional_span
                            ),
                            **additional_qualifiers,
                            **(
                                {"state_signal": "true"}
                                if fact_kind == "state"
                                else {}
                            ),
                        },
                        supersession_key=additional_key,
                        confidence=0.8,
                    )
                )
            delta = _counter_delta(unit) if speaker == "user" else None
            if delta:
                delta_excerpt, delta_category = delta
                facts.append(
                    AtomicFact(
                        fact_id=f"{session['session_id']}-t{turn_index}-u{unit_index}-delta",
                        citation=AtomicCitation(
                            session_id=session["session_id"],
                            turn_index=turn_index,
                            speaker=speaker,
                            session_date=session["date"],
                            excerpt=delta_excerpt,
                            source_content_hash=digest,
                        ),
                        subject="user",
                        predicate="counter_delta",
                        object_text=delta_category,
                        fact_kind="event",
                        observed_date=session["date"],
                        quantity=AtomicQuantity(
                            value=1,
                            unit=delta_category,
                            role="counter_increment",
                        ),
                        qualifiers={
                            "atomic_origin": "deterministic_semantic",
                            "counter_operation": "increment",
                            "counter_key": f"user:current_quantity:{delta_category}",
                            "entity_category": delta_category,
                        },
                        confidence=0.88,
                    )
                )
        for claim_index, claim in enumerate(
            extract_structured_claims(content, speaker)
        ):
            excerpt = claim.citation_excerpt
            if excerpt not in content:
                folded_position = content.casefold().find(excerpt.casefold())
                if folded_position < 0:
                    continue
                excerpt = content[folded_position : folded_position + len(excerpt)]
            claim_quantity = _extract_quantity(claim.object_text)
            kind_map = {
                "action": "event",
                "fact": "attribute",
                "goal": "plan",
                "plan": "plan",
                "preference": "preference",
                "state": "state",
                "suggestion": "recommendation",
            }
            facts.append(
                AtomicFact(
                    fact_id=f"{session['session_id']}-t{turn_index}-s{claim_index}",
                    citation=AtomicCitation(
                        session_id=session["session_id"],
                        turn_index=turn_index,
                        speaker=speaker,
                        session_date=session["date"],
                        excerpt=excerpt,
                        source_content_hash=digest,
                    ),
                    subject=claim.subject_key,
                    predicate=claim.predicate_key,
                    object_text=claim.object_text,
                    fact_kind=kind_map.get(claim.assertion_kind, "other"),
                    assertion_mode=claim.modality,
                    event_date=(
                        claim.metadata.get("event_date")
                        or _resolve_explicit_date(claim.citation_excerpt, session["date"])
                    ),
                    observed_date=session["date"],
                    quantity=claim_quantity[0] if claim_quantity else None,
                    qualifiers={
                        "atomic_origin": "deterministic_semantic",
                        **claim.metadata,
                    },
                    supersession_key=claim.supersession_key or None,
                    confidence=claim.confidence,
                )
            )
    return facts


def compile_deterministic_atomic_session(session: dict) -> AtomicSessionExtraction:
    """Compile one session and prove that every bounded source unit was processed."""
    facts = deterministic_atomic_facts(session)
    return AtomicSessionExtraction(
        session_id=session["session_id"],
        facts=facts,
        source_units=_source_coverage(session, facts),
    )


def materialize_progressive_counters(facts: Iterable[AtomicFact]) -> list[AtomicFact]:
    """Materialize totals only for an explicit snapshot followed by unambiguous +1 events."""
    output = list(facts)
    snapshots: dict[str, list[AtomicFact]] = defaultdict(list)
    deltas: dict[str, list[AtomicFact]] = defaultdict(list)
    for fact in output:
        if fact.quantity is None or fact.assertion_mode != "asserted":
            continue
        if fact.qualifiers.get("counter_snapshot") == "true" and fact.supersession_key:
            snapshots[fact.supersession_key].append(fact)
        counter_key = fact.qualifiers.get("counter_key")
        if fact.qualifiers.get("counter_operation") == "increment" and counter_key:
            deltas[counter_key].append(fact)

    for counter_key, bases in snapshots.items():
        bases.sort(
            key=lambda fact: (
                fact.observed_date,
                fact.citation.session_id,
                fact.citation.turn_index,
            )
        )
        base = bases[-1]
        applicable = [
            fact
            for fact in deltas.get(counter_key, [])
            if fact.observed_date > base.observed_date
            or (
                fact.observed_date == base.observed_date
                and fact.citation.session_id == base.citation.session_id
                and fact.citation.turn_index > base.citation.turn_index
            )
        ]
        if not applicable:
            continue
        applicable.sort(
            key=lambda fact: (
                fact.observed_date,
                fact.citation.session_id,
                fact.citation.turn_index,
            )
        )
        if any(
            fact.quantity is None
            or fact.quantity.role != "counter_increment"
            or fact.quantity.value != 1
            or fact.quantity.unit != base.quantity.unit
            for fact in applicable
        ):
            continue
        supporting = [base, *applicable]
        digest = hashlib.sha256(
            "|".join(fact.fact_id for fact in supporting).encode("utf-8")
        ).hexdigest()[:16]
        latest = applicable[-1]
        total = base.quantity.value + len(applicable)
        output.append(
            AtomicFact(
                fact_id=f"derived-counter-{digest}",
                citation=latest.citation,
                subject=base.subject,
                predicate="current_quantity",
                object_text=f"{total:g} {base.quantity.unit}",
                fact_kind="state",
                observed_date=latest.observed_date,
                quantity=AtomicQuantity(
                    value=total,
                    unit=base.quantity.unit,
                    role="derived_current_total",
                ),
                qualifiers={
                    "atomic_origin": "deterministic_derived",
                    "closed_world_category": "true",
                    "counter_snapshot": "true",
                    "derived_from": ",".join(fact.fact_id for fact in supporting),
                    "entity_category": base.quantity.unit,
                },
                supersession_key=counter_key,
                confidence=min(fact.confidence for fact in supporting),
            )
        )
    return output


def extract_atomic_memory(
    sessions: list[dict],
    *,
    model: str,
    cache_dir: Path,
    extractor: AtomicExtractor | None,
    max_sessions_per_batch: int = 1,
    include_lossless_atoms: bool = True,
) -> tuple[list[AtomicFact], AtomicExtractionDiagnostics]:
    if max_sessions_per_batch <= 0:
        raise ValueError("max_sessions_per_batch must be positive")
    started = time.perf_counter()
    cached: dict[str, AtomicSessionExtraction] = {}
    uncached: list[dict] = []
    for session in sessions:
        hit = _read_cache(_cache_path(cache_dir, model, session))
        if hit is None:
            uncached.append(session)
        else:
            cached[session["session_id"]] = hit

    usage: Counter[str] = Counter()
    invalid: Counter[str] = Counter()
    failures: list[str] = []
    extracted_count = 0
    if extractor is None:
        for session in uncached:
            extraction = compile_deterministic_atomic_session(session)
            cached[session["session_id"]] = extraction
            _write_cache(_cache_path(cache_dir, model, session), extraction)
            extracted_count += 1
    semantic_uncached = uncached if extractor is not None else []
    for offset in range(0, len(semantic_uncached), max_sessions_per_batch):
        batch = semantic_uncached[offset : offset + max_sessions_per_batch]
        try:
            response_text, batch_usage = extractor(atomic_extraction_prompt(batch))
            usage.update(
                {
                    key: int(value)
                    for key, value in batch_usage.items()
                    if isinstance(value, (int, float))
                }
            )
            payload = _extract_json_object(response_text)
            returned = {
                str(item.get("session_id") or ""): item
                for item in payload.get("sessions") or []
                if isinstance(item, dict)
            }
            for session in batch:
                raw = returned.get(session["session_id"])
                if raw is None:
                    invalid["missing_session"] += 1
                    continue
                extraction, reasons = _coerce_and_validate(raw, session)
                extraction.source_units = _source_coverage(session, extraction.facts)
                invalid.update(reasons)
                cached[session["session_id"]] = extraction
                _write_cache(_cache_path(cache_dir, model, session), extraction)
                extracted_count += 1
        except (OSError, RuntimeError, ValidationError, ValueError) as exc:
            failures.append(
                f"batch {offset // max_sessions_per_batch + 1}: "
                f"{type(exc).__name__}: {exc}"
            )

    semantic_facts = [
        fact
        for session in sessions
        for fact in cached.get(
            session["session_id"],
            AtomicSessionExtraction(session_id=session["session_id"]),
        ).facts
    ]
    lossless_facts = (
        [fact for session in sessions for fact in deterministic_atomic_facts(session)]
        if include_lossless_atoms
        else []
    )
    covered_units = {
        (
            fact.citation.session_id,
            fact.citation.turn_index,
            " ".join(fact.citation.excerpt.casefold().split()),
        )
        for fact in semantic_facts
    }
    lossless_facts = [
        fact
        for fact in lossless_facts
        if (
            fact.citation.session_id,
            fact.citation.turn_index,
            " ".join(fact.citation.excerpt.casefold().split()),
        )
        not in covered_units
    ]
    facts, removed = deduplicate_atomic_facts(
        [*semantic_facts, *lossless_facts]
    )
    facts = materialize_progressive_counters(facts)
    source_unit_count = sum(
        len(extraction.source_units) for extraction in cached.values()
    )
    covered_source_unit_count = sum(
        1
        for extraction in cached.values()
        for unit in extraction.source_units
        if unit.status in {"facts_extracted", "processed_no_fact"}
    )
    return facts, AtomicExtractionDiagnostics(
        requested_session_count=len(sessions),
        cache_hit_count=len(sessions) - len(uncached),
        extracted_session_count=extracted_count,
        valid_fact_count=len(facts),
        invalid_fact_count=sum(invalid.values()),
        invalid_by_reason=dict(invalid),
        deduplicated_fact_count=removed,
        source_unit_count=source_unit_count,
        covered_source_unit_count=covered_source_unit_count,
        source_coverage_complete=(
            source_unit_count > 0 and covered_source_unit_count == source_unit_count
        ),
        extraction_failed=bool(failures),
        failure_reason="; ".join(failures) or None,
        wall_seconds=round(time.perf_counter() - started, 4),
        usage=dict(usage),
    )


def export_semantic_normalization_jobs(
    sessions: list[dict],
    *,
    model: str,
    cache_dir: Path,
    output_path: Path,
) -> dict:
    """Export uncached semantic work without blocking the lossless compiler."""
    jobs: list[dict] = []
    for session in sessions:
        if _read_cache(_cache_path(cache_dir, model, session)) is not None:
            continue
        digest = source_content_hash(session["session_id"], session["date"], session["turns"])
        jobs.append(
            {
                "job_id": digest,
                "version": ATOMIC_MEMORY_VERSION,
                "model": model,
                "session": session,
                "prompt": atomic_extraction_prompt([session]),
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(job, ensure_ascii=False) + "\n" for job in jobs),
        encoding="utf-8",
    )
    return {"exported_job_count": len(jobs), "output_path": str(output_path)}


def import_semantic_normalization_results(
    results_path: Path,
    *,
    model: str,
    cache_dir: Path,
) -> dict:
    """Validate asynchronous results and commit only exact-cited semantic facts."""
    imported = 0
    invalid: Counter[str] = Counter()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        session = row.get("session")
        if not isinstance(session, dict):
            invalid["missing_session"] += 1
            continue
        expected = source_content_hash(
            session["session_id"], session["date"], session["turns"]
        )
        if row.get("job_id") != expected:
            invalid["source_hash_mismatch"] += 1
            continue
        try:
            response = row.get("response")
            payload = response if isinstance(response, dict) else _extract_json_object(str(response))
            raw_sessions = payload.get("sessions") or []
            raw = next(
                (
                    item for item in raw_sessions
                    if str(item.get("session_id") or "") == session["session_id"]
                ),
                None,
            )
            if raw is None:
                invalid["missing_session_result"] += 1
                continue
            extraction, reasons = _coerce_and_validate(raw, session)
            invalid.update(reasons)
            extraction.source_units = _source_coverage(session, extraction.facts)
            # Empty/partial semantic output is allowed, but it never replaces the
            # deterministic lossless tier read by extract_atomic_memory.
            _write_cache(_cache_path(cache_dir, model, session), extraction)
            imported += 1
        except (KeyError, TypeError, ValueError, ValidationError):
            invalid["malformed_result"] += 1
    return {
        "imported_session_count": imported,
        "invalid_result_count": sum(invalid.values()),
        "invalid_by_reason": dict(invalid),
    }


def estimate_atomic_tokens(text: str) -> int:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    pieces = len(re.findall(r"\w+|[^\w\s]", cleaned, re.UNICODE))
    return max(1, len(cleaned) // 4, math.ceil(pieces * 1.15))


def _fact_score(question: str, fact: AtomicFact, retrieval_rank: int) -> float:
    question_terms = {
        token for token in _TOKEN_RE.findall(question.casefold()) if token not in _QUESTION_STOPWORDS
    }
    fact_terms = set(
        _TOKEN_RE.findall(
            " ".join(
                [
                    fact.subject,
                    fact.predicate.replace("_", " "),
                    fact.object_text,
                    fact.citation.excerpt,
                    " ".join(fact.qualifiers.values()),
                ]
            ).casefold()
        )
    )
    overlap = len(question_terms & fact_terms)
    phrase_bonus = sum(
        0.8 for term in question_terms if len(term) >= 5 and term in fact.object_text.casefold()
    )
    kind_bonus = 0.0
    lowered = question.casefold()

    if re.search(r"\b(how many|number|total)\b", lowered) and fact.quantity is not None:
        kind_bonus += 3.0
    if re.search(r"\b(when|date|how long|before|after)\b", lowered) and fact.event_date:
        kind_bonus += 2.0
    if re.search(r"\b(current|now|latest|changed|change)\b", lowered) and fact.supersession_key:
        kind_bonus += 2.0
    return overlap * 2.0 + phrase_bonus + kind_bonus + 1.0 / (retrieval_rank + 1)


def render_atomic_fact(fact: AtomicFact) -> str:
    details = [
        f"subject={fact.subject}",
        f"predicate={fact.predicate}",
        f"object={fact.object_text}",
        f"kind={fact.fact_kind}",
        f"mode={fact.assertion_mode}",
    ]
    if fact.event_date:
        details.append(f"event_date={fact.event_date}")
    if fact.quantity is not None:
        details.append(
            f"quantity={fact.quantity.value:g} {fact.quantity.unit} ({fact.quantity.role})"
        )
    if fact.qualifiers:
        details.append(
            "qualifiers=" + ", ".join(f"{key}:{value}" for key, value in fact.qualifiers.items())
        )
    if fact.qualifiers.get("atomic_origin") == "deterministic_lossless":
        return (
            f"[ATOMIC SOURCE | {fact.observed_date} | {fact.citation.speaker} | "
            f"{fact.citation.session_id}#turn-{fact.citation.turn_index}]\n"
            f"{fact.object_text}"
        )
    return (
        f"[FACT {fact.fact_id} | {fact.observed_date} | {fact.citation.speaker} | "
        f"{fact.citation.session_id}#turn-{fact.citation.turn_index}]\n"
        + "; ".join(details)
        + f"\nSOURCE: {fact.citation.excerpt}"
    )


_OPERATION_TERMS = {
    "all", "average", "before", "between", "change", "changed", "compare",
    "compared", "current", "currently", "decrease", "decreased", "difference",
    "distinct", "earliest", "elapsed", "first", "former", "formerly", "how",
    "increase", "increased", "latest", "list", "many", "most", "now", "number",
    "old", "older", "over", "previous", "previously", "recent", "recently", "than",
    "reduced", "raised", "sum", "total", "used", "versus", "what", "when",
    "which",
}


def _canonical_term(token: str) -> str:
    value = token.casefold()
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if suffix == "s" and value.endswith(("ss", "is", "us")):
            continue
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            return value[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return value


def _semantic_terms(text: str, *, omit_operations: bool = False) -> set[str]:
    terms = {
        _canonical_term(token)
        for token in _TOKEN_RE.findall(text)
        if token.casefold() not in _QUESTION_STOPWORDS and len(token) > 2
    }
    if omit_operations:
        operation_terms = {_canonical_term(term) for term in _OPERATION_TERMS}
        terms = {term for term in terms if term not in operation_terms}
    return terms


def plan_atomic_query(question: str) -> AtomicQueryPlan:
    """Create a production query plan from user language only.

    Official benchmark labels are deliberately not accepted by this interface.
    Rules describe general reasoning contracts, while ambiguous/direct questions
    remain on claim-first.
    """
    lowered = " ".join(question.casefold().split())
    targets = sorted(_semantic_terms(question, omit_operations=True))
    subject_scope: Literal["user", "assistant", "any"] = (
        "user"
        if re.search(r"\b(i|me|my|mine)\b", lowered)
        else "assistant"
        if re.search(r"\b(you|your)\b", lowered)
        else "any"
    )
    quantity_subjects: list[str] = []
    subject_match = re.search(
        r"\b(?:how many|number of)\s+(?P<subject>.+?)\s+"
        r"(?:am|are|did|do|does|had|has|have|in|on|were|was)\b",
        lowered,
    )
    if subject_match:
        quantity_subjects = sorted(
            _semantic_terms(subject_match.group("subject"), omit_operations=True)
            - {"online", "recent", "total"}
        )

    if re.search(
        r"\b(how long|elapsed|time between|days? between|weeks? between|"
        r"months? between|years? between|how many (?:days?|weeks?|months?|years?)"
        r"(?: ago| before| after| since)?)\b",
        lowered,
    ):
        return AtomicQueryPlan(
            operation="temporal_difference",
            target_terms=targets,
            quantity_subject_terms=quantity_subjects,
            subject_scope=subject_scope,
            required_slots=["start_date", "end_date"],
            atomic_eligible=True,
            confidence=0.96,
            reason="elapsed-time operation",
        )
    if re.search(r"\baverage|mean\b", lowered):
        return AtomicQueryPlan(
            operation="numeric_average",
            target_terms=targets,
            quantity_subject_terms=quantity_subjects,
            subject_scope=subject_scope,
            required_slots=["complete_numeric_set", "compatible_units"],
            atomic_eligible=True,
            confidence=0.97,
            reason="numeric average operation",
        )
    if re.search(r"\b(sum|total|combined)\b", lowered) and re.search(
        r"\b(how much|amount|cost|price|spent|distance|time|number|total)\b", lowered
    ):
        return AtomicQueryPlan(
            operation="numeric_sum",
            target_terms=targets,
            quantity_subject_terms=quantity_subjects,
            subject_scope=subject_scope,
            required_slots=["complete_numeric_set", "compatible_units"],
            atomic_eligible=True,
            confidence=0.94,
            reason="numeric sum operation",
        )
    if re.search(
        r"\b(how much (?:more|less)|difference|gap|older than|younger than|"
        r"increase by|decrease by)\b",
        lowered,
    ):
        return AtomicQueryPlan(
            operation="numeric_difference",
            target_terms=targets,
            quantity_subject_terms=quantity_subjects,
            subject_scope=subject_scope,
            required_slots=["left_value", "right_value", "compatible_units"],
            atomic_eligible=True,
            confidence=0.94,
            reason="numeric difference operation",
        )
    transition = re.search(
        r"\b(chang(?:e|ed)|increase(?:d)?|decrease(?:d)?|raised?|reduced?|"
        r"went from|moved from|switched from|compared (?:with|to)|before versus now|"
        r"old (?:and|versus) new|used to|no longer)\b",
        lowered,
    )
    if transition or re.search(
        r"\b(up or down|more or less than before|(?:more|less)\b.+\bthan before)\b",
        lowered,
    ):
        return AtomicQueryPlan(
            operation="state_comparison",
            target_terms=targets,
            required_slots=["previous_state", "current_state"],
            atomic_eligible=True,
            confidence=0.93,
            reason="state transition/comparison operation",
        )
    if re.search(r"\b(chronological(?:ly)?|in order)\b", lowered) or (
        re.search(r"\b(earliest|latest|first|most recent(?:ly)?)\b", lowered)
        and re.search(
            r"\b(event|happen|occur|visit|trip|appointment|purchase|attend|start|finish|"
            r"flight|flew|travel)\w*\b",
            lowered,
        )
    ):
        return AtomicQueryPlan(
            operation="event_order",
            target_terms=targets,
            required_slots=["dated_event_set"],
            atomic_eligible=True,
            confidence=0.9,
            reason="event ordering operation",
        )
    if re.search(
        r"\b(current|currently|now|latest|most recent|present|as of today)\b",
        lowered,
    ):
        return AtomicQueryPlan(
            operation="current_state",
            target_terms=targets,
            required_slots=["current_state", "state_history_checked"],
            atomic_eligible=True,
            confidence=0.88,
            reason="current-state operation",
        )
    if re.search(r"\b(how many|number of|count(?: of)?)\b", lowered):
        return AtomicQueryPlan(
            operation="distinct_count",
            target_terms=targets,
            quantity_subject_terms=quantity_subjects,
            subject_scope=subject_scope,
            required_slots=["complete_candidate_set", "deduplication_key"],
            atomic_eligible=True,
            confidence=0.91,
            reason="distinct-count operation",
        )
    if re.search(
        r"\b(list|all|every|which ones|(?:what|which) (?:activities|items|places|people|"
        r"things|events)|in common|across (?:\w+\s+){0,2}(?:sessions|conversations|months|years))\b",
        lowered,
    ):
        return AtomicQueryPlan(
            operation="aggregate_list",
            target_terms=targets,
            required_slots=["complete_candidate_set", "session_coverage"],
            atomic_eligible=True,
            confidence=0.86,
            reason="cross-source aggregation operation",
        )
    return AtomicQueryPlan(
        operation="direct_lookup",
        target_terms=targets,
        required_slots=["answer_fact"],
        atomic_eligible=False,
        confidence=0.9,
        reason="no multi-fact reasoning contract detected",
    )


def route_atomic_question(
    question: str,
    *,
    retrieved_session_count: int,
    plan: AtomicQueryPlan | None = None,
) -> AtomicRouteDecision:
    query_plan = plan or plan_atomic_query(question)
    if not query_plan.atomic_eligible:
        return AtomicRouteDecision(
            path="claim-first",
            reason=query_plan.reason,
            plan=query_plan,
        )
    if query_plan.confidence < 0.8:
        return AtomicRouteDecision(
            path="claim-first",
            reason="query-plan confidence below atomic threshold",
            plan=query_plan,
        )
    if query_plan.operation == "aggregate_list" and retrieved_session_count < 2:
        return AtomicRouteDecision(
            path="claim-first",
            reason="aggregation has fewer than two retrieved sessions",
            plan=query_plan,
        )
    return AtomicRouteDecision(
        path="atomic",
        reason=query_plan.reason,
        plan=query_plan,
    )


def _question_terms(question: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(question.casefold())
        if token not in _QUESTION_STOPWORDS and len(token) > 2
    }


def _anchor_kinds(
    question: str, fact: AtomicFact, plan: AtomicQueryPlan | None = None
) -> set[str]:
    kinds: set[str] = set()
    text = f"{fact.object_text} {fact.citation.excerpt}"
    if _QUANTITY_QUERY_RE.search(question) and (
        fact.quantity is not None or _extract_quantity(text) is not None
    ):
        kinds.add("quantity")
    if _DATE_QUERY_RE.search(question) and (fact.event_date or re.search(
        r"\b(?:19|20)\d{2}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
        r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\b",
        text,
        re.IGNORECASE,
    )):
        kinds.add("date")
    if _STATE_QUERY_RE.search(question) and (
        fact.supersession_key or fact.fact_kind == "state"
    ):
        kinds.add("state")
    # A named entity is mandatory only when the question names it explicitly.
    question_names = {
        name.casefold()
        for name in re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b", question)
    }
    if question_names and any(name in text.casefold() for name in question_names):
        kinds.add("entity")
    query_plan = plan or plan_atomic_query(question)
    fact_terms = _semantic_terms(text)
    relevant = bool(set(query_plan.target_terms) & fact_terms)
    if "entity" in kinds:
        relevant = True
    return kinds if relevant else set()


def _citation_label(fact: AtomicFact) -> str:
    return (
        f"{fact.citation.session_id}#turn-{fact.citation.turn_index}"
        f" ({fact.citation.session_date})"
    )


def _fact_relevant_to_plan(fact: AtomicFact, plan: AtomicQueryPlan) -> bool:
    if fact.assertion_mode == "hypothetical":
        return False
    if not plan.target_terms:
        return False
    fact_terms = _semantic_terms(
        " ".join(
            [
                fact.subject,
                fact.predicate.replace("_", " "),
                fact.object_text,
                " ".join(fact.qualifiers.values()),
            ]
        )
    )
    return bool(set(plan.target_terms) & fact_terms)


_MEASURE_TARGET_TERMS = {
    "amount", "average", "cost", "distance", "duration", "few", "hour",
    "many", "money", "month", "number", "past", "price", "spend", "spent",
    "sum", "time", "total", "week", "year",
}


def _quantity_family(unit: str) -> str:
    canonical = _canonical_term(unit)
    if canonical in {"currency", "dollar"}:
        return "money:dollar"
    if canonical in {"euro"}:
        return "money:euro"
    if canonical in {"pound", "sterling"}:
        return "money:pound"
    if canonical in {"kilometer", "km", "meter", "mile", "foot", "feet"}:
        return "distance"
    if canonical in {"gallon", "liter", "litre"}:
        return "capacity"
    if canonical in {"minute", "hour", "day", "week", "month"}:
        return "duration"
    if canonical == "year":
        return "years"
    if canonical in {"percent", "percentage"}:
        return "percent"
    if canonical in {"number", "item", "person", "people", "follower", "engineer", "session"}:
        return "count"
    return canonical


def _expected_quantity_family(plan: AtomicQueryPlan) -> str | None:
    terms = set(plan.target_terms)
    if set(plan.quantity_subject_terms) & {"day", "hour", "minute", "month", "week"}:
        return "duration"
    if plan.quantity_subject_terms:
        return "count"
    if terms & {"money", "cost", "price", "spend", "spent", "budget", "fare", "worth"}:
        return "money"
    if terms & {"distance", "mile", "kilometer", "meter", "km"}:
        return "distance"
    if terms & {"duration", "hour", "minute", "time"}:
        return "duration"
    if "age" in terms or "older" in terms or "younger" in terms:
        return "years"
    if terms & {"percent", "percentage"}:
        return "percent"
    if terms & {
        "comment", "course", "day", "engineer", "episode", "follower", "item",
        "meal", "people", "person", "piece", "sibling", "title", "view",
    }:
        return "count"
    return None


def _effective_quantity_family(fact: AtomicFact, plan: AtomicQueryPlan) -> str:
    if fact.quantity is None:
        return ""
    family = _quantity_family(fact.quantity.unit)
    if _canonical_term(fact.quantity.unit) != "number":
        return family
    if _expected_quantity_family(plan) != "count" or not plan.quantity_subject_terms:
        return family
    context_terms = _semantic_terms(
        fact.qualifiers.get("quantity_context") or fact.object_text
    )
    return "count" if set(plan.quantity_subject_terms) & context_terms else "untyped_number"


def _numeric_fact_relevant(fact: AtomicFact, plan: AtomicQueryPlan) -> bool:
    if fact.quantity is None or fact.assertion_mode != "asserted":
        return False
    expected = _expected_quantity_family(plan)
    family = _effective_quantity_family(fact, plan)
    if expected == "money" and not family.startswith("money:"):
        return False
    if expected is not None and expected != "money" and family != expected:
        # Unit-less counts are accepted only when their local clause names the
        # requested counted concept.
        if not (expected == "count" and family == "count"):
            return False
    context = fact.qualifiers.get("quantity_context") or fact.object_text
    context_terms = _semantic_terms(context)
    semantic_targets = set(plan.target_terms) - _MEASURE_TARGET_TERMS
    return not semantic_targets or bool(semantic_targets & context_terms)


def _deduplicate_quantity_operands(
    facts: list[AtomicFact], plan: AtomicQueryPlan
) -> list[AtomicFact]:
    exact: dict[tuple, AtomicFact] = {}
    for fact in facts:
        if fact.quantity is None:
            continue
        key = (
            fact.citation.session_id,
            fact.citation.turn_index,
            round(fact.quantity.value, 9),
            _quantity_family(fact.quantity.unit),
            " ".join((fact.qualifiers.get("quantity_context") or fact.object_text).casefold().split()),
        )
        existing = exact.get(key)
        if existing is None or fact.confidence > existing.confidence:
            exact[key] = fact
    output: list[AtomicFact] = []
    for fact in exact.values():
        context_terms = _semantic_terms(
            fact.qualifiers.get("quantity_context") or fact.object_text,
            omit_operations=True,
        )
        duplicate = False
        for previous in output:
            if (
                previous.citation.session_id != fact.citation.session_id
                or previous.quantity is None
                or previous.quantity.value != fact.quantity.value
                or _effective_quantity_family(previous, plan)
                != _effective_quantity_family(fact, plan)
            ):
                continue
            previous_terms = _semantic_terms(
                previous.qualifiers.get("quantity_context") or previous.object_text,
                omit_operations=True,
            )
            union = previous_terms | context_terms
            similarity = len(previous_terms & context_terms) / max(1, len(union))
            salient_overlap = (
                previous_terms
                & context_terms
                - _MEASURE_TARGET_TERMS
                - {"experience", "great", "help", "recent", "recently", "think"}
            )
            if similarity >= 0.45 or (
                similarity >= 0.15 and len(salient_overlap) >= 4
            ):
                duplicate = True
                break
        if not duplicate:
            output.append(fact)
    return output


def _declared_cardinality_facts(
    facts: list[AtomicFact], plan: AtomicQueryPlan
) -> list[AtomicFact]:
    """Return explicit scalar cardinalities that directly answer a count query.

    A statement such as "I watched 10 comedians" is itself a closed-world count
    assertion.  It does not need ten synthetic entity facts.  Genuine distinct-list
    questions still use the stricter normalized-category contract below.
    """
    ignored_targets = {
        "all", "current", "currently", "different", "every", "how", "many",
        "number", "now", "recent", "recently", "this", "total", "type",
    }
    required_context_terms = set(plan.target_terms) - ignored_targets
    related: list[AtomicFact] = []
    scoped: list[AtomicFact] = []
    for fact in facts:
        if (
            fact.assertion_mode != "asserted"
            or fact.quantity is None
            or not _numeric_fact_relevant(fact, plan)
            or (
                plan.subject_scope != "any"
                and fact.citation.speaker != plan.subject_scope
            )
        ):
            continue
        context_terms = _semantic_terms(
            fact.qualifiers.get("quantity_context") or fact.object_text,
            omit_operations=True,
        )
        related.append(fact)
        # A local number cannot certify a broader total.  Requiring every
        # discriminating query term rejects, for example, one wedding as the
        # count for "weddings this year" and an album year as albums purchased.
        if required_context_terms - context_terms:
            continue
        scoped.append(fact)
    related = _deduplicate_quantity_operands(related, plan)
    scoped = _deduplicate_quantity_operands(scoped, plan)
    # Multiple related cardinalities form a history, not one closed assertion.
    # A later-looking local value must not silently stand in for a requested
    # cumulative/current total until the state chain itself is normalized.
    if len(related) != 1 or len(scoped) != 1:
        return []
    candidate = scoped[0]
    subject_terms = set(plan.quantity_subject_terms)
    later_related = [
        fact
        for fact in facts
        if fact.fact_id != candidate.fact_id
        and fact.assertion_mode == "asserted"
        and fact.citation.speaker == candidate.citation.speaker
        and fact.observed_date > candidate.observed_date
        and subject_terms
        & _semantic_terms(
            " ".join(
                [
                    fact.predicate.replace("_", " "),
                    fact.object_text,
                    " ".join(fact.qualifiers.values()),
                ]
            ),
            omit_operations=True,
        )
    ]
    return [] if later_related else scoped


def validate_atomic_contract(
    plan: AtomicQueryPlan,
    facts: list[AtomicFact],
    selected_fact_ids: Iterable[str],
    packing_metadata: dict,
) -> AtomicContractResult:
    """Prove operation-specific evidence completeness before atomic activation."""
    selected_ids = set(selected_fact_ids)
    relevant = [fact for fact in facts if _fact_relevant_to_plan(fact, plan)]
    relevant_user = [fact for fact in relevant if fact.citation.speaker == "user"]
    reasons = list(packing_metadata.get("safety_reasons") or [])
    missing: list[str] = []
    filled: dict[str, list[str]] = {}
    operands: list[AtomicFact] = []

    def require_all(candidates: list[AtomicFact], slot: str) -> None:
        nonlocal operands
        selected = [fact for fact in candidates if fact.fact_id in selected_ids]
        filled[slot] = [fact.fact_id for fact in selected]
        if not candidates or len(selected) != len(candidates):
            missing.append(slot)
        operands.extend(selected)

    if plan.operation == "state_comparison":
        states = [
            fact
            for fact in relevant_user
            if fact.fact_kind == "state"
            or fact.quantity is not None
            or fact.supersession_key is not None
        ]
        states.sort(
            key=lambda fact: (
                fact.event_date or fact.observed_date,
                fact.citation.turn_index,
                fact.fact_id,
            )
        )
        selected_states = [fact for fact in states if fact.fact_id in selected_ids]
        distinct_state_sources = {
            (fact.citation.session_id, fact.citation.turn_index)
            for fact in states
        }
        state_keys = {fact.supersession_key for fact in states if fact.supersession_key}
        if states:
            filled["previous_state"] = [states[0].fact_id] if states[0] in selected_states else []
            filled["current_state"] = [states[-1].fact_id] if states[-1] in selected_states else []
        if len(states) < 2 or not filled.get("previous_state"):
            missing.append("previous_state")
        if len(states) < 2 or not filled.get("current_state"):
            missing.append("current_state")
        if any(fact.fact_id not in selected_ids for fact in states):
            missing.append("complete_state_chain")
        if len(distinct_state_sources) < 2:
            missing.append("distinct_state_sources")
        if len(state_keys) != 1 or any(not fact.supersession_key for fact in states):
            missing.append("normalized_state_identity")
        if any(
            fact.quantity is not None
            and _canonical_term(fact.quantity.unit) == "number"
            for fact in states
        ):
            missing.append("normalized_state_quantity_role")
        operands.extend(selected_states)
    elif plan.operation == "current_state":
        states = [
            fact
            for fact in relevant_user
            if fact.fact_kind == "state"
            or fact.supersession_key is not None
        ]
        states.sort(
            key=lambda fact: (
                fact.event_date or fact.observed_date,
                fact.citation.turn_index,
                fact.fact_id,
            )
        )
        scope_terms = {
            "brand", "current", "currently", "how", "local", "many", "model",
            "now", "often", "present", "recent", "recently", "today", "type",
        }
        coverage_targets = set(plan.target_terms) - scope_terms

        def state_terms(fact: AtomicFact) -> set[str]:
            return _semantic_terms(
                " ".join(
                    [
                        fact.predicate.replace("_", " "),
                        fact.object_text,
                        " ".join(fact.qualifiers.values()),
                    ]
                )
            )

        matching_states = [
            fact for fact in states if not (coverage_targets - state_terms(fact))
        ]
        current = matching_states[-1] if matching_states else None
        if current is not None and current.fact_id in selected_ids:
            filled["current_state"] = [current.fact_id]
        else:
            missing.append("current_state")
        if current is not None and current.supersession_key:
            state_history = [
                fact
                for fact in states
                if fact.supersession_key == current.supersession_key
            ]
        else:
            state_history = matching_states
        if not state_history or any(
            fact.fact_id not in selected_ids for fact in state_history
        ):
            missing.append("state_history_checked")
        if not matching_states:
            missing.append("target_concept_coverage")
        operands.extend(
            fact for fact in state_history if fact.fact_id in selected_ids
        )
    elif plan.operation in {"numeric_sum", "numeric_average", "numeric_difference"}:
        user_quantities = [
            fact for fact in relevant_user if _numeric_fact_relevant(fact, plan)
        ]
        quantities = (
            user_quantities
            if plan.subject_scope == "user"
            else [fact for fact in relevant if _numeric_fact_relevant(fact, plan)]
        )
        quantities = _deduplicate_quantity_operands(quantities, plan)
        selected_quantities = [fact for fact in quantities if fact.fact_id in selected_ids]
        units = {
            _effective_quantity_family(fact, plan)
            for fact in quantities
            if fact.quantity is not None
        }
        filled["numeric_operands"] = [fact.fact_id for fact in selected_quantities]
        required_count = 2
        if len(quantities) < required_count or len(selected_quantities) != len(quantities):
            missing.append(
                "left_value" if plan.operation == "numeric_difference" else "complete_numeric_set"
            )
            if plan.operation == "numeric_difference":
                missing.append("right_value")
        if len(units) != 1:
            missing.append("compatible_units")
        if any(
            fact.quantity is not None
            and _effective_quantity_family(fact, plan) == "untyped_number"
            for fact in quantities
        ):
            missing.append("normalized_quantity_role")
        operand_terms = set().union(
            *(
                _semantic_terms(fact.object_text)
                for fact in quantities
            )
        ) if quantities else set()
        scope_terms = {
            "amount", "average", "both", "cost", "distance", "each", "few",
            "last", "many", "money", "month", "number", "past", "per", "price",
            "several", "spend", "spent", "there", "these", "those", "time",
            "total", "week",
        }
        coverage_targets = (
            set(plan.quantity_subject_terms)
            if _expected_quantity_family(plan) == "count"
            and plan.quantity_subject_terms
            else set(plan.target_terms)
        )
        uncovered_targets = {
            term for term in coverage_targets
            if term not in scope_terms and term not in operand_terms
        }
        if uncovered_targets:
            missing.append("target_concept_coverage")
        operands.extend(selected_quantities)
    elif plan.operation in {"temporal_difference", "event_order"}:
        generic_event_terms = {
            "attend", "date", "day", "event", "finish", "happen", "occur",
            "participate", "start", "time",
        }
        discriminative_targets = set(plan.target_terms) - generic_event_terms
        dated = [
            fact
            for fact in relevant
            if fact.event_date
            and (
                not discriminative_targets
                or discriminative_targets
                & _semantic_terms(
                    " ".join(
                        [
                            fact.predicate.replace("_", " "),
                            fact.object_text,
                            " ".join(fact.qualifiers.values()),
                        ]
                    )
                )
            )
        ]
        require_all(dated, "dated_event_set")
        if plan.operation == "event_order" and len(dated) < 2:
            missing.append("complete_ordered_event_set")
        if plan.operation == "temporal_difference" and len({fact.event_date for fact in dated}) != 2:
            missing.extend(["start_date", "end_date"])
    elif plan.operation in {"distinct_count", "aggregate_list"}:
        declared = (
            _declared_cardinality_facts(relevant, plan)
            if plan.operation == "distinct_count"
            else []
        )
        if len(declared) == 1:
            require_all(declared, "declared_cardinality")
            filled["deduplication_key"] = ["explicit-cardinality-assertion"]
            candidates = declared
        else:
            candidates = []
        normalized_candidates = [
            fact
            for fact in relevant_user
            if fact.qualifiers.get("atomic_origin") != "deterministic_lossless"
        ]
        if len(declared) != 1:
            candidates = normalized_candidates or relevant_user or relevant
            require_all(candidates, "complete_candidate_set")
            if not candidates or not all(
                fact.qualifiers.get("closed_world_category") == "true"
                for fact in candidates
            ):
                missing.append("closed_world_category_coverage")
        candidate_sessions = {fact.citation.session_id for fact in candidates}
        selected_sessions = {
            fact.citation.session_id for fact in candidates if fact.fact_id in selected_ids
        }
        if candidate_sessions != selected_sessions:
            missing.append("session_coverage")
        if plan.operation == "distinct_count" and candidates:
            filled["deduplication_key"] = ["normalized-object-text"]
        elif plan.operation == "distinct_count":
            missing.append("deduplication_key")
    else:
        missing.append("unsupported_operation")

    if not packing_metadata.get("safe", False):
        reasons.append("base packet safety check failed")
    missing = list(dict.fromkeys(missing))
    unique_operands = list({fact.fact_id: fact for fact in operands}.values())
    if missing:
        reasons.append("missing required evidence slots: " + ", ".join(missing))
    return AtomicContractResult(
        safe=bool(packing_metadata.get("safe", False)) and not missing,
        operation=plan.operation,
        filled_slots=filled,
        missing_slots=missing,
        operand_fact_ids=[fact.fact_id for fact in unique_operands],
        reasons=list(dict.fromkeys(reasons)),
    )


def evaluate_deterministic_operation(
    question: str,
    facts: list[AtomicFact],
    selected_fact_ids: Iterable[str],
    *,
    plan: AtomicQueryPlan | None = None,
    operand_fact_ids: Iterable[str] | None = None,
) -> DeterministicOperationResult:
    """Resolve a proven query contract; never infer missing operands."""
    query_plan = plan or plan_atomic_query(question)
    if query_plan.operation in {"direct_lookup", "aggregate_list", "unknown"}:
        return DeterministicOperationResult()
    selected_id_set = set(selected_fact_ids)
    if operand_fact_ids is not None:
        selected_id_set &= set(operand_fact_ids)
    selected = [fact for fact in facts if fact.fact_id in selected_id_set]
    lowered = question.casefold()
    operation = query_plan.operation

    if operation in {"current_state", "state_comparison"}:
        states = sorted(
            selected,
            key=lambda fact: (
                fact.event_date or fact.observed_date,
                fact.citation.turn_index,
                fact.fact_id,
            ),
        )
        if operation == "current_state":
            if not states:
                return DeterministicOperationResult(
                    requested=True,
                    operation=operation,
                    fallback_reason="current-state operand is incomplete",
                )
            latest = states[-1]
            return DeterministicOperationResult(
                requested=True,
                resolved=True,
                operation=operation,
                result=latest.object_text,
                operand_fact_ids=[fact.fact_id for fact in states],
                citation_labels=[_citation_label(fact) for fact in states],
            )
        if len(states) < 2:
            return DeterministicOperationResult(
                requested=True,
                operation=operation,
                fallback_reason="previous/current state operands are incomplete",
            )
        previous, current = states[0], states[-1]
        result = f"previous={previous.object_text}; current={current.object_text}"
        if previous.quantity is not None and current.quantity is not None:
            if _canonical_term(previous.quantity.unit) != _canonical_term(current.quantity.unit):
                return DeterministicOperationResult(
                    requested=True,
                    operation=operation,
                    fallback_reason="state quantities use incompatible units",
                )
            direction = (
                "increased"
                if current.quantity.value > previous.quantity.value
                else "decreased"
                if current.quantity.value < previous.quantity.value
                else "unchanged"
            )
            result = (
                f"{direction} from {previous.quantity.value:g} {previous.quantity.unit} "
                f"to {current.quantity.value:g} {current.quantity.unit}"
            )
        return DeterministicOperationResult(
            requested=True,
            resolved=True,
            operation=operation,
            result=result,
            operand_fact_ids=[fact.fact_id for fact in states],
            citation_labels=[_citation_label(fact) for fact in states],
        )

    if operation == "event_order":
        dated = [fact for fact in selected if fact.event_date]
        if not dated:
            return DeterministicOperationResult(
                requested=True,
                operation="event_order",
                fallback_reason="requires normalized dated events",
            )
        chooser = min if re.search(r"\b(earliest|first)\b", lowered) else max
        chosen = chooser(dated, key=lambda fact: fact.event_date or "")
        return DeterministicOperationResult(
            requested=True,
            resolved=True,
            operation="earliest_event" if chooser is min else "latest_event",
            result=f"{chosen.object_text} ({chosen.event_date})",
            operand_fact_ids=[fact.fact_id for fact in dated],
            citation_labels=[_citation_label(fact) for fact in dated],
        )

    if operation == "temporal_difference":
        from datetime import date

        dated = [fact for fact in selected if fact.event_date]
        distinct = sorted({fact.event_date for fact in dated})
        if len(distinct) != 2:
            return DeterministicOperationResult(
                requested=True,
                operation="date_difference",
                fallback_reason="requires exactly two unambiguous normalized event dates",
            )
        try:
            start, end = (date.fromisoformat(value) for value in distinct)
        except ValueError:
            return DeterministicOperationResult(
                requested=True,
                operation="date_difference",
                fallback_reason="event dates are not exact ISO dates",
            )
        days = (end - start).days
        unit = "days"
        value: float = float(days)
        if "week" in lowered and days % 7 == 0:
            unit, value = "weeks", days / 7
        operands = [fact for fact in dated if fact.event_date in distinct]
        return DeterministicOperationResult(
            requested=True,
            resolved=True,
            operation="date_difference",
            result=f"{value:g} {unit}",
            operand_fact_ids=[fact.fact_id for fact in operands],
            citation_labels=[_citation_label(fact) for fact in operands],
        )

    if operation == "distinct_count":
        typed = [fact for fact in selected if fact.assertion_mode == "asserted"]
        if not typed:
            return DeterministicOperationResult(
                requested=True,
                operation="distinct_count",
                fallback_reason="requires one complete normalized fact category",
            )
        if len(typed) == 1 and typed[0].quantity is not None:
            cardinality = typed[0]
            quantity = cardinality.quantity
            rendered_unit = "" if _quantity_family(quantity.unit) == "count" else f" {quantity.unit}"
            return DeterministicOperationResult(
                requested=True,
                resolved=True,
                operation="declared_cardinality",
                result=f"{quantity.value:g}{rendered_unit}",
                operand_fact_ids=[cardinality.fact_id],
                citation_labels=[_citation_label(cardinality)],
            )
        distinct = {
            " ".join(fact.object_text.casefold().split()): fact for fact in typed
        }
        operands = list(distinct.values())
        return DeterministicOperationResult(
            requested=True,
            resolved=True,
            operation="distinct_count",
            result=str(len(distinct)),
            operand_fact_ids=[fact.fact_id for fact in operands],
            citation_labels=[_citation_label(fact) for fact in operands],
        )

    quantities = [fact for fact in selected if fact.quantity is not None]
    units = {_quantity_family(fact.quantity.unit) for fact in quantities if fact.quantity}
    if len(quantities) < 2 or len(units) != 1:
        return DeterministicOperationResult(
            requested=True,
            operation="numeric_arithmetic",
            fallback_reason="typed numeric operands are incomplete or use incompatible units",
        )
    values = [fact.quantity.value for fact in quantities if fact.quantity]
    rendered_operation = "sum"
    result = sum(values)
    if operation == "numeric_average":
        rendered_operation, result = "average", sum(values) / len(values)
    elif operation == "numeric_difference":
        if len(values) != 2:
            return DeterministicOperationResult(
                requested=True,
                operation="difference",
                fallback_reason="difference requires exactly two typed operands",
            )
        rendered_operation, result = "difference", abs(values[0] - values[1])
    return DeterministicOperationResult(
        requested=True,
        resolved=True,
        operation=rendered_operation,
        result=f"{result:g} {quantities[0].quantity.unit}",
        operand_fact_ids=[fact.fact_id for fact in quantities],
        citation_labels=[_citation_label(fact) for fact in quantities],
    )


def render_deterministic_operation(result: DeterministicOperationResult) -> str:
    if not result.resolved:
        return ""
    operands = ", ".join(
        f"{fact_id} [{citation}]"
        for fact_id, citation in zip(
            result.operand_fact_ids, result.citation_labels, strict=True
        )
    )
    return (
        "[DETERMINISTIC OPERATION]\n"
        f"operation={result.operation}; result={result.result}\n"
        f"operands={operands}"
    )


def pack_atomic_facts(
    question: str,
    facts: list[AtomicFact],
    retrieved_session_ids: list[str],
    *,
    token_budget: int,
    plan: AtomicQueryPlan | None = None,
) -> tuple[str, dict]:
    query_plan = plan or plan_atomic_query(question)
    broad_aggregation = query_plan.operation in {"aggregate_list", "distinct_count"}
    ranks = {session_id: rank for rank, session_id in enumerate(retrieved_session_ids)}
    analysis_facts = [
        fact for fact in facts if fact.citation.session_id in ranks
    ]
    base_scores = {
        fact.fact_id: _fact_score(
            question, fact, ranks.get(fact.citation.session_id, 10_000)
        )
        for fact in analysis_facts
    }
    scores = dict(base_scores)
    if broad_aggregation:
        for fact in analysis_facts:
            rank = ranks.get(fact.citation.session_id, 10_000)
            if fact.citation.speaker == "user" and rank < 10:
                # Count/list/update questions often use category words absent from the
                # source fact ("doctors" versus "Dr. Lee"). Preserve broad user-event
                # coverage from the strongest retrieved sessions before lexical fill.
                scores[fact.fact_id] += 12.0 + (10 - rank) * 0.8
    by_turn: dict[tuple[str, int], list[AtomicFact]] = {}
    for fact in analysis_facts:
        by_turn.setdefault(
            (fact.citation.session_id, fact.citation.turn_index), []
        ).append(fact)
    # A relevant table row needs its header, and a short list item often needs the
    # neighboring item or heading. Propagate a bounded relevance bonus within that turn.
    for turn_facts in by_turn.values():
        turn_peak = max(scores[fact.fact_id] for fact in turn_facts)
        if turn_peak < 2.0:
            continue
        for fact in turn_facts:
            if fact.fact_kind == "list_item":
                scores[fact.fact_id] += min(2.0, turn_peak * 0.2)
    ranked = sorted(
        analysis_facts,
        key=lambda fact: (
            scores[fact.fact_id],
            fact.confidence,
            fact.observed_date,
        ),
        reverse=True,
    )
    selected: list[AtomicFact] = []
    selected_ids: set[str] = set()
    used = 0
    represented_sessions: set[str] = set()

    def add(fact: AtomicFact) -> bool:
        nonlocal used
        if fact.fact_id in selected_ids:
            return True
        rendered_tokens = estimate_atomic_tokens(render_atomic_fact(fact)) + 4
        if used + rendered_tokens > token_budget:
            return False
        selected.append(fact)
        selected_ids.add(fact.fact_id)
        represented_sessions.add(fact.citation.session_id)
        used += rendered_tokens
        return True

    # Reserve a per-session quota before global competition. Aggregations get two
    # user assertions per session because one unit is often only a heading or setup.
    quota = 2 if broad_aggregation else 1
    for session_id in retrieved_session_ids:
        candidates = [
            fact
            for fact in ranked
            if fact.citation.session_id == session_id
            and fact.citation.speaker == "user"
        ] or [fact for fact in ranked if fact.citation.session_id == session_id]
        for candidate in candidates[:quota]:
            add(candidate)

    important_anchor_ids = {
        fact.fact_id
        for fact in analysis_facts
        if _anchor_kinds(question, fact, query_plan)
    }
    contract_candidate_ids: set[str] = set()
    if query_plan.operation in {"distinct_count", "aggregate_list"}:
        relevant_user_facts = [
            fact
            for fact in analysis_facts
            if fact.citation.speaker == "user"
            and _fact_relevant_to_plan(fact, query_plan)
        ]
        normalized_user_facts = [
            fact
            for fact in relevant_user_facts
            if fact.qualifiers.get("atomic_origin") != "deterministic_lossless"
        ]
        declared = (
            _declared_cardinality_facts(analysis_facts, query_plan)
            if query_plan.operation == "distinct_count"
            else []
        )
        contract_candidate_ids = {
            fact.fact_id
            for fact in (
                declared
                if len(declared) == 1
                else (normalized_user_facts or relevant_user_facts)
            )
        }
    elif query_plan.operation in {
        "numeric_sum", "numeric_average", "numeric_difference"
    }:
        relevant_quantities = [
            fact
            for fact in analysis_facts
            if fact.quantity is not None and _fact_relevant_to_plan(fact, query_plan)
        ]
        user_quantities = [
            fact for fact in relevant_quantities if fact.citation.speaker == "user"
        ]
        contract_candidate_ids = {
            fact.fact_id for fact in (user_quantities or relevant_quantities)
        }
    elif query_plan.operation in {"state_comparison", "current_state"}:
        contract_candidate_ids = {
            fact.fact_id
            for fact in analysis_facts
            if fact.citation.speaker == "user"
            and (
                fact.fact_kind == "state"
                or (
                    query_plan.operation == "state_comparison"
                    and fact.quantity is not None
                )
                or fact.supersession_key is not None
            )
            and _fact_relevant_to_plan(fact, query_plan)
        }
    elif query_plan.operation in {"event_order", "temporal_difference"}:
        contract_candidate_ids = {
            fact.fact_id
            for fact in analysis_facts
            if fact.event_date and _fact_relevant_to_plan(fact, query_plan)
        }
    # Dates, quantities, entities, and state facts that overlap the question are
    # mandatory. Old/new normalized states are retained as a pair.
    for fact in ranked:
        if fact.fact_id in important_anchor_ids | contract_candidate_ids:
            add(fact)
    state_groups: dict[str, list[AtomicFact]] = {}
    for fact in analysis_facts:
        if fact.supersession_key:
            state_groups.setdefault(fact.supersession_key, []).append(fact)
    if _STATE_QUERY_RE.search(question):
        for group in state_groups.values():
            ordered = sorted(group, key=lambda fact: (fact.event_date or fact.observed_date))
            add(ordered[0])
            add(ordered[-1])

    # Add table headers and immediate same-turn neighbors after anchor analysis.
    dependencies: list[AtomicFact] = []
    for fact in list(selected):
        turn_facts = sorted(
            by_turn.get((fact.citation.session_id, fact.citation.turn_index), []),
            key=lambda candidate: candidate.fact_id,
        )
        if not turn_facts:
            continue
        position = turn_facts.index(fact)
        if fact.fact_kind == "list_item":
            table_rows = [
                candidate for candidate in turn_facts
                if candidate.object_text.startswith("|")
            ]
            # Markdown tables begin with the semantic header followed by the
            # separator row; both are needed to interpret any selected data row.
            dependencies.extend(table_rows[:2])
        dependencies.extend(turn_facts[max(0, position - 1) : position + 2])
    for dependency in dependencies:
        add(dependency)

    for fact in ranked:
        add(fact)

    # Presentation-only deduplication happens after all count/update analysis.
    # Count/list questions retain repetitions because occurrence itself is evidence.
    presented: list[AtomicFact] = []
    satisfied_ids = set(selected_ids)
    duplicate_of: dict[str, str] = {}
    seen_assistant_units: dict[str, AtomicFact] = {}
    for fact in selected:
        normalized = " ".join(fact.object_text.casefold().split())
        if (
            not broad_aggregation
            and fact.citation.speaker == "assistant"
            and fact.qualifiers.get("atomic_origin") == "deterministic_lossless"
            and normalized in seen_assistant_units
        ):
            duplicate_of[fact.fact_id] = seen_assistant_units[normalized].fact_id
            continue
        seen_assistant_units[normalized] = fact
        presented.append(fact)

    presented.sort(
        key=lambda fact: (
            fact.observed_date,
            ranks.get(fact.citation.session_id, 10_000),
            fact.citation.turn_index,
            fact.fact_id,
        )
    )
    context = "\n\n".join(render_atomic_fact(fact) for fact in presented)
    sessions_with_facts = {
        fact.citation.session_id for fact in analysis_facts
    }
    missing_sessions = [
        session_id for session_id in retrieved_session_ids
        if session_id in sessions_with_facts and session_id not in represented_sessions
    ]
    dropped_anchor_ids = sorted(important_anchor_ids - satisfied_ids)
    dropped_contract_candidate_ids = sorted(contract_candidate_ids - satisfied_ids)
    relevant_user_ids = {
        fact.fact_id
        for fact in analysis_facts
        if fact.citation.speaker == "user" and base_scores[fact.fact_id] >= 6.0
    }
    dropped_user_ids = sorted(relevant_user_ids - satisfied_ids)
    safety_reasons: list[str] = []
    if missing_sessions:
        safety_reasons.append("retrieved sessions received no evidence allocation")
    if dropped_anchor_ids:
        safety_reasons.append("relevant date/quantity/entity/state anchors were dropped")
    if dropped_contract_candidate_ids:
        safety_reasons.append("operation-required candidate facts were dropped")
    if broad_aggregation and dropped_user_ids:
        safety_reasons.append("potentially relevant user statements were truncated")
    return context, {
        "packing": ATOMIC_MEMORY_VERSION,
        "query_plan": query_plan.model_dump(mode="json"),
        "candidate_fact_count": len(facts),
        "analysis_fact_count": len(analysis_facts),
        "presentation_fact_count": len(presented),
        "selected_fact_count": len(presented),
        "selected_fact_ids": [fact.fact_id for fact in presented],
        "satisfied_fact_ids": sorted(satisfied_ids),
        "presentation_duplicate_of": duplicate_of,
        "represented_session_count": len(represented_sessions),
        "retrieved_session_count": len(retrieved_session_ids),
        "packed_tokens_estimate": estimate_atomic_tokens(context),
        "token_budget": token_budget,
        "important_anchor_count": len(important_anchor_ids),
        "contract_candidate_count": len(contract_candidate_ids),
        "dropped_anchor_fact_ids": dropped_anchor_ids,
        "dropped_contract_candidate_fact_ids": dropped_contract_candidate_ids,
        "dropped_relevant_user_fact_ids": dropped_user_ids,
        "missing_session_ids": missing_sessions,
        "safe": not safety_reasons,
        "safety_reasons": safety_reasons,
    }
