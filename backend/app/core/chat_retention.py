from backend.app.core.database import connect, dict_from_row, utc_now


def paginated_messages(session_id: str, *, limit: int = 50, cursor: str | None = None) -> dict:
    safe_limit = max(1, min(limit, 100))
    params: list[object] = [session_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND (created_at > ? OR (created_at = ? AND id > ?))"
        params.extend([cursor, cursor, ""])
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
        next_cursor = items[-1]["created_at"]
    return {"session_id": session_id, "items": items, "next_cursor": next_cursor}


def compact_retrieval_snapshots(*, message_id: str | None = None, keep_latest_per_message: int = 1) -> dict:
    safe_keep = max(1, min(keep_latest_per_message, 5))
    params: list[object] = []
    message_clause = ""
    if message_id:
        message_clause = "WHERE message_id = ?"
        params.append(message_id)
    compacted = 0
    now = utc_now()
    with connect() as conn:
        messages = conn.execute(
            f"SELECT DISTINCT message_id FROM retrieval_snapshots {message_clause}",
            params,
        ).fetchall()
        for message in messages:
            rows = conn.execute(
                """
                SELECT id
                FROM retrieval_snapshots
                WHERE message_id = ?
                ORDER BY created_at DESC
                """,
                (message["message_id"],),
            ).fetchall()
            stale_ids = [row["id"] for row in rows[safe_keep:]]
            for snapshot_id in stale_ids:
                conn.execute(
                    """
                    UPDATE retrieval_snapshot_items
                    SET chunk_id = NULL,
                        page_id = NULL,
                        short_snippet_excerpt = SUBSTR(short_snippet_excerpt, 1, 240),
                        state = CASE WHEN state = 'current' THEN 'compacted' ELSE state END
                    WHERE snapshot_id = ?
                    """,
                    (snapshot_id,),
                )
                conn.execute(
                    """
                    UPDATE retrieval_snapshots
                    SET retrieval_mode = retrieval_mode || ':compacted'
                    WHERE id = ? AND retrieval_mode NOT LIKE '%:compacted'
                    """,
                    (snapshot_id,),
                )
                compacted += 1
    return {"compacted_snapshots": compacted, "compacted_at": now}


def chat_evidence_retention_policy() -> dict:
    return {
        "default_keep_latest_snapshots_per_message": 1,
        "max_keep_latest_snapshots_per_message": 5,
        "default_excerpt_chars": 240,
        "deleted_source_state": "source_deleted",
        "compacted_state": "compacted",
        "query_cache_prune_endpoint": "/api/v1/search/query-cache/prune",
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
        tombstone_rows = conn.execute(
            f"""
            SELECT items.id
            FROM retrieval_snapshot_items items
            JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
            LEFT JOIN sources ON sources.id = items.source_id
            WHERE items.source_id IS NOT NULL
              AND (sources.id IS NULL OR sources.deleted_at IS NOT NULL)
              {message_clause}
            """,
            params,
        ).fetchall()
        for row in tombstone_rows:
            conn.execute(
                """
                UPDATE retrieval_snapshot_items
                SET state = 'source_deleted', source_id = NULL, chunk_id = NULL, page_id = NULL
                WHERE id = ?
                """,
                (row["id"],),
            )
            tombstoned += 1
        trim_rows = conn.execute(
            f"""
            SELECT items.id
            FROM retrieval_snapshot_items items
            JOIN retrieval_snapshots snapshots ON snapshots.id = items.snapshot_id
            WHERE LENGTH(items.short_snippet_excerpt) > ?
              {message_clause}
            """,
            [safe_excerpt, *params],
        ).fetchall()
        for row in trim_rows:
            conn.execute(
                """
                UPDATE retrieval_snapshot_items
                SET short_snippet_excerpt = SUBSTR(short_snippet_excerpt, 1, ?)
                WHERE id = ?
                """,
                (safe_excerpt, row["id"]),
            )
            trimmed += 1
    return {
        "message_id": message_id,
        "keep_latest_per_message": safe_keep,
        "excerpt_chars": safe_excerpt,
        "compacted_snapshots": compacted["compacted_snapshots"],
        "deleted_source_tombstones": tombstoned,
        "trimmed_items": trimmed,
        "retained_at": now,
    }
