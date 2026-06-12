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

    def test_phase0_protected_route_families_reject_before_ready(self) -> None:
        self._initialize_security_directly()
        client = self._client()
        try:
            checks = [
                client.get("/api/v1/sources"),
                client.get("/api/v1/chat/sessions"),
                client.post("/api/v1/search/semantic", json={"vault_id": "vault-phase2", "query": "x"}),
                client.get("/api/v1/clusters"),
                client.get("/api/v1/clusters/cluster-1/expert/status"),
                client.post("/api/v1/bridge/context", json={"query": "x", "vault_id": "vault-phase2"}),
                client.get("/api/v1/integrations/imports"),
                client.get("/api/v1/integrations/imports/import-1/reconciliation-runs"),
                client.get("/api/v1/integrations/reconciliation-runs/run-1/items"),
                client.post("/api/v1/integrations/reconciliation-items/item-1/retry"),
                client.post("/api/v1/diagnostics/bundle"),
                client.post("/api/v1/jobs/run-once"),
            ]
        finally:
            client.close()

        for response in checks:
            self.assertEqual(response.status_code, 423)
            self.assertEqual(response.json()["detail"], "vault_unlock_required")

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

    def test_unlock_settings_visible_and_mutable(self) -> None:
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
            settings = client.patch(
                "/api/v1/system/unlock/settings",
                json={"vault_id": "vault-phase2", "unlock_mode": "strict", "pin_enabled": True},
            )
            status = client.get("/api/v1/system/unlock/status")
        finally:
            client.close()

        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json()["unlock_mode"], "strict")
        self.assertTrue(settings.json()["pin_enabled"])
        self.assertEqual(status.json()["unlock_mode"], "strict")
        self.assertTrue(status.json()["pin_enabled"])

    def test_settings_ui_exposes_phase2_unlock_controls(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        settings_tsx = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.settings.tsx").read_text(encoding="utf-8")
        backend_ts = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")

        for required in (
            "Vault unlock",
            "Convenience mode",
            "Strict locked mode",
            "Enable PIN setting",
            "Offline recovery key",
            "full passphrase",
        ):
            self.assertIn(required, settings_tsx)
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
