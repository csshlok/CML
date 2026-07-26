import hashlib
import importlib.util
import json
import math
import re
import ast
import threading
import time
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now
from backend.app.core.derived_state import chunk_tuple_values, query_epoch_snapshot_conn
from backend.app.core.encrypted_storage import (
    delete_source_chunk_encrypted_content,
    page_from_encrypted_row,
    plaintext_column_for_text,
    source_from_encrypted_row,
)
from backend.app.core.turbovec_runtime import apply_source_delta_to_sidecar

HASH_EMBEDDING_DIMENSIONS = 128
CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 40
EMBEDDING_TARGET_TOKENS = 240
EMBEDDING_TOKEN_OVERLAP = 24
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MANAGED_EMBEDDING_MODELS = frozenset({DEFAULT_EMBEDDING_MODEL})
MINILM_DOWNLOAD_PATTERNS = (
    "1_Pooling/config.json",
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
MINILM_APPROXIMATE_DOWNLOAD_BYTES = 100 * 1024 * 1024

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def embed_text(text: str) -> list[float]:
    config = embedding_config()
    if config["provider"] == "sentence-transformers":
        return _embed_with_sentence_transformers(config["model"], config["cache_dir"], text)
    return _embed_with_hash(text)


def embedding_status(*, probe_model: bool = True) -> dict:
    config = embedding_config()
    status = {
        "provider": config["provider"],
        "model": config["model"] if config["provider"] != "hash" else "hash",
        "dimensions": config["dimensions"] if config["provider"] != "hash" else HASH_EMBEDDING_DIMENSIONS,
        "available": True,
        "detail": "Using deterministic hash embeddings.",
        "setup_required": False,
        "cache_dir": str(config["cache_dir"]) if config["cache_dir"] else None,
    }
    if config["provider"] == "sentence-transformers":
        if importlib.util.find_spec("sentence_transformers") is not None:
            local_model_path = _find_local_sentence_transformer_path(
                str(config["model"]),
                config["cache_dir"],
            )
            if local_model_path is None:
                status["available"] = False
                status["setup_required"] = True
                status["detail"] = (
                    "SentenceTransformers is installed, but the local embedding model files "
                    "were not found in the selected folder."
                )
            elif probe_model:
                try:
                    _embed_with_sentence_transformers(config["model"], config["cache_dir"], "vault setup test")
                    status["detail"] = "SentenceTransformers embedding model is available."
                except Exception as exc:
                    status["available"] = False
                    status["setup_required"] = True
                    status["detail"] = f"SentenceTransformers is installed, but the embedding model is not ready: {exc}"
            else:
                status["detail"] = "The local SentenceTransformers model files are ready."
        else:
            status["available"] = False
            status["setup_required"] = True
            status["detail"] = "SentenceTransformers is not installed in this Python runtime."
    return status


_EMBEDDING_DOWNLOAD_LOCK = threading.Lock()
_EMBEDDING_DOWNLOAD_STATE = {
    "model_id": DEFAULT_EMBEDDING_MODEL,
    "status": "idle",
    "bytes_downloaded": 0,
    "bytes_total": None,
    "total_bytes": None,
    "progress_percent": None,
    "download_speed_bps": None,
    "eta_seconds": None,
    "file_name": None,
    "local_path": None,
    "error": None,
    "started_at": None,
    "updated_at": None,
}
_EMBEDDING_DOWNLOAD_THREAD: threading.Thread | None = None
_EMBEDDING_DOWNLOAD_PROCESS: subprocess.Popen[bytes] | None = None
_EMBEDDING_DOWNLOAD_STATE_LOADED_FROM: Path | None = None
_EMBEDDING_DOWNLOAD_LAST_PERSISTED = 0.0


def _embedding_download_state_path() -> Path:
    return get_settings().data_dir / "embedding-download.json"


def _ensure_embedding_download_state_loaded() -> None:
    global _EMBEDDING_DOWNLOAD_STATE_LOADED_FROM
    state_path = _embedding_download_state_path()
    if _EMBEDDING_DOWNLOAD_STATE_LOADED_FROM == state_path:
        return
    if _EMBEDDING_DOWNLOAD_STATE.get("status") != "idle":
        _EMBEDDING_DOWNLOAD_STATE_LOADED_FROM = state_path
        return
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        loaded = payload.get("download", {}) if isinstance(payload, dict) else {}
        if not isinstance(loaded, dict):
            loaded = {}
    except (OSError, json.JSONDecodeError):
        loaded = {}
    if loaded:
        _EMBEDDING_DOWNLOAD_STATE.update(loaded)
        if _EMBEDDING_DOWNLOAD_STATE.get("status") in {"queued", "downloading"}:
            local_path_value = str(_EMBEDDING_DOWNLOAD_STATE.get("local_path") or "")
            local_path = Path(local_path_value) if local_path_value else None
            downloaded = (
                _directory_size(local_path)
                if local_path is not None and local_path.exists()
                else int(_EMBEDDING_DOWNLOAD_STATE.get("bytes_downloaded") or 0)
            )
            _EMBEDDING_DOWNLOAD_STATE.update(
                {
                    "status": "interrupted",
                    "bytes_downloaded": downloaded,
                    "download_speed_bps": None,
                    "eta_seconds": None,
                    "resumable": bool(local_path and local_path.exists()),
                    "error": "The app restarted during this download. Resume or cancel it.",
                    "updated_at": utc_now(),
                }
            )
    _EMBEDDING_DOWNLOAD_STATE_LOADED_FROM = state_path
    if loaded:
        with _EMBEDDING_DOWNLOAD_LOCK:
            _persist_embedding_download_state_locked()


def _persist_embedding_download_state_locked(*, throttle_seconds: float = 0.0) -> None:
    global _EMBEDDING_DOWNLOAD_LAST_PERSISTED
    now = time.monotonic()
    if throttle_seconds and now - _EMBEDDING_DOWNLOAD_LAST_PERSISTED < throttle_seconds:
        return
    state_path = _embedding_download_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": utc_now(),
                "download": _EMBEDDING_DOWNLOAD_STATE,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(state_path)
    _EMBEDDING_DOWNLOAD_LAST_PERSISTED = now


def embedding_download_status() -> dict:
    _ensure_embedding_download_state_loaded()
    with _EMBEDDING_DOWNLOAD_LOCK:
        return _normalized_download_state(_EMBEDDING_DOWNLOAD_STATE)


def start_embedding_model_download(cache_dir: str | None = None, model: str | None = None) -> dict:
    _ensure_embedding_download_state_loaded()
    target_model = (model or get_settings().embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
    if target_model not in MANAGED_EMBEDDING_MODELS:
        raise ValueError(
            "Vault can only download its curated public memory-search model. "
            "Import other embedding models from an existing local folder."
        )
    target_dir = Path(cache_dir).expanduser() if cache_dir and cache_dir.strip() else (
        get_settings().data_dir / "models" / "embeddings"
    )
    model_dir = target_dir / target_model.rsplit("/", 1)[-1]
    dependency_error = _embedding_download_dependency_error()
    if dependency_error:
        with _EMBEDDING_DOWNLOAD_LOCK:
            _EMBEDDING_DOWNLOAD_STATE.update(
                {
                    "model_id": target_model,
                    "status": "failed",
                    "local_path": str(model_dir),
                    "error": dependency_error,
                    "updated_at": utc_now(),
                }
            )
            _persist_embedding_download_state_locked()
            return _normalized_download_state(_EMBEDDING_DOWNLOAD_STATE)
    with _EMBEDDING_DOWNLOAD_LOCK:
        global _EMBEDDING_DOWNLOAD_THREAD
        if (
            _EMBEDDING_DOWNLOAD_STATE["status"] in {"queued", "downloading"}
            and _EMBEDDING_DOWNLOAD_THREAD is not None
            and _EMBEDDING_DOWNLOAD_THREAD.is_alive()
        ):
            return dict(_EMBEDDING_DOWNLOAD_STATE)
        _EMBEDDING_DOWNLOAD_STATE.update(
            {
                "model_id": target_model,
                "status": "queued",
                "bytes_downloaded": 0,
                "bytes_total": None,
                "total_bytes": None,
                "progress_percent": None,
                "download_speed_bps": None,
                "eta_seconds": None,
                "file_name": target_model,
                "local_path": str(model_dir),
                "error": None,
                "started_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        _persist_embedding_download_state_locked()
        _EMBEDDING_DOWNLOAD_THREAD = threading.Thread(
            target=_download_embedding_model,
            args=(target_model, model_dir),
            daemon=True,
            name="cml-embedding-download",
        )
        _EMBEDDING_DOWNLOAD_THREAD.start()
        return _normalized_download_state(_EMBEDDING_DOWNLOAD_STATE)


def cancel_embedding_model_download() -> dict:
    _ensure_embedding_download_state_loaded()
    process: subprocess.Popen[bytes] | None = None
    with _EMBEDDING_DOWNLOAD_LOCK:
        if _EMBEDDING_DOWNLOAD_STATE["status"] in {"queued", "downloading", "interrupted"}:
            _EMBEDDING_DOWNLOAD_STATE["status"] = "cancelling"
            _EMBEDDING_DOWNLOAD_STATE["error"] = None
            _EMBEDDING_DOWNLOAD_STATE["updated_at"] = utc_now()
            _persist_embedding_download_state_locked()
            process = _EMBEDDING_DOWNLOAD_PROCESS
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    with _EMBEDDING_DOWNLOAD_LOCK:
        if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelling":
            _EMBEDDING_DOWNLOAD_STATE["status"] = "cancelled"
            _EMBEDDING_DOWNLOAD_STATE["error"] = "Download cancelled."
            _EMBEDDING_DOWNLOAD_STATE["updated_at"] = utc_now()
            _persist_embedding_download_state_locked()
        return _normalized_download_state(_EMBEDDING_DOWNLOAD_STATE)


def _download_embedding_model(model: str, model_dir: Path) -> None:
    global _EMBEDDING_DOWNLOAD_PROCESS
    with _EMBEDDING_DOWNLOAD_LOCK:
        if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelled":
            return
        _EMBEDDING_DOWNLOAD_STATE["status"] = "downloading"
        _EMBEDDING_DOWNLOAD_STATE["updated_at"] = utc_now()
        _persist_embedding_download_state_locked()
    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        expected_size = MINILM_APPROXIMATE_DOWNLOAD_BYTES
        started_monotonic = time.monotonic()
        initial_bytes = _directory_size(model_dir)
        _update_embedding_download_progress(
            bytes_downloaded=initial_bytes,
            bytes_total=expected_size,
            started_monotonic=started_monotonic,
            initial_bytes=initial_bytes,
        )

        _EMBEDDING_DOWNLOAD_PROCESS = subprocess.Popen(
            [
                sys.executable,
                "-s",
                "-m",
                "backend.app.core.embedding_download_worker",
                "--model",
                model,
                "--target",
                str(model_dir),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        while _EMBEDDING_DOWNLOAD_PROCESS.poll() is None:
            with _EMBEDDING_DOWNLOAD_LOCK:
                if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelling":
                    break
            _update_embedding_download_progress(
                bytes_downloaded=_directory_size(model_dir),
                bytes_total=expected_size,
                started_monotonic=started_monotonic,
                initial_bytes=initial_bytes,
            )
            time.sleep(0.25)
        return_code = _EMBEDDING_DOWNLOAD_PROCESS.wait(timeout=5)
        stderr = (
            _EMBEDDING_DOWNLOAD_PROCESS.stderr.read().decode("utf-8", errors="replace")
            if _EMBEDDING_DOWNLOAD_PROCESS.stderr is not None
            else ""
        )
        _EMBEDDING_DOWNLOAD_PROCESS = None
        with _EMBEDDING_DOWNLOAD_LOCK:
            if _EMBEDDING_DOWNLOAD_STATE["status"] in {"cancelling", "cancelled"}:
                return
        if return_code != 0:
            raise RuntimeError(stderr.strip() or f"Memory-search download exited with code {return_code}.")
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(str(model_dir), local_files_only=True)
        configure_embedding_runtime("sentence-transformers", str(model_dir), model)
        with _EMBEDDING_DOWNLOAD_LOCK:
            installed_size = _directory_size(model_dir)
            _EMBEDDING_DOWNLOAD_STATE.update(
                {
                    "status": "installed",
                    "bytes_downloaded": installed_size,
                    "bytes_total": installed_size,
                    "total_bytes": installed_size,
                    "progress_percent": 100.0,
                    "download_speed_bps": None,
                    "eta_seconds": 0,
                    "error": None,
                    "updated_at": utc_now(),
                }
            )
            _persist_embedding_download_state_locked()
    except Exception as exc:
        _EMBEDDING_DOWNLOAD_PROCESS = None
        with _EMBEDDING_DOWNLOAD_LOCK:
            if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelled":
                return
            _EMBEDDING_DOWNLOAD_STATE.update(
                {
                    "status": "failed",
                    "error": _friendly_embedding_download_error(exc),
                    "updated_at": utc_now(),
                }
            )
            _persist_embedding_download_state_locked()


def _embedding_download_dependency_error() -> str | None:
    if importlib.util.find_spec("sentence_transformers") is None:
        return "SentenceTransformers is not installed in this Python runtime."
    if importlib.util.find_spec("huggingface_hub") is None:
        return "The Hugging Face download runtime is not installed."
    return None


def _friendly_embedding_download_error(exc: Exception) -> str:
    message = str(exc)
    if "CML_HF_AUTH_REQUIRED" in message:
        return (
            "Hugging Face requested an account or approval for this model. "
            "Vault stopped without sending credentials; choose the approved public model or a local folder."
        )
    if "CML_HF_DOWNLOAD_FAILED:" in message:
        return "Hugging Face could not complete the public model download. Check your connection and try again."
    try:
        from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError
    except ImportError:
        return str(exc)
    if isinstance(exc, GatedRepoError):
        return (
            "This Hugging Face model requires an account or approval. "
            "Vault onboarding only supports public models that need no account."
        )
    if isinstance(exc, RepositoryNotFoundError):
        return "Vault could not find the approved public memory-search model on Hugging Face."
    if isinstance(exc, HfHubHTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in {401, 403}:
            return (
                "Hugging Face requested authentication for this model. "
                "Vault did not send credentials and stopped the download."
            )
        return "Hugging Face could not complete the model download. Check your connection and try again."
    return message


def _update_embedding_download_progress(
    *,
    bytes_downloaded: int,
    bytes_total: int | None,
    started_monotonic: float,
    initial_bytes: int = 0,
) -> None:
    elapsed = max(0.001, time.monotonic() - started_monotonic)
    transferred = max(0, bytes_downloaded - initial_bytes)
    speed = int(transferred / elapsed) if transferred > 0 else None
    eta = None
    percent = None
    if bytes_total and bytes_total > 0:
        percent = round(min(100.0, (bytes_downloaded / bytes_total) * 100.0), 2)
        if speed:
            eta = max(0, int((bytes_total - bytes_downloaded) / speed))
    with _EMBEDDING_DOWNLOAD_LOCK:
        _EMBEDDING_DOWNLOAD_STATE.update(
            {
                "bytes_downloaded": bytes_downloaded,
                "bytes_total": bytes_total,
                "total_bytes": bytes_total,
                "progress_percent": percent,
                "download_speed_bps": speed,
                "eta_seconds": eta,
                "updated_at": utc_now(),
            }
        )
        _persist_embedding_download_state_locked(throttle_seconds=0.25)


def _normalized_download_state(state: dict) -> dict:
    payload = dict(state)
    if "bytes_total" not in payload:
        payload["bytes_total"] = payload.get("total_bytes")
    if "total_bytes" not in payload:
        payload["total_bytes"] = payload.get("bytes_total")
    downloaded = payload.get("bytes_downloaded") or 0
    total = payload.get("bytes_total") or payload.get("total_bytes")
    payload["bytes_downloaded"] = downloaded
    if total and not payload.get("progress_percent"):
        payload["progress_percent"] = round(min(100.0, (downloaded / total) * 100.0), 2)
    return payload


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def require_embeddings_available(feature: str = "semantic memory") -> None:
    status = embedding_status()
    if status["available"]:
        return
    raise RuntimeError(
        f"{feature} requires the local embedding model, but embeddings are unavailable: {status['detail']}"
    )


def embedding_config() -> dict:
    settings = get_settings()
    provider = settings.embedding_provider
    if provider == "hash" and not settings.allow_hash_embeddings:
        provider = "sentence-transformers"
    config = {
        "provider": provider,
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "cache_dir": settings.embedding_cache_dir,
    }
    config_path = _embedding_config_path()
    if config_path.exists():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict):
            provider = saved.get("provider")
            cache_dir = saved.get("cache_dir")
            model = saved.get("model")
            if provider == "sentence-transformers" or (provider == "hash" and settings.allow_hash_embeddings):
                config["provider"] = provider
            if isinstance(cache_dir, str) and cache_dir.strip():
                config["cache_dir"] = Path(cache_dir)
            if isinstance(model, str) and model.strip():
                config["model"] = model.strip()
    return config


def active_embedding_model_id() -> str:
    config = embedding_config()
    if config["provider"] == "sentence-transformers":
        return str(config["model"])
    return "hash-dev"


def normalize_for_hash(text: str) -> str:
    return " ".join((text or "").split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def configure_embedding_runtime(provider: str, cache_dir: str | None = None, model: str | None = None) -> dict:
    if provider == "hash" and not get_settings().allow_hash_embeddings:
        raise ValueError("Hash embeddings are only available in explicit dev/test mode")
    if provider not in {"hash", "sentence-transformers"}:
        raise ValueError("Embedding provider must be 'sentence-transformers'")
    config_path = _embedding_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if provider == "sentence-transformers" and not (cache_dir or "").strip():
        raise ValueError("Choose a local embedding model folder or cache folder before continuing")
    payload = {
        "provider": provider,
        "cache_dir": cache_dir or "",
        "model": model or get_settings().embedding_model,
    }
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    global _SENTENCE_TRANSFORMER_MODEL
    global _SENTENCE_TRANSFORMER_MODEL_NAME
    global _SENTENCE_TRANSFORMER_CACHE_DIR
    _SENTENCE_TRANSFORMER_MODEL = None
    _SENTENCE_TRANSFORMER_MODEL_NAME = None
    _SENTENCE_TRANSFORMER_CACHE_DIR = None
    return embedding_status(probe_model=False)


def _embedding_config_path() -> Path:
    return get_settings().data_dir / "embedding-runtime.json"


def _embed_with_hash(text: str) -> list[float]:
    vector = [0.0] * HASH_EMBEDDING_DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % HASH_EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


_SENTENCE_TRANSFORMER_MODEL = None
_SENTENCE_TRANSFORMER_MODEL_NAME = None
_SENTENCE_TRANSFORMER_CACHE_DIR = None


def _get_sentence_transformer(model_name: str, cache_dir=None):
    global _SENTENCE_TRANSFORMER_MODEL
    global _SENTENCE_TRANSFORMER_MODEL_NAME
    global _SENTENCE_TRANSFORMER_CACHE_DIR
    cache_key = str(cache_dir) if cache_dir else ""
    if (
        _SENTENCE_TRANSFORMER_MODEL is not None
        and _SENTENCE_TRANSFORMER_MODEL_NAME == model_name
        and _SENTENCE_TRANSFORMER_CACHE_DIR == cache_key
    ):
        return _SENTENCE_TRANSFORMER_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("install sentence-transformers to use real local embeddings") from exc
    model_ref = _resolve_sentence_transformer_ref(model_name, cache_dir)
    kwargs = {"local_files_only": True}
    if cache_dir and model_ref == model_name:
        kwargs["cache_folder"] = str(cache_dir)
    _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer(model_ref, **kwargs)
    _SENTENCE_TRANSFORMER_MODEL_NAME = model_name
    _SENTENCE_TRANSFORMER_CACHE_DIR = cache_key
    return _SENTENCE_TRANSFORMER_MODEL


def _resolve_sentence_transformer_ref(model_name: str, cache_dir) -> str:
    if cache_dir is None:
        raise RuntimeError("choose a local embedding model folder before using memory search")
    model_path = Path(cache_dir)
    if not model_path.exists():
        raise RuntimeError(f"embedding model path does not exist: {model_path}")
    local_model_path = _find_local_sentence_transformer_path(model_name, model_path)
    if local_model_path is not None:
        return str(local_model_path)
    return model_name


def _find_local_sentence_transformer_path(model_name: str, cache_dir) -> Path | None:
    if cache_dir is None:
        return None
    cache_path = Path(cache_dir)
    if not cache_path.is_dir():
        return None

    model_folder_name = model_name.rstrip("/").rsplit("/", 1)[-1]
    candidates = [cache_path, cache_path / model_folder_name]
    hub_model_root = cache_path / f"models--{model_name.replace('/', '--')}" / "snapshots"
    if hub_model_root.is_dir():
        candidates.extend(path for path in hub_model_root.iterdir() if path.is_dir())

    for candidate in candidates:
        if (candidate / "modules.json").is_file() or (candidate / "config.json").is_file():
            return candidate
    return None


def _embed_with_sentence_transformers(model_name: str, cache_dir, text: str) -> list[float]:
    model = _get_sentence_transformer(model_name, cache_dir)
    vector = model.encode(text or "", normalize_embeddings=True)
    return [float(value) for value in vector.tolist()]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False))


def encode_embedding(vector: list[float]) -> str:
    return json.dumps([round(value, 6) for value in vector], separators=(",", ":"))


def decode_embedding(raw: str) -> list[float]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [float(value) for value in values] if isinstance(values, list) else []


def chunk_text(text: str) -> list[str]:
    return [item["text"] for item in chunk_text_for_source({}, text)]


def chunk_text_for_source(
    source: dict,
    text: str,
    *,
    tokenizer=None,
    max_seq_length: int | None = None,
) -> list[dict[str, str]]:
    normalized = str(text or "").replace("\r\n", "\n")
    profile = detect_content_profile(source, normalized)
    if profile == "conversation":
        chunks = (
            [_chunk_payload(normalized, "conversation", "conversation_token_window")]
            if tokenizer is not None and max_seq_length and normalized.strip()
            else _conversation_chunks(normalized)
        )
    elif profile == "markdown":
        chunks = _markdown_chunks(normalized)
    elif profile == "code":
        chunks = _code_chunks(source, normalized)
    elif profile == "diff":
        chunks = _diff_chunks(normalized)
    elif profile == "log":
        chunks = _log_chunks(normalized)
    elif profile == "structured_json":
        chunks = _structured_chunks(normalized, profile=profile)
    elif profile == "table_csv":
        chunks = _csv_chunks(
            normalized,
            delimiter="\t" if _looks_like_tsv(source, normalized) else ",",
        )
    else:
        chunks = _word_window_chunks(normalized, profile=profile)
    if tokenizer is None or not max_seq_length:
        return chunks
    return _embedding_safe_chunks(
        chunks,
        tokenizer=tokenizer,
        max_seq_length=max_seq_length,
    )


def _embedding_safe_chunks(
    chunks: list[dict[str, str]],
    *,
    tokenizer,
    max_seq_length: int,
) -> list[dict[str, str]]:
    special_tokens = max(0, int(tokenizer.num_special_tokens_to_add(pair=False)))
    total_budget = max(8, min(int(max_seq_length), EMBEDDING_TARGET_TOKENS))
    content_budget = max(1, total_budget - special_tokens)
    overlap = min(EMBEDDING_TOKEN_OVERLAP, max(0, content_budget // 4))
    safe: list[dict[str, str]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        spans = _token_spans(tokenizer, text)
        if len(spans) <= content_budget:
            safe.append(chunk)
            continue
        windows: list[tuple[int, int, int, int]] = []
        token_start = 0
        while token_start < len(spans):
            desired_end = min(len(spans), token_start + content_budget)
            fitted = None
            preferred_start = _word_boundary_start(text, spans[token_start][0])
            for char_start in dict.fromkeys((preferred_start, spans[token_start][0])):
                token_end = desired_end
                while token_end > token_start:
                    char_end = spans[token_end - 1][1]
                    candidate = text[char_start:char_end].strip()
                    if _model_token_count(tokenizer, candidate) <= total_budget:
                        fitted = (token_end, char_start, char_end)
                        break
                    token_end -= 1
                if fitted is not None and (
                    fitted[0] >= len(spans)
                    or fitted[0] - token_start > overlap
                    or char_start == spans[token_start][0]
                ) and char_start >= spans[max(0, token_start - overlap)][0]:
                    break
                fitted = None
            if fitted is None:
                raise RuntimeError(
                    "The active embedding tokenizer could not fit one token inside its sequence limit"
                )
            token_end, char_start, char_end = fitted
            windows.append((token_start, token_end, char_start, char_end))
            if token_end >= len(spans):
                break
            token_start = max(token_start + 1, token_end - overlap)
        for segment_index, (token_start, token_end, char_start, char_end) in enumerate(windows):
            segment_text = text[char_start:char_end].strip()
            if not segment_text:
                continue
            try:
                metadata = json.loads(chunk.get("chunk_meta_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            metadata.update(
                {
                    "embedding_segment_index": segment_index,
                    "embedding_segment_count": len(windows),
                    "embedding_token_start": token_start,
                    "embedding_token_end": token_end,
                    "embedding_content_tokens": token_end - token_start,
                    "embedding_total_token_budget": total_budget,
                    "embedding_original_content_tokens": len(spans),
                }
            )
            safe.append(
                {
                    **chunk,
                    "text": segment_text,
                    "chunk_meta_json": json.dumps(metadata, separators=(",", ":")),
                }
            )
    return safe


def _word_boundary_start(text: str, offset: int) -> int:
    start = max(0, min(len(text), int(offset)))
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return start


def _model_token_count(tokenizer, text: str) -> int:
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
        return_attention_mask=False,
    )
    return len(encoded.get("input_ids") or [])


def _token_spans(tokenizer, text: str) -> list[tuple[int, int]]:
    try:
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_attention_mask=False,
            return_offsets_mapping=True,
        )
        offsets = encoded.get("offset_mapping") or []
        spans = [(int(start), int(end)) for start, end in offsets if int(end) > int(start)]
        if spans:
            return spans
    except (TypeError, NotImplementedError, ValueError):
        pass
    return _word_token_spans(tokenizer, text)


def _word_token_spans(tokenizer, text: str) -> list[tuple[int, int]]:
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    spans: list[tuple[int, int]] = []
    for word in words:
        token_ids = tokenizer(
            word.group(0),
            add_special_tokens=False,
            truncation=False,
            return_attention_mask=False,
        ).get("input_ids") or []
        spans.extend([(word.start(), word.end())] * max(1, len(token_ids)))
    return spans


def detect_content_profile(source: dict, text: str) -> str:
    source_type = str(source.get("source_type") or "").lower()
    title = str(source.get("title") or "")
    path = str(source.get("original_path") or "")
    suffix = Path(path or title).suffix.lower()
    if source_type in {"chat_transcript", "external_transcript"}:
        return "conversation"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rs", ".c", ".cpp", ".cs"}:
        return "code"
    if suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "structured_json"
    if suffix in {".csv", ".tsv"}:
        return "table_csv"
    if "diff --git" in text or "\n@@" in text:
        return "diff"
    if "traceback (most recent call last)" in text.lower() or _looks_like_log(text):
        return "log"
    if re.search(r"^\s{0,3}(def |class |function |export function |const [A-Za-z_][A-Za-z0-9_]*\s*=)", text, re.MULTILINE):
        return "code"
    if re.search(r"^#{1,6}\s", text, re.MULTILINE):
        return "markdown"
    if re.search(r"^\s*[\{\[]", text) and re.search(r"[\}\]]\s*$", text):
        return "structured_json"
    if re.search(r"^[A-Za-z0-9_\" ]+(,|\t)[A-Za-z0-9_\" ]+", text, re.MULTILINE):
        return "table_csv"
    return "prose"


def _word_window_chunks(text: str, *, profile: str) -> list[dict[str, str]]:
    words = text.split()
    if not words:
        return []

    chunks: list[dict[str, str]] = []
    step = max(1, CHUNK_SIZE_WORDS - CHUNK_OVERLAP_WORDS)
    for start in range(0, len(words), step):
        chunk_text = " ".join(words[start : start + CHUNK_SIZE_WORDS]).strip()
        if chunk_text:
            chunks.append(
                {
                    "text": chunk_text,
                    "content_profile": profile,
                    "chunk_strategy": "word_window",
                    "chunk_meta_json": json.dumps({"start_word": start}, separators=(",", ":")),
                }
            )
        if start + CHUNK_SIZE_WORDS >= len(words):
            break
    return chunks


def _conversation_chunks(text: str) -> list[dict[str, str]]:
    turns = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    if not turns:
        return []
    chunks: list[dict[str, str]] = []
    current: list[str] = []
    for turn in turns:
        current.append(turn)
        if len(current) >= 6 or sum(len(item.split()) for item in current) >= CHUNK_SIZE_WORDS:
            chunks.append(_chunk_payload("\n\n".join(current), "conversation", "turn_group"))
            current = current[-1:]
    if current:
        chunks.append(_chunk_payload("\n\n".join(current), "conversation", "turn_group"))
    return chunks


def _markdown_chunks(text: str) -> list[dict[str, str]]:
    sections = re.split(r"(?=^#{1,6}\s)", text, flags=re.MULTILINE)
    chunks = [_chunk_payload(section.strip(), "markdown", "markdown_section") for section in sections if section.strip()]
    return chunks or _word_window_chunks(text, profile="markdown")


def _code_chunks(source: dict, text: str) -> list[dict[str, str]]:
    suffix = Path(str(source.get("original_path") or source.get("title") or "")).suffix.lower()
    if suffix == ".py":
        chunks = _python_symbol_chunks(text)
        if chunks:
            return chunks
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".cs", ".c", ".cpp", ".rs"}:
        chunks = _brace_language_symbol_chunks(text, suffix=suffix)
        if chunks:
            return chunks
    chunks = _generic_code_chunks(text)
    return chunks or _word_window_chunks(text, profile="code")


def _python_symbol_chunks(text: str) -> list[dict[str, str]]:
    parse_text = _strip_leading_code_label(text)
    try:
        tree = ast.parse(parse_text)
    except SyntaxError:
        return []
    lines = parse_text.splitlines()
    chunks: list[dict[str, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = max(0, int(getattr(node, "lineno", 1)) - 1)
        end = max(start + 1, int(getattr(node, "end_lineno", start + 1)))
        snippet = "\n".join(lines[start:end]).strip()
        if snippet:
            chunks.append(
                _chunk_payload(
                    snippet,
                    "code",
                    "python_ast_symbol",
                    {"symbol": getattr(node, "name", ""), "line_start": start + 1, "line_end": end},
                )
            )
    return chunks


def _generic_code_chunks(text: str) -> list[dict[str, str]]:
    lines = _strip_leading_code_label(text).splitlines()
    if not lines:
        return []
    boundary = re.compile(r"^\s*(class |def |async def |function |export function |const [A-Za-z_][A-Za-z0-9_]*\s*=|func )")
    chunks: list[dict[str, str]] = []
    current: list[str] = []
    for line in lines:
        if current and boundary.search(line):
            chunks.append(_chunk_payload("\n".join(current).strip(), "code", "line_symbol_group"))
            current = []
        current.append(line)
        if len(current) >= 80:
            chunks.append(_chunk_payload("\n".join(current).strip(), "code", "line_symbol_group"))
            current = []
    if current:
        chunks.append(_chunk_payload("\n".join(current).strip(), "code", "line_symbol_group"))
    return [chunk for chunk in chunks if chunk["text"]]


def _brace_language_symbol_chunks(text: str, *, suffix: str) -> list[dict[str, str]]:
    parse_text = _strip_leading_code_label(text)
    lines = parse_text.splitlines()
    if not lines:
        return []
    boundaries = _brace_language_boundaries(suffix)
    if not boundaries:
        return []
    chunks: list[dict[str, str]] = []
    start_index = 0
    while start_index < len(lines):
        matched = None
        for index in range(start_index, len(lines)):
            line = lines[index]
            for pattern in boundaries:
                match = pattern.search(line)
                if match:
                    matched = (index, match)
                    break
            if matched:
                break
        if not matched:
            break
        symbol_start, match = matched
        symbol_name = _extract_symbol_name(match)
        symbol_end = _brace_block_end(lines, symbol_start)
        if symbol_end <= symbol_start:
            start_index = symbol_start + 1
            continue
        snippet = "\n".join(lines[symbol_start:symbol_end]).strip()
        if snippet:
            chunks.append(
                _chunk_payload(
                    snippet,
                    "code",
                    "brace_symbol_block",
                    {"symbol": symbol_name, "line_start": symbol_start + 1, "line_end": symbol_end},
                )
            )
        start_index = max(symbol_end, symbol_start + 1)
    return chunks


def _brace_language_boundaries(suffix: str) -> list[re.Pattern[str]]:
    common = [
        re.compile(r"^\s*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+function\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*function\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\("),
        re.compile(r"^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?[A-Za-z_][A-Za-z0-9_]*\s*=>"),
    ]
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return common + [
            re.compile(r"^\s*interface\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*="),
        ]
    if suffix == ".go":
        return [
            re.compile(r"^\s*type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+struct\b"),
            re.compile(r"^\s*func\s*(?:\([^\)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("),
        ]
    if suffix == ".rs":
        return [
            re.compile(r"^\s*(?:pub\s+)?struct\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:pub\s+)?enum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:pub\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("),
            re.compile(r"^\s*impl\b.*\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"),
        ]
    if suffix in {".java", ".cs", ".c", ".cpp"}:
        return [
            re.compile(r"^\s*(?:public|private|protected|static|final|sealed|abstract|\s)*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:public|private|protected|static|final|sealed|abstract|\s)*(?:interface|enum)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:public|private|protected|static|virtual|async|inline|constexpr|template<.*>\s*)*[\w:<>\[\]]+\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*\{?"),
        ]
    return []


def _extract_symbol_name(match: re.Match[str]) -> str:
    try:
        return str(match.group("name") or "")
    except IndexError:
        return ""


def _brace_block_end(lines: list[str], start_index: int) -> int:
    brace_depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = re.sub(r"//.*$", "", lines[index])
        brace_depth += line.count("{")
        if line.count("{") > 0:
            seen_open = True
        brace_depth -= line.count("}")
        if seen_open and brace_depth <= 0:
            return index + 1
        if not seen_open and index > start_index and line.strip().endswith(";"):
            return index + 1
    return len(lines) if seen_open else start_index


def _strip_leading_code_label(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("code file:"):
        return "\n".join(lines[1:]).lstrip()
    return text


def _diff_chunks(text: str) -> list[dict[str, str]]:
    sections = re.split(r"(?=^diff --git )", text, flags=re.MULTILINE)
    chunks = [_chunk_payload(section.strip(), "diff", "diff_file_or_hunk") for section in sections if section.strip()]
    return chunks or _word_window_chunks(text, profile="diff")


def _log_chunks(text: str) -> list[dict[str, str]]:
    sections = re.split(r"(?=^\d{4}-\d{2}-\d{2}[ T])|(?=^Traceback )", text, flags=re.MULTILINE)
    chunks = [_chunk_payload(section.strip(), "log", "log_event") for section in sections if section.strip()]
    return chunks or _word_window_chunks(text, profile="log")


def _structured_chunks(text: str, *, profile: str) -> list[dict[str, str]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    chunks: list[dict[str, str]] = []
    current: list[str] = []
    for line in lines:
        if current and (line.endswith("{") or re.match(r"^[A-Za-z0-9_.-]+\s*:", line)):
            chunks.append(_chunk_payload("\n".join(current).strip(), profile, "structured_section"))
            current = []
        current.append(line)
        if len(current) >= 60:
            chunks.append(_chunk_payload("\n".join(current).strip(), profile, "structured_section"))
            current = []
    if current:
        chunks.append(_chunk_payload("\n".join(current).strip(), profile, "structured_section"))
    return chunks or _word_window_chunks(text, profile=profile)


def _csv_chunks(text: str, *, delimiter: str) -> list[dict[str, str]]:
    rows = [line for line in text.splitlines() if line.strip()]
    if not rows:
        return []
    header = rows[0]
    data_rows = rows[1:]
    if not data_rows:
        return [_chunk_payload(header, "table_csv", "tabular_rows", {"rows": 0})]
    chunks: list[dict[str, str]] = []
    batch_size = 40
    for start in range(0, len(data_rows), batch_size):
        batch = data_rows[start : start + batch_size]
        payload = "\n".join([header, *batch]).strip()
        chunks.append(_chunk_payload(payload, "table_csv", "tabular_rows", {"start_row": start + 1, "rows": len(batch)}))
    return chunks


def _chunk_payload(text: str, profile: str, strategy: str, meta: dict | None = None) -> dict[str, str]:
    return {
        "text": text,
        "content_profile": profile,
        "chunk_strategy": strategy,
        "chunk_meta_json": json.dumps(meta or {}, separators=(",", ":")),
    }


def _looks_like_log(text: str) -> bool:
    return bool(re.search(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text, re.MULTILINE))


def _looks_like_tsv(source: dict, text: str) -> bool:
    suffix = Path(str(source.get("original_path") or source.get("title") or "")).suffix.lower()
    return suffix == ".tsv" or ("\t" in text and "," not in text.splitlines()[0])


def reindex_source_chunks(conn, source: dict) -> int:
    removed_chunk_ids = [
        str(row["id"])
        for row in conn.execute("SELECT id FROM source_chunks WHERE source_id = ?", (source["id"],)).fetchall()
    ]
    delete_source_chunk_encrypted_content(conn, source_id=source["id"], vault_id=source.get("vault_id"))
    conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source["id"],))
    if source.get("vault_id"):
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
        if row is not None:
            source = source_from_encrypted_row(conn, row)
    _ensure_source_pages(conn, source)
    pages = conn.execute(
        """
        SELECT * FROM source_pages
        WHERE source_id = ?
        ORDER BY page_number ASC
        """,
        (source["id"],),
    ).fetchall()
    now = utc_now()
    chunk_count = 0
    added_chunks: list[dict[str, str]] = []
    model_id = active_embedding_model_id()
    tuple_snapshot = query_epoch_snapshot_conn(
        conn,
        source["vault_id"],
        embedding_model_id=model_id,
        index_version="v1",
    )
    tuple_values = chunk_tuple_values(tuple_snapshot)
    tokenizer = None
    max_seq_length = None
    config = embedding_config()
    if config["provider"] == "sentence-transformers":
        embedding_model = _get_sentence_transformer(config["model"], config["cache_dir"])
        tokenizer = embedding_model.tokenizer
        max_seq_length = int(embedding_model.max_seq_length)
    for page in pages:
        page_data = page_from_encrypted_row(conn, page)
        chunks = chunk_text_for_source(
            source,
            page_data["raw_text"],
            tokenizer=tokenizer,
            max_seq_length=max_seq_length,
        )
        for index, chunk in enumerate(chunks):
            chunk_id = f"chunk-{uuid4()}"
            embedding = encode_embedding(embed_text(chunk["text"]))
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, page_id, vault_id, cluster_id, chunk_index, text, embedding,
                    embedding_model_id, content_profile, chunk_strategy, chunk_meta_json,
                    content_hash, index_version, normalization_version, extraction_version,
                    derived_state_epoch, indexed_at, created_at
                )
                VALUES (
                    :id, :source_id, :page_id, :vault_id, :cluster_id, :chunk_index, :text,
                    :embedding, :embedding_model_id, :content_profile, :chunk_strategy,
                    :chunk_meta_json, :content_hash, :index_version, :normalization_version,
                    :extraction_version, :derived_state_epoch, :indexed_at, :created_at
                )
                """,
                {
                    "id": chunk_id,
                    "source_id": source["id"],
                    "page_id": page_data["id"],
                    "vault_id": source["vault_id"],
                    "cluster_id": source.get("cluster_id"),
                    "chunk_index": index,
                    "text": plaintext_column_for_text(
                        conn,
                        vault_id=source["vault_id"],
                        entity_type="source_chunk",
                        entity_id=chunk_id,
                        field_name="text",
                        text=chunk["text"],
                        now=now,
                    ),
                    "embedding": embedding,
                    "embedding_model_id": model_id,
                    "content_profile": chunk["content_profile"],
                    "chunk_strategy": chunk["chunk_strategy"],
                    "chunk_meta_json": chunk["chunk_meta_json"],
                    "content_hash": content_hash(chunk["text"]),
                    "index_version": "v1",
                    **tuple_values,
                    "indexed_at": now,
                    "created_at": now,
                },
            )
            added_chunks.append({"chunk_id": chunk_id, "embedding": embedding})
            chunk_count += 1
    if source.get("vault_id"):
        apply_source_delta_to_sidecar(
            conn,
            vault_id=source["vault_id"],
            snapshot=tuple_snapshot,
            removed_chunk_ids=removed_chunk_ids,
            added_chunks=added_chunks,
            rebuild_reason=f"reindex_source:{source['id']}",
        )
    return chunk_count


def _ensure_source_pages(conn, source: dict) -> None:
    existing = conn.execute(
        "SELECT 1 FROM source_pages WHERE source_id = ? LIMIT 1",
        (source["id"],),
    ).fetchone()
    if existing is not None:
        return
    text = (source.get("extracted_text") or source.get("raw_text") or "").strip()
    if not text:
        return
    now = utc_now()
    page_id = f"page-{uuid4()}"
    conn.execute(
        """
        INSERT INTO source_pages (
            id, source_id, vault_id, page_number, raw_text, extraction_version,
            content_hash, created_at, updated_at
        )
        VALUES (
            :id, :source_id, :vault_id, :page_number, :raw_text, :extraction_version,
            :content_hash, :created_at, :updated_at
        )
        """,
        {
            "id": page_id,
            "source_id": source["id"],
            "vault_id": source["vault_id"],
            "page_number": 1,
            "raw_text": plaintext_column_for_text(
                conn,
                vault_id=source["vault_id"],
                entity_type="source_page",
                entity_id=page_id,
                field_name="raw_text",
                text=text,
                now=now,
            ),
            "extraction_version": "v1",
            "content_hash": content_hash(text),
            "created_at": now,
            "updated_at": now,
        },
    )
