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
                checksum TEXT,
                raw_text TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                cover_image_url TEXT,
                deleted_at TEXT,
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
                bridge_token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cluster_expert_jobs (
                id TEXT PRIMARY KEY,
                cluster_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                failure_code TEXT NOT NULL DEFAULT '',
                artifact_path TEXT,
                hardware_tier TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS expert_artifacts (
                id TEXT PRIMARY KEY,
                cluster_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                job_id TEXT,
                artifact_type TEXT NOT NULL,
                status TEXT NOT NULL,
                local_path TEXT,
                base_model TEXT NOT NULL DEFAULT '',
                hardware_tier TEXT NOT NULL DEFAULT '',
                quality_score REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS vault_lock_audit (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                pid INTEGER,
                owner_pid INTEGER,
                lock_path TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                user_choice TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS integration_imports (
                id TEXT PRIMARY KEY,
                vault_id TEXT,
                integration_type TEXT NOT NULL,
                root_path TEXT NOT NULL,
                status TEXT NOT NULL,
                supported_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                truncated INTEGER NOT NULL DEFAULT 0,
                last_scan_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS extension_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS extension_captures (
                id TEXT PRIMARY KEY,
                client_id TEXT,
                vault_id TEXT NOT NULL,
                source_id TEXT,
                capture_type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES extension_clients(id) ON DELETE SET NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS app_jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                dedupe_key TEXT,
                priority TEXT NOT NULL DEFAULT 'normal',
                idempotency_class TEXT NOT NULL DEFAULT 'idempotent',
                restart_policy TEXT NOT NULL DEFAULT 'requeue',
                dependency_failure_policy TEXT NOT NULL DEFAULT 'cancel',
                write_scope TEXT NOT NULL DEFAULT 'none',
                scope_id TEXT,
                concurrency_group TEXT,
                resource_cost TEXT NOT NULL DEFAULT 'light',
                can_run_during_synthesis INTEGER NOT NULL DEFAULT 1,
                user_visible INTEGER NOT NULL DEFAULT 0,
                user_initiated INTEGER NOT NULL DEFAULT 0,
                cancellable INTEGER NOT NULL DEFAULT 0,
                preemptable INTEGER NOT NULL DEFAULT 0,
                timeout_seconds INTEGER,
                soft_timeout_seconds INTEGER,
                timeout_action TEXT NOT NULL DEFAULT 'fail',
                depends_on_job_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_error TEXT NOT NULL DEFAULT '',
                status_detail TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_chunks (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                page_id TEXT,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                embedding_model_id TEXT NOT NULL DEFAULT 'hash',
                content_hash TEXT NOT NULL DEFAULT '',
                index_version TEXT NOT NULL DEFAULT 'v1',
                indexed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (page_id) REFERENCES source_pages(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS source_pages (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                raw_text TEXT NOT NULL DEFAULT '',
                extraction_version TEXT NOT NULL DEFAULT 'v1',
                content_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                UNIQUE(source_id, page_number)
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

            CREATE TABLE IF NOT EXISTS chat_generations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_message_id TEXT,
                assistant_message_id TEXT,
                vault_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                state TEXT NOT NULL,
                runtime_provider TEXT NOT NULL DEFAULT '',
                runtime_model TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                heartbeat_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (user_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
                FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_attachments (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                original_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS retrieval_snapshots (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                query TEXT NOT NULL,
                retrieval_mode TEXT NOT NULL DEFAULT 'semantic',
                embedding_model_id TEXT NOT NULL DEFAULT '',
                token_budget INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS retrieval_snapshot_items (
                id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                source_id TEXT,
                chunk_id TEXT,
                page_id TEXT,
                source_title_at_answer_time TEXT NOT NULL,
                page_number INTEGER,
                snippet_hash TEXT NOT NULL DEFAULT '',
                short_snippet_excerpt TEXT NOT NULL DEFAULT '',
                relevance_score REAL NOT NULL DEFAULT 0,
                item_rank INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'current',
                created_at TEXT NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES retrieval_snapshots(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
                FOREIGN KEY (chunk_id) REFERENCES source_chunks(id) ON DELETE SET NULL,
                FOREIGN KEY (page_id) REFERENCES source_pages(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_source_chunks_vault_id ON source_chunks(vault_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_cluster_id ON source_chunks(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id ON source_chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_source_pages_source_id ON source_pages(source_id);
            CREATE INDEX IF NOT EXISTS idx_source_pages_vault_id ON source_pages(vault_id);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_vault_id ON chat_sessions(vault_id);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_chat_generations_state ON chat_generations(state, updated_at);
            CREATE INDEX IF NOT EXISTS idx_chat_attachments_message_id ON chat_attachments(message_id);
            CREATE INDEX IF NOT EXISTS idx_chat_attachments_source_id ON chat_attachments(source_id);
            CREATE INDEX IF NOT EXISTS idx_retrieval_snapshots_message_id ON retrieval_snapshots(message_id);
            CREATE INDEX IF NOT EXISTS idx_retrieval_snapshot_items_snapshot_id ON retrieval_snapshot_items(snapshot_id);
            CREATE INDEX IF NOT EXISTS idx_app_jobs_status ON app_jobs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_integration_imports_vault ON integration_imports(vault_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_extension_captures_vault ON extension_captures(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_expert_artifacts_cluster ON expert_artifacts(cluster_id, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_app_jobs_dedupe_active
                ON app_jobs(dedupe_key)
                WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running');
            """
        )
        _add_column_if_missing(conn, "sources", "tags", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "sources", "cover_image_url", "TEXT")
        _add_column_if_missing(conn, "sources", "deleted_at", "TEXT")
        _add_column_if_missing(conn, "sources", "checksum", "TEXT")
        _add_column_if_missing(conn, "chat_messages", "useful", "INTEGER")
        _add_column_if_missing(conn, "chat_messages", "saved", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "chat_sessions", "memory_status", "TEXT NOT NULL DEFAULT 'idle'")
        _add_column_if_missing(conn, "chat_sessions", "memory_updated_at", "TEXT")
        _add_column_if_missing(conn, "bridge_settings", "bridge_token", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "source_chunks", "page_id", "TEXT")
        _add_column_if_missing(conn, "source_chunks", "embedding_model_id", "TEXT NOT NULL DEFAULT 'hash'")
        _add_column_if_missing(conn, "source_chunks", "content_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "source_chunks", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing(conn, "source_chunks", "indexed_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "priority", "TEXT NOT NULL DEFAULT 'normal'")
        _add_column_if_missing(conn, "app_jobs", "idempotency_class", "TEXT NOT NULL DEFAULT 'idempotent'")
        _add_column_if_missing(conn, "app_jobs", "restart_policy", "TEXT NOT NULL DEFAULT 'requeue'")
        _add_column_if_missing(conn, "app_jobs", "dependency_failure_policy", "TEXT NOT NULL DEFAULT 'cancel'")
        _add_column_if_missing(conn, "app_jobs", "write_scope", "TEXT NOT NULL DEFAULT 'none'")
        _add_column_if_missing(conn, "app_jobs", "scope_id", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "concurrency_group", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "resource_cost", "TEXT NOT NULL DEFAULT 'light'")
        _add_column_if_missing(conn, "app_jobs", "can_run_during_synthesis", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "app_jobs", "user_visible", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "app_jobs", "user_initiated", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "app_jobs", "cancellable", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "app_jobs", "preemptable", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "app_jobs", "timeout_seconds", "INTEGER")
        _add_column_if_missing(conn, "app_jobs", "soft_timeout_seconds", "INTEGER")
        _add_column_if_missing(conn, "app_jobs", "timeout_action", "TEXT NOT NULL DEFAULT 'fail'")
        _add_column_if_missing(conn, "app_jobs", "depends_on_job_id", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "status_detail", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "app_jobs", "started_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "completed_at", "TEXT")
        _add_column_if_missing(conn, "cluster_expert_jobs", "failure_code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "cluster_expert_jobs", "artifact_path", "TEXT")
        _add_column_if_missing(conn, "cluster_expert_jobs", "hardware_tier", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "extension_clients", "allowed_vault_ids", "TEXT NOT NULL DEFAULT '[]'")
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_app_jobs_runnable
                ON app_jobs(status, priority, created_at);
            CREATE INDEX IF NOT EXISTS idx_app_jobs_dependency
                ON app_jobs(depends_on_job_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_page_id
                ON source_chunks(page_id);
            CREATE INDEX IF NOT EXISTS idx_sources_checksum
                ON sources(vault_id, checksum);
            """
        )


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
