from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.core.hardware import hardware_status


_HARDWARE_BASE_BUDGETS = {
    "unsupported": 1200,
    "unknown": 1200,
    "cpu_minimum_spec": 1600,
    "cpu_high_spec": 2800,
    "gpu_or_high_spec_candidate": 4200,
}

_MODEL_MULTIPLIERS = {
    "small": 1.0,
    "standard": 1.0,
    "quality": 1.35,
    "large": 1.5,
}

_QUERY_MULTIPLIERS = {
    "general": 0.75,
    "fact_lookup": 0.9,
    "compare_synthesis": 1.1,
    "plan_multistep": 1.25,
    "expanded_analysis": 1.5,
}

_TRUST_MULTIPLIERS = {
    "trusted": 1.0,
    "mixed": 0.85,
    "low_trust_heavy": 0.65,
}


def select_context_budget(
    *,
    prompt: str,
    runtime_state: str,
    expanded_analysis: bool,
    trust_gate: dict | None,
    cluster_count_used: int,
    candidate_citation_count: int,
) -> dict:
    settings = get_settings()
    floor_budget = max(int(settings.llm_context_token_budget), 1200)
    hardware = hardware_status()
    hardware_tier = str(hardware.get("hardware_tier") or "unknown")
    base_budget = _HARDWARE_BASE_BUDGETS.get(hardware_tier, floor_budget)
    model_tier = classify_chat_model_tier(settings.llm_model)
    query_type = classify_query_type(prompt, expanded_analysis=expanded_analysis, cluster_count_used=cluster_count_used)
    trust_mode = classify_trust_mode(trust_gate)

    selected = float(base_budget)
    selected *= _MODEL_MULTIPLIERS[model_tier]
    selected *= _QUERY_MULTIPLIERS[query_type]
    selected *= _TRUST_MULTIPLIERS[trust_mode]

    widening_reason = ""
    narrowing_reason = ""
    if runtime_state == "busy":
        selected *= 0.8
        narrowing_reason = "runtime_busy"
    elif runtime_state not in {"ready", "busy"}:
        selected *= 0.75
        narrowing_reason = "runtime_degraded"

    if candidate_citation_count >= 8 and trust_mode == "trusted":
        selected *= 1.1
        widening_reason = "broad_candidate_set"

    final_budget = min(max(int(round(selected)), floor_budget), 8000)
    return {
        "token_budget": final_budget,
        "fallback_floor_budget": floor_budget,
        "hardware_tier": hardware_tier,
        "model_tier": model_tier,
        "query_type": query_type,
        "trust_mode": trust_mode,
        "widening_applied": final_budget > floor_budget,
        "narrowing_applied": final_budget < int(round(base_budget * _MODEL_MULTIPLIERS[model_tier])),
        "widening_reason": widening_reason,
        "narrowing_reason": narrowing_reason,
        "candidate_citation_count": candidate_citation_count,
    }


def classify_chat_model_tier(model_name: str) -> str:
    normalized = str(model_name or "").lower()
    if any(marker in normalized for marker in ("12b", "14b", "32b")):
        return "large"
    if any(marker in normalized for marker in ("8b", "9b")):
        return "quality"
    if any(marker in normalized for marker in ("4b", "mini", "3b", "2b")):
        return "standard"
    return "small"


def classify_query_type(prompt: str, *, expanded_analysis: bool, cluster_count_used: int) -> str:
    normalized = " ".join(str(prompt or "").lower().split())
    if expanded_analysis:
        return "expanded_analysis"
    if any(word in normalized for word in ("plan", "roadmap", "work path", "steps", "compare", "difference")):
        return "plan_multistep"
    if cluster_count_used > 1 or any(word in normalized for word in ("compare", "tradeoff", "pros and cons", "why")):
        return "compare_synthesis"
    if normalized.startswith(("what ", "which ", "where ", "when ", "who ")) or "summary" in normalized:
        return "fact_lookup"
    return "general"


def classify_trust_mode(trust_gate: dict | None) -> str:
    if not trust_gate:
        return "trusted"
    mode = str(trust_gate.get("mode") or "")
    if mode in {"degraded_all_low_trust", "refuse_sensitive_low_trust"}:
        return "low_trust_heavy"
    if float(trust_gate.get("low_trust_ratio") or 0) > 0:
        return "mixed"
    return "trusted"
