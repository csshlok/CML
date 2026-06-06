import base64
import binascii
import json
import re
import secrets
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.app.core.database import connect, dict_from_row, utc_now

SECURITY_VERSION = 1
VAULT_MASTER_KEY_BYTES = 32
WRAP_NONCE_BYTES = 12
SALT_BYTES = 16
RECOVERY_KEY_BYTES = 32
RECOVERY_KEY_GROUP = 4
KDF_ALGORITHM = "argon2id"
DEFAULT_KDF_PARAMS = {
    "length": 32,
    "iterations": 3,
    "lanes": 4,
    "memory_cost": 65536,
}
TEST_KDF_PARAMS = {
    "length": 32,
    "iterations": 1,
    "lanes": 1,
    "memory_cost": 8192,
}
DEFAULT_DERIVED_STATE_TUPLE = {
    "normalization_version": "norm-v1",
    "embedding_model_version": "unset",
    "extraction_version": "extract-v1",
    "epoch": 1,
}
SENSITIVE_VALUE_RE = re.compile(
    r"(CMLR-[A-Z2-7-]+|passphrase\s*[:=]\s*[^,\s]+|recovery(?:[-_ ]?key)?\s*[:=]\s*[^,\s]+|[A-Za-z0-9+/]{32,}={0,2})",
    re.IGNORECASE,
)


class VaultCryptoError(RuntimeError):
    pass


class VaultSecurityExistsError(VaultCryptoError):
    pass


class VaultSecurityNotInitializedError(VaultCryptoError):
    pass


class InvalidVaultSecretError(VaultCryptoError):
    def __init__(self) -> None:
        super().__init__("invalid_vault_secret")


@dataclass(frozen=True)
class VaultKeyMaterial:
    vault_id: str
    master_key: bytes


@dataclass(frozen=True)
class VaultSubkeys:
    database_key: bytes
    blob_key: bytes
    metadata_key: bytes
    lora_artifact_key: bytes


@dataclass(frozen=True)
class VaultSetupResult:
    vault_id: str
    recovery_key: str


_ACTIVE_KEYS: dict[str, VaultKeyMaterial] = {}


def initialize_vault_security(
    vault_id: str,
    passphrase: str,
    *,
    unlock_mode: Literal["convenience", "strict"] = "convenience",
    kdf_params: dict | None = None,
) -> VaultSetupResult:
    _validate_secret(passphrase, "passphrase")
    if unlock_mode not in {"convenience", "strict"}:
        raise ValueError("unlock_mode must be convenience or strict")
    params = _normalize_kdf_params(kdf_params)
    master_key = secrets.token_bytes(VAULT_MASTER_KEY_BYTES)
    recovery_key_bytes = secrets.token_bytes(RECOVERY_KEY_BYTES)
    recovery_key = _format_recovery_key(recovery_key_bytes)
    passphrase_salt = secrets.token_bytes(SALT_BYTES)
    recovery_salt = secrets.token_bytes(SALT_BYTES)
    passphrase_kek = _derive_kek(passphrase.encode("utf-8"), passphrase_salt, params)
    recovery_kek = _derive_kek(_canonical_recovery_key_bytes(recovery_key), recovery_salt, params)
    now = utc_now()
    metadata = {
        "vault_id": vault_id,
        "security_version": SECURITY_VERSION,
        "kdf_algorithm": KDF_ALGORITHM,
        "kdf_params_json": json.dumps(params, sort_keys=True),
        "passphrase_salt": _b64e(passphrase_salt),
        "passphrase_wrapped_vmk": _b64e(_wrap_key(passphrase_kek, master_key, vault_id, "passphrase")),
        "recovery_salt": _b64e(recovery_salt),
        "recovery_wrapped_vmk": _b64e(_wrap_key(recovery_kek, master_key, vault_id, "recovery")),
        "unlock_mode": unlock_mode,
        "pin_enabled": 0,
        "pin_salt": "",
        "pin_wrapped_unlock_secret": "",
        "active_derived_state_tuple": json.dumps(DEFAULT_DERIVED_STATE_TUPLE, sort_keys=True),
        "previous_verified_tuple": "{}",
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise VaultCryptoError("vault_not_found")
        existing = conn.execute("SELECT vault_id FROM vault_security_metadata WHERE vault_id = ?", (vault_id,)).fetchone()
        if existing is not None:
            raise VaultSecurityExistsError("vault_security_already_initialized")
        conn.execute(
            """
            INSERT INTO vault_security_metadata (
                vault_id, security_version, kdf_algorithm, kdf_params_json,
                passphrase_salt, passphrase_wrapped_vmk, recovery_salt, recovery_wrapped_vmk,
                unlock_mode, pin_enabled, pin_salt, pin_wrapped_unlock_secret,
                active_derived_state_tuple, previous_verified_tuple, created_at, updated_at
            )
            VALUES (
                :vault_id, :security_version, :kdf_algorithm, :kdf_params_json,
                :passphrase_salt, :passphrase_wrapped_vmk, :recovery_salt, :recovery_wrapped_vmk,
                :unlock_mode, :pin_enabled, :pin_salt, :pin_wrapped_unlock_secret,
                :active_derived_state_tuple, :previous_verified_tuple, :created_at, :updated_at
            )
            """,
            metadata,
        )
    _ACTIVE_KEYS[vault_id] = VaultKeyMaterial(vault_id=vault_id, master_key=master_key)
    return VaultSetupResult(vault_id=vault_id, recovery_key=recovery_key)


def unlock_vault_with_passphrase(vault_id: str, passphrase: str) -> VaultKeyMaterial:
    _validate_secret(passphrase, "passphrase")
    row = _metadata(vault_id)
    params = _row_kdf_params(row)
    salt = _b64d(row["passphrase_salt"])
    wrapped = _b64d(row["passphrase_wrapped_vmk"])
    kek = _derive_kek(passphrase.encode("utf-8"), salt, params)
    master_key = _unwrap_key(kek, wrapped, vault_id, "passphrase")
    material = VaultKeyMaterial(vault_id=vault_id, master_key=master_key)
    _ACTIVE_KEYS[vault_id] = material
    return material


def unlock_vault_with_recovery_key(vault_id: str, recovery_key: str) -> VaultKeyMaterial:
    recovery_bytes = _canonical_recovery_key_bytes(recovery_key)
    row = _metadata(vault_id)
    params = _row_kdf_params(row)
    salt = _b64d(row["recovery_salt"])
    wrapped = _b64d(row["recovery_wrapped_vmk"])
    kek = _derive_kek(recovery_bytes, salt, params)
    master_key = _unwrap_key(kek, wrapped, vault_id, "recovery")
    material = VaultKeyMaterial(vault_id=vault_id, master_key=master_key)
    _ACTIVE_KEYS[vault_id] = material
    return material


def reset_passphrase_with_recovery_key(
    vault_id: str,
    recovery_key: str,
    new_passphrase: str,
    *,
    kdf_params: dict | None = None,
) -> None:
    _validate_secret(new_passphrase, "passphrase")
    material = unlock_vault_with_recovery_key(vault_id, recovery_key)
    row = _metadata(vault_id)
    params = _normalize_kdf_params(kdf_params or _row_kdf_params(row))
    passphrase_salt = secrets.token_bytes(SALT_BYTES)
    recovery_salt = secrets.token_bytes(SALT_BYTES)
    passphrase_kek = _derive_kek(new_passphrase.encode("utf-8"), passphrase_salt, params)
    recovery_kek = _derive_kek(_canonical_recovery_key_bytes(recovery_key), recovery_salt, params)
    with connect() as conn:
        conn.execute(
            """
            UPDATE vault_security_metadata
            SET kdf_params_json = ?,
                passphrase_salt = ?,
                passphrase_wrapped_vmk = ?,
                recovery_salt = ?,
                recovery_wrapped_vmk = ?,
                updated_at = ?
            WHERE vault_id = ?
            """,
            (
                json.dumps(params, sort_keys=True),
                _b64e(passphrase_salt),
                _b64e(_wrap_key(passphrase_kek, material.master_key, vault_id, "passphrase")),
                _b64e(recovery_salt),
                _b64e(_wrap_key(recovery_kek, material.master_key, vault_id, "recovery")),
                utc_now(),
                vault_id,
            ),
        )
    _ACTIVE_KEYS[vault_id] = material


def verify_sensitive_action(vault_id: str, passphrase: str) -> bool:
    unlock_vault_with_passphrase(vault_id, passphrase)
    return True


def derive_vault_subkeys(material: VaultKeyMaterial) -> VaultSubkeys:
    return VaultSubkeys(
        database_key=_hkdf(material.master_key, b"cml-vault-database-key-v1"),
        blob_key=_hkdf(material.master_key, b"cml-vault-blob-key-v1"),
        metadata_key=_hkdf(material.master_key, b"cml-vault-metadata-key-v1"),
        lora_artifact_key=_hkdf(material.master_key, b"cml-vault-lora-artifact-key-v1"),
    )


def lock_vault(vault_id: str) -> None:
    material = _ACTIVE_KEYS.pop(vault_id, None)
    if material is not None:
        _best_effort_zeroize(material.master_key)


def lock_all_vaults() -> None:
    for vault_id in list(_ACTIVE_KEYS):
        lock_vault(vault_id)


def is_vault_unlocked(vault_id: str) -> bool:
    return vault_id in _ACTIVE_KEYS


def active_key_count() -> int:
    return len(_ACTIVE_KEYS)


def get_vault_security_metadata(vault_id: str) -> dict:
    row = _metadata(vault_id)
    data = dict_from_row(row)
    for key in (
        "passphrase_salt",
        "passphrase_wrapped_vmk",
        "recovery_salt",
        "recovery_wrapped_vmk",
        "pin_salt",
        "pin_wrapped_unlock_secret",
    ):
        data.pop(key, None)
    data["has_vendor_recovery"] = False
    data["pin_enabled"] = bool(data.get("pin_enabled"))
    return data


def no_vendor_recovery_available() -> bool:
    return True


def redact_security_material(value: object) -> str:
    return SENSITIVE_VALUE_RE.sub("[REDACTED]", str(value))


def _metadata(vault_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM vault_security_metadata WHERE vault_id = ?", (vault_id,)).fetchone()
    if row is None:
        raise VaultSecurityNotInitializedError("vault_security_not_initialized")
    return row


def _derive_kek(secret: bytes, salt: bytes, params: dict) -> bytes:
    return Argon2id(
        salt=salt,
        length=int(params["length"]),
        iterations=int(params["iterations"]),
        lanes=int(params["lanes"]),
        memory_cost=int(params["memory_cost"]),
    ).derive(secret)


def _wrap_key(kek: bytes, master_key: bytes, vault_id: str, purpose: str) -> bytes:
    nonce = secrets.token_bytes(WRAP_NONCE_BYTES)
    encrypted = AESGCM(kek).encrypt(nonce, master_key, _aad(vault_id, purpose))
    return nonce + encrypted


def _unwrap_key(kek: bytes, wrapped: bytes, vault_id: str, purpose: str) -> bytes:
    if len(wrapped) <= WRAP_NONCE_BYTES:
        raise InvalidVaultSecretError()
    nonce = wrapped[:WRAP_NONCE_BYTES]
    ciphertext = wrapped[WRAP_NONCE_BYTES:]
    try:
        return AESGCM(kek).decrypt(nonce, ciphertext, _aad(vault_id, purpose))
    except (InvalidTag, ValueError) as exc:
        raise InvalidVaultSecretError() from exc


def _aad(vault_id: str, purpose: str) -> bytes:
    return f"cml:vault:{vault_id}:security:{SECURITY_VERSION}:{purpose}".encode("utf-8")


def _hkdf(master_key: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master_key)


def _format_recovery_key(key: bytes) -> str:
    encoded = base64.b32encode(key).decode("ascii").rstrip("=")
    grouped = "-".join(encoded[index : index + RECOVERY_KEY_GROUP] for index in range(0, len(encoded), RECOVERY_KEY_GROUP))
    return f"CMLR-{grouped}"


def _canonical_recovery_key_bytes(recovery_key: str) -> bytes:
    normalized = recovery_key.strip().upper().replace(" ", "").replace("-", "")
    if normalized.startswith("CMLR"):
        normalized = normalized[4:]
    if not normalized:
        raise InvalidVaultSecretError()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        return base64.b32decode(normalized + padding)
    except (binascii.Error, ValueError) as exc:
        raise InvalidVaultSecretError() from exc


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidVaultSecretError() from exc


def _row_kdf_params(row) -> dict:
    if row["kdf_algorithm"] != KDF_ALGORITHM:
        raise VaultCryptoError("unsupported_kdf_algorithm")
    try:
        parsed = json.loads(row["kdf_params_json"])
    except json.JSONDecodeError as exc:
        raise VaultCryptoError("invalid_kdf_params") from exc
    return _normalize_kdf_params(parsed)


def _normalize_kdf_params(params: dict | None) -> dict:
    normalized = dict(DEFAULT_KDF_PARAMS if params is None else params)
    for key in ("length", "iterations", "lanes", "memory_cost"):
        try:
            normalized[key] = int(normalized[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_kdf_param:{key}") from exc
        if normalized[key] <= 0:
            raise ValueError(f"invalid_kdf_param:{key}")
    if normalized["length"] != 32:
        raise ValueError("invalid_kdf_param:length")
    return {key: normalized[key] for key in ("length", "iterations", "lanes", "memory_cost")}


def _validate_secret(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name}_required")


def _best_effort_zeroize(value: bytes) -> None:
    # Python bytes are immutable; this is a documented best-effort hook for future native storage.
    _ = value
