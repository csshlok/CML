from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import activity, bridge, chat, cli_auth, clusters, diagnostics, extension, integrations, jobs, map, memory, models, projects, search, sources, system, vaults
from backend.app.core.auth import LocalApiAuthMiddleware
from backend.app.core.background_jobs import (
    enqueue_startup_metadata_jobs,
    enqueue_startup_reconciliation_jobs,
    migrate_legacy_project_index_jobs,
    start_background_worker,
)
from backend.app.core.config import get_settings
from backend.app.core.database import init_db
from backend.app.core.generation_recovery import recover_interrupted_generations
from backend.app.core.logging_setup import setup_logging
from backend.app.core.migrations import run_migrations
from backend.app.core.model_registry import active_chat_model_status
from backend.app.core.model_runtime_supervisor import restore_selected_model, stop_managed_runtime
from backend.app.core.pre_vault import BackendModeMiddleware
from backend.app.core.public_errors import (
    public_http_exception,
    public_unhandled_exception,
    public_validation_exception,
)
from backend.app.core.request_security import RequestSecurityMiddleware
from backend.app.core.startup_checks import StartupCheckError, verify_schema_version, verify_sqlite_integrity
from backend.app.core.unlock_middleware import UnlockGateMiddleware
from backend.app.core.startup_status import reset_startup_status_timing, write_startup_status
from backend.app.core.version import app_version
from backend.app.core.vault_lock import VaultLockError, acquire_vault_lock, release_vault_lock
from backend.app.schemas import HealthResponse

settings = get_settings()


def startup() -> None:
    reset_startup_status_timing()
    write_startup_status("starting")
    failure_status_written = False
    try:
        setup_logging()
        if settings.backend_mode == "pre_vault":
            write_startup_status("pre_vault_mode", message="Backend started in restricted setup mode.")
            init_db()
            write_startup_status("ready", status="ready", message="Pre-vault backend is ready.")
            return
        write_startup_status("vault_lock_acquiring")
        try:
            acquire_vault_lock()
        except VaultLockError as exc:
            write_startup_status("vault_lock_failed", status="failed", message=str(exc), error_code=exc.__class__.__name__)
            failure_status_written = True
            raise
        write_startup_status("vault_lock_acquired")
        write_startup_status("database_initializing")
        try:
            init_db()
        except Exception as exc:
            write_startup_status(
                "database_initialization_failed",
                status="failed",
                message=str(exc),
                error_code=exc.__class__.__name__,
            )
            failure_status_written = True
            raise
        write_startup_status("integrity_check_running", message="Running the fast database check.")
        try:
            verify_sqlite_integrity(full=False)
        except StartupCheckError as exc:
            write_startup_status("integrity_check_failed", status="failed", message=str(exc), error_code=exc.__class__.__name__)
            failure_status_written = True
            raise
        write_startup_status("schema_check_running")
        try:
            run_migrations()
            verify_schema_version()
        except Exception as exc:
            write_startup_status("schema_check_failed", status="failed", message=str(exc), error_code=exc.__class__.__name__)
            failure_status_written = True
            raise
        write_startup_status("job_recovery_running")
        # A fresh process cannot own generations left by the previous process,
        # so startup recovery intentionally has no staleness grace period.
        recover_interrupted_generations(stale_after_seconds=0)
        start_background_worker()
        write_startup_status("core_ready", status="ready", message="Your library is ready.")
        start_startup_warming()
    except Exception as exc:
        if not failure_status_written:
            write_startup_status("startup_failed", status="failed", message=str(exc), error_code=exc.__class__.__name__)
        raise


def start_startup_warming() -> None:
    thread = threading.Thread(target=_run_startup_warming, name="cml-startup-warming", daemon=True)
    thread.start()


def _run_startup_warming() -> None:
    try:
        write_startup_status("warming", message="Finishing background setup.")
        migrate_legacy_project_index_jobs()
        enqueue_startup_reconciliation_jobs()
        write_startup_status("runtime_detection_running")
        active_model = active_chat_model_status()
        if active_model and active_model.get("local_path"):
            restore_selected_model(str(active_model["id"]), str(active_model["local_path"]))
        enqueue_startup_metadata_jobs()
        write_startup_status("ready", status="ready", message="Vault is ready.")
    except Exception as exc:
        write_startup_status(
            "ready",
            status="ready",
            message="Your library is ready. Some background setup needs attention.",
            error_code=exc.__class__.__name__,
        )


def shutdown() -> None:
    stop_managed_runtime()
    release_vault_lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="CML Local Backend", version=app_version(), lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return public_http_exception(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return public_unhandled_exception(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return public_validation_exception(request, exc)

app.add_middleware(UnlockGateMiddleware)
app.add_middleware(BackendModeMiddleware)
app.add_middleware(LocalApiAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        *[f"http://127.0.0.1:{port}" for port in range(5174, 5191)],
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestSecurityMiddleware)


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cml-backend"}


app.include_router(vaults.router, prefix=settings.api_prefix)
app.include_router(activity.router, prefix=settings.api_prefix)
app.include_router(clusters.router, prefix=settings.api_prefix)
app.include_router(map.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(cli_auth.router, prefix=settings.api_prefix)
app.include_router(sources.router, prefix=settings.api_prefix)
app.include_router(search.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(bridge.router, prefix=settings.api_prefix)
app.include_router(models.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(memory.router, prefix=settings.api_prefix)
app.include_router(diagnostics.router, prefix=settings.api_prefix)
app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(integrations.router, prefix=settings.api_prefix)
app.include_router(extension.router, prefix=settings.api_prefix)
