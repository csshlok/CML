from __future__ import annotations

import math
from typing import Any

from backend.app.core.hardware import hardware_status
from backend.app.core.llm_runtime import runtime_status


def build_hardware_profile() -> dict[str, Any]:
    hardware = hardware_status()
    runtime = runtime_status()
    total_ram = int(hardware.get("total_memory_bytes") or 0)
    available_ram = int(hardware.get("available_memory_bytes") or 0)
    usable_ram = int(hardware.get("usable_memory_bytes") or 0)
    disk_free = int(hardware.get("disk_free_bytes") or 0)
    gpus = []
    for gpu in hardware.get("gpus") or []:
        if not isinstance(gpu, dict):
            continue
        gpus.append(
            {
                "vendor": str(gpu.get("vendor") or "unknown"),
                "name": str(gpu.get("name") or "Unknown GPU"),
                "vram_bytes": int(gpu.get("vram_bytes") or 0),
                "usable_vram_bytes": int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0),
                "shared_memory": bool(gpu.get("shared_memory")),
                "memory_bandwidth_gbps": float(gpu.get("memory_bandwidth_gbps") or 0.0),
                "compute_capability": gpu.get("compute_capability"),
                "driver_confidence": str(gpu.get("driver_confidence") or "medium"),
            }
        )
    detection_confidence = "high"
    if not hardware.get("avx2") or not total_ram:
        detection_confidence = "medium"
    if not gpus:
        detection_confidence = "medium"
    return {
        "os": str(hardware.get("os") or ""),
        "architecture": str(hardware.get("machine") or ""),
        "cpu_name": str(hardware.get("processor") or ""),
        "cpu_threads": int(hardware.get("cpu_count") or 1),
        "ram_total_bytes": total_ram,
        "ram_available_bytes": available_ram,
        "ram_usable_bytes": usable_ram,
        "disk_free_bytes": disk_free,
        "has_avx2": hardware.get("avx2"),
        "has_avx512": hardware.get("avx512"),
        "hardware_tier": str(hardware.get("hardware_tier") or "unknown"),
        "training_supported": bool(hardware.get("training_supported")),
        "runtime_provider": str(runtime.get("provider") or "none"),
        "runtime_backend": _runtime_backend_label(str(runtime.get("base_url") or ""), str(runtime.get("provider") or "")),
        "runtime_base_url": str(runtime.get("base_url") or ""),
        "runtime_detected": bool(runtime.get("available")),
        "runtime_detail": str(runtime.get("detail") or ""),
        "detection_confidence": detection_confidence,
        "warnings": list(hardware.get("warnings") or []),
        "gpus": gpus,
    }


def best_gpu(profile: dict[str, Any]) -> dict[str, Any] | None:
    gpus = [gpu for gpu in profile.get("gpus") or [] if isinstance(gpu, dict)]
    if not gpus:
        return None
    return max(gpus, key=lambda gpu: int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0))


def approximate_cpu_bandwidth_gbps(profile: dict[str, Any]) -> float:
    ram_total = float(profile.get("ram_total_bytes") or 0)
    threads = max(1, int(profile.get("cpu_threads") or 1))
    if ram_total <= 0:
        return max(12.0, min(48.0, threads * 2.0))
    gib = ram_total / float(1024**3)
    return max(12.0, min(64.0, 12.0 + gib * 0.8 + threads * 1.5))


def _runtime_backend_label(base_url: str, provider: str) -> str:
    lowered = base_url.lower()
    if provider == "none":
        return "none"
    if "11434" in lowered or "ollama" in lowered:
        return "ollama_compatible"
    if "8080" in lowered or "llama" in lowered:
        return "llama_cpp_compatible"
    return "openai_compatible"


def bytes_to_gib(value: int | float) -> float:
    if not value:
        return 0.0
    return float(value) / float(1024**3)


def gib_to_bytes(value: float) -> int:
    return int(math.ceil(value * float(1024**3)))
