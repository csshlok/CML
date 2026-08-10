import hashlib
import json
from collections.abc import Callable
from uuid import uuid4

from backend.app.core.database import connect, utc_now

SCHEMA_VERSION = 37


class MigrationError(RuntimeError):
    pass


Migration = Callable[[object], None]

# SQLite schema migrations run inside one transaction. The registered migrations
# are intentionally idempotent so an old, persisted ``running`` marker from a
# previous app version can be retried. Unknown or renamed work is never guessed.
RESTARTABLE_MIGRATION_VERSIONS = frozenset(range(1, SCHEMA_VERSION + 1))


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


def _migration_008_project_graph(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL,
            root_fingerprint TEXT NOT NULL,
            primary_cluster_id TEXT NOT NULL,
            repository_kind TEXT NOT NULL DEFAULT 'folder',
            git_remote_fingerprint TEXT,
            default_branch TEXT,
            indexed_commit TEXT,
            working_tree_dirty INTEGER NOT NULL DEFAULT 0,
            changed_file_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'registered',
            structure_status TEXT NOT NULL DEFAULT 'waiting',
            retrieval_status TEXT NOT NULL DEFAULT 'waiting',
            interpretation_status TEXT NOT NULL DEFAULT 'unavailable',
            active_snapshot_id TEXT,
            brief TEXT NOT NULL DEFAULT '',
            languages_json TEXT NOT NULL DEFAULT '{}',
            workspace_count INTEGER NOT NULL DEFAULT 0,
            entrypoints_json TEXT NOT NULL DEFAULT '[]',
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (primary_cluster_id) REFERENCES clusters(id) ON DELETE RESTRICT,
            UNIQUE(vault_id, root_fingerprint)
        );
        CREATE TABLE IF NOT EXISTS project_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_manifest_hash TEXT NOT NULL,
            git_commit TEXT,
            branch TEXT,
            dirty_working_tree INTEGER NOT NULL DEFAULT 0,
            extractor_version TEXT NOT NULL,
            eligible_count INTEGER NOT NULL DEFAULT 0,
            ignored_count INTEGER NOT NULL DEFAULT 0,
            generated_count INTEGER NOT NULL DEFAULT 0,
            parsed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            structure_status TEXT NOT NULL DEFAULT 'waiting',
            retrieval_status TEXT NOT NULL DEFAULT 'waiting',
            interpretation_status TEXT NOT NULL DEFAULT 'unavailable',
            manifest_json TEXT NOT NULL DEFAULT '{}',
            activated_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_index_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT,
            trigger_source TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'discovery',
            eligible_total INTEGER NOT NULL DEFAULT 0,
            completed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            cancellation_requested INTEGER NOT NULL DEFAULT 0,
            failure_category TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS project_sources (
            project_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_role TEXT NOT NULL DEFAULT 'source',
            content_hash TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_id, source_id),
            UNIQUE (project_id, relative_path),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_cluster_links (
            project_id TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('primary', 'linked')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, cluster_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS code_nodes (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            source_id TEXT,
            qualified_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            display_label TEXT NOT NULL,
            relative_path TEXT NOT NULL DEFAULT '',
            start_line INTEGER,
            start_column INTEGER,
            end_line INTEGER,
            end_column INTEGER,
            signature TEXT NOT NULL DEFAULT '',
            extraction_method TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
            UNIQUE(snapshot_id, qualified_id)
        );
        CREATE TABLE IF NOT EXISTS code_edges (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            evidence_source_id TEXT,
            source_line INTEGER,
            extraction_method TEXT NOT NULL,
            confidence_class TEXT NOT NULL DEFAULT 'extracted',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (source_node_id) REFERENCES code_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_node_id) REFERENCES code_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (evidence_source_id) REFERENCES sources(id) ON DELETE CASCADE,
            UNIQUE(snapshot_id, source_node_id, target_node_id, edge_type, source_line)
        );
        CREATE TABLE IF NOT EXISTS relationship_suggestions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            source_node_id TEXT,
            target_node_id TEXT,
            suggested_type TEXT NOT NULL,
            score REAL NOT NULL,
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            review_state TEXT NOT NULL DEFAULT 'pending',
            extractor_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (source_node_id) REFERENCES code_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_node_id) REFERENCES code_nodes(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_vault_name
            ON projects(vault_id, lower(name)) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_projects_primary_cluster
            ON projects(primary_cluster_id) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_project_sources_source ON project_sources(source_id);
        CREATE INDEX IF NOT EXISTS idx_project_snapshots_project
            ON project_snapshots(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_project_runs_project
            ON project_index_runs(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_code_nodes_lookup
            ON code_nodes(project_id, snapshot_id, kind, qualified_id);
        CREATE INDEX IF NOT EXISTS idx_code_edges_source
            ON code_edges(project_id, snapshot_id, source_node_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_code_edges_target
            ON code_edges(project_id, snapshot_id, target_node_id, edge_type);
        """
    )


def _migration_009_project_chat_scope(conn) -> None:
    _add_column_if_missing(conn, "chat_sessions", "scope_project_id", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_project ON chat_sessions(scope_project_id, updated_at DESC)"
    )


def _migration_010_odin_release_contracts(conn) -> None:
    for column, definition in (
        ("active_manifest_snapshot_id", "TEXT"),
        ("active_structure_snapshot_id", "TEXT"),
        ("active_retrieval_snapshot_id", "TEXT"),
        ("candidate_snapshot_id", "TEXT"),
        ("active_run_id", "TEXT"),
    ):
        _add_column_if_missing(conn, "projects", column, definition)
    for column, definition in (
        ("manifest_activated_at", "TEXT"),
        ("structure_activated_at", "TEXT"),
        ("retrieval_activated_at", "TEXT"),
    ):
        _add_column_if_missing(conn, "project_snapshots", column, definition)
    for column, definition in (
        ("cancellation_requested_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
        ("queued_at", "TEXT"),
        ("job_id", "TEXT"),
        ("phase_completed_count", "INTEGER NOT NULL DEFAULT 0"),
        ("phase_total_count", "INTEGER NOT NULL DEFAULT 0"),
        ("activation_outcome", "TEXT NOT NULL DEFAULT ''"),
    ):
        _add_column_if_missing(conn, "project_index_runs", column, definition)
    for table, column, definition in (
        ("sources", "project_id", "TEXT"),
        ("sources", "project_snapshot_id", "TEXT"),
        ("sources", "activation_state", "TEXT NOT NULL DEFAULT 'active'"),
        ("source_chunks", "project_id", "TEXT"),
        ("source_chunks", "project_snapshot_id", "TEXT"),
        ("source_chunks", "activation_state", "TEXT NOT NULL DEFAULT 'active'"),
    ):
        _add_column_if_missing(conn, table, column, definition)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_snapshot_sources (
            snapshot_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            source_id TEXT,
            prior_source_id TEXT,
            relative_path TEXT NOT NULL,
            file_role TEXT NOT NULL DEFAULT 'source',
            language TEXT NOT NULL DEFAULT '',
            byte_size INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL,
            resolved_path_hash TEXT NOT NULL DEFAULT '',
            exclusion_decision TEXT NOT NULL DEFAULT 'included',
            intended_action TEXT NOT NULL DEFAULT 'unchanged',
            stage_status TEXT NOT NULL DEFAULT 'discovered',
            parser_status TEXT NOT NULL DEFAULT 'waiting',
            retrieval_status TEXT NOT NULL DEFAULT 'waiting',
            error_category TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (snapshot_id, relative_path),
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
            FOREIGN KEY (prior_source_id) REFERENCES sources(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS cli_clients (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            executable_fingerprint TEXT NOT NULL,
            credential_hash TEXT NOT NULL,
            credential_version INTEGER NOT NULL DEFAULT 1,
            scopes_json TEXT NOT NULL DEFAULT '[]',
            allowed_vault_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            rotated_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS cli_pairing_challenges (
            id TEXT PRIMARY KEY,
            client_id TEXT,
            verifier_hash TEXT NOT NULL,
            requested_scopes_json TEXT NOT NULL DEFAULT '[]',
            requester_name TEXT NOT NULL DEFAULT '',
            executable_fingerprint TEXT NOT NULL DEFAULT '',
            runtime_instance_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            failed_attempt_count INTEGER NOT NULL DEFAULT 0,
            last_polled_at TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            approved_at TEXT,
            denied_at TEXT,
            consumed_at TEXT,
            FOREIGN KEY (client_id) REFERENCES cli_clients(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS cli_sessions (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            session_version INTEGER NOT NULL DEFAULT 1,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY (client_id) REFERENCES cli_clients(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cli_auth_audit (
            id TEXT PRIMARY KEY,
            client_id TEXT,
            challenge_id TEXT,
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES cli_clients(id) ON DELETE SET NULL,
            FOREIGN KEY (challenge_id) REFERENCES cli_pairing_challenges(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_snapshot_sources_project
            ON project_snapshot_sources(project_id, snapshot_id, relative_path);
        CREATE INDEX IF NOT EXISTS idx_project_snapshot_sources_source
            ON project_snapshot_sources(source_id);
        CREATE INDEX IF NOT EXISTS idx_project_runs_job ON project_index_runs(job_id);
        CREATE INDEX IF NOT EXISTS idx_project_runs_active
            ON project_index_runs(project_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sources_project_snapshot
            ON sources(project_id, project_snapshot_id, activation_state);
        CREATE INDEX IF NOT EXISTS idx_source_chunks_project_snapshot
            ON source_chunks(project_id, project_snapshot_id, activation_state);
        CREATE INDEX IF NOT EXISTS idx_cli_clients_active
            ON cli_clients(revoked_at, last_used_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cli_sessions_token_hash ON cli_sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_cli_sessions_client
            ON cli_sessions(client_id, expires_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cli_pairing_status
            ON cli_pairing_challenges(status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_cli_auth_audit_client
            ON cli_auth_audit(client_id, created_at DESC);
        """
    )
    for column, definition in (
        ("resolved_path_hash", "TEXT NOT NULL DEFAULT ''"),
        ("exclusion_decision", "TEXT NOT NULL DEFAULT 'included'"),
        ("parser_status", "TEXT NOT NULL DEFAULT 'waiting'"),
        ("retrieval_status", "TEXT NOT NULL DEFAULT 'waiting'"),
    ):
        _add_column_if_missing(conn, "project_snapshot_sources", column, definition)
    _add_column_if_missing(conn, "cli_pairing_challenges", "client_id", "TEXT")
    _add_column_if_missing(conn, "cli_pairing_challenges", "failed_attempt_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "cli_pairing_challenges", "last_polled_at", "TEXT")
    conn.execute(
        """
        UPDATE projects
        SET active_manifest_snapshot_id = COALESCE(active_manifest_snapshot_id, active_snapshot_id),
            active_structure_snapshot_id = COALESCE(active_structure_snapshot_id, active_snapshot_id),
            active_retrieval_snapshot_id = COALESCE(active_retrieval_snapshot_id, active_snapshot_id)
        WHERE active_snapshot_id IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE project_snapshots
        SET manifest_activated_at = COALESCE(manifest_activated_at, activated_at),
            structure_activated_at = CASE
                WHEN structure_status IN ('ready', 'partial')
                THEN COALESCE(structure_activated_at, activated_at)
                ELSE structure_activated_at
            END,
            retrieval_activated_at = CASE
                WHEN retrieval_status IN ('ready', 'partial')
                THEN COALESCE(retrieval_activated_at, activated_at)
                ELSE retrieval_activated_at
            END
        WHERE activated_at IS NOT NULL
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO project_snapshot_sources (
            snapshot_id, project_id, source_id, prior_source_id, relative_path, file_role,
            language, byte_size, content_hash, intended_action, stage_status,
            error_category, created_at, updated_at
        )
        SELECT p.active_snapshot_id, ps.project_id, ps.source_id, ps.source_id,
               ps.relative_path, ps.file_role, '', 0, ps.content_hash,
               'unchanged', 'active', '', ps.discovered_at, ps.updated_at
        FROM project_sources ps
        JOIN projects p ON p.id = ps.project_id
        WHERE p.active_snapshot_id IS NOT NULL
        """
    )


def _migration_011_project_discovery_scope(conn) -> None:
    _add_column_if_missing(
        conn,
        "projects",
        "discovery_scope",
        "TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code'))",
    )
    _add_column_if_missing(
        conn,
        "project_snapshots",
        "discovery_scope",
        "TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code'))",
    )
    conn.execute(
        "UPDATE projects SET discovery_scope = 'context' WHERE discovery_scope NOT IN ('context', 'code')"
    )
    conn.execute(
        "UPDATE project_snapshots SET discovery_scope = 'context' WHERE discovery_scope NOT IN ('context', 'code')"
    )


def _migration_012_cluster_suggestion_decisions(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cluster_suggestion_decisions (
            source_id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            suggested_cluster_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('accepted', 'dismissed')),
            source_updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_decisions_vault
            ON cluster_suggestion_decisions(vault_id, updated_at DESC);
        """
    )


def _migration_013_cluster_identity_origin(conn) -> None:
    if not _table_exists(conn, "clusters"):
        return
    _add_column_if_missing(conn, "clusters", "name_origin", "TEXT NOT NULL DEFAULT 'user'")
    conn.execute(
        """
        UPDATE clusters
        SET name_origin = 'auto'
        WHERE name_origin = 'user'
          AND description <> ''
          AND description NOT LIKE '%.%'
          AND description NOT LIKE '%:%'
          AND (
              description LIKE '%,%'
              OR lower(description) = lower(name)
          )
        """
    )


def _migration_014_stable_cluster_suggestion_batches(conn) -> None:
    _add_column_if_missing(
        conn,
        "sources",
        "metadata_version",
        "INTEGER NOT NULL DEFAULT 1",
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cluster_suggestion_batches (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cluster_suggestion_candidates (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            vault_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            current_cluster_id TEXT,
            suggested_cluster_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            source_updated_at TEXT NOT NULL,
            decision TEXT,
            decided_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES cluster_suggestion_batches(id) ON DELETE CASCADE,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
            FOREIGN KEY (current_cluster_id) REFERENCES clusters(id) ON DELETE SET NULL,
            FOREIGN KEY (suggested_cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
            UNIQUE(batch_id, source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_batches_vault
            ON cluster_suggestion_batches(vault_id, status, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cluster_suggestion_one_active_batch
            ON cluster_suggestion_batches(vault_id) WHERE status = 'active';
        CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_candidates_batch
            ON cluster_suggestion_candidates(batch_id, decision, confidence DESC);
        """
    )
    required_cleanup_tables = {
        "clusters",
        "sources",
        "chat_sessions",
        "projects",
        "project_cluster_links",
    }
    if not all(_table_exists(conn, table) for table in required_cleanup_tables):
        return
    conn.executescript(
        """
        DELETE FROM cluster_suggestion_decisions
        WHERE NOT EXISTS (
            SELECT 1 FROM clusters
            WHERE clusters.id = cluster_suggestion_decisions.suggested_cluster_id
              AND clusters.vault_id = cluster_suggestion_decisions.vault_id
        );
        DELETE FROM clusters
        WHERE name_origin = 'auto'
          AND NOT EXISTS (
              SELECT 1 FROM sources
              WHERE sources.cluster_id = clusters.id
                AND sources.deleted_at IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM chat_sessions
              WHERE chat_sessions.scope_cluster_id = clusters.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM projects
              WHERE projects.primary_cluster_id = clusters.id
                AND projects.deleted_at IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM project_cluster_links
              WHERE project_cluster_links.cluster_id = clusters.id
          );
        UPDATE clusters
        SET profile_status = 'stale',
            profile_source_hash = ''
        WHERE name_origin = 'auto'
          AND EXISTS (
              SELECT 1 FROM sources
              WHERE sources.cluster_id = clusters.id
                AND sources.deleted_at IS NULL
          );
        """
    )


def _migration_015_source_folder_membership(conn) -> None:
    _add_column_if_missing(conn, "sources", "import_root_path", "TEXT")
    _add_column_if_missing(conn, "sources", "import_relative_path", "TEXT")
    source_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
    }
    if not {"vault_id", "activation_state", "deleted_at"} <= source_columns:
        return
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sources_import_root
        ON sources(vault_id, import_root_path, activation_state, deleted_at)
        """
    )


def _migration_016_repair_project_chunk_scope(conn) -> None:
    """Repair project chunks activated before their source joined the project cluster."""
    source_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
    }
    chunk_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(source_chunks)").fetchall()
    }
    required_source_columns = {"id", "cluster_id", "activation_state", "deleted_at"}
    required_chunk_columns = {
        "source_id",
        "project_id",
        "activation_state",
        "cluster_id",
    }
    if not required_source_columns <= source_columns or not required_chunk_columns <= chunk_columns:
        return
    conn.execute(
        """
        UPDATE source_chunks
        SET cluster_id = (
            SELECT sources.cluster_id
            FROM sources
            WHERE sources.id = source_chunks.source_id
        )
        WHERE source_chunks.project_id IS NOT NULL
          AND source_chunks.activation_state = 'active'
          AND EXISTS (
              SELECT 1
              FROM sources
              WHERE sources.id = source_chunks.source_id
                AND sources.activation_state = 'active'
                AND sources.deleted_at IS NULL
                AND sources.cluster_id IS NOT NULL
                AND (
                    source_chunks.cluster_id IS NULL
                    OR source_chunks.cluster_id <> sources.cluster_id
                )
          )
        """
    )


def _migration_017_cluster_candidate_profiles(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cluster_candidate_profiles (
            cluster_id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            profile_version INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            derived_state_tuple TEXT NOT NULL DEFAULT '{}',
            centroid TEXT NOT NULL DEFAULT '',
            lexical_terms TEXT NOT NULL DEFAULT '{}',
            source_type_distribution TEXT NOT NULL DEFAULT '{}',
            representative_source_ids TEXT NOT NULL DEFAULT '[]',
            cohesion REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cluster_candidate_terms (
            cluster_id TEXT NOT NULL,
            vault_id TEXT NOT NULL,
            term TEXT NOT NULL,
            weight REAL NOT NULL,
            PRIMARY KEY (cluster_id, term),
            FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cluster_candidate_terms_lookup
            ON cluster_candidate_terms(vault_id, term, weight DESC, cluster_id);
        CREATE INDEX IF NOT EXISTS idx_cluster_candidate_profiles_vault
            ON cluster_candidate_profiles(vault_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cli_clients_active_created
            ON cli_clients(created_at DESC, id DESC)
            WHERE revoked_at IS NULL AND rotated_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_cli_clients_history_created
            ON cli_clients(created_at DESC, id DESC)
            WHERE revoked_at IS NOT NULL OR rotated_at IS NOT NULL;
        """
    )
    for table in ("cluster_suggestion_decisions", "cluster_suggestion_candidates"):
        _add_column_if_missing(conn, table, "source_content_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, table, "candidate_profile_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, table, "candidate_profile_version", "INTEGER NOT NULL DEFAULT 0")


def _migration_018_stable_cluster_suggestion_evidence(conn) -> None:
    for table in ("cluster_suggestion_decisions", "cluster_suggestion_candidates"):
        _add_column_if_missing(conn, table, "source_content_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, table, "candidate_profile_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, table, "candidate_profile_version", "INTEGER NOT NULL DEFAULT 0")


def _migration_019_cluster_membership_integrity(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cluster_membership_events (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            previous_cluster_id TEXT,
            target_cluster_id TEXT,
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT 'system',
            source_updated INTEGER NOT NULL DEFAULT 0,
            chunks_updated INTEGER NOT NULL DEFAULT 0,
            facts_updated INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cluster_membership_events_source
            ON cluster_membership_events(source_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cluster_membership_events_vault
            ON cluster_membership_events(vault_id, created_at DESC);
        """
    )


def _migration_020_job_diagnostics(conn) -> None:
    if not _table_exists(conn, "app_jobs"):
        return
    _add_column_if_missing(conn, "app_jobs", "error_code", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "app_jobs", "diagnostic_id", "TEXT NOT NULL DEFAULT ''")


def _migration_021_chat_generation_identity(conn) -> None:
    if not _table_exists(conn, "chat_generations"):
        return
    _add_column_if_missing(conn, "chat_generations", "request_id", "TEXT")
    _add_column_if_missing(conn, "chat_generations", "parent_generation_id", "TEXT")
    _add_column_if_missing(conn, "chat_generations", "attempt_number", "INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_generations_request_id
        ON chat_generations(vault_id, request_id)
        WHERE request_id IS NOT NULL AND request_id <> ''
        """
    )


def _migration_022_app_profile(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_profile (
            id TEXT PRIMARY KEY CHECK (id = 'local'),
            display_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )


def _migration_023_project_delta_sync(conn) -> None:
    _add_column_if_missing(conn, "projects", "auto_sync_enabled", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "projects", "change_fingerprint", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "projects", "last_change_checked_at", "TEXT")


def _migration_024_unclustered_chat_scope(conn) -> None:
    if not _table_exists(conn, "chat_sessions"):
        return
    _add_column_if_missing(
        conn,
        "chat_sessions",
        "scope_unclustered",
        "INTEGER NOT NULL DEFAULT 0",
    )


def _migration_025_semantic_source_metadata(conn) -> None:
    _add_column_if_missing(conn, "sources", "metadata_quality", "TEXT NOT NULL DEFAULT 'fallback'")
    _add_column_if_missing(conn, "sources", "semantic_metadata_version", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sources", "semantic_metadata_updated_at", "TEXT")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
    if {"vault_id", "state", "deleted_at"} <= columns:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sources_semantic_metadata_backlog
            ON sources(vault_id, semantic_metadata_version, state, deleted_at)
            """
        )


def _migration_026_source_ingestion_stages(conn) -> None:
    _add_column_if_missing(conn, "sources", "ingestion_stage", "TEXT NOT NULL DEFAULT 'ready'")
    _add_column_if_missing(conn, "sources", "ingestion_generation", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "sources", "ingestion_error_code", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "sources", "ingestion_status_detail", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "sources", "ingestion_updated_at", "TEXT")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
    if {"state", "updated_at"} <= columns:
        conn.execute(
            """
            UPDATE sources
            SET ingestion_stage = CASE
                    WHEN state = 'failed' THEN 'needs_attention'
                    WHEN state = 'waiting' THEN 'imported'
                    WHEN state = 'processing' THEN 'extracting'
                    ELSE 'ready'
                END,
                ingestion_updated_at = COALESCE(ingestion_updated_at, updated_at)
            WHERE ingestion_updated_at IS NULL OR ingestion_updated_at = ''
            """
        )
    if {"vault_id", "id"} <= columns:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sources_ingestion_progress
            ON sources(vault_id, ingestion_stage, ingestion_updated_at, id)
            """
        )


def _migration_027_adaptive_scheduler_state(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_lane_state (
            capability_fingerprint TEXT NOT NULL,
            lane TEXT NOT NULL,
            current_limit INTEGER NOT NULL,
            stable_observations INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_latency_ms REAL NOT NULL DEFAULT 0,
            last_pressure_event TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (capability_fingerprint, lane)
        )
        """
    )


def _migration_028_project_sync_modes(conn) -> None:
    _add_column_if_missing(conn, "projects", "sync_mode", "TEXT NOT NULL DEFAULT 'automatic'")
    conn.execute(
        """
        UPDATE projects
        SET sync_mode = CASE WHEN auto_sync_enabled = 1 THEN 'automatic' ELSE 'manual' END
        WHERE sync_mode IS NULL OR sync_mode = '' OR sync_mode NOT IN ('automatic', 'notify', 'manual')
        """
    )


def _migration_029_project_intelligence_foundation(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_intelligence_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owning_snapshot_id TEXT NOT NULL,
            structure_snapshot_id TEXT,
            retrieval_snapshot_id TEXT,
            contract_version TEXT NOT NULL,
            identity_json TEXT NOT NULL DEFAULT '{}',
            architecture_json TEXT NOT NULL DEFAULT '{}',
            repository_signals_json TEXT NOT NULL DEFAULT '{}',
            decisions_json TEXT NOT NULL DEFAULT '{}',
            interpretation_json TEXT NOT NULL DEFAULT '{}',
            freshness_json TEXT NOT NULL DEFAULT '{}',
            layer_states_json TEXT NOT NULL DEFAULT '{}',
            generated_at TEXT NOT NULL,
            activated_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (owning_snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (structure_snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL,
            FOREIGN KEY (retrieval_snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL,
            UNIQUE(project_id, owning_snapshot_id)
        );
        CREATE TABLE IF NOT EXISTS project_intelligence_evidence (
            id TEXT PRIMARY KEY,
            intelligence_snapshot_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            relative_path TEXT NOT NULL DEFAULT '',
            source_snapshot TEXT,
            start_line INTEGER,
            end_line INTEGER,
            extraction_method TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            confidence_class TEXT NOT NULL,
            excerpt_hash TEXT NOT NULL,
            verification_state TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (intelligence_snapshot_id) REFERENCES project_intelligence_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_intelligence_active
            ON project_intelligence_snapshots(project_id, owning_snapshot_id, generated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_project_intelligence_structure
            ON project_intelligence_snapshots(project_id, structure_snapshot_id, generated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_project_intelligence_evidence_snapshot
            ON project_intelligence_evidence(intelligence_snapshot_id, source_type, relative_path);
        """
    )


def _migration_030_project_intelligence_layers(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_graph_metrics (
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            pagerank REAL NOT NULL DEFAULT 0,
            in_degree INTEGER NOT NULL DEFAULT 0,
            out_degree INTEGER NOT NULL DEFAULT 0,
            scc_id TEXT NOT NULL DEFAULT '',
            scc_size INTEGER NOT NULL DEFAULT 1,
            community_id TEXT NOT NULL DEFAULT '',
            community_label TEXT NOT NULL DEFAULT '',
            is_cycle INTEGER NOT NULL DEFAULT 0,
            computed_at TEXT NOT NULL,
            PRIMARY KEY (project_id, snapshot_id, node_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (node_id) REFERENCES code_nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_graph_metrics_rank
            ON project_graph_metrics(project_id, snapshot_id, pagerank DESC);
        CREATE INDEX IF NOT EXISTS idx_project_graph_metrics_community
            ON project_graph_metrics(project_id, snapshot_id, community_id, pagerank DESC);

        CREATE TABLE IF NOT EXISTS project_graph_communities (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            label TEXT NOT NULL,
            root_path TEXT NOT NULL DEFAULT '',
            node_count INTEGER NOT NULL DEFAULT 0,
            file_count INTEGER NOT NULL DEFAULT 0,
            summary_json TEXT NOT NULL DEFAULT '{}',
            computed_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE,
            UNIQUE(project_id, snapshot_id, root_path)
        );

        CREATE TABLE IF NOT EXISTS project_execution_flows (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            start_node_id TEXT NOT NULL,
            end_node_id TEXT NOT NULL,
            node_ids_json TEXT NOT NULL,
            relationships_json TEXT NOT NULL,
            confidence_class TEXT NOT NULL,
            reason TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id) REFERENCES project_snapshots(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_execution_flows_snapshot
            ON project_execution_flows(project_id, snapshot_id, start_node_id);

        CREATE TABLE IF NOT EXISTS project_git_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owning_snapshot_id TEXT,
            indexed_commit TEXT,
            head_commit TEXT,
            branch TEXT,
            history_available INTEGER NOT NULL DEFAULT 0,
            history_truncated INTEGER NOT NULL DEFAULT 0,
            shallow_history INTEGER NOT NULL DEFAULT 0,
            commit_count INTEGER NOT NULL DEFAULT 0,
            live_state_json TEXT NOT NULL DEFAULT '{}',
            recent_commits_json TEXT NOT NULL DEFAULT '[]',
            error_detail TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (owning_snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL,
            UNIQUE(project_id, owning_snapshot_id)
        );
        CREATE INDEX IF NOT EXISTS idx_project_git_snapshots_latest
            ON project_git_snapshots(project_id, generated_at DESC);

        CREATE TABLE IF NOT EXISTS project_git_file_signals (
            project_id TEXT NOT NULL,
            git_snapshot_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            additions INTEGER NOT NULL DEFAULT 0,
            deletions INTEGER NOT NULL DEFAULT 0,
            commit_count INTEGER NOT NULL DEFAULT 0,
            bugfix_commit_count INTEGER NOT NULL DEFAULT 0,
            last_commit_id TEXT,
            last_commit_at TEXT,
            last_commit_subject TEXT NOT NULL DEFAULT '',
            ownership_json TEXT NOT NULL DEFAULT '[]',
            history_truncated INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (git_snapshot_id, relative_path),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (git_snapshot_id) REFERENCES project_git_snapshots(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_git_file_signals_path
            ON project_git_file_signals(project_id, relative_path);

        CREATE TABLE IF NOT EXISTS project_cochange_edges (
            project_id TEXT NOT NULL,
            git_snapshot_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            touch_count INTEGER NOT NULL,
            confidence_class TEXT NOT NULL,
            heuristic_label TEXT NOT NULL,
            PRIMARY KEY (git_snapshot_id, source_path, target_path),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (git_snapshot_id) REFERENCES project_git_snapshots(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_cochange_source
            ON project_cochange_edges(project_id, source_path, touch_count DESC);

        CREATE TABLE IF NOT EXISTS project_decisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owning_snapshot_id TEXT,
            statement TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            governed_paths_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            confidence_class TEXT NOT NULL,
            verification_state TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            user_created INTEGER NOT NULL DEFAULT 0,
            stale_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (owning_snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_decisions_active
            ON project_decisions(project_id, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS project_decision_evidence (
            id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            source_id TEXT,
            relative_path TEXT NOT NULL DEFAULT '',
            start_line INTEGER,
            end_line INTEGER,
            excerpt_hash TEXT NOT NULL,
            extraction_method TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (decision_id) REFERENCES project_decisions(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS project_decision_edges (
            project_id TEXT NOT NULL,
            source_decision_id TEXT NOT NULL,
            target_decision_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            verification_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (source_decision_id, target_decision_id, relationship_type),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (source_decision_id) REFERENCES project_decisions(id) ON DELETE CASCADE,
            FOREIGN KEY (target_decision_id) REFERENCES project_decisions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS project_coverage_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owning_snapshot_id TEXT,
            indexed_commit TEXT,
            artifact_path TEXT NOT NULL DEFAULT '',
            format TEXT NOT NULL,
            status TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            test_count INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (owning_snapshot_id) REFERENCES project_snapshots(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_coverage_latest
            ON project_coverage_snapshots(project_id, generated_at DESC);

        CREATE TABLE IF NOT EXISTS project_coverage_files (
            coverage_snapshot_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            covered_lines_json TEXT NOT NULL DEFAULT '[]',
            missed_lines_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (coverage_snapshot_id, relative_path),
            FOREIGN KEY (coverage_snapshot_id) REFERENCES project_coverage_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_coverage_test_map (
            coverage_snapshot_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            test_name TEXT NOT NULL,
            test_path TEXT NOT NULL,
            source_path TEXT NOT NULL,
            covered_lines_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (coverage_snapshot_id, test_name, source_path),
            FOREIGN KEY (coverage_snapshot_id) REFERENCES project_coverage_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_coverage_source
            ON project_coverage_test_map(project_id, source_path, test_path);
        """
    )


def _migration_031_snapshot_scoped_graph_communities(conn) -> None:
    """Repair globally colliding community IDs written by graph intelligence v1."""
    if not _table_exists(conn, "project_graph_communities"):
        return
    rows = conn.execute(
        """SELECT id, project_id, snapshot_id, root_path
           FROM project_graph_communities"""
    ).fetchall()
    for row in rows:
        root = str(row["root_path"] or "") or "(project root)"
        legacy_id = "community-" + hashlib.sha256(
            root.casefold().encode("utf-8")
        ).hexdigest()[:16]
        if str(row["id"]) != legacy_id:
            continue
        scoped_id = "community-" + hashlib.sha256(
            "\0".join(
                (str(row["project_id"]), str(row["snapshot_id"]), root.casefold())
            ).encode("utf-8")
        ).hexdigest()[:16]
        conn.execute(
            """UPDATE project_graph_metrics SET community_id = ?
               WHERE project_id = ? AND snapshot_id = ? AND community_id = ?""",
            (scoped_id, row["project_id"], row["snapshot_id"], legacy_id),
        )
        existing = conn.execute(
            "SELECT 1 FROM project_graph_communities WHERE id = ?", (scoped_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE project_graph_communities SET id = ? WHERE id = ?",
                (scoped_id, legacy_id),
            )
        else:
            conn.execute("DELETE FROM project_graph_communities WHERE id = ?", (legacy_id,))


def _migration_032_security_scope_and_bridge_storage(conn) -> None:
    """Freeze legacy allow-all clients to explicit existing-vault scopes."""
    if _table_exists(conn, "bridge_requests"):
        _add_column_if_missing(conn, "bridge_requests", "vault_id", "TEXT")
        # Historical request rows had no vault association, so they cannot be
        # safely migrated under vault-bound AAD. Purge rather than guess a key.
        conn.execute("UPDATE bridge_requests SET query = ''")
    vault_ids = (
        [str(row["id"]) for row in conn.execute("SELECT id FROM vaults ORDER BY id").fetchall()]
        if _table_exists(conn, "vaults")
        else []
    )
    explicit_vault_scope = json.dumps(vault_ids, separators=(",", ":"))
    now = utc_now()
    if _table_exists(conn, "extension_clients"):
        if vault_ids:
            conn.execute(
                """UPDATE extension_clients SET allowed_vault_ids = ?, updated_at = ?
                   WHERE TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'""",
                (explicit_vault_scope, now),
            )
        else:
            conn.execute(
                """UPDATE extension_clients SET enabled = 0, updated_at = ?
                   WHERE TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'""",
                (now,),
            )
    if _table_exists(conn, "bridge_clients"):
        if vault_ids:
            conn.execute(
                """UPDATE bridge_clients SET allowed_vault_ids = ?, updated_at = ?
                   WHERE TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'
                     AND TRIM(COALESCE(allowed_cluster_ids, '[]')) = '[]'""",
                (explicit_vault_scope, now),
            )
        else:
            conn.execute(
                """UPDATE bridge_clients SET enabled = 0, revoked_at = COALESCE(revoked_at, ?), updated_at = ?
                   WHERE TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'
                     AND TRIM(COALESCE(allowed_cluster_ids, '[]')) = '[]'""",
                (now, now),
            )
    if _table_exists(conn, "bridge_context_packets") and _table_exists(conn, "vault_security_metadata"):
        conn.execute(
            """UPDATE bridge_context_packets
               SET query = '', packet_text = ''
               WHERE vault_id IN (SELECT vault_id FROM vault_security_metadata)"""
        )


def _migration_033_security_scan_schedule(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_scan_settings (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            enabled INTEGER NOT NULL DEFAULT 1,
            interval_days INTEGER NOT NULL DEFAULT 30 CHECK (interval_days BETWEEN 1 AND 365),
            last_started_at TEXT,
            last_completed_at TEXT,
            last_scan_type TEXT,
            last_status TEXT NOT NULL DEFAULT 'never_run',
            last_summary_json TEXT NOT NULL DEFAULT '{}',
            next_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _migration_034_chat_generation_leases(conn) -> None:
    if not _table_exists(conn, "chat_generations"):
        return
    _add_column_if_missing(conn, "chat_generations", "lease_owner", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "chat_generations", "cancellation_requested_at", "TEXT")
    now = utc_now()
    duplicate_sessions = conn.execute(
        """
        SELECT session_id
        FROM chat_generations
        WHERE state = 'in_flight'
        GROUP BY session_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for duplicate in duplicate_sessions:
        rows = conn.execute(
            """
            SELECT id FROM chat_generations
            WHERE session_id = ? AND state = 'in_flight'
            ORDER BY COALESCE(heartbeat_at, updated_at, created_at) DESC, id DESC
            """,
            (duplicate["session_id"],),
        ).fetchall()
        for stale in rows[1:]:
            conn.execute(
                """
                UPDATE chat_generations
                SET state = 'retriable', lease_owner = '',
                    error = 'Superseded while repairing duplicate active generations.',
                    updated_at = ?
                WHERE id = ? AND state = 'in_flight'
                """,
                (now, stale["id"]),
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_generations_one_active_session
        ON chat_generations(session_id)
        WHERE state = 'in_flight'
        """
    )


def _migration_035_background_job_leases(conn) -> None:
    if not _table_exists(conn, "app_jobs"):
        return
    _add_column_if_missing(conn, "app_jobs", "claim_token", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "app_jobs", "heartbeat_at", "TEXT")
    _add_column_if_missing(conn, "app_jobs", "deadline_at", "TEXT")


def _migration_036_watched_folder_backoff(conn) -> None:
    if _table_exists(conn, "integration_imports"):
        _add_column_if_missing(conn, "integration_imports", "watch_failure_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "watch_last_error", "TEXT NOT NULL DEFAULT ''")
    if _table_exists(conn, "sources"):
        source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if {"vault_id", "import_root_path", "deleted_at", "original_path"} <= source_columns:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sources_import_root_active "
                "ON sources(vault_id, import_root_path, deleted_at, original_path)"
            )


def _migration_037_maintenance_coordinator(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_state (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            last_started_at TEXT,
            last_completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'never_run',
            last_report_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
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
    8: _migration_008_project_graph,
    9: _migration_009_project_chat_scope,
    10: _migration_010_odin_release_contracts,
    11: _migration_011_project_discovery_scope,
    12: _migration_012_cluster_suggestion_decisions,
    13: _migration_013_cluster_identity_origin,
    14: _migration_014_stable_cluster_suggestion_batches,
    15: _migration_015_source_folder_membership,
    16: _migration_016_repair_project_chunk_scope,
    17: _migration_017_cluster_candidate_profiles,
    18: _migration_018_stable_cluster_suggestion_evidence,
    19: _migration_019_cluster_membership_integrity,
    20: _migration_020_job_diagnostics,
    21: _migration_021_chat_generation_identity,
    22: _migration_022_app_profile,
    23: _migration_023_project_delta_sync,
    24: _migration_024_unclustered_chat_scope,
    25: _migration_025_semantic_source_metadata,
    26: _migration_026_source_ingestion_stages,
    27: _migration_027_adaptive_scheduler_state,
    28: _migration_028_project_sync_modes,
    29: _migration_029_project_intelligence_foundation,
    30: _migration_030_project_intelligence_layers,
    31: _migration_031_snapshot_scoped_graph_communities,
    32: _migration_032_security_scope_and_bridge_storage,
    33: _migration_033_security_scan_schedule,
    34: _migration_034_chat_generation_leases,
    35: _migration_035_background_job_leases,
    36: _migration_036_watched_folder_backoff,
    37: _migration_037_maintenance_coordinator,
}


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table_exists(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


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
        _add_column_if_missing(conn, "schema_migrations", "lease_owner", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "schema_migrations", "heartbeat_at", "TEXT")
        _add_column_if_missing(conn, "schema_migrations", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "schema_migrations", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        running = conn.execute(
            "SELECT version, name FROM schema_migrations WHERE status = 'running' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if running is not None:
            version = int(running["version"])
            registered = MIGRATIONS.get(version)
            expected_name = (
                registered.__name__.removeprefix("_migration_") if registered is not None else ""
            )
            compatible_names = {expected_name, expected_name.split("_", 1)[-1]}
            if version not in RESTARTABLE_MIGRATION_VERSIONS or running["name"] not in compatible_names:
                raise MigrationError(
                    "Previous migration cannot be retried automatically: "
                    f"{version} {running['name']}. Preserve a database backup and use migration recovery."
                )
            conn.execute(
                """
                UPDATE schema_migrations
                SET status = 'failed', finished_at = ?, lease_owner = '', heartbeat_at = ?,
                    error = 'Interrupted migration detected; safe retry scheduled.'
                WHERE version = ? AND status = 'running'
                """,
                (utc_now(), utc_now(), version),
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
            lease_owner = f"migration-{uuid4()}"
            previous = conn.execute(
                "SELECT status FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if previous is None:
                conn.execute(
                    """
                    INSERT INTO schema_migrations (
                        version, name, started_at, status, lease_owner, heartbeat_at,
                        attempt_count, metadata_json
                    )
                    VALUES (?, ?, ?, 'running', ?, ?, 1, ?)
                    """,
                    (
                        version,
                        name,
                        started_at,
                        lease_owner,
                        started_at,
                        json.dumps({"restartable": version in RESTARTABLE_MIGRATION_VERSIONS}),
                    ),
                )
            elif previous["status"] == "failed":
                conn.execute(
                    """
                    UPDATE schema_migrations
                    SET name = ?, started_at = ?, finished_at = NULL, status = 'running', error = '',
                        lease_owner = ?, heartbeat_at = ?, attempt_count = attempt_count + 1,
                        metadata_json = ?
                    WHERE version = ?
                    """,
                    (
                        name,
                        started_at,
                        lease_owner,
                        started_at,
                        json.dumps({"restartable": version in RESTARTABLE_MIGRATION_VERSIONS}),
                        version,
                    ),
                )
            else:
                raise MigrationError(f"Unexpected migration state for version {version}: {previous['status']}")
            try:
                migration(conn)
            except Exception as exc:
                conn.execute(
                    """
                    UPDATE schema_migrations
                    SET status = 'failed', finished_at = ?, heartbeat_at = ?, lease_owner = '', error = ?
                    WHERE version = ? AND status = 'running' AND lease_owner = ?
                    """,
                    (utc_now(), utc_now(), str(exc)[:1000], version, lease_owner),
                )
                raise MigrationError(f"Migration {version} failed: {exc}") from exc
            conn.execute(
                """
                UPDATE schema_migrations
                SET status = 'succeeded', finished_at = ?, heartbeat_at = ?, lease_owner = '', error = ''
                WHERE version = ? AND status = 'running' AND lease_owner = ?
                """,
                (utc_now(), utc_now(), version, lease_owner),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
