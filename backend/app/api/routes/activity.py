from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect

router = APIRouter(prefix="/activity", tags=["activity"])

ACTIVITY_KINDS = {"source", "chat", "cluster"}


@router.get("")
def list_activity(
    vault_id: str,
    kind: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    if kind and kind not in ACTIVITY_KINDS:
        raise HTTPException(status_code=400, detail="Invalid activity kind")
    unions: list[str] = []
    params: list[object] = []
    if kind in {None, "source"}:
        unions.append(
            """
            SELECT 'source:' || id AS id, 'source' AS kind, updated_at AS time,
                   CASE WHEN state = 'indexed' THEN 'Indexed ' || title ELSE title || ' updated' END AS title,
                   CASE
                     WHEN summary != '' THEN summary
                     WHEN source_type != '' THEN source_type || ' / ' || state
                     ELSE 'Source metadata updated.'
                   END AS detail,
                   '/sources?source=' || id AS href
            FROM sources
            WHERE vault_id = ? AND deleted_at IS NULL
            """
        )
        params.append(vault_id)
    if kind in {None, "cluster"}:
        unions.append(
            """
            SELECT 'cluster:' || id AS id, 'cluster' AS kind, updated_at AS time,
                   name || ' updated' AS title,
                   CASE
                     WHEN cluster_summary != '' THEN cluster_summary
                     WHEN description != '' THEN description
                     ELSE 'Cluster memory changed.'
                   END AS detail,
                   '/clusters/' || id AS href
            FROM clusters
            WHERE vault_id = ?
            """
        )
        params.append(vault_id)
    if kind in {None, "chat"}:
        unions.append(
            """
            SELECT 'chat:' || id AS id, 'chat' AS kind, updated_at AS time,
                   title,
                   CASE
                     WHEN scope_cluster_id IS NOT NULL THEN 'Cluster chat session'
                     ELSE 'Library-wide chat session'
                   END AS detail,
                   '/chat/' || id AS href
            FROM chat_sessions
            WHERE vault_id = ?
            """
        )
        params.append(vault_id)
    union_sql = " UNION ALL ".join(unions)
    normalized_query = (q or "").strip().lower()
    where = ""
    if normalized_query:
        where = "WHERE LOWER(title || ' ' || detail) LIKE ?"
        params.append(f"%{normalized_query}%")
    safe_limit = max(1, min(int(limit), 250))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM ({union_sql}) activity {where}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT id, kind, time, title, detail, href
            FROM ({union_sql}) activity
            {where}
            ORDER BY time DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_limit, safe_offset],
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": int(total_row["total"] or 0),
        "limit": safe_limit,
        "offset": safe_offset,
    }
