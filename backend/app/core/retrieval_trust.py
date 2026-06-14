import json
import re
from collections import Counter
from time import perf_counter

LOW_TRUST_TIERS = {"low_trust_web", "quarantined"}
TRUSTED_TIERS = {"trusted_local", "imported_local", "trusted_reviewed"}
MEDIUM_TRUST_TIERS = {"imported_web", "web_static", "external_capture"}
LOW_TRUST_LABELS = {
    "low_trust",
    "browser_derived",
    "defender_failed",
    "review_needed",
    "ungrounded_external",
    "partial_external",
}
EXCLUDED_FROM_SYNTHESIS_LABELS = {"review_needed", "ungrounded_external", "partial_external"}
SYNTHESIS_LOW_TRUST_CAP = 1
LOW_TRUST_DOMINANCE_RATIO = 0.5
SENSITIVE_QUERY_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "credentials_secrets": re.compile(
        r"\b(password|passphrase|recovery key|api key|token|secret|private key|ssh key|seed phrase)\b",
        re.IGNORECASE,
    ),
    "finance": re.compile(
        r"\b(bank|financial|finance|tax|ssn|social security|credit card|wallet)\b",
        re.IGNORECASE,
    ),
    "medical": re.compile(
        r"\b(doctor|medical|medication|medicine|prescription|diagnosis|diagnoses|lab result|test result|diagnosed|clinic)\b",
        re.IGNORECASE,
    ),
    "therapy_mental_health": re.compile(
        r"\b(therapy|therapist|counseling|counselling|mental health|trauma|addiction|depression|anxiety|psychiatrist)\b",
        re.IGNORECASE,
    ),
    "legal": re.compile(
        r"\b(attorney|lawyer|legal|nda|contract|agreement|lawsuit|court|settlement)\b",
        re.IGNORECASE,
    ),
    "identity": re.compile(
        r"\b(passport|license|licence|immigration|visa|identity|birth certificate|drivers license|driver's license)\b",
        re.IGNORECASE,
    ),
    "employment": re.compile(
        r"\b(salary|payroll|termination|performance review|hr|employment|manager feedback|promotion|job offer)\b",
        re.IGNORECASE,
    ),
    "family_private_correspondence": re.compile(
        r"\b(private correspondence|family|relationship|child|children|custody|spouse|partner|daughter|son)\b",
        re.IGNORECASE,
    ),
    "safety": re.compile(
        r"\b(safety|threat|abuse|police|incident|stalking|harassment|danger)\b",
        re.IGNORECASE,
    ),
}


def trust_weight(candidate: dict) -> float:
    if is_low_trust(candidate):
        return 0.55
    tier = str(_value(candidate, "trust_tier") or "").lower()
    if tier in MEDIUM_TRUST_TIERS or tier.startswith("imported_web"):
        return 0.85
    return 1.0


def is_low_trust(candidate: dict) -> bool:
    tier = str(_value(candidate, "trust_tier") or "").lower()
    if tier in LOW_TRUST_TIERS:
        return True
    labels = {str(label).lower() for label in _labels(_value(candidate, "security_labels"))}
    return bool(labels & LOW_TRUST_LABELS)


def is_trusted(candidate: dict) -> bool:
    return str(_value(candidate, "trust_tier") or "").lower() in TRUSTED_TIERS and not is_low_trust(candidate)


def classify_evidence_trust(prompt: str, citations: list[dict]) -> dict:
    started = perf_counter()
    total = len(citations)
    low_trust = [citation for citation in citations if is_low_trust(citation)]
    trusted = [citation for citation in citations if is_trusted(citation)]
    sensitive_categories = sensitive_query_categories(prompt)
    sensitive = bool(sensitive_categories)
    low_count = len(low_trust)
    trusted_count = len(trusted)
    low_ratio = low_count / total if total else 0.0
    reasons: list[str] = []
    mode = "normal"
    allow_synthesis = True
    if total == 0:
        mode = "no_evidence"
        allow_synthesis = False
    elif sensitive and trusted_count == 0:
        mode = "refuse_sensitive_low_trust"
        allow_synthesis = False
        reasons.append("sensitive_query_without_trusted_evidence")
        reasons.extend(f"sensitive_category:{category}" for category in sensitive_categories)
    elif low_count == total:
        mode = "degraded_all_low_trust"
        allow_synthesis = False
        reasons.append("all_evidence_low_trust")
    elif low_ratio > LOW_TRUST_DOMINANCE_RATIO:
        mode = "degraded_low_trust_dominant"
        reasons.append("low_trust_evidence_dominant")
    warnings = _warnings(mode, total, low_count, trusted_count)
    return {
        "mode": mode,
        "allow_synthesis": allow_synthesis,
        "sensitive_query": sensitive,
        "sensitive_query_categories": sensitive_categories,
        "evidence_count": total,
        "trusted_count": trusted_count,
        "low_trust_count": low_count,
        "low_trust_ratio": round(low_ratio, 4),
        "trust_tier_counts": dict(Counter(str(_value(item, "trust_tier") or "unknown") for item in citations)),
        "reasons": reasons,
        "warnings": warnings,
        "latency_ms": round((perf_counter() - started) * 1000, 3),
    }


def citations_for_synthesis(citations: list[dict], trust_gate: dict) -> list[dict]:
    if not trust_gate.get("allow_synthesis"):
        return []
    eligible = [citation for citation in citations if not _has_excluded_synthesis_label(citation)]
    trusted_or_medium = [citation for citation in eligible if not is_low_trust(citation)]
    low_trust = [citation for citation in eligible if is_low_trust(citation)]
    return [*trusted_or_medium, *low_trust[:SYNTHESIS_LOW_TRUST_CAP]]


def is_sensitive_query(prompt: str) -> bool:
    return bool(sensitive_query_categories(prompt))


def sensitive_query_categories(prompt: str) -> list[str]:
    normalized = str(prompt or "").strip()
    if not normalized:
        return []
    categories: list[str] = []
    for category, pattern in SENSITIVE_QUERY_CATEGORY_PATTERNS.items():
        if pattern.search(normalized):
            categories.append(category)
    return categories


def _warnings(mode: str, total: int, low_count: int, trusted_count: int) -> list[str]:
    if mode == "no_evidence":
        return []
    if mode == "refuse_sensitive_low_trust":
        return [
            "Trust gate: this looks sensitive and the retrieved evidence has no trusted local support; CML will not synthesize from low-trust evidence."
        ]
    if mode == "degraded_all_low_trust":
        return [
            "Trust gate: all retrieved evidence is low-trust, so CML is using a degraded extractive answer instead of model synthesis."
        ]
    if mode == "degraded_low_trust_dominant":
        return [
            f"Trust gate: {low_count}/{total} retrieved item(s) are low-trust; CML will limit low-trust evidence during synthesis."
        ]
    if low_count:
        return [
            f"Trust gate: {low_count}/{total} retrieved item(s) are low-trust and {trusted_count} trusted item(s) support this answer."
        ]
    return []


def _labels(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _has_excluded_synthesis_label(candidate: dict) -> bool:
    labels = {str(label).lower() for label in _labels(_value(candidate, "security_labels"))}
    return bool(labels & EXCLUDED_FROM_SYNTHESIS_LABELS)


def _value(candidate, key: str):
    if hasattr(candidate, "keys") and key in candidate.keys():
        return candidate[key]
    if isinstance(candidate, dict):
        return candidate.get(key)
    return None
