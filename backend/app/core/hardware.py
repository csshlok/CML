import ctypes
import os
import platform
import shutil
import subprocess
from pathlib import Path

_GIB = 1024**3


def hardware_status() -> dict:
    avx2, avx2_detection_method = _detect_avx2()
    avx512 = _detect_avx512()
    total_memory = _total_memory_bytes()
    available_memory = _available_memory_bytes()
    usable_memory = _usable_memory_bytes(total_memory)
    cpu_count = os.cpu_count() or 1
    tier = _hardware_tier(cpu_count, total_memory, avx2)
    supported = avx2 is True and tier != "unsupported"
    detail = _hardware_detail(avx2, tier)
    disk_free = _disk_free_bytes()
    gpus = _detect_gpus()
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": cpu_count,
        "total_memory_bytes": total_memory,
        "available_memory_bytes": available_memory,
        "usable_memory_bytes": usable_memory,
        "disk_free_bytes": disk_free,
        "avx2": avx2,
        "avx2_detection_method": avx2_detection_method,
        "avx512": avx512,
        "hardware_tier": tier,
        "training_supported": supported,
        "detail": detail,
        "gpus": gpus,
        "warnings": [],
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


def _detect_avx512() -> bool | None:
    try:
        import cpuinfo

        flags = cpuinfo.get_cpu_info().get("flags") or []
        return "avx512f" in {str(flag).lower() for flag in flags}
    except Exception:
        return None


def _total_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        return None


def _available_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        return None


def _usable_memory_bytes(total_memory: int | None) -> int | None:
    if total_memory is None:
        return None
    reserve = int(total_memory * 0.15)
    reserve = max(4 * _GIB, min(reserve, 32 * _GIB))
    return max(0, int(total_memory) - reserve)


def _disk_free_bytes() -> int:
    try:
        return int(shutil.disk_usage(Path.home()).free)
    except Exception:
        return 0


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


def _detect_gpus() -> list[dict]:
    os_name = platform.system().lower()
    if os_name != "windows":
        return []
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$controllers = Get-CimInstance Win32_VideoController; "
            "$controllers | ForEach-Object { "
            "[PSCustomObject]@{"
            "Name=$_.Name; "
            "AdapterRAM=$_.AdapterRAM"
            "} "
            "} | ConvertTo-Json -Depth 3"
        ),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        import json

        payload = json.loads(result.stdout)
    except Exception:
        return []
    entries = payload if isinstance(payload, list) else [payload]
    gpus = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or "").strip()
        if not name:
            continue
        vendor = _gpu_vendor(name)
        raw_vram = _gpu_vram(name, entry.get("AdapterRAM"))
        key = f"{vendor}:{name}:{raw_vram}"
        if key in seen:
            continue
        seen.add(key)
        gpus.append(
            {
                "vendor": vendor,
                "name": name,
                "vram_bytes": raw_vram,
                "usable_vram_bytes": raw_vram,
                "shared_memory": vendor == "intel" and raw_vram < 2 * _GIB,
                "memory_bandwidth_gbps": _gpu_bandwidth_guess(name, raw_vram),
                "compute_capability": None,
                "driver_confidence": "medium",
            }
        )
    return gpus


def _gpu_vendor(name: str) -> str:
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "rtx" in lowered or "gtx" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "intel" in lowered or "arc" in lowered:
        return "intel"
    return "unknown"


def _gpu_vram(name: str, value: object) -> int:
    try:
        vram = max(0, int(value or 0))
    except Exception:
        vram = 0
    upper = name.upper()
    if "RX 9060 XT" in upper and vram < 8 * _GIB:
        return 8 * _GIB
    return vram


def _gpu_bandwidth_guess(name: str, vram_bytes: int) -> float:
    upper = name.upper()
    if any(marker in upper for marker in ("4090", "4080", "4070 TI", "3090", "3080")):
        return 700.0
    if any(marker in upper for marker in ("4070", "3070", "4060 TI", "7900", "7800")):
        return 420.0
    if any(marker in upper for marker in ("3060", "3050", "7600", "ARC A770", "ARC B580")):
        return 280.0
    gib = vram_bytes / float(_GIB) if vram_bytes else 0.0
    if gib >= 20:
        return 700.0
    if gib >= 12:
        return 420.0
    if gib >= 8:
        return 280.0
    if gib >= 4:
        return 160.0
    return 0.0
