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

    def test_complete_analysis_field_is_rejected_without_masking_parse_errors(self) -> None:
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

        self.assertEqual(reserved.status_code, 501)
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
