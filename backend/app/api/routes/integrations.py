import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, utc_now
from backend.app.core.local_integrations import (
    MAX_SCAN_LIMIT,
    WATCHED_FOLDER_SCAN_LIMIT,
    scan_local_folder,
    watched_folder_limits,
)
from backend.app.core.reconciliation_log import (
    append_reconciliation_item,
    compact_reconciliation_logs,
    create_reconciliation_run,
    finish_reconciliation_run,
    item_from_row,
    list_reconciliation_items,
    list_reconciliation_runs,
    load_reconciliation_item,
    run_from_row,
)
from backend.app.core.database import dict_from_row
from backend.app.api.routes.sources import _create_source_record, delete_source
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.embeddings import require_embeddings_available
from backend.app.core.encrypted_storage import update_source_content_fields
from backend.app.core.cluster_lifecycle import mark_cluster_needs_update
from backend.app.core.extraction import ExtractionError, extract_pages_from_path
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.core.retrieval_cache import invalidate_caches_for_source
from backend.app.core.source_records import file_checksum, replace_source_pages, source_type_for_suffix
from backend.app.schemas import (
    AppJobRead,
    IntegrationImportRead,
    IntegrationImportUpdate,
    LocalFolderScanRequest,
    LocalFolderScanResponse,
    ReconciliationItemPageRead,
    ReconciliationItemRetryResponse,
    ReconciliationRunRead,
    SourceCreate,
)
from uuid import uuid4

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/imports", response_model=list[IntegrationImportRead])
def list_integration_imports(
    vault_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(offset, 0)
    with connect() as conn:
        params: list[object] = []
        where = ""
        if vault_id:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                raise HTTPException(status_code=404, detail="Vault not found")
            where = "WHERE vault_id = ?"
            params.append(vault_id)
        params.extend([safe_limit, safe_offset])
        rows = conn.execute(
            f"""
            SELECT integration_imports.*,
                   (
                       SELECT rr.id
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ) AS last_reconciliation_run_id,
                   (
                       SELECT rr.status
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ) AS last_reconciliation_status,
                   (
                       SELECT rr.trigger_source
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ) AS last_reconciliation_trigger_source,
                   (
                       SELECT rr.finished_at
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ) AS last_reconciliation_finished_at,
                   COALESCE((
                       SELECT rr.detail_count
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ), 0) AS last_reconciliation_detail_count,
                   COALESCE((
                       SELECT rr.retryable_failed_count
                       FROM reconciliation_runs rr
                       WHERE rr.import_id = integration_imports.id
                       ORDER BY rr.created_at DESC
                       LIMIT 1
                   ), 0) AS last_reconciliation_retryable_failed_count
            FROM integration_imports
            {where}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
    return [_import_from_row(row) for row in rows]


@router.get("/watched-folder/limits")
def get_watched_folder_limits() -> dict:
    return watched_folder_limits()


@router.patch("/imports/{import_id}", response_model=IntegrationImportRead)
def update_integration_import(import_id: str, payload: IntegrationImportUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        with connect() as conn:
            row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Integration import not found")
        return _import_from_row(row)

    watch_enabled = updates.get("watch_enabled")
    interval = updates.get("watch_interval_seconds")
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Integration import not found")
        next_watch_at = None
        if watch_enabled is True:
            next_watch_at = now
        elif watch_enabled is None and int(row["watch_enabled"] or 0) == 1:
            next_watch_at = row["next_watch_at"] or now
        conn.execute(
            """
            UPDATE integration_imports
            SET watch_enabled = COALESCE(?, watch_enabled),
                watch_interval_seconds = COALESCE(?, watch_interval_seconds),
                next_watch_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                None if watch_enabled is None else int(watch_enabled),
                interval,
                next_watch_at,
                now,
                import_id,
            ),
        )
        updated = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
    return _import_from_row(updated)


@router.get("/imports/{import_id}/reconciliation-runs", response_model=list[ReconciliationRunRead])
def list_import_reconciliation_runs(import_id: str, limit: int = 10) -> list[dict]:
    with connect() as conn:
        row = conn.execute("SELECT id FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Integration import not found")
        return list_reconciliation_runs(conn, import_id=import_id, limit=limit)


@router.get("/reconciliation-runs/{run_id}/items", response_model=ReconciliationItemPageRead)
def list_import_reconciliation_items(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    result: str | None = None,
) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reconciliation_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Reconciliation run not found")
        items, total = list_reconciliation_items(conn, run_id=run_id, limit=limit, offset=offset, result=result)
    return {
        "run_id": run_id,
        "items": items,
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(offset, 0),
    }


@router.post("/reconciliation-items/{item_id}/retry", response_model=ReconciliationItemRetryResponse)
def retry_import_reconciliation_item(item_id: str) -> dict:
    with connect() as conn:
        item = load_reconciliation_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Reconciliation item not found")
        run_row = conn.execute("SELECT * FROM reconciliation_runs WHERE id = ?", (item["run_id"],)).fetchone()
        import_row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (item["import_id"],)).fetchone()
    if run_row is None or import_row is None:
        raise HTTPException(status_code=404, detail="Reconciliation context not found")
    if not item["retryable"] or item["result"] != "failed":
        raise HTTPException(status_code=400, detail="Reconciliation item is not retryable")

    action = str(item["action"])
    detail = item.get("detail") or {}
    if action == "scan":
        refreshed = refresh_integration_import(
            import_row["id"],
            import_files=bool(run_row["import_files"]),
            tombstone_missing=bool(run_row["tombstone_missing"]),
            trigger_source="retry_item",
        )
        run_id = refreshed.get("reconciliation_run_id")
        if not run_id:
            raise HTTPException(status_code=500, detail="Retry did not create reconciliation run")
        with connect() as conn:
            new_run_row = conn.execute("SELECT * FROM reconciliation_runs WHERE id = ?", (run_id,)).fetchone()
            latest_item_row = conn.execute(
                """
                SELECT *
                FROM reconciliation_items
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            new_item = item_from_row(conn, latest_item_row) if latest_item_row is not None else None
        return {
            "retried_item_id": item_id,
            "new_run": run_from_row(new_run_row),
            "new_item": new_item,
        }

    file_path = str(detail.get("path") or item["item_reference"] or "")
    if not file_path:
        raise HTTPException(status_code=400, detail="Reconciliation item is missing retry path")
    new_run, new_item = _retry_reconciliation_file_item(
        import_row=import_row,
        file_path=file_path,
        action=action,
    )
    return {
        "retried_item_id": item_id,
        "new_run": new_run,
        "new_item": new_item,
    }


@router.post("/imports/{import_id}/refresh/jobs", response_model=AppJobRead, status_code=202)
def queue_integration_refresh(
    import_id: str,
    import_files: bool = False,
    tombstone_missing: bool = False,
) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT id, vault_id FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Integration import not found")
        return enqueue_job(
            conn,
            job_type="integration_refresh",
            payload={
                "import_id": import_id,
                "import_files": import_files,
                "tombstone_missing": tombstone_missing,
                "trigger_source": "manual_refresh",
            },
            dedupe_key=f"integration-refresh:{import_id}",
            scope_id=str(row["vault_id"] or import_id),
            user_initiated=True,
        )


@router.post("/imports/{import_id}/refresh", response_model=LocalFolderScanResponse)
def refresh_integration_import(
    import_id: str,
    import_files: bool = False,
    tombstone_missing: bool = False,
    trigger_source: str = "manual_refresh",
    scan_limit: int | None = None,
) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Integration import not found")
    run_id: str | None = None
    if import_files:
        if not row["vault_id"]:
            raise HTTPException(status_code=400, detail="Import refresh cannot ingest without a vault")
        with connect() as conn:
            run_id = create_reconciliation_run(
                conn,
                vault_id=row["vault_id"],
                import_id=import_id,
                trigger_source=trigger_source,
                root_path=row["root_path"],
                import_files=import_files,
                tombstone_missing=tombstone_missing,
            )
    try:
        resolved_scan_limit = _bounded_scan_limit(scan_limit)
        if resolved_scan_limit is None:
            resolved_scan_limit = _refresh_scan_limit(row, trigger_source=trigger_source)
        result = scan_local_folder(row["root_path"], resolved_scan_limit)
    except OSError as exc:
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                UPDATE integration_imports
                SET status = 'error', updated_at = ?
                WHERE id = ?
                """,
                (now, import_id),
            )
            if run_id and row["vault_id"]:
                append_reconciliation_item(
                    conn,
                    run_id=run_id,
                    vault_id=row["vault_id"],
                    import_id=import_id,
                    item_reference=row["root_path"],
                    action="scan",
                    result="failed",
                    error=_failure_detail(exc),
                    retryable=True,
                    detail={"path": row["root_path"], "scope": "root_scan"},
                )
                finish_reconciliation_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    counts=_empty_reconcile_result(),
                )
                compact_reconciliation_logs(conn)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reconcile = _empty_reconcile_result()
    if import_files:
        try:
            reconcile = _reconcile_import_sources(
                vault_id=row["vault_id"],
                import_id=import_id,
                run_id=run_id,
                root_path=row["root_path"],
                supported_files=result["supported_files"],
                tombstone_missing=tombstone_missing,
            )
        except HTTPException as exc:
            if run_id and row["vault_id"]:
                with connect() as conn:
                    append_reconciliation_item(
                        conn,
                        run_id=run_id,
                        vault_id=row["vault_id"],
                        import_id=import_id,
                        item_reference=row["root_path"],
                        action="scan",
                        result="failed",
                        error=_failure_detail(exc),
                        retryable=exc.status_code in (400, 409),
                        detail={"path": row["root_path"], "scope": "preflight"},
                    )
                    finish_reconciliation_run(
                        conn,
                        run_id=run_id,
                        status="failed",
                        counts=reconcile,
                    )
                    compact_reconciliation_logs(conn)
            raise

    now = utc_now()
    next_watch_at = _next_watch_at(row, now) if int(row["watch_enabled"] or 0) == 1 else None
    with connect() as conn:
        conn.execute(
            """
            UPDATE integration_imports
            SET integration_type = ?, status = 'scanned', supported_count = ?, skipped_count = ?,
                truncated = ?, imported_count = ?, updated_count = ?, moved_count = ?,
                unchanged_count = ?, tombstoned_count = ?, failed_count = ?,
                last_failures = ?, last_scan_at = ?, last_import_at = ?,
                next_watch_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                result["integration_type"],
                result["supported_count"],
                result["skipped_count"],
                1 if result["truncated"] else 0,
                reconcile["imported_count"],
                reconcile["updated_count"],
                reconcile["moved_count"],
                reconcile["unchanged_count"],
                reconcile["tombstoned_count"],
                reconcile["failed_count"],
                json.dumps(reconcile["failures"][:25]),
                now,
                now if import_files else row["last_import_at"],
                next_watch_at,
                now,
                import_id,
            ),
        )
        if run_id and row["vault_id"]:
            finish_reconciliation_run(
                conn,
                run_id=run_id,
                status=_run_status_for_counts(reconcile),
                counts=reconcile,
            )
            compact_reconciliation_logs(conn)
    return {"import_id": import_id, "reconciliation_run_id": run_id, **result, **reconcile}


@router.post("/local-folder/scan", response_model=LocalFolderScanResponse)
def scan_local_folder_integration(payload: LocalFolderScanRequest) -> dict:
    try:
        result = scan_local_folder(payload.path, payload.max_files)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import_id = None
    if payload.vault_id:
        now = utc_now()
        import_id = f"integration-{uuid4()}"
        with connect() as conn:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
            if vault is None:
                raise HTTPException(status_code=404, detail="Vault not found")
            conn.execute(
                """
                INSERT INTO integration_imports (
                    id, vault_id, integration_type, root_path, status, supported_count,
                    skipped_count, truncated, last_scan_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'scanned', ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    payload.vault_id,
                    result["integration_type"],
                    result["path"],
                    result["supported_count"],
                    result["skipped_count"],
                    1 if result["truncated"] else 0,
                    now,
                    now,
                    now,
                ),
            )
    return {"import_id": import_id, **result}


def _import_from_row(row) -> dict:
    record = dict_from_row(row)
    record["truncated"] = bool(record["truncated"])
    record["watch_enabled"] = bool(record.get("watch_enabled"))
    record["last_reconciliation_detail_count"] = int(record.get("last_reconciliation_detail_count") or 0)
    record["last_reconciliation_retryable_failed_count"] = int(record.get("last_reconciliation_retryable_failed_count") or 0)
    raw_failures = record.get("last_failures") or "[]"
    try:
        failures = json.loads(raw_failures)
    except json.JSONDecodeError:
        failures = []
    record["last_failures"] = failures if isinstance(failures, list) else []
    return record


def _empty_reconcile_result() -> dict:
    return {
        "imported_count": 0,
        "updated_count": 0,
        "moved_count": 0,
        "unchanged_count": 0,
        "tombstoned_count": 0,
        "failed_count": 0,
        "failures": [],
    }


def _refresh_scan_limit(row, *, trigger_source: str) -> int:
    if trigger_source in {"manual_refresh", "retry_item"}:
        return MAX_SCAN_LIMIT

    supported_count = int(row["supported_count"] or 0)
    imported_count = int(row["imported_count"] or 0)
    base_limit = max(WATCHED_FOLDER_SCAN_LIMIT, supported_count, imported_count)
    if bool(row["truncated"]):
        base_limit = max(base_limit, supported_count + 500, imported_count + 500)
    return max(1, min(base_limit, MAX_SCAN_LIMIT))


def _bounded_scan_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    return max(1, min(int(limit), MAX_SCAN_LIMIT))


def _reconcile_import_sources(
    *,
    vault_id: str,
    import_id: str,
    run_id: str | None,
    root_path: str,
    supported_files: list[str],
    tombstone_missing: bool,
) -> dict:
    try:
        require_embeddings_available("Local folder import")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    root = Path(root_path).expanduser()
    seen_paths = {_normalize_path(path) for path in supported_files}
    result = _empty_reconcile_result()
    active_source_ids: set[str] = set()
    log_entries: list[dict] = []

    with connect() as conn:
        existing_rows = conn.execute(
            """
            SELECT * FROM sources
            WHERE vault_id = ? AND original_path IS NOT NULL AND deleted_at IS NULL
            """,
            (vault_id,),
        ).fetchall()
        existing_for_root = [
            row for row in existing_rows
            if _is_path_within_root(row["original_path"], root)
        ]
        by_path = {_normalize_path(row["original_path"]): row for row in existing_for_root}
        by_checksum = {
            row["checksum"]: row
            for row in existing_for_root
            if row["checksum"]
        }

    for file_path in supported_files:
        try:
            outcome = _reconcile_single_supported_file(
                vault_id=vault_id,
                file_path=file_path,
                by_path=by_path,
                by_checksum=by_checksum,
                seen_paths=seen_paths,
            )
            existing_source_id = outcome.get("source_id")
            if existing_source_id:
                active_source_ids.add(str(existing_source_id))
            result[_count_key_for_action(outcome["action"])] += 1
            if run_id:
                log_entries.append(
                    {
                        "item_reference": file_path,
                        "action": outcome["action"],
                        "result": "success",
                        "detail": outcome["detail"],
                    }
                )
        except (ExtractionError, OSError, HTTPException) as exc:
            result["failed_count"] += 1
            result["failures"].append({"path": file_path, "error": _failure_detail(exc)})
            if run_id:
                log_entries.append(
                    {
                        "item_reference": file_path,
                        "action": "scan_file",
                        "result": "failed",
                        "error": _failure_detail(exc),
                        "retryable": True,
                        "detail": {"path": file_path, "error_type": exc.__class__.__name__},
                    }
                )

    if tombstone_missing:
        for row in existing_for_root:
            if row["id"] in active_source_ids:
                continue
            original_path = _normalize_path(row["original_path"])
            if original_path not in seen_paths:
                delete_source(row["id"])
                result["tombstoned_count"] += 1
                if run_id:
                    log_entries.append(
                        {
                            "item_reference": row["original_path"],
                            "action": "tombstone",
                            "result": "success",
                            "detail": {"path": row["original_path"], "source_id": row["id"]},
                        }
                    )

    if run_id and log_entries:
        with connect() as conn:
            for entry in log_entries:
                append_reconciliation_item(
                    conn,
                    run_id=run_id,
                    vault_id=vault_id,
                    import_id=import_id,
                    item_reference=entry["item_reference"],
                    action=entry["action"],
                    result=entry["result"],
                    error=str(entry.get("error") or ""),
                    retryable=bool(entry.get("retryable")),
                    detail=entry.get("detail"),
                )

    return result


def _create_source_from_local_file(*, vault_id: str, file_path: str, checksum: str) -> str:
    title, pages = extract_pages_from_path(file_path)
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    created = _create_source_record(
        SourceCreate(
            vault_id=vault_id,
            title=title,
            source_type=source_type_for_suffix(Path(file_path).suffix.lower()),
            original_path=file_path,
            checksum=checksum,
            raw_text=text,
        ),
        page_texts=pages,
        dedupe_checksum=False,
    )
    return created["id"]


def _update_source_path(source_id: str, file_path: str) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE sources
            SET original_path = ?, title = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (file_path, Path(file_path).name, now, source_id),
        )
        invalidate_caches_for_source(source_id, conn=conn)


def _update_source_from_local_file(existing, *, file_path: str, checksum: str) -> None:
    title, pages = extract_pages_from_path(file_path)
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    now = utc_now()
    tags = generate_tags(title, text, source_type_for_suffix(Path(file_path).suffix.lower()))
    with connect() as conn:
        stored_updates = update_source_content_fields(
            conn,
            vault_id=existing["vault_id"],
            source_id=existing["id"],
            updates={
                "raw_text": text,
                "extracted_text": text,
                "summary": summarize_text(text),
                "tags": json.dumps(tags),
            },
            now=now,
        )
        conn.execute(
            """
            UPDATE sources
            SET title = ?, source_type = ?, state = 'indexed', original_path = ?,
                checksum = ?, raw_text = ?, extracted_text = ?, summary = ?,
                tags = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                title,
                source_type_for_suffix(Path(file_path).suffix.lower()),
                file_path,
                checksum,
                stored_updates["raw_text"],
                stored_updates["extracted_text"],
                stored_updates["summary"],
                stored_updates["tags"],
                now,
                existing["id"],
            ),
        )
        replace_source_pages(
            conn,
            source_id=existing["id"],
            vault_id=existing["vault_id"],
            page_texts=pages,
            now=now,
        )
        conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (existing["id"],))
        enqueue_job(
            conn,
            job_type="reindex_source",
            payload={"source_id": existing["id"]},
            dedupe_key=f"reindex-source:{existing['id']}",
        )
        mark_cluster_needs_update(conn, existing["cluster_id"], "Imported local file changed.")
        invalidate_caches_for_source(existing["id"], conn=conn)


def _reconcile_single_supported_file(
    *,
    vault_id: str,
    file_path: str,
    by_path: dict[str, object],
    by_checksum: dict[str, object],
    seen_paths: set[str] | None = None,
) -> dict:
    normalized = _normalize_path(file_path)
    checksum = file_checksum(Path(file_path))
    existing = by_path.get(normalized)
    moved = False
    if existing is None:
        checksum_match = by_checksum.get(checksum)
        if checksum_match is not None and _should_treat_checksum_match_as_move(checksum_match, seen_paths=seen_paths):
            existing = checksum_match
            moved = True

    if existing is None:
        source_id = _create_source_from_local_file(vault_id=vault_id, file_path=file_path, checksum=checksum)
        return {
            "action": "import",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    source_id = str(existing["id"])
    if moved:
        _update_source_path(existing["id"], file_path)
        by_path[normalized] = existing
        return {
            "action": "move",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    if existing["checksum"] == checksum:
        return {
            "action": "unchanged",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    _update_source_from_local_file(existing, file_path=file_path, checksum=checksum)
    return {
        "action": "update",
        "source_id": source_id,
        "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
    }


def _retry_reconciliation_file_item(*, import_row, file_path: str, action: str) -> tuple[dict, dict | None]:
    with connect() as conn:
        run_id = create_reconciliation_run(
            conn,
            vault_id=import_row["vault_id"],
            import_id=import_row["id"],
            trigger_source="retry_item",
            root_path=import_row["root_path"],
            import_files=True,
            tombstone_missing=False,
        )
    counts = _empty_reconcile_result()
    try:
        with connect() as conn:
            existing_rows = conn.execute(
                """
                SELECT *
                FROM sources
                WHERE vault_id = ? AND original_path IS NOT NULL AND deleted_at IS NULL
                """,
                (import_row["vault_id"],),
            ).fetchall()
        root = Path(import_row["root_path"]).expanduser()
        existing_for_root = [row for row in existing_rows if _is_path_within_root(row["original_path"], root)]
        by_path = {_normalize_path(row["original_path"]): row for row in existing_for_root}
        by_checksum = {row["checksum"]: row for row in existing_for_root if row["checksum"]}
        outcome = _reconcile_single_supported_file(
            vault_id=import_row["vault_id"],
            file_path=file_path,
            by_path=by_path,
            by_checksum=by_checksum,
        )
        counts[_count_key_for_action(outcome["action"])] += 1
        with connect() as conn:
            item_id = append_reconciliation_item(
                conn,
                run_id=run_id,
                vault_id=import_row["vault_id"],
                import_id=import_row["id"],
                item_reference=file_path,
                action=outcome["action"],
                result="success",
                detail={**outcome["detail"], "retried_from_action": action},
            )
            finish_reconciliation_run(conn, run_id=run_id, status=_run_status_for_counts(counts), counts=counts)
            compact_reconciliation_logs(conn)
            run_row = conn.execute("SELECT * FROM reconciliation_runs WHERE id = ?", (run_id,)).fetchone()
            item_row = conn.execute("SELECT * FROM reconciliation_items WHERE id = ?", (item_id,)).fetchone()
            return run_from_row(run_row), item_from_row(conn, item_row)
    except (ExtractionError, OSError, HTTPException) as exc:
        with connect() as conn:
            item_id = append_reconciliation_item(
                conn,
                run_id=run_id,
                vault_id=import_row["vault_id"],
                import_id=import_row["id"],
                item_reference=file_path,
                action=action,
                result="failed",
                error=_failure_detail(exc),
                retryable=True,
                detail={"path": file_path, "error_type": exc.__class__.__name__, "retried_from_action": action},
            )
            counts["failed_count"] = 1
            finish_reconciliation_run(conn, run_id=run_id, status="failed", counts=counts)
            compact_reconciliation_logs(conn)
            run_row = conn.execute("SELECT * FROM reconciliation_runs WHERE id = ?", (run_id,)).fetchone()
            item_row = conn.execute("SELECT * FROM reconciliation_items WHERE id = ?", (item_id,)).fetchone()
            return run_from_row(run_row), item_from_row(conn, item_row)


def _count_key_for_action(action: str) -> str:
    return {
        "import": "imported_count",
        "update": "updated_count",
        "move": "moved_count",
        "unchanged": "unchanged_count",
        "tombstone": "tombstoned_count",
    }.get(action, "unchanged_count")


def _run_status_for_counts(counts: dict) -> str:
    failed_count = int(counts.get("failed_count") or 0)
    if failed_count > 0:
        succeeded = sum(int(counts.get(key) or 0) for key in (
            "imported_count",
            "updated_count",
            "moved_count",
            "unchanged_count",
            "tombstoned_count",
        ))
        return "completed_with_failures" if succeeded > 0 else "failed"
    return "completed"


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve()).casefold()


def _is_path_within_root(path: str, root: Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _failure_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _next_watch_at(row, now: str) -> str:
    try:
        interval = max(60, int(row["watch_interval_seconds"] or 900))
        current = datetime.fromisoformat(now)
    except (TypeError, ValueError):
        current = datetime.now(UTC)
        interval = 900
    return (current + timedelta(seconds=interval)).isoformat()


def _should_treat_checksum_match_as_move(existing, *, seen_paths: set[str] | None) -> bool:
    original_path = str(existing["original_path"] or "").strip()
    if not original_path:
        return False
    normalized_original = _normalize_path(original_path)
    if seen_paths is not None and normalized_original in seen_paths:
        return False
    try:
        return not Path(original_path).expanduser().exists()
    except OSError:
        return False
