import os
import tempfile
import unittest
from pathlib import Path


class ExtensionSetupContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_desktop_setup_contract_returns_thin_capture_bundle(self) -> None:
        from backend.app.api.routes.extension import create_desktop_extension_setup
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionDesktopSetupCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )

        bundle = create_desktop_extension_setup(
            ExtensionDesktopSetupCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                backend_url="http://127.0.0.1:7343",
                browser="brave",
            )
        )

        self.assertEqual(bundle["default_vault_id"], "vault-1")
        self.assertEqual(bundle["default_cluster_id"], "cluster-1")
        self.assertEqual(bundle["browser"], "brave")
        self.assertEqual(bundle["primary_actions"], ["save_link_to_vault", "take_and_save_screenshot"])
        self.assertIn("save_selection", bundle["optional_actions"])
        self.assertTrue(bundle["extension_token"])


if __name__ == "__main__":
    unittest.main()
