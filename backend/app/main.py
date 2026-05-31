from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import bridge, chat, clusters, diagnostics, jobs, models, search, sources, vaults
from backend.app.core.auth import LocalApiAuthMiddleware
from backend.app.core.background_jobs import enqueue_startup_reconciliation_jobs, start_background_worker
from backend.app.core.config import get_settings
from backend.app.core.database import init_db
from backend.app.core.generation_recovery import recover_interrupted_generations
from backend.app.core.logging_setup import setup_logging
from backend.app.core.pre_vault import BackendModeMiddleware
from backend.app.core.reserved_fields import ReservedChatFieldMiddleware
from backend.app.core.startup_checks import run_startup_checks
from backend.app.core.startup_status import write_startup_status
from backend.app.core.vault_lock import acquire_vault_lock, release_vault_lock
from backend.app.schemas import HealthResponse

settings = get_settings()

app = FastAPI(title="CML Local Backend", version="0.1.0")

app.add_middleware(ReservedChatFieldMiddleware)
app.add_middleware(BackendModeMiddleware)
app.add_middleware(LocalApiAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    write_startup_status("starting")
    try:
        setup_logging()
        if settings.backend_mode == "pre_vault":
            write_startup_status("pre_vault_mode", message="Backend started in restricted setup mode.")
            init_db()
            write_startup_status("ready", status="ready", message="Pre-vault backend is ready.")
            return
        write_startup_status("vault_lock_acquiring")
        acquire_vault_lock()
        write_startup_status("database_initializing")
        init_db()
        write_startup_status("integrity_check_running")
        run_startup_checks()
        write_startup_status("job_recovery_running")
        recover_interrupted_generations()
        write_startup_status("reconciliation_queued")
        enqueue_startup_reconciliation_jobs()
        write_startup_status("runtime_detection_running")
        start_background_worker()
        write_startup_status("ready", status="ready", message="Full-vault backend is ready.")
    except Exception as exc:
        write_startup_status("startup_failed", status="failed", message=str(exc), error_code=exc.__class__.__name__)
        raise


@app.on_event("shutdown")
def shutdown() -> None:
    release_vault_lock()


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cml-backend"}


app.include_router(vaults.router, prefix=settings.api_prefix)
app.include_router(clusters.router, prefix=settings.api_prefix)
app.include_router(sources.router, prefix=settings.api_prefix)
app.include_router(search.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(bridge.router, prefix=settings.api_prefix)
app.include_router(models.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(diagnostics.router, prefix=settings.api_prefix)
