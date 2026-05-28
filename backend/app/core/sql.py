from collections.abc import Iterable

from fastapi import HTTPException


def build_update_assignments(updates: dict, allowed_columns: Iterable[str]) -> str:
    allowed = set(allowed_columns)
    unexpected = set(updates) - allowed
    if unexpected:
        raise HTTPException(status_code=400, detail="Unsupported update field")
    return ", ".join(f"{key} = :{key}" for key in updates)
