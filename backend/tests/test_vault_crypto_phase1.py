import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class VaultCryptoPhase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-crypto", "Crypto", str(self.data_dir), now, now),
            )

    def tearDown(self) -> None:
        try:
            from backend.app.core import vault_crypto

            vault_crypto.lock_all_vaults()
        except Exception:
            pass
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def test_initialize_unlock_and_derive_distinct_subkeys(self) -> None:
        from backend.app.core import vault_crypto
        from backend.app.core.database import connect

        setup = vault_crypto.initialize_vault_security(
            "vault-crypto",
            "correct horse battery staple",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

        self.assertTrue(setup.recovery_key.startswith("CMLR-"))
        self.assertTrue(vault_crypto.is_vault_unlocked("vault-crypto"))
        with connect() as conn:
            row = conn.execute("SELECT * FROM vault_security_metadata WHERE vault_id = ?", ("vault-crypto",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["security_version"], 1)
        self.assertEqual(row["unlock_mode"], "convenience")
        self.assertNotIn("correct horse", json.dumps(dict(row)))

        material = vault_crypto.unlock_vault_with_passphrase("vault-crypto", "correct horse battery staple")
        subkeys = vault_crypto.derive_vault_subkeys(material)
        self.assertEqual(len(subkeys.database_key), 32)
        self.assertEqual(len({subkeys.database_key, subkeys.blob_key, subkeys.metadata_key, subkeys.lora_artifact_key}), 4)

    def test_wrong_passphrase_does_not_unlock_or_leak_secret(self) -> None:
        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-crypto",
            "right-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        vault_crypto.lock_vault("vault-crypto")

        with self.assertRaises(vault_crypto.InvalidVaultSecretError) as raised:
            vault_crypto.unlock_vault_with_passphrase("vault-crypto", "wrong-passphrase")

        self.assertFalse(vault_crypto.is_vault_unlocked("vault-crypto"))
        self.assertNotIn("wrong-passphrase", str(raised.exception))
        self.assertEqual(str(raised.exception), "invalid_vault_secret")

    def test_recovery_unlock_and_passphrase_reset_preserve_vault_master_key(self) -> None:
        from backend.app.core import vault_crypto

        setup = vault_crypto.initialize_vault_security(
            "vault-crypto",
            "old-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        old_material = vault_crypto.unlock_vault_with_passphrase("vault-crypto", "old-passphrase")
        old_subkeys = vault_crypto.derive_vault_subkeys(old_material)
        vault_crypto.lock_vault("vault-crypto")

        recovered = vault_crypto.unlock_vault_with_recovery_key("vault-crypto", setup.recovery_key)
        self.assertEqual(vault_crypto.derive_vault_subkeys(recovered), old_subkeys)

        vault_crypto.reset_passphrase_with_recovery_key(
            "vault-crypto",
            setup.recovery_key,
            "new-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        vault_crypto.lock_vault("vault-crypto")
        with self.assertRaises(vault_crypto.InvalidVaultSecretError):
            vault_crypto.unlock_vault_with_passphrase("vault-crypto", "old-passphrase")

        new_material = vault_crypto.unlock_vault_with_passphrase("vault-crypto", "new-passphrase")
        self.assertEqual(vault_crypto.derive_vault_subkeys(new_material), old_subkeys)
        vault_crypto.lock_vault("vault-crypto")
        recovered_again = vault_crypto.unlock_vault_with_recovery_key("vault-crypto", setup.recovery_key)
        self.assertEqual(vault_crypto.derive_vault_subkeys(recovered_again), old_subkeys)

    def test_sensitive_action_requires_full_passphrase(self) -> None:
        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-crypto",
            "sensitive-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

        self.assertTrue(vault_crypto.verify_sensitive_action("vault-crypto", "sensitive-passphrase"))
        with self.assertRaises(vault_crypto.InvalidVaultSecretError):
            vault_crypto.verify_sensitive_action("vault-crypto", "123456")

    def test_public_metadata_redacts_wrapped_keys_and_vendor_recovery_is_absent(self) -> None:
        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-crypto",
            "metadata-passphrase",
            unlock_mode="strict",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

        metadata = vault_crypto.get_vault_security_metadata("vault-crypto")
        self.assertEqual(metadata["unlock_mode"], "strict")
        self.assertFalse(metadata["pin_enabled"])
        self.assertFalse(metadata["has_vendor_recovery"])
        self.assertTrue(vault_crypto.no_vendor_recovery_available())
        for secret_field in (
            "passphrase_salt",
            "passphrase_wrapped_vmk",
            "recovery_salt",
            "recovery_wrapped_vmk",
            "pin_salt",
            "pin_wrapped_unlock_secret",
        ):
            self.assertNotIn(secret_field, metadata)

    def test_backend_restart_does_not_regain_unlocked_state(self) -> None:
        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-crypto",
            "restart-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        self.assertTrue(vault_crypto.is_vault_unlocked("vault-crypto"))

        reloaded = importlib.reload(vault_crypto)
        self.assertFalse(reloaded.is_vault_unlocked("vault-crypto"))
        self.assertEqual(reloaded.active_key_count(), 0)
        reloaded.unlock_vault_with_passphrase("vault-crypto", "restart-passphrase")
        self.assertTrue(reloaded.is_vault_unlocked("vault-crypto"))

    def test_redaction_helper_removes_recovery_key_and_base64_material(self) -> None:
        from backend.app.core import vault_crypto

        message = "recovery_key=CMLR-ABCD-EFGH-IJKL passphrase=hunter2 wrapped=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo="
        redacted = vault_crypto.redact_security_material(message)
        self.assertNotIn("CMLR-ABCD", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("YWJjZGVm", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_migration_adds_security_metadata_table_to_existing_v1_database(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.migrations import run_migrations

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
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_migrations (version, name, started_at, finished_at, status, error)
                VALUES (1, '001_baseline', '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:01+00:00', 'succeeded', '')
                """
            )
            conn.execute("DROP TABLE vault_security_metadata")

        run_migrations()

        with connect() as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'vault_security_metadata'"
            ).fetchone()
            encrypted_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'encrypted_content'"
            ).fetchone()
            derived_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'derived_state_publications'"
            ).fetchone()
            quarantine_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'source_quarantine_records'"
            ).fetchone()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            migration = conn.execute("SELECT status FROM schema_migrations WHERE version = 2").fetchone()
            encrypted_migration = conn.execute("SELECT status FROM schema_migrations WHERE version = 3").fetchone()
            derived_migration = conn.execute("SELECT status FROM schema_migrations WHERE version = 4").fetchone()
            quarantine_migration = conn.execute("SELECT status FROM schema_migrations WHERE version = 5").fetchone()
        self.assertIsNotNone(table)
        self.assertIsNotNone(encrypted_table)
        self.assertIsNotNone(derived_table)
        self.assertIsNotNone(quarantine_table)
        self.assertEqual(version, 5)
        self.assertEqual(migration["status"], "succeeded")
        self.assertEqual(encrypted_migration["status"], "succeeded")
        self.assertEqual(derived_migration["status"], "succeeded")
        self.assertEqual(quarantine_migration["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
