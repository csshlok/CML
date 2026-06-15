import json
import tempfile
import unittest
from pathlib import Path


class BenchmarkGraphsTests(unittest.TestCase):
    def test_render_graphical_reports_supports_current_benchmark_families(self) -> None:
        from backend.app.core.benchmark_graphs import render_graphical_reports

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            reports_dir = root / "reports"
            output_dir = root / "graphs"
            reports_dir.mkdir()
            fixtures = {
                "pdf.json": {
                    "report_id": "pdf-benchmark-test",
                    "generated_at": "2026-06-15T00:00:00Z",
                    "runtime": {"selected_backend": "builtin"},
                    "rows": [{"parser": "builtin", "status": "passed", "seconds": 1.2}],
                    "parser_summaries": {
                        "builtin": {
                            "parser": "builtin",
                            "document_count": 1,
                            "success_count": 1,
                            "failure_count": 0,
                            "total_seconds": 1.2,
                            "avg_seconds_per_document": 1.2,
                            "avg_pages_per_document": 2.0,
                            "avg_chars_per_document": 1200.0,
                            "table_count": 0,
                        }
                    },
                },
                "ingestion.json": {
                    "report_id": "ingestion-benchmark-test",
                    "generated_at": "2026-06-15T00:00:00Z",
                    "rows": [{"path": "alpha.txt", "suffix": ".txt", "status": "passed", "seconds": 0.25}],
                    "operator_summary": {
                        "document_count": 1,
                        "type_breakdown": {
                            ".txt": {
                                "document_count": 1,
                                "success_count": 1,
                                "failure_count": 0,
                                "total_seconds": 0.25,
                                "text_chars": 42,
                                "avg_seconds_per_document": 0.25,
                            }
                        },
                    },
                    "product_summary": {
                        "import_success_rate_percent": 100.0,
                        "median_document_latency_seconds": 0.25,
                    },
                },
                "context.json": {
                    "report_id": "context-strategy-benchmark-test",
                    "generated_at": "2026-06-15T00:00:00Z",
                    "query_count": 1,
                    "rows": [
                        {
                            "query": "token reduction",
                            "raw_tokens": 500,
                            "current_cml_tokens": 250,
                            "strategies": {
                                "current_cml": {"reduction_percent": 50.0},
                                "context_caching": {"warm_reduction_percent": 80.0, "warm_tokens": 100},
                                "mem_u_style": {"reduction_percent": 70.0},
                                "context_mode_style": {"reduction_percent": 90.0},
                            },
                        }
                    ],
                    "product_summary": {
                        "best_average_strategy": "context_mode_style",
                        "warm_cache_average_reduction_percent": 80.0,
                    },
                },
                "release.json": {
                    "generated_at": "2026-06-15T00:00:00Z",
                    "passed": 2,
                    "failed": 1,
                    "results": [
                        {"name": "compile", "status": "passed"},
                        {"name": "tests", "status": "passed"},
                        {"name": "smoke", "status": "failed"},
                    ],
                },
            }
            report_paths = []
            for name, payload in fixtures.items():
                path = reports_dir / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                report_paths.append(path)

            result = render_graphical_reports(report_paths, output_dir=output_dir)

            self.assertEqual(result["report_count"], 4)
            self.assertTrue(Path(result["index_path"]).exists())
            for report in result["reports"]:
                self.assertTrue(Path(report["html_path"]).exists())
                self.assertGreater(len(report["svg_paths"]), 0)
                for svg_path in report["svg_paths"]:
                    text = Path(svg_path).read_text(encoding="utf-8")
                    self.assertIn("<svg", text)

    def test_discover_benchmark_reports_filters_to_supported_json(self) -> None:
        from backend.app.core.benchmark_graphs import discover_benchmark_reports

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            valid = root / "valid.json"
            invalid = root / "invalid.json"
            valid.write_text(json.dumps({"report_id": "pdf-benchmark-test", "parser_summaries": {}}), encoding="utf-8")
            invalid.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

            discovered = discover_benchmark_reports([root])

            self.assertEqual(discovered, [str(valid.resolve())])


if __name__ == "__main__":
    unittest.main()
