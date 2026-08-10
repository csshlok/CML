import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from backend.app.core.encrypted_storage import get_encrypted_text, is_vault_secured, put_encrypted_text

APPROVAL_PENDING_SECONDS = 10 * 60
APPROVAL_DELIVERY_SECONDS = 10 * 60
APPROVAL_RETENTION_DAYS = 30
BRIDGE_REQUEST_RETENTION_DAYS = 30
BRIDGE_AUDIT_RETENTION_DAYS = 30
MAX_APPROVAL_HISTORY_ROWS = 1000
MAX_BRIDGE_REQUEST_ROWS = 5000
MAX_BRIDGE_AUDIT_ROWS = 5000
APPROVAL_RATE_WINDOW_SECONDS = 10 * 60
APPROVAL_RATE_LIMIT_PER_FINGERPRINT = 5
APPROVAL_RATE_LIMIT_GLOBAL = 20
CLIENT_RATE_WINDOW_SECONDS = 5 * 60
CLIENT_RATE_LIMIT = 60
GLOBAL_RATE_LIMIT = 240
CLIENT_RESPONSE_BYTE_LIMIT = 20 * 1024 * 1024
GLOBAL_RESPONSE_BYTE_LIMIT = 80 * 1024 * 1024


class BridgeRateLimitError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_after(seconds: int) -> str:
    return (now_utc() + timedelta(seconds=seconds)).isoformat()


def is_expired(value: str | None) -> bool:
    if not value:
        return False
    return parse_utc(value) <= now_utc()


def metadata_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def store_secure_json(
    conn,
    *,
    vault_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    payload: dict[str, Any],
    now: str | None = None,
) -> str:
    text = json.dumps(payload, sort_keys=True)
    if is_vault_secured(conn, vault_id):
        put_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            text=text,
            now=now,
        )
        return "{}"
    return text


def load_secure_json(
    conn,
    *,
    vault_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    fallback_text: str | None,
) -> dict[str, Any]:
    text = fallback_text or "{}"
    if is_vault_secured(conn, vault_id):
        decrypted = get_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
        )
        if decrypted:
            text = decrypted
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def inspect_client_identity(claimed_name: str, executable_path_claim: str | None) -> dict[str, Any]:
    claim = str(executable_path_claim or "").strip()
    observed = ""
    publisher_name = ""
    signature_status = "not_provided"
    signature_detail = ""
    if claim:
        candidate = Path(claim).expanduser()
        try:
            candidate = candidate.resolve()
        except OSError:
            candidate = candidate.absolute()
        if candidate.exists():
            observed = str(candidate)
            signature_status = "unavailable"
            publisher_name, signature_status, signature_detail = _probe_windows_signature(candidate)
        else:
            signature_status = "path_missing"
            signature_detail = "Claimed executable path does not exist on disk."
    return {
        "claimed_name": claimed_name.strip() or "unknown",
        "executable_path_claim": claim,
        "observed_executable_path": observed,
        "publisher_name": publisher_name,
        "signature_status": signature_status,
        "signature_detail": signature_detail,
        "verified_identity": False,
        "verified_identity_label": "",
    }


def enforce_rate_limit(
    conn,
    *,
    scope_type: str,
    scope_id: str,
    bucket: str,
    limit: int,
    window_seconds: int,
    byte_count: int = 0,
    byte_limit: int = 0,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT scope_type, scope_id, bucket, window_started_at, request_count, byte_count
        FROM bridge_rate_limits
        WHERE scope_type = ? AND scope_id = ? AND bucket = ?
        """,
        (scope_type, scope_id, bucket),
    ).fetchone()
    now = now_utc()
    now_text = now.isoformat()
    if row is None or parse_utc(row["window_started_at"]) + timedelta(seconds=window_seconds) <= now:
        current_count = 0
        current_bytes = 0
        window_started_at = now_text
    else:
        current_count = int(row["request_count"] or 0)
        current_bytes = int(row["byte_count"] or 0)
        window_started_at = str(row["window_started_at"])
    if current_count >= limit:
        raise BridgeRateLimitError("bridge_rate_limited")
    next_count = current_count + 1
    next_bytes = current_bytes + max(0, int(byte_count))
    if byte_limit > 0 and next_bytes > byte_limit:
        raise BridgeRateLimitError("bridge_byte_limit_exceeded")
    conn.execute(
        """
        INSERT INTO bridge_rate_limits (
            scope_type, scope_id, bucket, window_started_at, request_count, byte_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scope_type, scope_id, bucket) DO UPDATE SET
            window_started_at = excluded.window_started_at,
            request_count = excluded.request_count,
            byte_count = excluded.byte_count,
            updated_at = excluded.updated_at
        """,
        (scope_type, scope_id, bucket, window_started_at, next_count, next_bytes, now_text),
    )
    return {
        "window_started_at": window_started_at,
        "request_count": next_count,
        "byte_count": next_bytes,
    }


def compact_bridge_tables(conn) -> None:
    now = now_utc()
    request_cutoff = (now - timedelta(days=BRIDGE_REQUEST_RETENTION_DAYS)).isoformat()
    approval_cutoff = (now - timedelta(days=APPROVAL_RETENTION_DAYS)).isoformat()
    audit_cutoff = (now - timedelta(days=BRIDGE_AUDIT_RETENTION_DAYS)).isoformat()
    rate_cutoff = (now - timedelta(seconds=max(APPROVAL_RATE_WINDOW_SECONDS, CLIENT_RATE_WINDOW_SECONDS) * 3)).isoformat()
    conn.execute("DELETE FROM bridge_requests WHERE created_at < ?", (request_cutoff,))
    conn.execute(
        """
        DELETE FROM bridge_approval_requests
        WHERE updated_at < ?
          AND status IN ('approved', 'rejected', 'expired', 'revoked')
        """,
        (approval_cutoff,),
    )
    conn.execute("DELETE FROM bridge_audit_events WHERE created_at < ?", (audit_cutoff,))
    conn.execute("DELETE FROM bridge_rate_limits WHERE updated_at < ?", (rate_cutoff,))
    _cap_rows(conn, table="bridge_requests", order_by="created_at DESC", max_rows=MAX_BRIDGE_REQUEST_ROWS)
    _cap_rows(
        conn,
        table="bridge_approval_requests",
        order_by="updated_at DESC",
        max_rows=MAX_APPROVAL_HISTORY_ROWS,
    )
    _cap_rows(conn, table="bridge_audit_events", order_by="created_at DESC", max_rows=MAX_BRIDGE_AUDIT_ROWS)


def _cap_rows(conn, *, table: str, order_by: str, max_rows: int) -> None:
    count_row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    if int(count_row["count"] or 0) <= max_rows:
        return
    conn.execute(
        f"""
        DELETE FROM {table}
        WHERE id NOT IN (
            SELECT id FROM {table}
            ORDER BY {order_by}
            LIMIT ?
        )
        """,
        (max_rows,),
    )


def _probe_windows_signature(path: Path) -> tuple[str, str, str]:
    if os.name != "nt":
        return "", "unavailable", "Signature verification is only available on Windows."
    powershell = shutil.which("powershell")
    if not powershell:
        return "", "unavailable", "PowerShell is not available."
    command = [
        powershell,
        "-NoProfile",
        "-Command",
        (
            "$sig = Get-AuthenticodeSignature -LiteralPath $args[0]; "
            "[pscustomobject]@{"
            "Status=$sig.Status.ToString(); "
            "StatusMessage=$sig.StatusMessage; "
            "Subject=if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' }"
            "} | ConvertTo-Json -Compress"
        ),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return "", "unavailable", str(exc)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return "", "unavailable", detail[:240]
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "", "unavailable", completed.stdout.strip()[:240]
    subject = str(payload.get("Subject") or "")
    status = str(payload.get("Status") or "unavailable").strip() or "unavailable"
    detail = str(payload.get("StatusMessage") or "").strip()
    mapped = {
        "Valid": "signed_valid",
        "NotSigned": "not_signed",
        "HashMismatch": "signed_invalid",
        "NotTrusted": "signed_untrusted",
        "UnknownError": "signed_unknown_error",
    }.get(status, f"signed_{status.lower()}")
    return subject, mapped, detail[:240]
