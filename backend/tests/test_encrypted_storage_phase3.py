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
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

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
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
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

    def test_secured_source_memory_rebuild_uses_decrypted_content(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.context_memory import get_context_memory, rebuild_source_memory
        from backend.app.core.database import connect
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                title="Encrypted Memory Source",
                source_type="note",
                raw_text=(
                    "We decided to retain the encrypted memory marker for future retrieval. "
                    "The system must preserve secured source memory without plaintext columns."
                ),
            )
        )

        with connect() as conn:
            rebuild_source_memory(conn, source_id=source["id"])
            stored_source = conn.execute(
                "SELECT raw_text, extracted_text, summary FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            active_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM memory_items
                WHERE source_id = ? AND status = 'active'
                """,
                (source["id"],),
            ).fetchone()
            memory_items, working_memory = get_context_memory(
                conn,
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                query="encrypted memory marker",
            )

        self.assertEqual(stored_source["raw_text"], "")
        self.assertEqual(stored_source["extracted_text"], "")
        self.assertEqual(stored_source["summary"], "")
        self.assertGreater(active_count["count"], 0)
        self.assertTrue(any("encrypted memory marker" in item["detail_text"] for item in memory_items))
        self.assertGreater(working_memory["memory_count"], 0)

    def test_secured_bootstrap_memory_map_uses_decrypted_summary(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.context_memory import get_context_memory, refresh_bootstrap_memory_map
        from backend.app.core.database import connect
        from backend.app.schemas import SourceCreate

        create_source(
            SourceCreate(
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                title="Encrypted Bootstrap Source",
                source_type="note",
                raw_text="Bootstrap secret marker should appear only after decrypting the secured summary.",
            )
        )

        with connect() as conn:
            refresh_bootstrap_memory_map(conn, vault_id="vault-secure", cluster_id="cluster-secure")
            _memory_items, working_memory = get_context_memory(
                conn,
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                query="bootstrap secret marker",
            )
            stored_summary = conn.execute(
                """
                SELECT summary
                FROM working_memory_snapshots
                WHERE vault_id = ? AND cluster_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                ("vault-secure", "cluster-secure"),
            ).fetchone()

        self.assertIn("Encrypted Bootstrap Source", working_memory["summary"])
        self.assertIn("Bootstrap secret marker", stored_summary["summary"])

    def test_secured_context_layer_report_includes_decrypted_evidence(self) -> None:
        import json
        from unittest.mock import patch

        from backend.app.api.routes.search import create_context_layer_report
        from backend.app.api.routes.sources import create_source
        from backend.app.core.context_packets import build_bridge_context_packet as real_build_packet
        from backend.app.core.database import connect, dict_from_row
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                title="Encrypted Context Report Source",
                source_type="note",
                raw_text=(
                    "Context report encrypted evidence marker should be measured in packets. "
                    "We decided the context layer must keep secured snippets available for reports. "
                )
                * 18,
            )
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))
        captured_snippets: list[list[dict]] = []

        def capture_packet(**kwargs):
            captured_snippets.append(list(kwargs.get("source_snippets") or []))
            return real_build_packet(**kwargs)

        with patch("backend.app.core.context_layer_eval.build_bridge_context_packet", side_effect=capture_packet):
            report = create_context_layer_report("vault-secure", cluster_id="cluster-secure", limit=3)

        payload = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
        all_snippets = [snippet for batch in captured_snippets for snippet in batch]

        with connect() as conn:
            stored_source = conn.execute(
                "SELECT raw_text, extracted_text, summary FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()

        self.assertEqual(stored_source["raw_text"], "")
        self.assertEqual(stored_source["extracted_text"], "")
        self.assertEqual(stored_source["summary"], "")
        self.assertTrue(any("encrypted evidence marker" in item.get("snippet", "").lower() for item in all_snippets))
        self.assertTrue(any(row["expansion_handle_count"] >= 1 for row in payload["rows"]))
        self.assertTrue(any(row["raw_payload_bytes"] > 600 for row in payload["rows"]))

    def test_secured_context_strategy_report_measures_decrypted_evidence(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.benchmark_matrix import export_context_strategy_report
        from backend.app.core.database import connect, dict_from_row
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-secure",
                cluster_id="cluster-secure",
                title="Encrypted Strategy Report Source",
                source_type="note",
                raw_text=(
                    "Context strategy encrypted benchmark marker proves secured snippets affect token accounting. "
                    "The benchmark should measure decrypted source evidence, not blank database columns. "
                )
                * 18,
            )
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        report = export_context_strategy_report(
            "vault-secure",
            cluster_id="cluster-secure",
            queries=["encrypted benchmark marker"],
            strict=True,
        )
        row = report["rows"][0]

        with connect() as conn:
            stored_source = conn.execute(
                "SELECT raw_text, extracted_text, summary FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()

        self.assertEqual(stored_source["raw_text"], "")
        self.assertEqual(stored_source["extracted_text"], "")
        self.assertEqual(stored_source["summary"], "")
        self.assertGreaterEqual(row["result_count"], 1)
        self.assertGreater(row["raw_tokens"], 120)
        self.assertGreater(row["current_cml_tokens"], 80)

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
            names = archive.namelist()
            bundle_text = "\n".join(
                archive.read(name).decode("utf-8")
                for name in names
                if name.endswith(".json")
            )

        self.assertIn("encrypted_content/blob records", manifest)
        self.assertNotIn("logs/backend.log", names)
        self.assertNotIn("phase three pass", bundle_text)
        self.assertNotIn(recovery_key, bundle_text)
        self.assertNotIn(r"C:\Users\name\Secret\file.txt", bundle_text)

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
