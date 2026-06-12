from fastapi import APIRouter, HTTPException

from backend.app.core.hardware import hardware_status
from backend.app.core.lora_training import trainer_dependency_status
from backend.app.core.migration_planner import (
    MigrationPreflightError,
    begin_planned_migration,
    collect_staged_garbage,
    plan_derived_state_migration,
    staging_summary,
)
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.preflight import disk_preflight
from backend.app.core.recovery_drills import startup_recovery_drills
from backend.app.core.setup_readiness import first_run_readiness
from backend.app.core.startup_repair import startup_repair_summary
from backend.app.core.startup_status import read_startup_status, startup_status_staleness, validate_startup_phase_registry
from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row
from backend.app.core.storage_accounting import storage_accounting
from backend.app.core.unlock_state import (
    RepairRequiredError,
    current_unlock_state,
    initialize_security_and_unlock,
    lock,
    reset_passphrase,
    unlock_with_passphrase,
    unlock_with_recovery,
    update_unlock_settings,
    verify_sensitive_action,
)
from backend.app.core.vault_safety import vault_safety_status
from backend.app.schemas import (
    DiskPreflightRequest,
    DiskPreflightResponse,
    HardwareStatusRead,
    LoraTrainerStatusRead,
    OCRRuntimeStatusRead,
    SensitiveActionVerifyRead,
    SensitiveActionVerifyRequest,
    StartupStatusRead,
    UnlockInitializeRequest,
    UnlockInitializeResponse,
    UnlockPassphraseRequest,
    UnlockRecoveryRequest,
    UnlockRecoveryResetRequest,
    UnlockSettingsUpdate,
    UnlockStatusRead,
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


@router.get("/unlock/status", response_model=UnlockStatusRead)
def get_unlock_status() -> dict:
    return current_unlock_state()


@router.post("/unlock/initialize", response_model=UnlockInitializeResponse)
def initialize_unlock(payload: UnlockInitializeRequest) -> dict:
    try:
        return initialize_security_and_unlock(payload.vault_id, payload.passphrase, payload.unlock_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepairRequiredError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


@router.post("/unlock/passphrase", response_model=UnlockStatusRead)
def unlock_passphrase(payload: UnlockPassphraseRequest) -> dict:
    try:
        return unlock_with_passphrase(payload.vault_id, payload.passphrase)
    except RepairRequiredError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


@router.post("/unlock/recovery", response_model=UnlockStatusRead)
def unlock_recovery(payload: UnlockRecoveryRequest) -> dict:
    try:
        return unlock_with_recovery(payload.vault_id, payload.recovery_key)
    except RepairRequiredError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


@router.post("/unlock/recovery/reset", response_model=UnlockStatusRead)
def reset_unlock_passphrase(payload: UnlockRecoveryResetRequest) -> dict:
    try:
        return reset_passphrase(payload.vault_id, payload.recovery_key, payload.new_passphrase)
    except RepairRequiredError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


@router.post("/unlock/lock", response_model=UnlockStatusRead)
def lock_unlock(vault_id: str | None = None) -> dict:
    return lock(vault_id)


@router.patch("/unlock/settings")
def patch_unlock_settings(payload: UnlockSettingsUpdate) -> dict:
    try:
        return update_unlock_settings(
            payload.vault_id,
            unlock_mode=payload.unlock_mode,
            pin_enabled=payload.pin_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


@router.post("/unlock/sensitive-action", response_model=SensitiveActionVerifyRead)
def verify_unlock_sensitive_action(payload: SensitiveActionVerifyRequest) -> dict:
    try:
        return verify_sensitive_action(payload.vault_id, payload.passphrase)
    except Exception as exc:
        raise _unlock_http_exception(exc) from exc


def _unlock_http_exception(exc: Exception) -> HTTPException:
    detail = str(exc) or exc.__class__.__name__
    if detail == "invalid_vault_secret" or exc.__class__.__name__ == "InvalidVaultSecretError":
        return HTTPException(status_code=401, detail="invalid_vault_secret")
    if detail == "vault_security_already_initialized" or exc.__class__.__name__ == "VaultSecurityExistsError":
        return HTTPException(status_code=409, detail="vault_security_already_initialized")
    if detail == "vault_security_not_initialized" or exc.__class__.__name__ == "VaultSecurityNotInitializedError":
        return HTTPException(status_code=409, detail="vault_security_not_initialized")
    if detail == "vault_not_found":
        return HTTPException(status_code=404, detail="vault_not_found")
    return HTTPException(status_code=409, detail=detail)


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


@router.get("/security/migrations/plan")
def get_security_migration_plan(
    vault_id: str,
    normalization_version: str = "norm-v1",
    embedding_model_id: str = "hash-dev",
    index_version: str = "v1",
    extraction_version: str = "extract-v1",
    epoch: int = 1,
    safety_margin_bytes: int = 512 * 1024 * 1024,
) -> dict:
    return plan_derived_state_migration(
        vault_id,
        {
            "normalization_version": normalization_version,
            "embedding_model_id": embedding_model_id,
            "index_version": index_version,
            "extraction_version": extraction_version,
            "epoch": epoch,
        },
        safety_margin_bytes=safety_margin_bytes,
    )


@router.post("/security/migrations/begin")
def begin_security_migration(
    vault_id: str,
    normalization_version: str = "norm-v1",
    embedding_model_id: str = "hash-dev",
    index_version: str = "v1",
    extraction_version: str = "extract-v1",
    epoch: int = 1,
    safety_margin_bytes: int = 512 * 1024 * 1024,
) -> dict:
    try:
        return begin_planned_migration(
            vault_id,
            {
                "normalization_version": normalization_version,
                "embedding_model_id": embedding_model_id,
                "index_version": index_version,
                "extraction_version": extraction_version,
                "epoch": epoch,
            },
            safety_margin_bytes=safety_margin_bytes,
        )
    except MigrationPreflightError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/security/migrations/staging")
def get_security_migration_staging(vault_id: str | None = None) -> dict:
    return staging_summary(vault_id)


@router.post("/security/migrations/staging/gc")
def run_security_migration_staging_gc(
    vault_id: str | None = None,
    limit: int = 100,
    stale_after_seconds: int = 3600,
) -> dict:
    return collect_staged_garbage(vault_id, limit=limit, stale_after_seconds=stale_after_seconds)


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
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict_from_row(row) for row in rows]
