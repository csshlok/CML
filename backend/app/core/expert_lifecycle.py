from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now


def mark_cluster_needs_update(conn, cluster_id: str | None, detail: str) -> None:
    if not cluster_id:
        return
    row = conn.execute("SELECT id, vault_id, expert_status FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        return
    if row["expert_status"] not in {"learning", "setting-up"}:
        conn.execute(
            "UPDATE clusters SET expert_status = 'needs-update', updated_at = ? WHERE id = ?",
            (utc_now(), cluster_id),
        )
    create_expert_job(conn, cluster_id=cluster_id, vault_id=row["vault_id"], action="refresh-needed", detail=detail)


def create_expert_job(conn, *, cluster_id: str, vault_id: str, action: str, detail: str = "") -> dict:
    now = utc_now()
    job = {
        "id": f"expert-job-{uuid4()}",
        "cluster_id": cluster_id,
        "vault_id": vault_id,
        "action": action,
        "status": "queued",
        "detail": detail,
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO cluster_expert_jobs (
            id, cluster_id, vault_id, action, status, detail, created_at, updated_at
        )
        VALUES (
            :id, :cluster_id, :vault_id, :action, :status, :detail, :created_at, :updated_at
        )
        """,
        job,
    )
    return job


def latest_expert_jobs(conn, cluster_id: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM cluster_expert_jobs
        WHERE cluster_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (cluster_id, limit),
    ).fetchall()
    return [dict_from_row(row) for row in rows]
