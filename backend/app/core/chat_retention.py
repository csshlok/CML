from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, utc_now


def paginated_messages(session_id: str, *, limit: int = 50, cursor: str | None = None) -> dict:
    safe_limit = max(1, min(limit, 100))
    params: list[object] = [session_id]
    cursor_clause = ""
    if cursor:
        cursor_created_at, cursor_id = _parse_message_cursor(cursor)
        cursor_clause = "AND (created_at > ? OR (created_at = ? AND id > ?))"
        params.extend([cursor_created_at, cursor_created_at, cursor_id])
    params.append(safe_limit + 1)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM chat_messages
            WHERE session_id = ?
            {cursor_clause}
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    items = [dict_from_row(row) for row in rows[:safe_limit]]
    next_cursor = None
    if len(rows) > safe_limit and items:
        next_cursor = _format_message_cursor(items[-1]["created_at"], items[-1]["id"])
    return {"session_id": session_id, "items": items, "next_cursor": next_cursor}


def _format_message_cursor(created_at: str, message_id: str) -> str:
    return f"{created_at}|{message_id}"


def _parse_message_cursor(cursor: str) -> tuple[str, str]:
    text = str(cursor or "").strip()
    if "|" not in text:
        # Backward compatibility with older timestamp-only cursors.
        return text, ""
    created_at, message_id = text.rsplit("|", 1)
    return created_at, message_id


def compact_retrieval_snapshots(*, message_id: str | None = None, keep_latest_per_message: int = 1) -> dict:
    safe_keep = max(1, min(keep_latest_per_message, 5))
    params: list[object] = []
    message_clause = ""
    if message_id:
        message_clause = "WHERE message_id = ?"
        params.append(message_id)
    now = utc_now()
    with connect() as conn:
        count_row = conn.execute(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY message_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rank_index
                FROM retrieval_snapshots
                {message_clause}
            )
            SELECT COUNT(*) AS count
            FROM ranked
            WHERE rank_index > ?
            """,
            [*params, safe_keep],
        ).fetchone()
        compacted = int(count_row["count"] or 0)
        if compacted:
            conn.execute(
                f"""
                WITH stale AS (
                    SELECT id
                    FROM (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY message_id
                                ORDER BY created_at DESC, id DESC
                            ) AS rank_index
                        FROM retrieval_snapshots
                        {message_clause}
                    )
                    WHERE rank_index > ?
                )
                UPDATE retrieval_snapshot_items
                SET chunk_id = NULL,
                    page_id = NULL,
                    short_snippet_excerpt = SUBSTR(short_snippet_excerpt, 1, 240),
                    state = CASE WHEN state = 'current' THEN 'compacted' ELSE state END
                WHERE snapshot_id IN (SELECT id FROM stale)
                """,
                [*params, safe_keep],
            )
            conn.execute(
                f"""
                WITH stale AS (
                    SELECT id
                    FROM (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY message_id
                                ORDER BY created_at DESC, id DESC
                            ) AS rank_index
                        FROM retrieval_snapshots
                        {message_clause}
                    )
                    WHERE rank_index > ?
                )
                UPDATE retrieval_snapshots
                SET retrieval_mode = retrieval_mode || ':compacted'
                WHERE id IN (SELECT id FROM stale)
                  AND retrieval_mode NOT LIKE '%:compacted'
                """,
                [*params, safe_keep],
            )
    return {"compacted_snapshots": compacted, "compacted_at": now}


def chat_evidence_retention_policy() -> dict:
    api_prefix = get_settings().api_prefix.rstrip("/") or "/api/v1"
    return {
        "default_keep_latest_snapshots_per_message": 1,
        "max_keep_latest_snapshots_per_message": 5,
        "default_excerpt_chars": 240,
        "deleted_source_state": "source_deleted",
        "compacted_state": "compacted",
        "query_cache_prune_endpoint": f"{api_prefix}/search/query-cache/prune",
    }


def enforce_chat_evidence_retention(
    *,
    message_id: str | None = None,
    keep_latest_per_message: int = 1,
    excerpt_chars: int = 240,
) -> dict:
    safe_keep = max(1, min(keep_latest_per_message, 5))
    safe_excerpt = max(80, min(excerpt_chars, 1000))
    compacted = compact_retrieval_snapshots(
        message_id=message_id,
        keep_latest_per_message=safe_keep,
    )
    tombstoned = 0
    trimmed = 0
    now = utc_now()
    message_clause = ""
    params: list[object] = []
    if message_id:
        message_clause = "AND snapshots.message_id = ?"
        params.append(message_id)
    with connect() as conn:
        tombstone_count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM retrieval_snapshot_items items
            JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
            LEFT JOIN sources ON sources.id = items.source_id
            WHERE items.source_id IS NOT NULL
              AND (sources.id IS NULL OR sources.deleted_at IS NOT NULL)
              {message_clause}
            """,
            params,
        ).fetchone()
        tombstoned = int(tombstone_count_row["count"] or 0)
        if tombstoned:
            conn.execute(
                f"""
                UPDATE retrieval_snapshot_items
                SET state = 'source_deleted', source_id = NULL, chunk_id = NULL, page_id = NULL
                WHERE id IN (
                    SELECT items.id
                    FROM retrieval_snapshot_items items
                    JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
                    LEFT JOIN sources ON sources.id = items.source_id
                    WHERE items.source_id IS NOT NULL
                      AND (sources.id IS NULL OR sources.deleted_at IS NOT NULL)
                      {message_clause}
                )
                """,
                params,
            )
        trim_count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM retrieval_snapshot_items items
            JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
            WHERE LENGTH(items.short_snippet_excerpt) > ?
              {message_clause}
            """,
            [safe_excerpt, *params],
        ).fetchone()
        trimmed = int(trim_count_row["count"] or 0)
        if trimmed:
            conn.execute(
                f"""
                UPDATE retrieval_snapshot_items
                SET short_snippet_excerpt = SUBSTR(short_snippet_excerpt, 1, ?)
                WHERE id IN (
                    SELECT items.id
                    FROM retrieval_snapshot_items items
                    JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
                    WHERE LENGTH(items.short_snippet_excerpt) > ?
                      {message_clause}
                )
                """,
                [safe_excerpt, safe_excerpt, *params],
            )
    return {
        "message_id": message_id,
        "keep_latest_per_message": safe_keep,
        "excerpt_chars": safe_excerpt,
        "compacted_snapshots": compacted["compacted_snapshots"],
        "deleted_source_tombstones": tombstoned,
        "trimmed_items": trimmed,
        "retained_at": now,
    }
