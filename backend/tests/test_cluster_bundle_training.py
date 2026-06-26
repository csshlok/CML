import json
import os
import tempfile
import unittest
from pathlib import Path


class ClusterBundleTrainingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_training_dataset_uses_evidence_grounded_record_types(self) -> None:
        from backend.app.core.training_dataset import TRAINING_RECORD_TYPES, write_cluster_training_dataset

        dataset = {
            "cluster_id": "cluster-1",
            "cluster_name": "Cluster One",
            "source_count": 1,
            "unique_content_hash_count": 1,
            "duplicate_content_count": 0,
            "duplicate_content_ratio": 0.0,
            "total_text_chars": 2400,
            "estimated_token_count": 600,
            "dataset_hash": "dataset-hash",
            "documents": [
                {
                    "source_id": "source-1",
                    "title": "Public V1 Blockers",
                    "summary": "Public V1 remains blocked until the bundle benchmark passes.",
                    "text": (
                        "Public V1 remains blocked until the bundle benchmark passes. "
                        "The implementation keeps retrieval as authority and uses expert compression only after evidence exists."
                    ),
                    "content_hash": "content-hash",
                }
            ],
        }

        manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "bundle-dataset")
        rows = [
            json.loads(line)
            for path in (manifest["train_path"], manifest["validation_path"])
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        record_types = {row["record_type"] for row in rows}

        self.assertEqual(record_types, set(TRAINING_RECORD_TYPES))
        self.assertTrue(all(row["grounding_required"] for row in rows))
        self.assertTrue(all(row["evidence_handles"] for row in rows))
        self.assertTrue(all("source_ids" in row for row in rows))
        self.assertTrue(all("content_hashes" in row for row in rows))
        self.assertTrue(all("input_token_estimate" in row for row in rows))
        self.assertTrue(all("target_token_estimate" in row for row in rows))
        self.assertEqual(manifest["expert_objective_version"], "retrieval_grounded_compression_v1")
        self.assertTrue(manifest["requires_retrieved_evidence"])
        self.assertEqual(set(manifest["record_type_distribution"]), set(TRAINING_RECORD_TYPES))
        self.assertNotIn("factual_recall", {row["record_type"] for row in rows})
        self.assertNotIn("citation_grounding", {row["record_type"] for row in rows})

    def test_benchmark_accounting_uses_record_types_and_excludes_manifest_sources(self) -> None:
        from backend.app.core.training_dataset import build_cluster_dataset, write_cluster_training_dataset
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
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'needs-update', ?, ?)
                """,
                (now, now),
            )
            for source_id, title in (
                ("source-1", "Alpha Note"),
                ("source-2", "MANIFEST.json"),
            ):
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, cluster_id, title, source_type, state, original_path, url, checksum,
                        provenance, trust_tier, security_labels, parser_security_json, raw_text, extracted_text,
                        summary, tags, cover_image_url, deleted_at, created_at, updated_at
                    )
                    VALUES (?, 'vault-1', 'cluster-1', ?, 'note', 'ready', '', '', '', 'local_import',
                            'trusted_local', '[]', '{}', ?, ?, ?, '[]', NULL, NULL, ?, ?)
                    """,
                    (
                        source_id,
                        title,
                        f"{title} text describing evidence grounded compression.",
                        f"{title} text describing evidence grounded compression.",
                        f"{title} summary describing evidence grounded compression.",
                        now,
                        now,
                    ),
                )

        dataset = build_cluster_dataset("cluster-1")
        manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "accounting-dataset")
        validation = manifest["benchmark_record_accounting"]["validation"]

        self.assertEqual(dataset["source_count"], 1)
        self.assertEqual(manifest["benchmark_record_accounting"]["used_source_count"], 1)
        self.assertIn("record_type_counts", validation)
        self.assertIn("max_record_share_per_source_per_record_type", validation)

    def test_legacy_prompt_only_artifact_is_not_treated_as_trained(self) -> None:
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.expert_lifecycle import expert_status_report

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Primary", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO expert_artifacts (
                    id, cluster_id, vault_id, job_id, artifact_type, status, local_path, base_model,
                    hardware_tier, quality_score, dataset_hash, training_config_hash, metrics_json,
                    active, rolled_back_at, deleted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, 'lora_adapter', 'ready', 'C:/tmp/adapter', 'base-model', 'gpu',
                        90.0, 'dataset-hash', 'cfg', ?, 1, NULL, NULL, ?, ?)
                """,
                (
                    "artifact-1",
                    "cluster-1",
                    "vault-1",
                    json.dumps({"expert_objective_version": "legacy_prompt_only"}, separators=(",", ":")),
                    now,
                    now,
                ),
            )

        with connect() as conn:
            status = expert_status_report(conn, "cluster-1")

        self.assertFalse(status["trained"])
        self.assertEqual(status["failure_code"], "legacy_prompt_only")

    def test_status_report_uses_bundle_era_user_labels(self) -> None:
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.expert_lifecycle import expert_status_report

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Primary", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )

        with connect() as conn:
            status = expert_status_report(conn, "cluster-1")

        self.assertEqual(status["expert_status"], "retrieval_ready")
        self.assertEqual(status["user_status"], "Searchable")
        self.assertFalse(status["trained"])

    def test_mark_cluster_needs_update_writes_expert_stale(self) -> None:
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.expert_lifecycle import mark_cluster_needs_update

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Primary", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'expert_compression_ready', ?, ?)
                """,
                (now, now),
            )
            mark_cluster_needs_update(conn, "cluster-1", "Sources changed.")
            cluster = conn.execute("SELECT expert_status FROM clusters WHERE id = 'cluster-1'").fetchone()
            job = conn.execute(
                "SELECT action, status, detail FROM cluster_expert_jobs WHERE cluster_id = 'cluster-1'"
            ).fetchone()

        self.assertEqual(cluster["expert_status"], "expert_stale")
        self.assertEqual(job["action"], "refresh-needed")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["detail"], "Sources changed.")

    def test_activation_guard_rejects_legacy_or_unverified_artifacts(self) -> None:
        from backend.app.core.expert_lifecycle import activation_guard_report

        legacy = activation_guard_report(
            {
                "id": "artifact-legacy",
                "dataset_hash": "dataset-hash",
                "metrics_json": json.dumps({"expert_objective_version": "legacy_prompt_only"}),
            },
            current_dataset_hash="dataset-hash",
        )
        unverified = activation_guard_report(
            {
                "id": "artifact-unverified",
                "dataset_hash": "dataset-hash",
                "metrics_json": json.dumps(
                    {
                        "expert_objective_version": "retrieval_grounded_compression_v1",
                        "benchmark_report": {
                            "passes": False,
                            "dataset_hash": "dataset-hash",
                            "metadata": {"expert_objective_version": "retrieval_grounded_compression_v1"},
                        },
                    }
                ),
            },
            current_dataset_hash="dataset-hash",
        )

        self.assertFalse(legacy["ok"])
        self.assertEqual(legacy["failure_code"], "legacy_prompt_only")
        self.assertFalse(unverified["ok"])
        self.assertEqual(unverified["failure_code"], "benchmark_unverified")


if __name__ == "__main__":
    unittest.main()
