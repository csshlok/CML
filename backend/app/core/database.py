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
        # Older local databases may predate columns now used by startup indexes.
        # Add those columns first when the legacy tables already exist so init_db
        # can repair forward instead of crashing before migrations run.
        _add_column_if_missing_if_table_exists(conn, "sources", "provenance", "TEXT NOT NULL DEFAULT 'local_import'")
        _add_column_if_missing_if_table_exists(conn, "sources", "trust_tier", "TEXT NOT NULL DEFAULT 'trusted_local'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "embedding_model_id", "TEXT NOT NULL DEFAULT 'hash'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
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
            );

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
                provenance TEXT NOT NULL DEFAULT 'local_import',
                trust_tier TEXT NOT NULL DEFAULT 'trusted_local',
                security_labels TEXT NOT NULL DEFAULT '[]',
                parser_security_json TEXT NOT NULL DEFAULT '{}',
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
            );

            CREATE TABLE IF NOT EXISTS bridge_requests (
                id TEXT PRIMARY KEY,
                client_id TEXT,
                client_name TEXT NOT NULL DEFAULT 'unknown',
                query TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'context',
                decision TEXT NOT NULL DEFAULT 'allowed',
                source_count INTEGER NOT NULL DEFAULT 0,
                response_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES bridge_clients(id) ON DELETE SET NULL
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

            CREATE TABLE IF NOT EXISTS bridge_token_rotations (
                id TEXT PRIMARY KEY,
                rotated_at TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                previous_token_hash TEXT NOT NULL DEFAULT '',
                new_token_hash TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS bridge_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                approval_vault_id TEXT,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                allow_style_profile INTEGER NOT NULL DEFAULT 0,
                allow_expert_calls INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                approval_request_id TEXT,
                approved_at TEXT,
                revoked_at TEXT,
                last_request_at TEXT,
                request_count_total INTEGER NOT NULL DEFAULT 0,
                response_bytes_total INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (approval_vault_id) REFERENCES vaults(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_client_token_rotations (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                rotated_at TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                previous_token_hash TEXT NOT NULL DEFAULT '',
                new_token_hash TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (client_id) REFERENCES bridge_clients(id) ON DELETE CASCADE
            );

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
            );

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
            );

            CREATE TABLE IF NOT EXISTS bridge_rate_limits (
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                bucket TEXT NOT NULL,
                window_started_at TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope_type, scope_id, bucket)
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
                dataset_hash TEXT NOT NULL DEFAULT '',
                training_config_hash TEXT NOT NULL DEFAULT '',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 0,
                rolled_back_at TEXT,
                deleted_at TEXT,
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
            );

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
                content_profile TEXT NOT NULL DEFAULT 'prose',
                chunk_strategy TEXT NOT NULL DEFAULT 'word_window',
                chunk_meta_json TEXT NOT NULL DEFAULT '{}',
                content_hash TEXT NOT NULL DEFAULT '',
                index_version TEXT NOT NULL DEFAULT 'v1',
                normalization_version TEXT NOT NULL DEFAULT 'norm-v1',
                extraction_version TEXT NOT NULL DEFAULT 'extract-v1',
                derived_state_epoch INTEGER NOT NULL DEFAULT 1,
                indexed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (page_id) REFERENCES source_pages(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

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
            );

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
                index_version TEXT NOT NULL DEFAULT 'v1',
                normalization_version TEXT NOT NULL DEFAULT 'norm-v1',
                extraction_version TEXT NOT NULL DEFAULT 'extract-v1',
                derived_state_epoch INTEGER NOT NULL DEFAULT 1,
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

            CREATE TABLE IF NOT EXISTS analysis_evidence_packets (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                query TEXT NOT NULL,
                source_id TEXT,
                source_title TEXT NOT NULL DEFAULT '',
                relevance_score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                read_error TEXT NOT NULL DEFAULT '',
                evidence_excerpt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES app_jobs(id) ON DELETE SET NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                source_id TEXT,
                session_id TEXT,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                detail_text TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                freshness REAL NOT NULL DEFAULT 0.5,
                review_state TEXT NOT NULL DEFAULT 'auto',
                status TEXT NOT NULL DEFAULT 'active',
                origin_fingerprint TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                invalidated_at TEXT,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS working_memory_snapshots (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                scope_type TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source_count INTEGER NOT NULL DEFAULT 0,
                memory_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_context_packets (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                client_name TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL,
                packet_text TEXT NOT NULL DEFAULT '',
                evidence_handles_json TEXT NOT NULL DEFAULT '[]',
                source_titles_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_writeback_reviews (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                context_request_id TEXT,
                quality_state TEXT NOT NULL,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS query_evidence_cache (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                query_fingerprint TEXT NOT NULL,
                artifact_type TEXT NOT NULL DEFAULT 'query_result',
                contributing_source_ids TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                invalidated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS cluster_merge_artifacts (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                source_cluster_id TEXT NOT NULL,
                target_cluster_id TEXT NOT NULL,
                source_cluster_snapshot TEXT NOT NULL DEFAULT '{}',
                target_cluster_snapshot TEXT NOT NULL DEFAULT '{}',
                moved_source_ids TEXT NOT NULL DEFAULT '[]',
                moved_chat_session_ids TEXT NOT NULL DEFAULT '[]',
                reversible INTEGER NOT NULL DEFAULT 1,
                rolled_back_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS extension_pairing_sessions (
                id TEXT PRIMARY KEY,
                pairing_code TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_name TEXT NOT NULL,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS extension_permission_audit (
                id TEXT PRIMARY KEY,
                client_id TEXT,
                event_type TEXT NOT NULL,
                vault_id TEXT,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES extension_clients(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_source_chunks_vault_id ON source_chunks(vault_id);
            CREATE INDEX IF NOT EXISTS idx_sources_trust ON sources(vault_id, trust_tier, provenance);
            CREATE INDEX IF NOT EXISTS idx_source_quarantine_vault
                ON source_quarantine_records(vault_id, validation_status, parser_status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_cluster_id ON source_chunks(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id ON source_chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_tuple
                ON source_chunks(vault_id, embedding_model_id, index_version, normalization_version, extraction_version, derived_state_epoch);
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
            CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_import ON reconciliation_runs(import_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_vault ON reconciliation_runs(vault_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_reconciliation_items_run ON reconciliation_items(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_reconciliation_items_import ON reconciliation_items(import_id, result, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_extension_captures_vault ON extension_captures(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_expert_artifacts_cluster ON expert_artifacts(cluster_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_evidence_packets_job ON analysis_evidence_packets(job_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_evidence_packets_vault ON analysis_evidence_packets(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items(vault_id, cluster_id, status, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_origin_active ON memory_items(origin_fingerprint) WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_working_memory_scope ON working_memory_snapshots(vault_id, cluster_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_bridge_context_packets_scope ON bridge_context_packets(vault_id, cluster_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bridge_writeback_reviews_source ON bridge_writeback_reviews(source_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_query_evidence_cache_vault ON query_evidence_cache(vault_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_cluster_merge_artifacts_vault ON cluster_merge_artifacts(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_extension_pairing_status ON extension_pairing_sessions(status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_extension_permission_audit_client ON extension_permission_audit(client_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_vault_security_unlock_mode ON vault_security_metadata(unlock_mode);
            CREATE INDEX IF NOT EXISTS idx_encrypted_content_vault ON encrypted_content(vault_id, entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_derived_state_publications_vault
                ON derived_state_publications(vault_id, status, epoch);
            CREATE INDEX IF NOT EXISTS idx_derived_state_staged_vault
                ON derived_state_staged_artifacts(vault_id, status, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_app_jobs_dedupe_active
                ON app_jobs(dedupe_key)
                WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running');
            """
        )
        _add_column_if_missing(conn, "sources", "tags", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "sources", "provenance", "TEXT NOT NULL DEFAULT 'local_import'")
        _add_column_if_missing(conn, "sources", "trust_tier", "TEXT NOT NULL DEFAULT 'trusted_local'")
        _add_column_if_missing(conn, "sources", "security_labels", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "sources", "parser_security_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column_if_missing(conn, "sources", "cover_image_url", "TEXT")
        _add_column_if_missing(conn, "sources", "deleted_at", "TEXT")
        _add_column_if_missing(conn, "sources", "checksum", "TEXT")
        _add_column_if_missing(conn, "source_chunks", "content_profile", "TEXT NOT NULL DEFAULT 'prose'")
        _add_column_if_missing(conn, "source_chunks", "chunk_strategy", "TEXT NOT NULL DEFAULT 'word_window'")
        _add_column_if_missing(conn, "source_chunks", "chunk_meta_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column_if_missing(conn, "integration_imports", "imported_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "updated_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "moved_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "unchanged_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "tombstoned_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "failed_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "last_failures", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "integration_imports", "last_import_at", "TEXT")
        _add_column_if_missing(conn, "integration_imports", "watch_enabled", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "watch_interval_seconds", "INTEGER NOT NULL DEFAULT 900")
        _add_column_if_missing(conn, "integration_imports", "next_watch_at", "TEXT")
        _add_column_if_missing(conn, "chat_messages", "useful", "INTEGER")
        _add_column_if_missing(conn, "chat_messages", "saved", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "chat_sessions", "memory_status", "TEXT NOT NULL DEFAULT 'idle'")
        _add_column_if_missing(conn, "chat_sessions", "memory_updated_at", "TEXT")
        _add_column_if_missing(conn, "bridge_settings", "bridge_token", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "bridge_requests", "client_id", "TEXT")
        _add_column_if_missing(conn, "bridge_requests", "decision", "TEXT NOT NULL DEFAULT 'allowed'")
        _add_column_if_missing(conn, "bridge_requests", "source_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "bridge_requests", "response_bytes", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "bridge_clients", "approval_vault_id", "TEXT")
        _add_column_if_missing(conn, "bridge_clients", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column_if_missing(conn, "bridge_clients", "approval_request_id", "TEXT")
        _add_column_if_missing(conn, "bridge_clients", "approved_at", "TEXT")
        _add_column_if_missing(conn, "bridge_clients", "revoked_at", "TEXT")
        _add_column_if_missing(conn, "bridge_clients", "last_request_at", "TEXT")
        _add_column_if_missing(conn, "bridge_clients", "request_count_total", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "bridge_clients", "response_bytes_total", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "source_chunks", "page_id", "TEXT")
        _add_column_if_missing(conn, "source_chunks", "embedding_model_id", "TEXT NOT NULL DEFAULT 'hash'")
        _add_column_if_missing(conn, "source_chunks", "content_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "source_chunks", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing(conn, "source_chunks", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
        _add_column_if_missing(conn, "source_chunks", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
        _add_column_if_missing(conn, "source_chunks", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
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
        _add_column_if_missing(conn, "expert_artifacts", "dataset_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "expert_artifacts", "training_config_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "expert_artifacts", "metrics_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column_if_missing(conn, "expert_artifacts", "active", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "expert_artifacts", "rolled_back_at", "TEXT")
        _add_column_if_missing(conn, "expert_artifacts", "deleted_at", "TEXT")
        _ensure_vault_security_metadata_schema(conn)
        _ensure_encrypted_content_schema(conn)
        _ensure_derived_state_schema(conn)
        _ensure_quarantine_schema(conn)
        conn.executescript(
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
            );
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
            );
            CREATE TABLE IF NOT EXISTS bridge_rate_limits (
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                bucket TEXT NOT NULL,
                window_started_at TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope_type, scope_id, bucket)
            );
            """
        )
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_app_jobs_runnable
                ON app_jobs(status, priority, created_at);
            CREATE INDEX IF NOT EXISTS idx_app_jobs_dependency
                ON app_jobs(depends_on_job_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_page_id
                ON source_chunks(page_id);
            CREATE INDEX IF NOT EXISTS idx_source_chunks_tuple
                ON source_chunks(vault_id, embedding_model_id, index_version, normalization_version, extraction_version, derived_state_epoch);
            CREATE INDEX IF NOT EXISTS idx_sources_trust
                ON sources(vault_id, trust_tier, provenance);
            CREATE INDEX IF NOT EXISTS idx_bridge_requests_created
                ON bridge_requests(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bridge_approval_requests_status
                ON bridge_approval_requests(vault_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bridge_audit_events_created
                ON bridge_audit_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_source_quarantine_vault
                ON source_quarantine_records(vault_id, validation_status, parser_status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_sources_checksum
                ON sources(vault_id, checksum);
            CREATE INDEX IF NOT EXISTS idx_expert_artifacts_active
                ON expert_artifacts(cluster_id, active, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_query_evidence_cache_fingerprint
                ON query_evidence_cache(vault_id, query_fingerprint, invalidated_at);
            CREATE INDEX IF NOT EXISTS idx_cluster_merge_artifacts_target
                ON cluster_merge_artifacts(target_cluster_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_vault_security_unlock_mode
                ON vault_security_metadata(unlock_mode);
            CREATE INDEX IF NOT EXISTS idx_encrypted_content_vault
                ON encrypted_content(vault_id, entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_derived_state_publications_vault
                ON derived_state_publications(vault_id, status, epoch);
            CREATE INDEX IF NOT EXISTS idx_derived_state_staged_vault
                ON derived_state_staged_artifacts(vault_id, status, updated_at);
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


def _add_column_if_missing_if_table_exists(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not IDENTIFIER_RE.fullmatch(table):
        raise ValueError("Unsafe database identifier")
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if exists:
        _add_column_if_missing(conn, table, column, definition)


def _ensure_vault_security_metadata_schema(conn: sqlite3.Connection) -> None:
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
    for column, definition in {
        "security_version": "INTEGER NOT NULL DEFAULT 1",
        "kdf_algorithm": "TEXT NOT NULL DEFAULT 'argon2id'",
        "kdf_params_json": "TEXT NOT NULL DEFAULT '{}'",
        "passphrase_salt": "TEXT NOT NULL DEFAULT ''",
        "passphrase_wrapped_vmk": "TEXT NOT NULL DEFAULT ''",
        "recovery_salt": "TEXT NOT NULL DEFAULT ''",
        "recovery_wrapped_vmk": "TEXT NOT NULL DEFAULT ''",
        "unlock_mode": "TEXT NOT NULL DEFAULT 'convenience'",
        "pin_enabled": "INTEGER NOT NULL DEFAULT 0",
        "pin_salt": "TEXT NOT NULL DEFAULT ''",
        "pin_wrapped_unlock_secret": "TEXT NOT NULL DEFAULT ''",
        "active_derived_state_tuple": "TEXT NOT NULL DEFAULT '{}'",
        "previous_verified_tuple": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        _add_column_if_missing(conn, "vault_security_metadata", column, definition)


def _ensure_encrypted_content_schema(conn: sqlite3.Connection) -> None:
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
    for column, definition in {
        "vault_id": "TEXT NOT NULL DEFAULT ''",
        "entity_type": "TEXT NOT NULL DEFAULT ''",
        "entity_id": "TEXT NOT NULL DEFAULT ''",
        "field_name": "TEXT NOT NULL DEFAULT ''",
        "nonce": "TEXT NOT NULL DEFAULT ''",
        "ciphertext": "TEXT NOT NULL DEFAULT ''",
        "content_hash": "TEXT NOT NULL DEFAULT ''",
        "byte_length": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        _add_column_if_missing(conn, "encrypted_content", column, definition)


def _ensure_derived_state_schema(conn: sqlite3.Connection) -> None:
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
    for column, definition in {
        "vault_id": "TEXT NOT NULL DEFAULT ''",
        "epoch": "INTEGER NOT NULL DEFAULT 1",
        "normalization_version": "TEXT NOT NULL DEFAULT 'norm-v1'",
        "embedding_model_id": "TEXT NOT NULL DEFAULT 'hash'",
        "index_version": "TEXT NOT NULL DEFAULT 'v1'",
        "extraction_version": "TEXT NOT NULL DEFAULT 'extract-v1'",
        "status": "TEXT NOT NULL DEFAULT 'staging'",
        "artifact_manifest_json": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "verified_at": "TEXT",
        "published_at": "TEXT",
        "rolled_back_at": "TEXT",
    }.items():
        _add_column_if_missing(conn, "derived_state_publications", column, definition)
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
    for column, definition in {
        "vault_id": "TEXT NOT NULL DEFAULT ''",
        "publication_id": "TEXT NOT NULL DEFAULT ''",
        "artifact_type": "TEXT NOT NULL DEFAULT ''",
        "artifact_ref": "TEXT NOT NULL DEFAULT ''",
        "content_hash": "TEXT NOT NULL DEFAULT ''",
        "byte_length": "INTEGER NOT NULL DEFAULT 0",
        "status": "TEXT NOT NULL DEFAULT 'staging'",
        "owner_job_id": "TEXT",
        "heartbeat_at": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        _add_column_if_missing(conn, "derived_state_staged_artifacts", column, definition)


def _ensure_quarantine_schema(conn: sqlite3.Connection) -> None:
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
    for column, definition in {
        "vault_id": "TEXT NOT NULL DEFAULT ''",
        "source_id": "TEXT",
        "original_path": "TEXT NOT NULL DEFAULT ''",
        "canonical_path": "TEXT NOT NULL DEFAULT ''",
        "file_name": "TEXT NOT NULL DEFAULT ''",
        "suffix": "TEXT NOT NULL DEFAULT ''",
        "file_size": "INTEGER NOT NULL DEFAULT 0",
        "content_hash": "TEXT NOT NULL DEFAULT ''",
        "encrypted_blob_id": "TEXT NOT NULL DEFAULT ''",
        "encrypted_blob_path": "TEXT NOT NULL DEFAULT ''",
        "validation_status": "TEXT NOT NULL DEFAULT 'pending'",
        "validation_json": "TEXT NOT NULL DEFAULT '{}'",
        "defender_status": "TEXT NOT NULL DEFAULT 'not_run'",
        "defender_detail": "TEXT NOT NULL DEFAULT ''",
        "parser_status": "TEXT NOT NULL DEFAULT 'not_run'",
        "parser_detail": "TEXT NOT NULL DEFAULT ''",
        "trust_tier": "TEXT NOT NULL DEFAULT 'quarantined'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        _add_column_if_missing(conn, "source_quarantine_records", column, definition)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database_path = path or get_settings().database_path
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA secure_delete = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
