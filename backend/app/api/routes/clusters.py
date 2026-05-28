from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.cluster_suggestions import suggest_source_cluster_moves
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.sql import build_update_assignments
from backend.app.schemas import ClusterCreate, ClusterRead, ClusterSuggestionRead, ClusterUpdate

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("", response_model=list[ClusterRead])
def list_clusters(vault_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if vault_id:
            rows = conn.execute(
                "SELECT * FROM clusters WHERE vault_id = ? ORDER BY updated_at DESC",
                (vault_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clusters ORDER BY updated_at DESC").fetchall()
        return [dict_from_row(row) for row in rows]


@router.post("", response_model=ClusterRead)
def create_cluster(payload: ClusterCreate) -> dict:
    now = utc_now()
    cluster = {
        "id": f"cluster-{uuid4()}",
        "vault_id": payload.vault_id,
        "name": payload.name,
        "description": payload.description,
        "color": payload.color,
        "expert_status": "setting-up",
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        conn.execute(
            """
            INSERT INTO clusters (
                id, vault_id, name, description, color, expert_status, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :name, :description, :color, :expert_status, :created_at, :updated_at
            )
            """,
            cluster,
        )
    return cluster


@router.get("/suggestions", response_model=list[ClusterSuggestionRead])
def list_cluster_suggestions(vault_id: str, limit: int = 12) -> list[dict]:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return suggest_source_cluster_moves(conn, vault_id, limit=max(1, min(limit, 30)))


@router.get("/{cluster_id}", response_model=ClusterRead)
def get_cluster(cluster_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return dict_from_row(row)


@router.patch("/{cluster_id}", response_model=ClusterRead)
def update_cluster(cluster_id: str, payload: ClusterUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_cluster(cluster_id)

    updates["updated_at"] = utc_now()
    assignments = build_update_assignments(
        updates,
        {"name", "description", "color", "expert_status", "updated_at"},
    )
    params = {"id": cluster_id, **updates}
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(f"UPDATE clusters SET {assignments} WHERE id = :id", params)
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    return dict_from_row(row)


@router.delete("/{cluster_id}", status_code=204)
def delete_cluster(cluster_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cluster not found")
