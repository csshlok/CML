import json
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.core.database import utc_now

FALLBACK_PHASES = {
    "starting",
    "startup_failed",
    "ready",
    "integrity_check_failed",
    "vault_lock_failed",
}


def known_startup_phases() -> set[str]:
    phase_path = ROOT_DIR / "shared" / "startup-phases.json"
    try:
        phases = json.loads(phase_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(FALLBACK_PHASES)
    if not isinstance(phases, list):
        return set(FALLBACK_PHASES)
    values = {phase for phase in phases if isinstance(phase, str) and phase}
    return values or set(FALLBACK_PHASES)


def write_startup_status(phase: str, *, status: str = "running", message: str = "", error_code: str = "") -> None:
    settings = get_settings()
    status_path = settings.startup_status_path
    if status_path is None:
        return
    phases = known_startup_phases()
    normalized_phase = phase if phase in phases else "startup_failed"
    payload = {
        "phase": normalized_phase,
        "raw_phase": phase,
        "status": status,
        "message": message,
        "error_code": error_code,
        "backend_mode": settings.backend_mode,
        "data_dir": str(settings.data_dir),
        "database_path": str(settings.database_path),
        "updated_at": utc_now(),
    }
    try:
        Path(status_path).parent.mkdir(parents=True, exist_ok=True)
        Path(status_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        # Startup status must never be the reason the backend cannot start.
        return
