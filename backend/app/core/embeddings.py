import hashlib
import importlib.util
import json
import math
import re
import threading
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now

HASH_EMBEDDING_DIMENSIONS = 128
CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 40
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def embed_text(text: str) -> list[float]:
    config = embedding_config()
    if config["provider"] == "sentence-transformers":
        return _embed_with_sentence_transformers(config["model"], config["cache_dir"], text)
    return _embed_with_hash(text)


def embedding_status() -> dict:
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
            try:
                _embed_with_sentence_transformers(config["model"], config["cache_dir"], "vault setup test")
                status["detail"] = "SentenceTransformers embedding model is available."
            except Exception as exc:
                status["available"] = False
                status["setup_required"] = True
                status["detail"] = f"SentenceTransformers is installed, but the embedding model is not ready: {exc}"
        else:
            status["available"] = False
            status["setup_required"] = True
            status["detail"] = "SentenceTransformers is not installed in this Python runtime."
    return status


_EMBEDDING_DOWNLOAD_LOCK = threading.Lock()
_EMBEDDING_DOWNLOAD_STATE = {
    "model_id": DEFAULT_EMBEDDING_MODEL,
    "status": "idle",
    "bytes_downloaded": None,
    "total_bytes": None,
    "file_name": None,
    "local_path": None,
    "error": None,
}
_EMBEDDING_DOWNLOAD_THREAD: threading.Thread | None = None


def embedding_download_status() -> dict:
    with _EMBEDDING_DOWNLOAD_LOCK:
        return dict(_EMBEDDING_DOWNLOAD_STATE)


def start_embedding_model_download(cache_dir: str | None = None, model: str | None = None) -> dict:
    target_model = (model or get_settings().embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
    target_dir = Path(cache_dir).expanduser() if cache_dir and cache_dir.strip() else (
        get_settings().data_dir / "models" / "embeddings"
    )
    with _EMBEDDING_DOWNLOAD_LOCK:
        global _EMBEDDING_DOWNLOAD_THREAD
        if _EMBEDDING_DOWNLOAD_STATE["status"] in {"queued", "downloading"}:
            return dict(_EMBEDDING_DOWNLOAD_STATE)
        _EMBEDDING_DOWNLOAD_STATE.update(
            {
                "model_id": target_model,
                "status": "queued",
                "bytes_downloaded": None,
                "total_bytes": None,
                "file_name": target_model,
                "local_path": str(target_dir),
                "error": None,
            }
        )
        _EMBEDDING_DOWNLOAD_THREAD = threading.Thread(
            target=_download_embedding_model,
            args=(target_model, target_dir),
            daemon=True,
            name="cml-embedding-download",
        )
        _EMBEDDING_DOWNLOAD_THREAD.start()
        return dict(_EMBEDDING_DOWNLOAD_STATE)


def cancel_embedding_model_download() -> dict:
    with _EMBEDDING_DOWNLOAD_LOCK:
        if _EMBEDDING_DOWNLOAD_STATE["status"] in {"queued", "downloading"}:
            _EMBEDDING_DOWNLOAD_STATE["status"] = "cancelled"
            _EMBEDDING_DOWNLOAD_STATE["error"] = "Cancellation requested. The active Hugging Face request may finish before stopping."
        return dict(_EMBEDDING_DOWNLOAD_STATE)


def _download_embedding_model(model: str, cache_dir: Path) -> None:
    with _EMBEDDING_DOWNLOAD_LOCK:
        if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelled":
            return
        _EMBEDDING_DOWNLOAD_STATE["status"] = "downloading"
    try:
        if importlib.util.find_spec("sentence_transformers") is None:
            raise RuntimeError("SentenceTransformers is not installed in this Python runtime.")
        cache_dir.mkdir(parents=True, exist_ok=True)
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(model, cache_folder=str(cache_dir))
        with _EMBEDDING_DOWNLOAD_LOCK:
            if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelled":
                return
        configure_embedding_runtime("sentence-transformers", str(cache_dir), model)
        with _EMBEDDING_DOWNLOAD_LOCK:
            _EMBEDDING_DOWNLOAD_STATE.update({"status": "installed", "error": None})
    except Exception as exc:
        with _EMBEDDING_DOWNLOAD_LOCK:
            if _EMBEDDING_DOWNLOAD_STATE["status"] == "cancelled":
                return
            _EMBEDDING_DOWNLOAD_STATE.update({"status": "failed", "error": str(exc)})


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
    return embedding_status()


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
    if (model_path / "modules.json").exists() or (model_path / "config.json").exists():
        return str(model_path)
    return model_name


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
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    step = max(1, CHUNK_SIZE_WORDS - CHUNK_OVERLAP_WORDS)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + CHUNK_SIZE_WORDS]).strip()
        if chunk:
            chunks.append(chunk)
        if start + CHUNK_SIZE_WORDS >= len(words):
            break
    return chunks


def reindex_source_chunks(conn, source: dict) -> int:
    conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source["id"],))
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
    model_id = active_embedding_model_id()
    for page in pages:
        chunks = chunk_text(page["raw_text"])
        for index, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, page_id, vault_id, cluster_id, chunk_index, text, embedding,
                    embedding_model_id, content_hash, index_version, indexed_at, created_at
                )
                VALUES (
                    :id, :source_id, :page_id, :vault_id, :cluster_id, :chunk_index, :text,
                    :embedding, :embedding_model_id, :content_hash, :index_version, :indexed_at,
                    :created_at
                )
                """,
                {
                    "id": f"chunk-{uuid4()}",
                    "source_id": source["id"],
                    "page_id": page["id"],
                    "vault_id": source["vault_id"],
                    "cluster_id": source.get("cluster_id"),
                    "chunk_index": index,
                    "text": chunk,
                    "embedding": encode_embedding(embed_text(chunk)),
                    "embedding_model_id": model_id,
                    "content_hash": content_hash(chunk),
                    "index_version": "v1",
                    "indexed_at": now,
                    "created_at": now,
                },
            )
            chunk_count += 1
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
            "id": f"page-{uuid4()}",
            "source_id": source["id"],
            "vault_id": source["vault_id"],
            "page_number": 1,
            "raw_text": text,
            "extraction_version": "v1",
            "content_hash": content_hash(text),
            "created_at": now,
            "updated_at": now,
        },
    )
