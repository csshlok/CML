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
        _add_column_if_missing_if_table_exists(conn, "sources", "metadata_version", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing_if_table_exists(conn, "sources", "metadata_quality", "TEXT NOT NULL DEFAULT 'fallback'")
        _add_column_if_missing_if_table_exists(conn, "sources", "semantic_metadata_version", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing_if_table_exists(conn, "sources", "semantic_metadata_updated_at", "TEXT")
        _add_column_if_missing_if_table_exists(conn, "sources", "ingestion_stage", "TEXT NOT NULL DEFAULT 'ready'")
        _add_column_if_missing_if_table_exists(conn, "sources", "ingestion_generation", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing_if_table_exists(conn, "sources", "ingestion_error_code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing_if_table_exists(conn, "sources", "ingestion_status_detail", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing_if_table_exists(conn, "sources", "ingestion_updated_at", "TEXT")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "embedding_model_id", "TEXT NOT NULL DEFAULT 'hash'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
        _add_column_if_missing_if_table_exists(conn, "source_chunks", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing_if_table_exists(conn, "temporal_facts", "cluster_id", "TEXT")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "planned_source_ids", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "planned_chat_session_ids", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "source_cursor", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "chat_cursor", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "status", "TEXT NOT NULL DEFAULT 'completed'")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "conflict_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing_if_table_exists(conn, "cluster_merge_artifacts", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing_if_table_exists(conn, "integration_imports", "scan_cursor", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing_if_table_exists(conn, "integration_imports", "scan_cycle_id", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing_if_table_exists(conn, "integration_imports", "scan_phase", "TEXT NOT NULL DEFAULT 'discovery'")
        _add_column_if_missing_if_table_exists(conn, "integration_imports", "scan_processed_count", "INTEGER NOT NULL DEFAULT 0")
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            PRAGMA journal_mode = WAL;

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
                content_migration_status TEXT NOT NULL DEFAULT 'complete',
                content_migration_updated_at TEXT NOT NULL DEFAULT '',
                content_migration_error TEXT NOT NULL DEFAULT '',
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
                name_origin TEXT NOT NULL DEFAULT 'user',
                description TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT 'sage',
                index_status TEXT NOT NULL DEFAULT 'empty',
                profile_status TEXT NOT NULL DEFAULT 'missing',
                cluster_summary TEXT NOT NULL DEFAULT '',
                cluster_glossary TEXT NOT NULL DEFAULT '[]',
                profile_updated_at TEXT,
                profile_source_hash TEXT NOT NULL DEFAULT '',
                indexed_source_count INTEGER NOT NULL DEFAULT 0,
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
                metadata_version INTEGER NOT NULL DEFAULT 1,
                metadata_quality TEXT NOT NULL DEFAULT 'fallback',
                semantic_metadata_version INTEGER NOT NULL DEFAULT 0,
                semantic_metadata_updated_at TEXT,
                ingestion_stage TEXT NOT NULL DEFAULT 'ready',
                ingestion_generation INTEGER NOT NULL DEFAULT 1,
                ingestion_error_code TEXT NOT NULL DEFAULT '',
                ingestion_status_detail TEXT NOT NULL DEFAULT '',
                ingestion_updated_at TEXT,
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
                vault_id TEXT,
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
                schema_version INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 0,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                allow_style_profile INTEGER NOT NULL DEFAULT 0,
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
                capability_profile TEXT NOT NULL DEFAULT 'read_write',
                approval_vault_id TEXT,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                allow_style_profile INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS bridge_idempotency (
                principal_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (principal_id, operation, idempotency_key)
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
                scan_cursor TEXT NOT NULL DEFAULT '',
                scan_cycle_id TEXT NOT NULL DEFAULT '',
                scan_phase TEXT NOT NULL DEFAULT 'discovery',
                scan_processed_count INTEGER NOT NULL DEFAULT 0,
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
                result_json TEXT NOT NULL DEFAULT '{}',
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
                error_code TEXT NOT NULL DEFAULT '',
                diagnostic_id TEXT NOT NULL DEFAULT '',
                status_detail TEXT NOT NULL DEFAULT '',
                cancellation_requested INTEGER NOT NULL DEFAULT 0,
                cancellation_requested_at TEXT,
                claim_token TEXT NOT NULL DEFAULT '',
                heartbeat_at TEXT,
                deadline_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS integration_scan_seen (
                import_id TEXT NOT NULL,
                cycle_id TEXT NOT NULL,
                normalized_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (import_id, cycle_id, normalized_path),
                FOREIGN KEY (import_id) REFERENCES integration_imports(id) ON DELETE CASCADE
            );

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
            );

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
                project_id TEXT,
                project_snapshot_id TEXT,
                activation_state TEXT NOT NULL DEFAULT 'active',
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
                scope_project_id TEXT,
                scope_unclustered INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS chat_transcript_memory_state (
                session_id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                last_message_rowid INTEGER NOT NULL DEFAULT 0,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                summary_version TEXT NOT NULL DEFAULT 'bounded-v1',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scheduler_prerequisites (
                name TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS temporal_facts (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                subject_key TEXT NOT NULL,
                predicate_key TEXT NOT NULL,
                object_text TEXT NOT NULL,
                object_type TEXT NOT NULL DEFAULT 'text',
                assertion_kind TEXT NOT NULL CHECK (
                    assertion_kind IN ('fact', 'preference', 'suggestion', 'action', 'plan', 'goal', 'state')
                ),
                modality TEXT NOT NULL DEFAULT 'asserted' CHECK (
                    modality IN ('asserted', 'negated', 'hypothetical')
                ),
                speaker_role TEXT NOT NULL CHECK (
                    speaker_role IN ('user', 'assistant', 'tool', 'system', 'external')
                ),
                source_type TEXT NOT NULL CHECK (
                    source_type IN ('chat_message', 'source', 'benchmark', 'manual')
                ),
                source_id TEXT NOT NULL,
                session_id TEXT,
                citation_excerpt TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                supersession_key TEXT NOT NULL DEFAULT '',
                supersedes_fact_id TEXT,
                superseded_by_fact_id TEXT,
                status TEXT NOT NULL DEFAULT 'current' CHECK (
                    status IN ('current', 'superseded', 'retracted')
                ),
                confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
                origin_fingerprint TEXT NOT NULL UNIQUE,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (supersedes_fact_id) REFERENCES temporal_facts(id) ON DELETE SET NULL,
                FOREIGN KEY (superseded_by_fact_id) REFERENCES temporal_facts(id) ON DELETE SET NULL,
                CHECK (valid_until IS NULL OR valid_until >= valid_from),
                CHECK (
                    NOT (
                        speaker_role = 'assistant'
                        AND subject_key = 'user'
                        AND assertion_kind = 'action'
                    )
                )
            );

            CREATE TRIGGER IF NOT EXISTS temporal_facts_immutable_provenance
            BEFORE UPDATE ON temporal_facts
            WHEN NEW.vault_id != OLD.vault_id
              OR COALESCE(NEW.cluster_id, '') != COALESCE(OLD.cluster_id, '')
              OR NEW.subject_key != OLD.subject_key
              OR NEW.predicate_key != OLD.predicate_key
              OR NEW.object_text != OLD.object_text
              OR NEW.object_type != OLD.object_type
              OR NEW.assertion_kind != OLD.assertion_kind
              OR NEW.modality != OLD.modality
              OR NEW.speaker_role != OLD.speaker_role
              OR NEW.source_type != OLD.source_type
              OR NEW.source_id != OLD.source_id
              OR COALESCE(NEW.session_id, '') != COALESCE(OLD.session_id, '')
              OR NEW.citation_excerpt != OLD.citation_excerpt
              OR NEW.observed_at != OLD.observed_at
              OR NEW.valid_from != OLD.valid_from
              OR NEW.supersession_key != OLD.supersession_key
              OR COALESCE(NEW.supersedes_fact_id, '') != COALESCE(OLD.supersedes_fact_id, '')
              OR NEW.confidence != OLD.confidence
              OR NEW.origin_fingerprint != OLD.origin_fingerprint
              OR NEW.metadata_json != OLD.metadata_json
            BEGIN
                SELECT RAISE(ABORT, 'temporal_fact_provenance_is_immutable');
            END;

            CREATE TABLE IF NOT EXISTS temporal_fact_session_state (
                session_id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                source_content_hash TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                fact_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS atomic_memory_facts (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                cluster_id TEXT,
                session_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                compiler_fact_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                speaker_role TEXT NOT NULL CHECK (speaker_role IN ('user', 'assistant', 'tool')),
                session_date TEXT NOT NULL,
                citation_excerpt TEXT NOT NULL,
                source_content_hash TEXT NOT NULL,
                subject_key TEXT NOT NULL,
                predicate_key TEXT NOT NULL,
                object_text TEXT NOT NULL,
                fact_kind TEXT NOT NULL,
                assertion_mode TEXT NOT NULL CHECK (assertion_mode IN ('asserted', 'negated', 'hypothetical')),
                event_date TEXT,
                observed_date TEXT NOT NULL,
                quantity_value REAL,
                quantity_unit TEXT,
                quantity_role TEXT,
                qualifiers_json TEXT NOT NULL DEFAULT '{}',
                supersession_key TEXT,
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                compiler_version TEXT NOT NULL,
                origin_fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'retracted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (source_message_id) REFERENCES chat_messages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS atomic_memory_source_units (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                compiler_unit_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                speaker_role TEXT NOT NULL CHECK (speaker_role IN ('user', 'assistant', 'tool')),
                excerpt_hash TEXT NOT NULL,
                coverage_status TEXT NOT NULL CHECK (
                    coverage_status IN ('facts_extracted', 'processed_no_fact')
                ),
                fact_ids_json TEXT NOT NULL DEFAULT '[]',
                compiler_version TEXT NOT NULL,
                source_content_hash TEXT NOT NULL,
                origin_fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'retracted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (source_message_id) REFERENCES chat_messages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS atomic_memory_session_state (
                session_id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                source_content_hash TEXT NOT NULL,
                compiler_version TEXT NOT NULL,
                fact_count INTEGER NOT NULL DEFAULT 0,
                source_unit_count INTEGER NOT NULL DEFAULT 0,
                covered_source_unit_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS atomic_memory_semantic_state (
                session_id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                source_content_hash TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                facts_json TEXT NOT NULL DEFAULT '[]',
                source_units_json TEXT NOT NULL DEFAULT '[]',
                fact_count INTEGER NOT NULL DEFAULT 0,
                invalid_fact_count INTEGER NOT NULL DEFAULT 0,
                invalid_reasons_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL CHECK (status IN ('current', 'failed', 'stale')),
                processed_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS temporal_fact_reviews (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                replacement_fact_id TEXT,
                action TEXT NOT NULL CHECK (action IN ('corrected', 'retracted')),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (fact_id) REFERENCES temporal_facts(id) ON DELETE CASCADE,
                FOREIGN KEY (replacement_fact_id) REFERENCES temporal_facts(id) ON DELETE SET NULL
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
                lease_owner TEXT NOT NULL DEFAULT '',
                cancellation_requested_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                request_id TEXT,
                parent_generation_id TEXT,
                attempt_number INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (user_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
                FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_generation_id) REFERENCES chat_generations(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS app_profile (
                id TEXT PRIMARY KEY CHECK (id = 'local'),
                display_name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
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
                context_strategy TEXT NOT NULL DEFAULT '',
                candidate_citation_count INTEGER NOT NULL DEFAULT 0,
                selected_citation_count INTEGER NOT NULL DEFAULT 0,
                prompt_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                evidence_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                history_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                memory_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                raw_candidate_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                raw_context_tokens_estimate INTEGER NOT NULL DEFAULT 0,
                final_context_tokens_estimate INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                root_fingerprint TEXT NOT NULL,
                discovery_scope TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code')),
                primary_cluster_id TEXT NOT NULL,
                repository_kind TEXT NOT NULL DEFAULT 'folder',
                git_remote_fingerprint TEXT,
                default_branch TEXT,
                indexed_commit TEXT,
                working_tree_dirty INTEGER NOT NULL DEFAULT 0,
                changed_file_count INTEGER NOT NULL DEFAULT 0,
                auto_sync_enabled INTEGER NOT NULL DEFAULT 1,
                sync_mode TEXT NOT NULL DEFAULT 'automatic',
                change_fingerprint TEXT NOT NULL DEFAULT '',
                last_change_checked_at TEXT,
                status TEXT NOT NULL DEFAULT 'registered',
                structure_status TEXT NOT NULL DEFAULT 'waiting',
                retrieval_status TEXT NOT NULL DEFAULT 'waiting',
                interpretation_status TEXT NOT NULL DEFAULT 'unavailable',
                active_snapshot_id TEXT,
                active_manifest_snapshot_id TEXT,
                active_structure_snapshot_id TEXT,
                active_retrieval_snapshot_id TEXT,
                candidate_snapshot_id TEXT,
                active_run_id TEXT,
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
                discovery_scope TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code')),
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
                manifest_activated_at TEXT,
                structure_activated_at TEXT,
                retrieval_activated_at TEXT,
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
                cancellation_requested_at TEXT,
                heartbeat_at TEXT,
                queued_at TEXT,
                job_id TEXT,
                phase_completed_count INTEGER NOT NULL DEFAULT 0,
                phase_total_count INTEGER NOT NULL DEFAULT 0,
                activation_outcome TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS project_cluster_links (
                project_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('primary', 'linked')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (project_id, cluster_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
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
                planned_source_ids TEXT NOT NULL DEFAULT '[]',
                planned_chat_session_ids TEXT NOT NULL DEFAULT '[]',
                source_cursor INTEGER NOT NULL DEFAULT 0,
                chat_cursor INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                conflict_count INTEGER NOT NULL DEFAULT 0,
                reversible INTEGER NOT NULL DEFAULT 1,
                rolled_back_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

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

            CREATE TABLE IF NOT EXISTS cluster_suggestion_decisions (
                source_id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                suggested_cluster_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('accepted', 'dismissed')),
                source_updated_at TEXT NOT NULL,
                source_content_hash TEXT NOT NULL DEFAULT '',
                candidate_profile_hash TEXT NOT NULL DEFAULT '',
                candidate_profile_version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            );

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
                source_content_hash TEXT NOT NULL DEFAULT '',
                candidate_profile_hash TEXT NOT NULL DEFAULT '',
                candidate_profile_version INTEGER NOT NULL DEFAULT 0,
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
            CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_decisions_vault
                ON cluster_suggestion_decisions(vault_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_batches_vault
                ON cluster_suggestion_batches(vault_id, status, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cluster_suggestion_one_active_batch
                ON cluster_suggestion_batches(vault_id) WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_cluster_suggestion_candidates_batch
                ON cluster_suggestion_candidates(batch_id, decision, confidence DESC);
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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_vault_name
                ON projects(vault_id, lower(name)) WHERE deleted_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_projects_primary_cluster
                ON projects(primary_cluster_id) WHERE deleted_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_project_sources_source ON project_sources(source_id);
            CREATE INDEX IF NOT EXISTS idx_project_snapshots_project
                ON project_snapshots(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_project_runs_project
                ON project_index_runs(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_project_snapshot_sources_project
                ON project_snapshot_sources(project_id, snapshot_id, relative_path);
            CREATE INDEX IF NOT EXISTS idx_project_snapshot_sources_source
                ON project_snapshot_sources(source_id);
            CREATE INDEX IF NOT EXISTS idx_cli_clients_active
                ON cli_clients(revoked_at, last_used_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cli_sessions_token_hash
                ON cli_sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_cli_sessions_client
                ON cli_sessions(client_id, expires_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cli_pairing_status
                ON cli_pairing_challenges(status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_cli_auth_audit_client
                ON cli_auth_audit(client_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_code_nodes_lookup
                ON code_nodes(project_id, snapshot_id, kind, qualified_id);
            CREATE INDEX IF NOT EXISTS idx_code_nodes_source_range
                ON code_nodes(project_id, snapshot_id, source_id, start_line, end_line);
            CREATE INDEX IF NOT EXISTS idx_code_nodes_label_search
                ON code_nodes(project_id, snapshot_id, display_label COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_code_nodes_path_search
                ON code_nodes(project_id, snapshot_id, relative_path COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_code_edges_source
                ON code_edges(project_id, snapshot_id, source_node_id, edge_type);
            CREATE INDEX IF NOT EXISTS idx_code_edges_target
                ON code_edges(project_id, snapshot_id, target_node_id, edge_type);
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
            CREATE INDEX IF NOT EXISTS idx_temporal_facts_current
                ON temporal_facts(vault_id, cluster_id, subject_key, predicate_key, status, valid_from DESC);
            CREATE INDEX IF NOT EXISTS idx_temporal_facts_history
                ON temporal_facts(vault_id, supersession_key, valid_from ASC);
            CREATE INDEX IF NOT EXISTS idx_temporal_facts_source
                ON temporal_facts(source_type, source_id, status);
            CREATE INDEX IF NOT EXISTS idx_temporal_fact_session_state_vault
                ON temporal_fact_session_state(vault_id, processed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_atomic_memory_facts_session
                ON atomic_memory_facts(vault_id, session_id, status, turn_index);
            CREATE INDEX IF NOT EXISTS idx_atomic_memory_facts_lookup
                ON atomic_memory_facts(vault_id, subject_key, predicate_key, status, observed_date DESC);
            CREATE INDEX IF NOT EXISTS idx_atomic_memory_source_units_session
                ON atomic_memory_source_units(vault_id, session_id, status, turn_index);
            CREATE INDEX IF NOT EXISTS idx_atomic_memory_session_state_vault
                ON atomic_memory_session_state(vault_id, processed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_atomic_memory_semantic_state_vault
                ON atomic_memory_semantic_state(vault_id, status, processed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_temporal_fact_reviews_vault
                ON temporal_fact_reviews(vault_id, created_at DESC);
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
            CREATE INDEX IF NOT EXISTS idx_analysis_evidence_packets_job ON analysis_evidence_packets(job_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_evidence_packets_vault ON analysis_evidence_packets(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items(vault_id, cluster_id, status, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_origin_active ON memory_items(origin_fingerprint) WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_working_memory_scope ON working_memory_snapshots(vault_id, cluster_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_bridge_context_packets_scope ON bridge_context_packets(vault_id, cluster_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bridge_writeback_reviews_source ON bridge_writeback_reviews(source_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_query_evidence_cache_vault ON query_evidence_cache(vault_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_cluster_merge_artifacts_vault ON cluster_merge_artifacts(vault_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_cluster_membership_events_source
                ON cluster_membership_events(source_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cluster_membership_events_vault
                ON cluster_membership_events(vault_id, created_at DESC);
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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_source_import_one_active
                ON app_jobs(scope_id)
                WHERE job_type = 'source_import_batch'
                  AND status IN ('queued', 'running', 'paused');
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
        _add_column_if_missing(conn, "sources", "project_id", "TEXT")
        _add_column_if_missing(conn, "sources", "project_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "sources", "activation_state", "TEXT NOT NULL DEFAULT 'active'")
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
        _add_column_if_missing(conn, "integration_imports", "watch_failure_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "integration_imports", "watch_last_error", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "chat_messages", "useful", "INTEGER")
        _add_column_if_missing(conn, "chat_messages", "saved", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "index_version", "TEXT NOT NULL DEFAULT 'v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "normalization_version", "TEXT NOT NULL DEFAULT 'norm-v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "extraction_version", "TEXT NOT NULL DEFAULT 'extract-v1'")
        _add_column_if_missing(conn, "retrieval_snapshots", "derived_state_epoch", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "retrieval_snapshots", "context_strategy", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "retrieval_snapshots", "candidate_citation_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "selected_citation_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "prompt_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "evidence_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "history_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "memory_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "raw_candidate_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "raw_context_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "retrieval_snapshots", "final_context_tokens_estimate", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "chat_sessions", "memory_status", "TEXT NOT NULL DEFAULT 'idle'")
        _add_column_if_missing(conn, "chat_sessions", "memory_updated_at", "TEXT")
        _add_column_if_missing(conn, "chat_sessions", "scope_project_id", "TEXT")
        _add_column_if_missing(conn, "chat_sessions", "scope_unclustered", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_project ON chat_sessions(scope_project_id, updated_at DESC)"
        )
        _add_column_if_missing(conn, "projects", "active_manifest_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "projects", "active_structure_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "projects", "active_retrieval_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "projects", "candidate_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "projects", "active_run_id", "TEXT")
        _add_column_if_missing(
            conn,
            "projects",
            "discovery_scope",
            "TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code'))",
        )
        _add_column_if_missing(conn, "project_snapshots", "manifest_activated_at", "TEXT")
        _add_column_if_missing(conn, "project_snapshots", "structure_activated_at", "TEXT")
        _add_column_if_missing(conn, "project_snapshots", "retrieval_activated_at", "TEXT")
        _add_column_if_missing(
            conn,
            "project_snapshots",
            "discovery_scope",
            "TEXT NOT NULL DEFAULT 'context' CHECK (discovery_scope IN ('context', 'code'))",
        )
        _add_column_if_missing(conn, "project_index_runs", "cancellation_requested_at", "TEXT")
        _add_column_if_missing(conn, "project_index_runs", "heartbeat_at", "TEXT")
        _add_column_if_missing(conn, "project_index_runs", "queued_at", "TEXT")
        _add_column_if_missing(conn, "project_index_runs", "job_id", "TEXT")
        _add_column_if_missing(conn, "project_index_runs", "phase_completed_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "project_index_runs", "phase_total_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "project_index_runs", "activation_outcome", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "project_snapshot_sources", "resolved_path_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "project_snapshot_sources", "exclusion_decision", "TEXT NOT NULL DEFAULT 'included'")
        _add_column_if_missing(conn, "project_snapshot_sources", "parser_status", "TEXT NOT NULL DEFAULT 'waiting'")
        _add_column_if_missing(conn, "project_snapshot_sources", "retrieval_status", "TEXT NOT NULL DEFAULT 'waiting'")
        _add_column_if_missing(conn, "clusters", "index_status", "TEXT NOT NULL DEFAULT 'empty'")
        _add_column_if_missing(conn, "clusters", "profile_status", "TEXT NOT NULL DEFAULT 'missing'")
        _add_column_if_missing(conn, "clusters", "cluster_summary", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "clusters", "cluster_glossary", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "clusters", "profile_updated_at", "TEXT")
        _add_column_if_missing(conn, "clusters", "profile_source_hash", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "clusters", "indexed_source_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "bridge_settings", "bridge_token", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "bridge_settings", "schema_version", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "bridge_requests", "client_id", "TEXT")
        _add_column_if_missing(conn, "bridge_requests", "vault_id", "TEXT")
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
        _add_column_if_missing(conn, "source_chunks", "project_id", "TEXT")
        _add_column_if_missing(conn, "source_chunks", "project_snapshot_id", "TEXT")
        _add_column_if_missing(conn, "source_chunks", "activation_state", "TEXT NOT NULL DEFAULT 'active'")
        _add_column_if_missing(conn, "app_jobs", "error_code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "app_jobs", "diagnostic_id", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "chat_generations", "request_id", "TEXT")
        _add_column_if_missing(conn, "chat_generations", "parent_generation_id", "TEXT")
        _add_column_if_missing(conn, "chat_generations", "attempt_number", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "chat_generations", "lease_owner", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "chat_generations", "cancellation_requested_at", "TEXT")
        _add_column_if_missing(conn, "projects", "auto_sync_enabled", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "projects", "sync_mode", "TEXT NOT NULL DEFAULT 'automatic'")
        _add_column_if_missing(conn, "projects", "change_fingerprint", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "projects", "last_change_checked_at", "TEXT")
        _add_column_if_missing(conn, "sources", "metadata_quality", "TEXT NOT NULL DEFAULT 'fallback'")
        _add_column_if_missing(conn, "sources", "semantic_metadata_version", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "sources", "semantic_metadata_updated_at", "TEXT")
        _add_column_if_missing(conn, "sources", "import_root_path", "TEXT")
        _add_column_if_missing(conn, "sources", "ingestion_stage", "TEXT NOT NULL DEFAULT 'ready'")
        _add_column_if_missing(conn, "sources", "ingestion_generation", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "sources", "ingestion_error_code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "sources", "ingestion_status_detail", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "sources", "ingestion_updated_at", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_import_root_active "
            "ON sources(vault_id, import_root_path, deleted_at, original_path)"
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_generations_request_id
            ON chat_generations(vault_id, request_id)
            WHERE request_id IS NOT NULL AND request_id <> ''
            """
        )
        _ensure_single_active_chat_generation(conn)
        _add_column_if_missing(conn, "source_chunks", "indexed_at", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_project_snapshot "
            "ON sources(project_id, project_snapshot_id, activation_state)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_chunks_project_snapshot "
            "ON source_chunks(project_id, project_snapshot_id, activation_state)"
        )
        _add_column_if_missing(conn, "app_jobs", "priority", "TEXT NOT NULL DEFAULT 'normal'")
        _add_column_if_missing(conn, "app_jobs", "result_json", "TEXT NOT NULL DEFAULT '{}'")
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
        _add_column_if_missing(conn, "app_jobs", "cancellation_requested", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "app_jobs", "cancellation_requested_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "claim_token", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "app_jobs", "heartbeat_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "deadline_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "started_at", "TEXT")
        _add_column_if_missing(conn, "app_jobs", "completed_at", "TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sources_ingestion_progress
            ON sources(vault_id, ingestion_stage, ingestion_updated_at, id)
            """
        )
        _add_column_if_missing(conn, "extension_clients", "allowed_vault_ids", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_vault_security_metadata_schema(conn)
        _ensure_encrypted_content_schema(conn)
        _ensure_derived_state_schema(conn)
        _ensure_quarantine_schema(conn)
        _rebuild_clusters_table_without_expert_status(conn)
        _rebuild_bridge_settings_without_allow_expert_calls(conn)
        _rebuild_bridge_clients_without_allow_expert_calls(conn)
        _add_column_if_missing(conn, "bridge_clients", "capability_profile", "TEXT NOT NULL DEFAULT 'read_write'")
        _drop_legacy_expert_tables(conn)
        _backfill_cluster_rag_lifecycle(conn)
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
            CREATE TABLE IF NOT EXISTS bridge_idempotency (
                principal_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (principal_id, operation, idempotency_key)
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
            CREATE INDEX IF NOT EXISTS idx_bridge_idempotency_created
                ON bridge_idempotency(created_at);
            CREATE INDEX IF NOT EXISTS idx_source_quarantine_vault
                ON source_quarantine_records(vault_id, validation_status, parser_status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_sources_checksum
                ON sources(vault_id, checksum);
            CREATE INDEX IF NOT EXISTS idx_sources_cluster_state
                ON sources(cluster_id, state, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_sources_vault_state
                ON sources(vault_id, state, deleted_at);
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


def _ensure_single_active_chat_generation(conn: sqlite3.Connection) -> None:
    """Repair legacy duplicates before enforcing one active answer per chat."""
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
            SELECT id
            FROM chat_generations
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


def _backfill_cluster_rag_lifecycle(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE clusters
        SET index_status = CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                ) THEN 'empty'
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state = 'failed'
                ) THEN 'error'
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state IN ('waiting', 'processing')
                ) THEN 'indexing'
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state = 'indexed'
                ) THEN 'ready'
                ELSE index_status
            END,
            profile_status = CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                ) THEN 'missing'
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state = 'failed'
                ) THEN 'error'
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state IN ('waiting', 'processing')
                ) THEN CASE
                    WHEN EXISTS (
                        SELECT 1 FROM sources
                        WHERE sources.cluster_id = clusters.id
                          AND sources.deleted_at IS NULL
                          AND sources.state = 'indexed'
                    ) THEN 'stale'
                    ELSE 'refreshing'
                END
                WHEN EXISTS (
                    SELECT 1 FROM sources
                    WHERE sources.cluster_id = clusters.id
                      AND sources.deleted_at IS NULL
                      AND sources.state = 'indexed'
                ) THEN CASE
                    WHEN COALESCE(cluster_summary, '') = '' AND COALESCE(cluster_glossary, '[]') = '[]' THEN 'missing'
                    ELSE 'ready'
                END
                ELSE profile_status
            END,
            indexed_source_count = COALESCE((
                SELECT COUNT(*) FROM sources
                WHERE sources.cluster_id = clusters.id
                  AND sources.deleted_at IS NULL
                  AND sources.state = 'indexed'
            ), 0)
        """
    )


def _rebuild_clusters_table_without_expert_status(conn: sqlite3.Connection) -> None:
    if not _table_has_column(conn, "clusters", "expert_status"):
        return
    name_origin_select = (
        "COALESCE(name_origin, 'user')"
        if _table_has_column(conn, "clusters", "name_origin")
        else "'user'"
    )
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS clusters_new")
        conn.execute(
            """
            CREATE TABLE clusters_new (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                name TEXT NOT NULL,
                name_origin TEXT NOT NULL DEFAULT 'user',
                description TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT 'sage',
                index_status TEXT NOT NULL DEFAULT 'empty',
                profile_status TEXT NOT NULL DEFAULT 'missing',
                cluster_summary TEXT NOT NULL DEFAULT '',
                cluster_glossary TEXT NOT NULL DEFAULT '[]',
                profile_updated_at TEXT,
                profile_source_hash TEXT NOT NULL DEFAULT '',
                indexed_source_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            f"""
            INSERT INTO clusters_new (
                id, vault_id, name, name_origin, description, color, index_status, profile_status,
                cluster_summary, cluster_glossary, profile_updated_at, profile_source_hash,
                indexed_source_count, created_at, updated_at
            )
            SELECT
                id,
                vault_id,
                name,
                {name_origin_select},
                description,
                color,
                COALESCE(index_status, 'empty'),
                COALESCE(profile_status, 'missing'),
                COALESCE(cluster_summary, ''),
                COALESCE(cluster_glossary, '[]'),
                profile_updated_at,
                COALESCE(profile_source_hash, ''),
                COALESCE(indexed_source_count, 0),
                created_at,
                updated_at
            FROM clusters
            """
        )
        conn.execute("DROP TABLE clusters")
        conn.execute("ALTER TABLE clusters_new RENAME TO clusters")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _rebuild_bridge_settings_without_allow_expert_calls(conn: sqlite3.Connection) -> None:
    if not _table_has_column(conn, "bridge_settings", "allow_expert_calls"):
        return
    conn.execute("ALTER TABLE bridge_settings RENAME TO bridge_settings_legacy_expert_calls")
    conn.execute(
        """
        CREATE TABLE bridge_settings (
            id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 0,
            allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
            allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
            allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
            allow_style_profile INTEGER NOT NULL DEFAULT 0,
            bridge_token TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_settings (
            id, schema_version, enabled, allowed_vault_ids, allowed_cluster_ids, allow_raw_snippets,
            allow_style_profile, bridge_token, created_at, updated_at
        )
        SELECT
            id,
            1,
            enabled,
            allowed_vault_ids,
            allowed_cluster_ids,
            allow_raw_snippets,
            allow_style_profile,
            bridge_token,
            created_at,
            updated_at
        FROM bridge_settings_legacy_expert_calls
        """
    )
    conn.execute("DROP TABLE bridge_settings_legacy_expert_calls")


def _rebuild_bridge_clients_without_allow_expert_calls(conn: sqlite3.Connection) -> None:
    if not _table_has_column(conn, "bridge_clients", "allow_expert_calls"):
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS bridge_clients_new")
        conn.execute(
            """
            CREATE TABLE bridge_clients_new (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                capability_profile TEXT NOT NULL DEFAULT 'read_write',
                approval_vault_id TEXT,
                allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                allow_style_profile INTEGER NOT NULL DEFAULT 0,
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
            )
            """
        )
        conn.execute(
            """
            INSERT INTO bridge_clients_new (
                id, name, token_hash, enabled, capability_profile, approval_vault_id, allowed_vault_ids,
                allowed_cluster_ids, allow_raw_snippets, allow_style_profile, metadata_json,
                approval_request_id, approved_at, revoked_at, last_request_at,
                request_count_total, response_bytes_total, created_at, updated_at
            )
            SELECT
                id,
                name,
                token_hash,
                enabled,
                'read_write',
                approval_vault_id,
                allowed_vault_ids,
                allowed_cluster_ids,
                allow_raw_snippets,
                allow_style_profile,
                metadata_json,
                approval_request_id,
                approved_at,
                revoked_at,
                last_request_at,
                request_count_total,
                response_bytes_total,
                created_at,
                updated_at
            FROM bridge_clients
            """
        )
        conn.execute("DROP TABLE bridge_clients")
        conn.execute("ALTER TABLE bridge_clients_new RENAME TO bridge_clients")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _drop_legacy_expert_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS cluster_expert_jobs")
    conn.execute("DROP TABLE IF EXISTS expert_artifacts")
    conn.execute("DROP INDEX IF EXISTS idx_expert_artifacts_cluster")
    conn.execute("DROP INDEX IF EXISTS idx_expert_artifacts_active")


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not IDENTIFIER_RE.fullmatch(table) or not IDENTIFIER_RE.fullmatch(column):
        raise ValueError("Unsafe database identifier")
    columns = _table_columns(conn, table)
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _add_column_if_missing_if_table_exists(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not IDENTIFIER_RE.fullmatch(table):
        raise ValueError("Unsafe database identifier")
    if _table_exists(conn, table):
        _add_column_if_missing(conn, table, column, definition)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    if not IDENTIFIER_RE.fullmatch(table):
        raise ValueError("Unsafe database identifier")
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not IDENTIFIER_RE.fullmatch(table):
        raise ValueError("Unsafe database identifier")
    if not _table_exists(conn, table):
        return set()
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not IDENTIFIER_RE.fullmatch(column):
        raise ValueError("Unsafe database identifier")
    return column in _table_columns(conn, table)


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
            content_migration_status TEXT NOT NULL DEFAULT 'complete',
            content_migration_updated_at TEXT NOT NULL DEFAULT '',
            content_migration_error TEXT NOT NULL DEFAULT '',
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
        "content_migration_status": "TEXT NOT NULL DEFAULT 'complete'",
        "content_migration_updated_at": "TEXT NOT NULL DEFAULT ''",
        "content_migration_error": "TEXT NOT NULL DEFAULT ''",
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
    conn = sqlite3.connect(database_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA secure_delete = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
