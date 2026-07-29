from fastapi import APIRouter, HTTPException

from backend.app.core.background_jobs import (
    cancel_job,
    enqueue_job,
    job_queue_status,
    pause_job,
    resume_job,
    wake_background_worker,
)
from backend.app.core.database import connect
from backend.app.core.pagination import cursor_page, decode_cursor
from backend.app.core.temporal_facts import temporal_fact_diagnostics
from backend.app.schemas import (
    AppJobRead,
    JobQueueStatus,
    TemporalFactBackfillRequest,
    TemporalFactDiagnosticsRead,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/status", response_model=JobQueueStatus)
def get_job_status() -> dict:
    return job_queue_status()


@router.post("/run-once", response_model=JobQueueStatus)
def run_jobs_once() -> dict:
    # Wake the durable startup worker and return immediately. Running queued
    # jobs inside this request made one slow job block the API health path.
    wake_background_worker()
    return job_queue_status()


@router.get("/temporal-facts/status", response_model=TemporalFactDiagnosticsRead)
def get_temporal_fact_status(vault_id: str) -> dict:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return temporal_fact_diagnostics(conn, vault_id=vault_id)


@router.post("/temporal-facts/backfill", response_model=AppJobRead, status_code=202)
def backfill_temporal_facts(payload: TemporalFactBackfillRequest) -> dict:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return enqueue_job(
            conn,
            job_type="temporal_fact_backfill",
            payload=payload.model_dump(),
            dedupe_key=f"temporal-fact-backfill:{payload.vault_id}",
            scope_id=payload.vault_id,
            user_initiated=True,
        )


@router.post("/cluster-profiles/backfill", response_model=AppJobRead, status_code=202)
def backfill_cluster_profiles(vault_id: str) -> dict:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return enqueue_job(
            conn,
            job_type="cluster_profile_backfill",
            payload={"vault_id": vault_id},
            dedupe_key=f"cluster-profile-backfill:{vault_id}",
            scope_id=vault_id,
            user_initiated=True,
        )


@router.get("")
def list_app_jobs(
    status: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        allowed = {
            "queued", "running", "paused", "succeeded", "failed", "cancelled",
            "blocked_by_dependency", "blocked_setup_required", "deferred",
            "manual_review",
        }
        if not statuses or any(item not in allowed for item in statuses):
            raise HTTPException(status_code=400, detail="Invalid job status")
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    decoded = decode_cursor(cursor)
    if decoded:
        updated_at, item_id = decoded
        clauses.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
        params.extend([updated_at, updated_at, item_id])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 200))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM app_jobs {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            [*params, safe_limit + 1],
        ).fetchall()
    return cursor_page(
        [dict(row) for row in rows],
        requested_limit=safe_limit,
        sort_field="updated_at",
    )


@router.get("/{job_id}", response_model=AppJobRead)
def get_app_job(job_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(row)


@router.post("/{job_id}/cancel", response_model=AppJobRead)
def cancel_app_job(job_id: str) -> dict:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/pause", response_model=AppJobRead)
def pause_app_job(job_id: str) -> dict:
    try:
        return pause_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/resume", response_model=AppJobRead)
def resume_app_job(job_id: str) -> dict:
    try:
        return resume_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
