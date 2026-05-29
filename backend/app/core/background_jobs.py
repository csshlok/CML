import json
import threading
import time
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.expert_lifecycle import mark_cluster_needs_update

JOB_POLL_SECONDS = 1.0
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def enqueue_job(
    conn,
    *,
    job_type: str,
    payload: dict,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
) -> dict:
    now = utc_now()
    if dedupe_key:
        existing = conn.execute(
            """
            SELECT * FROM app_jobs
            WHERE dedupe_key = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (dedupe_key,),
        ).fetchone()
        if existing is not None:
            return dict_from_row(existing)

    job = {
        "id": f"job-{uuid4()}",
        "job_type": job_type,
        "status": "queued",
        "payload": json.dumps(payload, separators=(",", ":")),
        "dedupe_key": dedupe_key,
        "attempts": 0,
        "max_attempts": max_attempts,
        "last_error": "",
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO app_jobs (
            id, job_type, status, payload, dedupe_key, attempts, max_attempts,
            last_error, created_at, updated_at
        )
        VALUES (
            :id, :job_type, :status, :payload, :dedupe_key, :attempts, :max_attempts,
            :last_error, :created_at, :updated_at
        )
        """,
        job,
    )
    return job


def start_background_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(target=_worker_loop, name="cml-background-jobs", daemon=True)
        thread.start()
        _WORKER_STARTED = True


def run_due_jobs_once(limit: int = 5) -> int:
    processed = 0
    for _ in range(limit):
        job = _claim_next_job()
        if job is None:
            break
        _run_claimed_job(job)
        processed += 1
    return processed


def job_queue_status() -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM app_jobs
            GROUP BY status
            """
        ).fetchall()
        latest = conn.execute(
            """
            SELECT * FROM app_jobs
            ORDER BY updated_at DESC
            LIMIT 10
            """
        ).fetchall()
    counts = {row["status"]: row["count"] for row in rows}
    return {
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "latest": [dict_from_row(row) for row in latest],
    }


def _worker_loop() -> None:
    while True:
        try:
            run_due_jobs_once(limit=3)
        except Exception:
            pass
        time.sleep(JOB_POLL_SECONDS)


def _claim_next_job() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM app_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        job = dict_from_row(row)
        now = utc_now()
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'running', attempts = attempts + 1, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, job["id"]),
        )
    return job


def _run_claimed_job(job: dict) -> None:
    try:
        payload = _decode_payload(job["payload"])
        if job["job_type"] == "reindex_source":
            _run_reindex_source(payload)
        elif job["job_type"] == "chat_transcript_memory":
            _run_chat_transcript_memory(payload)
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
    except Exception as exc:
        _mark_job_failed_or_retry(job, str(exc))
        return

    with connect() as conn:
        conn.execute(
            "UPDATE app_jobs SET status = 'succeeded', updated_at = ?, last_error = '' WHERE id = ?",
            (utc_now(), job["id"]),
        )


def _run_reindex_source(payload: dict) -> None:
    source_id = str(payload["source_id"])
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return
        source = dict_from_row(row)
        if source["state"] != "indexed":
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            return
        reindex_source_chunks(conn, source)
        mark_cluster_needs_update(conn, source.get("cluster_id"), "Source was indexed in the background.")


def _run_chat_transcript_memory(payload: dict) -> None:
    from backend.app.core.chat_memory import upsert_chat_transcript_sources

    vault_id = str(payload["vault_id"])
    session_id = str(payload["session_id"])
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexing', memory_updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        upsert_chat_transcript_sources(conn, vault_id=vault_id, session_id=session_id)
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexed', memory_updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )


def _mark_job_failed_or_retry(job: dict, error: str) -> None:
    attempts = int(job.get("attempts") or 0) + 1
    max_attempts = int(job.get("max_attempts") or 3)
    status = "failed" if attempts >= max_attempts else "queued"
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = ?, attempts = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, attempts, error[:500], utc_now(), job["id"]),
        )


def _decode_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
