from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import SourceCreate, SourceRead, SourceUpdate

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
def list_sources(vault_id: str | None = None, cluster_id: str | None = None) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []
    if vault_id:
        clauses.append("vault_id = ?")
        params.append(vault_id)
    if cluster_id:
        clauses.append("cluster_id = ?")
        params.append(cluster_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM sources {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        return [dict_from_row(row) for row in rows]


@router.post("", response_model=SourceRead)
def create_source(payload: SourceCreate) -> dict:
    now = utc_now()
    source = {
        "id": f"source-{uuid4()}",
        "vault_id": payload.vault_id,
        "cluster_id": payload.cluster_id,
        "title": payload.title,
        "source_type": payload.source_type,
        "state": "indexed" if payload.raw_text else "waiting",
        "original_path": payload.original_path,
        "url": payload.url,
        "raw_text": payload.raw_text,
        "extracted_text": payload.raw_text,
        "summary": "",
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        if payload.cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ?",
                (payload.cluster_id,),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(
            """
            INSERT INTO sources (
                id, vault_id, cluster_id, title, source_type, state, original_path, url,
                raw_text, extracted_text, summary, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path, :url,
                :raw_text, :extracted_text, :summary, :created_at, :updated_at
            )
            """,
            source,
        )
    return source


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return dict_from_row(row)


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(source_id: str, payload: SourceUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if "raw_text" in updates and "extracted_text" not in updates:
        updates["extracted_text"] = updates["raw_text"]
    if not updates:
        return get_source(source_id)

    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    params = {"id": source_id, **updates}
    with connect() as conn:
        existing = conn.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Source not found")
        if updates.get("cluster_id"):
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ?",
                (updates["cluster_id"],),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(f"UPDATE sources SET {assignments} WHERE id = :id", params)
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return dict_from_row(row)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Source not found")
