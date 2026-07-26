import importlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class UnlockPhase2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-phase2", "Phase 2", str(self.data_dir), now, now),
            )

        from backend.app.core import unlock_state, vault_crypto

        importlib.reload(vault_crypto)
        importlib.reload(unlock_state)

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_API_PREFIX",
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_ALLOW_UNAUTHENTICATED_API",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_secured_vault_blocks_protected_routes_until_ready(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            locked = client.get("/api/v1/sources")
            status = client.get("/api/v1/system/unlock/status")
            unlocked = client.post(
                "/api/v1/system/unlock/passphrase",
                json={"vault_id": "vault-phase2", "passphrase": "phase2-passphrase"},
            )
            after = client.get("/api/v1/sources")
        finally:
            client.close()

        self.assertEqual(locked.status_code, 423)
        self.assertEqual(locked.json()["detail"], "vault_unlock_required")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["state"], "locked")
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(unlocked.json()["state"], "ready")
        self.assertEqual(after.status_code, 200)

    def test_new_unsecured_vault_starts_ready(self) -> None:
        client = self._client()
        try:
            status = client.get("/api/v1/system/unlock/status")
            sources = client.get("/api/v1/sources")
        finally:
            client.close()

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["state"], "ready")
        self.assertTrue(status.json()["ready"])
        self.assertEqual(status.json()["secured_vault_count"], 0)
        self.assertIn("Lock protection has not been enabled", status.json()["message"])
        self.assertEqual(sources.status_code, 200)

    def test_enabling_security_migrates_existing_source_plaintext_before_ready(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.unlock_state import initialize_security_and_unlock

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, raw_text, extracted_text,
                    summary, tags, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-before-security",
                    "vault-phase2",
                    "Private note",
                    "note",
                    "indexed",
                    "raw secret",
                    "extracted secret",
                    "summary secret",
                    '["private"]',
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status,
                    memory_updated_at, created_at, updated_at
                )
                VALUES ('session-before-security', 'vault-phase2', 'Private chat', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings,
                    useful, saved, created_at
                )
                VALUES (
                    'message-before-security', 'session-before-security', 'user',
                    'chat secret marker', '[]', '[{"snippet":"citation secret"}]', '[]',
                    NULL, 0, ?
                )
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id,
                    prompt, state, runtime_provider, runtime_model, error, heartbeat_at,
                    created_at, updated_at, completed_at
                )
                VALUES (
                    'generation-before-security', 'session-before-security',
                    'message-before-security', NULL, 'vault-phase2', 'generation secret marker',
                    'retriable', '', '', '', NULL, ?, ?, NULL
                )
                """,
                (now, now),
            )

        result = initialize_security_and_unlock(
            "vault-phase2",
            "CorrectHorseBatteryStaple1!",
        )

        with connect() as conn:
            source = conn.execute(
                "SELECT raw_text, extracted_text, summary, tags FROM sources WHERE id = ?",
                ("source-before-security",),
            ).fetchone()
            encrypted = conn.execute(
                """
                SELECT field_name, byte_length
                FROM encrypted_content
                WHERE vault_id = ? AND entity_type = 'source' AND entity_id = ?
                ORDER BY field_name
                """,
                ("vault-phase2", "source-before-security"),
            ).fetchall()
            chat_message = conn.execute(
                "SELECT content, clusters_used, citations, warnings FROM chat_messages WHERE id = 'message-before-security'"
            ).fetchone()
            generation = conn.execute(
                "SELECT prompt FROM chat_generations WHERE id = 'generation-before-security'"
            ).fetchone()
            chat_encrypted_fields = {
                row["field_name"]
                for row in conn.execute(
                    """
                    SELECT field_name FROM encrypted_content
                    WHERE vault_id = 'vault-phase2'
                      AND entity_type = 'chat_message'
                      AND entity_id = 'message-before-security'
                    """
                ).fetchall()
            }

        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["migrated_content"]["sources"], 1)
        self.assertEqual(result["migrated_content"]["chat_messages"], 1)
        self.assertEqual(result["migrated_content"]["chat_generations"], 1)
        self.assertEqual(dict(source), {
            "raw_text": "",
            "extracted_text": "",
            "summary": "",
            "tags": "[]",
        })
        self.assertEqual(
            {row["field_name"] for row in encrypted},
            {"raw_text", "extracted_text", "summary", "tags"},
        )
        self.assertEqual(dict(chat_message), {
            "content": "",
            "clusters_used": "[]",
            "citations": "[]",
            "warnings": "[]",
        })
        self.assertEqual(generation["prompt"], "")
        self.assertEqual(chat_encrypted_fields, {"content", "clusters_used", "citations", "warnings"})

    def test_unlock_resumes_interrupted_content_migration_before_ready(self) -> None:
        from backend.app.core import vault_crypto
        from backend.app.core.database import connect, utc_now
        from backend.app.core.encrypted_storage import put_encrypted_text
        from backend.app.core.unlock_state import unlock_with_passphrase

        vault_crypto.initialize_vault_security(
            "vault-phase2",
            "phase2-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        now = utc_now()
        with connect() as conn:
            for source_id, marker in (
                ("already-migrated-source", "first secret marker"),
                ("pending-migration-source", "second secret marker"),
            ):
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, title, source_type, state, raw_text, extracted_text,
                        summary, tags, created_at, updated_at
                    )
                    VALUES (?, 'vault-phase2', ?, 'note', 'indexed', ?, ?, ?, '[]', ?, ?)
                    """,
                    (source_id, source_id, marker, marker, marker, now, now),
                )
            put_encrypted_text(
                conn,
                vault_id="vault-phase2",
                entity_type="source",
                entity_id="already-migrated-source",
                field_name="raw_text",
                text="first secret marker",
                now=now,
            )
            conn.execute(
                """
                UPDATE sources
                SET raw_text = '', extracted_text = '', summary = '', tags = '[]'
                WHERE id = 'already-migrated-source'
                """
            )
            conn.execute(
                """
                UPDATE vault_security_metadata
                SET content_migration_status = 'running',
                    content_migration_updated_at = ?
                WHERE vault_id = 'vault-phase2'
                """,
                (now,),
            )
        vault_crypto.lock_vault("vault-phase2")

        result = unlock_with_passphrase("vault-phase2", "phase2-passphrase")

        with connect() as conn:
            metadata = conn.execute(
                "SELECT content_migration_status FROM vault_security_metadata WHERE vault_id = 'vault-phase2'"
            ).fetchone()
            pending_source = conn.execute(
                "SELECT raw_text, extracted_text, summary FROM sources WHERE id = 'pending-migration-source'"
            ).fetchone()
            encrypted_rows = conn.execute(
                """
                SELECT entity_id, field_name FROM encrypted_content
                WHERE vault_id = 'vault-phase2' AND entity_type = 'source'
                """
            ).fetchall()

        self.assertEqual(result["state"], "ready")
        self.assertEqual(metadata["content_migration_status"], "complete")
        self.assertEqual(dict(pending_source), {"raw_text": "", "extracted_text": "", "summary": ""})
        encrypted_pairs = {(row["entity_id"], row["field_name"]) for row in encrypted_rows}
        self.assertIn(("already-migrated-source", "raw_text"), encrypted_pairs)
        self.assertIn(("pending-migration-source", "raw_text"), encrypted_pairs)
        self.assertIn(("pending-migration-source", "extracted_text"), encrypted_pairs)

    def test_phase0_protected_route_families_reject_before_ready(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            checks = [
                client.get("/api/v1/sources"),
                client.get("/api/v1/chat/sessions"),
                client.post("/api/v1/search/semantic", json={"vault_id": "vault-phase2", "query": "x"}),
                client.get("/api/v1/clusters"),
                client.get("/api/v1/clusters/cluster-1"),
                client.post("/api/v1/bridge/context", json={"query": "x", "vault_id": "vault-phase2"}),
                client.get("/api/v1/integrations/imports"),
                client.get("/api/v1/integrations/imports/import-1/reconciliation-runs"),
                client.get("/api/v1/integrations/reconciliation-runs/run-1/items"),
                client.post("/api/v1/integrations/reconciliation-items/item-1/retry"),
                client.post("/api/v1/diagnostics/bundle"),
                client.post("/api/v1/jobs/run-once"),
                client.post(
                    "/api/v1/vaults",
                    json={"name": "Should not be created", "path": "C:/blocked"},
                ),
            ]
            vaults = client.get("/api/v1/vaults")
        finally:
            client.close()

        for response in checks:
            self.assertEqual(response.status_code, 423)
            self.assertEqual(response.json()["detail"], "vault_unlock_required")
        self.assertEqual(vaults.status_code, 200)
        self.assertEqual(vaults.json()[0]["path"], "")

    def test_lock_returns_to_locked_and_blocks_again(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            self.assertEqual(
                client.post(
                    "/api/v1/system/unlock/passphrase",
                    json={"vault_id": "vault-phase2", "passphrase": "phase2-passphrase"},
                ).status_code,
                200,
            )
            self.assertEqual(client.get("/api/v1/sources").status_code, 200)
            locked = client.post("/api/v1/system/unlock/lock")
            blocked = client.get("/api/v1/sources")
        finally:
            client.close()

        self.assertEqual(locked.status_code, 200)
        self.assertEqual(locked.json()["state"], "locked")
        self.assertEqual(blocked.status_code, 423)

    def test_wrong_passphrase_and_pin_do_not_unlock_sensitive_action(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            wrong = client.post(
                "/api/v1/system/unlock/passphrase",
                json={"vault_id": "vault-phase2", "passphrase": "wrong"},
            )
            pin = client.post(
                "/api/v1/system/unlock/sensitive-action",
                json={"vault_id": "vault-phase2", "passphrase": "123456"},
            )
            full = client.post(
                "/api/v1/system/unlock/sensitive-action",
                json={"vault_id": "vault-phase2", "passphrase": "phase2-passphrase"},
            )
            status_after_sensitive_action = client.get("/api/v1/system/unlock/status")
            protected_after_sensitive_action = client.get("/api/v1/sources")
        finally:
            client.close()

        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["detail"], "invalid_vault_secret")
        self.assertEqual(pin.status_code, 401)
        self.assertEqual(full.status_code, 200)
        self.assertTrue(full.json()["ok"])
        self.assertEqual(status_after_sensitive_action.json()["state"], "locked")
        self.assertEqual(protected_after_sensitive_action.status_code, 423)

    def test_locked_secured_vault_respects_custom_api_prefix_for_setup_routes(self) -> None:
        os.environ["CML_API_PREFIX"] = "custom/v2/"
        self._initialize_security_directly()
        client = self._client()
        try:
            identity = client.get("/custom/v2/system/backend-identity")
            unlock_status = client.get("/custom/v2/system/unlock/status")
            vaults = client.get("/custom/v2/vaults")
            protected = client.get("/custom/v2/sources")
        finally:
            client.close()

        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json()["api_prefix"], "/custom/v2")
        self.assertEqual(unlock_status.status_code, 200)
        self.assertEqual(unlock_status.json()["state"], "locked")
        self.assertEqual(vaults.status_code, 200)
        self.assertEqual(protected.status_code, 423)
        self.assertEqual(protected.json()["detail"], "vault_unlock_required")

    def test_initialize_endpoint_returns_recovery_key_once_and_ready_state(self) -> None:
        client = self._client()
        try:
            response = client.post(
                "/api/v1/system/unlock/initialize",
                json={"vault_id": "vault-phase2", "passphrase": "new-passphrase", "unlock_mode": "strict"},
            )
            duplicate = client.post(
                "/api/v1/system/unlock/initialize",
                json={"vault_id": "vault-phase2", "passphrase": "new-passphrase", "unlock_mode": "strict"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["unlock_mode"], "strict")
        self.assertTrue(body["recovery_key"].startswith("CMLR-"))
        self.assertEqual(duplicate.status_code, 409)

    def test_initialize_endpoint_rejects_weak_passphrase(self) -> None:
        client = self._client()
        try:
            response = client.post(
                "/api/v1/system/unlock/initialize",
                json={"vault_id": "vault-phase2", "passphrase": "short"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 422)

    def test_recovery_reset_unlocks_with_new_passphrase(self) -> None:
        client = self._client()
        try:
            setup = client.post(
                "/api/v1/system/unlock/initialize",
                json={"vault_id": "vault-phase2", "passphrase": "old-passphrase"},
            ).json()
            client.post("/api/v1/system/unlock/lock")
            reset = client.post(
                "/api/v1/system/unlock/recovery/reset",
                json={
                    "vault_id": "vault-phase2",
                    "recovery_key": setup["recovery_key"],
                    "new_passphrase": "new-passphrase",
                },
            )
            client.post("/api/v1/system/unlock/lock")
            old = client.post(
                "/api/v1/system/unlock/passphrase",
                json={"vault_id": "vault-phase2", "passphrase": "old-passphrase"},
            )
            new = client.post(
                "/api/v1/system/unlock/passphrase",
                json={"vault_id": "vault-phase2", "passphrase": "new-passphrase"},
            )
        finally:
            client.close()

        self.assertEqual(reset.status_code, 200)
        self.assertEqual(old.status_code, 401)
        self.assertEqual(new.status_code, 200)
        self.assertEqual(new.json()["state"], "ready")

    def test_recovery_reset_rejects_weak_new_passphrase(self) -> None:
        client = self._client()
        try:
            setup = client.post(
                "/api/v1/system/unlock/initialize",
                json={"vault_id": "vault-phase2", "passphrase": "correct horse battery staple"},
            ).json()
            client.post("/api/v1/system/unlock/lock")
            reset = client.post(
                "/api/v1/system/unlock/recovery/reset",
                json={
                    "vault_id": "vault-phase2",
                    "recovery_key": setup["recovery_key"],
                    "new_passphrase": "short",
                },
            )
        finally:
            client.close()

        self.assertEqual(reset.status_code, 422)

    def test_backend_restart_does_not_regain_ready_state(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            ready = client.post(
                "/api/v1/system/unlock/passphrase",
                json={"vault_id": "vault-phase2", "passphrase": "phase2-passphrase"},
            )
        finally:
            client.close()
        self.assertEqual(ready.status_code, 200)

        from backend.app.core import unlock_state

        importlib.reload(unlock_state)
        restarted = self._client()
        try:
            status = restarted.get("/api/v1/system/unlock/status")
            blocked = restarted.get("/api/v1/sources")
        finally:
            restarted.close()

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["state"], "locked")
        self.assertEqual(blocked.status_code, 423)

    def test_vault_bound_jobs_are_not_claimed_while_locked(self) -> None:
        self._initialize_security_directly()
        from backend.app.core.background_jobs import enqueue_job, run_due_jobs_once
        from backend.app.core.database import connect

        with connect() as conn:
            enqueue_job(
                conn,
                job_type="integration_refresh",
                payload={"vault_id": "vault-phase2", "import_id": "missing"},
                dedupe_key="phase2:locked-job",
            )

        processed = run_due_jobs_once(limit=1)

        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE dedupe_key = ?", ("phase2:locked-job",)).fetchone()
        self.assertEqual(processed, 0)
        self.assertEqual(row["status"], "queued")

    def test_incomplete_pin_mode_is_rejected_while_strict_mode_remains_available(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            self.assertEqual(
                client.post(
                    "/api/v1/system/unlock/passphrase",
                    json={"vault_id": "vault-phase2", "passphrase": "phase2-passphrase"},
                ).status_code,
                200,
            )
            rejected_pin = client.patch(
                "/api/v1/system/unlock/settings",
                json={"vault_id": "vault-phase2", "unlock_mode": "strict", "pin_enabled": True},
            )
            settings = client.patch(
                "/api/v1/system/unlock/settings",
                json={"vault_id": "vault-phase2", "unlock_mode": "strict", "pin_enabled": False},
            )
            status = client.get("/api/v1/system/unlock/status")
        finally:
            client.close()

        self.assertEqual(settings.status_code, 200)
        self.assertEqual(rejected_pin.status_code, 400)
        self.assertIn("PIN unlock is not available", rejected_pin.json()["detail"])
        self.assertEqual(settings.json()["unlock_mode"], "strict")
        self.assertFalse(settings.json()["pin_enabled"])
        self.assertEqual(status.json()["unlock_mode"], "strict")
        self.assertFalse(status.json()["pin_enabled"])

    def test_settings_ui_exposes_phase2_unlock_controls(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        settings_tsx = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.settings.tsx").read_text(encoding="utf-8")
        backend_ts = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")

        for required in (
            "Library unlock",
            "A protected library always starts locked",
            "Offline recovery key",
            "full passphrase",
        ):
            self.assertIn(required, settings_tsx)
        self.assertNotIn("Convenience mode", settings_tsx)
        self.assertNotIn("Enable PIN setting", settings_tsx)
        for required in (
            "getUnlockStatus",
            "initializeVaultSecurity",
            "unlockVaultWithPassphrase",
            "lockVault",
            "updateUnlockSettings",
        ):
            self.assertIn(required, backend_ts)

    def _initialize_security_directly(self) -> None:
        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-phase2",
            "phase2-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        vault_crypto.lock_vault("vault-phase2")

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
