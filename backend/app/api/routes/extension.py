import base64
import hashlib
import binascii
import json
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.routes.sources import _create_source_record, create_source
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.config import get_settings
from backend.app.core.bridge_security import BridgeRateLimitError, enforce_rate_limit
from backend.app.core.extraction import ExtractionError
from backend.app.core.quarantine import attach_quarantine_record, ingest_file_through_quarantine
from backend.app.schemas import (
    ExtensionCaptureRequest,
    ExtensionCaptureRead,
    ExtensionCaptureResponse,
    ExtensionClientCreate,
    ExtensionClientCreateResponse,
    ExtensionClientRead,
    ExtensionClientUpdate,
    ExtensionDesktopSetupCreate,
    ExtensionDesktopSetupRead,
    ExtensionPairingRead,
    ExtensionPairingStartRequest,
    ExtensionPermissionAuditRead,
    ExtensionStatusResponse,
    ExtensionUploadCaptureRequest,
    SourceCreate,
)

router = APIRouter(prefix="/extension", tags=["extension"])
MAX_EXTENSION_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/clients", response_model=list[ExtensionClientRead])
def list_extension_clients(limit: int = 50, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, enabled, allowed_vault_ids, created_at, updated_at
            FROM extension_clients
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        ).fetchall()
    return [_client_from_row(row) for row in rows]


@router.post("/clients", response_model=ExtensionClientCreateResponse)
def create_extension_client(payload: ExtensionClientCreate) -> dict:
    with connect() as conn:
        return _create_extension_client_in_connection(conn, payload)


def _create_extension_client_in_connection(conn, payload: ExtensionClientCreate) -> dict:
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


@router.post("/desktop-setup", response_model=ExtensionDesktopSetupRead)
def create_desktop_extension_setup(payload: ExtensionDesktopSetupCreate) -> dict:
    with connect() as conn:
        vault = conn.execute("SELECT id, path FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        if payload.cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (payload.cluster_id, payload.vault_id),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="Cluster not found")
    client = create_extension_client(
        ExtensionClientCreate(name=payload.name, allowed_vault_ids=[payload.vault_id]),
    )
    browser = str(payload.browser or "chrome").strip().lower() or "chrome"
    if browser not in {"chrome", "brave"}:
        browser = "chrome"
    backend_url = str(payload.backend_url or "http://127.0.0.1:7343").rstrip("/")
    settings = get_settings()
    return {
        "backend_url": backend_url,
        "api_prefix": settings.api_prefix,
        "extension_token": client["token"],
        "default_vault_id": payload.vault_id,
        "default_cluster_id": str(payload.cluster_id or ""),
        "vault_path": str(vault["path"]),
        "client_name": payload.name,
        "browser": browser,
        "install_targets": ["chrome", "brave"],
        "primary_actions": ["save_link_to_vault", "take_and_save_screenshot"],
        "optional_actions": ["save_selection"],
        "save_root": str(vault["path"]),
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


@router.post("/clients/{client_id}/rotate", response_model=ExtensionClientCreateResponse)
def rotate_extension_client(client_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    with connect() as conn:
        client = conn.execute(
            "SELECT * FROM extension_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if client is None:
            raise HTTPException(status_code=404, detail="Extension client not found")
        if not bool(client["enabled"]):
            raise HTTPException(status_code=409, detail="Enable this extension client before rotating its token")
        conn.execute(
            "UPDATE extension_clients SET token_hash = ?, updated_at = ? WHERE id = ?",
            (_hash_token(token), now, client_id),
        )
        _insert_extension_audit(
            conn,
            client_id=client_id,
            event_type="client_token_rotated",
            vault_id=None,
            detail="",
        )
        allowed_vault_ids = _json_list(client["allowed_vault_ids"])
    return {
        "id": client_id,
        "name": client["name"],
        "token": token,
        "enabled": True,
        "allowed_vault_ids": allowed_vault_ids,
        "created_at": client["created_at"],
    }


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
    expired = False
    with connect() as conn:
        # Serialize the one-time claim and client creation. Without an immediate
        # write lock, two approvers can both observe `pending` and mint separate
        # credentials before either one marks the pairing complete.
        conn.execute("BEGIN IMMEDIATE")
        pairing = conn.execute("SELECT * FROM extension_pairing_sessions WHERE id = ?", (pairing_id,)).fetchone()
        if pairing is None:
            raise HTTPException(status_code=404, detail="Extension pairing not found")
        if pairing["status"] != "pending":
            raise HTTPException(status_code=409, detail="Extension pairing is not pending")
        now = utc_now()
        if pairing["expires_at"] <= now:
            conn.execute("UPDATE extension_pairing_sessions SET status = 'expired' WHERE id = ?", (pairing_id,))
            expired = True
            client = None
        else:
            claimed = conn.execute(
                """
                UPDATE extension_pairing_sessions
                SET status = 'approving'
                WHERE id = ? AND status = 'pending' AND expires_at > ?
                """,
                (pairing_id, now),
            )
            if claimed.rowcount != 1:
                raise HTTPException(status_code=409, detail="Extension pairing is not pending")
            client = _create_extension_client_in_connection(
                conn,
                ExtensionClientCreate(
                    name=pairing["requested_name"],
                    allowed_vault_ids=_json_list(pairing["allowed_vault_ids"]),
                ),
            )
            conn.execute(
                "UPDATE extension_pairing_sessions SET status = 'approved', completed_at = ? WHERE id = ?",
                (now, pairing_id),
            )
            _insert_extension_audit(
                conn,
                client_id=client["id"],
                event_type="pairing_approved",
                vault_id=None,
                detail=json.dumps({"pairing_id": pairing_id}),
            )
    if expired:
        # Raise after the context commits the terminal expiry state.
        raise HTTPException(status_code=409, detail="Extension pairing expired")
    assert client is not None
    return client


@router.get("/pairing", response_model=list[ExtensionPairingRead])
def list_extension_pairings(limit: int = 50, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM extension_pairing_sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (safe_limit, safe_offset),
        ).fetchall()
    return [_pairing_from_row(row) for row in rows]


@router.get("/permission-audit", response_model=list[ExtensionPermissionAuditRead])
def list_extension_permission_audit(limit: int = 50, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM extension_permission_audit ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (safe_limit, safe_offset),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/captures", response_model=list[ExtensionCaptureRead])
def list_extension_captures(vault_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        if vault_id:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                raise HTTPException(status_code=404, detail="Vault not found")
            rows = conn.execute(
                """
                SELECT * FROM extension_captures
                WHERE vault_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (vault_id, safe_limit, safe_offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM extension_captures
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
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
    _reserve_extension_storage(client["id"], len(payload.text.encode("utf-8")))
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


@router.post("/capture-upload", response_model=ExtensionCaptureResponse)
def capture_uploaded_file_from_extension(
    payload: ExtensionUploadCaptureRequest,
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

    file_bytes = _decode_upload_bytes(payload.content_base64)
    _reserve_extension_storage(client["id"], len(file_bytes))
    source = _create_uploaded_extension_source(payload, file_bytes=file_bytes)
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
    return bool(allowed) and vault_id in allowed


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


def _create_uploaded_extension_source(payload: ExtensionUploadCaptureRequest, *, file_bytes: bytes | None = None) -> dict:
    file_name = _safe_upload_file_name(payload.file_name, payload.mime_type, payload.capture_type)
    file_bytes = file_bytes if file_bytes is not None else _decode_upload_bytes(payload.content_base64)
    suffix = Path(file_name).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="cml-extension-upload-") as temp_dir:
        temp_path = Path(temp_dir) / file_name
        temp_path.write_bytes(file_bytes)
        try:
            ingested = ingest_file_through_quarantine(payload.vault_id, str(temp_path))
        except ExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    pages = ingested["pages"]
    raw_text = "\n\n".join(page for page in pages if page.strip()).strip()
    security = ingested["security"]
    checksum = security["validation"]["content_hash"]
    source_type = _uploaded_extension_source_type(payload.capture_type, suffix)
    source = _create_source_record(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=payload.title,
            source_type=source_type,
            url=payload.url or None,
            checksum=checksum,
            raw_text=raw_text,
            tags=security["security_labels"],
        ),
        page_texts=pages,
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE sources
            SET provenance = ?,
                trust_tier = ?,
                security_labels = ?,
                parser_security_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                security["provenance"],
                security["trust_tier"],
                json.dumps(security["security_labels"], sort_keys=True),
                json.dumps(security, sort_keys=True),
                utc_now(),
                source["id"],
            ),
        )
    attach_quarantine_record(ingested["quarantine_record_id"], source["id"])
    return source


def _decode_upload_bytes(content_base64: str) -> bytes:
    if len(content_base64) > 27_962_028:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the 20 MB extension upload limit.")
    try:
        payload = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Uploaded file payload is not valid base64.") from exc
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file payload is empty.")
    if len(payload) > MAX_EXTENSION_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the 20 MB extension upload limit.")
    return payload


def _reserve_extension_storage(client_id: str, byte_count: int) -> None:
    try:
        with connect() as conn:
            enforce_rate_limit(
                conn,
                scope_type="extension_storage",
                scope_id=client_id,
                bucket="stored_bytes",
                limit=10_000,
                window_seconds=24 * 60 * 60,
                byte_count=byte_count,
                byte_limit=500 * 1024 * 1024,
            )
    except BridgeRateLimitError as exc:
        raise HTTPException(status_code=429, detail="Extension storage quota exceeded") from exc


def _safe_upload_file_name(file_name: str, mime_type: str, capture_type: str) -> str:
    raw = Path(str(file_name or "").replace("\\", "/")).name.strip()
    if raw:
        return raw
    suffix = _suffix_for_mime_type(mime_type, capture_type)
    return f"extension-capture{suffix}"


def _suffix_for_mime_type(mime_type: str, capture_type: str) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized == "application/pdf":
        return ".pdf"
    if normalized in {"image/png", "image/x-png"}:
        return ".png"
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/gif":
        return ".gif"
    if normalized == "text/markdown":
        return ".md"
    if normalized in {"application/json", "text/json"}:
        return ".json"
    if normalized in {"text/plain", "text/csv"}:
        return ".txt" if normalized == "text/plain" else ".csv"
    if capture_type == "screenshot":
        return ".png"
    return ".bin"


def _uploaded_extension_source_type(capture_type: str, suffix: str) -> str:
    if capture_type == "screenshot":
        return "extension_screenshot"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "extension_image"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c"}:
        return "extension_code"
    if suffix in {".md", ".markdown", ".txt", ".text"}:
        return "extension_note"
    return "extension_file"
