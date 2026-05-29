from uuid import uuid4

from fastapi import APIRouter

from backend.app.api.routes.search import semantic_search
from backend.app.api.routes.sources import source_from_row
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    BridgeContextRequest,
    BridgeContextResponse,
    BridgeRequestRead,
    BridgeStatus,
    SemanticSearchRequest,
)

router = APIRouter(prefix="/bridge", tags=["bridge"])


@router.get("/status", response_model=BridgeStatus)
def bridge_status() -> dict[str, str | bool]:
    return {
        "enabled": False,
        "mcp": "planned",
        "http_api": "available",
        "cli": "planned",
    }


@router.post("/context", response_model=BridgeContextResponse)
def build_context(payload: BridgeContextRequest) -> dict:
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

        if payload.cluster_id:
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
