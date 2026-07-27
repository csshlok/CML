import ctypes
import json
import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_GIB = 1024**3


def hardware_status() -> dict:
    avx2, avx2_detection_method = _detect_avx2()
    avx512 = _detect_avx512()
    total_memory = _total_memory_bytes()
    available_memory = _available_memory_bytes()
    usable_memory = _usable_memory_bytes(total_memory)
    cpu_count = os.cpu_count() or 1
    gpus = _detect_gpus()
    tier = _hardware_tier(cpu_count, total_memory, avx2, gpus)
    detection_failures = []
    if total_memory is None:
        detection_failures.append("system_memory")
    if avx2 is None:
        detection_failures.append("avx2")
    supported = avx2 is True and tier != "unsupported"
    detail = _hardware_detail(avx2, tier, detection_failures)
    disk_free = _disk_free_bytes()
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
        "compatibility_detection": "failed" if detection_failures else "complete",
        "detection_failures": detection_failures,
        "training_supported": supported,
        "detail": detail,
        "gpus": gpus,
        "warnings": (
            ["Vault could not fully detect this device. Retry the hardware check before choosing a model."]
            if detection_failures
            else []
        ),
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
        return _native_memory_status()[0]


def _available_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        return _native_memory_status()[1]


def _native_memory_status() -> tuple[int | None, int | None]:
    if platform.system().lower() == "windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        try:
            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical), int(status.available_physical)
        except Exception:
            return None, None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        return page_size * total_pages, page_size * available_pages
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None


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


def _hardware_tier(
    cpu_count: int,
    total_memory: int | None,
    avx2: bool | None,
    gpus: list[dict] | None = None,
) -> str:
    if avx2 is False:
        return "unsupported"
    if total_memory is None or avx2 is None:
        return "unknown"
    gib = (total_memory or 0) / (1024**3)
    dedicated_gpu_bytes = max(
        (
            int(gpu.get("usable_vram_bytes") or 0)
            for gpu in (gpus or [])
            if not bool(gpu.get("shared_memory"))
        ),
        default=0,
    )
    if (gib >= 22.5 and cpu_count >= 12) or dedicated_gpu_bytes >= 4 * _GIB:
        return "gpu_or_high_spec_candidate"
    if gib >= 15 and cpu_count >= 8:
        return "cpu_high_spec"
    if gib >= 7.5 and cpu_count >= 4:
        return "cpu_minimum_spec"
    return "unsupported"


def _hardware_detail(avx2: bool | None, tier: str, detection_failures: list[str] | None = None) -> str:
    if detection_failures:
        missing = ", ".join(detection_failures)
        return f"Vault could not detect required hardware values: {missing}."
    if avx2 is False:
        return "AVX2 is not available. Local adapter training should remain disabled on this device."
    if avx2 is None:
        return "Vault could not verify CPU capabilities. One guarded training attempt may be allowed with a warning."
    if tier == "unsupported":
        return "This device is below the current local adapter training target."
    return "Hardware passes the first local adapter training gate. Runtime and memory tests are still required."


def _detect_gpus() -> list[dict]:
    return [dict(item) for item in _detect_gpus_cached()]


@lru_cache(maxsize=1)
def _detect_gpus_cached() -> tuple[tuple[tuple[str, object], ...], ...]:
    """Cache static GPU inventory and avoid repeating slow Windows device probes."""

    os_name = platform.system().lower()
    if os_name != "windows":
        return ()
    nvidia_gpus = _detect_nvidia_gpus()
    if nvidia_gpus:
        return tuple(tuple(item.items()) for item in nvidia_gpus)
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
    result = _run_probe(command, timeout=10)
    if result is None:
        return ()
    if result.returncode != 0 or not result.stdout.strip():
        return ()
    try:
        payload = json.loads(result.stdout)
    except Exception:
        return ()
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
    return tuple(tuple(item.items()) for item in gpus)


def _detect_nvidia_gpus() -> list[dict]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    result = _run_probe(
        [
            executable,
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )
    if result is None or result.returncode != 0:
        return []
    gpus = []
    for line in result.stdout.splitlines():
        name, separator, memory_mib = line.rpartition(",")
        if not separator or not name.strip():
            continue
        try:
            vram = max(0, int(float(memory_mib.strip())) * 1024**2)
        except ValueError:
            continue
        normalized_name = name.strip()
        gpus.append(
            {
                "vendor": "nvidia",
                "name": normalized_name,
                "vram_bytes": vram,
                "usable_vram_bytes": vram,
                "shared_memory": False,
                "memory_bandwidth_gbps": _gpu_bandwidth_guess(normalized_name, vram),
                "compute_capability": None,
                "driver_confidence": "high",
            }
        )
    return gpus


def _run_probe(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str] | None:
    """Run a hardware probe without allowing a descendant to hold capture pipes open forever."""

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if process is not None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                    creationflags=creationflags,
                )
            else:
                process.kill()
            try:
                process.communicate(timeout=2)
            except (subprocess.SubprocessError, OSError):
                pass
        return None
    except (OSError, subprocess.SubprocessError):
        return None


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
