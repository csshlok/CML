import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now

HASH_EMBEDDING_DIMENSIONS = 128
CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 40

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
    }
    if config["provider"] == "sentence-transformers":
        if importlib.util.find_spec("sentence_transformers") is not None:
            status["detail"] = "SentenceTransformers embedding model is available."
        else:
            status["available"] = False
            status["detail"] = "SentenceTransformers is not installed in this Python runtime."
    return status


def embedding_config() -> dict:
    settings = get_settings()
    config = {
        "provider": settings.embedding_provider,
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
            if provider in {"hash", "sentence-transformers"}:
                config["provider"] = provider
            if isinstance(cache_dir, str) and cache_dir.strip():
                config["cache_dir"] = Path(cache_dir)
    return config


def configure_embedding_runtime(provider: str, cache_dir: str | None = None) -> dict:
    if provider not in {"hash", "sentence-transformers"}:
        raise ValueError("Embedding provider must be 'hash' or 'sentence-transformers'")
    config_path = _embedding_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"provider": provider, "cache_dir": cache_dir or ""}
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
    kwargs = {"cache_folder": str(cache_dir)} if cache_dir else {}
    _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer(model_name, **kwargs)
    _SENTENCE_TRANSFORMER_MODEL_NAME = model_name
    _SENTENCE_TRANSFORMER_CACHE_DIR = cache_key
    return _SENTENCE_TRANSFORMER_MODEL


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
    text = (source.get("extracted_text") or source.get("raw_text") or "").strip()
    chunks = chunk_text(text)
    now = utc_now()
    for index, chunk in enumerate(chunks):
        conn.execute(
            """
            INSERT INTO source_chunks (
                id, source_id, vault_id, cluster_id, chunk_index, text, embedding, created_at
            )
            VALUES (
                :id, :source_id, :vault_id, :cluster_id, :chunk_index, :text, :embedding, :created_at
            )
            """,
            {
                "id": f"chunk-{uuid4()}",
                "source_id": source["id"],
                "vault_id": source["vault_id"],
                "cluster_id": source.get("cluster_id"),
                "chunk_index": index,
                "text": chunk,
                "embedding": encode_embedding(embed_text(chunk)),
                "created_at": now,
            },
        )
    return len(chunks)
