import importlib
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
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Research', 'Cluster summary', 'sage', 'expert_compression_ready', ?, ?)
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

    def test_bundle_returns_retrieval_evidence_without_expert_when_no_ready_adapter(self) -> None:
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
                allow_expert_compression=False,
            )

        self.assertTrue(bundle["retrieval_authority"])
        self.assertEqual(len(bundle["citations"]), 1)
        self.assertFalse(bundle["expert_digest"]["used"])
        self.assertEqual(bundle["expert_digest"]["mode"], "disabled")
        self.assertIn("behavior_profile", bundle["cluster_profile"])
        self.assertEqual(
            bundle["cluster_profile"]["behavior_profile"]["reasoning_order"],
            ["evidence", "interpretation", "conclusion"],
        )

    def test_bundle_calls_expert_only_when_evidence_exists(self) -> None:
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
        ), patch(
            "backend.app.core.cluster_bundle.run_cluster_expert_compression",
            return_value={
                "ok": True,
                "artifact_id": "artifact-1",
                "digest": "Bundle migration keeps retrieval as authority.",
                "local_terms": ["bundle"],
                "reasoning_hints": ["ground claims first"],
                "uncertainties": [],
                "unsupported_claims": [],
                "behavior_profile": {
                    "voice": "Research local-expert",
                    "terminology_shift": ["bundle"],
                    "style_markers": ["grounded", "concrete"],
                    "reasoning_order": ["evidence", "interpretation", "conclusion"],
                    "framing_rules": ["prefer practical takeaways"],
                    "refusal_style": "state missing evidence explicitly",
                    "practicality_bias": "practical",
                },
            },
        ):
            from backend.app.core.database import connect, utc_now

            with connect() as conn:
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO expert_artifacts (
                        id, cluster_id, vault_id, job_id, artifact_type, status, local_path, base_model,
                        hardware_tier, quality_score, dataset_hash, training_config_hash, metrics_json,
                        active, rolled_back_at, deleted_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, NULL, 'lora_adapter', 'ready', 'C:/tmp/adapter', 'base-model',
                            'gpu', 90.0, 'hash', 'cfg', '{}', 1, NULL, NULL, ?, ?)
                    """,
                    ("artifact-1", "cluster-1", "vault-1", now, now),
                )

            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="what changed",
                cluster_id="cluster-1",
            )

        self.assertTrue(bundle["expert_digest"]["used"])
        self.assertEqual(bundle["expert_digest"]["artifact_id"], "artifact-1")
        self.assertGreater(bundle["token_ledger"]["expert_digest_tokens_estimate"], 0)
        self.assertEqual(bundle["expert_digest"]["mode"], "retrieval_grounded_behavior")
        self.assertEqual(
            bundle["expert_digest"]["behavior_profile"]["reasoning_order"],
            ["evidence", "interpretation", "conclusion"],
        )

    def test_bundle_rejects_unsupported_source_claims_from_expert_digest(self) -> None:
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
        ), patch(
            "backend.app.core.cluster_bundle.run_cluster_expert_compression",
            return_value={
                "ok": False,
                "mode": "unsupported_claims",
                "detail": "unsupported source title",
                "warnings": ["Expert digest failed grounding validation."],
            },
        ):
            from backend.app.core.database import connect, utc_now

            with connect() as conn:
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO expert_artifacts (
                        id, cluster_id, vault_id, job_id, artifact_type, status, local_path, base_model,
                        hardware_tier, quality_score, dataset_hash, training_config_hash, metrics_json,
                        active, rolled_back_at, deleted_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, NULL, 'lora_adapter', 'ready', 'C:/tmp/adapter', 'base-model',
                            'gpu', 90.0, 'hash', 'cfg', '{}', 1, NULL, NULL, ?, ?)
                    """,
                    ("artifact-1", "cluster-1", "vault-1", now, now),
                )

            bundle = build_cluster_bundle_context(
                vault_id="vault-1",
                query="what changed",
                cluster_id="cluster-1",
            )

        self.assertFalse(bundle["expert_digest"]["used"])
        self.assertEqual(bundle["expert_digest"]["mode"], "unsupported_claims")
        self.assertTrue(bundle["warnings"])

    def test_runtime_compression_rejects_empty_evidence(self) -> None:
        from backend.app.core.expert_runtime import run_cluster_expert_compression
        from backend.app.core.database import connect

        with connect() as conn:
            result = run_cluster_expert_compression(
                conn,
                cluster_id="cluster-1",
                prompt="compress",
                citations=[],
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["mode"], "no_evidence")

    def test_runtime_compression_prompt_and_validation(self) -> None:
        from backend.app.core.expert_runtime import build_expert_compression_prompt, _unsupported_claims_against_evidence

        prompt = build_expert_compression_prompt(
            prompt="summarize this",
            citations=[{"source_title": "Roadmap Note", "snippet": "Roadmap Note explains the bundle migration."}],
            cluster_profile={
                "local_terms": ["bundle"],
                "style_profile": "plain",
                "answer_contract": {"voice": "local-expert"},
                "behavior_profile": {"reasoning_order": ["evidence", "interpretation", "conclusion"]},
            },
        )
        unsupported = _unsupported_claims_against_evidence(
            "Roadmap Note says Berlin shipped 2028.",
            [{"source_title": "Roadmap Note", "snippet": "Roadmap Note explains the bundle migration."}],
            cluster_profile={"local_terms": ["bundle"]},
        )

        self.assertIn("Authority: Use only the evidence below.", prompt)
        self.assertIn("behavior_profile", prompt)
        self.assertTrue(any("Berlin" in item or "2028" in item for item in unsupported))

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
                allow_expert_compression=False,
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
                allow_expert_compression=False,
                mode="complete_analysis",
            )

        self.assertEqual(bundle["bundle_status"]["mode"], "complete_analysis")
        self.assertTrue(bundle["bundle_status"]["analysis_full_scope"])
        self.assertEqual(bundle["bundle_status"]["sources_considered"], 3)


if __name__ == "__main__":
    unittest.main()
