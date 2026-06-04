from fastapi import APIRouter, HTTPException

from backend.app.core.hardware import hardware_status
from backend.app.core.lora_training import trainer_dependency_status
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.preflight import disk_preflight
from backend.app.core.recovery_drills import startup_recovery_drills
from backend.app.core.setup_readiness import first_run_readiness
from backend.app.core.startup_repair import startup_repair_summary
from backend.app.core.startup_status import read_startup_status, startup_status_staleness, validate_startup_phase_registry
from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row
from backend.app.core.storage_accounting import storage_accounting
from backend.app.core.vault_safety import vault_safety_status
from backend.app.schemas import (
    DiskPreflightRequest,
    DiskPreflightResponse,
    HardwareStatusRead,
    LoraTrainerStatusRead,
    OCRRuntimeStatusRead,
    StartupStatusRead,
    VaultLockAuditRead,
    VaultSafetyRead,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/backend-identity")
def get_backend_identity() -> dict:
    settings = get_settings()
    return {
        "service": "cml-backend",
        "api_prefix": settings.api_prefix,
        "backend_mode": settings.backend_mode,
        "data_dir": str(settings.data_dir),
        "database_path": str(settings.database_path),
        "authenticated": bool(settings.api_token),
    }


@router.get("/startup-status", response_model=StartupStatusRead)
def get_startup_status() -> dict:
    status = read_startup_status()
    if status is None:
        return {
            "phase": "ready",
            "raw_phase": "ready",
            "status": "ready",
            "message": "Startup status file is not configured.",
            "error_code": "",
            "backend_mode": "",
            "data_dir": "",
            "database_path": "",
            "updated_at": "",
        }
    return status


@router.get("/startup-phases")
def get_startup_phase_registry(timeout_seconds: int = 30) -> dict:
    return {
        "registry": validate_startup_phase_registry(),
        "staleness": startup_status_staleness(timeout_seconds=timeout_seconds),
    }


@router.get("/startup-repair")
def get_startup_repair_summary(apply_recovery: bool = False) -> dict:
    return startup_repair_summary(apply_recovery=apply_recovery)


@router.get("/recovery-drills")
def get_startup_recovery_drills(apply_recovery: bool = False, stale_timeout_seconds: int = 30) -> dict:
    return startup_recovery_drills(
        apply_recovery=apply_recovery,
        stale_timeout_seconds=stale_timeout_seconds,
    )


@router.get("/first-run/readiness")
def get_first_run_readiness() -> dict:
    return first_run_readiness()


@router.get("/storage")
def get_storage_accounting(vault_id: str | None = None) -> dict:
    return storage_accounting(vault_id)


@router.post("/preflight/disk", response_model=DiskPreflightResponse)
def check_disk_preflight(payload: DiskPreflightRequest) -> dict:
    try:
        return disk_preflight(payload.path, payload.required_bytes)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hardware", response_model=HardwareStatusRead)
def get_hardware_status() -> dict:
    return hardware_status()


@router.get("/lora-trainer", response_model=LoraTrainerStatusRead)
def get_lora_trainer_status() -> dict:
    return trainer_dependency_status()


@router.get("/ocr", response_model=OCRRuntimeStatusRead)
def get_ocr_status() -> dict:
    return ocr_runtime_status()


@router.get("/vault-safety", response_model=VaultSafetyRead)
def get_vault_safety_status() -> dict:
    return vault_safety_status(create_backup=False)


@router.post("/vault-safety/backup", response_model=VaultSafetyRead)
def create_vault_backup() -> dict:
    try:
        return vault_safety_status(create_backup=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/vault-lock/audit", response_model=list[VaultLockAuditRead])
def list_vault_lock_audit(limit: int = 20) -> list[dict]:
    safe_limit = max(1, min(limit, 100))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM vault_lock_audit
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict_from_row(row) for row in rows]
