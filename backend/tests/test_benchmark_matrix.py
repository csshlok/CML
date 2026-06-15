import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BenchmarkMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_benchmark_ingestion_corpus_reports_operator_and_product_metrics(self) -> None:
        from backend.app.core.benchmark_matrix import benchmark_ingestion_corpus

        target = Path(self.tmp.name) / "note.txt"
        target.write_text("benchmark ingestion evidence", encoding="utf-8")

        report = benchmark_ingestion_corpus([target])

        self.assertEqual(report["operator_summary"]["document_count"], 1)
        self.assertEqual(report["product_summary"]["documents_ready_for_search"], 1)
        self.assertTrue(Path(report["json_path"]).exists())

    def test_benchmark_ingestion_corpus_can_return_capture_payloads(self) -> None:
        from backend.app.core.benchmark_matrix import benchmark_ingestion_corpus

        target = Path(self.tmp.name) / "note.txt"
        target.write_text("benchmark ingestion evidence", encoding="utf-8")

        report = benchmark_ingestion_corpus([target], capture_payloads=True)

        self.assertIn("_captures", report)
        self.assertEqual(report["_captures"][0]["suffix"], ".txt")
        self.assertIn("benchmark ingestion evidence", report["_captures"][0]["text"])

    def test_benchmark_pdf_parser_corpus_summarizes_each_parser(self) -> None:
        from backend.app.core.benchmark_matrix import benchmark_pdf_parser_corpus

        target = Path(self.tmp.name) / "doc.pdf"
        target.write_bytes(b"%PDF-1.4\n")

        def fake_extract(path, backend):
            return {
                "title": Path(path).name,
                "pages": ["alpha", "beta"],
                "parser": {"backend": backend, "mode": "text", "structured_tables": []},
            }

        with patch("backend.app.core.benchmark_matrix.extract_pdf_document_with_backend", side_effect=fake_extract):
            report = benchmark_pdf_parser_corpus([target], parsers=["builtin", "opendataloader_pdf"])

        self.assertIn("builtin", report["parser_summaries"])
        self.assertIn("opendataloader_pdf", report["parser_summaries"])
        self.assertEqual(report["parser_summaries"]["builtin"]["success_count"], 1)

    def test_export_context_strategy_report_compares_multiple_reduction_modes(self) -> None:
        from backend.app.core.benchmark_matrix import export_context_strategy_report
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', 'Benchmarks', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES ('source-1', 'vault-1', 'cluster-1', 'Benchmark Report', 'note', 'indexed',
                    'raw', 'raw', 'Token reduction and parser speed evidence.', '[]', ?, ?)
                """,
                (now, now),
            )

        with (
            patch("backend.app.core.benchmark_matrix.embed_text", return_value=[0.1, 0.2]),
            patch(
                "backend.app.core.benchmark_matrix.semantic_search_results",
                return_value={
                    "results": [
                        {
                            "source_id": "source-1",
                            "cluster_id": "cluster-1",
                            "snippet": "Token reduction and parser speed evidence.",
                        }
                    ]
                },
            ),
            patch(
                "backend.app.core.benchmark_matrix.get_context_memory",
                return_value=([{"kind": "fact", "summary": "Repeated-turn savings matter."}], {"summary": "Benchmark focus"}), 
            ),
        ):
            report = export_context_strategy_report("vault-1", queries=["benchmark token reduction"])

        self.assertEqual(report["query_count"], 1)
        row = report["rows"][0]
        self.assertIn("current_cml", row["strategies"])
        self.assertIn("context_caching", row["strategies"])
        self.assertIn("mem_u_style", row["strategies"])
        self.assertIn("context_mode_style", row["strategies"])

    def test_validate_context_benchmark_inputs_rejects_zero_chunk_vaults(self) -> None:
        from backend.app.core.benchmark_matrix import validate_context_benchmark_inputs
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-empty", "Empty", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES ('source-empty', 'vault-empty', 'Empty source', 'note', 'indexed', 'alpha', 'alpha', 'alpha', '[]', ?, ?)
                """,
                (now, now),
            )

        with self.assertRaisesRegex(RuntimeError, "zero indexed chunks"):
            validate_context_benchmark_inputs("vault-empty", query_specs=[{"prompt": "alpha"}])

    def test_benchmark_scripts_reference_the_new_python_benchmark_exports(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        pdf_script = (repo_root / "scripts" / "backend" / "benchmark-pdf-parsers.ps1").read_text(encoding="utf-8")
        ingestion_script = (repo_root / "scripts" / "backend" / "benchmark-ingestion-matrix.ps1").read_text(encoding="utf-8")
        context_script = (repo_root / "scripts" / "backend" / "benchmark-context-strategies.ps1").read_text(encoding="utf-8")
        release_script = (repo_root / "scripts" / "backend" / "validate-release-proof.ps1").read_text(encoding="utf-8")
        synthetic_script = (repo_root / "scripts" / "backend" / "benchmark-synthetic-user-corpus.ps1").read_text(encoding="utf-8")

        self.assertIn("benchmark_pdf_parser_corpus", pdf_script)
        self.assertIn("benchmark_ingestion_corpus", ingestion_script)
        self.assertIn("export_context_strategy_report", context_script)
        self.assertIn("test_pdf_pipeline.py", release_script)
        self.assertIn("create_synthetic_user_corpus", synthetic_script)


if __name__ == "__main__":
    unittest.main()
