import tempfile
import unittest
from pathlib import Path


class BenchmarkCorpusTests(unittest.TestCase):
    def test_create_synthetic_user_corpus_builds_varied_files(self) -> None:
        from backend.app.core.benchmark_corpus import create_synthetic_user_corpus

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            corpus = create_synthetic_user_corpus(tmp_dir)

            all_paths = [Path(path) for path in corpus["all_paths"]]
            pdf_paths = [Path(path) for path in corpus["pdf_paths"]]

            self.assertEqual(len(pdf_paths), 6)
            self.assertGreaterEqual(len(all_paths), 12)
            self.assertIn(".pdf", corpus["expected_suffixes"])
            self.assertIn(".md", corpus["expected_suffixes"])
            self.assertIn(".docx", corpus["expected_suffixes"])
            self.assertIn(".html", corpus["expected_suffixes"])
            self.assertTrue(all(path.exists() for path in all_paths))
            self.assertEqual(len({path.name for path in pdf_paths}), len(pdf_paths))
            self.assertGreater(len({path.stat().st_size for path in pdf_paths}), 3)
            self.assertGreaterEqual(len(corpus["queries"]), 4)

    def test_large_target_uses_scale_distribution(self) -> None:
        from backend.app.core.benchmark_corpus import _normalize_counts

        counts = _normalize_counts(None, target_file_count=10_000)

        self.assertGreaterEqual(sum(counts.values()), 10_000)
        self.assertGreaterEqual(counts["pdf"], 100)
        self.assertGreaterEqual(counts["csv"], 1000)


if __name__ == "__main__":
    unittest.main()
