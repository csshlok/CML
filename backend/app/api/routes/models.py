import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.core.embeddings import (
    MANAGED_EMBEDDING_MODELS,
    cancel_embedding_model_download,
    configure_embedding_runtime,
    embedding_download_status,
    embedding_status,
    start_embedding_model_download,
)
from backend.app.core.llm_runtime import runtime_status
from backend.app.core.background_jobs import (
    enqueue_job,
    notify_embedding_prerequisite_changed,
    notify_local_model_prerequisite_changed,
)
from backend.app.core.database import connect
from backend.app.core.model_registry import (
    activate_model_runtime,
    approve_model_scan_root,
    cancel_model_download,
    discover_installed_models,
    import_model_checkpoint,
    list_models,
    model_compatibility_report,
    model_integrity_manifest_status,
    model_recommendations,
    model_status,
    start_model_download,
)
from backend.app.core.model_recommender.diagnostics import export_recommendation_diagnostics
from backend.app.core.model_recommender.benchmark_store import record_model_measurement
from backend.app.core.model_recommender.measurement import run_chat_measurement
from backend.app.schemas import (
    EmbeddingRuntimeConfigure,
    EmbeddingRuntimeStatus,
    EmbeddingModelDownloadRequest,
    EmbeddingModelDownloadState,
    InstalledModelDiscoveryRead,
    ModelCompatibilityRead,
    ModelCompatibilityRequest,
    ModelActivateRequest,
    AppJobRead,
    ModelDownloadRequest,
    ModelDownloadStart,
    ModelRecommendationMeasurementRunRequest,
    ModelRecommendationHardwarePreviewRequest,
    ModelRecommendationMeasurementWrite,
    ModelRecommendationRead,
    ModelRead,
    ModelRuntimeStatus,
    ModelScanRootRequest,
    ModelDiscoveryJobRequest,
)

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelRead])
def list_local_models() -> list[dict]:
    return list_models()


@router.get("/recommendations", response_model=ModelRecommendationRead)
def get_model_recommendations(refresh: bool = False) -> dict:
    return model_recommendations(refresh=refresh)


@router.get("/recommendations/diagnostics")
def get_model_recommendation_diagnostics(refresh: bool = False) -> dict:
    return export_recommendation_diagnostics(refresh=refresh)


@router.post("/recommendations/diagnostics/preview")
def preview_model_recommendation_diagnostics(payload: ModelRecommendationHardwarePreviewRequest) -> dict:
    return export_recommendation_diagnostics(
        hardware_profile_override=dict(payload.hardware or {}),
        refresh=payload.refresh,
    )


@router.post("/recommendations/measurements")
def record_model_recommendation_measurement(payload: ModelRecommendationMeasurementWrite) -> dict:
    if payload.model_id:
        return {
            "kind": "model",
            "record": record_model_measurement(
                payload.model_id,
                score=payload.score,
                estimated_tok_per_sec=payload.estimated_tok_per_sec,
                startup_seconds=payload.startup_seconds,
                runtime_success=payload.runtime_success,
                training_success=payload.training_success,
                measured_at=payload.measured_at,
            ),
        }
    raise HTTPException(status_code=400, detail="model_id is required.")


@router.post("/recommendations/measurements/run")
def run_model_recommendation_measurement(payload: ModelRecommendationMeasurementRunRequest) -> dict:
    try:
        if payload.model_id:
            return run_chat_measurement(model_id=payload.model_id, prompt=payload.prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="model_id is required.")


@router.get("/discover", response_model=InstalledModelDiscoveryRead)
def discover_local_models(max_results: int = 32, include_rejected: bool = False, refresh: bool = False) -> dict:
    return discover_installed_models(
        max_results=max(1, min(int(max_results), 200)),
        include_rejected=include_rejected,
        refresh=refresh,
    )


@router.post("/discover/jobs", response_model=AppJobRead, status_code=202)
def queue_model_discovery(payload: ModelDiscoveryJobRequest) -> dict:
    with connect() as conn:
        return enqueue_job(
            conn,
            job_type="model_discovery",
            payload={
                "max_results": payload.max_results,
                "include_rejected": payload.include_rejected,
                "scan_all_drives": payload.scan_all_drives,
            },
            dedupe_key=payload.idempotency_key or "model-discovery:active",
            user_initiated=True,
        )


@router.post("/discovery-roots")
def add_model_discovery_root(payload: ModelScanRootRequest) -> dict:
    try:
        return approve_model_scan_root(payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runtime", response_model=ModelRuntimeStatus)
def get_runtime_status() -> dict:
    return runtime_status()


@router.get("/integrity-manifest")
def get_model_integrity_manifest_status() -> dict:
    return model_integrity_manifest_status()


@router.get("/embeddings", response_model=EmbeddingRuntimeStatus)
def get_embedding_status(probe: bool = False) -> dict:
    return embedding_status(probe_model=probe)


@router.post("/embeddings/configure", response_model=EmbeddingRuntimeStatus)
def configure_embeddings(payload: EmbeddingRuntimeConfigure) -> dict:
    try:
        result = configure_embedding_runtime(payload.provider, payload.cache_dir, payload.model)
        notify_embedding_prerequisite_changed()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/embeddings/download", response_model=EmbeddingModelDownloadState)
def get_embedding_download_status() -> dict:
    return embedding_download_status()


@router.post("/embeddings/download", response_model=EmbeddingModelDownloadState)
def download_embedding_model(payload: EmbeddingModelDownloadRequest) -> dict:
    if payload.model and payload.model not in MANAGED_EMBEDDING_MODELS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Vault only downloads its curated public memory-search model. "
                "Use an existing local folder for other embedding models."
            ),
        )
    try:
        return start_embedding_model_download(payload.cache_dir, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/embeddings/download/cancel", response_model=EmbeddingModelDownloadState)
def cancel_embedding_download() -> dict:
    return cancel_embedding_model_download()


@router.get("/{model_id}", response_model=ModelRead)
def get_local_model(model_id: str) -> dict:
    try:
        return model_status(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc


@router.post("/compatibility/report", response_model=ModelCompatibilityRead)
def get_model_compatibility_report(payload: ModelCompatibilityRequest) -> dict:
    return model_compatibility_report(payload.path)


@router.post("/import", response_model=ModelRead)
def import_local_model(payload: ModelCompatibilityRequest) -> dict:
    try:
        return import_model_checkpoint(payload.path, name=payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/jobs", response_model=AppJobRead, status_code=202)
def queue_local_model_import(payload: ModelCompatibilityRequest) -> dict:
    source = Path(payload.path).expanduser().resolve()
    report = model_compatibility_report(source)
    if not report["accepted"]:
        raise HTTPException(status_code=400, detail=report["detail"])
    stat = source.stat()
    identity = hashlib.sha256(
        f"{source}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()
    with connect() as conn:
        return enqueue_job(
            conn,
            job_type="model_import",
            payload={"path": str(source), "name": payload.name},
            dedupe_key=f"model-import:{identity}",
            scope_id=identity,
            user_initiated=True,
        )


@router.post("/{model_id}/activate", response_model=ModelRead)
def activate_local_model(model_id: str, payload: ModelActivateRequest | None = None) -> dict:
    try:
        role = payload.role if payload is not None else "chat"
        activated = activate_model_runtime(model_id, role=role)
        notify_local_model_prerequisite_changed()
        return activated
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{model_id}/download", response_model=ModelDownloadStart)
def download_local_model(model_id: str, payload: ModelDownloadRequest | None = None) -> dict:
    try:
        return start_model_download(model_id, target_dir=payload.target_dir if payload else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc


@router.post("/{model_id}/download/cancel", response_model=ModelDownloadStart)
def cancel_local_model_download(model_id: str) -> dict:
    try:
        return cancel_model_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc
