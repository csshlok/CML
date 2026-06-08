import os
import tempfile
import unittest
from pathlib import Path


class TurbovecBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "benchmark.sqlite3"
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATA_DIR", "CML_DATABASE_PATH", "CML_ALLOW_HASH_EMBEDDINGS", "CML_EMBEDDING_PROVIDER"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_stable_u64_is_deterministic(self) -> None:
        from backend.app.core.turbovec_benchmark import stable_u64

        left = stable_u64("chunk-1")
        right = stable_u64("chunk-1")
        self.assertEqual(left, right)
        self.assertNotEqual(left, stable_u64("chunk-2"))

    def test_sampled_queries_extracts_real_terms(self) -> None:
        from backend.app.core.turbovec_benchmark import BenchmarkChunkRow, sampled_queries

        rows = [
            BenchmarkChunkRow("c1", "s1", "A", "retrieval benchmark vector search memory scaling", "[]"),
            BenchmarkChunkRow("c2", "s2", "B", "bridge context audit token approval runtime", "[]"),
        ]

        queries = sampled_queries(rows, limit=2)
        self.assertEqual(len(queries), 2)
        self.assertIn("retrieval benchmark vector search memory scaling", queries[0])

    def test_discover_pdf_files_respects_exclude_roots(self) -> None:
        from backend.app.core.turbovec_benchmark import discover_pdf_files

        include_root = Path(self.tmp.name) / "include"
        exclude_root = Path(self.tmp.name) / "exclude"
        include_root.mkdir(parents=True)
        exclude_root.mkdir(parents=True)
        (include_root / "a.pdf").write_bytes(b"%PDF-1.4")
        (exclude_root / "b.pdf").write_bytes(b"%PDF-1.4")

        discovered = discover_pdf_files(
            [str(include_root.parent)],
            exclude_roots=[str(exclude_root)],
        )

        normalized = {str(path.resolve()).lower() for path in discovered}
        self.assertIn(str((include_root / "a.pdf").resolve()).lower(), normalized)
        self.assertNotIn(str((exclude_root / "b.pdf").resolve()).lower(), normalized)

    def test_projected_costs_reflect_chunk_count(self) -> None:
        from backend.app.core.turbovec_benchmark import projected_costs

        report = projected_costs(chunk_count=100_000, avg_embedding_bytes=3200, avg_chunk_text_bytes=900)
        self.assertEqual(report["chunk_count"], 100_000)
        self.assertGreater(report["current_architecture"]["embedding_storage_bytes_estimate"], 0)
        self.assertGreater(report["turbovec_4bit_projection"]["index_bytes_estimate"], 0)

    def test_benchmark_turbovec_scan_returns_results(self) -> None:
        from backend.app.core.embeddings import embed_text, encode_embedding
        from backend.app.core.turbovec_benchmark import BenchmarkChunkRow, benchmark_turbovec_scan

        rows = [
            BenchmarkChunkRow("chunk-1", "source-1", "One", "alpha beta gamma delta", encode_embedding(embed_text("alpha beta gamma delta"))),
            BenchmarkChunkRow("chunk-2", "source-2", "Two", "bridge approval identity token", encode_embedding(embed_text("bridge approval identity token"))),
            BenchmarkChunkRow("chunk-3", "source-3", "Three", "parser quarantine validation worker", encode_embedding(embed_text("parser quarantine validation worker"))),
        ]

        report = benchmark_turbovec_scan(rows, ["alpha beta gamma delta"], top_k=2, persist_path=str(Path(self.tmp.name) / "index.tvim"))
        self.assertEqual(report["engine"], "turbovec")
        self.assertEqual(report["query_count"], 1)
        self.assertGreaterEqual(report["persisted_index_bytes"], 1)
        self.assertGreaterEqual(len(report["results"][0]["top_chunk_ids"]), 1)

    def test_real_vault_benchmark_script_mentions_turbovec_and_pdfs(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "backend" / "benchmark-real-vault-retrieval.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("discover_pdf_files", text)
        self.assertIn("benchmark_turbovec_scan", text)
        self.assertIn("projected_100k_chunk_costs", text)


if __name__ == "__main__":
    unittest.main()
