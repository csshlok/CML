from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal


AssertionKind = Literal["fact", "preference", "suggestion", "action", "plan", "goal", "state"]
Modality = Literal["asserted", "negated", "hypothetical"]


@dataclass(frozen=True)
class StructuredClaim:
    subject_key: str
    predicate_key: str
    object_text: str
    assertion_kind: AssertionKind
    citation_excerpt: str
    modality: Modality = "asserted"
    supersession_key: str = ""
    supersede_current: bool = False
    confidence: float = 0.9
    metadata: dict[str, str] = field(default_factory=dict)


def extract_structured_claims(content: str, speaker: str) -> list[StructuredClaim]:
    """Extract only explicit, source-verbatim claims.

    This deliberately avoids inference and pronoun resolution. Every citation is an
    exact substring of the whitespace-normalized source, which lets callers retain
    immutable provenance while sharing the same semantics in product and evaluation.
    """
    role = str(speaker or "").strip().lower()
    text = " ".join(str(content or "").split())
    if role not in {"user", "assistant"} or not text:
        return []
    if role == "assistant":
        return _assistant_claims(text)

    claims: list[StructuredClaim] = []
    for segment in split_claim_units(text):
        claims.extend(_user_segment_claims(segment))
    deduped: list[StructuredClaim] = []
    seen: set[tuple[str, str, str, str]] = set()
    for claim in claims:
        key = (
            claim.predicate_key,
            _key(claim.object_text),
            claim.modality,
            claim.citation_excerpt.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def canonical_topic_key(value: str) -> str:
    """Normalize formatting variants without guessing semantic equivalence."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"['’]s\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    normalized = re.sub(r"^(?:a|an|the)\s+", "", normalized)
    return "_".join(normalized.split())


def split_claim_units(text: str) -> list[str]:
    """Split explicit compound first-person clauses without rewriting their text."""
    raw = re.split(
        r"(?<=[.!?;])\s+|,\s+(?=(?:but\s+)?I\b)|\s+(?=and\s+I\b)",
        text,
        flags=re.IGNORECASE,
    )
    output: list[str] = []
    for item in raw:
        segment = re.sub(r"^(?:and|but)\s+", "", item.strip(), flags=re.IGNORECASE)
        if segment:
            output.append(segment)
    return output


def _user_segment_claims(segment: str) -> list[StructuredClaim]:
    claims: list[StructuredClaim] = []

    current_activity = re.search(
        r"\bi (?:(?:am|'m) currently|currently|(?:am|'m) now)\s+"
        r"(?P<verb>reading|devouring|using|working on|obsessed with|keeping|storing|"
        r"watching|driving|taking|wearing)\s+(?P<object>.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if current_activity:
        verb = current_activity.group("verb").casefold().replace(" ", "_")
        normalized_verb = "reading" if verb == "devouring" else verb
        metadata = {"family": "current_activity"}
        if normalized_verb == "reading":
            metadata["object_type"] = "book"
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key=f"currently_{normalized_verb}",
                object_text=current_activity.group("object").strip(),
                assertion_kind="state",
                citation_excerpt=current_activity.group(0),
                supersession_key=f"user:current_activity:{normalized_verb}",
                supersede_current=True,
                metadata=metadata,
                confidence=0.92,
            )
        )

    current_use = re.search(
        r"\bi currently use\s+(?P<object>.+?)(?:[.!?]|$)", segment, re.I
    )
    if current_use:
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key="currently_uses",
                object_text=current_use.group("object").strip(),
                assertion_kind="state",
                citation_excerpt=current_use.group(0),
                supersession_key="user:currently_uses",
                supersede_current=True,
                metadata={"family": "current_possession_or_use"},
                confidence=0.92,
            )
        )

    current_quantity = re.search(
        r"\bi (?:(?:am|'m) now at|now (?:have|own|lead)|currently (?:have|own|lead))\s+"
        r"(?P<object>.+?)(?:[.!?]|$)|"
        r"\bi (?:have|own|lead)\s+(?P<trailing_object>.+?)\s+(?:right )?now(?:[.!?]|$)",
        segment,
        re.I,
    )
    if current_quantity:
        quantity_object = (
            current_quantity.group("object")
            or current_quantity.group("trailing_object")
        ).strip()
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key="current_quantity",
                object_text=quantity_object,
                assertion_kind="state",
                citation_excerpt=current_quantity.group(0),
                supersession_key=(
                    "user:current_quantity:"
                    + canonical_topic_key(quantity_object)
                ),
                supersede_current=True,
                metadata={"family": "current_quantity"},
                confidence=0.9,
            )
        )

    current_location = re.search(
        r"\bi (?:(?:currently|now) )?(?:keep|store)\s+"
        r"(?P<object>.+?)\s+(?:in|on|at)\s+(?P<location>.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if current_location:
        stored_object = current_location.group("object").strip()
        location = current_location.group("location").strip()
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key="currently_stored_at",
                object_text=location,
                assertion_kind="state",
                citation_excerpt=current_location.group(0),
                supersession_key=(
                    "user:stored_location:" + canonical_topic_key(stored_object)
                ),
                supersede_current=True,
                metadata={
                    "family": "stored_location",
                    "stored_object": stored_object,
                },
                confidence=0.92,
            )
        )

    favorite = re.search(
        r"\bmy favou?rite\s+(.+?)\s+is\s+(.+?)(?:[.!?]|$)", segment, re.I
    )
    if favorite:
        category = favorite.group(1).strip()
        value = favorite.group(2).strip()
        claims.append(
            _preference(
                value,
                favorite.group(0),
                polarity="positive",
                topic=f"favorite:{_key(category)}",
                family="favorite",
            )
        )

    positive = re.search(
        r"\bi (?:really )?(?:prefer|like|love|enjoy)\s+(.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if positive:
        object_text = re.split(r"\s+over\s+", positive.group(1), maxsplit=1, flags=re.I)[0].strip()
        claims.append(_preference(object_text, positive.group(0), polarity="positive"))

    rather = re.search(
        r"\bi(?:'d| would) rather\s+(.+?)(?:\s+than\s+.+?)?(?:[.!?]|$)",
        segment,
        re.I,
    )
    if rather:
        claims.append(_preference(rather.group(1).strip(), rather.group(0), polarity="positive"))

    negative = re.search(
        r"\bi (?:(?:do not|don't) like|no longer like|dislike|hate|avoid|can't stand|cannot stand)"
        r"\s+(.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if negative:
        claims.append(_preference(negative.group(1).strip(), negative.group(0), polarity="negative"))

    habitual = re.search(
        r"\bi (?:usually|typically|normally) (?:choose|pick|reach for|go with)\s+(.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if habitual:
        claims.append(
            _preference(
                habitual.group(1).strip(),
                habitual.group(0),
                polarity="positive",
                family="habitual_choice",
                confidence=0.84,
            )
        )

    first_choice = re.search(
        r"\b(.+?) is my (?:usual |typical )?first choice(?:[.!?]|$)", segment, re.I
    )
    if first_choice and not re.search(r"\b(if|would|could|might)\b", first_choice.group(1), re.I):
        claims.append(
            _preference(
                first_choice.group(1).strip(),
                first_choice.group(0),
                polarity="positive",
                family="first_choice",
                confidence=0.84,
            )
        )

    no_longer_reaches = re.search(
        r"\bi (?:do not|don't|no longer) reach for\s+(.+?)(?:\s+anymore)?(?:[.!?]|$)",
        segment,
        re.I,
    )
    if no_longer_reaches:
        claims.append(
            _preference(
                no_longer_reaches.group(1).strip(),
                no_longer_reaches.group(0),
                polarity="negative",
                family="habitual_choice",
                confidence=0.84,
            )
        )

    patterns: tuple[tuple[re.Pattern[str], str, AssertionKind, bool, dict[str, str]], ...] = (
        (re.compile(r"\bi (?:now )?(?:live in|moved to)\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "lives_in", "state", True, {"family": "location"}),
        (re.compile(r"\bi (?:am|'m) based in\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "lives_in", "state", True, {"family": "location"}),
        (re.compile(r"\bi (?:now )?work at\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "works_at", "state", True, {"family": "work"}),
        (re.compile(r"\bmy name is\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "name", "fact", True, {"family": "identity"}),
        (re.compile(r"\bmy time ?zone is\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "timezone", "state", True, {"family": "locale"}),
        (re.compile(r"\bi (?:work as|am employed as)\s+(?:an?\s+)?(?P<object>.+?)(?:[.!?]|$)", re.I), "role", "state", True, {"family": "work"}),
        (re.compile(r"\bmy (?:role|job title) is\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "role", "state", True, {"family": "work"}),
        (re.compile(r"\bi speak\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "speaks", "fact", False, {"family": "language"}),
        (re.compile(r"\bmy goal is(?: to)?\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "goal", "goal", False, {"family": "goal"}),
        (re.compile(r"\bi (?:decided|have decided) to\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "decided", "action", False, {"family": "decision"}),
        (re.compile(r"\bremember that\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "stated_fact", "fact", False, {"family": "explicit_memory"}),
        (re.compile(r"\bi (?:plan to|am going to|want to|would like to)\s+(?P<object>.+?)(?:[.!?]|$)", re.I), "plans", "plan", False, {}),
    )
    for pattern, predicate, kind, supersede, metadata in patterns:
        match = pattern.search(segment)
        if not match:
            continue
        object_text, temporal_metadata = _strip_temporal_suffix(match.group("object").strip())
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key=predicate,
                object_text=object_text,
                assertion_kind=kind,
                citation_excerpt=match.group(0),
                supersession_key=f"user:{predicate}" if supersede else "",
                supersede_current=supersede,
                metadata={**metadata, **temporal_metadata},
            )
        )

    action = re.search(
        r"\bi (?:just |recently |already |finally )?"
        r"(?P<verb>bought|made|visited|completed|finished|started|stopped|attended|used|tried)"
        r"\s+(?P<object>.+?)(?:[.!?]|$)",
        segment,
        re.I,
    )
    if action:
        object_text, temporal_metadata = _strip_temporal_suffix(action.group("object").strip())
        claims.append(
            StructuredClaim(
                subject_key="user",
                predicate_key="completed_action",
                object_text=f"{action.group('verb')} {object_text}".strip(),
                assertion_kind="action",
                citation_excerpt=action.group(0),
                metadata=temporal_metadata,
            )
        )

    negated_states = (
        (re.compile(r"\bi (?:no longer|do not|don't) live in\s+(.+?)(?:[.!?]|$)", re.I), "lives_in"),
        (re.compile(r"\bi (?:no longer|do not|don't) work at\s+(.+?)(?:[.!?]|$)", re.I), "works_at"),
    )
    for pattern, predicate in negated_states:
        match = pattern.search(segment)
        if match:
            claims.append(
                StructuredClaim(
                    subject_key="user",
                    predicate_key=predicate,
                    object_text=match.group(1).strip(),
                    assertion_kind="state",
                    citation_excerpt=match.group(0),
                    modality="negated",
                    supersession_key=f"user:{predicate}",
                    supersede_current=True,
                    confidence=0.95,
                )
            )
    return claims


def _preference(
    object_text: str,
    citation: str,
    *,
    polarity: str,
    topic: str | None = None,
    family: str = "preference",
    confidence: float = 0.9,
) -> StructuredClaim:
    normalized_topic = topic or canonical_topic_key(object_text)
    return StructuredClaim(
        subject_key="user",
        predicate_key="prefers" if polarity == "positive" else "avoids",
        object_text=object_text,
        assertion_kind="preference",
        citation_excerpt=citation,
        supersession_key=f"user:preference:{normalized_topic}",
        supersede_current=True,
        metadata={"polarity": polarity, "family": family},
        confidence=confidence,
    )


def _assistant_claims(text: str) -> list[StructuredClaim]:
    suggestion = re.search(
        r"(?:\byou (?:could|should|might)|\btry|\bconsider|\bi recommend)\s+(.+?)(?:[.!?]|$)",
        text,
        re.I,
    )
    if not suggestion:
        return []
    return [
        StructuredClaim(
            subject_key="user",
            predicate_key="suggested_option",
            object_text=suggestion.group(1).strip(),
            assertion_kind="suggestion",
            citation_excerpt=suggestion.group(0),
        )
    ]


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", "_", value.strip().lower()).strip("_")


def _strip_temporal_suffix(value: str) -> tuple[str, dict[str, str]]:
    match = re.search(
        r"\s+(?P<expression>today|yesterday|last week|\d+\s+(?:days?|weeks?)\s+ago|"
        r"on\s+\d{4}-\d{2}-\d{2})$",
        value,
        re.I,
    )
    if not match:
        return value, {}
    cleaned = value[: match.start()].strip(" ,")
    return cleaned or value, {"event_time_expression": match.group("expression")}
