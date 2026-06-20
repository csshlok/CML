import ctypes
import os
import platform


def hardware_status() -> dict:
    avx2, avx2_detection_method = _detect_avx2()
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
        "avx2_detection_method": avx2_detection_method,
        "hardware_tier": tier,
        "training_supported": supported,
        "detail": detail,
    }


def _detect_avx2() -> tuple[bool | None, str]:
    try:
        import cpuinfo

        flags = cpuinfo.get_cpu_info().get("flags") or []
        normalized_flags = {str(flag).lower() for flag in flags}
        if normalized_flags:
            return "avx2" in normalized_flags, "py-cpuinfo"
    except Exception:
        pass
    windows_result = _detect_windows_avx2()
    if windows_result is not None:
        return windows_result, "windows-kernel32"
    return None, "unavailable"


def _detect_windows_avx2() -> bool | None:
    if platform.system().lower() != "windows":
        return None
    try:
        # PF_AVX2_INSTRUCTIONS_AVAILABLE is exposed by IsProcessorFeaturePresent.
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))
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
