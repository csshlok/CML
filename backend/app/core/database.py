import sqlite3
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dict_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def init_db() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(settings.database_path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS vaults (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clusters (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT 'sage',
                expert_status TEXT NOT NULL DEFAULT 'setting-up',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'waiting',
                original_path TEXT,
                url TEXT,
                raw_text TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                cover_image_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_requests (
                id TEXT PRIMARY KEY,
                client_name TEXT NOT NULL DEFAULT 'unknown',
                query TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'context',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_settings (
                id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                allow_style_profile INTEGER NOT NULL DEFAULT 0,
                allow_expert_calls INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_chunks (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                title TEXT NOT NULL,
                scope_cluster_id TEXT,
                saved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (scope_cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                clusters_used TEXT NOT NULL DEFAULT '[]',
                citations TEXT NOT NULL DEFAULT '[]',
                warnings TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_source_chunks_vault_id ON source_chunks(vault_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_cluster_id ON source_chunks(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id ON source_chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_vault_id ON chat_sessions(vault_id);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
            """
        )
        _add_column_if_missing(conn, "sources", "tags", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "sources", "cover_image_url", "TEXT")
        _add_column_if_missing(conn, "chat_messages", "useful", "INTEGER")
        _add_column_if_missing(conn, "chat_messages", "saved", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "chat_sessions", "memory_status", "TEXT NOT NULL DEFAULT 'idle'")
        _add_column_if_missing(conn, "chat_sessions", "memory_updated_at", "TEXT")


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not IDENTIFIER_RE.fullmatch(table) or not IDENTIFIER_RE.fullmatch(column):
        raise ValueError("Unsafe database identifier")
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database_path = path or get_settings().database_path
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
