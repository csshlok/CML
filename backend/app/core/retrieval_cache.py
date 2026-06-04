import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.database import connect, utc_now


def put_query_cache(
    *,
    vault_id: str,
    query_fingerprint: str,
    contributing_source_ids: list[str],
    artifact_type: str = "query_result",
    payload: dict | None = None,
) -> dict:
    now = utc_now()
    cache_id = f"query-cache-{uuid4()}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO query_evidence_cache (
                id, vault_id, query_fingerprint, artifact_type, contributing_source_ids,
                payload_json, invalidated_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                cache_id,
                vault_id,
                query_fingerprint,
                artifact_type,
                json.dumps(contributing_source_ids),
                json.dumps(payload or {}, separators=(",", ":")),
                now,
                now,
            ),
        )
    return {"id": cache_id, "invalidated": False}


def invalidate_caches_for_source(source_id: str, conn=None) -> dict:
    now = utc_now()
    pattern = f'%"{source_id}"%'
    if conn is not None:
        result = conn.execute(
            """
            UPDATE query_evidence_cache
            SET invalidated_at = ?, updated_at = ?
            WHERE invalidated_at IS NULL AND contributing_source_ids LIKE ?
            """,
            (now, now, pattern),
        )
        return {"source_id": source_id, "invalidated_count": result.rowcount}
    with connect() as owned_conn:
        result = owned_conn.execute(
            """
            UPDATE query_evidence_cache
            SET invalidated_at = ?, updated_at = ?
            WHERE invalidated_at IS NULL AND contributing_source_ids LIKE ?
            """,
            (now, now, pattern),
        )
    return {"source_id": source_id, "invalidated_count": result.rowcount}


def list_query_cache(vault_id: str | None = None) -> list[dict]:
    clause = ""
    params: list[str] = []
    if vault_id:
        clause = "WHERE vault_id = ?"
        params.append(vault_id)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM query_evidence_cache
            {clause}
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "vault_id": row["vault_id"],
            "query_fingerprint": row["query_fingerprint"],
            "artifact_type": row["artifact_type"],
            "contributing_source_ids": _json_list(row["contributing_source_ids"]),
            "invalidated": row["invalidated_at"] is not None,
            "invalidated_at": row["invalidated_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def prune_query_cache(
    *,
    vault_id: str | None = None,
    max_age_days: int = 30,
    max_items: int = 500,
    max_payload_bytes: int = 5_000_000,
) -> dict:
    cutoff = (datetime.now(UTC) - timedelta(days=max(1, max_age_days))).isoformat()
    params: list[object] = [cutoff]
    vault_clause = ""
    if vault_id:
        vault_clause = "AND vault_id = ?"
        params.append(vault_id)
    with connect() as conn:
        old_result = conn.execute(
            f"""
            DELETE FROM query_evidence_cache
            WHERE (updated_at < ? OR invalidated_at IS NOT NULL) {vault_clause}
            """,
            params,
        )
        size_deleted = 0
        payload_rows = conn.execute(
            f"""
            SELECT id, LENGTH(payload_json) AS size
            FROM query_evidence_cache
            WHERE LENGTH(payload_json) > ? {"AND vault_id = ?" if vault_id else ""}
            """,
            ([max(1, max_payload_bytes)] + ([vault_id] if vault_id else [])),
        ).fetchall()
        for row in payload_rows:
            conn.execute("DELETE FROM query_evidence_cache WHERE id = ?", (row["id"],))
            size_deleted += 1
        extra_deleted = 0
        scoped_clause = "WHERE vault_id = ?" if vault_id else ""
        scoped_params = [vault_id] if vault_id else []
        extra_rows = conn.execute(
            f"""
            SELECT id
            FROM query_evidence_cache
            {scoped_clause}
            ORDER BY updated_at DESC
            LIMIT -1 OFFSET ?
            """,
            scoped_params + [max(1, max_items)],
        ).fetchall()
        for row in extra_rows:
            conn.execute("DELETE FROM query_evidence_cache WHERE id = ?", (row["id"],))
            extra_deleted += 1
    return {
        "vault_id": vault_id,
        "deleted_old_or_invalidated": old_result.rowcount,
        "deleted_oversized": size_deleted,
        "deleted_over_limit": extra_deleted,
        "max_age_days": max(1, max_age_days),
        "max_items": max(1, max_items),
        "max_payload_bytes": max(1, max_payload_bytes),
    }


def _json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
