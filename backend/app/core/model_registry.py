from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import URLError
from urllib.request import Request, urlopen
import json
import threading

from backend.app.core.config import get_settings
from backend.app.core.network_security import NetworkSecurityError, validate_huggingface_url


@dataclass(frozen=True)
class LocalModel:
    id: str
    name: str
    role: str
    hf_repo: str
    quantization: str
    approximate_download_gb: float
    recommended_ram_gb: str
    notes: str


MODEL_REGISTRY: tuple[LocalModel, ...] = (
    LocalModel(
        id="qwen3-4b-q4_k_m",
        name="Qwen3 4B Q4_K_M",
        role="default",
        hf_repo="Qwen/Qwen3-4B-GGUF",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Default local synthesis model for CML.",
    ),
    LocalModel(
        id="phi-4-mini-instruct-q4_k_m",
        name="Phi-4 Mini Instruct Q4_K_M",
        role="low-spec-fallback",
        hf_repo="unsloth/Phi-4-mini-instruct-GGUF",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Fallback for weaker machines.",
    ),
    LocalModel(
        id="qwen3-8b-q4_k_m",
        name="Qwen3 8B Q4_K_M",
        role="quality-option",
        hf_repo="Qwen/Qwen3-8B-GGUF",
        quantization="Q4_K_M",
        approximate_download_gb=4.8,
        recommended_ram_gb="16+",
        notes="Higher-quality local synthesis option.",
    ),
    LocalModel(
        id="gemma-3-4b-it-q4_k_m",
        name="Gemma 3 4B IT Q4_K_M",
        role="optional",
        hf_repo="Aldaris/gemma-3-4b-it-Q4_K_M-GGUF",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Optional later candidate.",
    ),
    LocalModel(
        id="gemma-3-12b-it-q4_k_m",
        name="Gemma 3 12B IT Q4_K_M",
        role="optional-large",
        hf_repo="nocturne23/gemma-3-12b-it-Q4_K_M-GGUF",
        quantization="Q4_K_M",
        approximate_download_gb=6.9,
        recommended_ram_gb="24+",
        notes="Optional larger candidate for later experiments.",
    ),
)

_download_state: dict[str, dict[str, Any]] = {}
_download_lock = threading.Lock()


def models_dir() -> Path:
    settings = get_settings()
    path = settings.models_dir or settings.data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_models() -> list[dict[str, Any]]:
    return [model_status(model.id) for model in MODEL_REGISTRY]


def get_model(model_id: str) -> LocalModel | None:
    return next((model for model in MODEL_REGISTRY if model.id == model_id), None)


def model_status(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    info = _model_to_dict(model)
    local_path = _find_local_model_file(model)
    state = _download_state.get(model_id)
    info.update(
        {
            "installed": local_path is not None,
            "local_path": str(local_path) if local_path else None,
            "download": state,
        }
    )
    return info


def start_model_download(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)

    existing = model_status(model_id)
    if existing["installed"]:
        return {"model_id": model_id, "status": "installed", "local_path": existing["local_path"]}

    with _download_lock:
        state = _download_state.get(model_id)
        if state and state["status"] in {"resolving", "downloading"}:
            return state
        _download_state[model_id] = {
            "model_id": model_id,
            "status": "resolving",
            "bytes_downloaded": 0,
            "total_bytes": None,
            "error": None,
        }

    thread = threading.Thread(target=_download_model, args=(model,), daemon=True)
    thread.start()
    return _download_state[model_id]


def _model_to_dict(model: LocalModel) -> dict[str, Any]:
    info = asdict(model)
    info["llama_cpp_ref"] = f"{model.hf_repo}:{model.quantization}"
    return info


def _find_local_model_file(model: LocalModel) -> Path | None:
    pattern = f"*{model.quantization.lower()}*.gguf"
    repo_dir = models_dir() / model.id
    if not repo_dir.exists():
        return None
    matches = sorted(repo_dir.glob(pattern))
    return matches[0] if matches else None


def _download_model(model: LocalModel) -> None:
    try:
        file_name = _resolve_gguf_filename(model)
        safe_file_name = _safe_model_file_name(file_name)
        url = f"https://huggingface.co/{model.hf_repo}/resolve/main/{quote(file_name, safe='')}"
        validate_huggingface_url(url)
        target_dir = models_dir() / model.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_file_name
        partial = target.with_suffix(target.suffix + ".part")

        with _download_lock:
            _download_state[model.id].update(
                {"status": "downloading", "file_name": safe_file_name, "local_path": str(target)}
            )

        request = Request(url, headers={"User-Agent": "CML-local-backend/0.1"})
        with urlopen(request, timeout=30) as response:
            total = response.headers.get("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            downloaded = 0
            with partial.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    with _download_lock:
                        _download_state[model.id].update(
                            {"bytes_downloaded": downloaded, "total_bytes": total_bytes}
                        )
        partial.replace(target)
        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "installed",
                    "bytes_downloaded": target.stat().st_size,
                    "total_bytes": target.stat().st_size,
                    "local_path": str(target),
                }
            )
    except Exception as exc:
        with _download_lock:
            _download_state[model.id].update({"status": "failed", "error": str(exc)})


def _resolve_gguf_filename(model: LocalModel) -> str:
    api_url = f"https://huggingface.co/api/models/{model.hf_repo}"
    validate_huggingface_url(api_url)
    request = Request(api_url, headers={"User-Agent": "CML-local-backend/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not resolve model files for {model.hf_repo}") from exc

    siblings = payload.get("siblings", [])
    quant = model.quantization.lower()
    candidates = [
        item.get("rfilename", "")
        for item in siblings
        if item.get("rfilename", "").lower().endswith(".gguf")
        and quant in item.get("rfilename", "").lower()
    ]
    if not candidates:
        raise RuntimeError(f"No {model.quantization} GGUF file found for {model.hf_repo}")
    return sorted(candidates, key=len)[0]


def _safe_model_file_name(file_name: str) -> str:
    name = Path(file_name).name
    if not name or name != file_name or not name.lower().endswith(".gguf"):
        raise RuntimeError("Resolved model filename was not safe")
    return name
