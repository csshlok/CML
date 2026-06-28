import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.app.core.expert_contract import EXPERT_OBJECTIVE_VERSION


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
        self.assertEqual(manifest["expert_objective_version"], EXPERT_OBJECTIVE_VERSION)
        self.assertTrue(manifest["requires_retrieved_evidence"])
        self.assertTrue(manifest["behavior_specialization_enabled"])
        self.assertIn("behavior_profile", manifest)
        self.assertTrue(all("behavior_profile" in row for row in rows))
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

    def test_training_dataset_can_export_exact_source_splits_raw_corpus_and_qa_files(self) -> None:
        from backend.app.core.training_dataset import write_cluster_training_dataset

        documents = [
            {
                "source_id": f"source-{index:04d}",
                "title": f"Doc {index:04d}",
                "summary": f"Summary for source {index:04d} with enough grounding detail for export.",
                "text": (
                    f"Source {index:04d} contains grounded cluster evidence. "
                    f"It includes practical steps, terminology, and concrete notes for adapter training."
                ),
                "content_hash": f"content-hash-{index:04d}",
            }
            for index in range(1000)
        ]
        dataset = {
            "cluster_id": "cluster-1",
            "cluster_name": "Cluster One",
            "source_count": len(documents),
            "unique_content_hash_count": len(documents),
            "duplicate_content_count": 0,
            "duplicate_content_ratio": 0.0,
            "total_text_chars": sum(len(doc["text"]) for doc in documents),
            "estimated_token_count": 25000,
            "dataset_hash": "dataset-hash",
            "train_source_target": 700,
            "validation_source_target": 300,
            "documents": documents,
        }

        manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "large-dataset")
        train_source_rows = [
            json.loads(line)
            for line in Path(manifest["train_sources_path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        validation_source_rows = [
            json.loads(line)
            for line in Path(manifest["validation_sources_path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        train_qa_rows = [
            json.loads(line)
            for line in Path(manifest["train_qa_path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        validation_qa_rows = [
            json.loads(line)
            for line in Path(manifest["validation_qa_path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        train_corpus = Path(manifest["train_corpus_path"]).read_text(encoding="utf-8")
        validation_corpus = Path(manifest["validation_corpus_path"]).read_text(encoding="utf-8")

        self.assertEqual(manifest["train_source_count"], 700)
        self.assertEqual(manifest["validation_source_count"], 300)
        self.assertEqual(len(train_source_rows), 700)
        self.assertEqual(len(validation_source_rows), 300)
        self.assertEqual({row["source_id"] for row in train_source_rows} & {row["source_id"] for row in validation_source_rows}, set())
        self.assertTrue(all("prompt" in row and "answer" in row for row in train_qa_rows))
        self.assertTrue(all("prompt" in row and "answer" in row for row in validation_qa_rows))
        self.assertIn("### SOURCE_ID: source-0000", train_corpus)
        self.assertIn("### SOURCE_ID: source-0700", validation_corpus)
        self.assertIn("Ground the answer in the evidence", train_qa_rows[1]["answer"])

    def test_build_path_text_dataset_filters_translated_readmes_and_dedupes_content(self) -> None:
        from backend.app.core.training_dataset import build_path_text_dataset

        corpus_root = Path(self.tmp.name) / "corpus"
        corpus_root.mkdir(parents=True, exist_ok=True)
        (corpus_root / "README.md").write_text("Alpha text " * 80, encoding="utf-8")
        (corpus_root / "README-fr.md").write_text("French translation text " * 80, encoding="utf-8")
        (corpus_root / "guide.txt").write_text("Bravo text " * 90, encoding="utf-8")
        (corpus_root / "duplicate.md").write_text("Alpha text " * 80, encoding="utf-8")

        dataset = build_path_text_dataset(
            dataset_id="real-corpus",
            dataset_name="Real Corpus",
            source_paths=[corpus_root],
            minimum_chars=100,
        )

        self.assertEqual(dataset["source_count"], 2)
        titles = {doc["title"] for doc in dataset["documents"]}
        self.assertIn("guide.txt", titles)
        self.assertNotIn("README-fr.md", titles)
        self.assertEqual(sum(1 for doc in dataset["documents"] if doc["text"].startswith("Alpha text")), 1)

    def test_wikipedia_row_to_document_filters_disambiguation_and_shapes_source(self) -> None:
        from backend.app.core.external_lora_dataset import wikipedia_row_to_document

        disambiguation = wikipedia_row_to_document(
            {
                "id": "1",
                "title": "Mercury (disambiguation)",
                "text": "Mercury may refer to:\n" + ("Item\n" * 1000),
            },
            config="20231101.en",
            split="train",
        )
        accepted = wikipedia_row_to_document(
            {
                "id": "2",
                "url": "https://en.wikipedia.org/wiki/Anarchism",
                "title": "Anarchism",
                "text": ("Anarchism is a political philosophy concerned with authority and hierarchy. " * 80).strip(),
            },
            config="20231101.en",
            split="train",
        )

        self.assertIsNone(disambiguation)
        self.assertIsNotNone(accepted)
        assert accepted is not None
        self.assertEqual(accepted["source_id"], "wiki:20231101.en:2")
        self.assertEqual(accepted["origin_dataset"], "wikimedia/wikipedia")
        self.assertEqual(accepted["origin_config"], "20231101.en")
        self.assertEqual(accepted["origin_split"], "train")
        self.assertTrue(accepted["content_hash"])

    def test_squad_row_to_record_preserves_answers_and_impossible_cases(self) -> None:
        from backend.app.core.external_lora_dataset import squad_row_to_record

        answerable = squad_row_to_record(
            {
                "id": "qa-1",
                "title": "Normans",
                "context": "The Normans gave their name to Normandy in France.",
                "question": "In what country is Normandy located?",
                "answers": {"text": ["France", "France"], "answer_start": [42, 42]},
            },
            split="validation",
        )
        impossible = squad_row_to_record(
            {
                "id": "qa-2",
                "title": "Normans",
                "context": "The Normans gave their name to Normandy in France.",
                "question": "What was the mayor's favorite color?",
                "answers": {"text": [], "answer_start": []},
            },
            split="validation",
        )

        self.assertEqual(answerable["qa_id"], "squad_v2:validation:qa-1")
        self.assertEqual(answerable["answers"], ["France"])
        self.assertEqual(answerable["answer"], "France")
        self.assertFalse(answerable["is_impossible"])
        self.assertTrue(impossible["is_impossible"])
        self.assertEqual(impossible["answer"], "")

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

    def test_run_lora_training_process_packages_dataset_artifacts_with_test_trainer(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import run_lora_training_process

        dataset_dir = Path(self.tmp.name) / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        (dataset_dir / "train.jsonl").write_text("{}\n", encoding="utf-8")
        (dataset_dir / "validation.jsonl").write_text("{}\n", encoding="utf-8")
        (dataset_dir / "dataset-manifest.json").write_text(json.dumps({"dataset_hash": "hash-1"}), encoding="utf-8")
        output_dir = Path(self.tmp.name) / "adapter"
        os.environ["CML_ALLOW_LORA_TEST_TRAINER"] = "1"
        get_settings.cache_clear()
        try:
            result = run_lora_training_process(
                dataset_manifest={
                    "dataset_dir": str(dataset_dir),
                    "train_path": str(dataset_dir / "train.jsonl"),
                    "validation_path": str(dataset_dir / "validation.jsonl"),
                    "dataset_hash": "hash-1",
                },
                output_dir=output_dir,
                config={"base_model": str(Path(self.tmp.name) / "base-model")},
            )
        finally:
            os.environ.pop("CML_ALLOW_LORA_TEST_TRAINER", None)
            get_settings.cache_clear()

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue((output_dir / "dataset" / "train.jsonl").exists())
        self.assertTrue((output_dir / "dataset" / "validation.jsonl").exists())
        self.assertTrue((output_dir / "dataset" / "dataset-manifest.json").exists())

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
                        "expert_objective_version": EXPERT_OBJECTIVE_VERSION,
                        "benchmark_report": {
                            "passes": False,
                            "dataset_hash": "dataset-hash",
                            "metadata": {"expert_objective_version": EXPERT_OBJECTIVE_VERSION},
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
