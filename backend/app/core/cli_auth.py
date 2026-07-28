import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.runtime_identity import BACKEND_INSTANCE_ID


PAIRING_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 900
MAX_PAIRING_FAILURES = 8
CLI_SCOPES = frozenset({
    "context:read",
    "project:read",
    "project:write",
    "source:read",
    "cluster:link",
})


class CliAuthError(ValueError):
    def __init__(self, code: str, *, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_pairing_challenge(
    *,
    verifier_hash: str,
    requested_scopes: list[str],
    requester_name: str,
    executable_fingerprint: str,
    runtime_instance_id: str,
) -> dict:
    normalized_scopes = _normalize_scopes(requested_scopes)
    if runtime_instance_id != BACKEND_INSTANCE_ID:
        raise CliAuthError("backend_identity_mismatch", status_code=409)
    if len(verifier_hash) != 64 or any(char not in "0123456789abcdef" for char in verifier_hash.lower()):
        raise CliAuthError("invalid_pairing_verifier")
    normalized_name = requester_name.strip()[:120] or "Odin CLI"
    normalized_fingerprint = executable_fingerprint.strip().lower()
    if len(normalized_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in normalized_fingerprint):
        raise CliAuthError("invalid_executable_fingerprint")
    now = datetime.now(UTC)
    challenge = {
        "id": f"cli-pair-{uuid4()}",
        "verifier_hash": verifier_hash.lower(),
        "requested_scopes_json": json.dumps(normalized_scopes, separators=(",", ":")),
        "requester_name": normalized_name,
        "executable_fingerprint": normalized_fingerprint,
        "runtime_instance_id": runtime_instance_id,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=PAIRING_TTL_SECONDS)).isoformat(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO cli_pairing_challenges (
                id, verifier_hash, requested_scopes_json, requester_name,
                executable_fingerprint, runtime_instance_id, status, created_at, expires_at
            ) VALUES (
                :id, :verifier_hash, :requested_scopes_json, :requester_name,
                :executable_fingerprint, :runtime_instance_id, :status, :created_at, :expires_at
            )
            """,
            challenge,
        )
        _audit(conn, event_type="pairing_requested", challenge_id=challenge["id"])
    return _public_challenge(challenge)


def pairing_status(challenge_id: str, verifier: str) -> dict:
    with connect() as conn:
        row = _verified_challenge(conn, challenge_id, verifier)
        return _public_challenge(dict_from_row(row))


def consume_pairing(challenge_id: str, verifier: str) -> dict:
    with connect() as conn:
        row = _verified_challenge(conn, challenge_id, verifier)
        if row["status"] != "approved" or not row["client_id"]:
            raise CliAuthError("pairing_not_approved", status_code=409)
        if row["consumed_at"]:
            raise CliAuthError("pairing_already_consumed", status_code=409)
        credential = secrets.token_urlsafe(48)
        now = utc_now()
        updated = conn.execute(
            """
            UPDATE cli_pairing_challenges
            SET status = 'consumed', consumed_at = ?, last_polled_at = ?
            WHERE id = ? AND consumed_at IS NULL AND status = 'approved'
            """,
            (now, now, challenge_id),
        )
        if updated.rowcount != 1:
            raise CliAuthError("pairing_already_consumed", status_code=409)
        conn.execute(
            "UPDATE cli_clients SET credential_hash = ? WHERE id = ?",
            (token_hash(credential), row["client_id"]),
        )
        client = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (row["client_id"],)).fetchone()
        _audit(conn, event_type="pairing_consumed", client_id=row["client_id"], challenge_id=challenge_id)
        return {
            "client": _public_client(dict_from_row(client)),
            "credential": credential,
        }


def list_pairing_challenges(*, status: str = "pending", limit: int = 50) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM cli_pairing_challenges
            ORDER BY created_at DESC
            """,
        ).fetchall()
        challenges = [
            _public_challenge(dict_from_row(row), include_request=True)
            for row in rows
        ]
        return [challenge for challenge in challenges if challenge["status"] == status][:safe_limit]


def approve_pairing(challenge_id: str, *, scopes: list[str], allowed_vault_ids: list[str]) -> dict:
    normalized_scopes = _normalize_scopes(scopes)
    normalized_vault_ids = sorted({value.strip() for value in allowed_vault_ids if value.strip()})
    if not normalized_vault_ids:
        raise CliAuthError("at_least_one_vault_required")
    with connect() as conn:
        _expire_pairings(conn)
        row = conn.execute("SELECT * FROM cli_pairing_challenges WHERE id = ?", (challenge_id,)).fetchone()
        if row is None:
            raise CliAuthError("pairing_not_found", status_code=404)
        if row["status"] != "pending":
            raise CliAuthError("pairing_not_pending", status_code=409)
        requested = set(json.loads(row["requested_scopes_json"] or "[]"))
        if not set(normalized_scopes) <= requested:
            raise CliAuthError("scope_not_requested")
        known_vaults = {
            item["id"]
            for item in conn.execute(
                f"SELECT id FROM vaults WHERE id IN ({','.join('?' for _ in normalized_vault_ids)})",
                normalized_vault_ids,
            ).fetchall()
        }
        if known_vaults != set(normalized_vault_ids):
            raise CliAuthError("vault_not_found", status_code=404)
        client_id = f"cli-client-{uuid4()}"
        now = utc_now()
        conn.execute(
            """
            INSERT INTO cli_clients (
                id, display_name, executable_fingerprint, credential_hash,
                credential_version, scopes_json, allowed_vault_ids_json, created_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                client_id,
                row["requester_name"],
                row["executable_fingerprint"],
                f"pending:{challenge_id}",
                json.dumps(normalized_scopes, separators=(",", ":")),
                json.dumps(normalized_vault_ids, separators=(",", ":")),
                now,
            ),
        )
        conn.execute(
            """
            UPDATE cli_pairing_challenges
            SET client_id = ?, status = 'approved', approved_at = ? WHERE id = ?
            """,
            (client_id, now, challenge_id),
        )
        _audit(conn, event_type="pairing_approved", client_id=client_id, challenge_id=challenge_id)
        client = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        return _public_client(dict_from_row(client))


def deny_pairing(challenge_id: str) -> dict:
    with connect() as conn:
        _expire_pairings(conn)
        row = conn.execute("SELECT * FROM cli_pairing_challenges WHERE id = ?", (challenge_id,)).fetchone()
        if row is None:
            raise CliAuthError("pairing_not_found", status_code=404)
        if row["status"] != "pending":
            raise CliAuthError("pairing_not_pending", status_code=409)
        now = utc_now()
        conn.execute(
            "UPDATE cli_pairing_challenges SET status = 'denied', denied_at = ? WHERE id = ?",
            (now, challenge_id),
        )
        _audit(conn, event_type="pairing_denied", challenge_id=challenge_id)
        return {"id": challenge_id, "status": "denied", "denied_at": now}


def create_session(*, client_id: str, credential: str, executable_fingerprint: str | None = None) -> dict:
    with connect() as conn:
        client = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        if client is None or client["revoked_at"]:
            raise CliAuthError("invalid_cli_credential", status_code=401)
        if executable_fingerprint is not None and not hmac.compare_digest(
            executable_fingerprint.strip().lower(), str(client["executable_fingerprint"]).lower()
        ):
            _audit(conn, event_type="executable_fingerprint_mismatch", client_id=client_id)
            raise CliAuthError("executable_fingerprint_mismatch", status_code=401)
        supplied_hash = token_hash(credential)
        if not hmac.compare_digest(supplied_hash, client["credential_hash"]):
            _audit(conn, event_type="session_exchange_failed", client_id=client_id)
            raise CliAuthError("invalid_cli_credential", status_code=401)
        now = datetime.now(UTC)
        session_token = secrets.token_urlsafe(48)
        session = {
            "id": f"cli-session-{uuid4()}",
            "client_id": client_id,
            "token_hash": token_hash(session_token),
            "session_version": int(client["credential_version"]),
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat(),
        }
        conn.execute(
            """
            INSERT INTO cli_sessions (
                id, client_id, token_hash, session_version, issued_at, expires_at
            ) VALUES (
                :id, :client_id, :token_hash, :session_version, :issued_at, :expires_at
            )
            """,
            session,
        )
        conn.execute("UPDATE cli_clients SET last_used_at = ? WHERE id = ?", (session["issued_at"], client_id))
        _audit(conn, event_type="session_issued", client_id=client_id)
        return {
            "session_token": session_token,
            "expires_at": session["expires_at"],
            "client": _public_client(dict_from_row(client)),
        }


def authenticate_session(session_token: str) -> dict | None:
    if not session_token:
        return None
    hashed = token_hash(session_token)
    now = datetime.now(UTC)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, c.display_name, c.executable_fingerprint, c.credential_version,
                   c.scopes_json, c.allowed_vault_ids_json, c.revoked_at AS client_revoked_at,
                   c.last_used_at AS client_last_used_at
            FROM cli_sessions s
            JOIN cli_clients c ON c.id = s.client_id
            WHERE s.token_hash = ?
            """,
            (hashed,),
        ).fetchone()
        if row is None or row["revoked_at"] or row["client_revoked_at"]:
            return None
        if int(row["session_version"]) != int(row["credential_version"]):
            return None
        if _parse_time(row["expires_at"]) <= now:
            return None
        last_used = _parse_time(row["last_used_at"] or row["issued_at"])
        if now - last_used >= timedelta(minutes=5):
            used_at = now.isoformat()
            conn.execute("UPDATE cli_sessions SET last_used_at = ? WHERE id = ?", (used_at, row["id"]))
            conn.execute("UPDATE cli_clients SET last_used_at = ? WHERE id = ?", (used_at, row["client_id"]))
        return {
            "kind": "cli",
            "session_id": row["id"],
            "client_id": row["client_id"],
            "display_name": row["display_name"],
            "scopes": set(json.loads(row["scopes_json"] or "[]")),
            "allowed_vault_ids": set(json.loads(row["allowed_vault_ids_json"] or "[]")),
            "expires_at": row["expires_at"],
        }


def list_clients() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM cli_clients ORDER BY created_at DESC").fetchall()
        return [_public_client(dict_from_row(row)) for row in rows]


def revoke_client(client_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        client = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        if client is None:
            raise CliAuthError("cli_client_not_found", status_code=404)
        conn.execute("UPDATE cli_clients SET revoked_at = ? WHERE id = ?", (now, client_id))
        conn.execute("UPDATE cli_sessions SET revoked_at = ? WHERE client_id = ? AND revoked_at IS NULL", (now, client_id))
        _audit(conn, event_type="client_revoked", client_id=client_id)
        updated = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        return _public_client(dict_from_row(updated))


def rotate_client(client_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        client = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        if client is None:
            raise CliAuthError("cli_client_not_found", status_code=404)
        if client["revoked_at"]:
            raise CliAuthError("cli_client_revoked", status_code=409)
        next_version = int(client["credential_version"]) + 1
        conn.execute(
            """
            UPDATE cli_clients SET credential_hash = ?, credential_version = ?, rotated_at = ?
            WHERE id = ?
            """,
            (f"rotation-required:{next_version}", next_version, now, client_id),
        )
        conn.execute("UPDATE cli_sessions SET revoked_at = ? WHERE client_id = ? AND revoked_at IS NULL", (now, client_id))
        _audit(conn, event_type="client_rotated", client_id=client_id)
        updated = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client_id,)).fetchone()
        result = _public_client(dict_from_row(updated))
        result["requires_pairing"] = True
        return result


def cli_auth_me(context: dict) -> dict:
    return {
        "client_id": context["client_id"],
        "display_name": context["display_name"],
        "scopes": sorted(context["scopes"]),
        "allowed_vault_ids": sorted(context["allowed_vault_ids"]),
        "expires_at": context["expires_at"],
        "backend_instance_id": BACKEND_INSTANCE_ID,
    }


def _verified_challenge(conn, challenge_id: str, verifier: str):
    row = conn.execute("SELECT * FROM cli_pairing_challenges WHERE id = ?", (challenge_id,)).fetchone()
    if row is None:
        raise CliAuthError("pairing_not_found", status_code=404)
    if int(row["failed_attempt_count"] or 0) >= MAX_PAIRING_FAILURES:
        raise CliAuthError("pairing_locked", status_code=429)
    if not hmac.compare_digest(token_hash(verifier), row["verifier_hash"]):
        conn.execute(
            """
            UPDATE cli_pairing_challenges
            SET failed_attempt_count = failed_attempt_count + 1, last_polled_at = ? WHERE id = ?
            """,
            (utc_now(), challenge_id),
        )
        raise CliAuthError("invalid_pairing_verifier", status_code=401)
    if _effective_challenge_status(dict_from_row(row)) == "expired":
        raise CliAuthError("pairing_expired", status_code=410)
    return row


def _expire_pairings(conn) -> None:
    conn.execute(
        """
        UPDATE cli_pairing_challenges SET status = 'expired'
        WHERE status IN ('pending', 'approved') AND expires_at <= ?
        """,
        (utc_now(),),
    )


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted({value.strip() for value in scopes if value.strip()})
    unknown = set(normalized) - CLI_SCOPES
    if unknown:
        raise CliAuthError(f"unsupported_cli_scope:{sorted(unknown)[0]}")
    if not normalized:
        raise CliAuthError("at_least_one_scope_required")
    return normalized


def _public_challenge(row: dict, *, include_request: bool = False) -> dict:
    result = {
        "id": row["id"],
        "status": _effective_challenge_status(row),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "approved_at": row.get("approved_at"),
        "denied_at": row.get("denied_at"),
        "consumed_at": row.get("consumed_at"),
    }
    if include_request:
        result.update({
            "requester_name": row["requester_name"],
            "executable_fingerprint": row["executable_fingerprint"],
            "requested_scopes": json.loads(row["requested_scopes_json"] or "[]"),
            "client_id": row.get("client_id"),
        })
    return result


def _effective_challenge_status(row: dict) -> str:
    status = str(row["status"])
    if status in {"pending", "approved"} and _parse_time(str(row["expires_at"])) <= datetime.now(UTC):
        return "expired"
    return status


def _public_client(row: dict) -> dict:
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "executable_fingerprint": row["executable_fingerprint"],
        "credential_version": int(row["credential_version"]),
        "scopes": json.loads(row["scopes_json"] or "[]"),
        "allowed_vault_ids": json.loads(row["allowed_vault_ids_json"] or "[]"),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "rotated_at": row["rotated_at"],
        "revoked_at": row["revoked_at"],
    }


def _audit(
    conn,
    *,
    event_type: str,
    client_id: str | None = None,
    challenge_id: str | None = None,
    detail: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO cli_auth_audit (
            id, client_id, challenge_id, event_type, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"cli-audit-{uuid4()}",
            client_id,
            challenge_id,
            event_type,
            json.dumps(detail or {}, separators=(",", ":")),
            utc_now(),
        ),
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
