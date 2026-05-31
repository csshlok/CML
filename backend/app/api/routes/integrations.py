from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, utc_now
from backend.app.core.local_integrations import scan_local_folder
from backend.app.core.database import dict_from_row
from backend.app.schemas import IntegrationImportRead, LocalFolderScanRequest, LocalFolderScanResponse
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
def refresh_integration_import(import_id: str) -> dict:
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
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE integration_imports
            SET integration_type = ?, status = 'scanned', supported_count = ?, skipped_count = ?,
                truncated = ?, last_scan_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                result["integration_type"],
                result["supported_count"],
                result["skipped_count"],
                1 if result["truncated"] else 0,
                now,
                now,
                import_id,
            ),
        )
    return {"import_id": import_id, **result}


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
