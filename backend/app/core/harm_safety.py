from __future__ import annotations

import re
import unicodedata
from typing import Literal, TypedDict


HarmCategory = Literal[
    "explosives_or_incendiaries",
    "toxic_or_biological_agents",
    "weapon_construction",
    "targeted_physical_harm",
]


class HarmSafetyDecision(TypedDict):
    action: Literal["allow", "refuse"]
    category: HarmCategory | None
    reason: str


_CAPABILITY_PATTERNS: tuple[tuple[HarmCategory, re.Pattern[str]], ...] = (
    (
        "explosives_or_incendiaries",
        re.compile(
            r"\b(?:bombs?|explosives?|explosive devices?|improvised explosive devices?|"
            r"ieds?|detonators?|incendiaries|incendiary devices?|molotov cocktails?|"
            r"pipe bombs?|landmines?)\b"
        ),
    ),
    (
        "toxic_or_biological_agents",
        re.compile(
            r"\b(?:chemical weapons?|biological weapons?|nerve agents?|toxic gases?|"
            r"poisons?|poisoning|weaponized pathogens?|weaponised pathogens?)\b"
        ),
    ),
    (
        "weapon_construction",
        re.compile(
            r"\b(?:firearms?|ghost guns?|silencers?|firearm suppressors?|weapons?)\b"
        ),
    ),
)

_PROCEDURAL_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:teach|show|tell|walk)\s+(?:me|us)\s+how\s+to\b"),
    re.compile(
        r"\bhow\s+to\s+(?:make|build|create|assemble|construct|prepare|synthesize|"
        r"synthesise|produce|weaponize|weaponise|deploy)\b"
    ),
    re.compile(
        r"\bhow\s+(?:do|can|could|would|should)\s+(?:i|we|you|someone|a person)\b"
        r".{0,100}\b(?:make|build|create|assemble|construct|prepare|synthesize|"
        r"synthesise|produce|weaponize|weaponise|deploy|poison|kill|injure|attack)\b"
    ),
    re.compile(
        r"\b(?:give|provide|write|list|share|explain)\b.{0,45}"
        r"\b(?:step[- ]by[- ]step|instructions?|recipe|blueprint|construction plan)\b"
    ),
    re.compile(
        r"\b(?:steps?|instructions?|recipe|blueprint)\s+(?:for|to|on)\b"
    ),
    re.compile(
        r"\b(?:best|easiest|fastest|quietest|most effective)\s+way\s+to\b"
    ),
    re.compile(
        r"\b(?:materials?|ingredients?|parts?)\s+(?:do\s+i\s+need|are\s+needed|required)"
        r"\b"
    ),
    re.compile(
        r"\b(?:without|while)\s+(?:getting\s+caught|being\s+detected|leaving\s+evidence)\b"
    ),
)

_DIRECT_HARM_PATTERN = re.compile(
    r"\b(?:kill|murder|poison|injure|maim|hurt|attack)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:person|someone|people|them|him|her|target|victim)\b"
)

_OPERATIONAL_DETAIL_PATTERN = re.compile(
    r"\b(?:household|common|readily available|easy to obtain|untraceable)\b.{0,80}"
    r"\b(?:materials?|chemicals?|parts?|components?)\b"
)


def classify_harmful_capability_request(prompt: str) -> HarmSafetyDecision:
    """Classify explicit requests that would operationally enable physical harm.

    The gate requires both a harmful capability or target and procedural intent.
    Merely discussing a dangerous topic remains allowed, which keeps historical,
    fictional, preventative, emergency, and high-level questions available to the
    normal model and retrieval router.
    """

    normalized = _normalize(prompt)
    if not normalized:
        return _allow("empty_prompt")

    category = _capability_category(normalized)
    direct_targeted_harm = bool(_DIRECT_HARM_PATTERN.search(normalized))
    procedural_text = re.sub(
        r"\bwithout\s+(?:(?:technical|actionable|operational|construction)\s+)?"
        r"(?:instructions?|details?|steps?)\b",
        "",
        normalized,
    )
    procedural = any(
        pattern.search(procedural_text) for pattern in _PROCEDURAL_INTENT_PATTERNS
    )
    operational_detail = bool(_OPERATIONAL_DETAIL_PATTERN.search(normalized))

    if direct_targeted_harm and (
        procedural
        or normalized.startswith(("how ", "what is the best ", "what's the best "))
    ):
        return {
            "action": "refuse",
            "category": "targeted_physical_harm",
            "reason": "procedural_targeted_physical_harm",
        }
    if category is not None and (procedural or operational_detail):
        return {
            "action": "refuse",
            "category": category,
            "reason": "procedural_harmful_capability",
        }
    return _allow("non_procedural_or_non_harmful")


def safety_refusal_text() -> str:
    return (
        "I can't help with instructions that would meaningfully enable physical harm "
        "or weapon construction. I can help with emergency response, prevention, "
        "legal and historical information, or a non-actionable explanation of the topic."
    )


def _normalize(prompt: str) -> str:
    value = unicodedata.normalize("NFKC", prompt).casefold()
    value = value.replace("’", "'").replace("`", "'")
    return " ".join(value.split())


def _capability_category(prompt: str) -> HarmCategory | None:
    for category, pattern in _CAPABILITY_PATTERNS:
        if pattern.search(prompt):
            return category
    return None


def _allow(reason: str) -> HarmSafetyDecision:
    return {"action": "allow", "category": None, "reason": reason}
