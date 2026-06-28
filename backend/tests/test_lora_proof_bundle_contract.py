import json
import tempfile
import unittest
from pathlib import Path

from backend.app.core.expert_contract import EXPERT_OBJECTIVE_VERSION


class LoraProofBundleContractTests(unittest.TestCase):
    def test_smoke_proof_prefers_bundle_benchmark_contract(self) -> None:
        from backend.app.core.lora_proof import build_lora_smoke_proof

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            adapter_dir = tmp_path / "adapter"
            base_dir = tmp_path / "base-model"
            adapter_dir.mkdir()
            base_dir.mkdir()
            (base_dir / "config.json").write_text('{"model_type":"qwen2","architectures":["Qwen2ForCausalLM"]}', encoding="utf-8")
            (base_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
            (adapter_dir / "adapter_config.json").write_text(
                json.dumps(
                    {
                        "peft_type": "LORA",
                        "task_type": "CAUSAL_LM",
                        "base_model_name_or_path": str(base_dir),
                        "target_modules": ["q_proj", "v_proj"],
                    }
                ),
                encoding="utf-8",
            )
            (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

            report = {
                "mode": "real_local_lora_smoke",
                "used_synthetic_sources": False,
                "source_records": [{"title": "real", "path": "docs/PROJECT_CONTEXT.md", "chars": 1000}],
                "dataset": {
                    "source_count": 1,
                    "unique_content_hash_count": 1,
                    "estimated_token_count": 250,
                    "dataset_hash": "hash",
                },
                "actual_hardware_status": {"avx2": True, "hardware_tier": "cpu_minimum_spec"},
                "hardware_status_used": {"avx2": True, "training_supported": True},
                "artifacts": [{"active": 1, "local_path": str(adapter_dir), "base_model": str(base_dir)}],
                "runtime_smoke": {"ok": True, "adapter_path": str(adapter_dir), "base_model": str(base_dir)},
                "benchmark_report": {
                    "passes": False,
                    "metadata": {"expert_objective_version": EXPERT_OBJECTIVE_VERSION},
                    "bundle_benchmark_summary": {
                        "retrieval_only_full_score": 98.33,
                        "retrieval_only_small_score": 72.0,
                        "bundle_with_expert_score": 41.67,
                        "bundle_without_expert_score": 98.33,
                    },
                    "bundle_release_gate": {
                        "passes": False,
                        "quality_regression_vs_retrieval_full": 56.66,
                        "quality_gain_vs_retrieval_small": -30.33,
                    },
                    "bundle_readiness": {
                        "status": "failed",
                        "passes": False,
                        "failure_reasons": ["quality_regression_vs_retrieval_full"],
                    },
                    "overall": {"retrieval_only_score": 98.33, "adapter_score": 41.67, "quality_delta": -56.66},
                },
            }

            proof = build_lora_smoke_proof(report)

            self.assertFalse(proof["public_gate"]["passes"])
            self.assertIn("expert_bundle_benchmark_failed", proof["public_gate"]["blocked_reasons"])
            self.assertEqual(proof["benchmark"]["baseline_score"], 98.33)
            self.assertEqual(proof["benchmark"]["bundle_with_expert_score"], 41.67)
            self.assertEqual(
                proof["benchmark"]["bundle_release_gate"]["quality_regression_vs_retrieval_full"],
                56.66,
            )
            self.assertEqual(
                proof["benchmark"]["bundle_readiness"]["failure_reasons"],
                ["quality_regression_vs_retrieval_full"],
            )


if __name__ == "__main__":
    unittest.main()
