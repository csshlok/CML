import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.clustering import assign_or_create_cluster
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.database import connect, utc_now
from backend.app.core.embeddings import content_hash, require_embeddings_available
from backend.app.core.encrypted_storage import (
    delete_source_encrypted_content,
    mark_chat_citations_source_deleted,
    page_from_encrypted_row,
    source_from_encrypted_row,
    store_source_content_fields,
    update_source_content_fields,
)
from backend.app.core.cluster_lifecycle import mark_cluster_needs_update
from backend.app.core.extraction import ExtractionError, extract_text_from_url_with_security, link_extraction_diagnostics
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.core.network_security import strip_url_credentials
from backend.app.core.quarantine import attach_quarantine_record, ingest_file_through_quarantine
from backend.app.core.retrieval_cache import invalidate_caches_for_source
from backend.app.core.source_records import replace_source_pages, source_type_for_suffix
from backend.app.core.sql import build_update_assignments
from backend.app.core.turbovec_runtime import maybe_remove_source_chunks_from_sidecar
from backend.app.schemas import (
    SourceCreate,
    SourcePathCreate,
    SourcePageRead,
    SourceRead,
    SourceTextCreate,
    SourceUpdate,
    SourceUrlCreate,
)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
def list_sources(
    vault_id: str | None = None,
    cluster_id: str | None = None,
    unclustered: bool = False,
    states: str | None = None,
    source_types: str | None = None,
    q: str | None = None,
    order: str = "newest",
    limit: int = 500,
    offset: int = 0,
    include_content: bool = False,
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []
    if vault_id:
        clauses.append("vault_id = ?")
        params.append(vault_id)
    if cluster_id:
        clauses.append("cluster_id = ?")
        params.append(cluster_id)
    elif unclustered:
        clauses.append("cluster_id IS NULL")
    state_values = [item.strip() for item in (states or "").split(",") if item.strip()]
    if state_values:
        invalid_states = [item for item in state_values if item not in {"waiting", "processing", "indexed", "failed"}]
        if invalid_states:
            raise HTTPException(status_code=400, detail="Invalid source state filter")
        clauses.append(f"state IN ({','.join('?' for _ in state_values)})")
        params.extend(state_values)
    source_type_values = [item.strip() for item in (source_types or "").split(",") if item.strip()]
    if source_type_values:
        clauses.append(f"source_type IN ({','.join('?' for _ in source_type_values)})")
        params.extend(source_type_values)
    normalized_query = (q or "").strip().lower()
    if normalized_query:
        clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(source_type) LIKE ?)"
        )
        match = f"%{normalized_query}%"
        params.extend([match, match, match, match])

    clauses.append("deleted_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}"
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    order_clause = {
        "newest": "updated_at DESC, id DESC",
        "oldest": "updated_at ASC, id ASC",
        "alphabetical": "LOWER(title) ASC, id ASC",
    }.get(order)
    if order_clause is None:
        raise HTTPException(status_code=400, detail="Invalid source order")
    with connect() as conn:
        _validate_source_list_filters(conn, vault_id=vault_id, cluster_id=cluster_id)
        rows = conn.execute(
            f"SELECT * FROM sources {where} ORDER BY {order_clause} LIMIT ? OFFSET ?",
            [*params, safe_limit, safe_offset],
        ).fetchall()
        return [source_from_row(row, conn=conn, include_content=include_content) for row in rows]


@router.get("/count")
def count_sources(
    vault_id: str | None = None,
    cluster_id: str | None = None,
    unclustered: bool = False,
    states: str | None = None,
    source_types: str | None = None,
    q: str | None = None,
) -> dict:
    clauses = ["deleted_at IS NULL"]
    params: list[object] = []
    if vault_id:
        clauses.append("vault_id = ?")
        params.append(vault_id)
    if cluster_id:
        clauses.append("cluster_id = ?")
        params.append(cluster_id)
    elif unclustered:
        clauses.append("cluster_id IS NULL")
    state_values = [item.strip() for item in (states or "").split(",") if item.strip()]
    if state_values:
        invalid_states = [item for item in state_values if item not in {"waiting", "processing", "indexed", "failed"}]
        if invalid_states:
            raise HTTPException(status_code=400, detail="Invalid source state filter")
        clauses.append(f"state IN ({','.join('?' for _ in state_values)})")
        params.extend(state_values)
    source_type_values = [item.strip() for item in (source_types or "").split(",") if item.strip()]
    if source_type_values:
        clauses.append(f"source_type IN ({','.join('?' for _ in source_type_values)})")
        params.extend(source_type_values)
    normalized_query = (q or "").strip().lower()
    if normalized_query:
        clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(source_type) LIKE ?)"
        )
        match = f"%{normalized_query}%"
        params.extend([match, match, match, match])
    with connect() as conn:
        _validate_source_list_filters(conn, vault_id=vault_id, cluster_id=cluster_id)
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM sources WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
    return {"total": int(row["total"] or 0)}


@router.get("/counts-by-cluster")
def source_counts_by_cluster(vault_id: str) -> dict:
    with connect() as conn:
        _validate_source_list_filters(conn, vault_id=vault_id, cluster_id=None)
        rows = conn.execute(
            """
            SELECT cluster_id, state, COUNT(*) AS total
            FROM sources
            WHERE vault_id = ? AND deleted_at IS NULL
            GROUP BY cluster_id, state
            """,
            (vault_id,),
        ).fetchall()
    return {
        "items": [
            {"cluster_id": row["cluster_id"], "state": row["state"], "total": int(row["total"] or 0)}
            for row in rows
        ]
    }


@router.post("", response_model=SourceRead)
def create_source(payload: SourceCreate) -> dict:
    return _create_source_record(payload, page_texts=[payload.raw_text] if payload.raw_text else None)


def _create_source_record(
    payload: SourceCreate,
    page_texts: list[str] | None = None,
    *,
    dedupe_checksum: bool = False,
) -> dict:
    now = utc_now()
    raw_text = _sanitize_source_text(payload.raw_text)
    if page_texts:
        raw_text = _sanitize_source_text("\n\n".join(page for page in page_texts if page.strip()).strip())
    with connect() as conn:
        _validate_source_target(conn, payload.vault_id, payload.cluster_id)
        if payload.raw_text:
            try:
                require_embeddings_available("Source ingestion")
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        cluster_id = payload.cluster_id

        checksum = payload.checksum or (content_hash(raw_text) if raw_text else None)
        if checksum and dedupe_checksum:
            existing = None
            if payload.original_path:
                existing = conn.execute(
                    """
                    SELECT * FROM sources
                    WHERE vault_id = ? AND original_path = ? AND deleted_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (payload.vault_id, payload.original_path),
                ).fetchone()
            elif payload.url:
                existing = conn.execute(
                    """
                    SELECT * FROM sources
                    WHERE vault_id = ? AND url = ? AND deleted_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (payload.vault_id, payload.url),
                ).fetchone()
            if existing is not None:
                return source_from_row(existing, conn=conn)
        if cluster_id is None and raw_text:
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
            "checksum": checksum,
            "provenance": "local_import",
            "trust_tier": "trusted_local",
            "security_labels": "[]",
            "parser_security_json": "{}",
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
        stored_source = store_source_content_fields(conn, source, now=now)
        conn.execute(
            """
            INSERT INTO sources (
                id, vault_id, cluster_id, title, source_type, state, original_path, url,
                checksum, provenance, trust_tier, security_labels, parser_security_json,
                raw_text, extracted_text, summary, tags, cover_image_url, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path, :url,
                :checksum, :provenance, :trust_tier, :security_labels, :parser_security_json,
                :raw_text, :extracted_text, :summary, :tags, :cover_image_url, :created_at, :updated_at
            )
            """,
            stored_source,
        )
        if page_texts:
            replace_source_pages(
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
    with connect() as conn:
        _validate_source_target(conn, payload.vault_id, payload.cluster_id)
    try:
        ingested = ingest_file_through_quarantine(payload.vault_id, payload.path)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = ingested["title"]
    pages = ingested["pages"]
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    security = ingested["security"]

    suffix = Path(payload.path).suffix.lower()
    source_type = source_type_for_suffix(suffix)
    checksum = security["validation"]["content_hash"]
    now = utc_now()
    with connect() as conn:
        _validate_source_target(conn, payload.vault_id, payload.cluster_id)
        existing = conn.execute(
            """
            SELECT id, vault_id, cluster_id
            FROM sources
            WHERE vault_id = ? AND original_path = ? AND deleted_at IS NULL
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (payload.vault_id, payload.path),
        ).fetchone()
        created = existing is None
        if created:
            source = _create_source_record(
                SourceCreate(
                    vault_id=payload.vault_id,
                    cluster_id=payload.cluster_id,
                    title=title,
                    source_type=source_type,
                    original_path=payload.path,
                    checksum=checksum,
                    raw_text=text,
                    tags=security["security_labels"],
                ),
                page_texts=pages,
            )
            source_id = source["id"]
        else:
            source_id = str(existing["id"])
            target_cluster_id = payload.cluster_id if payload.cluster_id is not None else existing["cluster_id"]
            if target_cluster_id:
                cluster = conn.execute(
                    "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                    (target_cluster_id, payload.vault_id),
                ).fetchone()
                if cluster is None:
                    raise HTTPException(status_code=404, detail="Cluster not found")
            tags = json.dumps(security["security_labels"], sort_keys=True)
            stored_updates = update_source_content_fields(
                conn,
                vault_id=payload.vault_id,
                source_id=source_id,
                updates={
                    "cluster_id": target_cluster_id,
                    "title": title,
                    "source_type": source_type,
                    "state": "indexed",
                    "original_path": payload.path,
                    "checksum": checksum,
                    "raw_text": text,
                    "extracted_text": text,
                    "summary": summarize_text(text),
                    "tags": tags,
                },
                now=now,
            )
            conn.execute(
                """
                UPDATE sources
                SET cluster_id = ?,
                    title = ?,
                    source_type = ?,
                    state = 'indexed',
                    original_path = ?,
                    checksum = ?,
                    raw_text = ?,
                    extracted_text = ?,
                    summary = ?,
                    tags = ?,
                    provenance = ?,
                    trust_tier = ?,
                    security_labels = ?,
                    parser_security_json = ?,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    target_cluster_id,
                    title,
                    source_type,
                    payload.path,
                    checksum,
                    stored_updates["raw_text"],
                    stored_updates["extracted_text"],
                    stored_updates["summary"],
                    stored_updates["tags"],
                    security["provenance"],
                    security["trust_tier"],
                    tags,
                    json.dumps(security, sort_keys=True),
                    now,
                    source_id,
                ),
            )
            replace_source_pages(
                conn,
                source_id=source_id,
                vault_id=payload.vault_id,
                page_texts=pages,
                now=now,
            )
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": source_id},
                dedupe_key=f"reindex-source:{source_id}",
            )
            mark_cluster_needs_update(conn, existing["cluster_id"], "Source changed or moved.")
            mark_cluster_needs_update(conn, target_cluster_id, "Source changed or moved.")
            invalidate_caches_for_source(source_id, conn=conn)
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
                source_id,
            ),
        )
    attach_quarantine_record(ingested["quarantine_record_id"], source_id)
    result = get_source(source_id)
    result["import_outcome"] = "created" if created else "updated"
    return result


@router.post("/from-text", response_model=SourceRead)
def create_source_from_text(payload: SourceTextCreate) -> dict:
    text = _sanitize_source_text(payload.text)
    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text was provided")
    result = create_source(
        SourceCreate(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            title=payload.title,
            source_type="note",
            raw_text=text,
        )
    )
    result["import_outcome"] = "created"
    return result


@router.post("/from-url", response_model=SourceRead)
def create_source_from_url(payload: SourceUrlCreate) -> dict:
    sanitized_url = strip_url_credentials(payload.url)
    with connect() as conn:
        _validate_source_target(conn, payload.vault_id, payload.cluster_id)
    try:
        title, text, cover_image_url, security = extract_text_from_url_with_security(sanitized_url)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = utc_now()
    with connect() as conn:
        _validate_source_target(conn, payload.vault_id, payload.cluster_id)
        existing = conn.execute(
            """
            SELECT id, vault_id, cluster_id
            FROM sources
            WHERE vault_id = ? AND url = ? AND deleted_at IS NULL
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (payload.vault_id, sanitized_url),
        ).fetchone()
        created = existing is None
        if created:
            source = create_source(
                SourceCreate(
                    vault_id=payload.vault_id,
                    cluster_id=payload.cluster_id,
                    title=title,
                    source_type="link",
                    url=sanitized_url,
                    raw_text=text,
                    cover_image_url=cover_image_url,
                    tags=security["security_labels"],
                )
            )
            source_id = source["id"]
        else:
            source_id = str(existing["id"])
            target_cluster_id = payload.cluster_id if payload.cluster_id is not None else existing["cluster_id"]
            if target_cluster_id:
                cluster = conn.execute(
                    "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                    (target_cluster_id, payload.vault_id),
                ).fetchone()
                if cluster is None:
                    raise HTTPException(status_code=404, detail="Cluster not found")
            tags = json.dumps(security["security_labels"], sort_keys=True)
            stored_updates = update_source_content_fields(
                conn,
                vault_id=payload.vault_id,
                source_id=source_id,
                updates={
                    "cluster_id": target_cluster_id,
                    "title": title,
                    "state": "indexed",
                    "url": sanitized_url,
                    "raw_text": text,
                    "extracted_text": text,
                    "summary": summarize_text(text),
                    "tags": tags,
                    "cover_image_url": cover_image_url,
                },
                now=now,
            )
            conn.execute(
                """
                UPDATE sources
                SET cluster_id = ?,
                    title = ?,
                    source_type = 'link',
                    state = 'indexed',
                    url = ?,
                    raw_text = ?,
                    extracted_text = ?,
                    summary = ?,
                    tags = ?,
                    cover_image_url = ?,
                    provenance = ?,
                    trust_tier = ?,
                    security_labels = ?,
                    parser_security_json = ?,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    target_cluster_id,
                    title,
                    sanitized_url,
                    stored_updates["raw_text"],
                    stored_updates["extracted_text"],
                    stored_updates["summary"],
                    stored_updates["tags"],
                    cover_image_url,
                    security["provenance"],
                    security["trust_tier"],
                    tags,
                    json.dumps(security, sort_keys=True),
                    now,
                    source_id,
                ),
            )
            replace_source_pages(
                conn,
                source_id=source_id,
                vault_id=payload.vault_id,
                page_texts=[text] if text else [],
                now=now,
            )
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": source_id},
                dedupe_key=f"reindex-source:{source_id}",
            )
            mark_cluster_needs_update(conn, existing["cluster_id"], "Source changed or moved.")
            mark_cluster_needs_update(conn, target_cluster_id, "Source changed or moved.")
            invalidate_caches_for_source(source_id, conn=conn)
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
                source_id,
            ),
        )
    result = get_source(source_id)
    result["import_outcome"] = "created" if created else "updated"
    return result


@router.get("/link-diagnostics")
def get_link_diagnostics(url: str) -> dict:
    return link_extraction_diagnostics(url)


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return source_from_row(row, conn=conn)


@router.get("/{source_id}/pages", response_model=list[SourcePageRead])
def list_source_pages(source_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        source = conn.execute(
            "SELECT id FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        rows = conn.execute(
            """
            SELECT * FROM source_pages
            WHERE source_id = ?
            ORDER BY page_number ASC
            LIMIT ? OFFSET ?
            """,
            (source_id, safe_limit, safe_offset),
        ).fetchall()
        return [page_from_encrypted_row(conn, row) for row in rows]


@router.get("/{source_id}/stats")
def get_source_stats(source_id: str) -> dict:
    with connect() as conn:
        source = conn.execute(
            """
            SELECT id, original_path
            FROM sources
            WHERE id = ? AND deleted_at IS NULL
            """,
            (source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM source_pages WHERE source_id = ?) AS page_count,
                (SELECT COUNT(*) FROM source_chunks WHERE source_id = ?) AS chunk_count
            """,
            (source_id, source_id),
        ).fetchone()
        failed_job = conn.execute(
            """
            SELECT last_error
            FROM app_jobs
            WHERE scope_id = ? AND status = 'failed' AND last_error != ''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
    size_bytes = None
    original_path = str(source["original_path"] or "")
    if original_path:
        try:
            path = Path(original_path)
            if path.is_file() and not path.is_symlink():
                size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
    return {
        "source_id": source_id,
        "page_count": int(counts["page_count"] or 0),
        "chunk_count": int(counts["chunk_count"] or 0),
        "size_bytes": size_bytes,
        "last_error": str(failed_job["last_error"]) if failed_job is not None else None,
    }


@router.post("/{source_id}/reindex")
def reindex_source(source_id: str) -> dict:
    try:
        require_embeddings_available("Source reindexing")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with connect() as conn:
        source = conn.execute(
            """
            SELECT id, state, raw_text, extracted_text FROM sources
            WHERE id = ? AND state IN ('indexed', 'failed') AND deleted_at IS NULL
            """,
            (source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(status_code=409, detail="Only indexed or failed sources can be reindexed.")
        if source["state"] == "failed":
            if not str(source["extracted_text"] or source["raw_text"] or "").strip():
                raise HTTPException(
                    status_code=409,
                    detail="This source has no extracted content to retry. Remove it and import the original again.",
                )
            conn.execute(
                "UPDATE sources SET state = 'indexed', updated_at = ? WHERE id = ?",
                (utc_now(), source_id),
            )
        job = enqueue_job(
            conn,
            job_type="reindex_source",
            payload={"source_id": source_id},
            dedupe_key=f"reindex-source:{source_id}",
            scope_id=source_id,
            user_initiated=True,
        )
    return {"source_id": source_id, "job_id": job["id"], "status": job["status"]}


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(source_id: str, payload: SourceUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    for text_key in ("raw_text", "extracted_text"):
        if text_key in updates and updates[text_key] is not None:
            updates[text_key] = _sanitize_source_text(updates[text_key])
    if "raw_text" in updates and "extracted_text" not in updates:
        updates["extracted_text"] = updates["raw_text"]
    if "raw_text" in updates and "summary" not in updates:
        updates["summary"] = summarize_text(updates["raw_text"])
    if "tags" in updates:
        updates["tags"] = json.dumps(updates["tags"])
    if not updates:
        return get_source(source_id)

    updates["updated_at"] = utc_now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, vault_id, cluster_id FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Source not found")
        if updates.get("cluster_id"):
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (updates["cluster_id"], existing["vault_id"]),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="Cluster not found")
        stored_updates = update_source_content_fields(
            conn,
            vault_id=existing["vault_id"],
            source_id=source_id,
            updates=updates,
            now=updates["updated_at"],
        )
        assignments = build_update_assignments(
            stored_updates,
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
        params = {"id": source_id, **stored_updates}
        conn.execute(f"UPDATE sources SET {assignments} WHERE id = :id", params)
        if "raw_text" in updates or "extracted_text" in updates:
            text = str(updates.get("extracted_text") or updates.get("raw_text") or "")
            replace_source_pages(
                conn,
                source_id=source_id,
                vault_id=existing["vault_id"],
                page_texts=[text] if text else [],
                now=updates["updated_at"],
            )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None and any(key in updates for key in {"cluster_id", "raw_text", "extracted_text", "state"}):
            source = source_from_encrypted_row(conn, row)
            if source["state"] == "indexed":
                enqueue_job(
                    conn,
                    job_type="reindex_source",
                    payload={"source_id": source_id},
                    dedupe_key=f"reindex-source:{source_id}",
                )
            else:
                maybe_remove_source_chunks_from_sidecar(
                    conn,
                    source_id=source_id,
                    vault_id=existing["vault_id"],
                    rebuild_reason=f"source_state_change:{source_id}",
                )
                conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            mark_cluster_needs_update(conn, existing["cluster_id"], "Source changed or moved.")
            mark_cluster_needs_update(conn, source["cluster_id"], "Source changed or moved.")
            invalidate_caches_for_source(source_id, conn=conn)
        return source_from_row(row, conn=conn)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: str) -> None:
    now = utc_now()
    with connect() as conn:
        source = conn.execute(
            "SELECT id, vault_id, cluster_id FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        mark_chat_citations_source_deleted(
            conn,
            vault_id=str(source["vault_id"]),
            source_id=source_id,
            now=now,
        )
        delete_source_encrypted_content(conn, source_id=source_id, vault_id=source["vault_id"])
        result = conn.execute(
            """
            UPDATE sources
            SET state = 'deleted',
                deleted_at = ?,
                updated_at = ?,
                raw_text = '',
                extracted_text = '',
                summary = '',
                tags = '[]',
                cover_image_url = NULL,
                original_path = NULL,
                url = NULL,
                checksum = NULL
            WHERE id = ? AND deleted_at IS NULL
            """,
            (now, now, source_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Source not found")
        conn.execute(
            """
            UPDATE retrieval_snapshot_items
            SET state = 'source_deleted', source_id = NULL, chunk_id = NULL, page_id = NULL
            WHERE source_id = ? OR chunk_id IN (
                SELECT id FROM source_chunks WHERE source_id = ?
            ) OR page_id IN (
                SELECT id FROM source_pages WHERE source_id = ?
            )
            """,
            (source_id, source_id, source_id),
        )
        maybe_remove_source_chunks_from_sidecar(
            conn,
            source_id=source_id,
            vault_id=source["vault_id"],
            rebuild_reason=f"delete_source:{source_id}",
        )
        conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM chat_attachments WHERE source_id = ?", (source_id,))
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'cancelled', status_detail = 'Source was deleted.', completed_at = ?, updated_at = ?
            WHERE status IN ('queued', 'blocked_by_dependency', 'running')
                AND (
                    scope_id = ?
                    OR payload LIKE ?
                )
            """,
            (now, now, source_id, f'%"{source_id}"%'),
        )
        enqueue_job(
            conn,
            job_type="delete_source_cleanup",
            payload={"source_id": source_id},
            dedupe_key=f"delete-source-cleanup:{source_id}",
            scope_id=source_id,
            user_initiated=True,
        )
        mark_cluster_needs_update(conn, source["cluster_id"], "Source was deleted.")
        invalidate_caches_for_source(source_id, conn=conn)


def source_from_row(row, conn=None, *, include_content: bool = True) -> dict:
    if conn is not None:
        source = source_from_encrypted_row(conn, row, include_content=include_content)
    else:
        with connect() as local_conn:
            source = source_from_encrypted_row(local_conn, row, include_content=include_content)
    if not include_content:
        source["raw_text"] = ""
        source["extracted_text"] = ""
    raw_tags = source.get("tags") or "[]"
    try:
        tags = json.loads(raw_tags)
    except json.JSONDecodeError:
        tags = []
    source["tags"] = tags if isinstance(tags, list) else []
    return source


def _validate_source_target(conn, vault_id: str, cluster_id: str | None = None) -> None:
    vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    if cluster_id:
        cluster = conn.execute(
            "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
            (cluster_id, vault_id),
        ).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")


def _validate_source_list_filters(conn, *, vault_id: str | None, cluster_id: str | None) -> None:
    if vault_id:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
    if cluster_id:
        if vault_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, vault_id),
            ).fetchone()
        else:
            cluster = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")


def _sanitize_source_text(text: str) -> str:
    return text.replace("\x00", "")


