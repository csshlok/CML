import json
import os
import random
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
INTEGRATION_RECONCILE_BATCH_SIZE = 250
INTEGRATION_TOMBSTONE_BATCH_SIZE = 250


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
    scan_cycle_id = str(row["scan_cycle_id"] or "") or f"integration-scan-{uuid4()}"
    scan_phase = str(row["scan_phase"] or "discovery")
    if scan_phase not in {"discovery", "tombstone"}:
        scan_phase = "discovery"
    continuing_cycle = bool(row["scan_cycle_id"])
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
        if import_files:
            resolved_scan_limit = min(resolved_scan_limit, INTEGRATION_RECONCILE_BATCH_SIZE)
        if scan_phase == "tombstone" and continuing_cycle:
            result = {
                "path": row["root_path"],
                "integration_type": row["integration_type"],
                "supported_files": [],
                "supported_count": 0,
                "skipped_count": 0,
                "truncated": False,
                "backpressure_required": True,
                "scan_limit": resolved_scan_limit,
                "scan_cursor": "",
                "scan_complete": True,
            }
        else:
            result = scan_local_folder(
                row["root_path"],
                resolved_scan_limit,
                cursor=str(row["scan_cursor"] or "") if continuing_cycle else "",
            )
    except OSError as exc:
        now = utc_now()
        watched = int(row["watch_enabled"] or 0) == 1
        failure_count = int(row["watch_failure_count"] or 0) + 1 if watched else 0
        action_needed = watched and failure_count >= 5
        next_watch_at = (
            None
            if not watched or action_needed
            else _next_watch_failure_at(row, now, failure_count)
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE integration_imports
                SET status = ?, watch_failure_count = ?, watch_last_error = ?,
                    next_watch_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "action_needed" if action_needed else "error",
                    failure_count,
                    _failure_detail(exc)[:500],
                    next_watch_at,
                    now,
                    import_id,
                ),
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
                scan_cycle_id=scan_cycle_id,
                scan_complete=bool(result.get("scan_complete", not result["truncated"])),
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
    continuation_required = bool(
        result["truncated"] or reconcile.get("continuation_required")
    )
    next_scan_phase = (
        "tombstone"
        if bool(result.get("scan_complete", not result["truncated"]))
        and bool(reconcile.get("continuation_required"))
        else "discovery"
    )
    next_watch_at = None
    if int(row["watch_enabled"] or 0) == 1:
        next_watch_at = now if continuation_required else _next_watch_at(row, now)
    base_processed = int(row["scan_processed_count"] or 0) if continuing_cycle else 0
    base_supported = int(row["supported_count"] or 0) if continuing_cycle else 0
    base_skipped = int(row["skipped_count"] or 0) if continuing_cycle else 0
    base_imported = int(row["imported_count"] or 0) if continuing_cycle else 0
    base_updated = int(row["updated_count"] or 0) if continuing_cycle else 0
    base_moved = int(row["moved_count"] or 0) if continuing_cycle else 0
    base_unchanged = int(row["unchanged_count"] or 0) if continuing_cycle else 0
    base_tombstoned = int(row["tombstoned_count"] or 0) if continuing_cycle else 0
    base_failed = int(row["failed_count"] or 0) if continuing_cycle else 0
    with connect() as conn:
        conn.execute(
            """
            UPDATE integration_imports
            SET integration_type = ?, status = ?, supported_count = ?, skipped_count = ?,
                truncated = ?, imported_count = ?, updated_count = ?, moved_count = ?,
                unchanged_count = ?, tombstoned_count = ?, failed_count = ?,
                last_failures = ?, last_scan_at = ?, last_import_at = ?,
                next_watch_at = ?, scan_cursor = ?, scan_cycle_id = ?, scan_phase = ?,
                scan_processed_count = ?, watch_failure_count = 0, watch_last_error = '', updated_at = ?
            WHERE id = ?
            """,
            (
                result["integration_type"],
                "scanning" if continuation_required else "scanned",
                base_supported + int(result["supported_count"]),
                base_skipped + int(result["skipped_count"]),
                1 if continuation_required else 0,
                base_imported + int(reconcile["imported_count"]),
                base_updated + int(reconcile["updated_count"]),
                base_moved + int(reconcile["moved_count"]),
                base_unchanged + int(reconcile["unchanged_count"]),
                base_tombstoned + int(reconcile["tombstoned_count"]),
                base_failed + int(reconcile["failed_count"]),
                json.dumps(reconcile["failures"][:25]),
                now,
                now if import_files else row["last_import_at"],
                next_watch_at,
                str(result.get("scan_cursor") or "") if result["truncated"] else "",
                scan_cycle_id if continuation_required else "",
                next_scan_phase,
                base_processed + int(result["supported_count"]),
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
    return {
        "import_id": import_id,
        "reconciliation_run_id": run_id,
        **result,
        **reconcile,
        "continuation_required": continuation_required,
    }


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
    scan_cycle_id: str = "",
    scan_complete: bool = True,
) -> dict:
    try:
        require_embeddings_available("Local folder import")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    root = Path(root_path).expanduser()
    batch_seen_paths = {_normalize_path(path) for path in supported_files}
    seen_paths = set(batch_seen_paths)
    checksum_by_path: dict[str, str] = {}
    checksum_errors: dict[str, OSError] = {}
    for file_path in supported_files:
        try:
            checksum_by_path[file_path] = file_checksum(Path(file_path))
        except OSError as exc:
            checksum_errors[file_path] = exc
    result = _empty_reconcile_result()
    log_entries: list[dict] = []

    with connect() as conn:
        if scan_cycle_id:
            now = utc_now()
            conn.executemany(
                """
                INSERT OR IGNORE INTO integration_scan_seen (
                    import_id, cycle_id, normalized_path, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ((import_id, scan_cycle_id, item, now) for item in sorted(batch_seen_paths)),
            )
        escaped_root = str(root.resolve())
        escaped_like_root = (
            escaped_root.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        escaped_prefix = escaped_like_root.rstrip("\\/") + os.sep.replace("\\", "\\\\") + "%"
        candidate_paths = sorted(checksum_by_path)
        candidate_checksums = sorted(set(checksum_by_path.values()))
        candidate_parts: list[str] = []
        candidate_params: list[object] = []
        if candidate_paths:
            candidate_parts.append(f"original_path IN ({','.join('?' for _ in candidate_paths)})")
            candidate_params.extend(candidate_paths)
        if candidate_checksums:
            candidate_parts.append(f"checksum IN ({','.join('?' for _ in candidate_checksums)})")
            candidate_params.extend(candidate_checksums)
        existing_rows = []
        if candidate_parts:
            existing_rows = conn.execute(
                f"""
            SELECT * FROM sources
            WHERE vault_id = ? AND original_path IS NOT NULL AND deleted_at IS NULL
              AND (
                  import_root_path = ?
                  OR (import_root_path IS NULL AND (original_path = ? OR original_path LIKE ? ESCAPE '\'))
              )
              AND ({' OR '.join(candidate_parts)})
            ORDER BY CASE WHEN original_path IN ({','.join('?' for _ in candidate_paths)}) THEN 0 ELSE 1 END,
                     original_path, id
            LIMIT 750
                """,
                (
                    vault_id,
                    escaped_root,
                    escaped_root,
                    escaped_prefix,
                    *candidate_params,
                    *candidate_paths,
                ),
            ).fetchall()
        existing_for_root = [
            row for row in existing_rows
            if _is_path_within_root(row["original_path"], root)
        ]
        if scan_cycle_id and existing_for_root:
            possible_seen = sorted({_normalize_path(row["original_path"]) for row in existing_for_root})
            seen_rows = conn.execute(
                f"""
                SELECT normalized_path FROM integration_scan_seen
                WHERE import_id = ? AND cycle_id = ?
                  AND normalized_path IN ({','.join('?' for _ in possible_seen)})
                """,
                (import_id, scan_cycle_id, *possible_seen),
            ).fetchall()
            seen_paths.update(str(item["normalized_path"]) for item in seen_rows)
        by_path = {_normalize_path(row["original_path"]): row for row in existing_for_root}
        by_checksum = {
            row["checksum"]: row
            for row in existing_for_root
            if row["checksum"]
        }

    for file_path in supported_files:
        try:
            if file_path in checksum_errors:
                raise checksum_errors[file_path]
            outcome = _reconcile_single_supported_file(
                vault_id=vault_id,
                import_root_path=escaped_root,
                file_path=file_path,
                checksum=checksum_by_path[file_path],
                by_path=by_path,
                by_checksum=by_checksum,
                seen_paths=seen_paths,
            )
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

    tombstone_pending = False
    if tombstone_missing and scan_complete:
        missing_rows = _paged_missing_source_rows(
            vault_id=vault_id,
            import_id=import_id,
            scan_cycle_id=scan_cycle_id,
            root=root,
            escaped_root=escaped_root,
            escaped_prefix=escaped_prefix,
            fallback_seen_paths=seen_paths,
            limit=INTEGRATION_TOMBSTONE_BATCH_SIZE + 1,
        )
        tombstone_pending = len(missing_rows) > INTEGRATION_TOMBSTONE_BATCH_SIZE
        for row in missing_rows[:INTEGRATION_TOMBSTONE_BATCH_SIZE]:
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

    result["continuation_required"] = bool(not scan_complete or tombstone_pending)
    if scan_cycle_id and scan_complete and not tombstone_pending:
        with connect() as conn:
            conn.execute(
                "DELETE FROM integration_scan_seen WHERE import_id = ? AND cycle_id = ?",
                (import_id, scan_cycle_id),
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


def _create_source_from_local_file(
    *, vault_id: str, import_root_path: str, file_path: str, checksum: str
) -> str:
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
        import_root_path=import_root_path,
    )
    return created["id"]


def _update_source_path(source_id: str, file_path: str, import_root_path: str) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE sources
            SET original_path = ?, import_root_path = ?, title = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (file_path, import_root_path, Path(file_path).name, now, source_id),
        )
        invalidate_caches_for_source(source_id, conn=conn)


def _update_source_from_local_file(
    existing, *, import_root_path: str, file_path: str, checksum: str
) -> None:
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
            SET title = ?, source_type = ?, state = 'indexed', original_path = ?, import_root_path = ?,
                checksum = ?, raw_text = ?, extracted_text = ?, summary = ?,
                tags = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                title,
                source_type_for_suffix(Path(file_path).suffix.lower()),
                file_path,
                import_root_path,
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
    import_root_path: str,
    file_path: str,
    checksum: str | None = None,
    by_path: dict[str, object],
    by_checksum: dict[str, object],
    seen_paths: set[str] | None = None,
) -> dict:
    normalized = _normalize_path(file_path)
    checksum = checksum or file_checksum(Path(file_path))
    existing = by_path.get(normalized)
    moved = False
    if existing is None:
        checksum_match = by_checksum.get(checksum)
        if checksum_match is not None and _should_treat_checksum_match_as_move(checksum_match, seen_paths=seen_paths):
            existing = checksum_match
            moved = True

    if existing is None:
        source_id = _create_source_from_local_file(
            vault_id=vault_id,
            import_root_path=import_root_path,
            file_path=file_path,
            checksum=checksum,
        )
        return {
            "action": "import",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    source_id = str(existing["id"])
    if moved:
        _update_source_path(existing["id"], file_path, import_root_path)
        by_path[normalized] = existing
        return {
            "action": "move",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    if existing["checksum"] == checksum:
        if existing["import_root_path"] != import_root_path:
            _update_source_path(existing["id"], file_path, import_root_path)
        return {
            "action": "unchanged",
            "source_id": source_id,
            "detail": {"path": file_path, "checksum": checksum, "source_id": source_id},
        }

    _update_source_from_local_file(
        existing,
        import_root_path=import_root_path,
        file_path=file_path,
        checksum=checksum,
    )
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
        checksum = file_checksum(Path(file_path))
        with connect() as conn:
            root_text = str(Path(import_row["root_path"]).expanduser().resolve())
            escaped_like_root = root_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            escaped_prefix = escaped_like_root.rstrip("\\/") + os.sep.replace("\\", "\\\\") + "%"
            existing_rows = conn.execute(
                """
                SELECT *
                FROM sources
                WHERE vault_id = ? AND original_path IS NOT NULL AND deleted_at IS NULL
                  AND (
                      import_root_path = ?
                      OR (import_root_path IS NULL AND (original_path = ? OR original_path LIKE ? ESCAPE '\'))
                  )
                  AND (original_path = ? OR checksum = ?)
                ORDER BY CASE WHEN original_path = ? THEN 0 ELSE 1 END, original_path, id
                LIMIT 10
                """,
                (
                    import_row["vault_id"],
                    root_text,
                    root_text,
                    escaped_prefix,
                    file_path,
                    checksum,
                    file_path,
                ),
            ).fetchall()
        root = Path(import_row["root_path"]).expanduser()
        existing_for_root = [row for row in existing_rows if _is_path_within_root(row["original_path"], root)]
        by_path = {_normalize_path(row["original_path"]): row for row in existing_for_root}
        by_checksum = {row["checksum"]: row for row in existing_for_root if row["checksum"]}
        outcome = _reconcile_single_supported_file(
            vault_id=import_row["vault_id"],
            import_root_path=root_text,
            file_path=file_path,
            checksum=checksum,
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


def _paged_missing_source_rows(
    *,
    vault_id: str,
    import_id: str,
    scan_cycle_id: str,
    root: Path,
    escaped_root: str,
    escaped_prefix: str,
    fallback_seen_paths: set[str],
    limit: int,
) -> list[object]:
    """Find a bounded tombstone batch without materializing every source under a root."""
    missing: list[object] = []
    cursor_path = ""
    cursor_id = ""
    page_size = 500
    while len(missing) < limit:
        with connect() as conn:
            page = conn.execute(
                """
                SELECT * FROM sources
                WHERE vault_id = ? AND original_path IS NOT NULL AND deleted_at IS NULL
                  AND (
                      import_root_path = ?
                      OR (import_root_path IS NULL AND (original_path = ? OR original_path LIKE ? ESCAPE '\'))
                  )
                  AND (original_path > ? OR (original_path = ? AND id > ?))
                ORDER BY original_path, id
                LIMIT ?
                """,
                (
                    vault_id,
                    escaped_root,
                    escaped_root,
                    escaped_prefix,
                    cursor_path,
                    cursor_path,
                    cursor_id,
                    page_size,
                ),
            ).fetchall()
            if not page:
                break
            normalized_by_id = {
                str(row["id"]): _normalize_path(row["original_path"])
                for row in page
                if _is_path_within_root(row["original_path"], root)
            }
            cycle_seen: set[str] = set()
            normalized_values = sorted(set(normalized_by_id.values()))
            if scan_cycle_id and normalized_values:
                seen_rows = conn.execute(
                    f"""
                    SELECT normalized_path FROM integration_scan_seen
                    WHERE import_id = ? AND cycle_id = ?
                      AND normalized_path IN ({','.join('?' for _ in normalized_values)})
                    """,
                    (import_id, scan_cycle_id, *normalized_values),
                ).fetchall()
                cycle_seen = {str(item["normalized_path"]) for item in seen_rows}
        for row in page:
            normalized = normalized_by_id.get(str(row["id"]))
            if normalized is None:
                continue
            if normalized not in fallback_seen_paths and normalized not in cycle_seen:
                missing.append(row)
                if len(missing) >= limit:
                    break
        cursor_path = str(page[-1]["original_path"] or "")
        cursor_id = str(page[-1]["id"])
        if len(page) < page_size:
            break
    return missing


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


def _next_watch_failure_at(row, now: str, failure_count: int) -> str:
    try:
        base_interval = max(60, int(row["watch_interval_seconds"] or 900))
        current = datetime.fromisoformat(now)
    except (TypeError, ValueError):
        current = datetime.now(UTC)
        base_interval = 900
    delay = min(6 * 60 * 60, base_interval * (2 ** max(0, failure_count - 1)))
    jittered = int(delay * random.uniform(0.9, 1.1))
    return (current + timedelta(seconds=max(60, jittered))).isoformat()


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
