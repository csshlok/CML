import json
import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.routes.search import semantic_search
from backend.app.api.routes.sources import source_from_row
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    BridgeContextRequest,
    BridgeContextResponse,
    BridgeClientCreate,
    BridgeClientCreateResponse,
    BridgeClientRead,
    BridgeClientUpdate,
    BridgeRequestRead,
    BridgeSettingsUpdate,
    BridgeStatus,
    BridgeTokenRotationRead,
    SemanticSearchRequest,
)

router = APIRouter(prefix="/bridge", tags=["bridge"])


@router.get("/status", response_model=BridgeStatus)
def bridge_status() -> dict[str, str | bool]:
    settings = _get_bridge_settings()
    return {
        **settings,
        "mcp": "planned",
        "http_api": "available",
        "cli": "planned",
        "last_refreshed_at": utc_now(),
    }


@router.patch("/settings", response_model=BridgeStatus)
def update_bridge_settings(payload: BridgeSettingsUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    settings = _get_bridge_settings()
    next_settings = {**settings, **updates}
    rotating = bool(updates.get("rotate_token") or not next_settings.get("bridge_token"))
    previous_token = str(settings.get("bridge_token") or "")
    if rotating:
        next_settings["bridge_token"] = secrets.token_urlsafe(24)
    now = utc_now()
    with connect() as conn:
        _ensure_bridge_settings(conn)
        conn.execute(
            """
            UPDATE bridge_settings
            SET enabled = ?,
                allowed_vault_ids = ?,
                allowed_cluster_ids = ?,
                allow_raw_snippets = ?,
                allow_style_profile = ?,
                allow_expert_calls = ?,
                bridge_token = ?,
                updated_at = ?
            WHERE id = 'default'
            """,
            (
                1 if next_settings["enabled"] else 0,
                json.dumps(next_settings["allowed_vault_ids"]),
                json.dumps(next_settings["allowed_cluster_ids"]),
                1 if next_settings["allow_raw_snippets"] else 0,
                1 if next_settings["allow_style_profile"] else 0,
                1 if next_settings["allow_expert_calls"] else 0,
                next_settings["bridge_token"],
                now,
            ),
        )
        if rotating:
            conn.execute(
                """
                INSERT INTO bridge_token_rotations (
                    id, rotated_at, reason, previous_token_hash, new_token_hash
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"bridge-token-rotation-{uuid4()}",
                    now,
                    "manual_rotation" if updates.get("rotate_token") else "initial_token_created",
                    _token_hash(previous_token),
                    _token_hash(next_settings["bridge_token"]),
                ),
            )
    return bridge_status()


@router.post("/context", response_model=BridgeContextResponse)
def build_context(payload: BridgeContextRequest, x_cml_bridge_token: str | None = Header(default=None)) -> dict:
    settings = _get_bridge_settings()
    client_permissions = _bridge_client_for_token(x_cml_bridge_token)
    if not settings["enabled"]:
        _log_bridge_request(payload, mode_suffix="blocked_disabled")
        raise HTTPException(status_code=403, detail="bridge_disabled")
    if client_permissions is None and not _token_matches(settings["bridge_token"], x_cml_bridge_token):
        _log_bridge_request(payload, mode_suffix="blocked_token")
        raise HTTPException(status_code=401, detail="bridge_token_invalid")
    permissions = client_permissions or settings

    with connect() as conn:
        vault_id = payload.vault_id
        if vault_id:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                _log_bridge_request(payload, mode_suffix="vault_not_found")
                raise HTTPException(status_code=404, detail="vault_not_found")
        else:
            if len(permissions["allowed_vault_ids"]) == 1:
                vault_id = permissions["allowed_vault_ids"][0]
            else:
                _log_bridge_request(payload, mode_suffix="no_active_vault")
                raise HTTPException(status_code=409, detail="no_active_vault")

        if permissions["allowed_vault_ids"] and vault_id not in permissions["allowed_vault_ids"]:
            _log_bridge_request(payload, mode_suffix="vault_not_allowed")
            raise HTTPException(status_code=403, detail="vault_not_allowed")

        if payload.cluster_id:
            if permissions["allowed_cluster_ids"] and payload.cluster_id not in permissions["allowed_cluster_ids"]:
                _log_bridge_request(payload, mode_suffix="cluster_not_allowed")
                raise HTTPException(status_code=403, detail="cluster_not_allowed")
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (payload.cluster_id, vault_id),
            ).fetchone()
            if cluster is None:
                _log_bridge_request(payload, mode_suffix="cluster_not_found")
                raise HTTPException(status_code=404, detail="cluster_not_found")

    with connect() as conn:
        _insert_bridge_request(conn, payload.client_name, payload.query, payload.mode)

    search_response = semantic_search(
        SemanticSearchRequest(
            vault_id=vault_id,
            query=payload.query,
            cluster_id=payload.cluster_id,
            limit=payload.limit,
        )
    )
    results = search_response["results"]
    source_ids = []
    cluster_ids = []
    for result in results:
        if result["source_id"] not in source_ids:
            source_ids.append(result["source_id"])
        cluster_id = result.get("cluster_id")
        if cluster_id and cluster_id not in cluster_ids:
            cluster_ids.append(cluster_id)

    warnings = []
    with connect() as conn:
        if cluster_ids:
            cluster_rows = conn.execute(
                f"""
                SELECT * FROM clusters
                WHERE vault_id = ? AND id IN ({",".join("?" for _ in cluster_ids)})
                ORDER BY updated_at DESC
                """,
                [vault_id, *cluster_ids],
            ).fetchall()
        elif payload.cluster_id:
            cluster_rows = conn.execute(
                "SELECT * FROM clusters WHERE id = ? AND vault_id = ?",
                (payload.cluster_id, vault_id),
            ).fetchall()
            warnings.append("Bridge found the selected cluster but no matching indexed chunks.")
        else:
            cluster_rows = []
            if not results:
                warnings.append("Bridge did not find matching indexed chunks for this query.")

        source_rows = []
        if source_ids:
            source_rows = conn.execute(
                f"""
                SELECT * FROM sources
                WHERE vault_id = ? AND id IN ({",".join("?" for _ in source_ids)})
                """,
                [vault_id, *source_ids],
            ).fetchall()
        else:
            warnings.append("Add or reindex sources before relying on Bridge context.")

    sources_by_id = {row["id"]: source_from_row(row) for row in source_rows}
    ordered_sources = [sources_by_id[source_id] for source_id in source_ids if source_id in sources_by_id]
    if not permissions["allow_raw_snippets"]:
        for source in ordered_sources:
            source["raw_text"] = ""
            source["extracted_text"] = ""
        if ordered_sources:
            warnings.append("Raw source text is redacted by Bridge permissions.")
    if results:
        warnings.append("Bridge context is ranked by local semantic search.")

    return {
        "query": payload.query,
        "selected_clusters": [dict_from_row(row) for row in cluster_rows],
        "source_snippets": ordered_sources,
        "warnings": warnings,
    }


@router.get("/requests", response_model=list[BridgeRequestRead])
def list_bridge_requests() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bridge_requests
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
    return [dict_from_row(row) for row in rows]


@router.get("/token-rotations", response_model=list[BridgeTokenRotationRead])
def list_bridge_token_rotations() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, rotated_at, reason
            FROM bridge_token_rotations
            ORDER BY rotated_at DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict_from_row(row) for row in rows]


@router.get("/clients", response_model=list[BridgeClientRead])
def list_bridge_clients() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bridge_clients ORDER BY updated_at DESC"
        ).fetchall()
    return [_bridge_client_from_row(row) for row in rows]


@router.post("/clients", response_model=BridgeClientCreateResponse)
def create_bridge_client(payload: BridgeClientCreate) -> dict:
    now = utc_now()
    token = secrets.token_urlsafe(24)
    client = {
        "id": f"bridge-client-{uuid4()}",
        "name": payload.name,
        "token_hash": _token_hash(token),
        "enabled": 1,
        "allowed_vault_ids": json.dumps(payload.allowed_vault_ids),
        "allowed_cluster_ids": json.dumps(payload.allowed_cluster_ids),
        "allow_raw_snippets": 1 if payload.allow_raw_snippets else 0,
        "allow_style_profile": 1 if payload.allow_style_profile else 0,
        "allow_expert_calls": 1 if payload.allow_expert_calls else 0,
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bridge_clients (
                id, name, token_hash, enabled, allowed_vault_ids, allowed_cluster_ids,
                allow_raw_snippets, allow_style_profile, allow_expert_calls, created_at, updated_at
            )
            VALUES (
                :id, :name, :token_hash, :enabled, :allowed_vault_ids, :allowed_cluster_ids,
                :allow_raw_snippets, :allow_style_profile, :allow_expert_calls, :created_at, :updated_at
            )
            """,
            client,
        )
    return {**_bridge_client_from_mapping(client), "token": token}


@router.patch("/clients/{client_id}", response_model=BridgeClientCreateResponse | BridgeClientRead)
def update_bridge_client(client_id: str, payload: BridgeClientUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_client_not_found")
        current = dict_from_row(row)
        token = None
        if updates.get("rotate_token"):
            token = secrets.token_urlsafe(24)
            conn.execute(
                """
                INSERT INTO bridge_client_token_rotations (
                    id, client_id, rotated_at, reason, previous_token_hash, new_token_hash
                )
                VALUES (?, ?, ?, 'manual_rotation', ?, ?)
                """,
                (
                    f"bridge-client-token-rotation-{uuid4()}",
                    client_id,
                    now,
                    current["token_hash"],
                    _token_hash(token),
                ),
            )
            current["token_hash"] = _token_hash(token)
        for key in (
            "name",
            "enabled",
            "allowed_vault_ids",
            "allowed_cluster_ids",
            "allow_raw_snippets",
            "allow_style_profile",
            "allow_expert_calls",
        ):
            if key in updates and updates[key] is not None:
                value = updates[key]
                if key in {"allowed_vault_ids", "allowed_cluster_ids"}:
                    value = json.dumps(value)
                elif key in {"enabled", "allow_raw_snippets", "allow_style_profile", "allow_expert_calls"}:
                    value = 1 if value else 0
                current[key] = value
        current["updated_at"] = now
        conn.execute(
            """
            UPDATE bridge_clients
            SET name = :name,
                token_hash = :token_hash,
                enabled = :enabled,
                allowed_vault_ids = :allowed_vault_ids,
                allowed_cluster_ids = :allowed_cluster_ids,
                allow_raw_snippets = :allow_raw_snippets,
                allow_style_profile = :allow_style_profile,
                allow_expert_calls = :allow_expert_calls,
                updated_at = :updated_at
            WHERE id = :id
            """,
            current,
        )
        updated = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
    result = _bridge_client_from_row(updated)
    if token:
        return {**result, "token": token}
    return result


@router.delete("/clients/{client_id}", status_code=204)
def revoke_bridge_client(client_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM bridge_clients WHERE id = ?", (client_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="bridge_client_not_found")


@router.get("/clusters")
def list_bridge_clusters(x_cml_bridge_token: str | None = Header(default=None)) -> dict:
    settings = _get_bridge_settings()
    client_permissions = _bridge_client_for_token(x_cml_bridge_token)
    if not settings["enabled"]:
        raise HTTPException(status_code=403, detail="bridge_disabled")
    if client_permissions is None and not _token_matches(settings["bridge_token"], x_cml_bridge_token):
        raise HTTPException(status_code=401, detail="bridge_token_invalid")
    permissions = client_permissions or settings
    if not permissions["allowed_vault_ids"]:
        raise HTTPException(status_code=409, detail="no_active_vault")
    with connect() as conn:
        params: list[str] = list(permissions["allowed_vault_ids"])
        vault_clause = f"vault_id IN ({','.join('?' for _ in params)})"
        cluster_clause = ""
        if permissions["allowed_cluster_ids"]:
            cluster_clause = f" AND id IN ({','.join('?' for _ in permissions['allowed_cluster_ids'])})"
            params.extend(permissions["allowed_cluster_ids"])
        rows = conn.execute(
            f"SELECT * FROM clusters WHERE {vault_clause}{cluster_clause} ORDER BY updated_at DESC",
            params,
        ).fetchall()
    return {"clusters": [dict_from_row(row) for row in rows]}


def _ensure_bridge_settings(conn) -> None:
    existing = conn.execute("SELECT id FROM bridge_settings WHERE id = 'default'").fetchone()
    if existing is not None:
        return
    now = utc_now()
    conn.execute(
        """
        INSERT INTO bridge_settings (
            id, enabled, allowed_vault_ids, allowed_cluster_ids, allow_raw_snippets,
            allow_style_profile, allow_expert_calls, bridge_token, created_at, updated_at
        )
        VALUES ('default', 0, '[]', '[]', 0, 0, 0, ?, ?, ?)
        """,
        (secrets.token_urlsafe(24), now, now),
    )


def _get_bridge_settings() -> dict:
    with connect() as conn:
        _ensure_bridge_settings(conn)
        row = conn.execute("SELECT * FROM bridge_settings WHERE id = 'default'").fetchone()
        existing_vault_ids = {
            vault["id"] for vault in conn.execute("SELECT id FROM vaults").fetchall()
        }
        existing_cluster_ids = {
            cluster["id"] for cluster in conn.execute("SELECT id FROM clusters").fetchall()
        }
        allowed_vault_ids = [
            str(item) for item in _json_list(row["allowed_vault_ids"]) if str(item) in existing_vault_ids
        ]
        allowed_cluster_ids = [
            str(item)
            for item in _json_list(row["allowed_cluster_ids"])
            if str(item) in existing_cluster_ids
        ]
        if (
            allowed_vault_ids != _json_list(row["allowed_vault_ids"])
            or allowed_cluster_ids != _json_list(row["allowed_cluster_ids"])
        ):
            conn.execute(
                """
                UPDATE bridge_settings
                SET allowed_vault_ids = ?, allowed_cluster_ids = ?, updated_at = ?
                WHERE id = 'default'
                """,
                (json.dumps(allowed_vault_ids), json.dumps(allowed_cluster_ids), utc_now()),
            )
    return {
        "enabled": bool(row["enabled"]),
        "allowed_vault_ids": allowed_vault_ids,
        "allowed_cluster_ids": allowed_cluster_ids,
        "allow_raw_snippets": bool(row["allow_raw_snippets"]),
        "allow_style_profile": bool(row["allow_style_profile"]),
        "allow_expert_calls": bool(row["allow_expert_calls"]),
        "bridge_token": row["bridge_token"] or "",
    }


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _token_hash(token: str) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bridge_client_for_token(token: str | None) -> dict | None:
    if token and len(token) > 512:
        return None
    token_hash = _token_hash(token or "")
    if not token_hash:
        return None
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bridge_clients WHERE enabled = 1"
        ).fetchall()
    for row in rows:
        if secrets.compare_digest(str(row["token_hash"]), token_hash):
            return _bridge_client_from_row(row)
    return None


def _token_matches(expected: str, supplied: str | None) -> bool:
    if not expected or not supplied or len(supplied) > 512:
        return False
    return secrets.compare_digest(expected, supplied)


def _bridge_client_from_row(row) -> dict:
    return _bridge_client_from_mapping(dict_from_row(row))


def _bridge_client_from_mapping(client: dict) -> dict:
    return {
        "id": client["id"],
        "name": client["name"],
        "enabled": bool(client["enabled"]),
        "allowed_vault_ids": _json_list(client.get("allowed_vault_ids")),
        "allowed_cluster_ids": _json_list(client.get("allowed_cluster_ids")),
        "allow_raw_snippets": bool(client.get("allow_raw_snippets")),
        "allow_style_profile": bool(client.get("allow_style_profile")),
        "allow_expert_calls": bool(client.get("allow_expert_calls")),
        "created_at": client["created_at"],
        "updated_at": client["updated_at"],
    }


def _insert_bridge_request(conn, client_name: str, query: str, mode: str) -> None:
    conn.execute(
        """
        INSERT INTO bridge_requests (id, client_name, query, mode, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"bridge-{uuid4()}", client_name, query, mode, utc_now()),
    )


def _log_bridge_request(payload: BridgeContextRequest, *, mode_suffix: str) -> None:
    with connect() as conn:
        _insert_bridge_request(
            conn,
            payload.client_name,
            payload.query,
            f"{payload.mode}:{mode_suffix}",
        )
