from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import connect
from backend.app.core.encrypted_storage import encrypted_blob_store_size


def storage_accounting(vault_id: str | None = None) -> dict:
    with connect() as conn:
        source_clause = "WHERE deleted_at IS NULL"
        chunk_clause = ""
        page_clause = ""
        params: list[str] = []
        if vault_id:
            source_clause += " AND vault_id = ?"
            chunk_clause = "WHERE vault_id = ?"
            page_clause = "WHERE vault_id = ?"
            params.append(vault_id)
        source_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(LENGTH(raw_text)), 0) AS raw_text_bytes,
                COALESCE(SUM(LENGTH(extracted_text)), 0) AS extracted_text_bytes
            FROM sources
            {source_clause}
            """,
            params,
        ).fetchone()
        page_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count, COALESCE(SUM(LENGTH(raw_text)), 0) AS raw_text_bytes
            FROM source_pages
            {page_clause}
            """,
            params,
        ).fetchone()
        chunk_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(LENGTH(text)), 0) AS text_bytes,
                COALESCE(SUM(LENGTH(embedding)), 0) AS embedding_bytes
            FROM source_chunks
            {chunk_clause}
            """,
            params,
        ).fetchone()
        chat_clause = ""
        chat_params: list[str] = []
        if vault_id:
            chat_clause = "WHERE sessions.vault_id = ?"
            chat_params.append(vault_id)
        chat_row = conn.execute(
            f"""
            SELECT COUNT(messages.id) AS count, COALESCE(SUM(LENGTH(messages.content)), 0) AS text_bytes
            FROM chat_messages messages
            JOIN chat_sessions sessions ON sessions.id = messages.session_id
            {chat_clause}
            """,
            chat_params,
        ).fetchone()
        snapshot_clause = ""
        snapshot_params: list[str] = []
        if vault_id:
            snapshot_clause = "WHERE vault_id = ?"
            snapshot_params.append(vault_id)
        snapshot_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count, COALESCE(SUM(LENGTH(query)), 0) AS query_bytes
            FROM retrieval_snapshots
            {snapshot_clause}
            """,
            snapshot_params,
        ).fetchone()
        evidence_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(LENGTH(query)), 0) AS query_bytes,
                COALESCE(SUM(LENGTH(evidence_excerpt)), 0) AS excerpt_bytes
            FROM analysis_evidence_packets
            {snapshot_clause}
            """,
            snapshot_params,
        ).fetchone()
        external_clause = "WHERE deleted_at IS NULL AND source_type IN ('external_transcript', 'external_artifact', 'mcp_external_turn', 'mcp_artifact')"
        external_params: list[str] = []
        if vault_id:
            external_clause += " AND vault_id = ?"
            external_params.append(vault_id)
        external_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count, COALESCE(SUM(LENGTH(raw_text)), 0) AS text_bytes
            FROM sources
            {external_clause}
            """,
            external_params,
        ).fetchone()
        encrypted_clause = ""
        encrypted_params: list[str] = []
        if vault_id:
            encrypted_clause = "WHERE vault_id = ?"
            encrypted_params.append(vault_id)
        encrypted_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(LENGTH(ciphertext)), 0) AS ciphertext_text_bytes,
                COALESCE(SUM(byte_length), 0) AS plaintext_bytes
            FROM encrypted_content
            {encrypted_clause}
            """,
            encrypted_params,
        ).fetchone()
    vector_dir = _directory_size(get_settings().data_dir / "vectors")
    database_size = _safe_file_size(get_settings().database_path)
    encrypted_blob_bytes = encrypted_blob_store_size(vault_id)
    return {
        "vault_id": vault_id,
        "database_bytes": database_size,
        "vector_index_bytes": vector_dir,
        "encrypted_blob_bytes": encrypted_blob_bytes,
        "encrypted_content": {
            "count": int(encrypted_row["count"] or 0),
            "ciphertext_text_bytes": int(encrypted_row["ciphertext_text_bytes"] or 0),
            "plaintext_bytes": int(encrypted_row["plaintext_bytes"] or 0),
        },
        "sources": {
            "count": int(source_row["count"] or 0),
            "raw_text_bytes": int(source_row["raw_text_bytes"] or 0),
            "extracted_text_bytes": int(source_row["extracted_text_bytes"] or 0),
        },
        "pages": {
            "count": int(page_row["count"] or 0),
            "raw_text_bytes": int(page_row["raw_text_bytes"] or 0),
        },
        "chunks": {
            "count": int(chunk_row["count"] or 0),
            "text_bytes": int(chunk_row["text_bytes"] or 0),
            "embedding_bytes": int(chunk_row["embedding_bytes"] or 0),
        },
        "chat": {
            "message_count": int(chat_row["count"] or 0),
            "message_text_bytes": int(chat_row["text_bytes"] or 0),
        },
        "retrieval_snapshots": {
            "count": int(snapshot_row["count"] or 0),
            "query_bytes": int(snapshot_row["query_bytes"] or 0),
        },
        "analysis_evidence_packets": {
            "count": int(evidence_row["count"] or 0),
            "query_bytes": int(evidence_row["query_bytes"] or 0),
            "excerpt_bytes": int(evidence_row["excerpt_bytes"] or 0),
        },
        "external_captures": {
            "count": int(external_row["count"] or 0),
            "text_bytes": int(external_row["text_bytes"] or 0),
        },
        "estimate": True,
    }


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += _safe_file_size(child)
    return total


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
