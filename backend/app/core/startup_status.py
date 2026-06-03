import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.core.database import utc_now

FALLBACK_PHASES = {
    "starting",
    "pre_vault_mode",
    "vault_lock_acquiring",
    "vault_lock_acquired",
    "database_initializing",
    "integrity_check_running",
    "integrity_check_failed",
    "schema_check_running",
    "schema_check_failed",
    "job_recovery_running",
    "reconciliation_queued",
    "runtime_detection_running",
    "vault_lock_failed",
    "startup_failed",
    "ready",
}

TERMINAL_STATUSES = {"ready", "failed"}


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


def read_startup_status() -> dict | None:
    settings = get_settings()
    status_path = settings.startup_status_path
    if status_path is None:
        return None
    try:
        raw = Path(status_path).read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_startup_phase_registry() -> dict:
    phases = known_startup_phases()
    required = {
        "starting",
        "pre_vault_mode",
        "vault_lock_acquiring",
        "database_initializing",
        "integrity_check_running",
        "schema_check_running",
        "job_recovery_running",
        "reconciliation_queued",
        "runtime_detection_running",
        "ready",
        "startup_failed",
    }
    missing = sorted(required - phases)
    unknown_fallbacks = sorted(FALLBACK_PHASES - phases)
    return {
        "ok": not missing,
        "phase_count": len(phases),
        "missing_required_phases": missing,
        "fallbacks_not_in_registry": unknown_fallbacks,
        "source": str(ROOT_DIR / "shared" / "startup-phases.json"),
    }


def startup_status_staleness(timeout_seconds: int = 30) -> dict:
    status = read_startup_status()
    if status is None:
        return {"stale": False, "reason": "missing_status", "age_seconds": None, "phase": None}
    phase = str(status.get("phase") or "")
    state = str(status.get("status") or "")
    updated_at = str(status.get("updated_at") or "")
    if state in TERMINAL_STATUSES:
        return {"stale": False, "reason": "terminal_status", "age_seconds": 0, "phase": phase}
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return {"stale": True, "reason": "invalid_updated_at", "age_seconds": None, "phase": phase}
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    age = datetime.now(UTC) - updated.astimezone(UTC)
    stale = age > timedelta(seconds=max(1, timeout_seconds))
    return {
        "stale": stale,
        "reason": "timeout" if stale else "fresh",
        "age_seconds": int(age.total_seconds()),
        "phase": phase,
        "timeout_seconds": max(1, timeout_seconds),
    }
