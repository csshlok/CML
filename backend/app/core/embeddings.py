import hashlib
import json
import math
import re
from uuid import uuid4

from backend.app.core.database import utc_now

EMBEDDING_DIMENSIONS = 128
CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 40

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


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
