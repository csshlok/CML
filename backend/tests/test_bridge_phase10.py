import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class BridgePhase10Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "0"
        os.environ["CML_API_TOKEN"] = "local-api-token"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Primary", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', ?, ?)
                """,
                (now, now),
            )

        from backend.app.core import unlock_state, vault_crypto

        importlib.reload(vault_crypto)
        importlib.reload(unlock_state)

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_ALLOW_UNAUTHENTICATED_API",
            "CML_API_TOKEN",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_public_bridge_approval_request_bypasses_local_api_token_but_admin_list_does_not(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.schemas import BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = self._client()
        try:
            public = client.post(
                "/api/v1/bridge/approval-requests",
                json={"claimed_name": "Claude Desktop", "requested_vault_ids": ["vault-1"]},
            )
            admin = client.get("/api/v1/bridge/approval-requests")
        finally:
            client.close()

        self.assertEqual(public.status_code, 200)
        self.assertEqual(admin.status_code, 401)

    def test_bridge_settings_accept_legacy_style_profile_alias_and_return_cluster_profile_field(self) -> None:
        client = self._client()
        try:
            response = client.patch(
                "/api/v1/bridge/settings",
                headers={"x-cml-api-token": "local-api-token"},
                json={"enabled": True, "allow_style_profile": True},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["allow_cluster_profile"])
        self.assertNotIn("allow_style_profile", payload)

    def test_bridge_approval_request_round_trip_delivers_token_once(self) -> None:
        from backend.app.api.routes.bridge import (
            approve_bridge_approval_request,
            create_bridge_approval_request,
            poll_bridge_approval_request,
            update_bridge_settings,
        )
        from backend.app.schemas import (
            BridgeApprovalDecision,
            BridgeApprovalRequestCreate,
            BridgeSettingsUpdate,
        )

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        request_row = create_bridge_approval_request(
            BridgeApprovalRequestCreate(
                claimed_name="Local MCP",
                requested_vault_ids=["vault-1"],
                requested_cluster_ids=["cluster-1"],
            ),
            request=self._request_stub(),
        )
        pending = poll_bridge_approval_request(request_row["request_id"], approval_code=request_row["poll_code"])
        approved = approve_bridge_approval_request(
            request_row["request_id"],
            BridgeApprovalDecision(detail="approved for local MCP"),
        )
        delivered = poll_bridge_approval_request(request_row["request_id"], approval_code=request_row["poll_code"])
        redelivered = poll_bridge_approval_request(request_row["request_id"], approval_code=request_row["poll_code"])

        self.assertEqual(pending["status"], "pending")
        self.assertEqual(approved["name"], "Local MCP")
        self.assertTrue(delivered["token_available"])
        self.assertTrue(delivered["token"])
        self.assertFalse(redelivered["token_available"])
        self.assertIsNone(redelivered["token"])

    def test_bridge_approval_request_expiry_and_rate_limit_are_enforced(self) -> None:
        from backend.app.api.routes.bridge import (
            create_bridge_approval_request,
            poll_bridge_approval_request,
            update_bridge_settings,
        )
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeApprovalRequestCreate, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        first = create_bridge_approval_request(
            BridgeApprovalRequestCreate(claimed_name="Fast client", requested_vault_ids=["vault-1"]),
            request=self._request_stub(),
        )
        with connect() as conn:
            conn.execute(
                "UPDATE bridge_approval_requests SET expires_at = ?, updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", utc_now(), first["request_id"]),
            )
        expired = poll_bridge_approval_request(first["request_id"], approval_code=first["poll_code"])

        for _ in range(4):
            create_bridge_approval_request(
                BridgeApprovalRequestCreate(claimed_name="Fast client", requested_vault_ids=["vault-1"]),
                request=self._request_stub(),
            )
        with self.assertRaises(Exception) as raised:
            create_bridge_approval_request(
                BridgeApprovalRequestCreate(claimed_name="Fast client", requested_vault_ids=["vault-1"]),
                request=self._request_stub(),
            )

        self.assertEqual(expired["status"], "expired")
        self.assertIn("bridge_rate_limited", str(raised.exception))

    def test_claimed_name_is_not_treated_as_verified_identity(self) -> None:
        from backend.app.api.routes.bridge import (
            create_bridge_approval_request,
            list_bridge_approval_requests,
            update_bridge_settings,
        )
        from backend.app.schemas import BridgeApprovalRequestCreate, BridgeSettingsUpdate

        executable = Path(self.tmp.name) / "claude.exe"
        executable.write_bytes(b"fake-binary")
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        create_bridge_approval_request(
            BridgeApprovalRequestCreate(
                claimed_name="Claude Desktop",
                requested_vault_ids=["vault-1"],
                executable_path=str(executable),
            ),
            request=self._request_stub(),
        )
        rows = list_bridge_approval_requests()

        self.assertEqual(rows[0]["claimed_name"], "Claude Desktop")
        self.assertFalse(rows[0]["verified_identity"])
        self.assertEqual(rows[0]["verified_identity_label"], "")

    def test_cluster_scoped_client_can_infer_vault_for_context_requests(self) -> None:
        from backend.app.api.routes.bridge import (
            build_context,
            create_bridge_client,
            expand_context_item,
            update_bridge_settings,
        )
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.schemas import (
            BridgeClientCreate,
            BridgeContextExpandRequest,
            BridgeContextRequest,
            BridgeSettingsUpdate,
            SourceCreate,
        )

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                title="Cluster-only bridge note",
                source_type="note",
                raw_text="cluster scoped bridge lookup content " * 80,
            )
        )
        run_due_jobs_once(limit=1)
        client = create_bridge_client(
            BridgeClientCreate(
                name="Cluster only client",
                allowed_cluster_ids=["cluster-1"],
            )
        )

        response = build_context(
            BridgeContextRequest(
                cluster_id="cluster-1",
                query="cluster scoped bridge lookup",
                client_name="Cluster only client",
            ),
            x_cml_bridge_token=client["token"],
        )

        self.assertEqual(response["query"], "cluster scoped bridge lookup")
        self.assertEqual(len(response["selected_clusters"]), 1)
        self.assertEqual(response["selected_clusters"][0]["id"], "cluster-1")
        self.assertGreaterEqual(len(response["source_snippets"]), 1)
        self.assertTrue(response["expansion_handles"])

        expanded = expand_context_item(
            BridgeContextExpandRequest(cluster_id="cluster-1", handle=response["expansion_handles"][0]),
            x_cml_bridge_token=client["token"],
        )

        self.assertIn("cluster scoped bridge lookup content", expanded["text"])

    def test_bridge_context_exposes_cluster_profile_when_cluster_profiles_are_enabled(self) -> None:
        from backend.app.api.routes.bridge import build_context, create_bridge_client, update_bridge_settings
        from backend.app.schemas import BridgeClientCreate, BridgeContextRequest, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(
            BridgeClientCreate(
                name="Profile client",
                allowed_cluster_ids=["cluster-1"],
                allow_cluster_profile=True,
            )
        )

        with patch(
            "backend.app.api.routes.bridge.build_cluster_bundle_context",
            return_value={
                "context_request_id": "ctx-1",
                "query": "cluster scoped bridge lookup",
                "selected_clusters": [{"id": "cluster-1", "name": "Research"}],
                "source_snippets": [],
                "citations": [],
                "memory_items": [],
                "working_memory": {},
                "retrieval_authority": True,
                "cluster_profile": {"summary": "Persisted profile"},
                "token_estimate": {"total_tokens": 12},
                "bundle_status": {"mode": "context"},
                "warnings": [],
                "expansion_handles": [],
            },
        ):
            response = build_context(
                BridgeContextRequest(
                    cluster_id="cluster-1",
                    query="cluster scoped bridge lookup",
                    client_name="No profile client",
                ),
                x_cml_bridge_token=client["token"],
            )

        self.assertEqual(response["cluster_profile"], {"summary": "Persisted profile"})
        self.assertEqual(response["token_estimate"], {"total_tokens": 12})
        self.assertIn("Cluster Profile", response["packet_text"])

    def test_project_bridge_context_includes_graph_only_when_requested(self) -> None:
        from backend.app.api.routes.bridge import build_context, create_bridge_client, update_bridge_settings
        from backend.app.core.projects import register_project
        from backend.app.schemas import BridgeClientCreate, BridgeContextRequest, BridgeSettingsUpdate

        repo = Path(self.tmp.name) / "bridge-project"
        repo.mkdir()
        (repo / "main.py").write_text("from auth import login\nlogin()\n", encoding="utf-8")
        (repo / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
        project = register_project(vault_id="vault-1", root_path=str(repo), name="Bridge project", sync=True)
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(
            BridgeClientCreate(name="Graph client", allowed_vault_ids=["vault-1"])
        )
        bundle = {
            "selected_clusters": [], "source_snippets": [], "citations": [], "memory_items": [],
            "working_memory": {}, "retrieval_authority": True, "cluster_profile": {},
            "token_estimate": {}, "bundle_status": {}, "warnings": [],
        }
        with patch("backend.app.api.routes.bridge.build_cluster_bundle_context", return_value=bundle):
            ordinary = build_context(
                BridgeContextRequest(project_id=project["id"], query="explain login"),
                x_cml_bridge_token=client["token"],
            )
            visual = build_context(
                BridgeContextRequest(
                    project_id=project["id"], query="show login graph", include_graph=True,
                    graph_mode="graph", graph_max_nodes=20,
                ),
                x_cml_bridge_token=client["token"],
            )

        self.assertIsNone(ordinary["graph_context"])
        self.assertIsNotNone(visual["graph_context"])
        self.assertIn("# Odin Graph Context", visual["packet_text"])

    def test_cluster_scoped_client_can_list_clusters_without_explicit_vault_scope(self) -> None:
        from backend.app.api.routes.bridge import create_bridge_client, list_bridge_clusters, update_bridge_settings
        from backend.app.schemas import BridgeClientCreate, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(
            BridgeClientCreate(
                name="Cluster list client",
                allowed_cluster_ids=["cluster-1"],
            )
        )

        response = list_bridge_clusters(x_cml_bridge_token=client["token"])

        self.assertEqual(len(response["clusters"]), 1)
        self.assertEqual(response["clusters"][0]["id"], "cluster-1")

    def test_cluster_scoped_manual_client_is_anchored_to_single_vault(self) -> None:
        from backend.app.api.routes.bridge import create_bridge_client, list_bridge_clients, update_bridge_settings
        from backend.app.core.database import connect
        from backend.app.schemas import BridgeClientCreate, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(
            BridgeClientCreate(
                name="Anchored cluster client",
                allowed_cluster_ids=["cluster-1"],
            )
        )
        listed = list_bridge_clients()

        with connect() as conn:
            columns = {
                item["name"]
                for item in conn.execute("PRAGMA table_info(bridge_clients)").fetchall()
            }

        self.assertEqual(client["approval_vault_id"], "vault-1")
        self.assertEqual(listed[0]["approval_vault_id"], "vault-1")
        self.assertNotIn("allow_expert_calls", columns)

    def test_bridge_context_returns_contract_vault_not_found_for_missing_vault(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.bridge import build_context, update_bridge_settings
        from backend.app.schemas import BridgeContextRequest, BridgeSettingsUpdate

        settings = update_bridge_settings(
            BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True)
        )

        with self.assertRaises(HTTPException) as raised:
            build_context(
                BridgeContextRequest(
                    vault_id="vault-missing",
                    query="missing vault bridge lookup",
                    client_name="Bridge client",
                ),
                x_cml_bridge_token=settings["bridge_token"],
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "vault_not_found")

    def test_reenabling_bridge_client_clears_revoked_timestamp(self) -> None:
        from backend.app.api.routes.bridge import create_bridge_client, update_bridge_client, update_bridge_settings
        from backend.app.core.database import connect
        from backend.app.schemas import BridgeClientCreate, BridgeClientUpdate, BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        client = create_bridge_client(
            BridgeClientCreate(
                name="Re-enable client",
                allowed_vault_ids=["vault-1"],
            )
        )
        disabled = update_bridge_client(client["id"], BridgeClientUpdate(enabled=False))
        reenabled = update_bridge_client(client["id"], BridgeClientUpdate(enabled=True))

        with connect() as conn:
            row = conn.execute(
                "SELECT enabled, revoked_at FROM bridge_clients WHERE id = ?",
                (client["id"],),
            ).fetchone()

        self.assertFalse(disabled["enabled"])
        self.assertIsNotNone(disabled["revoked_at"])
        self.assertTrue(reenabled["enabled"])
        self.assertIsNone(reenabled["revoked_at"])
        self.assertEqual(row["enabled"], 1)
        self.assertIsNone(row["revoked_at"])

    def test_updating_approved_client_scope_keeps_anchor_and_identity_metadata(self) -> None:
        from backend.app.api.routes.bridge import (
            approve_bridge_approval_request,
            create_bridge_approval_request,
            update_bridge_client,
            update_bridge_settings,
        )
        from backend.app.schemas import (
            BridgeApprovalDecision,
            BridgeApprovalRequestCreate,
            BridgeClientUpdate,
            BridgeSettingsUpdate,
        )

        executable = Path(self.tmp.name) / "approved-client.exe"
        executable.write_bytes(b"fake-binary")
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        request_row = create_bridge_approval_request(
            BridgeApprovalRequestCreate(
                claimed_name="Approved client",
                requested_vault_ids=["vault-1"],
                executable_path=str(executable),
            ),
            request=self._request_stub(),
        )
        approved = approve_bridge_approval_request(request_row["request_id"], BridgeApprovalDecision())
        updated = update_bridge_client(
            approved["id"],
            BridgeClientUpdate(allowed_vault_ids=[]),
        )

        self.assertEqual(updated["approval_vault_id"], "vault-1")
        self.assertEqual(updated["observed_executable_path"], str(executable.resolve()))
        self.assertNotEqual(updated["signature_status"], "not_provided")

    def test_revoked_approved_client_token_is_blocked_and_shared_token_is_disabled_for_secured_vaults(self) -> None:
        from backend.app.api.routes.bridge import (
            approve_bridge_approval_request,
            build_context,
            create_bridge_approval_request,
            revoke_bridge_client,
            update_bridge_settings,
        )
        from backend.app.core.unlock_state import initialize_security_and_unlock, lock
        from backend.app.schemas import (
            BridgeApprovalDecision,
            BridgeApprovalRequestCreate,
            BridgeContextRequest,
            BridgeSettingsUpdate,
        )

        initialize_security_and_unlock("vault-1", "bridge-phase10-passphrase")
        update_bridge_settings(BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True))
        request_row = create_bridge_approval_request(
            BridgeApprovalRequestCreate(claimed_name="Scoped client", requested_vault_ids=["vault-1"]),
            request=self._request_stub(),
        )
        client = approve_bridge_approval_request(request_row["request_id"], BridgeApprovalDecision())
        ok = build_context(
            BridgeContextRequest(vault_id="vault-1", query="hello", client_name="Scoped client"),
            x_cml_bridge_token=client["token"],
        )
        revoke_bridge_client(client["id"])
        with self.assertRaises(Exception) as revoked:
            build_context(
                BridgeContextRequest(vault_id="vault-1", query="hello", client_name="Scoped client"),
                x_cml_bridge_token=client["token"],
            )
        shared = update_bridge_settings(BridgeSettingsUpdate())
        with self.assertRaises(Exception) as shared_blocked:
            build_context(
                BridgeContextRequest(vault_id="vault-1", query="hello", client_name="shared"),
                x_cml_bridge_token=shared["bridge_token"],
            )
        lock("vault-1")
        http_client = self._client()
        try:
            locked = http_client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": client["token"]},
                json={"vault_id": "vault-1", "query": "hello", "client_name": "Scoped client"},
            )
        finally:
            http_client.close()

        self.assertEqual(ok["query"], "hello")
        self.assertIn("bridge_token_invalid", str(revoked.exception))
        self.assertIn("bridge_shared_token_disabled", str(shared_blocked.exception))
        self.assertEqual(locked.status_code, 423)

    def test_bridge_approval_history_is_encrypted_for_secured_vaults(self) -> None:
        from backend.app.api.routes.bridge import create_bridge_approval_request, update_bridge_settings
        from backend.app.core.database import connect
        from backend.app.core.unlock_state import initialize_security_and_unlock
        from backend.app.schemas import BridgeApprovalRequestCreate, BridgeSettingsUpdate

        initialize_security_and_unlock("vault-1", "bridge-phase10-passphrase")
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        created = create_bridge_approval_request(
            BridgeApprovalRequestCreate(
                claimed_name="Encrypted history client",
                requested_vault_ids=["vault-1"],
            ),
            request=self._request_stub(),
        )

        with connect() as conn:
            row = conn.execute(
                "SELECT details_json FROM bridge_approval_requests WHERE id = ?",
                (created["request_id"],),
            ).fetchone()
            encrypted = conn.execute(
                """
                SELECT ciphertext FROM encrypted_content
                WHERE vault_id = 'vault-1'
                  AND entity_type = 'bridge_approval_request'
                  AND entity_id = ?
                  AND field_name = 'details_json'
                """,
                (created["request_id"],),
            ).fetchone()

        self.assertEqual(row["details_json"], "{}")
        self.assertIsNotNone(encrypted)

    def _client(self) -> TestClient:
        from backend.app.main import app

        return TestClient(app)

    def _request_stub(self):
        class Client:
            host = "127.0.0.1"

        class RequestStub:
            client = Client()

        return RequestStub()
