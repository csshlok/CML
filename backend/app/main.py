from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import bridge, chat, clusters, jobs, models, search, sources, vaults
from backend.app.core.auth import LocalApiAuthMiddleware
from backend.app.core.background_jobs import enqueue_startup_reconciliation_jobs, start_background_worker
from backend.app.core.config import get_settings
from backend.app.core.database import init_db
from backend.app.core.generation_recovery import recover_interrupted_generations
from backend.app.core.startup_checks import run_startup_checks
from backend.app.core.vault_lock import acquire_vault_lock, release_vault_lock
from backend.app.schemas import HealthResponse

settings = get_settings()

app = FastAPI(title="CML Local Backend", version="0.1.0")

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
    acquire_vault_lock()
    init_db()
    run_startup_checks()
    recover_interrupted_generations()
    enqueue_startup_reconciliation_jobs()
    start_background_worker()


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
