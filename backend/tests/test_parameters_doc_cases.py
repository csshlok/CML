import importlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class TestingParametersDocCases(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_BACKEND_MODE", None)
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        os.environ.pop("CML_ALLOW_UNAUTHENTICATED_API", None)
        os.environ.pop("CML_API_PREFIX", None)
        self.tmp.cleanup()

    def test_pre_vault_mode_blocks_private_routes_and_keeps_preflight_alive(self) -> None:
        os.environ["CML_BACKEND_MODE"] = "pre_vault"
        client = self._client()

        try:
            self.assertEqual(
                client.post(
                    "/api/v1/sources",
                    json={"vault_id": "vault-1", "title": "Test", "source_type": "note", "raw_text": "hi"},
                ).status_code,
                409,
            )
            self.assertEqual(
                client.post("/api/v1/chat/sessions", json={"vault_id": "vault-1"}).status_code,
                409,
            )
            self.assertEqual(client.get("/api/v1/clusters").status_code, 409)
            self.assertEqual(
                client.post("/api/v1/bridge/context", json={"client_name": "test", "query": "hello"}).status_code,
                409,
            )
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/v1/system/preflight/disk",
                    json={"path": self.tmp.name},
                ).status_code,
                200,
            )
        finally:
            client.close()

    def test_pre_vault_allowed_routes_follow_custom_api_prefix(self) -> None:
        from backend.app.core.pre_vault import allowed_pre_vault_paths

        allowed = allowed_pre_vault_paths("/custom/v2")

        self.assertIn("/custom/v2/system/startup-status", allowed)
        self.assertIn("/custom/v2/models", allowed)
        self.assertNotIn("/api/v1/system/startup-status", allowed)

    def test_bridge_public_auth_routes_follow_custom_api_prefix(self) -> None:
        from backend.app.core.auth import _is_public_path

        self.assertTrue(_is_public_path("/custom/v2/bridge/context", "POST", "/custom/v2"))
        self.assertTrue(
            _is_public_path("/custom/v2/bridge/approval-requests/request-1/status", "GET", "/custom/v2")
        )
        self.assertFalse(_is_public_path("/api/v1/bridge/context", "POST", "/custom/v2"))

    def test_reserved_chat_field_paths_follow_custom_api_prefix(self) -> None:
        from backend.app.core.reserved_fields import chat_context_paths

        paths = chat_context_paths("/custom/v2")

        self.assertIn("/custom/v2/chat/context", paths)
        self.assertIn("/custom/v2/chat/context/stream", paths)
        self.assertNotIn("/api/v1/chat/context", paths)

    def test_chat_evidence_policy_prune_endpoint_follows_custom_api_prefix(self) -> None:
        os.environ["CML_API_PREFIX"] = "custom/v2/"
        from backend.app.core.config import get_settings
        from backend.app.core.chat_retention import chat_evidence_retention_policy

        get_settings.cache_clear()

        policy = chat_evidence_retention_policy()

        self.assertEqual(policy["query_cache_prune_endpoint"], "/custom/v2/search/query-cache/prune")

    def test_settings_normalizes_api_prefix_for_mounted_routes(self) -> None:
        os.environ["CML_API_PREFIX"] = "custom/v2/"
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        self.assertEqual(get_settings().api_prefix, "/custom/v2")

    def test_blank_optional_cluster_ids_are_normalized_before_storage(self) -> None:
        from backend.app.api.routes.chat import create_chat_session, update_chat_session
        from backend.app.api.routes.sources import create_source, update_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, ChatSessionCreate, ChatSessionUpdate, SourceCreate, SourceUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
            conn.execute(
                "INSERT INTO clusters (id, vault_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("cluster-1", "vault-1", "Cluster", now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                title="Blank cluster",
                source_type="note",
                raw_text="blank optional cluster id source text",
            )
        )
        session = create_chat_session(ChatSessionCreate(vault_id="vault-1", scope_cluster_id="cluster-1"))

        updated_source = update_source(source["id"], SourceUpdate(cluster_id=""))
        updated_session = update_chat_session(session["id"], ChatSessionUpdate(scope_cluster_id=""))
        context_payload = ChatContextRequest(vault_id="vault-1", prompt="status", cluster_id="", session_id="")

        with connect() as conn:
            source_row = conn.execute("SELECT cluster_id FROM sources WHERE id = ?", (source["id"],)).fetchone()
            session_row = conn.execute("SELECT scope_cluster_id FROM chat_sessions WHERE id = ?", (session["id"],)).fetchone()

        self.assertIsNone(updated_source["cluster_id"])
        self.assertIsNone(updated_session["scope_cluster_id"])
        self.assertIsNone(source_row["cluster_id"])
        self.assertIsNone(session_row["scope_cluster_id"])
        self.assertIsNone(context_payload.cluster_id)
        self.assertIsNone(context_payload.session_id)

    def test_complete_analysis_field_routes_normally_without_masking_parse_errors(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        client = self._client()

        try:
            reserved = client.post(
                "/api/v1/chat/context",
                json={"vault_id": "vault-1", "prompt": "hello", "complete_analysis": True},
            )
            malformed = client.post(
                "/api/v1/chat/context",
                data='{"complete_analysis":',
                headers={"Content-Type": "application/json"},
            )
        finally:
            client.close()

        self.assertEqual(reserved.status_code, 200)
        self.assertEqual(reserved.json()["intent"], "complete_analysis")
        self.assertNotEqual(malformed.status_code, 501)

    def test_synthesis_gate_blocks_recent_retriable_generations_but_not_old_ones(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, 0, 'idle', NULL, ?, ?)
                """,
                ("session-1", "vault-1", "Scheduler test", now, now),
            )
            self._insert_job(conn, "job-blocked", can_run_during_synthesis=0)
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                    runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES (?, ?, NULL, NULL, ?, ?, 'retriable', '', '', '', NULL, ?, ?, NULL)
                """,
                ("gen-recent", "session-1", "vault-1", "prompt", now, now),
            )

        self.assertIsNone(_claim_next_job())

        with connect() as conn:
            conn.execute("DELETE FROM chat_generations")
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                    runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES (?, ?, NULL, NULL, ?, ?, 'retriable', '', '', '', NULL, ?, ?, NULL)
                """,
                ("gen-old", "session-1", "vault-1", "prompt", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00"),
            )

        claimed = _claim_next_job()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], "job-blocked")

    def test_bridge_context_redacts_raw_text_when_permission_is_disabled(self) -> None:
        from backend.app.api.routes.bridge import build_context, expand_context_item, update_bridge_settings
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import (
            BridgeContextExpandRequest,
            BridgeContextRequest,
            BridgeSettingsUpdate,
            SourceCreate,
        )

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        update_bridge_settings(
            BridgeSettingsUpdate(
                enabled=True,
                allow_raw_snippets=False,
                allowed_vault_ids=["vault-1"],
                rotate_token=True,
            )
        )
        settings = update_bridge_settings(BridgeSettingsUpdate())
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Bridge note",
                source_type="note",
                raw_text="bridge redaction source text " * 80,
            )
        )
        run_due_jobs_once(limit=1)

        response = build_context(
            BridgeContextRequest(vault_id="vault-1", client_name="test-client", query="bridge redaction"),
            x_cml_bridge_token=settings["bridge_token"],
        )

        self.assertGreaterEqual(len(response["source_snippets"]), 1)
        self.assertTrue(all(item["raw_text"] == "" for item in response["source_snippets"]))
        self.assertTrue(all(item["extracted_text"] == "" for item in response["source_snippets"]))
        self.assertTrue(any("redacted" in warning.lower() for warning in response["warnings"]))
        self.assertTrue(response["expansion_handles"])

        expanded = expand_context_item(
            BridgeContextExpandRequest(vault_id="vault-1", handle=response["expansion_handles"][0]),
            x_cml_bridge_token=settings["bridge_token"],
        )

        self.assertEqual(expanded["handle"], response["expansion_handles"][0])
        self.assertIn("redacted", " ".join(expanded["warnings"]).lower())
        self.assertEqual(expanded["text"], response["source_snippets"][0]["summary"])

    def test_bridge_context_does_not_decrypt_raw_source_fields_when_permission_is_disabled(self) -> None:
        from unittest.mock import patch

        from backend.app.api.routes.bridge import build_context, update_bridge_settings
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeContextRequest, BridgeSettingsUpdate, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Bridge encrypted note",
                source_type="note",
                raw_text="bridge encrypted source text " * 80,
            )
        )
        run_due_jobs_once(limit=1)
        update_bridge_settings(
            BridgeSettingsUpdate(
                enabled=True,
                allow_raw_snippets=False,
                allowed_vault_ids=["vault-1"],
                rotate_token=True,
            )
        )
        settings = update_bridge_settings(BridgeSettingsUpdate())
        requested_fields: list[str] = []

        def tracking_get_encrypted_text(conn, *, vault_id, entity_type, entity_id, field_name):
            requested_fields.append(field_name)
            from backend.app.core.encrypted_storage import get_encrypted_text as real_get_encrypted_text

            return real_get_encrypted_text(
                conn,
                vault_id=vault_id,
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=field_name,
            )

        with patch("backend.app.api.routes.bridge.get_encrypted_text", side_effect=tracking_get_encrypted_text):
            response = build_context(
                BridgeContextRequest(vault_id="vault-1", client_name="test-client", query="bridge encrypted"),
                x_cml_bridge_token=settings["bridge_token"],
            )

        self.assertGreaterEqual(len(response["source_snippets"]), 1)
        self.assertNotIn("raw_text", requested_fields)
        self.assertNotIn("extracted_text", requested_fields)
        self.assertTrue(set(requested_fields).issubset({"summary", "tags"}))

    def test_bridge_context_reuses_active_connection_when_redacting_sources(self) -> None:
        from unittest.mock import patch

        from backend.app.api.routes.bridge import build_context, update_bridge_settings
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeContextRequest, BridgeSettingsUpdate, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        for index in range(3):
            create_source(
                SourceCreate(
                    vault_id="vault-1",
                    title=f"Bridge note {index}",
                    source_type="note",
                    raw_text=(f"bridge connection reuse note {index} " * 80).strip(),
                )
            )
        run_due_jobs_once(limit=3)
        update_bridge_settings(
            BridgeSettingsUpdate(
                enabled=True,
                allow_raw_snippets=False,
                allowed_vault_ids=["vault-1"],
                rotate_token=True,
            )
        )
        settings = update_bridge_settings(BridgeSettingsUpdate())
        received_conn_flags: list[bool] = []
        from backend.app.api.routes import bridge as bridge_module

        real_bridge_source_from_row = bridge_module._bridge_source_from_row

        def tracking_bridge_source(row, *, conn=None, allow_raw_snippets):
            received_conn_flags.append(conn is not None)
            return real_bridge_source_from_row(row, conn=conn, allow_raw_snippets=allow_raw_snippets)

        with patch("backend.app.api.routes.bridge._bridge_source_from_row", side_effect=tracking_bridge_source):
            response = build_context(
                BridgeContextRequest(vault_id="vault-1", client_name="test-client", query="bridge connection reuse"),
                x_cml_bridge_token=settings["bridge_token"],
            )

        self.assertGreaterEqual(len(response["source_snippets"]), 1)
        self.assertTrue(received_conn_flags)
        self.assertTrue(all(received_conn_flags))

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)

    def _insert_job(self, conn, job_id: str, **overrides) -> None:
        from backend.app.core.database import utc_now

        now = utc_now()
        job = {
            "id": job_id,
            "job_type": "reindex_source",
            "status": "queued",
            "payload": "{}",
            "dedupe_key": None,
            "priority": "normal",
            "idempotency_class": "idempotent",
            "restart_policy": "requeue",
            "dependency_failure_policy": "cancel",
            "write_scope": "none",
            "scope_id": None,
            "concurrency_group": None,
            "resource_cost": "light",
            "can_run_during_synthesis": 1,
            "user_visible": 0,
            "user_initiated": 0,
            "cancellable": 0,
            "preemptable": 0,
            "timeout_seconds": None,
            "soft_timeout_seconds": None,
            "timeout_action": "fail",
            "depends_on_job_id": None,
            "attempts": 0,
            "max_attempts": 3,
            "last_error": "",
            "status_detail": "",
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        job.update(overrides)
        conn.execute(
            """
            INSERT INTO app_jobs (
                id, job_type, status, payload, dedupe_key, priority, idempotency_class,
                restart_policy, dependency_failure_policy, write_scope, scope_id,
                concurrency_group, resource_cost, can_run_during_synthesis, user_visible,
                user_initiated, cancellable, preemptable, timeout_seconds,
                soft_timeout_seconds, timeout_action, depends_on_job_id, attempts,
                max_attempts, last_error, status_detail, started_at, completed_at,
                created_at, updated_at
            )
            VALUES (
                :id, :job_type, :status, :payload, :dedupe_key, :priority,
                :idempotency_class, :restart_policy, :dependency_failure_policy,
                :write_scope, :scope_id, :concurrency_group, :resource_cost,
                :can_run_during_synthesis, :user_visible, :user_initiated,
                :cancellable, :preemptable, :timeout_seconds, :soft_timeout_seconds,
                :timeout_action, :depends_on_job_id, :attempts, :max_attempts,
                :last_error, :status_detail, :started_at, :completed_at,
                :created_at, :updated_at
            )
            """,
            job,
        )


if __name__ == "__main__":
    unittest.main()
