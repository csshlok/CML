import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MigrationPlannerPhase5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-migration", "Migration", str(self.data_dir), now, now),
            )

        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-migration",
            "phase five passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

    def tearDown(self) -> None:
        try:
            from backend.app.core import vault_crypto

            vault_crypto.lock_all_vaults()
        except Exception:
            pass
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_planner_refuses_when_disk_preflight_fails_without_publication(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.migration_planner import MigrationPreflightError, begin_planned_migration

        with patch(
            "backend.app.core.migration_planner.disk_preflight",
            return_value={
                "path": str(self.data_dir),
                "probe_path": str(self.data_dir),
                "required_bytes": 999,
                "available_bytes": 1,
                "ok": False,
                "message": "Not enough disk space is available for this action.",
            },
        ):
            with self.assertRaises(MigrationPreflightError):
                begin_planned_migration(
                    "vault-migration",
                    {
                        "normalization_version": "norm-v2",
                        "embedding_model_id": "hash-dev",
                        "index_version": "v1",
                        "extraction_version": "extract-v1",
                        "epoch": 2,
                    },
                    safety_margin_bytes=1,
                )

        with connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM derived_state_publications").fetchone()
        self.assertEqual(row["count"], 0)

    def test_planner_begins_publication_only_after_successful_preflight(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.migration_planner import begin_planned_migration

        result = begin_planned_migration(
            "vault-migration",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash-dev",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 2,
            },
            safety_margin_bytes=1,
        )
        self.assertTrue(result["plan"]["ok"])
        self.assertEqual(result["publication"]["status"], "staging")

        with connect() as conn:
            row = conn.execute("SELECT * FROM derived_state_publications WHERE id = ?", (result["publication"]["id"],)).fetchone()
        self.assertEqual(row["normalization_version"], "norm-v2")
        self.assertEqual(row["status"], "staging")

    def test_disk_full_failure_preserves_old_tuple_and_marks_staging_failed(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.derived_state import query_epoch_snapshot_conn, record_staged_artifact
        from backend.app.core.migration_planner import begin_planned_migration, mark_publication_failed

        result = begin_planned_migration(
            "vault-migration",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash-dev",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 2,
            },
            safety_margin_bytes=1,
        )
        publication_id = result["publication"]["id"]
        record_staged_artifact(
            publication_id,
            vault_id="vault-migration",
            artifact_type="chunk-index",
            artifact_ref="staging/partial",
            byte_length=123,
        )
        failed = mark_publication_failed(publication_id, reason="disk_full")
        self.assertTrue(failed["old_tuple_preserved"])

        with connect() as conn:
            active = query_epoch_snapshot_conn(conn, "vault-migration", embedding_model_id="hash-dev", index_version="v1")
            publication = conn.execute("SELECT status FROM derived_state_publications WHERE id = ?", (publication_id,)).fetchone()
            artifact = conn.execute(
                "SELECT status FROM derived_state_staged_artifacts WHERE publication_id = ?",
                (publication_id,),
            ).fetchone()
        self.assertEqual(active["epoch"], 1)
        self.assertEqual(publication["status"], "failed")
        self.assertEqual(artifact["status"], "failed")

    def test_staging_gc_is_bounded_and_keeps_live_heartbeat_artifacts(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.derived_state import begin_publication, record_staged_artifact
        from backend.app.core.migration_planner import collect_staged_garbage, staging_summary

        publication = begin_publication(
            "vault-migration",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash-dev",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 2,
            },
        )
        failed_one = record_staged_artifact(
            publication["id"],
            vault_id="vault-migration",
            artifact_type="chunk-index",
            artifact_ref="staging/failed-1",
            byte_length=10,
        )
        failed_two = record_staged_artifact(
            publication["id"],
            vault_id="vault-migration",
            artifact_type="chunk-index",
            artifact_ref="staging/failed-2",
            byte_length=20,
        )
        live = record_staged_artifact(
            publication["id"],
            vault_id="vault-migration",
            artifact_type="chunk-index",
            artifact_ref="staging/live",
            byte_length=30,
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE derived_state_staged_artifacts
                SET status = 'failed', heartbeat_at = '2000-01-01T00:00:00+00:00'
                WHERE id IN (?, ?)
                """,
                (failed_one["id"], failed_two["id"]),
            )

        deleted = collect_staged_garbage("vault-migration", limit=1, stale_after_seconds=1)
        self.assertEqual(deleted["deleted_artifacts"], 1)
        self.assertEqual(deleted["retained_live_artifacts"], 1)

        summary = staging_summary("vault-migration")
        self.assertEqual(summary["artifacts"]["failed"]["count"], 1)
        self.assertEqual(summary["artifacts"]["staging"]["count"], 1)
        with connect() as conn:
            live_row = conn.execute(
                "SELECT * FROM derived_state_staged_artifacts WHERE id = ?",
                (live["id"],),
            ).fetchone()
        self.assertIsNotNone(live_row)


if __name__ == "__main__":
    unittest.main()
