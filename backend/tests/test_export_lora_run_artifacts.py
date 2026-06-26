import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExportLoraRunArtifactsTests(unittest.TestCase):
    def test_exporter_prefers_bundle_first_summary_fields(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script_path = repo_root / "scripts" / "backend" / "export-lora-run-artifacts.py"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            benchmark_path = tmp_path / "post-training-benchmark.json"
            trainer_state_path = tmp_path / "trainer_state.json"
            output_prefix = tmp_path / "artifacts" / "run"

            benchmark_path.write_text(
                json.dumps(
                    {
                        "adapter_path": "adapter-path",
                        "base_model": "base-model",
                        "dataset_hash": "dataset-hash",
                        "created_at": "2026-06-26T00:00:00Z",
                        "status": "passed",
                        "passes": True,
                        "metrics": {
                            "quality_gate": {"passes": True},
                            "retrieval_case_scores": [
                                {
                                    "case_id": "case-1",
                                    "category": "style_transfer",
                                    "owner": "adapter",
                                    "counts_toward_graduation": True,
                                    "score": 80.0,
                                }
                            ],
                            "adapter_case_scores": [
                                {
                                    "case_id": "case-1",
                                    "category": "style_transfer",
                                    "owner": "adapter",
                                    "counts_toward_graduation": True,
                                    "score": 87.0,
                                }
                            ],
                            "evaluation_plan": {"case_count": 1},
                            "benchmark_report": {
                                "case_count": 1,
                                "scored_case_count": 1,
                                "overall": {"retrieval_only_score": 80.0, "adapter_score": 87.0},
                                "graduation_overall": {"retrieval_only_score": 80.0, "adapter_score": 87.0},
                                "category_scores": {
                                    "style_transfer": {
                                        "owner": "adapter",
                                        "counts_toward_graduation": True,
                                        "case_count": 1,
                                        "retrieval_only_score": 80.0,
                                        "adapter_score": 87.0,
                                        "quality_delta": 7.0,
                                        "passes": True,
                                    }
                                },
                                "bundle_benchmark_summary": {
                                    "retrieval_only_full_score": 83.0,
                                    "retrieval_only_small_score": 71.0,
                                    "bundle_with_expert_score": 87.0,
                                    "bundle_without_expert_score": 83.0,
                                    "passes": True,
                                },
                                "bundle_release_gate": {
                                    "passes": True,
                                    "quality_regression_vs_retrieval_full": -4.0,
                                    "quality_gain_vs_retrieval_small": 16.0,
                                    "token_savings_vs_retrieval_full": 42.0,
                                    "unsupported_claim_rate": 0.0,
                                    "wrong_citation_rate": 0.0,
                                },
                                "bundle_benchmark_modes": {
                                    "retrieval_only_full": {"score": 83.0, "token_count": 1000},
                                    "retrieval_only_small": {"score": 71.0, "token_count": 400},
                                    "bundle_with_expert": {"score": 87.0, "token_count": 580},
                                    "bundle_without_expert": {"score": 83.0, "token_count": 1000},
                                },
                                "bundle_category_scores": {
                                    "style_transfer": {
                                        "owner": "adapter",
                                        "counts_toward_graduation": True,
                                        "case_count": 1,
                                        "meaningful_case_count_reached": False,
                                        "complete": True,
                                        "retrieval_only_full": {"score": 83.0, "token_count": 1000},
                                        "retrieval_only_small": {"score": 71.0, "token_count": 400},
                                        "bundle_with_expert": {
                                            "score": 87.0,
                                            "token_count": 580,
                                            "unsupported_claim_rate": 0.0,
                                            "wrong_citation_rate": 0.0,
                                        },
                                        "bundle_without_expert": {"score": 83.0, "token_count": 1000},
                                        "quality_regression_vs_retrieval_full": -4.0,
                                        "quality_gain_vs_retrieval_small": 16.0,
                                        "token_savings_vs_retrieval_full": 42.0,
                                    }
                                },
                                "bundle_case_outputs": {
                                    "bundle_with_expert": [
                                        {
                                            "case_id": "case-1",
                                            "response_text": "expert digest",
                                            "raw_packet_text": "Mode: bundle_with_expert\nPacket response:\nexpert digest",
                                            "expert_used": True,
                                            "adapter_prompt": "compress this",
                                            "adapter_raw_output": "expert digest",
                                            "token_ledger": {
                                                "prompt_tokens_estimate": 3,
                                                "retrieval_evidence_tokens_estimate": 4,
                                                "response_tokens_estimate": 2,
                                                "packet_tokens_estimate": 7,
                                                "total_tokens_estimate": 9,
                                            },
                                        }
                                    ]
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            trainer_state_path.write_text(
                json.dumps(
                    {
                        "best_metric": 0.1234,
                        "best_global_step": 12,
                        "best_model_checkpoint": "checkpoint-12",
                        "global_step": 15,
                        "epoch": 1.5,
                        "log_history": [
                            {"step": 10, "epoch": 1.0, "eval_loss": 0.2, "eval_runtime": 12.0},
                            {"step": 12, "epoch": 1.2, "eval_loss": 0.1234, "eval_runtime": 11.5},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--benchmark",
                    str(benchmark_path),
                    "--trainer-state",
                    str(trainer_state_path),
                    "--output-prefix",
                    str(output_prefix),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )

            output_manifest = json.loads(result.stdout)
            summary_path = Path(output_manifest["summary"])
            html_path = Path(output_manifest["index_html"])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")
            bundle_case_csv_path = Path(output_manifest["bundle_case_outputs_csv"])
            bundle_case_csv = bundle_case_csv_path.read_text(encoding="utf-8")
            bundle_category_csv_path = Path(output_manifest["bundle_category_scores_csv"])
            bundle_category_csv = bundle_category_csv_path.read_text(encoding="utf-8")

            self.assertEqual(summary["bundle_benchmark_summary"]["bundle_with_expert_score"], 87.0)
            self.assertEqual(summary["bundle_gate"]["token_savings_vs_retrieval_full"], 42.0)
            self.assertEqual(summary["bundle_mode_count"], 4)
            self.assertTrue(summary["compatibility_only"]["legacy_category_scores"])
            self.assertTrue(output_manifest["category_scores_csv"].endswith("-legacy-category-scores.csv"))
            self.assertTrue(output_manifest["bundle_category_scores_csv"].endswith("-bundle-category-scores.csv"))
            self.assertTrue(output_manifest["case_scores_csv"].endswith("-legacy-case-scores.csv"))
            self.assertTrue(output_manifest["bundle_case_outputs_csv"].endswith("-bundle-case-outputs.csv"))
            self.assertIn("Cluster Bundle Run Artifacts", html)
            self.assertIn("Bundle With Expert", html)
            self.assertIn("Quality Gain Vs Small", html)
            self.assertIn("Legacy Category Scores CSV", html)
            self.assertIn("Bundle Category Scores CSV", html)
            self.assertIn("Bundle Case Outputs CSV", html)
            self.assertIn("style_transfer", bundle_category_csv)
            self.assertIn("42.0", bundle_category_csv)
            self.assertIn("bundle_with_expert", bundle_case_csv)
            self.assertIn("compress this", bundle_case_csv)


if __name__ == "__main__":
    unittest.main()
