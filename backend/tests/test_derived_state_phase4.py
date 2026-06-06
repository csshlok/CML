import os
import tempfile
import unittest
from pathlib import Path


class DerivedStatePhase4Tests(unittest.TestCase):
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
                ("vault-derived", "Derived", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("cluster-derived", "vault-derived", "Derived Cluster", "", now, now),
            )

        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-derived",
            "phase four passphrase",
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

    def test_query_snapshot_prevents_mixed_tuple_retrieval(self) -> None:
        source_id = self._create_and_reindex_source("phase four tuple evidence marker " * 40)

        from backend.app.api.routes.search import semantic_search
        from backend.app.core.database import connect
        from backend.app.core.derived_state import (
            begin_publication,
            chunk_eligibility_sql,
            publish_verified,
            query_epoch_snapshot_conn,
            record_staged_artifact,
            verify_publication,
        )
        from backend.app.schemas import SemanticSearchRequest

        initial = semantic_search(
            SemanticSearchRequest(vault_id="vault-derived", query="tuple evidence marker", limit=5)
        )
        self.assertTrue(initial["results"])

        with connect() as conn:
            old_snapshot = query_epoch_snapshot_conn(conn, "vault-derived", embedding_model_id="hash", index_version="v1")
            old_clause, old_params = chunk_eligibility_sql("chunks", old_snapshot)

        publication = begin_publication(
            "vault-derived",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 2,
            },
            artifact_manifest={"source_count": 1},
        )
        record_staged_artifact(
            publication["id"],
            vault_id="vault-derived",
            artifact_type="chunk-index",
            artifact_ref="staging/epoch-2",
        )
        verify_publication(publication["id"])
        publish_verified(publication["id"])

        after_publish = semantic_search(
            SemanticSearchRequest(vault_id="vault-derived", query="tuple evidence marker", limit=5)
        )
        self.assertEqual(after_publish["results"], [])

        with connect() as conn:
            old_rows = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM source_chunks chunks
                WHERE chunks.source_id = ? {old_clause}
                """,
                [source_id, *old_params],
            ).fetchone()
        self.assertGreater(old_rows["count"], 0)

    def test_reindex_under_new_tuple_restores_query_eligibility(self) -> None:
        source_id = self._create_and_reindex_source("phase four reindex restores evidence " * 40)

        from backend.app.api.routes.search import semantic_search
        from backend.app.core.database import connect, dict_from_row
        from backend.app.core.derived_state import begin_publication, publish_verified, verify_publication
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SemanticSearchRequest

        publication = begin_publication(
            "vault-derived",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash",
                "index_version": "v1",
                "extraction_version": "extract-v2",
                "epoch": 2,
            },
        )
        verify_publication(publication["id"])
        publish_verified(publication["id"])

        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))
            chunk = conn.execute("SELECT * FROM source_chunks WHERE source_id = ?", (source_id,)).fetchone()

        self.assertEqual(chunk["normalization_version"], "norm-v2")
        self.assertEqual(chunk["extraction_version"], "extract-v2")
        self.assertEqual(chunk["derived_state_epoch"], 2)

        result = semantic_search(
            SemanticSearchRequest(vault_id="vault-derived", query="restores evidence", limit=5)
        )
        self.assertTrue(result["results"])

    def test_failed_publication_does_not_flip_active_tuple_and_rollback_restores_previous(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.derived_state import (
            DerivedStatePublicationError,
            begin_publication,
            mark_artifact_status,
            publish_verified,
            query_epoch_snapshot_conn,
            record_staged_artifact,
            rollback_to_previous_tuple,
            verify_publication,
        )

        failed_publication = begin_publication(
            "vault-derived",
            {
                "normalization_version": "norm-failed",
                "embedding_model_id": "hash",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 2,
            },
        )
        artifact = record_staged_artifact(
            failed_publication["id"],
            vault_id="vault-derived",
            artifact_type="normalization",
            artifact_ref="staging/failed",
        )
        mark_artifact_status(artifact["id"], "failed")
        with self.assertRaises(DerivedStatePublicationError):
            verify_publication(failed_publication["id"])

        with connect() as conn:
            still_active = query_epoch_snapshot_conn(conn, "vault-derived", embedding_model_id="hash", index_version="v1")
        self.assertEqual(still_active["epoch"], 1)

        good_publication = begin_publication(
            "vault-derived",
            {
                "normalization_version": "norm-v2",
                "embedding_model_id": "hash",
                "index_version": "v1",
                "extraction_version": "extract-v1",
                "epoch": 3,
            },
        )
        verify_publication(good_publication["id"])
        publish_verified(good_publication["id"])
        rollback = rollback_to_previous_tuple("vault-derived")
        self.assertEqual(rollback["active_tuple"]["epoch"], 1)
        with self.assertRaises(DerivedStatePublicationError):
            publish_verified(failed_publication["id"])

    def _create_and_reindex_source(self, text: str) -> str:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-derived",
                cluster_id="cluster-derived",
                title="Derived Source",
                source_type="note",
                raw_text=text,
            )
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))
        return source["id"]


if __name__ == "__main__":
    unittest.main()
