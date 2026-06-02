import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, utc_now
from backend.app.core.local_integrations import scan_local_folder
from backend.app.core.database import dict_from_row
from backend.app.api.routes.sources import (
    _create_source_record,
    _file_checksum,
    _replace_source_pages,
    _source_type_for_suffix,
    delete_source,
)
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.embeddings import require_embeddings_available
from backend.app.core.expert_lifecycle import mark_cluster_needs_update
from backend.app.core.extraction import ExtractionError, extract_pages_from_path
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.schemas import IntegrationImportRead, LocalFolderScanRequest, LocalFolderScanResponse, SourceCreate
from uuid import uuid4

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/imports", response_model=list[IntegrationImportRead])
def list_integration_imports(vault_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if vault_id:
            rows = conn.execute(
                """
                SELECT * FROM integration_imports
                WHERE vault_id = ?
                ORDER BY updated_at DESC
                LIMIT 50
                """,
                (vault_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM integration_imports
                ORDER BY updated_at DESC
                LIMIT 50
                """
            ).fetchall()
    return [_import_from_row(row) for row in rows]


@router.post("/imports/{import_id}/refresh", response_model=LocalFolderScanResponse)
def refresh_integration_import(
    import_id: str,
    import_files: bool = False,
    tombstone_missing: bool = False,
) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (import_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Integration import not found")
    try:
        result = scan_local_folder(row["root_path"], 500)
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reconcile = _empty_reconcile_result()
    if import_files:
        if not row["vault_id"]:
            raise HTTPException(status_code=400, detail="Import refresh cannot ingest without a vault")
        reconcile = _reconcile_import_sources(
            vault_id=row["vault_id"],
            root_path=row["root_path"],
            supported_files=result["supported_files"],
            tombstone_missing=tombstone_missing,
        )

    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE integration_imports
            SET integration_type = ?, status = 'scanned', supported_count = ?, skipped_count = ?,
                truncated = ?, imported_count = ?, updated_count = ?, moved_count = ?,
                unchanged_count = ?, tombstoned_count = ?, failed_count = ?,
                last_scan_at = ?, last_import_at = ?, updated_at = ?
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
                now,
                now if import_files else row["last_import_at"],
                now,
                import_id,
            ),
        )
    return {"import_id": import_id, **result, **reconcile}


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


def _reconcile_import_sources(
    *,
    vault_id: str,
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
        normalized = _normalize_path(file_path)
        try:
            checksum = _file_checksum(Path(file_path))
            existing = by_path.get(normalized)
            moved = False
            if existing is None:
                existing = by_checksum.get(checksum)
                moved = existing is not None

            if existing is None:
                _create_source_from_local_file(vault_id=vault_id, file_path=file_path, checksum=checksum)
                result["imported_count"] += 1
                continue

            active_source_ids.add(existing["id"])
            if moved:
                _update_source_path(existing["id"], file_path)
                result["moved_count"] += 1
                continue

            if existing["checksum"] == checksum:
                result["unchanged_count"] += 1
                continue

            _update_source_from_local_file(existing, file_path=file_path, checksum=checksum)
            result["updated_count"] += 1
        except (ExtractionError, OSError, HTTPException) as exc:
            result["failed_count"] += 1
            result["failures"].append({"path": file_path, "error": _failure_detail(exc)})

    if tombstone_missing:
        for row in existing_for_root:
            if row["id"] in active_source_ids:
                continue
            original_path = _normalize_path(row["original_path"])
            if original_path not in seen_paths:
                delete_source(row["id"])
                result["tombstoned_count"] += 1

    return result


def _create_source_from_local_file(*, vault_id: str, file_path: str, checksum: str) -> None:
    title, pages = extract_pages_from_path(file_path)
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    _create_source_record(
        SourceCreate(
            vault_id=vault_id,
            title=title,
            source_type=_source_type_for_suffix(Path(file_path).suffix.lower()),
            original_path=file_path,
            checksum=checksum,
            raw_text=text,
        ),
        page_texts=pages,
    )


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


def _update_source_from_local_file(existing, *, file_path: str, checksum: str) -> None:
    title, pages = extract_pages_from_path(file_path)
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    now = utc_now()
    tags = generate_tags(title, text, _source_type_for_suffix(Path(file_path).suffix.lower()))
    with connect() as conn:
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
                _source_type_for_suffix(Path(file_path).suffix.lower()),
                file_path,
                checksum,
                text,
                text,
                summarize_text(text),
                json.dumps(tags),
                now,
                existing["id"],
            ),
        )
        _replace_source_pages(
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
