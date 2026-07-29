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
        model_root = Path(self.tmp.name) / "imported-models"
        model_dir = model_root / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        payload = {"model_type": model_type, "_name_or_path": repo_hint}
        (model_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        return model_dir

    def _import_chat_checkpoint(
        self,
        model_name: str,
        *,
        model_type: str,
        repo_hint: str,
    ) -> dict:
        from backend.app.core.model_registry import import_model_checkpoint

        family = "qwen3-4b"
        normalized_hint = f"{model_type} {repo_hint}".lower()
        if "phi" in normalized_hint:
            family = "phi-4-mini-instruct"
        elif "gemma" in normalized_hint:
            family = "gemma-3-4b-it"
        model_root = Path(self.tmp.name) / "imported-models"
        model_root.mkdir(parents=True, exist_ok=True)
        model_path = model_root / f"{family}-q4_k_m.gguf"
        model_path.write_bytes(b"GGUF fixture")
        return import_model_checkpoint(
            model_path,
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

    def test_catalog_fallback_is_labeled_as_an_estimate_not_a_measurement(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence

        evidence = resolve_benchmark_evidence(
            {
                "id": "qwen3-4b-q4_k_m",
                "name": "Qwen3 4B Q4_K_M",
                "family": "qwen",
                "source_kind": "default_choice",
                "local_path": "",
                "compatibility": {},
            }
        )

        self.assertEqual(evidence["source"], "catalog_estimate")
        self.assertLessEqual(float(evidence["confidence"]), 0.5)
        self.assertIn("detected memory", evidence["detail"].lower())

    def test_benchmark_evidence_demotes_frozen_only_exact_match_when_newer_current_lineage_exists(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        bundle_path = Path(self.tmp.name) / "benchmarks-layered.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "layered-v1",
                    "models": {},
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

    def test_measurement_route_records_model_measurements_only(self) -> None:
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
        finally:
            client.close()
        payload = load_internal_benchmark_bundle()
        self.assertEqual(model_response.status_code, 200)
        self.assertIn("qwen3-4b-q4_k_m", payload["models"])

    def test_diagnostics_export_script_targets_preview_route_and_output_write(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "export-model-recommender-diagnostics.ps1").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:7343/api/v1", script)
        self.assertIn("CML_API_TOKEN", script)
        self.assertIn("x-cml-api-token", script)
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
                "compatibility": {"chat_role_accepted": True},
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
                "compatibility": {"chat_role_accepted": True},
            }
        ]
        with patch("backend.app.core.model_recommender.service.build_hardware_profile", return_value=profile), patch(
            "backend.app.core.model_recommender.service.discover_installed_models",
            return_value=empty_detected,
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

        self._import_chat_checkpoint("Qwen Chat", model_type="qwen2", repo_hint="Qwen/Qwen3-4B")
        self._import_chat_checkpoint("Phi Chat", model_type="phi3", repo_hint="microsoft/Phi-4-mini-instruct")
        self._import_chat_checkpoint("Gemma Chat", model_type="gemma3", repo_hint="google/gemma-3-4b-it")

        fixture_root = Path(__file__).resolve().parent / "fixtures" / "model_recommender_profiles"
        expectations = {
            "cpu-8gb-no-gpu": {"allowed_models": {"qwen3-4b-q4_k_m", "gemma-3-4b-it-q4_k_m", "phi-4-mini-instruct-q4_k_m"}, "low_confidence": False},
            "cpu-16gb-no-gpu": {"allowed_models": {"qwen3-8b-q4_k_m"}, "low_confidence": False},
            "nvidia-8gb": {"allowed_models": {"qwen3-8b-q4_k_m", "qwen3-4b-q4_k_m", "gemma-3-4b-it-q4_k_m"}, "low_confidence": False},
            "nvidia-16gb": {"allowed_models": {"qwen3-8b-q4_k_m", "gemma-3-12b-it-q4_k_m"}, "low_confidence": False},
            "nvidia-24gb": {"allowed_models": {"gemma-3-12b-it-q4_k_m", "qwen3-8b-q4_k_m"}, "low_confidence": False},
            "runtime-missing-no-avx2": {"allowed_models": {"qwen3-4b-q4_k_m", "gemma-3-4b-it-q4_k_m", "phi-4-mini-instruct-q4_k_m"}, "low_confidence": True},
        }

        for fixture_path in sorted(fixture_root.glob("*.json")):
            profile = json.loads(fixture_path.read_text(encoding="utf-8"))
            result = build_model_recommendations(hardware_profile_override=profile)
            expectation = expectations[fixture_path.stem]
            self.assertIn(result["recommended_chat_model_id"], expectation["allowed_models"], fixture_path.stem)
            self.assertTrue(result["recommended_chat_model_id"], fixture_path.stem)
            self.assertIn(result["chat_fit_type"], {"full_gpu", "partial_offload", "cpu_only"}, fixture_path.stem)
            if expectation["low_confidence"]:
                self.assertEqual(result["confidence"], "low", fixture_path.stem)

    def test_imported_checkpoint_can_participate_in_chat_recommendation(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations

        self._import_chat_checkpoint("Qwen Chat", model_type="qwen2", repo_hint="Qwen/Qwen3-4B")
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

        self.assertTrue(result["recommended_chat_model_id"])
        self.assertIn("recommended_chat_model_id", result)

    def test_measurement_campaign_script_runs_recommendation_measurement_and_diagnostics_flow(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "run-model-recommender-measurement-campaign.ps1").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:7343/api/v1", script)
        self.assertIn("CML_API_TOKEN", script)
        self.assertIn("x-cml-api-token", script)
        self.assertIn("/models/recommendations?refresh=", script)
        self.assertIn("/models/recommendations/measurements/run", script)
        self.assertIn("/models/recommendations/diagnostics?refresh=true", script)
        self.assertIn("recommended_chat_model_id", script)

    def test_local_audit_script_exports_direct_backend_recommender_state(self) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts" / "backend" / "export-local-model-recommender-audit.ps1").read_text(encoding="utf-8")
        self.assertIn("model_recommendations", script)
        self.assertIn("export_recommendation_diagnostics", script)
        self.assertIn(".venv\\Scripts\\python.exe", script)


if __name__ == "__main__":
    unittest.main()
