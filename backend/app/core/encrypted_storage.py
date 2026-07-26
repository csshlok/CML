import base64
import hashlib
import json
import secrets
import struct
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.core.config import get_settings
from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.vault_crypto import (
    VaultCryptoError,
    derive_vault_subkeys,
    require_unlocked_key_material,
)

NONCE_BYTES = 12
BLOB_MAGIC = b"CMLBLOB1"
BLOB_CHUNK_SIZE = 1024 * 1024
CONTENT_MIGRATION_BATCH_SIZE = 100

SOURCE_TEXT_FIELDS = ("raw_text", "extracted_text", "summary", "tags")
CHAT_MESSAGE_FIELDS = ("content", "clusters_used", "citations", "warnings")


class EncryptedStorageError(RuntimeError):
    pass


class EncryptedContentIntegrityError(EncryptedStorageError):
    pass


def is_vault_secured(conn, vault_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM vault_security_metadata WHERE vault_id = ? LIMIT 1",
        (vault_id,),
    ).fetchone()
    return row is not None


def store_source_content_fields(conn, source: dict, *, now: str | None = None) -> dict:
    if not is_vault_secured(conn, source["vault_id"]):
        return source
    sanitized = dict(source)
    for field in SOURCE_TEXT_FIELDS:
        value = str(source.get(field) or "")
        put_encrypted_text(
            conn,
            vault_id=source["vault_id"],
            entity_type="source",
            entity_id=source["id"],
            field_name=field,
            text=value,
            now=now,
        )
        sanitized[field] = "[]" if field == "tags" else ""
    return sanitized


def migrate_existing_plaintext_content(conn, vault_id: str) -> dict[str, int]:
    """Resume bounded plaintext migration before a vault is reported secured."""
    counts = {"sources": 0, "pages": 0, "chunks": 0, "chat_messages": 0, "chat_generations": 0}
    conn.execute(
        """
        UPDATE vault_security_metadata
        SET content_migration_status = 'running',
            content_migration_updated_at = ?,
            content_migration_error = ''
        WHERE vault_id = ?
        """,
        (utc_now(), vault_id),
    )
    conn.commit()

    while True:
        rows = conn.execute(
            """
            SELECT id, raw_text, extracted_text, summary, tags
            FROM sources
            WHERE vault_id = ?
              AND (raw_text <> '' OR extracted_text <> '' OR summary <> '' OR tags NOT IN ('', '[]'))
            LIMIT ?
            """,
            (vault_id, CONTENT_MIGRATION_BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        now = utc_now()
        for row in rows:
            for field in SOURCE_TEXT_FIELDS:
                put_encrypted_text(
                    conn,
                    vault_id=vault_id,
                    entity_type="source",
                    entity_id=str(row["id"]),
                    field_name=field,
                    text=str(row[field] or ""),
                    now=now,
                )
            conn.execute(
                """
                UPDATE sources
                SET raw_text = '', extracted_text = '', summary = '', tags = '[]', updated_at = ?
                WHERE id = ? AND vault_id = ?
                """,
                (now, row["id"], vault_id),
            )
        counts["sources"] += len(rows)
        _commit_migration_batch(conn, vault_id)

    for table, entity_type, text_column, count_key, extra_update in (
        ("source_pages", "source_page", "raw_text", "pages", ", updated_at = :now"),
        ("source_chunks", "source_chunk", "text", "chunks", ""),
    ):
        while True:
            rows = conn.execute(
                f"SELECT id, {text_column} FROM {table} WHERE vault_id = ? AND {text_column} <> '' LIMIT ?",
                (vault_id, CONTENT_MIGRATION_BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            now = utc_now()
            for row in rows:
                put_encrypted_text(
                    conn,
                    vault_id=vault_id,
                    entity_type=entity_type,
                    entity_id=str(row["id"]),
                    field_name=text_column,
                    text=str(row[text_column] or ""),
                    now=now,
                )
                conn.execute(
                    f"UPDATE {table} SET {text_column} = ''{extra_update} WHERE id = :id AND vault_id = :vault_id",
                    {"id": row["id"], "vault_id": vault_id, "now": now},
                )
            counts[count_key] += len(rows)
            _commit_migration_batch(conn, vault_id)

    while True:
        rows = conn.execute(
            """
            SELECT messages.id, messages.content, messages.clusters_used, messages.citations, messages.warnings
            FROM chat_messages messages
            JOIN chat_sessions sessions ON sessions.id = messages.session_id
            WHERE sessions.vault_id = ?
              AND (
                messages.content <> '' OR messages.clusters_used NOT IN ('', '[]')
                OR messages.citations NOT IN ('', '[]') OR messages.warnings NOT IN ('', '[]')
              )
            LIMIT ?
            """,
            (vault_id, CONTENT_MIGRATION_BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        now = utc_now()
        for row in rows:
            for field in CHAT_MESSAGE_FIELDS:
                put_encrypted_text(
                    conn,
                    vault_id=vault_id,
                    entity_type="chat_message",
                    entity_id=str(row["id"]),
                    field_name=field,
                    text=str(row[field] or ""),
                    now=now,
                )
            conn.execute(
                "UPDATE chat_messages SET content = '', clusters_used = '[]', citations = '[]', warnings = '[]' WHERE id = ?",
                (row["id"],),
            )
        counts["chat_messages"] += len(rows)
        _commit_migration_batch(conn, vault_id)

    while True:
        rows = conn.execute(
            "SELECT id, prompt FROM chat_generations WHERE vault_id = ? AND prompt <> '' LIMIT ?",
            (vault_id, CONTENT_MIGRATION_BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        now = utc_now()
        for row in rows:
            put_encrypted_text(
                conn,
                vault_id=vault_id,
                entity_type="chat_generation",
                entity_id=str(row["id"]),
                field_name="prompt",
                text=str(row["prompt"] or ""),
                now=now,
            )
            conn.execute("UPDATE chat_generations SET prompt = '' WHERE id = ?", (row["id"],))
        counts["chat_generations"] += len(rows)
        _commit_migration_batch(conn, vault_id)

    conn.execute("DELETE FROM retrieval_snapshots WHERE vault_id = ?", (vault_id,))
    conn.execute("DELETE FROM query_evidence_cache WHERE vault_id = ?", (vault_id,))
    conn.execute(
        """
        UPDATE vault_security_metadata
        SET content_migration_status = 'complete',
            content_migration_updated_at = ?,
            content_migration_error = ''
        WHERE vault_id = ?
        """,
        (utc_now(), vault_id),
    )
    conn.commit()
    return counts


def _commit_migration_batch(conn, vault_id: str) -> None:
    conn.execute(
        """
        UPDATE vault_security_metadata
        SET content_migration_updated_at = ?
        WHERE vault_id = ?
        """,
        (utc_now(), vault_id),
    )
    conn.commit()


def store_chat_message_content(
    conn,
    *,
    vault_id: str,
    message_id: str,
    content: str,
    now: str | None = None,
) -> str:
    return plaintext_column_for_text(
        conn,
        vault_id=vault_id,
        entity_type="chat_message",
        entity_id=message_id,
        field_name="content",
        text=content,
        now=now,
    )


def store_chat_message_fields(
    conn,
    *,
    vault_id: str,
    message_id: str,
    fields: dict[str, str],
    now: str | None = None,
) -> dict[str, str]:
    stored = dict(fields)
    if not is_vault_secured(conn, vault_id):
        return stored
    for field in CHAT_MESSAGE_FIELDS:
        if field not in stored:
            continue
        put_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type="chat_message",
            entity_id=message_id,
            field_name=field,
            text=str(stored[field] or ""),
            now=now,
        )
        stored[field] = "[]" if field != "content" else ""
    return stored


def mark_chat_citations_source_deleted(
    conn,
    *,
    vault_id: str,
    source_id: str,
    now: str | None = None,
) -> int:
    """Tombstone historical citations before their source is removed.

    Secured vaults do not retain plaintext retrieval snapshots, so their
    encrypted citation payloads are the durable history that must be updated.
    """
    rows = conn.execute(
        """
        SELECT messages.id, messages.citations
        FROM chat_messages messages
        JOIN chat_sessions sessions ON sessions.id = messages.session_id
        WHERE sessions.vault_id = ?
          AND messages.role = 'assistant'
        """,
        (vault_id,),
    ).fetchall()
    secured = is_vault_secured(conn, vault_id)
    updated_count = 0
    for row in rows:
        serialized = str(row["citations"] or "[]")
        if secured:
            serialized = get_encrypted_text(
                conn,
                vault_id=vault_id,
                entity_type="chat_message",
                entity_id=str(row["id"]),
                field_name="citations",
            ) or serialized
        try:
            citations = json.loads(serialized)
        except (TypeError, ValueError):
            continue
        if not isinstance(citations, list):
            continue
        changed = False
        for citation in citations:
            if isinstance(citation, dict) and str(citation.get("source_id") or "") == source_id:
                citation["state"] = "source_deleted"
                changed = True
        if not changed:
            continue
        stored = store_chat_message_fields(
            conn,
            vault_id=vault_id,
            message_id=str(row["id"]),
            fields={"citations": json.dumps(citations)},
            now=now,
        )
        conn.execute(
            "UPDATE chat_messages SET citations = ? WHERE id = ?",
            (stored["citations"], row["id"]),
        )
        updated_count += 1
    return updated_count


def store_chat_generation_prompt(
    conn,
    *,
    vault_id: str,
    generation_id: str,
    prompt: str,
    now: str | None = None,
) -> str:
    return plaintext_column_for_text(
        conn,
        vault_id=vault_id,
        entity_type="chat_generation",
        entity_id=generation_id,
        field_name="prompt",
        text=prompt,
        now=now,
    )


def hydrate_chat_generation_rows(conn, rows) -> list[dict]:
    generations = [dict_from_row(row) for row in rows]
    for generation in generations:
        vault_id = str(generation.get("vault_id") or "")
        if not vault_id or not is_vault_secured(conn, vault_id):
            continue
        generation["prompt"] = get_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type="chat_generation",
            entity_id=str(generation["id"]),
            field_name="prompt",
        )
    return generations


def hydrate_chat_message_rows(conn, rows) -> list[dict]:
    messages = [dict_from_row(row) for row in rows]
    session_ids = sorted({str(message.get("session_id") or "") for message in messages if message.get("session_id")})
    if not session_ids:
        return messages
    placeholders = ",".join("?" for _ in session_ids)
    session_rows = conn.execute(
        f"SELECT id, vault_id FROM chat_sessions WHERE id IN ({placeholders})",
        session_ids,
    ).fetchall()
    vault_by_session = {str(row["id"]): str(row["vault_id"]) for row in session_rows}
    for message in messages:
        vault_id = vault_by_session.get(str(message.get("session_id") or ""))
        if not vault_id or not is_vault_secured(conn, vault_id):
            continue
        for field in CHAT_MESSAGE_FIELDS:
            encrypted = get_encrypted_text(
                conn,
                vault_id=vault_id,
                entity_type="chat_message",
                entity_id=str(message["id"]),
                field_name=field,
            )
            if encrypted:
                message[field] = encrypted
    return messages


def update_source_content_fields(conn, *, vault_id: str, source_id: str, updates: dict, now: str | None = None) -> dict:
    if not is_vault_secured(conn, vault_id):
        return updates
    sanitized = dict(updates)
    for field in SOURCE_TEXT_FIELDS:
        if field not in sanitized:
            continue
        put_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type="source",
            entity_id=source_id,
            field_name=field,
            text=str(sanitized.get(field) or ""),
            now=now,
        )
        sanitized[field] = "[]" if field == "tags" else ""
    return sanitized


def source_from_encrypted_row(conn, row, *, include_content: bool = True) -> dict:
    source = dict_from_row(row)
    if not is_vault_secured(conn, source["vault_id"]):
        return source
    if not include_content:
        return source
    for field in SOURCE_TEXT_FIELDS:
        encrypted = get_encrypted_text(
            conn,
            vault_id=source["vault_id"],
            entity_type="source",
            entity_id=source["id"],
            field_name=field,
        )
        if encrypted:
            source[field] = encrypted
    return source


def load_source_content_fields(
    conn,
    *,
    vault_id: str,
    source_id: str,
    fields: tuple[str, ...] = SOURCE_TEXT_FIELDS,
) -> dict[str, str]:
    values: dict[str, str] = {}
    if not is_vault_secured(conn, vault_id):
        return values
    for field in fields:
        values[field] = get_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type="source",
            entity_id=source_id,
            field_name=field,
        )
    return values


def page_from_encrypted_row(conn, row) -> dict:
    page = dict_from_row(row)
    if not is_vault_secured(conn, page["vault_id"]):
        return page
    encrypted = get_encrypted_text(
        conn,
        vault_id=page["vault_id"],
        entity_type="source_page",
        entity_id=page["id"],
        field_name="raw_text",
    )
    if encrypted:
        page["raw_text"] = encrypted
    return page


def chunk_from_encrypted_row(conn, row) -> dict:
    chunk = dict_from_row(row)
    if not is_vault_secured(conn, chunk["vault_id"]):
        return chunk
    encrypted = get_encrypted_text(
        conn,
        vault_id=chunk["vault_id"],
        entity_type="source_chunk",
        entity_id=chunk["chunk_id"] if "chunk_id" in chunk else chunk["id"],
        field_name="text",
    )
    if encrypted:
        chunk["text"] = encrypted
    return chunk


def plaintext_column_for_text(
    conn,
    *,
    vault_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    text: str,
    now: str | None = None,
) -> str:
    if not is_vault_secured(conn, vault_id):
        return text
    put_encrypted_text(
        conn,
        vault_id=vault_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        text=text,
        now=now,
    )
    return ""


def delete_encrypted_entity(conn, *, vault_id: str | None, entity_type: str, entity_id: str) -> None:
    if vault_id:
        conn.execute(
            """
            DELETE FROM encrypted_content
            WHERE vault_id = ? AND entity_type = ? AND entity_id = ?
            """,
            (vault_id, entity_type, entity_id),
        )
    else:
        conn.execute(
            """
            DELETE FROM encrypted_content
            WHERE entity_type = ? AND entity_id = ?
            """,
            (entity_type, entity_id),
        )


def delete_source_chunk_encrypted_content(conn, *, source_id: str, vault_id: str | None = None) -> None:
    chunk_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM source_chunks WHERE source_id = ?", (source_id,)).fetchall()
    ]
    for chunk_id in chunk_ids:
        delete_encrypted_entity(conn, vault_id=vault_id, entity_type="source_chunk", entity_id=chunk_id)


def delete_source_page_encrypted_content(conn, *, source_id: str, vault_id: str | None = None) -> None:
    page_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM source_pages WHERE source_id = ?", (source_id,)).fetchall()
    ]
    for page_id in page_ids:
        delete_encrypted_entity(conn, vault_id=vault_id, entity_type="source_page", entity_id=page_id)


def delete_source_derived_encrypted_content(conn, *, source_id: str, vault_id: str | None = None) -> None:
    delete_source_chunk_encrypted_content(conn, source_id=source_id, vault_id=vault_id)
    delete_source_page_encrypted_content(conn, source_id=source_id, vault_id=vault_id)


def delete_source_encrypted_content(conn, *, source_id: str, vault_id: str | None = None) -> None:
    delete_source_derived_encrypted_content(conn, source_id=source_id, vault_id=vault_id)
    delete_encrypted_entity(conn, vault_id=vault_id, entity_type="source", entity_id=source_id)


def put_encrypted_text(
    conn,
    *,
    vault_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    text: str,
    now: str | None = None,
) -> None:
    if not text:
        conn.execute(
            """
            DELETE FROM encrypted_content
            WHERE vault_id = ? AND entity_type = ? AND entity_id = ? AND field_name = ?
            """,
            (vault_id, entity_type, entity_id, field_name),
        )
        return
    created = now or utc_now()
    nonce, ciphertext = _encrypt_bytes(vault_id, _aad(vault_id, entity_type, entity_id, field_name), text.encode("utf-8"))
    params = {
        "id": f"encrypted-{uuid4()}",
        "vault_id": vault_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field_name": field_name,
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "byte_length": len(text.encode("utf-8")),
        "created_at": created,
        "updated_at": created,
    }
    conn.execute(
        """
        INSERT INTO encrypted_content (
            id, vault_id, entity_type, entity_id, field_name, nonce, ciphertext,
            content_hash, byte_length, created_at, updated_at
        )
        VALUES (
            :id, :vault_id, :entity_type, :entity_id, :field_name, :nonce, :ciphertext,
            :content_hash, :byte_length, :created_at, :updated_at
        )
        ON CONFLICT(entity_type, entity_id, field_name) DO UPDATE SET
            vault_id = excluded.vault_id,
            nonce = excluded.nonce,
            ciphertext = excluded.ciphertext,
            content_hash = excluded.content_hash,
            byte_length = excluded.byte_length,
            updated_at = excluded.updated_at
        """,
        params,
    )


def get_encrypted_text(
    conn,
    *,
    vault_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
) -> str:
    row = conn.execute(
        """
        SELECT nonce, ciphertext, content_hash
        FROM encrypted_content
        WHERE vault_id = ? AND entity_type = ? AND entity_id = ? AND field_name = ?
        """,
        (vault_id, entity_type, entity_id, field_name),
    ).fetchone()
    if row is None:
        return ""
    plaintext = _decrypt_bytes(
        vault_id,
        _aad(vault_id, entity_type, entity_id, field_name),
        _b64d(row["nonce"]),
        _b64d(row["ciphertext"]),
    )
    if hashlib.sha256(plaintext).hexdigest() != row["content_hash"]:
        raise EncryptedContentIntegrityError("encrypted_content_hash_mismatch")
    return plaintext.decode("utf-8")


def encrypted_blob_path(vault_id: str, blob_id: str) -> Path:
    safe_vault_id = _safe_segment(vault_id)
    safe_blob_id = _safe_segment(blob_id)
    return get_settings().data_dir / "blobs" / safe_vault_id / f"{safe_blob_id}.cmlblob"


def write_encrypted_file_from_path(
    *,
    vault_id: str,
    source_path: Path,
    blob_id: str | None = None,
    chunk_size: int = BLOB_CHUNK_SIZE,
) -> dict:
    blob_identifier = blob_id or f"blob-{uuid4()}"
    destination = encrypted_blob_path(vault_id, blob_identifier)
    destination.parent.mkdir(parents=True, exist_ok=True)
    aad_prefix = f"cml:vault:{vault_id}:blob:{blob_identifier}:chunk:".encode("utf-8")
    total_plaintext = 0
    chunk_count = 0
    digest = hashlib.sha256()
    with source_path.open("rb") as source, destination.open("wb") as target:
        target.write(BLOB_MAGIC)
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            nonce, ciphertext = _encrypt_bytes(vault_id, aad_prefix + str(chunk_count).encode("ascii"), chunk)
            target.write(struct.pack(">I", len(nonce)))
            target.write(nonce)
            target.write(struct.pack(">Q", len(ciphertext)))
            target.write(ciphertext)
            total_plaintext += len(chunk)
            chunk_count += 1
    return {
        "vault_id": vault_id,
        "blob_id": blob_identifier,
        "path": str(destination),
        "plaintext_bytes": total_plaintext,
        "chunk_count": chunk_count,
        "plaintext_sha256": digest.hexdigest(),
    }


def read_encrypted_file_to_bytes(*, vault_id: str, blob_id: str) -> bytes:
    path = encrypted_blob_path(vault_id, blob_id)
    aad_prefix = f"cml:vault:{vault_id}:blob:{blob_id}:chunk:".encode("utf-8")
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        if handle.read(len(BLOB_MAGIC)) != BLOB_MAGIC:
            raise EncryptedStorageError("invalid_encrypted_blob")
        index = 0
        while True:
            nonce_length_raw = handle.read(4)
            if not nonce_length_raw:
                break
            nonce_length = struct.unpack(">I", nonce_length_raw)[0]
            nonce = handle.read(nonce_length)
            ciphertext_length = struct.unpack(">Q", handle.read(8))[0]
            ciphertext = handle.read(ciphertext_length)
            chunks.append(_decrypt_bytes(vault_id, aad_prefix + str(index).encode("ascii"), nonce, ciphertext))
            index += 1
    return b"".join(chunks)


def encrypted_blob_store_size(vault_id: str | None = None) -> int:
    root = get_settings().data_dir / "blobs"
    if vault_id:
        root = root / _safe_segment(vault_id)
    if not root.exists():
        return 0
    total = 0
    for child in root.rglob("*.cmlblob"):
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def _encrypt_bytes(vault_id: str, aad: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    key = _blob_key(vault_id)
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def _decrypt_bytes(vault_id: str, aad: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    key = _blob_key(vault_id)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError) as exc:
        raise VaultCryptoError("encrypted_content_decrypt_failed") from exc


def _blob_key(vault_id: str) -> bytes:
    material = require_unlocked_key_material(vault_id)
    return derive_vault_subkeys(material).blob_key


def _aad(vault_id: str, entity_type: str, entity_id: str, field_name: str) -> bytes:
    return f"cml:vault:{vault_id}:encrypted-content:v1:{entity_type}:{entity_id}:{field_name}".encode("utf-8")


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _safe_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:180]
