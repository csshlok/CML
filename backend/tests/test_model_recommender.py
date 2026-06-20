import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ModelRecommenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_MODELS_DIR"] = str(Path(self.tmp.name) / "models")
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        invalidate_internal_benchmark_bundle_cache()
        get_settings.cache_clear()
        for key in [
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_MODELS_DIR",
            "CML_ALLOW_UNAUTHENTICATED_API",
            "CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE",
        ]:
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def _write_fake_local_transformers_model(
        self,
        model_name: str,
        *,
        model_type: str,
        repo_hint: str,
    ) -> Path:
        model_root = Path(self.tmp.name) / "expert-models"
        model_dir = model_root / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        payload = {"model_type": model_type, "_name_or_path": repo_hint}
        (model_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        return model_dir

    def _import_expert_checkpoint(
        self,
        model_name: str,
        *,
        model_type: str,
        repo_hint: str,
    ) -> dict:
        from backend.app.core.model_registry import import_model_checkpoint

        return import_model_checkpoint(
            self._write_fake_local_transformers_model(
                model_name,
                model_type=model_type,
                repo_hint=repo_hint,
            ),
            name=model_name,
        )

    def test_family_normalization_strips_packaging_noise(self) -> None:
        from backend.app.core.model_recommender.family import normalize_family_line, normalize_family_name

        self.assertEqual(normalize_family_line("Qwen3-8B-Instruct-Q4_K_M-GGUF"), "qwen3-8b-instruct-q4_k_m")
        self.assertEqual(normalize_family_name("Gemma-3-4B-it"), "gemma")

    def test_hardware_profile_marks_missing_runtime_and_no_gpu_conservatively(self) -> None:
        from backend.app.core.model_recommender.hardware_profile import build_hardware_profile

        hardware = {
            "os": "Windows",
            "machine": "AMD64",
            "processor": "CPU",
            "cpu_count": 4,
            "total_memory_bytes": 8 * 1024**3,
            "available_memory_bytes": 6 * 1024**3,
            "usable_memory_bytes": 6 * 1024**3,
            "disk_free_bytes": 20 * 1024**3,
            "avx2": True,
            "avx512": False,
            "hardware_tier": "cpu_minimum_spec",
            "training_supported": True,
            "warnings": [],
            "gpus": [],
        }
        runtime = {
            "provider": "none",
            "base_url": "",
            "available": False,
            "detail": "Missing.",
        }
        with patch("backend.app.core.model_recommender.hardware_profile.hardware_status", return_value=hardware), patch(
            "backend.app.core.model_recommender.hardware_profile.runtime_status",
            return_value=runtime,
        ):
            profile = build_hardware_profile()

        self.assertEqual(profile["runtime_backend"], "none")
        self.assertFalse(profile["runtime_detected"])
        self.assertEqual(profile["detection_confidence"], "medium")

    def test_chat_fit_rejects_borderline_insufficient_disk(self) -> None:
        from backend.app.core.model_recommender.fit import estimate_chat_fit

        profile = {
            "ram_usable_bytes": 10 * 1024**3,
            "disk_free_bytes": 1 * 1024**3,
            "hardware_tier": "cpu_high_spec",
            "gpus": [],
        }
        candidate = {
            "estimated_weight_bytes": int(2.5 * 1024**3),
            "parameter_count_total_b": 4.0,
            "minimum_chat_tier": "cpu_minimum_spec",
        }
        fit = estimate_chat_fit(profile, candidate)
        self.assertFalse(fit["feasible"])
        self.assertEqual(fit["fit_type"], "cannot_run")
        self.assertTrue(any("disk" in warning.lower() for warning in fit["warnings"]))

    def test_expert_fit_blocks_when_no_avx2_support(self) -> None:
        from backend.app.core.model_recommender.fit import estimate_expert_fit

        profile = {
            "ram_usable_bytes": 24 * 1024**3,
            "training_supported": False,
            "hardware_tier": "cpu_high_spec",
        }
        candidate = {
            "family": "qwen",
            "local_path": "C:\\model",
            "parameter_count_total_b": 4.0,
            "minimum_expert_tier": "cpu_minimum_spec",
            "compatibility": {"expert_role_accepted": True},
        }
        fit = estimate_expert_fit(profile, candidate)
        self.assertFalse(fit["training_feasible"])
        self.assertEqual(fit["training_fit_type"], "blocked")
        self.assertTrue(any("avx2" in warning.lower() for warning in fit["warnings"]))

    def test_speed_estimate_marks_shared_memory_apu_as_degraded(self) -> None:
        from backend.app.core.model_recommender.speed import estimate_chat_speed

        profile = {
            "gpus": [
                {
                    "vendor": "amd",
                    "usable_vram_bytes": 8 * 1024**3,
                    "vram_bytes": 8 * 1024**3,
                    "memory_bandwidth_gbps": 120.0,
                    "shared_memory": True,
                }
            ]
        }
        candidate = {
            "quantization": "Q4_K_M",
            "estimated_weight_bytes": int(2.5 * 1024**3),
            "parameter_count_total_b": 4.0,
        }
        fit = {"fit_type": "partial_offload"}
        speed = estimate_chat_speed(profile, candidate, fit)
        self.assertIn("thresholds", speed)
        self.assertIn("notes", speed)
        self.assertTrue(any("shared-memory" in note.lower() for note in speed["notes"]))

    def test_pair_gate_rejects_supported_pair_on_unsupported_tier(self) -> None:
        from backend.app.core.model_recommender.pairing import resolve_pair_recommendation

        pair = resolve_pair_recommendation(
            {"hardware_tier": "cpu_minimum_spec"},
            {"id": "gemma-3-12b-it-q4_k_m"},
            {"id": "gemma-local", "family": "gemma"},
        )
        self.assertFalse(pair["accepted"])
        self.assertIn("hardware", pair["detail"].lower())

    def test_explanations_include_evidence_and_limiting_factor(self) -> None:
        from backend.app.core.model_recommender.explanations import build_chat_reasons

        reasons = build_chat_reasons(
            {"id": "qwen3-4b-q4_k_m"},
            {"fit_type": "cpu_only"},
            {"estimated_tok_per_sec": 1.8},
            {"source": "base_model", "detail": "Inherited benchmark from approved family line."},
        )
        self.assertTrue(any("base_model" in reason for reason in reasons))
        self.assertTrue(any("cpu-first fallback" in reason.lower() for reason in reasons))

    def test_diagnostics_export_includes_bundle_and_recommendation_snapshot(self) -> None:
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache
        from backend.app.core.model_recommender.diagnostics import export_recommendation_diagnostics

        bundle_path = Path(self.tmp.name) / "benchmarks.json"
        bundle_path.write_text(
            json.dumps({"version": "diag-v1", "models": {}, "pairs": {}, "current_sources": {}, "frozen_sources": {}}),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE"] = str(bundle_path)
        invalidate_internal_benchmark_bundle_cache()

        with patch(
            "backend.app.core.model_recommender.diagnostics.build_model_recommendations",
            return_value={
                "catalog_version": "cml-recommender-v1",
                "benchmark_bundle_version": "diag-v1",
                "hardware": {"hardware_tier": "cpu_minimum_spec"},
                "recommended_chat_model_id": "qwen3-4b-q4_k_m",
                "chat_recommendation": {
                    "id": "qwen3-4b-q4_k_m",
                    "name": "Qwen3 4B Q4_K_M",
                    "fit": {"fit_type": "cpu_only", "feasible": True, "required_gib": 5.2, "warnings": []},
                    "speed": {"estimated_tok_per_sec": 2.1, "thresholds": {"acceptable_for_chat": False}, "notes": []},
                },
                "expert_recommendation": {},
                "pair_recommendation": {},
                "candidate_table": [],
            },
        ):
            payload = export_recommendation_diagnostics()

        self.assertEqual(payload["benchmark_bundle"]["version"], "diag-v1")
        self.assertEqual(payload["recommendation"]["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertIn("generated_at", payload)
        self.assertIn("fit_speed_report", payload)
        self.assertEqual(payload["fit_speed_report"]["recommended_chat"]["estimated_speed_band"], "degraded")
        self.assertIn("calibration_summary", payload)

    def test_diagnostics_export_reports_speed_and_fit_mismatch_rates_from_measurements(self) -> None:
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache
        from backend.app.core.model_recommender.diagnostics import export_recommendation_diagnostics

        bundle_path = Path(self.tmp.name) / "benchmarks-calibration.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "diag-v2",
                    "models": {
                        "qwen3-4b-q4_k_m": {
                            "estimated_tok_per_sec": 7.5,
                            "runtime_success": True,
                            "measured_at": "2026-06-20T00:00:00Z",
                        },
                        "phi-4-mini-instruct-q4_k_m": {
                            "estimated_tok_per_sec": 0.9,
                            "runtime_success": False,
                            "measured_at": "2026-06-20T00:00:00Z",
                        },
                    },
                    "pairs": {
                        "pair-qwen3-4b-qwen": {
                            "runtime_success": True,
                            "training_success": True,
                            "chat_tok_per_sec": 7.2,
                            "measured_at": "2026-06-20T00:00:00Z",
                        }
                    },
                    "current_sources": {},
                    "frozen_sources": {},
                }
            ),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE"] = str(bundle_path)
        invalidate_internal_benchmark_bundle_cache()

        recommendation = {
            "catalog_version": "cml-recommender-v1",
            "benchmark_bundle_version": "diag-v2",
            "hardware": {
                "hardware_tier": "cpu_minimum_spec",
                "detection_confidence": "high",
                "runtime_backend": "llama_cpp_compatible",
            },
            "recommended_chat_model_id": "qwen3-4b-q4_k_m",
            "recommended_pair_id": "pair-qwen3-4b-qwen",
            "chat_recommendation": {
                "id": "qwen3-4b-q4_k_m",
                "name": "Qwen3 4B Q4_K_M",
                "fit": {"fit_type": "cpu_only", "feasible": True, "required_gib": 5.2, "warnings": []},
                "speed": {"estimated_tok_per_sec": 4.5, "thresholds": {"acceptable_for_chat": True}, "notes": []},
            },
            "expert_recommendation": {},
            "pair_recommendation": {"pair_id": "pair-qwen3-4b-qwen", "accepted": True},
            "candidate_table": [
                {
                    "candidate_id": "qwen3-4b-q4_k_m",
                    "role": "chat",
                    "fit_type": "cpu_only",
                    "estimated_tok_per_sec": 4.5,
                },
                {
                    "candidate_id": "phi-4-mini-instruct-q4_k_m",
                    "role": "chat",
                    "fit_type": "cpu_only",
                    "estimated_tok_per_sec": 2.4,
                },
            ],
        }

        with patch("backend.app.core.model_recommender.diagnostics.build_model_recommendations", return_value=recommendation):
            payload = export_recommendation_diagnostics()

        calibration = payload["calibration_summary"]
        self.assertEqual(calibration["measured_model_count"], 2)
        self.assertEqual(calibration["measured_pair_count"], 1)
        self.assertEqual(calibration["speed_band_match_rate"], 0.5)
        self.assertEqual(calibration["fit_mismatch_rate"], 0.5)
        self.assertEqual(calibration["recommended_pair_calibration"]["measured_speed_band"], "acceptable")

    def test_benchmark_store_can_record_model_and_pair_measurements(self) -> None:
        from backend.app.core.model_recommender.benchmark_store import (
            load_internal_benchmark_bundle,
            record_model_measurement,
            record_pair_measurement,
        )

        model_record = record_model_measurement(
            "qwen3-4b-q4_k_m",
            score=87.5,
            estimated_tok_per_sec=8.4,
            startup_seconds=3.2,
            runtime_success=True,
            training_success=False,
            measured_at="2026-06-20T00:00:00Z",
        )
        pair_record = record_pair_measurement(
            "pair-qwen3-4b-qwen",
            runtime_success=True,
            training_success=True,
            chat_tok_per_sec=8.4,
            measured_at="2026-06-20T00:00:00Z",
        )
        payload = load_internal_benchmark_bundle()

        self.assertEqual(model_record["score"], 87.5)
        self.assertTrue(pair_record["runtime_success"])
        self.assertIn("qwen3-4b-q4_k_m", payload["models"])
        self.assertIn("pair-qwen3-4b-qwen", payload["pairs"])
        self.assertIn("current_sources", payload)
        self.assertIn("frozen_sources", payload)

    def test_benchmark_evidence_demotes_frozen_only_exact_match_when_newer_current_lineage_exists(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        bundle_path = Path(self.tmp.name) / "benchmarks-layered.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "layered-v1",
                    "models": {},
                    "pairs": {},
                    "current_sources": {
                        "qwen3-8b-base-public": {
                            "name": "Qwen3 8B Base Public",
                            "family": "qwen",
                            "family_line": "qwen3-8b",
                            "parameter_count_total_b": 8.0,
                            "runtime_format": "transformers",
                            "score": 79.0,
                            "updated_at": "2026-06-20",
                        }
                    },
                    "frozen_sources": {
                        "qwen3-8b-instruct": {
                            "name": "Qwen3 8B Instruct",
                            "family": "qwen",
                            "family_line": "qwen3-8b",
                            "parameter_count_total_b": 8.0,
                            "runtime_format": "transformers",
                            "score": 88.0,
                            "updated_at": "2025-10-01",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE"] = str(bundle_path)
        invalidate_internal_benchmark_bundle_cache()

        evidence = resolve_benchmark_evidence(
            {
                "id": "custom-qwen3-8b-instruct",
                "name": "Qwen3 8B Instruct",
                "family": "qwen",
                "source_kind": "custom_import",
                "local_path": str(Path(self.tmp.name) / "Qwen3-8B-Instruct"),
                "compatibility": {"accepted": True, "detail": "Accepted."},
            }
        )

        self.assertEqual(evidence["source"], "variant")
        self.assertIn("frozen-only", evidence["detail"].lower())
        self.assertLess(float(evidence["confidence"]), 0.55)

    def test_benchmark_evidence_rejects_family_inheritance_when_parameter_gap_is_too_large(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        bundle_path = Path(self.tmp.name) / "benchmarks-mismatch.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "mismatch-v1",
                    "models": {},
                    "pairs": {},
                    "current_sources": {
                        "qwen3-4b-q4_k_m": {
                            "name": "Qwen3 4B Q4_K_M",
                            "family": "qwen",
                            "family_line": "qwen3-4b",
                            "parameter_count_total_b": 4.0,
                            "runtime_format": "transformers",
                            "score": 72.0,
                            "updated_at": "2026-06-20",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE"] = str(bundle_path)
        invalidate_internal_benchmark_bundle_cache()

        evidence = resolve_benchmark_evidence(
            {
                "id": "custom-qwen3-32b-local",
                "name": "Qwen3 32B Local",
                "family": "qwen",
                "source_kind": "custom_import",
                "local_path": str(Path(self.tmp.name) / "Qwen3-32B-Local"),
                "compatibility": {"accepted": True, "detail": "Accepted."},
            }
        )

        self.assertEqual(evidence["source"], "self_reported")
        self.assertNotIn("base_model", evidence["detail"].lower())

    def test_every_approved_pair_accepts_at_minimum_tier_and_rejects_below_floor(self) -> None:
        from backend.app.core.model_recommender.catalog import approved_pairs, tier_rank
        from backend.app.core.model_recommender.pairing import resolve_pair_recommendation

        tiers = ["unsupported", "cpu_minimum_spec", "cpu_high_spec", "gpu_or_high_spec_candidate"]
        tier_by_rank = {tier_rank(tier): tier for tier in tiers}
        for spec in approved_pairs():
            accepted = resolve_pair_recommendation(
                {"hardware_tier": spec.minimum_hardware_tier},
                {"id": spec.chat_model_id},
                {"id": f"{spec.expert_family}-expert", "family": spec.expert_family},
            )
            self.assertTrue(accepted["accepted"], spec.pair_id)
            minimum_rank = tier_rank(spec.minimum_hardware_tier)
            if minimum_rank > 0:
                lower_tier = tier_by_rank[minimum_rank - 1]
                rejected = resolve_pair_recommendation(
                    {"hardware_tier": lower_tier},
                    {"id": spec.chat_model_id},
                    {"id": f"{spec.expert_family}-expert", "family": spec.expert_family},
                )
                self.assertFalse(rejected["accepted"], f"{spec.pair_id}:{lower_tier}")

    def test_measurement_route_records_model_and_pair_measurements(self) -> None:
        import backend.app.main as main_module
        from backend.app.core.config import get_settings
        from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle

        get_settings.cache_clear()
        client = TestClient(main_module.app)
        try:
            model_response = client.post(
                "/api/v1/models/recommendations/measurements",
                json={
                    "model_id": "qwen3-4b-q4_k_m",
                    "score": 86.5,
                    "estimated_tok_per_sec": 7.8,
                    "runtime_success": True,
                    "measured_at": "2026-06-20T00:00:00Z",
                },
            )
            pair_response = client.post(
                "/api/v1/models/recommendations/measurements",
                json={
                    "pair_id": "pair-qwen3-4b-qwen",
                    "estimated_tok_per_sec": 7.8,
                    "runtime_success": True,
                    "training_success": True,
                    "measured_at": "2026-06-20T00:00:00Z",
                },
            )
        finally:
            client.close()
        payload = load_internal_benchmark_bundle()
        self.assertEqual(model_response.status_code, 200)
        self.assertEqual(pair_response.status_code, 200)
        self.assertIn("qwen3-4b-q4_k_m", payload["models"])
        self.assertIn("pair-qwen3-4b-qwen", payload["pairs"])

    def test_measurement_script_targets_recommendation_measurement_route(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "record-model-recommender-measurement.ps1").read_text(encoding="utf-8")
        self.assertIn("/models/recommendations/measurements", script)
        self.assertIn("estimated_tok_per_sec", script)

    def test_runtime_measurement_script_targets_run_route(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "measure-model-recommender-runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("/models/recommendations/measurements/run", script)
        self.assertIn("adapter_path", script.lower())

    def test_diagnostics_export_script_targets_preview_route_and_output_write(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "export-model-recommender-diagnostics.ps1").read_text(encoding="utf-8")
        self.assertIn("/models/recommendations/diagnostics/preview", script)
        self.assertIn("Set-Content", script)

    def test_recommendation_snapshot_cache_obeys_refresh_and_input_fingerprint(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations

        profile = {
            "os": "Windows",
            "architecture": "AMD64",
            "cpu_name": "CPU",
            "cpu_threads": 8,
            "ram_total_bytes": 16 * 1024**3,
            "ram_available_bytes": 12 * 1024**3,
            "ram_usable_bytes": 12 * 1024**3,
            "disk_free_bytes": 64 * 1024**3,
            "has_avx2": True,
            "has_avx512": False,
            "hardware_tier": "cpu_high_spec",
            "training_supported": True,
            "runtime_provider": "openai",
            "runtime_backend": "llama_cpp_compatible",
            "runtime_base_url": "http://127.0.0.1:8080/v1",
            "runtime_detected": True,
            "runtime_detail": "Ready.",
            "detection_confidence": "high",
            "warnings": [],
            "gpus": [],
        }
        empty_detected = {"models": [], "compatible_model_count": 0}
        first_models = [
            {
                "id": "qwen3-4b-q4_k_m",
                "name": "Qwen3 4B Q4_K_M",
                "family": "qwen",
                "installed": False,
                "local_path": "",
                "source_kind": "default_choice",
                "active_chat": False,
                "active_expert": False,
                "compatibility": {"chat_role_accepted": True, "expert_role_accepted": False},
            }
        ]
        second_models = [
            {
                "id": "qwen3-8b-q4_k_m",
                "name": "Qwen3 8B Q4_K_M",
                "family": "qwen",
                "installed": False,
                "local_path": "",
                "source_kind": "default_choice",
                "active_chat": False,
                "active_expert": False,
                "compatibility": {"chat_role_accepted": True, "expert_role_accepted": False},
            }
        ]
        with patch("backend.app.core.model_recommender.service.build_hardware_profile", return_value=profile), patch(
            "backend.app.core.model_recommender.service.discover_installed_models",
            return_value=empty_detected,
        ), patch(
            "backend.app.core.model_recommender.service.active_model_pair_status",
            return_value={"accepted": False, "detail": "", "chat_model_id": "", "expert_model_id": ""},
        ), patch("backend.app.core.model_recommender.service.list_models", side_effect=[first_models, first_models, second_models]):
            first = build_model_recommendations(refresh=True)
            cached = build_model_recommendations()
            refreshed = build_model_recommendations(refresh=True)

        self.assertEqual(first["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertEqual(cached["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertEqual(refreshed["recommended_chat_model_id"], "qwen3-8b-q4_k_m")

    def test_measurement_run_route_records_chat_runtime_measurement(self) -> None:
        import backend.app.main as main_module
        from backend.app.core.config import get_settings
        from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle

        get_settings.cache_clear()
        client = TestClient(main_module.app)
        with patch("backend.app.core.model_recommender.measurement.runtime_status", return_value={"available": True}), patch(
            "backend.app.core.model_recommender.measurement.generate_direct_answer",
            return_value=type("R", (), {"text": "runtime working response", "provider": "test", "model": "qwen"})(),
        ):
            try:
                response = client.post(
                    "/api/v1/models/recommendations/measurements/run",
                    json={"model_id": "qwen3-4b-q4_k_m", "prompt": "test"},
                )
            finally:
                client.close()
        payload = load_internal_benchmark_bundle()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "chat_model")
        self.assertIn("qwen3-4b-q4_k_m", payload["models"])

    def test_measurement_run_route_records_pair_runtime_measurement(self) -> None:
        import backend.app.main as main_module
        from backend.app.core.config import get_settings
        from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle

        get_settings.cache_clear()
        client = TestClient(main_module.app)
        with patch("backend.app.core.model_recommender.measurement.runtime_status", return_value={"available": False}), patch(
            "backend.app.core.model_recommender.measurement.run_adapter_runtime_smoke",
            return_value={"ok": True, "response_text": "expert ok"},
        ):
            try:
                response = client.post(
                    "/api/v1/models/recommendations/measurements/run",
                    json={
                        "pair_id": "pair-qwen3-4b-qwen",
                        "adapter_path": "C:\\adapter",
                        "base_model": "Qwen/Qwen3-4B",
                        "prompt": "test",
                    },
                )
            finally:
                client.close()
        payload = load_internal_benchmark_bundle()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "approved_pair")
        self.assertIn("pair-qwen3-4b-qwen", payload["pairs"])

    def test_diagnostics_preview_route_uses_hardware_override_for_selected_machine_report(self) -> None:
        import backend.app.main as main_module
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        client = TestClient(main_module.app)
        try:
            response = client.post(
                "/api/v1/models/recommendations/diagnostics/preview",
                json={
                    "hardware": {
                        "hardware_tier": "gpu_or_high_spec_candidate",
                        "ram_total_bytes": 32 * 1024**3,
                        "ram_available_bytes": 28 * 1024**3,
                        "ram_usable_bytes": 28 * 1024**3,
                        "gpus": [
                            {
                                "vendor": "nvidia",
                                "name": "RTX Test",
                                "vram_bytes": 16 * 1024**3,
                                "usable_vram_bytes": 16 * 1024**3,
                                "shared_memory": False,
                                "memory_bandwidth_gbps": 500.0,
                                "driver_confidence": "high",
                            }
                        ],
                    }
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["hardware"]["hardware_tier"], "gpu_or_high_spec_candidate")
        self.assertEqual(payload["fit_speed_report"]["machine_profile"]["hardware_tier"], "gpu_or_high_spec_candidate")

    def test_recommendation_fixture_matrix_covers_representative_machine_classes(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations

        self._import_expert_checkpoint("Qwen Expert", model_type="qwen2", repo_hint="Qwen/Qwen3-4B")
        self._import_expert_checkpoint("Phi Expert", model_type="phi3", repo_hint="microsoft/Phi-4-mini-instruct")
        self._import_expert_checkpoint("Gemma Expert", model_type="gemma3", repo_hint="google/gemma-3-4b-it")

        fixture_root = Path(__file__).resolve().parent / "fixtures" / "model_recommender_profiles"
        expectations = {
            "cpu-8gb-no-gpu": {"allowed_pairs": {"pair-qwen3-4b-qwen", "pair-gemma3-4b-gemma", "pair-phi4-phi"}, "blocked_training": False},
            "cpu-16gb-no-gpu": {"allowed_pairs": {"pair-qwen3-8b-qwen"}, "blocked_training": False},
            "nvidia-8gb": {"allowed_pairs": {"pair-qwen3-8b-qwen", "pair-qwen3-4b-qwen", "pair-gemma3-4b-gemma"}, "blocked_training": False},
            "nvidia-16gb": {"allowed_pairs": {"pair-qwen3-8b-qwen", "pair-gemma3-12b-gemma"}, "blocked_training": False},
            "nvidia-24gb": {"allowed_pairs": {"pair-gemma3-12b-gemma", "pair-qwen3-8b-qwen"}, "blocked_training": False},
            "runtime-missing-no-avx2": {"allowed_pairs": {"pair-qwen3-4b-qwen", "pair-gemma3-4b-gemma", "pair-phi4-phi"}, "blocked_training": True},
        }

        for fixture_path in sorted(fixture_root.glob("*.json")):
            profile = json.loads(fixture_path.read_text(encoding="utf-8"))
            result = build_model_recommendations(hardware_profile_override=profile)
            expectation = expectations[fixture_path.stem]
            self.assertIn(result["recommended_pair_id"], expectation["allowed_pairs"], fixture_path.stem)
            self.assertTrue(result["recommended_chat_model_id"], fixture_path.stem)
            self.assertIn(result["chat_fit_type"], {"full_gpu", "partial_offload", "cpu_only"}, fixture_path.stem)
            if expectation["blocked_training"]:
                self.assertEqual(result["expert_training_fit_type"], "blocked", fixture_path.stem)
                self.assertEqual(result["confidence"], "low", fixture_path.stem)

    def test_matrix_script_targets_preview_route_and_iterates_json_profiles(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "evaluate-model-recommender-matrix.ps1").read_text(encoding="utf-8")
        self.assertIn("/models/recommendations/diagnostics/preview", script)
        self.assertIn("Get-ChildItem", script)
        self.assertIn("*.json", script)

    def test_expert_only_import_is_not_ranked_as_chat_recommendation(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations

        self._import_expert_checkpoint("Qwen Expert", model_type="qwen2", repo_hint="Qwen/Qwen3-4B")
        profile = {
            "os": "Windows",
            "architecture": "AMD64",
            "cpu_name": "Fixture CPU",
            "cpu_threads": 8,
            "ram_total_bytes": 16 * 1024**3,
            "ram_available_bytes": 12 * 1024**3,
            "ram_usable_bytes": 12 * 1024**3,
            "disk_free_bytes": 64 * 1024**3,
            "has_avx2": True,
            "has_avx512": False,
            "hardware_tier": "cpu_minimum_spec",
            "training_supported": True,
            "runtime_provider": "openai",
            "runtime_backend": "llama_cpp_compatible",
            "runtime_base_url": "http://127.0.0.1:8080/v1",
            "runtime_detected": True,
            "runtime_detail": "Fixture runtime available.",
            "detection_confidence": "high",
            "warnings": [],
            "gpus": [],
        }

        result = build_model_recommendations(hardware_profile_override=profile)

        self.assertNotEqual(result["recommended_chat_model_id"], "custom-qwen-expert")
        self.assertEqual(result["recommended_pair_id"], "pair-qwen3-4b-qwen")

    def test_measurement_campaign_script_runs_recommendation_measurement_and_diagnostics_flow(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "run-model-recommender-measurement-campaign.ps1").read_text(encoding="utf-8")
        self.assertIn("/models/recommendations?refresh=", script)
        self.assertIn("/models/recommendations/measurements/run", script)
        self.assertIn("/models/recommendations/diagnostics?refresh=true", script)
        self.assertIn("recommended_chat_model_id", script)
        self.assertIn("recommended_pair_id", script)

    def test_local_audit_script_exports_direct_backend_recommender_state(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "export-local-model-recommender-audit.ps1").read_text(encoding="utf-8")
        self.assertIn("model_recommendations", script)
        self.assertIn("export_recommendation_diagnostics", script)
        self.assertIn(".venv\\Scripts\\python.exe", script)


if __name__ == "__main__":
    unittest.main()
