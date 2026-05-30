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
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

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
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
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

    def test_deleted_source_is_hidden_from_search_before_cleanup_runs(self) -> None:
        from backend.app.api.routes.search import semantic_search
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SemanticSearchRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Searchable note",
                source_type="note",
                raw_text="alpha beta gamma " * 120,
            )
        )
        run_due_jobs_once(limit=1)

        delete_source(source["id"])

        result = semantic_search(SemanticSearchRequest(vault_id="vault-1", query="alpha beta"))

        self.assertEqual(result["results"], [])
        with connect() as conn:
            chunks_before_cleanup = conn.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]
        self.assertGreater(chunks_before_cleanup, 0)

        run_due_jobs_once(limit=1)
        with connect() as conn:
            chunks_after_cleanup = conn.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]
            pages_after_cleanup = conn.execute(
                "SELECT COUNT(*) AS count FROM source_pages WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]
        self.assertEqual(chunks_after_cleanup, 0)
        self.assertEqual(pages_after_cleanup, 0)

    def test_vector_reconciliation_queues_missing_source_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_vector_reconcile_incremental
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Needs chunks",
                source_type="note",
                raw_text="delta epsilon zeta " * 120,
            )
        )
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs")
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source["id"],))

        _run_vector_reconcile_incremental({"vault_id": "vault-1"})

        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_jobs
                WHERE job_type = 'reindex_source' AND status = 'queued'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn(source["id"], row["payload"])

    def test_vector_reconciliation_queues_stale_embedding_model_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_vector_reconcile_incremental, run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Stale chunks",
                source_type="note",
                raw_text="theta iota kappa " * 120,
            )
        )
        run_due_jobs_once(limit=1)
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs")
            conn.execute(
                "UPDATE source_chunks SET embedding_model_id = 'old-model' WHERE source_id = ?",
                (source["id"],),
            )

        _run_vector_reconcile_incremental({"vault_id": "vault-1"})

        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_jobs
                WHERE job_type = 'reindex_source' AND status = 'queued'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn(source["id"], row["payload"])

    def test_duplicate_source_checksum_returns_existing_source(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        payload = SourceCreate(
            vault_id="vault-1",
            title="Duplicate candidate",
            source_type="note",
            raw_text="same source body " * 40,
        )
        first = create_source(payload)
        second = create_source(payload)

        with connect() as conn:
            source_count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(source_count, 1)


if __name__ == "__main__":
    unittest.main()
