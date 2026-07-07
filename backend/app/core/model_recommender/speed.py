from __future__ import annotations

from typing import Any

from backend.app.core.model_recommender.hardware_profile import approximate_cpu_bandwidth_gbps, best_gpu

_BACKEND_FACTORS = {
    "nvidia": 1.0,
    "amd": 0.78,
    "intel": 0.66,
    "apple": 0.82,
}

_QUANT_FACTORS = {
    "Q4_K_M": 0.56,
    "Q5_K_M": 0.53,
    "Q6_K": 0.50,
    "Q8_0": 0.45,
    "F16": 0.40,
    "BF16": 0.40,
}


def estimate_chat_speed(profile: dict[str, Any], candidate: dict[str, Any], fit: dict[str, Any]) -> dict[str, Any]:
    gpu = best_gpu(profile)
    quant = str(candidate.get("quantization") or "Q4_K_M").upper()
    weight_bytes = float(candidate.get("estimated_weight_bytes") or 0.0)
    notes: list[str] = []
    if gpu and fit["fit_type"] != "cpu_only":
        bandwidth = float(gpu.get("memory_bandwidth_gbps") or 0.0)
        if bandwidth <= 0:
            bandwidth = _vram_bandwidth_proxy(int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0))
            notes.append("GPU bandwidth was inferred from VRAM class rather than measured directly.")
        effective_read_bytes = weight_bytes
        theoretical = (bandwidth * 1e9) / max(effective_read_bytes, 1.0)
        estimate = theoretical * _QUANT_FACTORS.get(quant, 0.45) * _BACKEND_FACTORS.get(str(gpu.get("vendor") or "intel"), 0.7)
        if fit["fit_type"] == "partial_offload":
            estimate *= 0.45 if not gpu.get("shared_memory") else 0.82
            notes.append("Estimated speed is penalized for partial offload.")
        if gpu.get("shared_memory"):
            notes.append("Shared-memory GPU results are conservative and may vary more than discrete VRAM estimates.")
        confidence = "medium" if bandwidth > 0 else "low"
    else:
        params_b = float(candidate.get("parameter_count_active_b") or candidate.get("parameter_count_total_b") or 1.0)
        estimate = max(0.3, (approximate_cpu_bandwidth_gbps(profile) / max(params_b, 0.5)) * 0.55 * _QUANT_FACTORS.get(quant, 0.45))
        notes.append("CPU-first estimate uses a coarse memory-bandwidth proxy and should be treated as directional.")
        confidence = "low"
    if fit["fit_type"] == "cannot_run":
        estimate = 0.0
        notes.append("No speed estimate is meaningful because the model does not pass the conservative fit gate.")
    thresholds = _threshold_flags(float(estimate))
    return {
        "estimated_tok_per_sec": round(float(estimate), 2),
        "confidence": confidence,
        "range_tok_per_sec": _speed_range(float(estimate), confidence),
        "notes": notes,
        "thresholds": thresholds,
    }


def _vram_bandwidth_proxy(vram_bytes: int) -> float:
    gib = vram_bytes / float(1024**3)
    if gib >= 20:
        return 700.0
    if gib >= 12:
        return 420.0
    if gib >= 8:
        return 280.0
    if gib >= 4:
        return 160.0
    return 0.0


def _speed_range(estimate: float, confidence: str) -> tuple[float, float] | None:
    if estimate <= 0:
        return None
    if confidence == "high":
        return (round(estimate * 0.85, 1), round(estimate * 1.2, 1))
    if confidence == "medium":
        return (round(estimate * 0.6, 1), round(estimate * 1.6, 1))
    return (round(estimate * 0.35, 1), round(estimate * 2.0, 1))


def _threshold_flags(estimate: float) -> dict[str, bool]:
    return {
        "fast_enough_for_chat": estimate >= 8.0,
        "acceptable_for_chat": estimate >= 4.0,
        "degraded_but_usable": estimate >= 1.5,
        "too_slow_for_default_chat": 0.0 < estimate < 1.5,
    }
