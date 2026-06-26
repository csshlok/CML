import unittest


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
        self.assertEqual(report["metadata"]["expert_objective_version"], "retrieval_grounded_compression_v1")

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


if __name__ == "__main__":
    unittest.main()
