from fastapi import APIRouter, HTTPException

from backend.app.core.background_jobs import (
    cancel_job,
    enqueue_job,
    job_queue_status,
    run_due_jobs_once,
)
from backend.app.core.database import connect
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
    run_due_jobs_once(limit=10)
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


@router.post("/{job_id}/cancel", response_model=AppJobRead)
def cancel_app_job(job_id: str) -> dict:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
