import os
import tempfile
import unittest
from pathlib import Path


class SourcePageIndexingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"

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
        self.tmp.cleanup()

    def test_text_source_creates_page_and_page_linked_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        text = " ".join(f"word{i}" for i in range(260))
        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Long note",
                source_type="note",
                raw_text=text,
            )
        )
        run_due_jobs_once(limit=1)

        with connect() as conn:
            pages = conn.execute(
                "SELECT * FROM source_pages WHERE source_id = ?",
                (source["id"],),
            ).fetchall()
            chunks = conn.execute(
                "SELECT * FROM source_chunks WHERE source_id = ? ORDER BY chunk_index",
                (source["id"],),
            ).fetchall()

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["page_number"], 1)
        self.assertTrue(pages[0]["content_hash"])
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(chunk["page_id"] == pages[0]["id"] for chunk in chunks))
        self.assertTrue(all(chunk["content_hash"] for chunk in chunks))
        self.assertTrue(all(chunk["embedding_model_id"] for chunk in chunks))
        self.assertTrue(all(chunk["indexed_at"] for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
