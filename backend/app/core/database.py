import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings


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
            """
        )


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
