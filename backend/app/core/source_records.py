import hashlib
from pathlib import Path
from uuid import uuid4

from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import (
    delete_source_derived_encrypted_content,
    plaintext_column_for_text,
)


def replace_source_pages(conn, *, source_id: str, vault_id: str, page_texts: list[str], now: str) -> None:
    delete_source_derived_encrypted_content(conn, source_id=source_id, vault_id=vault_id)
    conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
    for index, text in enumerate(page_texts, start=1):
        page_text = (text or "").strip()
        if not page_text:
            continue
        page_id = f"page-{uuid4()}"
        conn.execute(
            """
            INSERT INTO source_pages (
                id, source_id, vault_id, page_number, raw_text, extraction_version,
                content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'v1', ?, ?, ?)
            """,
            (
                page_id,
                source_id,
                vault_id,
                index,
                plaintext_column_for_text(
                    conn,
                    vault_id=vault_id,
                    entity_type="source_page",
                    entity_id=page_id,
                    field_name="raw_text",
                    text=page_text,
                    now=now,
                ),
                content_hash(page_text),
                now,
                now,
            ),
        )


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_type_for_suffix(suffix: str) -> str:
    if suffix in {".md", ".markdown", ".txt", ".text"}:
        return "note"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".py", ".pyi", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c"}:
        return "code"
    return "file"
