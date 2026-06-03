from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import URLError
from urllib.request import Request, urlopen
import json
import shutil
import threading
import time

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now
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
    expected_sha256: str = ""


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
_cancelled_downloads: set[str] = set()


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
    if state:
        state = _normalized_download_state(state)
    state_installed_path = state.get("local_path") if state and state.get("status") == "installed" else None
    info.update(
        {
            "installed": local_path is not None or state_installed_path is not None,
            "local_path": str(local_path) if local_path else state_installed_path,
            "download": state,
            "integrity": _model_integrity_status(model, local_path),
        }
    )
    return info


def model_integrity_manifest_status() -> dict[str, Any]:
    manifest = _trusted_integrity_manifest()
    entries = manifest.get("models", {})
    return {
        "available": bool(entries),
        "source": manifest.get("source") or "",
        "model_count": len(entries) if isinstance(entries, dict) else 0,
        "updated_at": manifest.get("updated_at") or "",
    }


def start_model_download(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)

    existing = model_status(model_id)
    if existing["installed"]:
        return {"model_id": model_id, "status": "installed", "local_path": existing["local_path"]}

    disk_check = _model_disk_preflight(model)
    if not disk_check["ok"]:
        state = {
            "model_id": model_id,
            "status": "failed",
            "bytes_downloaded": 0,
            "bytes_total": None,
            "total_bytes": None,
            "progress_percent": None,
            "download_speed_bps": None,
            "eta_seconds": None,
            "error": disk_check["message"],
            "started_at": utc_now(),
            "updated_at": utc_now(),
        }
        with _download_lock:
            _download_state[model_id] = state
        return state

    with _download_lock:
        _cancelled_downloads.discard(model_id)
        active_other = next(
            (
                item
                for item in _download_state.values()
                if item.get("model_id") != model_id and item.get("status") in {"resolving", "downloading", "cancelling"}
            ),
            None,
        )
        if active_other:
            state = {
                "model_id": model_id,
                "status": "blocked",
                "bytes_downloaded": 0,
                "bytes_total": None,
                "total_bytes": None,
                "progress_percent": None,
                "download_speed_bps": None,
                "eta_seconds": None,
                "error": f"Another model download is already {active_other.get('status')}.",
                "started_at": utc_now(),
                "updated_at": utc_now(),
            }
            _download_state[model_id] = state
            return state
        state = _download_state.get(model_id)
        if state and state["status"] in {"resolving", "downloading"}:
            return state
        _download_state[model_id] = {
            "model_id": model_id,
            "status": "resolving",
            "bytes_downloaded": 0,
            "bytes_total": None,
            "total_bytes": None,
            "progress_percent": None,
            "download_speed_bps": None,
            "eta_seconds": None,
            "error": None,
            "started_at": utc_now(),
            "updated_at": utc_now(),
        }

    thread = threading.Thread(target=_download_model, args=(model,), daemon=True)
    thread.start()
    return _normalized_download_state(_download_state[model_id])


def cancel_model_download(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    with _download_lock:
        state = _download_state.get(model_id)
        if state and state.get("status") == "installed":
            return state
        local_path = _find_local_model_file(model)
        if local_path is not None:
            installed = {
                "model_id": model_id,
                "status": "installed",
                "local_path": str(local_path),
                "bytes_downloaded": local_path.stat().st_size,
                "bytes_total": local_path.stat().st_size,
                "total_bytes": local_path.stat().st_size,
                "progress_percent": 100.0,
                "download_speed_bps": None,
                "eta_seconds": 0,
                "error": None,
                "started_at": None,
                "updated_at": utc_now(),
            }
            _download_state[model_id] = installed
            return installed
        if not state or state.get("status") not in {"resolving", "downloading"}:
            _download_state[model_id] = {
                "model_id": model_id,
                "status": "cancelled",
                "bytes_downloaded": state.get("bytes_downloaded") if state else 0,
                "bytes_total": state.get("bytes_total") if state else None,
                "total_bytes": state.get("total_bytes") if state else None,
                "progress_percent": state.get("progress_percent") if state else None,
                "download_speed_bps": None,
                "eta_seconds": None,
                "file_name": state.get("file_name") if state else None,
                "local_path": state.get("local_path") if state else None,
                "error": None,
                "started_at": state.get("started_at") if state else None,
                "updated_at": utc_now(),
            }
            return _download_state[model_id]
        _cancelled_downloads.add(model_id)
        state.update({"status": "cancelling", "updated_at": utc_now()})
        return state


def _model_to_dict(model: LocalModel) -> dict[str, Any]:
    info = asdict(model)
    info["llama_cpp_ref"] = f"{model.hf_repo}:{model.quantization}"
    return info


def _model_disk_preflight(model: LocalModel) -> dict[str, Any]:
    target_dir = models_dir() / model.id
    probe = target_dir if target_dir.exists() else _nearest_existing_parent(target_dir)
    required_bytes = int(model.approximate_download_gb * 1024 * 1024 * 1024 * 1.075)
    usage = shutil.disk_usage(probe)
    ok = int(usage.free) >= required_bytes
    return {
        "ok": ok,
        "message": (
            "Enough disk space is available."
            if ok
            else f"Not enough disk space is available for {model.name}."
        ),
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return Path.cwd()
        current = parent
    return current


def _find_local_model_file(model: LocalModel) -> Path | None:
    pattern = f"*{model.quantization.lower()}*.gguf"
    repo_dir = models_dir() / model.id
    if not repo_dir.exists():
        return None
    matches = sorted(repo_dir.glob(pattern))
    return matches[0] if matches else None


def _download_model(model: LocalModel) -> None:
    try:
        _raise_if_cancelled(model.id)
        file_name = _resolve_gguf_filename(model)
        _raise_if_cancelled(model.id)
        safe_file_name = _safe_model_file_name(file_name)
        url = f"https://huggingface.co/{model.hf_repo}/resolve/main/{quote(file_name, safe='')}"
        validate_huggingface_url(url)
        target_dir = models_dir() / model.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_file_name
        partial = target.with_suffix(target.suffix + ".part")

        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "downloading",
                    "file_name": safe_file_name,
                    "local_path": str(target),
                    "updated_at": utc_now(),
                }
            )

        request = Request(url, headers={"User-Agent": "CML-local-backend/0.1"})
        with urlopen(request, timeout=30) as response:
            total = response.headers.get("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            downloaded = 0
            started_monotonic = time.monotonic()
            with partial.open("wb") as file:
                while True:
                    _raise_if_cancelled(model.id)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    _update_model_download_progress(model.id, downloaded, total_bytes, started_monotonic)
        actual_sha256 = _sha256_file(partial)
        expected_sha256 = _expected_model_sha256(model)
        if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Model integrity check failed for {safe_file_name}: expected {expected_sha256}, got {actual_sha256}"
            )
        partial.replace(target)
        _write_integrity_manifest(model, target, actual_sha256)
        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "installed",
                    "bytes_downloaded": target.stat().st_size,
                    "bytes_total": target.stat().st_size,
                    "total_bytes": target.stat().st_size,
                    "progress_percent": 100.0,
                    "download_speed_bps": None,
                    "eta_seconds": 0,
                    "local_path": str(target),
                    "sha256": actual_sha256,
                    "integrity_status": "verified" if expected_sha256 else "recorded",
                    "updated_at": utc_now(),
                }
            )
    except Exception as exc:
        if isinstance(exc, DownloadCancelled):
            _cleanup_partial_download(model)
            with _download_lock:
                _cancelled_downloads.discard(model.id)
                _download_state[model.id].update({"status": "cancelled", "error": None, "updated_at": utc_now()})
            return
        with _download_lock:
            _download_state[model.id].update({"status": "failed", "error": str(exc), "updated_at": utc_now()})


def _update_model_download_progress(model_id: str, downloaded: int, total: int | None, started_monotonic: float) -> None:
    elapsed = max(0.001, time.monotonic() - started_monotonic)
    speed = int(downloaded / elapsed) if downloaded > 0 else None
    percent = None
    eta = None
    if total and total > 0:
        percent = round(min(100.0, (downloaded / total) * 100.0), 2)
        if speed:
            eta = max(0, int((total - downloaded) / speed))
    with _download_lock:
        _download_state[model_id].update(
            {
                "bytes_downloaded": downloaded,
                "bytes_total": total,
                "total_bytes": total,
                "progress_percent": percent,
                "download_speed_bps": speed,
                "eta_seconds": eta,
                "updated_at": utc_now(),
            }
        )


def _normalized_download_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    payload.setdefault("bytes_total", payload.get("total_bytes"))
    payload.setdefault("total_bytes", payload.get("bytes_total"))
    downloaded = payload.get("bytes_downloaded") or 0
    total = payload.get("bytes_total") or payload.get("total_bytes")
    payload["bytes_downloaded"] = downloaded
    if total and payload.get("progress_percent") is None:
        payload["progress_percent"] = round(min(100.0, (downloaded / total) * 100.0), 2)
    payload.setdefault("download_speed_bps", None)
    payload.setdefault("eta_seconds", None)
    payload.setdefault("started_at", None)
    payload.setdefault("updated_at", None)
    payload.setdefault("sha256", None)
    payload.setdefault("integrity_status", None)
    return payload


class DownloadCancelled(RuntimeError):
    pass


def _raise_if_cancelled(model_id: str) -> None:
    with _download_lock:
        if model_id in _cancelled_downloads:
            raise DownloadCancelled()


def _cleanup_partial_download(model: LocalModel) -> None:
    state = _download_state.get(model.id) or {}
    local_path = state.get("local_path")
    if not local_path:
        return
    partial = Path(str(local_path)).with_suffix(Path(str(local_path)).suffix + ".part")
    try:
        partial.unlink(missing_ok=True)
    except OSError:
        pass


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


def _expected_model_sha256(model: LocalModel) -> str:
    if model.expected_sha256:
        return model.expected_sha256
    trusted = _trusted_manifest_expected_sha256(model)
    if trusted:
        return trusted
    manifest = models_dir() / model.id / "integrity.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    expected = payload.get("expected_sha256", "")
    return expected if isinstance(expected, str) else ""


def _trusted_manifest_expected_sha256(model: LocalModel) -> str:
    manifest = _trusted_integrity_manifest()
    models = manifest.get("models", {})
    if not isinstance(models, dict):
        return ""
    entry = models.get(model.id) or {}
    if not isinstance(entry, dict):
        return ""
    sha256 = entry.get("sha256") or entry.get("expected_sha256") or ""
    return sha256 if _is_sha256(str(sha256)) else ""


def _trusted_integrity_manifest() -> dict[str, Any]:
    settings = get_settings()
    if settings.model_integrity_manifest_url:
        return _read_remote_integrity_manifest(settings.model_integrity_manifest_url)
    if settings.model_integrity_manifest_path:
        return _read_local_integrity_manifest(settings.model_integrity_manifest_path)
    default_path = Path(__file__).resolve().parents[3] / "docs" / "model-integrity-manifest.json"
    return _read_local_integrity_manifest(default_path)


def _read_local_integrity_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"source": str(path), "models": {}}
    if not isinstance(payload, dict):
        return {"source": str(path), "models": {}}
    payload.setdefault("source", str(path))
    payload.setdefault("models", {})
    return payload


def _read_remote_integrity_manifest(url: str) -> dict[str, Any]:
    if not url.startswith("https://"):
        return {"source": url, "models": {}, "error": "Remote integrity manifests must use https."}
    request = Request(url, headers={"User-Agent": "CML-local-backend/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(512 * 1024 + 1)
    except OSError as exc:
        return {"source": url, "models": {}, "error": str(exc)}
    if len(raw) > 512 * 1024:
        return {"source": url, "models": {}, "error": "Remote integrity manifest is too large."}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"source": url, "models": {}, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"source": url, "models": {}, "error": "Remote integrity manifest must be a JSON object."}
    payload.setdefault("source", url)
    payload.setdefault("models", {})
    return payload


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_integrity_manifest(model: LocalModel, target: Path, sha256: str) -> None:
    manifest = {
        "model_id": model.id,
        "file_name": target.name,
        "sha256": sha256,
        "expected_sha256": _expected_model_sha256(model),
        "status": "verified" if _expected_model_sha256(model) else "recorded",
        "updated_at": utc_now(),
    }
    (target.parent / "integrity.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _model_integrity_status(model: LocalModel, local_path: Path | None) -> dict[str, Any]:
    if local_path is None:
        return {"status": "missing", "sha256": None, "expected_sha256": _expected_model_sha256(model)}
    manifest = local_path.parent / "integrity.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unverified",
            "sha256": None,
            "expected_sha256": _expected_model_sha256(model),
            "detail": "No integrity manifest exists for this local model file.",
        }
    expected = str(payload.get("expected_sha256") or "")
    actual = str(payload.get("sha256") or "")
    if expected:
        status = "verified" if actual.lower() == expected.lower() else "mismatch"
    else:
        status = "recorded" if actual else "unverified"
    return {"status": status, "sha256": actual or None, "expected_sha256": expected or None}
