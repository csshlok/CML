from uuid import uuid4
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.sql import build_update_assignments
from backend.app.schemas import VaultCreate, VaultRead, VaultUpdate

router = APIRouter(prefix="/vaults", tags=["vaults"])


@router.get("", response_model=list[VaultRead])
def list_vaults() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM vaults ORDER BY updated_at DESC").fetchall()
        return [dict_from_row(row) for row in rows]


@router.post("", response_model=VaultRead)
def create_vault(payload: VaultCreate) -> dict:
    now = utc_now()
    requested_path_key = _normalized_vault_path(payload.path)
    with connect() as conn:
        for row in conn.execute("SELECT * FROM vaults").fetchall():
            if _normalized_vault_path(str(row["path"])) == requested_path_key:
                return dict_from_row(row)
        vault = {
            "id": f"vault-{uuid4()}",
            "name": payload.name,
            "path": payload.path,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO vaults (id, name, path, created_at, updated_at)
            VALUES (:id, :name, :path, :created_at, :updated_at)
            """,
            vault,
        )
    return vault


@router.get("/{vault_id}", response_model=VaultRead)
def get_vault(vault_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    return dict_from_row(row)


@router.patch("/{vault_id}", response_model=VaultRead)
def update_vault(vault_id: str, payload: VaultUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_vault(vault_id)

    updates["updated_at"] = utc_now()
    with connect() as conn:
        existing = conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        if "path" in updates:
            requested_path_key = _normalized_vault_path(str(updates["path"]))
            for row in conn.execute("SELECT * FROM vaults WHERE id != ?", (vault_id,)).fetchall():
                if _normalized_vault_path(str(row["path"])) == requested_path_key:
                    raise HTTPException(status_code=409, detail="A library already uses this path.")
        assignments = build_update_assignments(updates, {"name", "path", "updated_at"})
        params = {"id": vault_id, **updates}
        conn.execute(f"UPDATE vaults SET {assignments} WHERE id = :id", params)
        row = conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    return dict_from_row(row)


@router.delete("/{vault_id}", status_code=204)
def delete_vault(vault_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM vaults WHERE id = ?", (vault_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Vault not found")


def _normalized_vault_path(path: str) -> str:
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        return os.path.normcase(str(resolved))
    except OSError:
        return os.path.normcase(str(path).strip())
