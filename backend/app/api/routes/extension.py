import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.routes.sources import create_source
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    ExtensionCaptureRequest,
    ExtensionCaptureRead,
    ExtensionCaptureResponse,
    ExtensionClientCreate,
    ExtensionClientCreateResponse,
    ExtensionClientRead,
    ExtensionClientUpdate,
    ExtensionPairingRead,
    ExtensionPairingStartRequest,
    ExtensionPermissionAuditRead,
    ExtensionStatusResponse,
    SourceCreate,
)

router = APIRouter(prefix="/extension", tags=["extension"])


@router.get("/clients", response_model=list[ExtensionClientRead])
def list_extension_clients() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, enabled, allowed_vault_ids, created_at, updated_at
            FROM extension_clients
            ORDER BY updated_at DESC
            LIMIT 50
            """
        ).fetchall()
    return [_client_from_row(row) for row in rows]


@router.post("/clients", response_model=ExtensionClientCreateResponse)
def create_extension_client(payload: ExtensionClientCreate) -> dict:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    client = {
        "id": f"extension-client-{uuid4()}",
        "name": payload.name,
        "token_hash": _hash_token(token),
        "enabled": 1,
        "allowed_vault_ids": json.dumps(payload.allowed_vault_ids),
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO extension_clients (
                id, name, token_hash, enabled, allowed_vault_ids, created_at, updated_at
            )
            VALUES (:id, :name, :token_hash, :enabled, :allowed_vault_ids, :created_at, :updated_at)
            """,
            client,
        )
        _insert_extension_audit(conn, client_id=client["id"], event_type="client_created", vault_id=None, detail="")
    return {
        "id": client["id"],
        "name": client["name"],
        "token": token,
        "enabled": True,
        "allowed_vault_ids": payload.allowed_vault_ids,
        "created_at": now,
    }


@router.patch("/clients/{client_id}", response_model=ExtensionClientRead)
def update_extension_client(client_id: str, payload: ExtensionClientUpdate) -> dict:
    now = utc_now()
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _get_extension_client(client_id)
    fields = []
    params: list[object] = []
    if "enabled" in updates:
        fields.append("enabled = ?")
        params.append(1 if updates["enabled"] else 0)
    if "allowed_vault_ids" in updates:
        fields.append("allowed_vault_ids = ?")
        params.append(json.dumps(updates["allowed_vault_ids"] or []))
    fields.append("updated_at = ?")
    params.append(now)
    params.append(client_id)
    with connect() as conn:
        result = conn.execute(
            f"UPDATE extension_clients SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Extension client not found")
        _insert_extension_audit(
            conn,
            client_id=client_id,
            event_type="client_updated",
            vault_id=None,
            detail=json.dumps(updates),
        )
    return _get_extension_client(client_id)


@router.delete("/clients/{client_id}", status_code=204)
def revoke_extension_client(client_id: str) -> None:
    with connect() as conn:
        result = conn.execute(
            "UPDATE extension_clients SET enabled = 0, token_hash = '', updated_at = ? WHERE id = ?",
            (utc_now(), client_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Extension client not found")
        _insert_extension_audit(conn, client_id=client_id, event_type="client_revoked", vault_id=None, detail="")


@router.post("/pairing/start", response_model=ExtensionPairingRead)
def start_extension_pairing(payload: ExtensionPairingStartRequest) -> dict:
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    session = {
        "id": f"extension-pairing-{uuid4()}",
        "pairing_code": secrets.token_urlsafe(8),
        "status": "pending",
        "requested_name": payload.name,
        "allowed_vault_ids": json.dumps(payload.allowed_vault_ids),
        "created_at": now,
        "expires_at": (now_dt + timedelta(seconds=payload.ttl_seconds)).isoformat(),
        "completed_at": None,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO extension_pairing_sessions (
                id, pairing_code, status, requested_name, allowed_vault_ids, created_at, expires_at, completed_at
            )
            VALUES (
                :id, :pairing_code, :status, :requested_name, :allowed_vault_ids, :created_at, :expires_at, :completed_at
            )
            """,
            session,
        )
        _insert_extension_audit(
            conn,
            client_id=None,
            event_type="pairing_started",
            vault_id=None,
            detail=json.dumps({"pairing_id": session["id"]}),
        )
    return _pairing_from_mapping(session)


@router.post("/pairing/{pairing_id}/approve", response_model=ExtensionClientCreateResponse)
def approve_extension_pairing(pairing_id: str) -> dict:
    with connect() as conn:
        pairing = conn.execute("SELECT * FROM extension_pairing_sessions WHERE id = ?", (pairing_id,)).fetchone()
        if pairing is None:
            raise HTTPException(status_code=404, detail="Extension pairing not found")
        if pairing["status"] != "pending":
            raise HTTPException(status_code=409, detail="Extension pairing is not pending")
        if pairing["expires_at"] <= utc_now():
            conn.execute("UPDATE extension_pairing_sessions SET status = 'expired' WHERE id = ?", (pairing_id,))
            raise HTTPException(status_code=409, detail="Extension pairing expired")
    client = create_extension_client(
        ExtensionClientCreate(
            name=pairing["requested_name"],
            allowed_vault_ids=_json_list(pairing["allowed_vault_ids"]),
        )
    )
    with connect() as conn:
        conn.execute(
            "UPDATE extension_pairing_sessions SET status = 'approved', completed_at = ? WHERE id = ?",
            (utc_now(), pairing_id),
        )
        _insert_extension_audit(
            conn,
            client_id=client["id"],
            event_type="pairing_approved",
            vault_id=None,
            detail=json.dumps({"pairing_id": pairing_id}),
        )
    return client


@router.get("/pairing", response_model=list[ExtensionPairingRead])
def list_extension_pairings() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM extension_pairing_sessions ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [_pairing_from_row(row) for row in rows]


@router.get("/permission-audit", response_model=list[ExtensionPermissionAuditRead])
def list_extension_permission_audit(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM extension_permission_audit ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/captures", response_model=list[ExtensionCaptureRead])
def list_extension_captures(vault_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if vault_id:
            rows = conn.execute(
                """
                SELECT * FROM extension_captures
                WHERE vault_id = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (vault_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM extension_captures
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
    return [dict(row) for row in rows]


@router.get("/status", response_model=ExtensionStatusResponse)
def extension_status(x_cml_extension_token: str | None = Header(default=None)) -> dict:
    client = _client_for_token(x_cml_extension_token)
    if client is None:
        return {"ok": False, "client_id": None, "detail": "Missing or invalid extension token."}
    return {"ok": True, "client_id": client["id"], "detail": "Extension capture is available."}


@router.post("/capture", response_model=ExtensionCaptureResponse)
def capture_from_extension(
    payload: ExtensionCaptureRequest,
    x_cml_extension_token: str | None = Header(default=None),
) -> dict:
    client = _client_for_token(x_cml_extension_token)
    if client is None:
        raise HTTPException(status_code=401, detail="Missing or invalid extension token")
    if not _client_allows_vault(client, payload.vault_id):
        with connect() as conn:
            _insert_extension_audit(
                conn,
                client_id=client["id"],
                event_type="capture_denied",
                vault_id=payload.vault_id,
                detail="vault_not_allowed",
            )
        raise HTTPException(status_code=403, detail="Extension client is not allowed to capture into this vault")
    source = create_source(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=payload.title,
            source_type=f"extension_{payload.capture_type}",
            url=payload.url or None,
            raw_text=payload.text,
        )
    )
    now = utc_now()
    capture_id = f"extension-capture-{uuid4()}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO extension_captures (
                id, client_id, vault_id, source_id, capture_type, title, url, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'stored', ?)
            """,
            (
                capture_id,
                client["id"],
                payload.vault_id,
                source["id"],
                payload.capture_type,
                payload.title,
                payload.url,
                now,
            ),
        )
        _insert_extension_audit(
            conn,
            client_id=client["id"],
            event_type="capture_stored",
            vault_id=payload.vault_id,
            detail=json.dumps({"capture_id": capture_id, "source_id": source["id"]}),
        )
    return {"capture_id": capture_id, "source_id": source["id"], "status": "stored"}


def _client_for_token(token: str | None):
    if not token:
        return None
    token_hash = _hash_token(token)
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM extension_clients
            WHERE token_hash = ? AND enabled = 1
            LIMIT 1
            """,
            (token_hash,),
        ).fetchone()


def _get_extension_client(client_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, enabled, allowed_vault_ids, created_at, updated_at
            FROM extension_clients
            WHERE id = ?
            """,
            (client_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Extension client not found")
    return _client_from_row(row)


def _client_from_row(row) -> dict:
    try:
        allowed_vault_ids = json.loads(row["allowed_vault_ids"] or "[]")
    except json.JSONDecodeError:
        allowed_vault_ids = []
    return {
        "id": row["id"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "allowed_vault_ids": allowed_vault_ids if isinstance(allowed_vault_ids, list) else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pairing_from_row(row) -> dict:
    return _pairing_from_mapping(dict_from_row(row))


def _pairing_from_mapping(row: dict) -> dict:
    return {
        "id": row["id"],
        "pairing_code": row["pairing_code"],
        "status": row["status"],
        "requested_name": row["requested_name"],
        "allowed_vault_ids": _json_list(row.get("allowed_vault_ids")),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "completed_at": row.get("completed_at"),
    }


def _client_allows_vault(client, vault_id: str) -> bool:
    try:
        allowed = json.loads(client["allowed_vault_ids"] or "[]")
    except json.JSONDecodeError:
        allowed = []
    return not allowed or vault_id in allowed


def _json_list(raw: str | None) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _insert_extension_audit(conn, *, client_id: str | None, event_type: str, vault_id: str | None, detail: str) -> None:
    conn.execute(
        """
        INSERT INTO extension_permission_audit (id, client_id, event_type, vault_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (f"extension-audit-{uuid4()}", client_id, event_type, vault_id, detail[:1000], utc_now()),
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
