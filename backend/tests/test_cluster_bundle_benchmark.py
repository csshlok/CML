import unittest
import json
import tempfile
from pathlib import Path

from backend.app.core.expert_contract import EXPERT_OBJECTIVE_VERSION


class ClusterBundleBenchmarkTests(unittest.TestCase):
    def test_bundle_benchmark_report_exposes_bundle_modes_and_gate(self) -> None:
        from backend.app.core.expert_evaluation import build_expert_benchmark_report

        evaluation_plan = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "cases": [
                {
                    "id": "case-1",
                    "category": "style_transfer",
                    "owner": "adapter",
                    "counts_toward_graduation": True,
                },
                {
                    "id": "case-2",
                    "category": "citation_grounding",
                    "owner": "retrieval",
                    "counts_toward_graduation": False,
                },
            ],
        }
        report = build_expert_benchmark_report(
            evaluation_plan,
            retrieval_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 90.0, "grounding_consistency_score": 1.0, "citation_present": False},
                {"case_id": "case-2", "category": "citation_grounding", "owner": "retrieval", "counts_toward_graduation": False, "score": 100.0, "grounding_consistency_score": 1.0, "citation_present": True},
            ],
            retrieval_small_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 60.0, "grounding_consistency_score": 1.0, "citation_present": False},
                {"case_id": "case-2", "category": "citation_grounding", "owner": "retrieval", "counts_toward_graduation": False, "score": 70.0, "grounding_consistency_score": 1.0, "citation_present": True},
            ],
            adapter_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 88.0, "grounding_consistency_score": 1.0, "citation_present": False},
                {"case_id": "case-2", "category": "citation_grounding", "owner": "retrieval", "counts_toward_graduation": False, "score": 100.0, "grounding_consistency_score": 1.0, "citation_present": True},
            ],
            wrong_adapter_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 78.0, "grounding_consistency_score": 1.0, "citation_present": False},
                {"case_id": "case-2", "category": "citation_grounding", "owner": "retrieval", "counts_toward_graduation": False, "score": 100.0, "grounding_consistency_score": 1.0, "citation_present": True},
            ],
            retrieval_runtime={
                "responses": [
                    {
                        "prompt": "full prompt 1",
                        "response_text": "full retrieval response " * 20,
                        "citations": [{"source_id": "s1", "title": "Source 1", "snippet": "Evidence snippet one."}],
                    },
                    {
                        "prompt": "full prompt 2",
                        "response_text": "full retrieval response " * 10,
                        "citations": [{"source_id": "s2", "title": "Source 2", "snippet": "Evidence snippet two."}],
                    },
                ]
            },
            retrieval_small_runtime={
                "responses": [
                    {
                        "prompt": "small prompt 1",
                        "response_text": "small retrieval response " * 6,
                        "citations": [{"source_id": "s1", "title": "Source 1", "snippet": "Small evidence one."}],
                    },
                    {
                        "prompt": "small prompt 2",
                        "response_text": "small retrieval response " * 4,
                        "citations": [{"source_id": "s2", "title": "Source 2", "snippet": "Small evidence two."}],
                    },
                ]
            },
            adapter_runtime={
                "responses": [
                    {
                        "prompt": "expert prompt 1",
                        "response_text": "expert digest response " * 5,
                        "citations": [{"source_id": "s1", "title": "Source 1", "snippet": "Expert evidence one."}],
                    },
                    {
                        "prompt": "expert prompt 2",
                        "response_text": "expert digest response " * 3,
                        "citations": [{"source_id": "s2", "title": "Source 2", "snippet": "Expert evidence two."}],
                    },
                ]
            },
        )

        self.assertIn("benchmark_modes", report)
        self.assertIn("bundle_with_expert", report["benchmark_modes"])
        self.assertIn("retrieval_only_small", report["benchmark_modes"])
        self.assertIn("legacy_category_gate_report", report)
        self.assertIn("bundle_benchmark_summary", report)
        self.assertIn("behavior_specialization_summary", report)
        self.assertIn("behavior_specialization_gate", report)
        self.assertIn("bundle_release_gate", report)
        self.assertIn("bundle_readiness", report)
        self.assertIn("bundle_mode_coverage", report)
        self.assertIn("bundle_benchmark_modes", report)
        self.assertIn("bundle_category_scores", report)
        self.assertIn("bundle_case_outputs", report)
        self.assertIn("quality_gain_vs_retrieval_small", report["gate_report"])
        self.assertIn("token_savings_vs_retrieval_full", report["gate_report"])
        self.assertEqual(report["bundle_release_gate"]["passes"], report["gate_report"]["passes"])
        self.assertIn("bundle_with_expert_score", report["bundle_benchmark_summary"])
        self.assertEqual(report["behavior_specialization_summary"]["behavior_lift_vs_retrieval_full"], -2.0)
        self.assertEqual(report["behavior_specialization_summary"]["behavior_separation_vs_wrong_adapter"], 10.0)
        self.assertTrue(report["behavior_specialization_gate"]["checks"]["behavior_separation_vs_wrong_adapter"])
        self.assertIsInstance(report["bundle_readiness"]["failure_reasons"], list)
        self.assertTrue(report["bundle_mode_coverage"]["passes"])
        self.assertIn("mode_case_outputs", report)
        self.assertIn("bundle_with_expert", report["mode_case_outputs"])
        self.assertEqual(report["mode_case_outputs"]["bundle_with_expert"][0]["case_id"], "case-1")
        self.assertEqual(report["bundle_case_outputs"]["bundle_with_expert"][0]["case_id"], "case-1")
        style_transfer = report["bundle_category_scores"]["style_transfer"]
        self.assertEqual(style_transfer["bundle_with_expert"]["score"], 88.0)
        self.assertEqual(style_transfer["retrieval_only_small"]["score"], 60.0)
        self.assertEqual(style_transfer["quality_regression_vs_retrieval_full"], 2.0)
        self.assertEqual(style_transfer["quality_gain_vs_retrieval_small"], 28.0)
        self.assertTrue(style_transfer["complete"])
        bundle_case = report["bundle_case_outputs"]["bundle_with_expert"][0]
        self.assertTrue(bundle_case["expert_used"])
        self.assertEqual(bundle_case["adapter_prompt"], bundle_case["runtime_prompt"])
        self.assertEqual(bundle_case["adapter_raw_output"], bundle_case["response_text"])
        self.assertIn("raw_packet_text", bundle_case)
        self.assertIn("Retrieval evidence:", report["bundle_case_outputs"]["retrieval_only_full"][1]["raw_packet_text"])
        self.assertIn("token_ledger", bundle_case)
        self.assertGreater(bundle_case["token_ledger"]["packet_tokens_estimate"], 0)
        self.assertEqual(report["metadata"]["expert_objective_version"], EXPERT_OBJECTIVE_VERSION)

    def test_bundle_quality_gate_fails_on_unsupported_claim_rate(self) -> None:
        from backend.app.core.expert_evaluation import _bundle_quality_gate

        gate = _bundle_quality_gate(
            {
                "retrieval_only_full": {"score": 90.0, "token_count": 1000},
                "retrieval_only_small": {"score": 70.0, "token_count": 300},
                "bundle_with_expert": {
                    "score": 88.0,
                    "token_count": 500,
                    "unsupported_claim_rate": 0.1,
                    "wrong_citation_rate": 0.0,
                },
                "bundle_without_expert": {"score": 90.0, "token_count": 1000},
            }
        )

        self.assertFalse(gate["passes"])
        self.assertFalse(gate["checks"]["unsupported_claim_rate"])

    def test_bundle_readiness_fails_when_required_modes_are_incomplete(self) -> None:
        from backend.app.core.expert_evaluation import build_expert_benchmark_report

        evaluation_plan = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "cases": [
                {
                    "id": "case-1",
                    "category": "style_transfer",
                    "owner": "adapter",
                    "counts_toward_graduation": True,
                }
            ],
        }
        report = build_expert_benchmark_report(
            evaluation_plan,
            retrieval_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 90.0}
            ],
            retrieval_small_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 70.0}
            ],
            adapter_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 88.0}
            ],
            retrieval_runtime={"responses": [{"response_text": "retrieval response"}]},
            retrieval_small_runtime={"responses": [{"response_text": "small retrieval response"}]},
            adapter_runtime={"responses": []},
        )

        self.assertFalse(report["passes"])
        self.assertIn("incomplete_bundle_modes", report["bundle_readiness"]["failure_reasons"])
        self.assertFalse(report["bundle_mode_coverage"]["passes"])
        self.assertIn("bundle_with_expert", report["bundle_mode_coverage"]["incomplete_modes"])

    def test_behavior_specialization_gate_blocks_report_without_wrong_adapter_baseline(self) -> None:
        from backend.app.core.expert_evaluation import build_expert_benchmark_report

        evaluation_plan = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "cases": [
                {
                    "id": "case-1",
                    "category": "style_transfer",
                    "owner": "adapter",
                    "counts_toward_graduation": True,
                }
            ],
        }
        report = build_expert_benchmark_report(
            evaluation_plan,
            retrieval_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 80.0}
            ],
            retrieval_small_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 60.0}
            ],
            adapter_case_scores=[
                {"case_id": "case-1", "category": "style_transfer", "owner": "adapter", "counts_toward_graduation": True, "score": 90.0}
            ],
            retrieval_runtime={"responses": [{"response_text": "retrieval response"}]},
            retrieval_small_runtime={"responses": [{"response_text": "small retrieval response"}]},
            adapter_runtime={"responses": [{"response_text": "adapter response"}]},
        )

        self.assertFalse(report["passes"])
        self.assertFalse(report["behavior_specialization_gate"]["passes"])
        self.assertFalse(report["behavior_specialization_gate"]["checks"]["wrong_adapter_baseline_present"])
        self.assertIn("wrong_adapter_baseline_present", report["bundle_readiness"]["failure_reasons"])

    def test_build_heldout_bundle_evaluation_dataset_uses_validation_sources_and_qa(self) -> None:
        from backend.app.core.expert_evaluation import build_expert_evaluation_plan, build_heldout_bundle_evaluation_dataset

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "dataset-manifest.json").write_text(json.dumps({"dataset_hash": "heldout-hash"}), encoding="utf-8")
            (root / "validation-sources.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source_id": "source-1",
                                "title": "Normans",
                                "summary": "The Normans gave their name to Normandy in France.",
                                "text": "The Normans gave their name to Normandy in France. They were descended from Norse raiders.",
                                "content_hash": "hash-1",
                            }
                        ),
                        json.dumps(
                            {
                                "source_id": "source-2",
                                "title": "Miss Marple",
                                "summary": "Miss Marple is a fictional detective by Agatha Christie.",
                                "text": "Miss Marple is a fictional detective by Agatha Christie who lives in St. Mary Mead.",
                                "content_hash": "hash-2",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "validation-qa.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "qa_id": "qa-1",
                                "title": "Normans",
                                "question": "In what country is Normandy located?",
                                "context": "Normandy is a region in France.",
                                "answers": ["France"],
                                "answer": "France",
                                "is_impossible": False,
                            }
                        ),
                        json.dumps(
                            {
                                "qa_id": "qa-2",
                                "title": "Normans",
                                "question": "What color was the mayor's hat?",
                                "context": "Normandy is a region in France.",
                                "answers": [],
                                "answer": "",
                                "is_impossible": True,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            dataset = build_heldout_bundle_evaluation_dataset(root, cluster_id="cluster-1", max_cases=8)
            assert dataset is not None
            plan = build_expert_evaluation_plan(dataset, max_cases=8)

        self.assertEqual(dataset["dataset_hash"], "heldout-hash")
        self.assertEqual(plan["case_count"], 8)
        categories = {case["category"] for case in plan["cases"]}
        self.assertIn("factual_recall", categories)
        self.assertIn("citation_grounding", categories)
        self.assertIn("out_of_scope_refusal", categories)


if __name__ == "__main__":
    unittest.main()
