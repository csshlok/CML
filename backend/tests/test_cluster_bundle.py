import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ClusterBundleTests(unittest.TestCase):
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
                ("vault-1", "Primary", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Research', 'Cluster summary', 'sage', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, original_path, url, checksum,
                    provenance, trust_tier, security_labels, parser_security_json, raw_text, extracted_text,
                    summary, tags, cover_image_url, deleted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'note', 'ready', '', '', '', 'local_import', 'trusted_local', '[]', '{}', ?, ?, ?, '[]', NULL, NULL, ?, ?)
                """,
                (
                    "source-1",
                    "vault-1",
                    "cluster-1",
                    "Roadmap Note",
                    "Roadmap Note explains the bundle migration in plain terms.",
                    "Roadmap Note explains the bundle migration in plain terms.",
                    "Roadmap Note explains the bundle migration in plain terms.",
                    now,
                    now,
                ),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_bundle_returns_retrieval_evidence_with_rag_only_contract(self) -> None:
        from backend.app.core.cluster_bundle import build_cluster_bundle_context

        with patch(
            "backend.app.core.cluster_bundle.semantic_search",
            return_value={
                "results": [
                    {
                        "source_id": "source-1",
                        "source_title": "Roadmap Note",
                        "cluster_id": "cluster-1",
                        "chunk_id": "chunk-1",
                        "snippet": "Roadmap Note explains the bundle migration in plain terms.",
                        "score": 0.92,
                        "trust_tier": "trusted_local",
                        "source_type": "note",
                    }
                ]
            },
        ):
            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="what changed",
                cluster_id="cluster-1",
            )

        self.assertTrue(bundle["retrieval_authority"])
        self.assertEqual(len(bundle["citations"]), 1)
        self.assertNotIn("expert_digest", bundle)
        self.assertIn("answer_contract", bundle["cluster_profile"])
        self.assertEqual(
            bundle["cluster_profile"]["answer_contract"]["voice"],
            "Research local-context",
        )
        self.assertGreater(bundle["token_estimate"]["total_tokens"], 0)

    def test_bundle_uses_persisted_cluster_summary_and_glossary(self) -> None:
        from backend.app.core.cluster_bundle import build_cluster_bundle_context
        from backend.app.core.database import connect, utc_now

        with connect() as conn:
            conn.execute(
                """
                UPDATE clusters
                SET cluster_summary = ?, cluster_glossary = ?, updated_at = ?
                WHERE id = 'cluster-1'
                """,
                ("Persisted summary", '["bundle", "migration"]', utc_now()),
            )

        with patch(
            "backend.app.core.cluster_bundle.semantic_search",
            return_value={"results": []},
        ):
            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="what changed",
                cluster_id="cluster-1",
            )

        self.assertEqual(bundle["cluster_profile"]["summary"], "Persisted summary")
        self.assertEqual(bundle["cluster_profile"]["local_terms"], ["bundle", "migration"])

    def test_bundle_expanded_analysis_uses_analysis_packets(self) -> None:
        from backend.app.core.cluster_bundle import build_cluster_bundle_context

        with patch(
            "backend.app.core.cluster_bundle.build_analysis_packets",
            return_value={
                "packets": [
                    {
                        "source_id": "source-1",
                        "source_title": "Roadmap Note",
                        "chunk_id": "chunk-1",
                        "page_id": "page-1",
                        "page_number": 1,
                        "evidence_excerpt": "Expanded analysis packet evidence.",
                        "score": 0.88,
                        "provenance": "local_import",
                        "trust_tier": "trusted_local",
                        "security_labels": "[]",
                        "source_type": "note",
                        "low_trust": False,
                        "status": "ready",
                    }
                ],
                "analyzed_source_ids": ["source-1", "source-2"],
                "sources_considered": 2,
                "low_relevance_source_count": 1,
            },
        ) as packet_mock:
            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="expanded analysis indexed source scope",
                cluster_id="cluster-1",
                token_budget=12,
                mode="expanded_analysis",
            )

        packet_mock.assert_called_once()
        self.assertEqual(bundle["bundle_status"]["mode"], "expanded_analysis")
        self.assertEqual(bundle["bundle_status"]["sources_considered"], 2)
        self.assertEqual(bundle["bundle_status"]["sources_analyzed"], 2)
        self.assertEqual(bundle["bundle_status"]["sources_low_relevance"], 1)
        self.assertEqual(len(bundle["citations"]), 1)

    def test_bundle_complete_analysis_avoids_top_k_search(self) -> None:
        from backend.app.core.cluster_bundle import build_cluster_bundle_context

        with patch(
            "backend.app.core.cluster_bundle.semantic_search",
            side_effect=AssertionError("complete analysis should not use top-k semantic search"),
        ), patch(
            "backend.app.core.cluster_bundle.build_analysis_packets",
            return_value={
                "packets": [
                    {
                        "source_id": "source-1",
                        "source_title": "Roadmap Note",
                        "chunk_id": "chunk-1",
                        "page_id": "page-1",
                        "page_number": 1,
                        "evidence_excerpt": "Complete analysis packet evidence.",
                        "score": 0.9,
                        "provenance": "local_import",
                        "trust_tier": "trusted_local",
                        "security_labels": "[]",
                        "source_type": "note",
                        "low_trust": False,
                        "status": "ready",
                    }
                ],
                "analyzed_source_ids": ["source-1", "source-2", "source-3"],
                "sources_considered": 3,
                "low_relevance_source_count": 0,
            },
        ):
            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="complete analysis indexed source scope",
                cluster_id="cluster-1",
                token_budget=99,
                mode="complete_analysis",
            )

        self.assertEqual(bundle["bundle_status"]["mode"], "complete_analysis")
        self.assertTrue(bundle["bundle_status"]["analysis_full_scope"])
        self.assertEqual(bundle["bundle_status"]["sources_considered"], 3)


if __name__ == "__main__":
    unittest.main()
