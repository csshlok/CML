import json
import os
import subprocess
import sys
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path
from uuid import uuid4

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now


class VaultLockError(RuntimeError):
    pass


class VaultLockUnverifiedError(VaultLockError):
    pass


_LOCK_PATH: Path | None = None


def acquire_vault_lock() -> None:
    global _LOCK_PATH
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = settings.data_dir / ".vault.lock"
    current_pid = os.getpid()

    existing = _read_lock(lock_path)
    if existing:
        owner_pid = _parse_pid(existing.get("pid"))
        if owner_pid and owner_pid != current_pid:
            owner_state = _classify_lock_owner(owner_pid)
            if _lock_override_enabled():
                _write_override_audit_sequence(lock_path=lock_path, owner_pid=owner_pid, owner_state=owner_state)
            elif owner_state == "vault_backend":
                _write_audit("conflict_live_owner", lock_path=lock_path, owner_pid=owner_pid)
                raise VaultLockError(
                    "Vault is already open in another backend process. Close the current Vault instance before reopening it."
                )
            elif owner_state == "unverified":
                _write_audit("conflict_unverified_owner", lock_path=lock_path, owner_pid=owner_pid)
                raise VaultLockUnverifiedError(
                    "Vault lock owner is still running, but Vault could not verify the process identity. "
                    "Opening this vault anyway can permanently corrupt the database if another Vault process is writing."
                )
            else:
                _write_audit(f"reclaimed_{owner_state}", lock_path=lock_path, owner_pid=owner_pid)

    _write_lock(lock_path, current_pid)
    _write_audit("acquired", lock_path=lock_path, owner_pid=owner_pid if existing else None)
    _LOCK_PATH = lock_path


def release_vault_lock() -> None:
    global _LOCK_PATH
    lock_path = _LOCK_PATH
    if lock_path is None:
        return
    lock = _read_lock(lock_path)
    if _parse_pid(lock.get("pid") if lock else None) == os.getpid():
        try:
            lock_path.unlink()
            _write_audit("released", lock_path=lock_path)
        except FileNotFoundError:
            pass
    _LOCK_PATH = None


def _read_lock(lock_path: Path) -> dict | None:
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _write_lock(lock_path: Path, pid: int) -> None:
    lock_path.write_text(
        json.dumps(
            {
                "pid": pid,
                "created_at": utc_now(),
                "command_line": _current_command_line(),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _write_audit(
    event_type: str,
    *,
    lock_path: Path,
    owner_pid: int | None = None,
    detail: str = "",
    user_choice: str = "",
) -> None:
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vault_lock_audit (
                    id, event_type, pid, owner_pid, lock_path, detail, user_choice, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"lock-audit-{uuid4()}",
                    event_type,
                    os.getpid(),
                    owner_pid,
                    str(lock_path),
                    detail,
                    user_choice,
                    utc_now(),
                ),
            )
    except Exception:
        # Lock auditing must never prevent startup/shutdown.
        return


def _write_override_audit_sequence(*, lock_path: Path, owner_pid: int, owner_state: str) -> None:
    _write_audit(
        "lock_override_detection",
        lock_path=lock_path,
        owner_pid=owner_pid,
        detail=f"Detected {owner_state} lock owner.",
    )
    _write_audit(
        "dialog_shown",
        lock_path=lock_path,
        owner_pid=owner_pid,
        detail="Override warning was shown before opening.",
    )
    _write_audit(
        "user_choice",
        lock_path=lock_path,
        owner_pid=owner_pid,
        detail="User explicitly chose to open once despite the lock.",
        user_choice="open_anyway",
    )
    _write_audit(
        "startup_result",
        lock_path=lock_path,
        owner_pid=owner_pid,
        detail="Startup continued after one-time lock override.",
        user_choice="open_anyway",
    )


def _parse_pid(value: object) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _lock_override_enabled() -> bool:
    return os.getenv("CML_VAULT_LOCK_OVERRIDE", "").strip().lower() in {"1", "true", "yes", "open_anyway"}


def _classify_lock_owner(pid: int) -> str:
    command_line = _process_command_line(pid)
    if not command_line:
        if not _is_process_alive(pid):
            return "dead"
        if _is_local_backend_listener(pid):
            return "vault_backend"
        if _process_image_name(pid):
            return "other_process"
        return "unverified"
    normalized = command_line.lower()
    if (
        "backend.app.main:app" in normalized
        or " -m backend.app.main" in normalized
        or "\\backend.app.main" in normalized
        or ("uvicorn" in normalized and "backend.app.main" in normalized)
    ):
        return "vault_backend"
    return "other_process" if _is_process_alive(pid) else "dead"


def _current_command_line() -> str:
    return _process_command_line(os.getpid()) or " ".join([os.path.basename(sys.executable), *sys.argv])


def _process_command_line(pid: int) -> str:
    if os.name == "nt":
        return _windows_process_command_line(pid)
    return _posix_process_command_line(pid)


def _windows_process_command_line(pid: int) -> str:
    command = (
        "$p = Get-CimInstance Win32_Process -Filter \"ProcessId = "
        f"{pid}"
        "\"; if ($p) { $p.CommandLine }"
    )
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return output.strip()


def _process_image_name(pid: int) -> str:
    if os.name == "nt":
        command = f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p) {{ $p.ProcessName }}"
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", command],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return output.strip()
    proc_path = Path("/proc") / str(pid) / "comm"
    try:
        return proc_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _is_process_alive(pid: int) -> bool:
    if os.name == "nt":
        command = f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p) {{ 'alive' }}"
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", command],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return output.strip() == "alive"
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_local_backend_listener(pid: int) -> bool:
    for candidate_pid in _candidate_backend_probe_pids(pid):
        for port in _listening_ports_for_process(candidate_pid):
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (OSError, TimeoutError, URLError, ValueError, json.JSONDecodeError):
                continue
            if response.status == 200 and payload.get("service") == "cml-backend":
                return True
    return False


def _candidate_backend_probe_pids(pid: int) -> list[int]:
    candidates = [pid]
    if os.name == "nt":
        for child_pid in _windows_descendant_pids(pid):
            if child_pid not in candidates:
                candidates.append(child_pid)
    return candidates


def _listening_ports_for_process(pid: int) -> list[int]:
    if os.name == "nt":
        try:
            output = subprocess.check_output(
                ["cmd", "/c", "netstat -ano -p tcp"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return _parse_windows_netstat_ports(output.splitlines(), pid)
    proc_net_tcp = Path("/proc") / str(pid) / "net" / "tcp"
    proc_net_tcp6 = Path("/proc") / str(pid) / "net" / "tcp6"
    ports: list[int] = []
    for candidate in (proc_net_tcp, proc_net_tcp6):
        try:
            lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 4 or parts[3] != "0A":
                continue
            local_address = parts[1]
            try:
                port = int(local_address.split(":")[1], 16)
            except (IndexError, ValueError):
                continue
            ports.append(port)
    return sorted(set(ports))


def _parse_ports(lines: list[str]) -> list[int]:
    ports: list[int] = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        try:
            ports.append(int(value))
        except ValueError:
            continue
    return sorted(set(ports))


def _parse_windows_netstat_ports(lines: list[str], pid: int) -> list[int]:
    ports: list[int] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        protocol, local_address, _foreign_address, state, owning_pid = parts[:5]
        if protocol.upper() != "TCP" or state.upper() != "LISTENING":
            continue
        try:
            owning_pid_int = int(owning_pid)
        except ValueError:
            continue
        if owning_pid_int != pid:
            continue
        host, _, port_text = local_address.rpartition(":")
        if not host:
            continue
        try:
            ports.append(int(port_text))
        except ValueError:
            continue
    return sorted(set(ports))


def _windows_descendant_pids(pid: int) -> list[int]:
    child_map = _windows_process_child_map()
    discovered: list[int] = []
    queue = [pid]
    seen = {pid}
    while queue:
        current = queue.pop(0)
        for child_pid in child_map.get(current, ()):
            if child_pid in seen:
                continue
            seen.add(child_pid)
            discovered.append(child_pid)
            queue.append(child_pid)
    return discovered


def _windows_process_child_map() -> dict[int, list[int]]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return {}
    child_map: dict[int, list[int]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return {}
        while True:
            parent_pid = int(entry.th32ParentProcessID)
            process_pid = int(entry.th32ProcessID)
            child_map.setdefault(parent_pid, []).append(process_pid)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return child_map


def _posix_process_command_line(pid: int) -> str:
    try:
        os.kill(pid, 0)
    except OSError:
        return ""
    proc_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = proc_path.read_bytes()
    except OSError:
        return "live-process"
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
