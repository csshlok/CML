from __future__ import annotations

import math
from typing import Any


_BENCHMARK_SOURCE_WEIGHTS = {
    "internal_measured": 0.68,
    "direct": 0.62,
    "base_model": 0.55,
    "variant": 0.50,
    "line_interp": 0.40,
    "self_reported": 0.30,
    "catalog_estimate": 0.36,
    "none": 0.0,
}

_FIT_PENALTIES = {
    "full_gpu": 0.0,
    "partial_offload": -10.0,
    "cpu_only": -18.0,
    "cannot_run": -100.0,
}


def score_chat_candidate(candidate: dict[str, Any], fit: dict[str, Any], speed: dict[str, Any], evidence: dict[str, Any]) -> float:
    params_b = float(candidate.get("parameter_count_total_b") or 0.0)
    benchmark_score = float(evidence.get("score") or 0.0) * _BENCHMARK_SOURCE_WEIGHTS.get(str(evidence.get("source") or "none"), 0.0)
    size_score = min(35.0, 4.2 * math.log2(max(params_b, 0.5)) + 9.0)
    quant_penalty = _quant_penalty(str(candidate.get("quantization") or "Q4_K_M"))
    quality_core = (benchmark_score + size_score) * (1.0 - quant_penalty)
    if evidence.get("source") == "none":
        quality_core *= 0.55
    elif evidence.get("source") in {"base_model", "variant", "line_interp"}:
        quality_core *= 0.78
    speed_score = _speed_score(float(speed.get("estimated_tok_per_sec") or 0.0), str(fit.get("fit_type") or "cannot_run"))
    fit_penalty = _FIT_PENALTIES.get(str(fit.get("fit_type") or "cannot_run"), -100.0)
    return max(0.0, min(100.0, quality_core + speed_score + fit_penalty))
def _speed_score(tok_per_sec: float, fit_type: str) -> float:
    required = 8.0 if fit_type == "full_gpu" else (4.0 if fit_type == "partial_offload" else 1.5)
    if tok_per_sec <= 0:
        return -12.0
    if tok_per_sec < required:
        return -8.0 * (1.0 - (tok_per_sec / required))
    return min(8.0, math.log2(tok_per_sec / required + 1.0) * 3.2)


def _quant_penalty(quantization: str) -> float:
    quant = quantization.upper()
    if quant in {"Q4_K_M", "Q4_K_S"}:
        return 0.05
    if quant in {"Q5_K_M", "Q5_K_S"}:
        return 0.03
    if quant == "Q6_K":
        return 0.02
    if quant == "Q8_0":
        return 0.01
    if quant in {"F16", "BF16"}:
        return 0.0
    return 0.08
