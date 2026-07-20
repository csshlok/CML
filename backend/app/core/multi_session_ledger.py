from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol


AssertionMode = Literal[
    "completed", "current", "planned", "suggested", "hypothetical", "unknown"
]
NumericRole = Literal["cumulative_snapshot", "delta", "measurement", "unknown"]
EventRole = Literal["start", "end", "update", "none"]


class ClaimLike(Protocol):
    session_id: str
    date: str
    retrieval_rank: int
    turn_index: int
    sentence_index: int
    speaker: str
    text: str

    @property
    def key(self) -> tuple[str, int, int]: ...


@dataclass(frozen=True)
class LedgerEntry:
    claim_key: tuple[str, int, int]
    session_id: str
    session_date: str
    retrieval_rank: int
    speaker: str
    text: str
    assertion_mode: AssertionMode
    numeric_role: NumericRole
    numeric_values: tuple[float, ...]
    event_role: EventRole
    query_overlap: int
    provenance_authority: int
    structured_topic_keys: tuple[str, ...] = ()
    structured_kinds: tuple[str, ...] = ()
    preference_polarities: tuple[str, ...] = ()

    @property
    def annotation(self) -> str:
        parts: list[str] = []
        if self.assertion_mode != "unknown":
            parts.append(self.assertion_mode)
        if self.numeric_role != "unknown":
            parts.append(self.numeric_role)
        if self.event_role != "none":
            parts.append(self.event_role)
        return ",".join(parts)


@dataclass(frozen=True)
class LedgerPlan:
    operation: Literal[
        "aggregate", "duration", "latest_state", "preference", "multi_session", "fact_lookup"
    ]
    target_terms: frozenset[str]
    prefer_user_provenance: bool
    prefer_latest: bool
    consolidate: bool = False


@dataclass(frozen=True)
class ConsolidationGroup:
    topic_key: str
    claim_keys: tuple[tuple[str, int, int], ...]
    session_ids: tuple[str, ...]
    latest_claim_key: tuple[str, int, int]
    conflicting_preference_stances: bool


_STOPWORDS = {
    "about", "after", "again", "also", "been", "before", "could", "did",
    "does", "from", "have", "into", "many", "more", "much", "should",
    "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "what", "when", "where", "which", "with", "would", "your",
    "you", "were", "was", "are", "the", "and", "for", "how", "who",
    "why", "does", "did", "get",
}

_NUMBER_WORDS = {
    "zero": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0,
    "five": 5.0, "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0,
    "ten": 10.0, "eleven": 11.0, "twelve": 12.0, "thirteen": 13.0,
    "fourteen": 14.0, "fifteen": 15.0, "sixteen": 16.0,
    "seventeen": 17.0, "eighteen": 18.0, "nineteen": 19.0,
    "twenty": 20.0,
}


def plan_ledger(
    question: str, question_type: str = "", *, consolidate: bool = False
) -> LedgerPlan:
    lowered = question.casefold()
    if "temporal" in question_type or re.search(
        r"\bhow long\b|\b(days?|weeks?|months?|years?)\b|\bwhen\b", lowered
    ):
        operation = "duration"
    elif re.search(r"\bhow (?:many|much|often)\b|\b(total|combined|sum)\b", lowered):
        operation = "aggregate"
    elif "knowledge-update" in question_type or re.search(
        r"\b(current|latest|now|still|changed|updated)\b", lowered
    ):
        operation = "latest_state"
    elif "preference" in question_type:
        operation = "preference"
    elif consolidate and question_type == "multi-session":
        operation = "multi_session"
    else:
        operation = "fact_lookup"
    return LedgerPlan(
        operation=operation,
        target_terms=frozenset(_terms(question)),
        prefer_user_provenance=question_type != "single-session-assistant",
        prefer_latest=operation in {"aggregate", "latest_state"},
        consolidate=consolidate,
    )


def build_evidence_ledger(
    question: str,
    question_type: str,
    claims: Iterable[ClaimLike],
    *,
    consolidate: bool = False,
) -> tuple[LedgerPlan, dict[tuple[str, int, int], LedgerEntry]]:
    plan = plan_ledger(question, question_type, consolidate=consolidate)
    entries = {
        claim.key: _entry(claim, plan)
        for claim in claims
    }
    return plan, entries


def ledger_priority(entry: LedgerEntry, plan: LedgerPlan) -> float:
    score = min(entry.query_overlap, 4) * 0.8
    score += entry.provenance_authority * 0.6
    if entry.assertion_mode in {"completed", "current"}:
        score += 1.0
    elif entry.assertion_mode in {"planned", "hypothetical", "suggested"}:
        score -= 0.8
    if plan.operation == "aggregate":
        if entry.numeric_role == "cumulative_snapshot":
            score += 2.4
        elif entry.numeric_role == "delta":
            score += 1.5
        elif entry.numeric_values:
            score += 0.8
    if plan.operation == "duration" and entry.event_role in {"start", "end"}:
        score += 2.2
    if plan.operation == "latest_state" and entry.event_role == "update":
        score += 1.8
    if plan.consolidate and plan.operation == "preference" and "preference" in entry.structured_kinds:
        score += 2.0
    if plan.consolidate and plan.operation == "multi_session" and entry.structured_topic_keys:
        score += 1.2
    return score


def ledger_anchor_keys(
    entries: dict[tuple[str, int, int], LedgerEntry],
    plan: LedgerPlan,
    *,
    limit: int = 12,
) -> list[tuple[str, int, int]]:
    candidates = [
        entry
        for entry in entries.values()
        if entry.query_overlap
        and (
            (plan.operation == "aggregate" and bool(entry.numeric_values))
            or (plan.operation == "duration" and entry.event_role in {"start", "end"})
            or (
                plan.operation == "latest_state"
                and entry.assertion_mode in {"completed", "current"}
            )
            or (
                plan.consolidate
                and plan.operation == "preference"
                and "preference" in entry.structured_kinds
            )
            or (
                plan.consolidate
                and plan.operation == "multi_session"
                and bool(entry.structured_topic_keys)
            )
        )
    ]
    candidates.sort(
        key=lambda entry: (
            ledger_priority(entry, plan),
            entry.session_date,
            -entry.retrieval_rank,
        ),
        reverse=True,
    )
    selected: list[tuple[str, int, int]] = []
    per_session: dict[str, int] = {}
    for entry in candidates:
        if per_session.get(entry.session_id, 0) >= 2:
            continue
        selected.append(entry.claim_key)
        per_session[entry.session_id] = per_session.get(entry.session_id, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def consolidation_groups(
    entries: dict[tuple[str, int, int], LedgerEntry],
    *,
    limit: int = 8,
) -> list[ConsolidationGroup]:
    """Group only explicit structured topics observed in multiple sessions."""
    by_topic: dict[str, list[LedgerEntry]] = {}
    for entry in entries.values():
        for topic_key in entry.structured_topic_keys:
            by_topic.setdefault(topic_key, []).append(entry)
    groups: list[ConsolidationGroup] = []
    for topic_key, topic_entries in by_topic.items():
        sessions = tuple(dict.fromkeys(entry.session_id for entry in topic_entries))
        if len(sessions) < 2:
            continue
        ordered = sorted(
            topic_entries,
            key=lambda entry: (entry.session_date, -entry.retrieval_rank, entry.claim_key),
        )
        stances = {
            polarity
            for entry in ordered
            for polarity in entry.preference_polarities
        }
        groups.append(
            ConsolidationGroup(
                topic_key=topic_key,
                claim_keys=tuple(entry.claim_key for entry in ordered),
                session_ids=sessions,
                latest_claim_key=ordered[-1].claim_key,
                conflicting_preference_stances={"positive", "negative"}.issubset(stances),
            )
        )
    groups.sort(
        key=lambda group: (len(group.session_ids), len(group.claim_keys), group.topic_key),
        reverse=True,
    )
    return groups[: max(1, limit)]


def _entry(claim: ClaimLike, plan: LedgerPlan) -> LedgerEntry:
    text = claim.text
    lowered = text.casefold()
    assertion_mode = _assertion_mode(lowered, claim.speaker)
    digit_values = tuple(
        float(value.replace(",", ""))
        for value in re.findall(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?", text)
    )
    word_values = tuple(
        _NUMBER_WORDS[token]
        for token in re.findall(r"[a-z]+", lowered)
        if token in _NUMBER_WORDS
    )
    numeric_values = digit_values + word_values
    return LedgerEntry(
        claim_key=claim.key,
        session_id=claim.session_id,
        session_date=claim.date,
        retrieval_rank=claim.retrieval_rank,
        speaker=claim.speaker,
        text=text,
        assertion_mode=assertion_mode,
        numeric_role=_numeric_role(lowered, bool(numeric_values)),
        numeric_values=numeric_values,
        event_role=_event_role(lowered),
        query_overlap=len(plan.target_terms & _terms(text)),
        provenance_authority=(
            1 if claim.speaker == "user" and plan.prefer_user_provenance else 0
        ),
        structured_topic_keys=tuple(getattr(claim, "structured_topic_keys", ()) or ()),
        structured_kinds=tuple(getattr(claim, "structured_kinds", ()) or ()),
        preference_polarities=tuple(getattr(claim, "preference_polarities", ()) or ()),
    )


def _assertion_mode(text: str, speaker: str) -> AssertionMode:
    if speaker == "assistant":
        return "suggested"
    if re.search(r"\b(if|might|maybe|would|could|hypothetically)\b", text):
        return "hypothetical"
    if re.search(r"\b(plan(?:ning)?|intend|want to|going to|will|hope to)\b", text):
        return "planned"
    if re.search(
        r"\b(did|attended|completed|finished|bought|visited|went|got back|"
        r"returned|started|made|used|tried|serviced|have been|i've been)\b",
        text,
    ):
        return "completed"
    if re.search(r"\b(am|is|are|currently|now|still|remember|have)\b", text):
        return "current"
    return "unknown"


def _numeric_role(text: str, has_number: bool) -> NumericRole:
    if not has_number:
        return "unknown"
    if re.search(r"\b(so far|in total|total of|altogether|already|now|to date|that's)\b", text):
        return "cumulative_snapshot"
    if re.search(r"\b(another|additional|more|added|extra|increment)\b", text):
        return "delta"
    if re.search(r"\b(ounces?|pounds?|kg|kilograms?|miles?|km|percent|%)\b", text):
        return "measurement"
    return "cumulative_snapshot"


def _event_role(text: str) -> EventRole:
    if re.search(r"\b(started|began|left|departed|set out)\b", text):
        return "start"
    if re.search(r"\b(got back|returned|ended|finished|completed|arrived home)\b", text):
        return "end"
    if re.search(r"\b(now|currently|updated|changed|instead|remember)\b", text):
        return "update"
    return "none"


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) >= 3 and token not in _STOPWORDS
    }
