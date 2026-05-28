import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.clustering import assign_or_create_cluster
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.extraction import ExtractionError, extract_text_from_path, extract_text_from_url
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.schemas import (
    SourceCreate,
    SourcePathCreate,
    SourceRead,
    SourceTextCreate,
    SourceUpdate,
    SourceUrlCreate,
)

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
        return [source_from_row(row) for row in rows]


@router.post("", response_model=SourceRead)
def create_source(payload: SourceCreate) -> dict:
    now = utc_now()
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        cluster_id = payload.cluster_id
        if cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ?",
                (cluster_id,),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="Cluster not found")
        elif payload.raw_text:
            cluster_id = assign_or_create_cluster(
                conn,
                vault_id=payload.vault_id,
                title=payload.title,
                text=payload.raw_text,
            )

        source = {
            "id": f"source-{uuid4()}",
            "vault_id": payload.vault_id,
            "cluster_id": cluster_id,
            "title": payload.title,
            "source_type": payload.source_type,
            "state": "indexed" if payload.raw_text else "waiting",
            "original_path": payload.original_path,
            "url": payload.url,
            "raw_text": payload.raw_text,
            "extracted_text": payload.raw_text,
            "summary": payload.summary
            if payload.summary is not None
            else summarize_text(payload.raw_text),
            "tags": json.dumps(
                payload.tags
                if payload.tags is not None
                else generate_tags(payload.title, payload.raw_text, payload.source_type),
            ),
            "cover_image_url": payload.cover_image_url,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO sources (
                id, vault_id, cluster_id, title, source_type, state, original_path, url,
                raw_text, extracted_text, summary, tags, cover_image_url, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path, :url,
                :raw_text, :extracted_text, :summary, :tags, :cover_image_url, :created_at, :updated_at
            )
            """,
            source,
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
        if row is not None and source["state"] == "indexed":
            reindex_source_chunks(conn, dict_from_row(row))
    return source_from_row(row)


@router.post("/from-path", response_model=SourceRead)
def create_source_from_path(payload: SourcePathCreate) -> dict:
    try:
        title, text = extract_text_from_path(payload.path)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return create_source(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=title,
            source_type="note" if title.lower().endswith((".md", ".markdown", ".txt")) else "file",
            original_path=payload.path,
            raw_text=text,
        )
    )


@router.post("/from-text", response_model=SourceRead)
def create_source_from_text(payload: SourceTextCreate) -> dict:
    return create_source(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=payload.title,
            source_type="note",
            raw_text=payload.text,
        )
    )


@router.post("/from-url", response_model=SourceRead)
def create_source_from_url(payload: SourceUrlCreate) -> dict:
    try:
        title, text, cover_image_url = extract_text_from_url(payload.url)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return create_source(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=title,
            source_type="link",
            url=payload.url,
            raw_text=text,
            cover_image_url=cover_image_url,
        )
    )


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source_from_row(row)


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(source_id: str, payload: SourceUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if "raw_text" in updates and "extracted_text" not in updates:
        updates["extracted_text"] = updates["raw_text"]
    if "raw_text" in updates and "summary" not in updates:
        updates["summary"] = summarize_text(updates["raw_text"])
    if "tags" in updates:
        updates["tags"] = json.dumps(updates["tags"])
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
        if row is not None and any(key in updates for key in {"cluster_id", "raw_text", "extracted_text", "state"}):
            source = dict_from_row(row)
            if source["state"] == "indexed":
                reindex_source_chunks(conn, source)
            else:
                conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
    return source_from_row(row)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Source not found")


def source_from_row(row) -> dict:
    source = dict_from_row(row)
    raw_tags = source.get("tags") or "[]"
    try:
        tags = json.loads(raw_tags)
    except json.JSONDecodeError:
        tags = []
    source["tags"] = tags if isinstance(tags, list) else []
    return source
