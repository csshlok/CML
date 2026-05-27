from uuid import uuid4

from fastapi import APIRouter

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    BridgeContextRequest,
    BridgeContextResponse,
    BridgeRequestRead,
    BridgeStatus,
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
        conn.execute(
            """
            INSERT INTO bridge_requests (id, client_name, query, mode, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"bridge-{uuid4()}", payload.client_name, payload.query, payload.mode, utc_now()),
        )

        if payload.cluster_id:
            cluster_rows = conn.execute(
                "SELECT * FROM clusters WHERE id = ?",
                (payload.cluster_id,),
            ).fetchall()
        else:
            cluster_rows = conn.execute(
                "SELECT * FROM clusters ORDER BY updated_at DESC LIMIT 3"
            ).fetchall()

        source_rows = conn.execute(
            """
            SELECT * FROM sources
            WHERE extracted_text != ''
            ORDER BY updated_at DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "query": payload.query,
        "selected_clusters": [dict_from_row(row) for row in cluster_rows],
        "source_snippets": [dict_from_row(row) for row in source_rows],
        "warnings": ["Bridge context is using early metadata retrieval; semantic search is not wired yet."],
    }


@router.get("/requests", response_model=list[BridgeRequestRead])
def list_bridge_requests() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bridge_requests ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [dict_from_row(row) for row in rows]
