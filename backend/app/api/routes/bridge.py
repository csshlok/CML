import json
import secrets
from uuid import uuid4

from fastapi import APIRouter, Header

from backend.app.api.routes.search import semantic_search
from backend.app.api.routes.sources import source_from_row
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    BridgeContextRequest,
    BridgeContextResponse,
    BridgeRequestRead,
    BridgeSettingsUpdate,
    BridgeStatus,
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
    if updates.get("rotate_token") or not next_settings.get("bridge_token"):
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
    return bridge_status()


@router.post("/context", response_model=BridgeContextResponse)
def build_context(payload: BridgeContextRequest, x_cml_bridge_token: str | None = Header(default=None)) -> dict:
    settings = _get_bridge_settings()
    if not settings["enabled"]:
        return {
            "query": payload.query,
            "selected_clusters": [],
            "source_snippets": [],
            "warnings": ["Bridge is off. Enable it before external clients can request context."],
        }
    if not settings["bridge_token"] or x_cml_bridge_token != settings["bridge_token"]:
        return {
            "query": payload.query,
            "selected_clusters": [],
            "source_snippets": [],
            "warnings": ["Bridge blocked this request because the client token is missing or invalid."],
        }

    with connect() as conn:
        vault_id = payload.vault_id
        if vault_id:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                return {
                    "query": payload.query,
                    "selected_clusters": [],
                    "source_snippets": [],
                    "warnings": ["Bridge could not find the requested vault."],
                }
        else:
            vault = conn.execute("SELECT id FROM vaults ORDER BY updated_at DESC LIMIT 1").fetchone()
            if vault is None:
                return {
                    "query": payload.query,
                    "selected_clusters": [],
                    "source_snippets": [],
                    "warnings": ["Bridge needs a vault before it can retrieve context."],
                }
            vault_id = vault["id"]

        if settings["allowed_vault_ids"] and vault_id not in settings["allowed_vault_ids"]:
            return {
                "query": payload.query,
                "selected_clusters": [],
                "source_snippets": [],
                "warnings": ["Bridge blocked this request because the vault is not allowed."],
            }

        if payload.cluster_id:
            if settings["allowed_cluster_ids"] and payload.cluster_id not in settings["allowed_cluster_ids"]:
                return {
                    "query": payload.query,
                    "selected_clusters": [],
                    "source_snippets": [],
                    "warnings": ["Bridge blocked this request because the cluster is not allowed."],
                }
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (payload.cluster_id, vault_id),
            ).fetchone()
            if cluster is None:
                return {
                    "query": payload.query,
                    "selected_clusters": [],
                    "source_snippets": [],
                    "warnings": ["Bridge could not find the requested cluster in this vault."],
                }

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bridge_requests (id, client_name, query, mode, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"bridge-{uuid4()}", payload.client_name, payload.query, payload.mode, utc_now()),
        )

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
    if not settings["allow_raw_snippets"]:
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
