from fastapi import APIRouter, HTTPException

from backend.app.core.llm_runtime import runtime_status
from backend.app.core.model_registry import list_models, model_status, start_model_download
from backend.app.schemas import ModelDownloadStart, ModelRead, ModelRuntimeStatus

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelRead])
def list_local_models() -> list[dict]:
    return list_models()


@router.get("/runtime", response_model=ModelRuntimeStatus)
def get_runtime_status() -> dict:
    return runtime_status()


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
