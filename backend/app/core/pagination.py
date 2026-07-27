import base64
import json

from fastapi import HTTPException


def encode_cursor(sort_value: str, item_id: str) -> str:
    payload = json.dumps([str(sort_value), str(item_id)], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    text = str(cursor).strip()
    if not text or len(text) > 2048:
        raise HTTPException(status_code=400, detail="invalid_cursor")
    try:
        padded = text + ("=" * (-len(text) % 4))
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid_cursor")
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) and 0 < len(item) <= 1024 for item in value)
    ):
        raise HTTPException(status_code=400, detail="invalid_cursor")
    return value[0], value[1]


def cursor_page(items: list[dict], *, requested_limit: int, sort_field: str, id_field: str = "id") -> dict:
    has_more = len(items) > requested_limit
    visible = items[:requested_limit]
    next_cursor = None
    if has_more and visible:
        next_cursor = encode_cursor(str(visible[-1][sort_field]), str(visible[-1][id_field]))
    return {
        "items": visible,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
