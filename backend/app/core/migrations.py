from collections.abc import Callable

from backend.app.core.database import connect, utc_now

SCHEMA_VERSION = 7


class MigrationError(RuntimeError):
    pass


Migration = Callable[[object], None]


def _migration_001_baseline(conn) -> None:
    # init_db() owns the clean-slate schema today. This baseline records that
    # migration tracking exists before public user data ships.
    conn.execute("SELECT 1")


def _migration_002_vault_security_metadata(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_security_metadata (
            vault_id TEXT PRIMARY KEY,
            security_version INTEGER NOT NULL,
            kdf_algorithm TEXT NOT NULL,
            kdf_params_json TEXT NOT NULL,
            passphrase_salt TEXT NOT NULL,
            passphrase_wrapped_vmk TEXT NOT NULL,
            recovery_salt TEXT NOT NULL,
            recovery_wrapped_vmk TEXT NOT NULL,
            unlock_mode TEXT NOT NULL DEFAULT 'convenience',
            pin_enabled INTEGER NOT NULL DEFAULT 0,
            pin_salt TEXT NOT NULL DEFAULT '',
            pin_wrapped_unlock_secret TEXT NOT NULL DEFAULT '',
            active_derived_state_tuple TEXT NOT NULL DEFAULT '{}',
            previous_verified_tuple TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_security_unlock_mode ON vault_security_metadata(unlock_mode)")


def _migration_003_encrypted_content(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS encrypted_content (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            nonce TEXT NOT NULL,
            ciphertext TEXT NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            byte_length INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            UNIQUE(entity_type, entity_id, field_name)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_encrypted_content_vault ON encrypted_content(vault_id, entity_type, entity_id)")


def _migration_004_derived_state_publications(conn) -> None:
    _add_column_if_missing(conn, "source_chunks", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
    _add_column_if_missing(conn, "source_chunks", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
    _add_column_if_missing(conn, "source_chunks", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "retrieval_snapshots", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
    _add_column_if_missing(conn, "retrieval_snapshots", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
    _add_column_if_missing(conn, "retrieval_snapshots", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
    _add_column_if_missing(conn, "retrieval_snapshots", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_state_publications (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            normalization_version TEXT NOT NULL,
            embedding_model_id TEXT NOT NULL,
            index_version TEXT NOT NULL,
            extraction_version TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_manifest_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            verified_at TEXT,
            published_at TEXT,
            rolled_back_at TEXT,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            UNIQUE(vault_id, epoch)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_state_staged_artifacts (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            byte_length INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            owner_job_id TEXT,
            heartbeat_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (publication_id) REFERENCES derived_state_publications(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_chunks_tuple
            ON source_chunks(vault_id, embedding_model_id, index_version, normalization_version, extraction_version, derived_state_epoch)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_derived_state_publications_vault
            ON derived_state_publications(vault_id, status, epoch)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_derived_state_staged_vault
            ON derived_state_staged_artifacts(vault_id, status, updated_at)
        """
    )


def _migration_005_quarantine_records(conn) -> None:
    for column, definition in {
        "provenance": "TEXT NOT NULL DEFAULT 'local_import'",
        "trust_tier": "TEXT NOT NULL DEFAULT 'trusted_local'",
        "security_labels": "TEXT NOT NULL DEFAULT '[]'",
        "parser_security_json": "TEXT NOT NULL DEFAULT '{}'",
    }.items():
        _add_column_if_missing(conn, "sources", column, definition)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_quarantine_records (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            source_id TEXT,
            original_path TEXT NOT NULL,
            canonical_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            suffix TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            encrypted_blob_id TEXT NOT NULL DEFAULT '',
            encrypted_blob_path TEXT NOT NULL DEFAULT '',
            validation_status TEXT NOT NULL,
            validation_json TEXT NOT NULL DEFAULT '{}',
            defender_status TEXT NOT NULL DEFAULT 'not_run',
            defender_detail TEXT NOT NULL DEFAULT '',
            parser_status TEXT NOT NULL DEFAULT 'not_run',
            parser_detail TEXT NOT NULL DEFAULT '',
            trust_tier TEXT NOT NULL DEFAULT 'quarantined',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_trust ON sources(vault_id, trust_tier, provenance)")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_quarantine_vault
            ON source_quarantine_records(vault_id, validation_status, parser_status, updated_at)
        """
    )


def _migration_006_bridge_approvals(conn) -> None:
    for column, definition in {
        "client_id": "TEXT",
        "decision": "TEXT NOT NULL DEFAULT 'allowed'",
        "source_count": "INTEGER NOT NULL DEFAULT 0",
        "response_bytes": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        _add_column_if_missing(conn, "bridge_requests", column, definition)
    for column, definition in {
        "approval_vault_id": "TEXT",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "approval_request_id": "TEXT",
        "approved_at": "TEXT",
        "revoked_at": "TEXT",
        "last_request_at": "TEXT",
        "request_count_total": "INTEGER NOT NULL DEFAULT 0",
        "response_bytes_total": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        _add_column_if_missing(conn, "bridge_clients", column, definition)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bridge_approval_requests (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            status TEXT NOT NULL,
            fingerprint_hash TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            approval_code_hash TEXT NOT NULL DEFAULT '',
            requested_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            decided_at TEXT,
            delivered_at TEXT,
            client_id TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (client_id) REFERENCES bridge_clients(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bridge_audit_events (
            id TEXT PRIMARY KEY,
            vault_id TEXT,
            client_id TEXT,
            approval_request_id TEXT,
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (client_id) REFERENCES bridge_clients(id) ON DELETE SET NULL,
            FOREIGN KEY (approval_request_id) REFERENCES bridge_approval_requests(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bridge_rate_limits (
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            bucket TEXT NOT NULL,
            window_started_at TEXT NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0,
            byte_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_type, scope_id, bucket)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bridge_requests_created ON bridge_requests(created_at DESC)")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bridge_approval_requests_status
            ON bridge_approval_requests(vault_id, status, updated_at DESC)
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bridge_audit_events_created ON bridge_audit_events(created_at DESC)")


def _migration_007_reconciliation_logs(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_runs (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            import_id TEXT NOT NULL,
            trigger_source TEXT NOT NULL,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            import_files INTEGER NOT NULL DEFAULT 1,
            tombstone_missing INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            moved_count INTEGER NOT NULL DEFAULT 0,
            unchanged_count INTEGER NOT NULL DEFAULT 0,
            tombstoned_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            retryable_failed_count INTEGER NOT NULL DEFAULT 0,
            detail_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (import_id) REFERENCES integration_imports(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            vault_id TEXT NOT NULL,
            import_id TEXT NOT NULL,
            item_reference TEXT NOT NULL,
            action TEXT NOT NULL,
            result TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            retryable INTEGER NOT NULL DEFAULT 0,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (import_id) REFERENCES integration_imports(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_import
            ON reconciliation_runs(import_id, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_vault
            ON reconciliation_runs(vault_id, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reconciliation_items_run
            ON reconciliation_items(run_id, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reconciliation_items_import
            ON reconciliation_items(import_id, result, created_at DESC)
        """
    )


MIGRATIONS: dict[int, Migration] = {
    1: _migration_001_baseline,
    2: _migration_002_vault_security_metadata,
    3: _migration_003_encrypted_content,
    4: _migration_004_derived_state_publications,
    5: _migration_005_quarantine_records,
    6: _migration_006_bridge_approvals,
    7: _migration_007_reconciliation_logs,
}


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def run_migrations() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        running = conn.execute(
            "SELECT version, name FROM schema_migrations WHERE status = 'running' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if running is not None:
            raise MigrationError(
                f"Previous migration did not finish: {running['version']} {running['name']}"
            )
        current_row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_migrations WHERE status = 'succeeded'"
        ).fetchone()
        current_version = int(current_row["version"] or 0)
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise MigrationError(f"No migration registered for schema version {version}")
            name = migration.__name__.removeprefix("_migration_")
            started_at = utc_now()
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (version, name, started_at),
            )
            try:
                migration(conn)
            except Exception as exc:
                conn.execute(
                    """
                    UPDATE schema_migrations
                    SET status = 'failed', finished_at = ?, error = ?
                    WHERE version = ?
                    """,
                    (utc_now(), str(exc)[:1000], version),
                )
                raise MigrationError(f"Migration {version} failed: {exc}") from exc
            conn.execute(
                """
                UPDATE schema_migrations
                SET status = 'succeeded', finished_at = ?, error = ''
                WHERE version = ?
                """,
                (utc_now(), version),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
