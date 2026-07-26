import json
import threading
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.core.encrypted_storage import migrate_existing_plaintext_content
from backend.app.core.vault_crypto import (
    InvalidVaultSecretError,
    VaultCryptoError,
    get_vault_security_metadata,
    initialize_vault_security,
    is_vault_unlocked,
    lock_all_vaults,
    lock_vault,
    no_vendor_recovery_available,
    reset_passphrase_with_recovery_key,
    unlock_vault_with_passphrase,
    unlock_vault_with_recovery_key,
    verify_sensitive_action as verify_vault_sensitive_action,
)

UnlockState = Literal["locked", "unlocking", "verifying", "repair_required", "ready"]

LOCKED_SAFE_PATHS = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

API_LOCKED_SAFE_SUFFIXES = (
    "/system/backend-identity",
    "/system/startup-status",
    "/system/startup-phases",
    "/system/startup-repair",
    "/system/first-run/readiness",
    "/system/preflight",
    "/system/hardware",
    "/system/ocr",
    "/system/unlock",
    "/models",
    "/jobs/status",
    "/extension/status",
)
VAULT_BOUND_JOB_SCOPES = {"vault", "source", "chat", "vector_index", "cluster"}


@dataclass
class UnlockStateSnapshot:
    state: UnlockState
    vault_id: str | None
    unlock_mode: str
    pin_enabled: bool
    message: str
    verification_error: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "vault_id": self.vault_id,
            "unlock_mode": self.unlock_mode,
            "pin_enabled": self.pin_enabled,
            "message": self.message,
            "verification_error": self.verification_error,
            "updated_at": self.updated_at,
            "ready": self.state == "ready",
            "has_vendor_recovery": False,
        }


class UnlockStateError(RuntimeError):
    pass


class UnlockRequiredError(UnlockStateError):
    pass


class RepairRequiredError(UnlockStateError):
    pass


_STATE_LOCK = threading.RLock()
_STATE = UnlockStateSnapshot(
    state="locked",
    vault_id=None,
    unlock_mode="strict",
    pin_enabled=False,
    message="Vault is locked.",
    verification_error="",
    updated_at=utc_now(),
)


def current_unlock_state() -> dict:
    with _STATE_LOCK:
        snapshot = _STATE
    secured = secured_vault_ids()
    result = snapshot.to_dict()
    if not secured:
        result.update(
            {
                "state": "ready",
                "vault_id": None,
                "unlock_mode": "strict",
                "pin_enabled": False,
                "message": "Vault is ready. Lock protection has not been enabled.",
                "verification_error": "",
                "ready": True,
            }
        )
    result["secured_vault_count"] = len(secured)
    result["secured_vault_ids"] = secured
    result["has_vendor_recovery"] = no_vendor_recovery_available() is False
    return result


def secured_vault_ids() -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT vault_id FROM vault_security_metadata ORDER BY vault_id").fetchall()
    return [str(row["vault_id"]) for row in rows]


def security_gate_active() -> bool:
    return bool(secured_vault_ids())


def _api_path(api_prefix: str, suffix: str) -> str:
    return f"{api_prefix.rstrip('/')}/{suffix.lstrip('/')}"


def locked_safe_prefixes(api_prefix: str) -> tuple[str, ...]:
    return (
        *LOCKED_SAFE_PATHS,
        *(_api_path(api_prefix, suffix) for suffix in API_LOCKED_SAFE_SUFFIXES),
    )


def is_locked_safe_path(path: str, method: str = "GET", api_prefix: str | None = None) -> bool:
    normalized_method = method.upper()
    resolved_api_prefix = api_prefix or get_settings().api_prefix
    unlock_endpoint_prefix = _api_path(resolved_api_prefix, "/system/unlock")
    if path == unlock_endpoint_prefix or path.startswith(f"{unlock_endpoint_prefix}/"):
        return True
    if path == _api_path(resolved_api_prefix, "/vaults") and normalized_method == "GET":
        return True
    for allowed in locked_safe_prefixes(resolved_api_prefix):
        if path == allowed or path.startswith(f"{allowed}/"):
            return True
    return False


def require_ready_for_request(path: str, method: str = "GET") -> None:
    if not security_gate_active() or is_locked_safe_path(path, method):
        return
    state = current_unlock_state()["state"]
    if state == "ready":
        return
    if state == "repair_required":
        raise RepairRequiredError("vault_repair_required")
    raise UnlockRequiredError("vault_unlock_required")


def unlock_with_passphrase(vault_id: str, passphrase: str) -> dict:
    _set_state("unlocking", vault_id=vault_id, message="Unlocking vault.")
    try:
        unlock_vault_with_passphrase(vault_id, passphrase)
    except InvalidVaultSecretError:
        _set_state("locked", vault_id=vault_id, message="Wrong passphrase.")
        _audit("unlock_failed_bad_passphrase", vault_id)
        raise
    except Exception:
        _set_state("locked", vault_id=vault_id, message="Unlock failed.")
        _audit("unlock_failed_internal", vault_id)
        raise
    _set_state("verifying", vault_id=vault_id, message="Verifying vault state.")
    _audit("unlock_verification_started", vault_id)
    return _verify_after_unlock(vault_id)


def unlock_with_recovery(vault_id: str, recovery_key: str) -> dict:
    _set_state("unlocking", vault_id=vault_id, message="Unlocking vault with recovery key.")
    try:
        unlock_vault_with_recovery_key(vault_id, recovery_key)
    except InvalidVaultSecretError:
        _set_state("locked", vault_id=vault_id, message="Invalid recovery key.")
        _audit("unlock_failed_bad_recovery_key", vault_id)
        raise
    _set_state("verifying", vault_id=vault_id, message="Verifying vault state.")
    _audit("unlock_verification_started", vault_id)
    return _verify_after_unlock(vault_id)


def initialize_security_and_unlock(vault_id: str, passphrase: str, unlock_mode: str = "strict") -> dict:
    if unlock_mode != "strict":
        raise ValueError("Only full-passphrase protection is currently available.")
    result = initialize_vault_security(vault_id, passphrase, unlock_mode="strict")
    try:
        with connect() as conn:
            migration = migrate_existing_plaintext_content(conn, vault_id)
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                """
                UPDATE vault_security_metadata
                SET content_migration_status = 'pending',
                    content_migration_updated_at = ?,
                    content_migration_error = ?
                WHERE vault_id = ?
                """,
                (utc_now(), str(exc)[:300], vault_id),
            )
        _set_state(
            "repair_required",
            vault_id=vault_id,
            message="Security setup was interrupted. Unlock again to resume it.",
            verification_error=str(exc)[:300],
        )
        raise
    state = _verify_after_unlock(vault_id)
    state["migrated_content"] = migration
    state["recovery_key"] = result.recovery_key
    return state


def reset_passphrase(vault_id: str, recovery_key: str, new_passphrase: str) -> dict:
    reset_passphrase_with_recovery_key(vault_id, recovery_key, new_passphrase)
    _audit("passphrase_reset_with_recovery", vault_id)
    return _verify_after_unlock(vault_id)


def lock(vault_id: str | None = None) -> dict:
    if vault_id:
        lock_vault(vault_id)
    else:
        lock_all_vaults()
    _set_state("locked", vault_id=vault_id, message="Vault is locked.")
    _audit("vault_locked", vault_id)
    return current_unlock_state()


def verify_sensitive_action(vault_id: str, passphrase: str) -> dict:
    verify_vault_sensitive_action(vault_id, passphrase)
    _audit("sensitive_action_verified", vault_id)
    return {"ok": True, "vault_id": vault_id, "verified_at": utc_now()}


def update_unlock_settings(vault_id: str, *, unlock_mode: str | None = None, pin_enabled: bool | None = None) -> dict:
    updates: dict[str, object] = {"updated_at": utc_now()}
    if unlock_mode is not None:
        if unlock_mode != "strict":
            raise ValueError("Convenience unlock is not available without OS-protected secret storage.")
        updates["unlock_mode"] = "strict"
    if pin_enabled is not None:
        if pin_enabled:
            raise ValueError("PIN unlock is not available.")
        updates["pin_enabled"] = 0
    if len(updates) == 1:
        return get_vault_security_metadata(vault_id)
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    with connect() as conn:
        conn.execute(
            f"UPDATE vault_security_metadata SET {assignments} WHERE vault_id = :vault_id",
            {**updates, "vault_id": vault_id},
        )
    if current_unlock_state().get("vault_id") == vault_id:
        metadata = get_vault_security_metadata(vault_id)
        _set_state(
            current_unlock_state()["state"],
            vault_id=vault_id,
            unlock_mode=str(metadata["unlock_mode"]),
            pin_enabled=bool(metadata["pin_enabled"]),
            message=current_unlock_state()["message"],
        )
    return get_vault_security_metadata(vault_id)


def should_pause_vault_job(write_scope: str | None) -> bool:
    if not security_gate_active():
        return False
    if write_scope not in VAULT_BOUND_JOB_SCOPES:
        return False
    return current_unlock_state()["state"] != "ready"


def _verify_after_unlock(vault_id: str) -> dict:
    try:
        metadata = get_vault_security_metadata(vault_id)
        if not is_vault_unlocked(vault_id):
            raise UnlockStateError("vault_key_not_loaded")
        if metadata.get("content_migration_status", "complete") != "complete":
            _audit("content_migration_resumed", vault_id)
            with connect() as conn:
                migrate_existing_plaintext_content(conn, vault_id)
            metadata = get_vault_security_metadata(vault_id)
        if metadata.get("content_migration_status", "complete") != "complete":
            raise UnlockStateError("content_migration_incomplete")
        _validate_compact_tuple(metadata.get("active_derived_state_tuple"))
    except Exception as exc:
        _set_state(
            "repair_required",
            vault_id=vault_id,
            message="Vault needs repair before opening.",
            verification_error=str(exc)[:300],
        )
        _audit("unlock_repair_required", vault_id, str(exc)[:300])
        raise RepairRequiredError("vault_repair_required") from exc
    _set_state(
        "ready",
        vault_id=vault_id,
        unlock_mode=str(metadata["unlock_mode"]),
        pin_enabled=bool(metadata["pin_enabled"]),
        message="Vault ready.",
    )
    _audit("unlock_ready", vault_id)
    return current_unlock_state()


def _validate_compact_tuple(raw: object) -> None:
    if not isinstance(raw, str) or not raw:
        raise UnlockStateError("missing_active_derived_state_tuple")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise UnlockStateError("invalid_active_derived_state_tuple")
    for key in ("normalization_version", "extraction_version", "epoch"):
        if key not in parsed:
            raise UnlockStateError(f"missing_active_tuple_field:{key}")
    if "embedding_model_id" not in parsed and "embedding_model_version" not in parsed:
        raise UnlockStateError("missing_active_tuple_field:embedding_model_id")


def _set_state(
    state: UnlockState,
    *,
    vault_id: str | None,
    message: str,
    unlock_mode: str | None = None,
    pin_enabled: bool | None = None,
    verification_error: str = "",
) -> None:
    global _STATE
    if unlock_mode is None or pin_enabled is None:
        try:
            if vault_id:
                metadata = get_vault_security_metadata(vault_id)
                unlock_mode = unlock_mode or str(metadata["unlock_mode"])
                pin_enabled = bool(metadata["pin_enabled"]) if pin_enabled is None else pin_enabled
        except VaultCryptoError:
            pass
    with _STATE_LOCK:
        _STATE = UnlockStateSnapshot(
            state=state,
            vault_id=vault_id,
            unlock_mode=unlock_mode or "convenience",
            pin_enabled=bool(pin_enabled),
            message=message,
            verification_error=verification_error,
            updated_at=utc_now(),
        )


def _audit(event_type: str, vault_id: str | None, detail: str = "") -> None:
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vault_lock_audit (id, event_type, pid, owner_pid, lock_path, detail, user_choice, created_at)
                VALUES (?, ?, NULL, NULL, '', ?, '', ?)
                """,
                (f"unlock-{uuid4()}", event_type, f"vault_id={vault_id or ''} {detail}".strip(), utc_now()),
            )
    except Exception:
        return
