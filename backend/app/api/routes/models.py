from fastapi import APIRouter, HTTPException

from backend.app.core.embeddings import (
    cancel_embedding_model_download,
    configure_embedding_runtime,
    embedding_download_status,
    embedding_status,
    start_embedding_model_download,
)
from backend.app.core.llm_runtime import runtime_status
from backend.app.core.model_registry import (
    cancel_model_download,
    list_models,
    model_status,
    start_model_download,
)
from backend.app.schemas import (
    EmbeddingRuntimeConfigure,
    EmbeddingRuntimeStatus,
    EmbeddingModelDownloadRequest,
    EmbeddingModelDownloadState,
    ModelDownloadStart,
    ModelRead,
    ModelRuntimeStatus,
)

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelRead])
def list_local_models() -> list[dict]:
    return list_models()


@router.get("/runtime", response_model=ModelRuntimeStatus)
def get_runtime_status() -> dict:
    return runtime_status()


@router.get("/embeddings", response_model=EmbeddingRuntimeStatus)
def get_embedding_status() -> dict:
    return embedding_status()


@router.post("/embeddings/configure", response_model=EmbeddingRuntimeStatus)
def configure_embeddings(payload: EmbeddingRuntimeConfigure) -> dict:
    try:
        return configure_embedding_runtime(payload.provider, payload.cache_dir, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/embeddings/download", response_model=EmbeddingModelDownloadState)
def get_embedding_download_status() -> dict:
    return embedding_download_status()


@router.post("/embeddings/download", response_model=EmbeddingModelDownloadState)
def download_embedding_model(payload: EmbeddingModelDownloadRequest) -> dict:
    return start_embedding_model_download(payload.cache_dir, payload.model)


@router.post("/embeddings/download/cancel", response_model=EmbeddingModelDownloadState)
def cancel_embedding_download() -> dict:
    return cancel_embedding_model_download()


@router.get("/{model_id}", response_model=ModelRead)
def get_local_model(model_id: str) -> dict:
    try:
        return model_status(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc


@router.post("/{model_id}/download", response_model=ModelDownloadStart)
def download_local_model(model_id: str) -> dict:
    try:
        return start_model_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc


@router.post("/{model_id}/download/cancel", response_model=ModelDownloadStart)
def cancel_local_model_download(model_id: str) -> dict:
    try:
        return cancel_model_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc
