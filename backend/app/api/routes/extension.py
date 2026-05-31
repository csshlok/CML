import hashlib
import json
import secrets
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.routes.sources import create_source
from backend.app.core.database import connect, utc_now
from backend.app.schemas import (
    ExtensionCaptureRequest,
    ExtensionCaptureRead,
    ExtensionCaptureResponse,
    ExtensionClientCreate,
    ExtensionClientCreateResponse,
    ExtensionClientRead,
    ExtensionClientUpdate,
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


def _client_allows_vault(client, vault_id: str) -> bool:
    try:
        allowed = json.loads(client["allowed_vault_ids"] or "[]")
    except json.JSONDecodeError:
        allowed = []
    return not allowed or vault_id in allowed


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
