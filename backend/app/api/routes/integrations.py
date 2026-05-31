from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, utc_now
from backend.app.core.local_integrations import scan_local_folder
from backend.app.schemas import LocalFolderScanRequest, LocalFolderScanResponse
from uuid import uuid4

router = APIRouter(prefix="/integrations", tags=["integrations"])


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
