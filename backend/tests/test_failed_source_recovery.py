import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


class FailedSourceRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, init_db, utc_now

        get_settings.cache_clear()
        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", self.tmp.name, now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_stats_returns_latest_failed_job_error(self) -> None:
        from backend.app.api.routes.sources import create_source, get_source_stats
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Recoverable source",
                source_type="note",
                raw_text="Content that can be indexed again.",
            ),
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE dedupe_key = ?
                """,
                ("Embedding runtime stopped.", utc_now(), f"reindex-source:{source['id']}"),
            )

        stats = get_source_stats(source["id"])

        self.assertEqual(stats["last_error"], "Embedding runtime stopped.")

    def test_failed_source_with_content_can_be_retried(self) -> None:
        from backend.app.api.routes.sources import create_source, reindex_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Recoverable source",
                source_type="note",
                raw_text="Content that can be indexed again.",
            ),
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'failed', last_error = 'Temporary failure', updated_at = ?
                WHERE dedupe_key = ?
                """,
                (utc_now(), f"reindex-source:{source['id']}"),
            )
            conn.execute("UPDATE sources SET state = 'failed' WHERE id = ?", (source["id"],))

        result = reindex_source(source["id"])

        with connect() as conn:
            row = conn.execute("SELECT state FROM sources WHERE id = ?", (source["id"],)).fetchone()
        self.assertEqual(row["state"], "indexed")
        self.assertEqual(result["status"], "queued")

    def test_failed_source_without_content_requires_reimport(self) -> None:
        from backend.app.api.routes.sources import create_source, reindex_source
        from backend.app.core.database import connect
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Empty source",
                source_type="file",
            ),
        )
        with connect() as conn:
            conn.execute("UPDATE sources SET state = 'failed' WHERE id = ?", (source["id"],))

        with self.assertRaises(HTTPException) as raised:
            reindex_source(source["id"])

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("import the original again", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
