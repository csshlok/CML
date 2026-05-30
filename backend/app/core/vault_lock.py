import json
import os
import subprocess
import sys
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now


class VaultLockError(RuntimeError):
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
        if owner_pid and owner_pid != current_pid and _is_live_vault_backend(owner_pid):
            raise VaultLockError(
                "Vault is already open in another backend process. Close the current Vault instance before reopening it."
            )

    _write_lock(lock_path, current_pid)
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


def _parse_pid(value: object) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _is_live_vault_backend(pid: int) -> bool:
    command_line = _process_command_line(pid)
    if not command_line:
        return False
    normalized = command_line.lower()
    return "backend.app.main" in normalized or ("uvicorn" in normalized and "cml" in normalized)


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
