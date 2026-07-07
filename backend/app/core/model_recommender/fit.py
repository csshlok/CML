from __future__ import annotations

from typing import Any

from backend.app.core.model_recommender.catalog import minimum_tier_satisfied
from backend.app.core.model_recommender.hardware_profile import best_gpu, gib_to_bytes

_FRAMEWORK_OVERHEAD_BYTES = 400 * 1024**2
_ACTIVATION_BASE_BYTES = 350 * 1024**2


def estimate_chat_fit(profile: dict[str, Any], candidate: dict[str, Any], context_length: int = 8192) -> dict[str, Any]:
    total_weight_bytes = int(candidate.get("estimated_weight_bytes") or 0)
    active_params_b = float(
        candidate.get("parameter_count_active_b")
        or candidate.get("parameter_count_total_b")
        or 0.0
    )
    kv_cache = int(active_params_b * (context_length / 1024.0) * (3.25 * 1024**2))
    activation = _ACTIVATION_BASE_BYTES + int(active_params_b * 0.10 * 1024**3)
    required_bytes = total_weight_bytes + kv_cache + activation + _FRAMEWORK_OVERHEAD_BYTES
    gpu = best_gpu(profile)
    usable_ram = int(profile.get("ram_usable_bytes") or 0)
    gpu_bytes = int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0) if gpu else 0
    shared_memory = bool(gpu.get("shared_memory")) if gpu else False
    offload_ram = usable_ram if gpu and not shared_memory else 0
    warnings: list[str] = []
    if gpu_bytes >= required_bytes and gpu_bytes > 0:
        fit_type = "full_gpu"
        feasible = True
        offload_ratio = 0.0
    elif gpu_bytes > 0 and gpu_bytes + offload_ram >= required_bytes:
        fit_type = "partial_offload"
        feasible = True
        offload_ratio = max(0.0, min(1.0, (required_bytes - gpu_bytes) / max(required_bytes, 1)))
        if shared_memory:
            warnings.append("Uses shared system memory instead of a fully isolated VRAM budget.")
        else:
            warnings.append(f"About {round(offload_ratio * 100)}% of the model would spill into CPU RAM.")
    elif usable_ram >= required_bytes:
        fit_type = "cpu_only"
        feasible = True
        offload_ratio = 0.0
        warnings.append("This model fits only as a CPU-first fallback and will respond slowly.")
    else:
        fit_type = "cannot_run"
        feasible = False
        offload_ratio = 0.0
        warnings.append("This model exceeds the conservative local memory budget for this device.")
    if not minimum_tier_satisfied(str(profile.get("hardware_tier") or "unknown"), str(candidate.get("minimum_chat_tier") or "unknown")):
        warnings.append("This device tier is below the model's approved chat recommendation floor.")
    if int(profile.get("disk_free_bytes") or 0) and int(profile.get("disk_free_bytes") or 0) < total_weight_bytes:
        feasible = False
        fit_type = "cannot_run"
        warnings.append("Free disk space is below the model download size.")
    return {
        "fit_type": fit_type,
        "feasible": feasible,
        "required_bytes": required_bytes,
        "offload_ratio": offload_ratio,
        "warnings": warnings,
        "required_gib": round(required_bytes / 1024**3, 2),
        "context_length": context_length,
    }
