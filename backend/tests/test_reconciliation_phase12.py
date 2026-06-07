import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReconciliationPhase12Tests(unittest.TestCase):
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
        self._create_vault("vault-1")

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

    def test_refresh_creates_reconciliation_runs_and_retryable_failed_items(self) -> None:
        from backend.app.api.routes.integrations import (
            list_import_reconciliation_items,
            list_import_reconciliation_runs,
            refresh_integration_import,
            scan_local_folder_integration,
        )
        from backend.app.schemas import LocalFolderScanRequest

        folder = Path(self.tmp.name) / "Dropbox"
        folder.mkdir()
        (folder / "good.md").write_text("good synced note content " * 10, encoding="utf-8")
        (folder / "empty.md").write_text("", encoding="utf-8")

        scan = scan_local_folder_integration(
            LocalFolderScanRequest(vault_id="vault-1", path=str(folder), max_files=10)
        )
        refreshed = refresh_integration_import(scan["import_id"], import_files=True, tombstone_missing=True)

        self.assertIsNotNone(refreshed["reconciliation_run_id"])
        self.assertEqual(refreshed["failed_count"], 1)

        runs = list_import_reconciliation_runs(scan["import_id"], limit=5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "completed_with_failures")
        self.assertEqual(runs[0]["retryable_failed_count"], 1)

        page = list_import_reconciliation_items(runs[0]["id"], limit=25, offset=0, result="failed")
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["result"], "failed")
        self.assertTrue(page["items"][0]["retryable"])
        self.assertIn("empty.md", page["items"][0]["item_reference"])

    def test_secured_vault_encrypts_reconciliation_item_details(self) -> None:
        from backend.app.api.routes.integrations import refresh_integration_import, scan_local_folder_integration
        from backend.app.core import vault_crypto
        from backend.app.core.database import connect
        from backend.app.schemas import LocalFolderScanRequest

        vault_crypto.initialize_vault_security(
            "vault-1",
            "phase12-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

        folder = Path(self.tmp.name) / "Secured"
        folder.mkdir()
        (folder / "good.md").write_text("secured import content " * 10, encoding="utf-8")
        (folder / "empty.md").write_text("", encoding="utf-8")

        scan = scan_local_folder_integration(
            LocalFolderScanRequest(vault_id="vault-1", path=str(folder), max_files=10)
        )
        refresh_integration_import(scan["import_id"], import_files=True, tombstone_missing=True)

        with connect() as conn:
            item = conn.execute(
                """
                SELECT *
                FROM reconciliation_items
                WHERE import_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scan["import_id"],),
            ).fetchone()
            encrypted = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM encrypted_content
                WHERE entity_type = 'reconciliation_item'
                  AND field_name = 'detail_json'
                """
            ).fetchone()

        self.assertEqual(item["detail_json"], "{}")
        self.assertGreaterEqual(int(encrypted["count"] or 0), 1)

    def test_retry_reconciliation_item_creates_new_run_and_imports_fixed_file(self) -> None:
        from backend.app.api.routes.integrations import (
            list_import_reconciliation_items,
            list_import_reconciliation_runs,
            refresh_integration_import,
            retry_import_reconciliation_item,
            scan_local_folder_integration,
        )
        from backend.app.core.database import connect
        from backend.app.schemas import LocalFolderScanRequest

        folder = Path(self.tmp.name) / "Retryable"
        folder.mkdir()
        (folder / "good.md").write_text("good synced note content " * 10, encoding="utf-8")
        broken = folder / "empty.md"
        broken.write_text("", encoding="utf-8")

        scan = scan_local_folder_integration(
            LocalFolderScanRequest(vault_id="vault-1", path=str(folder), max_files=10)
        )
        refresh_integration_import(scan["import_id"], import_files=True, tombstone_missing=True)
        failed_page = list_import_reconciliation_items(
            list_import_reconciliation_runs(scan["import_id"], limit=1)[0]["id"],
            limit=25,
            offset=0,
            result="failed",
        )
        failed_item = failed_page["items"][0]

        broken.write_text("fixed content after retry " * 10, encoding="utf-8")
        retried = retry_import_reconciliation_item(failed_item["id"])

        self.assertEqual(retried["new_run"]["status"], "completed")
        self.assertIsNotNone(retried["new_item"])
        self.assertEqual(retried["new_item"]["result"], "success")

        with connect() as conn:
            source_titles = conn.execute(
                "SELECT title FROM sources WHERE vault_id = 'vault-1' ORDER BY title"
            ).fetchall()
        self.assertEqual([row["title"] for row in source_titles], ["empty.md", "good.md"])

    def test_compaction_keeps_logs_bounded(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.reconciliation_log import (
            append_reconciliation_item,
            compact_reconciliation_logs,
            create_reconciliation_run,
            finish_reconciliation_run,
        )
        from backend.app.core.database import utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO integration_imports (
                    id, vault_id, integration_type, root_path, status, supported_count,
                    skipped_count, truncated, last_scan_at, created_at, updated_at
                )
                VALUES ('import-cap', 'vault-1', 'local_folder', ?, 'scanned', 0, 0, 0, ?, ?, ?)
                """,
                (str(Path(self.tmp.name) / "cap"), now, now, now),
            )

        with patch("backend.app.core.reconciliation_log.RUN_ROW_CAP", 3), patch(
            "backend.app.core.reconciliation_log.ITEM_ROW_CAP_PER_RUN", 2
        ):
            for index in range(5):
                with connect() as conn:
                    run_id = create_reconciliation_run(
                        conn,
                        vault_id="vault-1",
                        import_id="import-cap",
                        trigger_source="manual_refresh",
                        root_path=str(Path(self.tmp.name) / "cap"),
                        import_files=True,
                        tombstone_missing=False,
                    )
                    for item_index in range(4):
                        append_reconciliation_item(
                            conn,
                            run_id=run_id,
                            vault_id="vault-1",
                            import_id="import-cap",
                            item_reference=f"file-{index}-{item_index}.md",
                            action="unchanged",
                            result="success",
                            detail={"path": f"file-{index}-{item_index}.md"},
                        )
                    finish_reconciliation_run(conn, run_id=run_id, status="completed", counts={"unchanged_count": 4})
                    compact_reconciliation_logs(conn)

        with connect() as conn:
            run_count = conn.execute("SELECT COUNT(*) AS count FROM reconciliation_runs").fetchone()
            item_counts = conn.execute(
                """
                SELECT MAX(item_count) AS max_items
                FROM (
                    SELECT COUNT(*) AS item_count
                    FROM reconciliation_items
                    GROUP BY run_id
                )
                """
            ).fetchone()

        self.assertEqual(int(run_count["count"] or 0), 3)
        self.assertEqual(int(item_counts["max_items"] or 0), 2)

    def _create_vault(self, vault_id: str) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (vault_id, "Test vault", self.tmp.name, now, now),
            )
