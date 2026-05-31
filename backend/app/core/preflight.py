import shutil
from pathlib import Path


DEFAULT_REQUIRED_BYTES = 5 * 1024 * 1024 * 1024


def disk_preflight(path: str, required_bytes: int | None = None) -> dict:
    target = Path(path).expanduser()
    required = int(required_bytes or DEFAULT_REQUIRED_BYTES)
    probe = target if target.exists() else _nearest_existing_parent(target)
    usage = shutil.disk_usage(probe)
    available = int(usage.free)
    return {
        "path": str(target),
        "probe_path": str(probe),
        "required_bytes": required,
        "available_bytes": available,
        "ok": available >= required,
        "message": (
            "Enough disk space is available."
            if available >= required
            else "Not enough disk space is available for this action."
        ),
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return Path.cwd()
        current = parent
    return current
