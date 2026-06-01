import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from fastapi.testclient import TestClient


class AdditionalQACases(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        self.tmp.cleanup()

    def test_bridge_context_requires_token_when_enabled(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        settings = update_bridge_settings(
            BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True)
        )
        client = self._client()
        try:
            missing = client.post(
                "/api/v1/bridge/context",
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
            wrong = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": settings["bridge_token"] + "-wrong"},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)

    def test_bridge_disabled_rejects_even_with_valid_token(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.schemas import BridgeSettingsUpdate

        enabled = update_bridge_settings(BridgeSettingsUpdate(enabled=True, rotate_token=True))
        update_bridge_settings(BridgeSettingsUpdate(enabled=False))
        client = self._client()
        try:
            response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": enabled["bridge_token"]},
                json={"client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "bridge_disabled")

    def test_bridge_rotated_token_invalidates_previous_token(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        first = update_bridge_settings(
            BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True)
        )
        second = update_bridge_settings(BridgeSettingsUpdate(rotate_token=True))
        client = self._client()
        try:
            old_response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": first["bridge_token"]},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
            new_response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": second["bridge_token"]},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(old_response.status_code, 401)
        self.assertEqual(new_response.status_code, 200)

    def test_extension_status_reports_invalid_token_cleanly(self) -> None:
        client = self._client()
        try:
            response = client.get("/api/v1/extension/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])

    def test_options_cors_allows_vite_dev_origin(self) -> None:
        client = self._client()
        try:
            response = client.options(
                "/api/v1/system/hardware",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")

    def test_options_cors_rejects_unknown_origin(self) -> None:
        client = self._client()
        try:
            response = client.options(
                "/api/v1/system/hardware",
                headers={
                    "Origin": "http://127.0.0.1:5174",
                    "Access-Control-Request-Method": "GET",
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_unsupported_local_file_type_is_rejected(self) -> None:
        from backend.app.core.extraction import ExtractionError, extract_pages_from_path

        target = Path(self.tmp.name) / "malware.exe"
        target.write_bytes(b"MZ")
        with self.assertRaises(ExtractionError):
            extract_pages_from_path(str(target))

    def test_zero_byte_text_file_is_rejected(self) -> None:
        from backend.app.core.extraction import ExtractionError, extract_pages_from_path

        target = Path(self.tmp.name) / "empty.txt"
        target.write_text("", encoding="utf-8")
        with self.assertRaises(ExtractionError) as raised:
            extract_pages_from_path(str(target))
        self.assertIn("No readable text", str(raised.exception))

    def test_modified_file_after_first_ingest_is_not_deduplicated(self) -> None:
        from backend.app.api.routes.sources import create_source_from_path
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourcePathCreate

        target = Path(self.tmp.name) / "note.txt"
        target.write_text("alpha beta gamma", encoding="utf-8")
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        first = create_source_from_path(SourcePathCreate(vault_id="vault-1", path=str(target)))
        target.write_text("alpha beta gamma!", encoding="utf-8")
        second = create_source_from_path(SourcePathCreate(vault_id="vault-1", path=str(target)))

        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(count, 2)

    def test_job_cancel_route_rejects_non_cancellable_job(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO app_jobs (
                    id, job_type, status, payload, dedupe_key, priority, idempotency_class,
                    restart_policy, dependency_failure_policy, write_scope, scope_id,
                    concurrency_group, resource_cost, can_run_during_synthesis, user_visible,
                    user_initiated, cancellable, preemptable, timeout_seconds, soft_timeout_seconds,
                    timeout_action, depends_on_job_id, attempts, max_attempts, last_error,
                    status_detail, started_at, completed_at, created_at, updated_at
                )
                VALUES (
                    'job-1', 'reindex_source', 'queued', '{}', NULL, 'normal', 'idempotent',
                    'requeue', 'cancel', 'none', NULL, NULL, 'light', 1, 0, 0, 0, 0, NULL, NULL,
                    'fail', NULL, 0, 3, '', '', NULL, NULL, ?, ?
                )
                """,
                (now, now),
            )

        client = self._client()
        try:
            response = client.post("/api/v1/jobs/job-1/cancel")
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)
        self.assertIn("not cancellable", response.json()["detail"])

    @unittest.expectedFailure
    def test_chat_timeline_includes_retriable_generation_item(self) -> None:
        from backend.app.api.routes.chat import get_chat_timeline
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-1', 'vault-1', 'QA session', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
                )
                VALUES ('msg-1', 'session-1', 'user', 'Hello', '[]', '[]', '[]', NULL, 0, ?)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                    runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES ('gen-1', 'session-1', 'msg-1', NULL, 'vault-1', 'Hello', 'retriable', '', '', 'interrupted', NULL, ?, ?, NULL)
                """,
                (now, now),
            )

        timeline = get_chat_timeline("session-1")
        retriable = [item for item in timeline["items"] if item["message_type"] == "retriable_generation"]

        self.assertEqual(len(retriable), 1)
        self.assertEqual(retriable[0]["prompt"], "Hello")

    def test_safe_open_stops_redirect_loops(self) -> None:
        from backend.app.core.extraction import ExtractionError, _safe_open
        from urllib.request import Request

        class LoopingOpener:
            def open(self, request, timeout=0):
                raise HTTPError(request.full_url, 302, "loop", {"Location": "/next"}, None)

        with patch("backend.app.core.extraction.build_opener", return_value=LoopingOpener()):
            with self.assertRaises(ExtractionError) as raised:
                _safe_open(Request("https://example.com/start"), timeout=1)
        self.assertIn("Too many redirects", str(raised.exception))

    def test_mcp_backend_unreachable_maps_to_1005(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        with patch("backend.app.bridge_mcp.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/api/v1/bridge/context", request_id="1")
        self.assertEqual(raised.exception.code, 1005)

    def test_mcp_http_error_uses_registered_application_code(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        body = json.dumps({"detail": "cluster_not_allowed"}).encode("utf-8")

        class FakeHTTPError(HTTPError):
            def read(self):
                return body

        error = FakeHTTPError("http://test", 403, "forbidden", {}, None)
        with patch("backend.app.bridge_mcp.urlopen", side_effect=error):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/api/v1/bridge/context", request_id="2")
        self.assertEqual(raised.exception.code, 1004)

    def test_token_store_is_only_local_backend_token_path_literal_in_electron_shell(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        electron_dir = repo_root / "apps" / "desktop" / "electron"
        hits: list[Path] = []
        for path in electron_dir.glob("*.cjs"):
            if path.name.endswith(".test.cjs"):
                continue
            text = path.read_text(encoding="utf-8")
            if '"backend-token"' in text or "'backend-token'" in text:
                hits.append(path)
        self.assertEqual([path.name for path in hits], ["token-store.cjs"])

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
