import os
import tempfile
import unittest
import zipfile
from pathlib import Path


class EncryptedStoragePhase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-secure", "Secure", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("cluster-secure", "vault-secure", "Secure Cluster", "", now, now),
            )

        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-secure",
            "phase three passphrase",
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
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        self.tmp.cleanup()

    def test_secured_source_pages_and_chunks_do_not_store_plaintext(self) -> None:
        from backend.app.api.routes.search import semantic_search
        from backend.app.api.routes.sources import create_source, list_source_pages
        from backend.app.core.database import connect, dict_from_row
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SemanticSearchRequest, SourceCreate

        secret = "phase-three-ultra-secret document content retrieval marker"
        source = create_source(
            SourceCreate(
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                title="Encrypted Source",
                source_type="note",
                raw_text=secret,
                tags=["secret-tag"],
            )
        )
        self.assertIn(secret, source["raw_text"])

        pages = list_source_pages(source["id"])
        self.assertEqual(pages[0]["raw_text"], secret)

        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        results = semantic_search(
            SemanticSearchRequest(vault_id="vault-secure", query="retrieval marker", limit=5)
        )
        self.assertTrue(results["results"])
        self.assertIn("retrieval marker", results["results"][0]["snippet"])

        with connect() as conn:
            stored_source = conn.execute(
                "SELECT raw_text, extracted_text, summary, tags FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            stored_page = conn.execute(
                "SELECT raw_text FROM source_pages WHERE source_id = ?",
                (source["id"],),
            ).fetchone()
            stored_chunk = conn.execute(
                "SELECT text FROM source_chunks WHERE source_id = ?",
                (source["id"],),
            ).fetchone()
            encrypted_count = conn.execute(
                "SELECT COUNT(*) AS count FROM encrypted_content WHERE vault_id = ?",
                ("vault-secure",),
            ).fetchone()

        self.assertEqual(stored_source["raw_text"], "")
        self.assertEqual(stored_source["extracted_text"], "")
        self.assertEqual(stored_source["summary"], "")
        self.assertEqual(stored_source["tags"], "[]")
        self.assertEqual(stored_page["raw_text"], "")
        self.assertEqual(stored_chunk["text"], "")
        self.assertGreaterEqual(encrypted_count["count"], 4)
        self._assert_plaintext_not_in_database_files(secret)

    def test_streaming_encrypted_blob_round_trip_without_plaintext_blob(self) -> None:
        from backend.app.core.encrypted_storage import read_encrypted_file_to_bytes, write_encrypted_file_from_path

        marker = b"phase-three-large-blob-secret"
        source_path = self.data_dir / "input-large.bin"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("wb") as handle:
            for index in range(6):
                handle.write((marker + bytes([index])) * 40_000)

        result = write_encrypted_file_from_path(
            vault_id="vault-secure",
            source_path=source_path,
            blob_id="large-blob-test",
            chunk_size=512 * 1024,
        )
        blob_path = Path(result["path"])
        self.assertTrue(blob_path.exists())
        self.assertGreater(result["chunk_count"], 1)
        self.assertNotIn(marker, blob_path.read_bytes())
        self.assertEqual(read_encrypted_file_to_bytes(vault_id="vault-secure", blob_id="large-blob-test"), source_path.read_bytes())

    def test_diagnostics_redacts_recovery_key_and_reports_encrypted_storage(self) -> None:
        from backend.app.api.routes.diagnostics import create_diagnostic_bundle

        log_dir = self.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        recovery_key = "CMLR-ABCD-EFGH-IJKL-MNOP-QRST-UVWX-Y234-567A"
        (log_dir / "backend.log").write_text(
            f"passphrase=phase-three pass recovery-key={recovery_key} C:\\Users\\name\\Secret\\file.txt",
            encoding="utf-8",
        )

        bundle = create_diagnostic_bundle()
        with zipfile.ZipFile(bundle["bundle_path"]) as archive:
            manifest = archive.read("manifest.json").decode("utf-8")
            log_text = archive.read("logs/backend.log").decode("utf-8")

        self.assertIn("encrypted_content/blob records", manifest)
        self.assertNotIn("phase-three", log_text)
        self.assertNotIn(recovery_key, log_text)
        self.assertIn("[local-path]", log_text)

    def _assert_plaintext_not_in_database_files(self, secret: str) -> None:
        needle = secret.encode("utf-8")
        candidates = [
            self.db_path,
            self.db_path.with_name(self.db_path.name + "-wal"),
            self.db_path.with_name(self.db_path.name + "-journal"),
            self.db_path.with_name(self.db_path.name + "-shm"),
        ]
        for path in candidates:
            if path.exists():
                self.assertNotIn(needle, path.read_bytes(), f"plaintext leaked into {path}")
