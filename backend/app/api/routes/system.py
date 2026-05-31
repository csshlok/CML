from fastapi import APIRouter, HTTPException

from backend.app.core.hardware import hardware_status
from backend.app.core.preflight import disk_preflight
from backend.app.core.startup_status import read_startup_status
from backend.app.core.database import connect, dict_from_row
from backend.app.schemas import DiskPreflightRequest, DiskPreflightResponse, HardwareStatusRead, StartupStatusRead, VaultLockAuditRead

router = APIRouter(prefix="/system", tags=["system"])


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


@router.post("/preflight/disk", response_model=DiskPreflightResponse)
def check_disk_preflight(payload: DiskPreflightRequest) -> dict:
    try:
        return disk_preflight(payload.path, payload.required_bytes)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hardware", response_model=HardwareStatusRead)
def get_hardware_status() -> dict:
    return hardware_status()


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
