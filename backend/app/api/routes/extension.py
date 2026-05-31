import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.routes.sources import create_source
from backend.app.core.database import connect, utc_now
from backend.app.schemas import (
    ExtensionCaptureRequest,
    ExtensionCaptureResponse,
    ExtensionClientCreate,
    ExtensionClientCreateResponse,
    ExtensionStatusResponse,
    SourceCreate,
)

router = APIRouter(prefix="/extension", tags=["extension"])


@router.post("/clients", response_model=ExtensionClientCreateResponse)
def create_extension_client(payload: ExtensionClientCreate) -> dict:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    client = {
        "id": f"extension-client-{uuid4()}",
        "name": payload.name,
        "token_hash": _hash_token(token),
        "enabled": 1,
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO extension_clients (
                id, name, token_hash, enabled, created_at, updated_at
            )
            VALUES (:id, :name, :token_hash, :enabled, :created_at, :updated_at)
            """,
            client,
        )
    return {"id": client["id"], "name": client["name"], "token": token, "created_at": now}


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


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
