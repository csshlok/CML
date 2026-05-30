import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.clustering import assign_or_create_cluster
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import content_hash
from backend.app.core.expert_lifecycle import mark_cluster_needs_update
from backend.app.core.extraction import ExtractionError, extract_pages_from_path, extract_text_from_url
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.core.sql import build_update_assignments
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
    return _create_source_record(payload, page_texts=[payload.raw_text] if payload.raw_text else None)


def _create_source_record(payload: SourceCreate, page_texts: list[str] | None = None) -> dict:
    now = utc_now()
    raw_text = payload.raw_text
    if page_texts:
        raw_text = "\n\n".join(page for page in page_texts if page.strip()).strip()
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
        elif raw_text:
            cluster_id = assign_or_create_cluster(
                conn,
                vault_id=payload.vault_id,
                title=payload.title,
                text=raw_text,
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
            "raw_text": raw_text,
            "extracted_text": raw_text,
            "summary": payload.summary
            if payload.summary is not None
            else summarize_text(raw_text),
            "tags": json.dumps(
                payload.tags
                if payload.tags is not None
                else generate_tags(payload.title, raw_text, payload.source_type),
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
        if page_texts:
            _replace_source_pages(
                conn,
                source_id=source["id"],
                vault_id=source["vault_id"],
                page_texts=page_texts,
                now=now,
            )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
        if row is not None and source["state"] == "indexed":
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": source["id"]},
                dedupe_key=f"reindex-source:{source['id']}",
            )
    return source_from_row(row)


@router.post("/from-path", response_model=SourceRead)
def create_source_from_path(payload: SourcePathCreate) -> dict:
    try:
        title, pages = extract_pages_from_path(payload.path)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    text = "\n\n".join(page for page in pages if page.strip()).strip()

    return _create_source_record(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=title,
            source_type="note" if title.lower().endswith((".md", ".markdown", ".txt")) else "file",
            original_path=payload.path,
            raw_text=text,
        ),
        page_texts=pages,
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
    assignments = build_update_assignments(
        updates,
        {
            "cluster_id",
            "title",
            "state",
            "raw_text",
            "extracted_text",
            "summary",
            "tags",
            "cover_image_url",
            "updated_at",
        },
    )
    params = {"id": source_id, **updates}
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, vault_id, cluster_id FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
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
        if "raw_text" in updates or "extracted_text" in updates:
            text = str(updates.get("extracted_text") or updates.get("raw_text") or "")
            _replace_source_pages(
                conn,
                source_id=source_id,
                vault_id=existing["vault_id"],
                page_texts=[text] if text else [],
                now=updates["updated_at"],
            )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None and any(key in updates for key in {"cluster_id", "raw_text", "extracted_text", "state"}):
            source = dict_from_row(row)
            if source["state"] == "indexed":
                enqueue_job(
                    conn,
                    job_type="reindex_source",
                    payload={"source_id": source_id},
                    dedupe_key=f"reindex-source:{source_id}",
                )
            else:
                conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            mark_cluster_needs_update(conn, existing["cluster_id"], "Source changed or moved.")
            mark_cluster_needs_update(conn, source["cluster_id"], "Source changed or moved.")
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


def _replace_source_pages(conn, *, source_id: str, vault_id: str, page_texts: list[str], now: str) -> None:
    conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
    for index, text in enumerate(page_texts, start=1):
        page_text = (text or "").strip()
        if not page_text:
            continue
        conn.execute(
            """
            INSERT INTO source_pages (
                id, source_id, vault_id, page_number, raw_text, extraction_version,
                content_hash, created_at, updated_at
            )
            VALUES (
                :id, :source_id, :vault_id, :page_number, :raw_text, :extraction_version,
                :content_hash, :created_at, :updated_at
            )
            """,
            {
                "id": f"page-{uuid4()}",
                "source_id": source_id,
                "vault_id": vault_id,
                "page_number": index,
                "raw_text": page_text,
                "extraction_version": "v1",
                "content_hash": content_hash(page_text),
                "created_at": now,
                "updated_at": now,
            },
        )
