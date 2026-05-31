from fastapi import APIRouter, HTTPException

from backend.app.core.background_jobs import cancel_job, job_queue_status, run_due_jobs_once
from backend.app.schemas import AppJobRead, JobQueueStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/status", response_model=JobQueueStatus)
def get_job_status() -> dict:
    return job_queue_status()


@router.post("/run-once", response_model=JobQueueStatus)
def run_jobs_once() -> dict:
    run_due_jobs_once(limit=10)
    return job_queue_status()


@router.post("/{job_id}/cancel", response_model=AppJobRead)
def cancel_app_job(job_id: str) -> dict:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
