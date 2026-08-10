import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class SecurityFixRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "security.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_API_TOKEN"] = "desktop-token"
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-a", "A", str(self.data_dir / "a"), now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-b", "B", str(self.data_dir / "b"), now, now),
            )
            conn.execute(
                """INSERT INTO clusters
                   (id, vault_id, name, description, color, cluster_summary, cluster_glossary, created_at, updated_at)
                   VALUES ('cluster-a', 'vault-a', 'A cluster', '', 'sage', 'private summary', '[\"private term\"]', ?, ?)""",
                (now, now),
            )

    def tearDown(self) -> None:
        try:
            from backend.app.core.vault_crypto import lock_all_vaults
            lock_all_vaults()
        except Exception:
            pass
        from backend.app.core.config import get_settings
        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS", "CML_API_TOKEN",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_bridge_cluster_scope_cannot_select_another_vault(self) -> None:
        from fastapi import HTTPException
        from backend.app.api.routes.bridge import build_context, create_bridge_client, update_bridge_settings
        from backend.app.schemas import BridgeClientCreate, BridgeContextRequest, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(BridgeClientCreate(name="cluster-only", allowed_cluster_ids=["cluster-a"]))
        with self.assertRaises(HTTPException) as denied:
            build_context(
                BridgeContextRequest(vault_id="vault-b", query="cross vault"),
                x_cml_bridge_token=client["token"],
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_cluster_profile_and_all_expansion_kinds_respect_capabilities(self) -> None:
        from backend.app.api.routes.bridge import (
            _expand_bridge_handle, create_bridge_client, list_bridge_clusters, update_bridge_settings,
        )
        from backend.app.schemas import BridgeClientCreate, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(BridgeClientCreate(name="redacted", allowed_cluster_ids=["cluster-a"]))
        clusters = list_bridge_clusters(x_cml_bridge_token=client["token"])["clusters"]
        self.assertEqual(clusters[0]["cluster_summary"], "")
        self.assertEqual(clusters[0]["cluster_glossary"], "[]")

        class FakeConn:
            def execute(self, *_args, **_kwargs):
                return self
            def fetchone(self):
                return {"id": "row"}

        with patch("backend.app.api.routes.bridge.chunk_from_encrypted_row", return_value={
            "id": "chunk-1", "source_id": "source-1", "text": "chunk secret",
        }):
            chunk = _expand_bridge_handle(FakeConn(), vault_id="vault-a", handle="chunk:chunk-1", allow_raw_snippets=False)
        with patch("backend.app.api.routes.bridge.page_from_encrypted_row", return_value={
            "id": "page-1", "source_id": "source-1", "raw_text": "page secret",
        }):
            page = _expand_bridge_handle(FakeConn(), vault_id="vault-a", handle="page:page-1", allow_raw_snippets=False)
        self.assertEqual(chunk["text"], "")
        self.assertEqual(page["text"], "")

    def test_secured_bridge_context_and_request_query_are_not_plaintext(self) -> None:
        from backend.app.api.routes.bridge import build_context, create_bridge_client, update_bridge_settings
        from backend.app.core.database import connect
        from backend.app.core.unlock_state import initialize_security_and_unlock
        from backend.app.schemas import BridgeClientCreate, BridgeContextRequest, BridgeSettingsUpdate

        initialize_security_and_unlock("vault-a", "security regression passphrase")
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(BridgeClientCreate(name="secured", allowed_vault_ids=["vault-a"]))
        secret = "unique-bridge-secret-9f43087c"
        bundle = {
            "selected_clusters": [], "source_snippets": [], "citations": [], "warnings": [],
            "memory_items": [], "working_memory": {}, "retrieval_authority": True,
            "cluster_profile": {}, "token_estimate": {}, "bundle_status": {},
        }
        with patch("backend.app.api.routes.bridge.build_cluster_bundle_context", return_value=bundle):
            response = build_context(
                BridgeContextRequest(vault_id="vault-a", query=secret),
                x_cml_bridge_token=client["token"],
            )
        with connect() as conn:
            packet = conn.execute("SELECT query, packet_text FROM bridge_context_packets WHERE id = ?", (response["context_request_id"],)).fetchone()
            request = conn.execute("SELECT query FROM bridge_requests WHERE vault_id = 'vault-a' ORDER BY created_at DESC LIMIT 1").fetchone()
            encrypted_count = conn.execute(
                "SELECT COUNT(*) AS count FROM encrypted_content WHERE entity_type IN ('bridge_context_packet', 'bridge_request')"
            ).fetchone()["count"]
        self.assertEqual(packet["query"], "")
        self.assertEqual(packet["packet_text"], "")
        self.assertEqual(request["query"], "")
        self.assertGreaterEqual(encrypted_count, 3)
        database_bytes = self.db_path.read_bytes()
        self.assertNotIn(secret.encode("utf-8"), database_bytes)

    def test_integration_middleware_authenticates_before_body_validation_and_caps_size(self) -> None:
        from backend.app.api.routes.extension import create_extension_client
        from backend.app.core.request_security import RequestSecurityMiddleware
        from backend.app.schemas import ExtensionClientCreate

        extension = create_extension_client(ExtensionClientCreate(name="browser", allowed_vault_ids=["vault-a"]))
        app = FastAPI()
        app.add_middleware(RequestSecurityMiddleware)

        @app.post("/api/v1/extension/capture")
        async def capture(payload: dict):
            return payload

        client = TestClient(app)
        invalid = client.post(
            "/api/v1/extension/capture",
            headers={"x-cml-extension-token": "invalid"},
            content=b"not-json",
        )
        oversized = client.post(
            "/api/v1/extension/capture",
            headers={
                "x-cml-extension-token": extension["token"],
                "content-length": str(3 * 1024 * 1024),
            },
            content=b"{}",
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(oversized.status_code, 413)

    def test_byte_limiter_rejects_before_recording_overage(self) -> None:
        from backend.app.core.bridge_security import BridgeRateLimitError, enforce_rate_limit
        from backend.app.core.database import connect

        with connect() as conn:
            enforce_rate_limit(
                conn, scope_type="test", scope_id="client", bucket="bytes",
                limit=10, window_seconds=60, byte_count=60, byte_limit=100,
            )
            with self.assertRaises(BridgeRateLimitError):
                enforce_rate_limit(
                    conn, scope_type="test", scope_id="client", bucket="bytes",
                    limit=10, window_seconds=60, byte_count=50, byte_limit=100,
                )
            row = conn.execute(
                "SELECT byte_count FROM bridge_rate_limits WHERE scope_type='test' AND scope_id='client' AND bucket='bytes'"
            ).fetchone()
        self.assertEqual(row["byte_count"], 60)

    def test_git_runner_disables_command_bearing_configuration(self) -> None:
        from backend.app.core.projects import _safe_git_run

        completed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
        with patch("backend.app.core.projects.subprocess.run", return_value=completed) as run:
            _safe_git_run(["git", "-C", str(self.data_dir), "diff", "HEAD"], capture_output=True)
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertIn("core.fsmonitor=false", command)
        self.assertIn("--no-ext-diff", command)
        self.assertIn("--no-textconv", command)
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

    def test_legacy_allow_all_clients_are_frozen_to_existing_vaults(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.migrations import _migration_032_security_scope_and_bridge_storage

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO extension_clients
                   (id, name, token_hash, enabled, allowed_vault_ids, created_at, updated_at)
                   VALUES ('legacy-extension', 'Legacy extension', 'hash', 1, '[]', ?, ?)""",
                (now, now),
            )
            conn.execute(
                """INSERT INTO bridge_clients
                   (id, name, token_hash, enabled, allowed_vault_ids, allowed_cluster_ids, created_at, updated_at)
                   VALUES ('legacy-bridge', 'Legacy bridge', 'hash', 1, '[]', '[]', ?, ?)""",
                (now, now),
            )

            _migration_032_security_scope_and_bridge_storage(conn)

            extension = conn.execute(
                "SELECT enabled, allowed_vault_ids FROM extension_clients WHERE id = 'legacy-extension'"
            ).fetchone()
            bridge = conn.execute(
                "SELECT enabled, allowed_vault_ids FROM bridge_clients WHERE id = 'legacy-bridge'"
            ).fetchone()

        self.assertTrue(extension["enabled"])
        self.assertTrue(bridge["enabled"])
        self.assertEqual(set(json.loads(extension["allowed_vault_ids"])), {"vault-a", "vault-b"})
        self.assertEqual(set(json.loads(bridge["allowed_vault_ids"])), {"vault-a", "vault-b"})


if __name__ == "__main__":
    unittest.main()
