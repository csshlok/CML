from fastapi import APIRouter

from backend.app.core.background_jobs import job_queue_status, run_due_jobs_once
from backend.app.schemas import JobQueueStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/status", response_model=JobQueueStatus)
def get_job_status() -> dict:
    return job_queue_status()


@router.post("/run-once", response_model=JobQueueStatus)
def run_jobs_once() -> dict:
    run_due_jobs_once(limit=10)
    return job_queue_status()
