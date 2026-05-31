import os
import platform


def hardware_status() -> dict:
    avx2 = _detect_avx2()
    total_memory = _total_memory_bytes()
    cpu_count = os.cpu_count() or 1
    tier = _hardware_tier(cpu_count, total_memory, avx2)
    supported = avx2 is True and tier != "unsupported"
    detail = _hardware_detail(avx2, tier)
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": cpu_count,
        "total_memory_bytes": total_memory,
        "avx2": avx2,
        "hardware_tier": tier,
        "training_supported": supported,
        "detail": detail,
    }


def _detect_avx2() -> bool | None:
    try:
        import cpuinfo

        flags = cpuinfo.get_cpu_info().get("flags") or []
        return "avx2" in {str(flag).lower() for flag in flags}
    except Exception:
        return None


def _total_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        return None


def _hardware_tier(cpu_count: int, total_memory: int | None, avx2: bool | None) -> str:
    if avx2 is False:
        return "unsupported"
    gib = (total_memory or 0) / (1024**3)
    if gib >= 24 and cpu_count >= 12:
        return "gpu_or_high_spec_candidate"
    if gib >= 16 and cpu_count >= 8:
        return "cpu_high_spec"
    if gib >= 8 and cpu_count >= 4:
        return "cpu_minimum_spec"
    if total_memory is None or avx2 is None:
        return "unknown"
    return "unsupported"


def _hardware_detail(avx2: bool | None, tier: str) -> str:
    if avx2 is False:
        return "AVX2 is not available. Local adapter training should remain disabled on this device."
    if avx2 is None:
        return "Vault could not verify CPU capabilities. One guarded training attempt may be allowed with a warning."
    if tier == "unsupported":
        return "This device is below the current local adapter training target."
    return "Hardware passes the first local adapter training gate. Runtime and memory tests are still required."
