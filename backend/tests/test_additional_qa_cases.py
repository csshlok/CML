import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from fastapi.testclient import TestClient


class AdditionalQACases(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_MODELS_DIR"] = str(Path(self.tmp.name) / "models")
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import invalidate_model_discovery_cache
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        get_settings.cache_clear()
        invalidate_model_discovery_cache()
        invalidate_internal_benchmark_bundle_cache()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        os.environ.pop("CML_ALLOW_UNAUTHENTICATED_API", None)
        os.environ.pop("CML_LORA_MIN_QUALITY_DELTA", None)
        os.environ.pop("CML_LORA_MIN_UNIQUE_SOURCES", None)
        os.environ.pop("CML_LORA_MAX_DUPLICATE_RATIO", None)
        os.environ.pop("CML_LORA_MODEL_DIRS", None)
        os.environ.pop("CML_LORA_RUNTIME_PYTHON", None)
        os.environ.pop("CML_LORA_RUNTIME_DEVICE", None)
        os.environ.pop("CML_LORA_RUNTIME_DTYPE", None)
        os.environ.pop("CML_LORA_RUNTIME_REPETITION_PENALTY", None)
        os.environ.pop("CML_LORA_RUNTIME_NO_REPEAT_NGRAM_SIZE", None)
        os.environ.pop("CML_LORA_TRAINING_DEVICE", None)
        os.environ.pop("CML_LORA_TRAINING_DTYPE", None)
        os.environ.pop("CML_MODEL_SCAN_ROOTS", None)
        os.environ.pop("CML_MODEL_SCAN_CACHE_SECONDS", None)
        os.environ.pop("CML_MODELS_DIR", None)
        os.environ.pop("CML_LLM_MODEL", None)
        os.environ.pop("CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE", None)
        self.tmp.cleanup()

    def _write_fake_local_transformers_model(
        self,
        model_name: str = "test-base-model",
        *,
        model_type: str = "qwen2",
        repo_hint: str | None = None,
    ) -> Path:
        model_root = Path(self.tmp.name) / "models"
        model_dir = model_root / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        payload = {"model_type": model_type, "_name_or_path": repo_hint or f"Qwen/{model_name}"}
        (model_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        os.environ["CML_LORA_MODEL_DIRS"] = str(model_root)
        os.environ["CML_LLM_MODEL"] = model_name
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        return model_dir

    def _install_default_chat_model(self, model_id: str = "qwen3-4b-q4_k_m") -> Path:
        model_dir = Path(self.tmp.name) / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        gguf_path = model_dir / "qwen3-4b-q4_k_m.gguf"
        gguf_path.write_bytes(b"gguf")
        return gguf_path

    def test_model_compatibility_report_accepts_supported_transformers_checkpoint(self) -> None:
        from backend.app.core.model_registry import model_compatibility_report

        model_dir = self._write_fake_local_transformers_model(
            "accepted-qwen",
            model_type="qwen2",
            repo_hint="Qwen/Qwen3-4B",
        )

        report = model_compatibility_report(model_dir)

        self.assertTrue(report["accepted"])
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["family"], "qwen")

    def test_model_compatibility_report_rejects_non_checkpoint_path(self) -> None:
        from backend.app.core.model_registry import model_compatibility_report

        file_path = Path(self.tmp.name) / "model.gguf"
        file_path.write_bytes(b"gguf")

        report = model_compatibility_report(file_path)

        self.assertFalse(report["accepted"])
        self.assertEqual(report["status"], "rejected")
        self.assertIn("checkpoint directory", report["detail"].lower())

    def test_import_and_activate_custom_model(self) -> None:
        from backend.app.core.model_registry import (
            active_chat_model_status,
            active_expert_model_status,
            import_model_checkpoint,
            set_active_model,
        )

        self._install_default_chat_model()
        set_active_model("qwen3-4b-q4_k_m", role="chat")

        imported = import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "custom-gemma",
                model_type="gemma3",
                repo_hint="google/gemma-3-4b-it",
            ),
            name="Gemma Local",
        )

        self.assertEqual(imported["source_kind"], "custom_import")
        self.assertTrue(imported["compatibility"]["accepted"])
        self.assertEqual(active_chat_model_status()["id"], "qwen3-4b-q4_k_m")
        self.assertEqual(active_expert_model_status()["id"], imported["id"])

        activated = set_active_model(imported["id"], role="expert")
        self.assertEqual(activated["id"], imported["id"])

    def test_import_model_checkpoint_rejects_overlapping_managed_destination(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint

        imported = import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "managed-qwen",
                model_type="qwen2",
                repo_hint="Qwen/Qwen3-4B",
            ),
            name="Managed Qwen",
        )
        managed_path = Path(imported["local_path"])

        with self.assertRaises(ValueError) as raised:
            import_model_checkpoint(managed_path, name="Managed Qwen")

        self.assertIn("separate directories", str(raised.exception))
        self.assertTrue((managed_path / "config.json").exists())

    def test_first_run_readiness_requires_active_approved_model(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint, set_active_model
        from backend.app.core.setup_readiness import first_run_readiness

        readiness = first_run_readiness()
        pair_check = next(check for check in readiness["checks"] if check["id"] == "approved_model_pair")
        self.assertFalse(pair_check["ok"])

        self._install_default_chat_model()
        set_active_model("qwen3-4b-q4_k_m", role="chat")

        import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "qwen-local",
                model_type="qwen2",
                repo_hint="Qwen/Qwen3-4B",
            ),
            name="Qwen Local",
        )

        readiness = first_run_readiness()
        chat_check = next(check for check in readiness["checks"] if check["id"] == "chat_model")
        expert_check = next(check for check in readiness["checks"] if check["id"] == "expert_model")
        pair_check = next(check for check in readiness["checks"] if check["id"] == "approved_model_pair")
        self.assertTrue(chat_check["ok"])
        self.assertTrue(expert_check["ok"])
        self.assertTrue(pair_check["ok"])
        self.assertEqual(readiness["recommended_setup"]["recommended_pair_id"], "pair-qwen3-4b-qwen")

    def test_active_model_pair_status_rejects_cross_family_pair_even_when_both_roles_are_accepted(self) -> None:
        from backend.app.core.model_registry import active_model_pair_status, import_model_checkpoint, set_active_model

        self._install_default_chat_model()
        set_active_model("qwen3-4b-q4_k_m", role="chat")
        import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "phi-local",
                model_type="phi3",
                repo_hint="microsoft/Phi-4-mini-instruct",
            ),
            name="Phi Local",
        )

        pair = active_model_pair_status()

        self.assertFalse(pair["accepted"])
        self.assertIn("not in the current approved pairing matrix", pair["detail"])

    def test_rejected_model_compatibility_report_includes_replacement_recommendation(self) -> None:
        from backend.app.core.model_registry import model_compatibility_report

        file_path = Path(self.tmp.name) / "bad-model.gguf"
        file_path.write_text("not-a-checkpoint", encoding="utf-8")

        report = model_compatibility_report(file_path)

        self.assertFalse(report["accepted"])
        self.assertIn("replacement_recommendation", report)
        self.assertIn("recommended_chat_model_id", report["replacement_recommendation"])

    def test_discover_installed_models_finds_supported_local_checkpoint(self) -> None:
        from backend.app.core.model_registry import discover_installed_models

        model_dir = self._write_fake_local_transformers_model(
            "detected-qwen",
            model_type="qwen2",
            repo_hint="Qwen/Qwen3-4B",
        )
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_dir.parent)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        discovery = discover_installed_models(max_results=10)

        self.assertGreaterEqual(discovery["compatible_model_count"], 1)
        self.assertTrue(any(item["local_path"] == str(model_dir.resolve()) for item in discovery["models"]))

    def test_discover_installed_models_prioritizes_late_compatible_results_when_rejected_fill_limit(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, invalidate_model_discovery_cache

        scan_root = Path(self.tmp.name) / "model-scan"
        scan_root.mkdir()
        rejected_dirs = [
            self._write_fake_local_transformers_model(
                f"rejected-{index:02d}",
                model_type="unknown-family",
                repo_hint=f"Unknown/Rejected-{index:02d}",
            )
            for index in range(12)
        ]
        compatible = self._write_fake_local_transformers_model(
            "zz-compatible-qwen",
            model_type="qwen2",
            repo_hint="Qwen/Qwen3-4B",
        )
        for model_dir in [*rejected_dirs, compatible]:
            model_dir.rename(scan_root / model_dir.name)
        ordered_candidates = [scan_root / path.name for path in rejected_dirs] + [scan_root / compatible.name]

        os.environ["CML_MODEL_SCAN_ROOTS"] = str(scan_root)
        os.environ["CML_MODEL_SCAN_CACHE_SECONDS"] = "0"
        get_settings.cache_clear()
        invalidate_model_discovery_cache()

        with patch("backend.app.core.model_registry._iter_transformers_checkpoint_dirs", return_value=ordered_candidates):
            discovery = discover_installed_models(max_results=5, include_rejected=True, refresh=True)

        self.assertTrue(discovery["truncated"])
        self.assertEqual(len(discovery["models"]), 5)
        self.assertEqual(discovery["compatible_model_count"], 1)
        self.assertIn(str((scan_root / compatible.name).resolve()), {item["local_path"] for item in discovery["models"]})
        self.assertTrue(discovery["models"][0]["compatibility"]["accepted"])

    def test_models_discover_route_returns_detected_models(self) -> None:
        model_dir = self._write_fake_local_transformers_model(
            "route-detected-qwen",
            model_type="qwen2",
            repo_hint="Qwen/Qwen3-4B",
        )
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_dir.parent)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        client = self._client()
        try:
            response = client.get("/api/v1/models/discover?max_results=10")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["compatible_model_count"], 1)
        self.assertTrue(any(item["local_path"] == str(model_dir.resolve()) for item in payload["models"]))

    def test_model_recommendations_prefer_conservative_chat_choice_for_low_spec_profile(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations
        from backend.app.core.model_registry import import_model_checkpoint

        low_spec_profile = {
            "os": "Windows",
            "architecture": "AMD64",
            "cpu_name": "Test CPU",
            "cpu_threads": 8,
            "ram_total_bytes": 8 * 1024**3,
            "ram_available_bytes": 6 * 1024**3,
            "ram_usable_bytes": 6 * 1024**3,
            "disk_free_bytes": 32 * 1024**3,
            "has_avx2": True,
            "has_avx512": False,
            "hardware_tier": "cpu_minimum_spec",
            "training_supported": True,
            "runtime_provider": "openai",
            "runtime_backend": "llama_cpp_compatible",
            "runtime_base_url": "http://127.0.0.1:8080/v1",
            "runtime_detected": True,
            "runtime_detail": "Configured.",
            "detection_confidence": "high",
            "warnings": [],
            "gpus": [],
        }

        import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "qwen-expert",
                model_type="qwen2",
                repo_hint="Qwen/Qwen3-4B",
            ),
            name="Qwen Expert",
        )

        with patch("backend.app.core.model_recommender.service.build_hardware_profile", return_value=low_spec_profile):
            recommendations = build_model_recommendations()

        self.assertEqual(recommendations["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertEqual(recommendations["recommended_pair_id"], "pair-qwen3-4b-qwen")
        self.assertEqual(recommendations["chat_fit_type"], "cpu_only")
        self.assertIn("fallback_low_spec", recommendations)
        self.assertIn("fallback_fastest", recommendations)

    def test_model_recommendations_prefer_best_approved_pair_over_independent_top_choices(self) -> None:
        from backend.app.core.model_recommender.service import build_model_recommendations
        from backend.app.core.model_registry import import_model_checkpoint

        profile = {
            "os": "Windows",
            "architecture": "AMD64",
            "cpu_name": "Test CPU",
            "cpu_threads": 8,
            "ram_total_bytes": 12 * 1024**3,
            "ram_available_bytes": 10 * 1024**3,
            "ram_usable_bytes": 10 * 1024**3,
            "disk_free_bytes": 64 * 1024**3,
            "has_avx2": True,
            "has_avx512": False,
            "hardware_tier": "cpu_minimum_spec",
            "training_supported": True,
            "runtime_provider": "openai",
            "runtime_backend": "llama_cpp_compatible",
            "runtime_base_url": "http://127.0.0.1:8080/v1",
            "runtime_detected": True,
            "runtime_detail": "Configured.",
            "detection_confidence": "high",
            "warnings": [],
            "gpus": [],
        }

        import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "gemma-local-4b",
                model_type="gemma3",
                repo_hint="google/gemma-3-4b-it",
            ),
            name="Gemma 3 4B Local",
        )

        with patch("backend.app.core.model_recommender.service.build_hardware_profile", return_value=profile):
            recommendations = build_model_recommendations()

        self.assertEqual(recommendations["recommended_pair_id"], "pair-gemma3-4b-gemma")
        self.assertEqual(recommendations["recommended_chat_model_id"], "gemma-3-4b-it-q4_k_m")
        self.assertTrue(recommendations["pair_recommendation"]["accepted"])
        self.assertEqual(recommendations["pair_recommendation"]["expert_model_id"], recommendations["recommended_expert_model_id"])

    def test_benchmark_evidence_inherits_variant_or_lineage_for_custom_import(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence

        evidence = resolve_benchmark_evidence(
            {
                "id": "custom-qwen3-8b-local",
                "name": "Qwen3 8B Local",
                "family": "qwen",
                "source_kind": "custom_import",
                "local_path": str(Path(self.tmp.name) / "Qwen3-8B-Instruct"),
                "compatibility": {"accepted": True, "detail": "Accepted."},
            }
        )

        self.assertIn(evidence["source"], {"variant", "line_interp", "base_model"})
        self.assertGreater(float(evidence["confidence"]), 0.0)

    def test_benchmark_evidence_prefers_internal_measured_bundle(self) -> None:
        from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        bundle_path = Path(self.tmp.name) / "benchmarks.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "bundle-1",
                    "models": {
                        "qwen3-4b-q4_k_m": {
                            "score": 91.5,
                            "measured_at": "2026-06-20T00:00:00Z",
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
                "id": "qwen3-4b-q4_k_m",
                "name": "Qwen3 4B Q4_K_M",
                "family": "qwen",
                "source_kind": "default_choice",
                "compatibility": {},
            }
        )

        self.assertEqual(evidence["source"], "internal_measured")
        self.assertEqual(float(evidence["score"]), 91.5)
        self.assertEqual(evidence["bundle_version"], "bundle-1")

    def test_model_recommendations_route_returns_rich_recommender_contract(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        self._install_default_chat_model()
        import_model_checkpoint(
            self._write_fake_local_transformers_model(
                "route-qwen-expert",
                model_type="qwen2",
                repo_hint="Qwen/Qwen3-4B",
            ),
            name="Route Qwen Expert",
        )

        hardware = {
            "os": "Windows",
            "machine": "AMD64",
            "processor": "Test CPU",
            "cpu_count": 8,
            "total_memory_bytes": 8 * 1024**3,
            "available_memory_bytes": 6 * 1024**3,
            "usable_memory_bytes": 6 * 1024**3,
            "disk_free_bytes": 32 * 1024**3,
            "avx2": True,
            "avx512": False,
            "hardware_tier": "cpu_minimum_spec",
            "training_supported": True,
            "detail": "OK",
            "gpus": [],
            "warnings": [],
        }
        runtime = {
            "provider": "llama.cpp",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "qwen3-4b-q4_k_m",
            "available": True,
            "state": "ready",
            "detail": "Ready.",
        }
        bundle_path = Path(self.tmp.name) / "route-benchmarks.json"
        bundle_path.write_text(
            json.dumps(
                {
                    "version": "route-bundle-v1",
                    "models": {
                        "qwen3-4b-q4_k_m": {
                            "score": 88.0,
                            "measured_at": "2026-06-20T00:00:00Z",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE"] = str(bundle_path)
        invalidate_internal_benchmark_bundle_cache()

        with patch("backend.app.core.model_recommender.hardware_profile.hardware_status", return_value=hardware), patch(
            "backend.app.core.model_recommender.hardware_profile.runtime_status",
            return_value=runtime,
        ):
            client = self._client()
            try:
                response = client.get("/api/v1/models/recommendations")
            finally:
                client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertEqual(payload["recommended_pair_id"], "pair-qwen3-4b-qwen")
        self.assertIn(payload["confidence"], {"medium", "high"})
        self.assertEqual(payload["chat_recommendation"]["summary"], "Qwen3 4B Q4_K_M is the most feasible approved chat model for this device.")
        self.assertIn("warnings", payload)
        self.assertIn("reasons", payload)
        self.assertIn("fallback_low_spec", payload)
        self.assertIn("fallback_fastest", payload)
        self.assertEqual(payload["benchmark_bundle_version"], "route-bundle-v1")
        self.assertEqual(payload["chat_recommendation"]["evidence"]["source"], "internal_measured")
        self.assertIn("operator_summary", payload)
        self.assertIn("scoring_breakdown", payload)
        self.assertIn("candidate_table", payload)
        self.assertIn("benchmark_evidence_audit", payload)

    def test_discover_installed_models_uses_cache_until_refresh(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, invalidate_model_discovery_cache

        model_dir = self._write_fake_local_transformers_model(
            "cached-detected-qwen",
            model_type="qwen2",
            repo_hint="Qwen/Qwen3-4B",
        )
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_dir.parent)
        os.environ["CML_MODEL_SCAN_CACHE_SECONDS"] = "300"
        get_settings.cache_clear()
        invalidate_model_discovery_cache()

        call_counter = {"count": 0}

        def counting_iter(root: Path, *, max_depth: int) -> list[Path]:
            call_counter["count"] += 1
            return [model_dir]

        with patch("backend.app.core.model_registry._iter_transformers_checkpoint_dirs", side_effect=counting_iter):
            first = discover_installed_models(max_results=10)
            after_first = call_counter["count"]
            second = discover_installed_models(max_results=10)
            after_second = call_counter["count"]
            refreshed = discover_installed_models(max_results=10, refresh=True)
            after_refresh = call_counter["count"]

        self.assertGreater(after_first, 0)
        self.assertEqual(after_second, after_first)
        self.assertGreater(after_refresh, after_second)
        self.assertEqual(first["models"], second["models"])
        def stable_fields(models: list[dict]) -> list[tuple]:
            return [
                (
                    item["id"],
                    item["local_path"],
                    item["compatibility"]["accepted"],
                    item["compatibility"]["family"],
                )
                for item in models
            ]

        self.assertEqual(stable_fields(second["models"]), stable_fields(refreshed["models"]))

    def test_first_run_readiness_skips_deep_embedding_probe(self) -> None:
        from backend.app.core.setup_readiness import first_run_readiness

        probe_flags: list[bool] = []

        def fake_embedding_status(*, probe_model: bool = True) -> dict:
            probe_flags.append(probe_model)
            return {
                "provider": "sentence-transformers",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "dimensions": 384,
                "available": True,
                "detail": "Configured.",
                "setup_required": False,
                "cache_dir": str(Path(self.tmp.name) / "embeddings"),
            }

        with patch("backend.app.core.setup_readiness.embedding_status", side_effect=fake_embedding_status):
            readiness = first_run_readiness()

        self.assertEqual(probe_flags, [False])
        embedding_check = next(check for check in readiness["checks"] if check["id"] == "embedding_setup")
        self.assertTrue(embedding_check["ok"])

    def test_bridge_context_requires_token_when_enabled(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        settings = update_bridge_settings(
            BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True)
        )
        client = self._client()
        try:
            missing = client.post(
                "/api/v1/bridge/context",
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
            wrong = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": settings["bridge_token"] + "-wrong"},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)

    def test_bridge_disabled_rejects_even_with_valid_token(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.schemas import BridgeSettingsUpdate

        enabled = update_bridge_settings(BridgeSettingsUpdate(enabled=True, rotate_token=True))
        update_bridge_settings(BridgeSettingsUpdate(enabled=False))
        client = self._client()
        try:
            response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": enabled["bridge_token"]},
                json={"client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 403)

    def test_runtime_adapter_load_plan_resolves_local_transformers_model_dir(self) -> None:
        from backend.app.core.expert_runtime import runtime_adapter_load_plan

        self._write_fake_local_transformers_model("resolved-base-model")
        adapter_dir = Path(self.tmp.name) / "adapter"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            json.dumps(
                {
                    "peft_type": "LORA",
                    "base_model_name_or_path": "resolved-base-model",
                    "task_type": "CAUSAL_LM",
                }
            ),
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

        plan = runtime_adapter_load_plan(adapter_path=adapter_dir, base_model="resolved-base-model")

        self.assertTrue(plan["available"])
        self.assertEqual(plan["runtime"], "transformers-peft-local")
        self.assertTrue(plan["adapter_metadata"]["available"])
        self.assertEqual(Path(plan["base_model_path"]).name, "resolved-base-model")
        self.assertTrue(plan["resolved_base_model"]["available"])

    def test_runtime_adapter_load_plan_requires_deps_without_separate_runtime_python(self) -> None:
        from backend.app.core.expert_runtime import runtime_adapter_load_plan

        self._write_fake_local_transformers_model("deps-model")
        adapter_dir = Path(self.tmp.name) / "adapter-deps"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            '{"peft_type":"LORA","base_model_name_or_path":"deps-model"}',
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

        with (
            patch("backend.app.core.expert_runtime._package_status", return_value={"importable": False}),
            patch("backend.app.core.expert_runtime.runtime_python_executable", return_value=sys.executable),
        ):
            plan = runtime_adapter_load_plan(adapter_path=adapter_dir, base_model="deps-model")

        self.assertFalse(plan["available"])
        self.assertEqual(plan["failure_code"], "runtime_load_failed")
        self.assertIn("Install peft, transformers, and torch", plan["detail"])

    def test_runtime_adapter_load_plan_rejects_missing_configured_runtime_python(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.expert_runtime import runtime_adapter_load_plan

        self._write_fake_local_transformers_model("missing-runtime-model")
        adapter_dir = Path(self.tmp.name) / "adapter-missing-runtime"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            '{"peft_type":"LORA","base_model_name_or_path":"missing-runtime-model"}',
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")
        os.environ["CML_LORA_RUNTIME_PYTHON"] = str(Path(self.tmp.name) / "missing-runtime-python.exe")
        get_settings.cache_clear()
        try:
            plan = runtime_adapter_load_plan(adapter_path=adapter_dir, base_model="missing-runtime-model")
        finally:
            os.environ.pop("CML_LORA_RUNTIME_PYTHON", None)
            get_settings.cache_clear()

        self.assertFalse(plan["available"])
        self.assertEqual(plan["failure_code"], "runtime_load_failed")
        self.assertFalse(plan["runtime_dependencies"]["runtime_python_exists"])
        self.assertTrue(plan["runtime_dependencies"]["external_runtime"])
        self.assertIn("Configured LoRA runtime python was not found", plan["detail"])

    def test_run_adapter_runtime_smoke_reads_worker_report(self) -> None:
        import subprocess

        from backend.app.core.config import get_settings
        from backend.app.core.expert_runtime import run_adapter_runtime_smoke

        self._write_fake_local_transformers_model("smoke-model")
        adapter_dir = Path(self.tmp.name) / "adapter-smoke"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            '{"peft_type":"LORA","base_model_name_or_path":"smoke-model"}',
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")
        os.environ["CML_LORA_RUNTIME_REPETITION_PENALTY"] = "1.23"
        os.environ["CML_LORA_RUNTIME_NO_REPEAT_NGRAM_SIZE"] = "5"
        get_settings.cache_clear()

        def fake_run(command, capture_output, text, timeout, cwd):
            payload_path = Path(command[-1])
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["repetition_penalty"], 1.23)
            self.assertEqual(payload["no_repeat_ngram_size"], 5)
            report_path = Path(payload["report_path"])
            report_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "response_text": "CML",
                        "error": "",
                        "unloaded": True,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="worker-ok", stderr="")

        with patch("backend.app.core.expert_runtime.subprocess.run", side_effect=fake_run):
            report = run_adapter_runtime_smoke(
                adapter_path=adapter_dir,
                base_model="smoke-model",
                prompt="Reply with the single word CML.",
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["response_text"], "CML")
        self.assertTrue(report["unloaded"])
        self.assertEqual(report["stdout"], "worker-ok")

    def test_run_adapter_runtime_smoke_executes_real_test_trainer_adapter(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.expert_runtime import run_adapter_runtime_smoke
        from backend.app.core.lora_training import run_lora_training_process

        dataset_dir = Path(self.tmp.name) / "dataset"
        dataset_dir.mkdir()
        train_path = dataset_dir / "train.jsonl"
        validation_path = dataset_dir / "validation.jsonl"
        train_path.write_text("{}", encoding="utf-8")
        validation_path.write_text("{}", encoding="utf-8")
        model_dir = Path(self.tmp.name) / "models" / "real-smoke-model"
        output_dir = Path(self.tmp.name) / "real-smoke-adapter"
        os.environ["CML_ALLOW_LORA_TEST_TRAINER"] = "1"
        os.environ["CML_LORA_RUNTIME_DEVICE"] = "cpu"
        os.environ["CML_LORA_RUNTIME_DTYPE"] = "float32"
        get_settings.cache_clear()
        try:
            result = run_lora_training_process(
                dataset_manifest={
                    "dataset_dir": dataset_dir,
                    "train_path": train_path,
                    "validation_path": validation_path,
                },
                output_dir=output_dir,
                config={"base_model": str(model_dir)},
            )
            report = run_adapter_runtime_smoke(
                adapter_path=result["adapter_path"],
                base_model=str(model_dir),
                prompt="Reply with the single word CML.",
                max_new_tokens=8,
            )
        finally:
            os.environ.pop("CML_ALLOW_LORA_TEST_TRAINER", None)
            os.environ.pop("CML_LORA_RUNTIME_DEVICE", None)
            os.environ.pop("CML_LORA_RUNTIME_DTYPE", None)
            get_settings.cache_clear()

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue((model_dir / "model.safetensors").exists())
        self.assertTrue((output_dir / "adapter_model.safetensors").exists())
        self.assertTrue(report["ok"])
        self.assertTrue(report["response_text"].strip())
        self.assertTrue(report["unloaded"])

    def test_run_adapter_runtime_smoke_reports_worker_launch_failure(self) -> None:
        from backend.app.core.expert_runtime import run_adapter_runtime_smoke

        self._write_fake_local_transformers_model("launch-model")
        adapter_dir = Path(self.tmp.name) / "adapter-launch"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            '{"peft_type":"LORA","base_model_name_or_path":"launch-model"}',
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

        with patch(
            "backend.app.core.expert_runtime.subprocess.run",
            side_effect=FileNotFoundError("runtime python missing"),
        ):
            report = run_adapter_runtime_smoke(adapter_path=adapter_dir, base_model="launch-model")

        self.assertFalse(report["ok"])
        self.assertEqual(report["failure_code"], "runtime_load_failed")
        self.assertEqual(report["error"], "runtime python missing")
        self.assertEqual(report["stdout"], "")
        self.assertEqual(report["stderr"], "")

    def test_run_cluster_expert_prompt_falls_back_to_another_ready_artifact(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.expert_runtime import run_cluster_expert_prompt

        now = utc_now()
        adapter_a = Path(self.tmp.name) / "adapter-a"
        adapter_b = Path(self.tmp.name) / "adapter-b"
        for path in (adapter_a, adapter_b):
            path.mkdir()
            (path / "adapter_config.json").write_text(
                '{"peft_type":"LORA","base_model_name_or_path":"base"}',
                encoding="utf-8",
            )
            (path / "adapter_model.safetensors").write_bytes(b"adapter")

        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Cluster', '', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO expert_artifacts (
                    id, cluster_id, vault_id, artifact_type, status, local_path, base_model,
                    hardware_tier, quality_score, active, created_at, updated_at
                )
                VALUES
                    ('artifact-a', 'cluster-1', 'vault-1', 'lora_adapter', 'ready', ?, 'base', 'cpu', 80, 0, ?, ?),
                    ('artifact-b', 'cluster-1', 'vault-1', 'lora_adapter', 'ready', ?, 'base', 'cpu', 85, 1, ?, ?)
                """,
                (str(adapter_a), now, now, str(adapter_b), now, now),
            )
            with patch(
                "backend.app.core.expert_runtime.run_adapter_runtime_smoke",
                side_effect=[
                    {"ok": False, "error": "selected adapter failed"},
                    {"ok": True, "response_text": "fallback worked", "unloaded": True},
                ],
            ):
                result = run_cluster_expert_prompt(conn, cluster_id="cluster-1", prompt="test prompt")

        self.assertTrue(result["ok"])
        self.assertEqual(result["artifact_id"], "artifact-a")
        self.assertTrue(result["used_fallback"])
        self.assertEqual(result["response_text"], "fallback worked")
        self.assertEqual(len(result["attempted_artifacts"]), 2)

    def test_bridge_rotated_token_invalidates_previous_token(self) -> None:
        from backend.app.api.routes.bridge import update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        first = update_bridge_settings(
            BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-1"], rotate_token=True)
        )
        second = update_bridge_settings(BridgeSettingsUpdate(rotate_token=True))
        client = self._client()
        try:
            old_response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": first["bridge_token"]},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
            new_response = client.post(
                "/api/v1/bridge/context",
                headers={"x-cml-bridge-token": second["bridge_token"]},
                json={"vault_id": "vault-1", "client_name": "qa", "query": "hello"},
            )
        finally:
            client.close()

        self.assertEqual(old_response.status_code, 401)
        self.assertEqual(new_response.status_code, 200)

    def test_extension_status_reports_invalid_token_cleanly(self) -> None:
        client = self._client()
        try:
            response = client.get("/api/v1/extension/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])

    def test_extension_http_contract_accepts_extension_token_without_local_api_token(self) -> None:
        from backend.app.api.routes.extension import create_extension_client
        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionClientCreate

        os.environ["CML_API_TOKEN"] = "local-api-token"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "0"
        get_settings.cache_clear()

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
        extension_client = create_extension_client(ExtensionClientCreate(name="browser", allowed_vault_ids=["vault-1"]))

        client = self._client()
        try:
            status_response = client.get(
                "/api/v1/extension/status",
                headers={"x-cml-extension-token": extension_client["token"]},
            )
            capture_response = client.post(
                "/api/v1/extension/capture",
                headers={"x-cml-extension-token": extension_client["token"]},
                json={
                    "vault_id": "vault-1",
                    "capture_type": "selection",
                    "title": "Saved selection",
                    "url": "https://example.com",
                    "text": "captured through http extension contract",
                },
            )
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)
            os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
            get_settings.cache_clear()

        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.json()["ok"])
        self.assertEqual(capture_response.status_code, 200)
        self.assertEqual(capture_response.json()["status"], "stored")

    def test_extension_upload_http_contract_accepts_extension_token_without_local_api_token(self) -> None:
        from backend.app.api.routes.extension import create_extension_client
        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionClientCreate

        os.environ["CML_API_TOKEN"] = "local-api-token"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "0"
        get_settings.cache_clear()

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
        extension_client = create_extension_client(ExtensionClientCreate(name="browser", allowed_vault_ids=["vault-1"]))

        client = self._client()
        try:
            upload_response = client.post(
                "/api/v1/extension/capture-upload",
                headers={"x-cml-extension-token": extension_client["token"]},
                json={
                    "vault_id": "vault-1",
                    "capture_type": "file",
                    "title": "notes.txt",
                    "file_name": "notes.txt",
                    "mime_type": "text/plain",
                    "content_base64": "bm90ZXMgdmlhIGV4dGVuc2lvbiB1cGxvYWQ=",
                },
            )
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)
            os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
            get_settings.cache_clear()

        self.assertEqual(upload_response.status_code, 200)
        self.assertEqual(upload_response.json()["status"], "stored")

    def test_options_cors_allows_vite_dev_origin(self) -> None:
        client = self._client()
        try:
            response = client.options(
                "/api/v1/system/hardware",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")

    def test_options_cors_rejects_unknown_origin(self) -> None:
        client = self._client()
        try:
            response = client.options(
                "/api/v1/system/hardware",
                headers={
                    "Origin": "http://127.0.0.1:5191",
                    "Access-Control-Request-Method": "GET",
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_local_api_auth_requires_explicit_unauthenticated_opt_in_without_token(self) -> None:
        os.environ.pop("CML_ALLOW_UNAUTHENTICATED_API", None)
        client = self._client()
        try:
            response = client.get("/api/v1/vaults")
        finally:
            client.close()
            os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
        self.assertEqual(response.status_code, 503)

    def test_local_api_auth_allows_explicit_unauthenticated_opt_in_without_token(self) -> None:
        client = self._client()
        try:
            response = client.get("/api/v1/vaults")
        finally:
            client.close()
        self.assertEqual(response.status_code, 200)

    def test_local_api_auth_blocks_private_route_when_token_is_configured(self) -> None:
        os.environ["CML_API_TOKEN"] = "test-token"
        client = self._client()
        try:
            missing = client.get("/api/v1/vaults")
            bearer = client.get("/api/v1/vaults", headers={"Authorization": "Bearer test-token"})
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(bearer.status_code, 200)

    def test_backend_identity_requires_local_api_token_when_configured(self) -> None:
        os.environ["CML_API_TOKEN"] = "identity-token"
        os.environ.pop("CML_ALLOW_UNAUTHENTICATED_API", None)
        client = self._client()
        try:
            missing = client.get("/api/v1/system/backend-identity")
            valid = client.get(
                "/api/v1/system/backend-identity",
                headers={"x-cml-api-token": "identity-token"},
            )
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)
            os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["service"], "cml-backend")
        self.assertTrue(valid.json()["authenticated"])

    def test_known_startup_phases_fall_back_when_shared_file_is_missing(self) -> None:
        from backend.app.core.startup_status import FALLBACK_PHASES, known_startup_phases

        with patch("pathlib.Path.read_text", side_effect=OSError("missing")):
            phases = known_startup_phases()

        self.assertEqual(phases, FALLBACK_PHASES)

    def test_scan_without_vault_does_not_persist_import_history(self) -> None:
        from backend.app.api.routes.integrations import list_integration_imports, scan_local_folder_integration
        from backend.app.schemas import LocalFolderScanRequest

        folder = Path(self.tmp.name) / "obsidian"
        folder.mkdir()
        (folder / ".obsidian").mkdir()
        (folder / "note.md").write_text("hello vault", encoding="utf-8")

        result = scan_local_folder_integration(LocalFolderScanRequest(path=str(folder), vault_id=None, max_files=20))

        self.assertIsNone(result["import_id"])
        self.assertEqual(list_integration_imports(), [])

    def test_integration_imports_are_paginated_and_validate_vault_filter(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.integrations import list_integration_imports
        from backend.app.core.database import connect

        with connect() as conn:
            for vault_id in ("vault-1", "vault-2"):
                conn.execute(
                    "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        vault_id,
                        vault_id,
                        str(Path(self.tmp.name) / vault_id),
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
            for index in range(5):
                conn.execute(
                    """
                    INSERT INTO integration_imports (
                        id, vault_id, integration_type, root_path, status, supported_count,
                        skipped_count, truncated, last_scan_at, created_at, updated_at
                    )
                    VALUES (?, 'vault-1', 'local_folder', ?, 'scanned', 0, 0, 0, ?, ?, ?)
                    """,
                    (
                        f"import-{index}",
                        str(Path(self.tmp.name) / f"import-{index}"),
                        f"2026-01-01T00:00:0{index}+00:00",
                        f"2026-01-01T00:00:0{index}+00:00",
                        f"2026-01-01T00:00:0{index}+00:00",
                    ),
                )
            conn.execute(
                """
                INSERT INTO integration_imports (
                    id, vault_id, integration_type, root_path, status, supported_count,
                    skipped_count, truncated, last_scan_at, created_at, updated_at
                )
                VALUES ('import-other', 'vault-2', 'local_folder', ?, 'scanned', 0, 0, 0, ?, ?, ?)
                """,
                (
                    str(Path(self.tmp.name) / "other"),
                    "2026-01-01T00:00:09+00:00",
                    "2026-01-01T00:00:09+00:00",
                    "2026-01-01T00:00:09+00:00",
                ),
            )

        page = list_integration_imports(vault_id="vault-1", limit=2, offset=1)
        self.assertEqual([item["id"] for item in page], ["import-3", "import-2"])
        self.assertTrue(all(item["vault_id"] == "vault-1" for item in page))
        self.assertEqual(len(list_integration_imports(limit=200)), 6)

        with self.assertRaises(HTTPException) as raised:
            list_integration_imports(vault_id="vault-missing")
        self.assertEqual(raised.exception.status_code, 404)

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("options: { limit?: number; offset?: number } = {}", backend_client)
        self.assertIn('params.set("limit", String(options.limit))', backend_client)
        self.assertIn('params.set("offset", String(options.offset))', backend_client)

    def test_integration_refresh_missing_folder_marks_import_error(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.integrations import refresh_integration_import
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO integration_imports (
                    id, vault_id, integration_type, root_path, status, supported_count,
                    skipped_count, truncated, last_scan_at, created_at, updated_at
                )
                VALUES ('import-1', NULL, 'local_folder', ?, 'scanned', 0, 0, 0, ?, ?, ?)
                """,
                (str(Path(self.tmp.name) / "missing-folder"), now, now, now),
            )

        with self.assertRaises(HTTPException) as raised:
            refresh_integration_import("import-1")
        self.assertEqual(raised.exception.status_code, 400)

        with connect() as conn:
            row = conn.execute("SELECT status FROM integration_imports WHERE id = 'import-1'").fetchone()
        self.assertEqual(row["status"], "error")

    def test_local_folder_scan_skips_symlink_targets(self) -> None:
        from backend.app.core.local_integrations import scan_local_folder

        root = Path(self.tmp.name) / "scan-root"
        root.mkdir()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret", encoding="utf-8")
        (root / "note.md").write_text("note", encoding="utf-8")
        try:
            (root / "link-out").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is not available in this environment")

        result = scan_local_folder(str(root), 50)
        joined = "\n".join(result["supported_files"])
        self.assertIn("note.md", joined)
        self.assertNotIn("secret.md", joined)

    def test_local_folder_scan_skips_tmp_subtrees(self) -> None:
        from backend.app.core.local_integrations import scan_local_folder

        root = Path(self.tmp.name) / "scan-root"
        root.mkdir()
        (root / "keep.md").write_text("keep", encoding="utf-8")
        tmp_dir = root / ".tmp"
        tmp_dir.mkdir()
        (tmp_dir / "skip.md").write_text("skip", encoding="utf-8")

        result = scan_local_folder(str(root), 50)

        joined = "\n".join(result["supported_files"])
        self.assertIn("keep.md", joined)
        self.assertNotIn("skip.md", joined)

    def test_unsupported_local_file_type_is_rejected(self) -> None:
        from backend.app.core.extraction import ExtractionError, extract_pages_from_path

        target = Path(self.tmp.name) / "malware.exe"
        target.write_bytes(b"MZ")
        with self.assertRaises(ExtractionError):
            extract_pages_from_path(str(target))

    def test_zero_byte_text_file_is_rejected(self) -> None:
        from backend.app.core.extraction import ExtractionError, extract_pages_from_path

        target = Path(self.tmp.name) / "empty.txt"
        target.write_text("", encoding="utf-8")
        with self.assertRaises(ExtractionError) as raised:
            extract_pages_from_path(str(target))
        self.assertIn("No readable text", str(raised.exception))

    def test_modified_file_after_first_ingest_updates_same_source(self) -> None:
        from backend.app.api.routes.sources import create_source_from_path
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourcePathCreate

        target = Path(self.tmp.name) / "note.txt"
        target.write_text("alpha beta gamma", encoding="utf-8")
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        first = create_source_from_path(SourcePathCreate(vault_id="vault-1", path=str(target)))
        target.write_text("alpha beta gamma!", encoding="utf-8")
        second = create_source_from_path(SourcePathCreate(vault_id="vault-1", path=str(target)))

        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]
            stored = conn.execute(
                "SELECT id, original_path, checksum FROM sources WHERE id = ?",
                (first["id"],),
            ).fetchone()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(count, 1)
        self.assertEqual(stored["id"], first["id"])
        self.assertEqual(stored["original_path"], str(target))
        self.assertNotEqual(first["checksum"], second["checksum"])

    def test_url_ingestion_resolves_relative_cover_image_url(self) -> None:
        from backend.app.api.routes.sources import create_source_from_url
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceUrlCreate

        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeResponse:
            headers = FakeHeaders({"content-type": "text/html"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return (
                    b"<html><head><meta property='og:image' content='/images/thumb.png'>"
                    b"<title>Relative cover</title></head><body><p>relative cover body</p></body></html>"
                )

            def geturl(self):
                return "https://example.com/articles/test"

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with patch("backend.app.core.extraction._safe_open", return_value=(FakeResponse(), "https://example.com/articles/test")):
            source = create_source_from_url(SourceUrlCreate(vault_id="vault-1", url="https://example.com/articles/test"))

        self.assertEqual(source["cover_image_url"], "https://example.com/images/thumb.png")
        self.assertEqual(source["source_type"], "link")

    def test_url_ingestion_strips_credentials_before_fetch_and_storage(self) -> None:
        from backend.app.api.routes.sources import create_source_from_url
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceUrlCreate

        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeResponse:
            headers = FakeHeaders({"content-type": "text/html"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"<html><head><title>Private</title></head><body>credential free content</body></html>"

            def geturl(self):
                return "https://example.com/private"

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        seen_urls: list[str] = []

        def fake_open(request, timeout):
            seen_urls.append(request.full_url)
            return FakeResponse(), "https://example.com/private"

        with (
            patch("backend.app.core.extraction._safe_open", side_effect=fake_open),
            patch("backend.app.core.extraction.validate_public_http_url"),
        ):
            source = create_source_from_url(
                SourceUrlCreate(vault_id="vault-1", url="https://user:secret@example.com/private")
            )

        self.assertEqual(seen_urls, ["https://example.com/private"])
        self.assertEqual(source["url"], "https://example.com/private")
        self.assertNotIn("secret", str(source))

    def test_url_ingestion_rejects_oversized_html_response(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.sources import create_source_from_url
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceUrlCreate

        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeResponse:
            headers = FakeHeaders({"content-type": "text/html"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"x" * 2_000_001

            def geturl(self):
                return "https://example.com/huge"

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with patch("backend.app.core.extraction._safe_open", return_value=(FakeResponse(), "https://example.com/huge")):
            with self.assertRaises(HTTPException) as raised:
                create_source_from_url(SourceUrlCreate(vault_id="vault-1", url="https://example.com/huge"))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("too large", raised.exception.detail.lower())

    def test_safe_open_blocks_redirect_to_loopback_target(self) -> None:
        from backend.app.core.extraction import ExtractionError, _safe_open
        from urllib.request import Request

        class RedirectToLoopback:
            def open(self, request, timeout=0):
                raise HTTPError(request.full_url, 302, "redirect", {"Location": "http://127.0.0.1/admin"}, None)

        with patch("backend.app.core.extraction.build_opener", return_value=RedirectToLoopback()):
            with self.assertRaises(ExtractionError) as raised:
                _safe_open(Request("https://example.com/start"), timeout=1)
        self.assertIn("not allowed", str(raised.exception).lower())

    def test_safe_open_blocks_private_connected_peer_after_public_url_validation(self) -> None:
        from backend.app.core.extraction import ExtractionError, _safe_open
        from urllib.request import Request

        class FakeSocket:
            def getpeername(self):
                return ("127.0.0.1", 443)

        class FakeRaw:
            _sock = FakeSocket()

        class FakeFp:
            raw = FakeRaw()

        class FakeResponse:
            fp = FakeFp()

            def geturl(self):
                return "https://example.com/start"

        class PublicUrlPrivatePeer:
            def open(self, _request, timeout=0):
                return FakeResponse()

        with (
            patch("backend.app.core.extraction.build_opener", return_value=PublicUrlPrivatePeer()),
            patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]),
        ):
            with self.assertRaises(ExtractionError) as raised:
                _safe_open(Request("https://example.com/start"), timeout=1)
        self.assertIn("private", str(raised.exception).lower())

    def test_text_ingestion_stores_sql_payload_literally(self) -> None:
        from backend.app.api.routes.sources import create_source_from_text
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceTextCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        source = create_source_from_text(
            SourceTextCreate(
                vault_id="vault-1",
                title="Injection probe",
                text="'; DROP TABLE sources; --",
            )
        )

        with connect() as conn:
            stored = conn.execute("SELECT raw_text FROM sources WHERE id = ?", (source["id"],)).fetchone()
            count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]

        self.assertEqual(stored["raw_text"], "'; DROP TABLE sources; --")
        self.assertEqual(count, 1)

    def test_job_cancel_route_rejects_non_cancellable_job(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO app_jobs (
                    id, job_type, status, payload, dedupe_key, priority, idempotency_class,
                    restart_policy, dependency_failure_policy, write_scope, scope_id,
                    concurrency_group, resource_cost, can_run_during_synthesis, user_visible,
                    user_initiated, cancellable, preemptable, timeout_seconds, soft_timeout_seconds,
                    timeout_action, depends_on_job_id, attempts, max_attempts, last_error,
                    status_detail, started_at, completed_at, created_at, updated_at
                )
                VALUES (
                    'job-1', 'reindex_source', 'queued', '{}', NULL, 'normal', 'idempotent',
                    'requeue', 'cancel', 'none', NULL, NULL, 'light', 1, 0, 0, 0, 0, NULL, NULL,
                    'fail', NULL, 0, 3, '', '', NULL, NULL, ?, ?
                )
                """,
                (now, now),
            )

        client = self._client()
        try:
            response = client.post("/api/v1/jobs/job-1/cancel")
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)
        self.assertIn("not cancellable", response.json()["detail"])

    def test_message_useful_flag_persists(self) -> None:
        from backend.app.api.routes.chat import get_chat_session, update_chat_message
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatMessageUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-1', 'vault-1', 'QA session', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
                )
                VALUES ('msg-1', 'session-1', 'assistant', 'Hello', '[]', '[]', '[]', NULL, 0, ?)
                """,
                (now,),
            )

        session = update_chat_message("msg-1", ChatMessageUpdate(useful=True))
        assistant = [message for message in session["messages"] if message["id"] == "msg-1"][0]
        reloaded = get_chat_session("session-1")
        reloaded_assistant = [message for message in reloaded["messages"] if message["id"] == "msg-1"][0]

        self.assertTrue(assistant["useful"])
        self.assertTrue(reloaded_assistant["useful"])

    def test_stream_chat_context_emits_meta_token_done_sequence(self) -> None:
        import asyncio

        from backend.app.api.routes.chat import stream_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        async def collect(response) -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        with (
            patch("backend.app.api.routes.chat.runtime_status", return_value={"state": "ready"}),
            patch("backend.app.api.routes.chat.stream_direct_answer", return_value=iter(["Hello", " world"])),
        ):
            response = stream_chat_context(ChatContextRequest(vault_id="vault-1", prompt="Hello there", persist=False))
            payload = asyncio.run(collect(response))

        self.assertEqual(response.media_type, "text/event-stream")
        self.assertIn("event: meta", payload)
        self.assertIn("event: token", payload)
        self.assertIn("event: done", payload)
        self.assertLess(payload.index("event: meta"), payload.index("event: token"))
        self.assertLess(payload.index("event: token"), payload.index("event: done"))

    def test_stream_chat_context_uses_direct_answer_fallback_when_retrieval_has_no_grounding(self) -> None:
        import asyncio

        from backend.app.api.routes.chat import stream_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        async def collect(response) -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        context = {
            "answer": "",
            "clusters_used": [],
            "citations": [],
            "coverage_ledger": {"partial_failure_mode": "no_citations_direct_answer"},
            "intent": "vault_question",
            "runtime_state": "ready",
            "warnings": [],
            "recent_turns": [],
            "direct_answer_fallback": True,
            "direct_answer_prefix": "Ungrounded fallback.\n\n",
        }

        with (
            patch("backend.app.api.routes.chat._build_retrieval_context", return_value=context),
            patch("backend.app.api.routes.chat.stream_direct_answer", return_value=iter(["Hello", " world"])),
        ):
            response = stream_chat_context(ChatContextRequest(vault_id="vault-1", prompt="overview", persist=False))
            payload = asyncio.run(collect(response))

        self.assertIn("Ungrounded fallback.", payload)
        self.assertIn("Hello", payload)
        self.assertIn("event: done", payload)

    def test_persisted_stream_chat_marks_generation_retriable_when_context_build_fails(self) -> None:
        import asyncio

        from backend.app.api.routes.chat import get_chat_timeline, stream_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        async def collect(response) -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        with patch("backend.app.api.routes.chat._build_retrieval_context", side_effect=RuntimeError("context build exploded")):
            response = stream_chat_context(ChatContextRequest(vault_id="vault-1", prompt="Find my notes", persist=True))
            with self.assertRaisesRegex(RuntimeError, "context build exploded"):
                asyncio.run(collect(response))

        with connect() as conn:
            generation = conn.execute("SELECT * FROM chat_generations").fetchone()
            self.assertIsNotNone(generation)
            self.assertEqual(generation["state"], "retriable")
            self.assertIn("context build exploded", generation["error"])
            self.assertIsNone(generation["assistant_message_id"])
            session_id = generation["session_id"]

            messages = conn.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["content"], "Find my notes")

        timeline = get_chat_timeline(session_id)
        retriable = [item for item in timeline["items"] if item["message_type"] == "retriable_generation"]
        self.assertEqual(len(retriable), 1)
        self.assertIn("context build exploded", retriable[0]["error"])

    def test_message_saved_flag_updates_session_saved_state(self) -> None:
        from backend.app.api.routes.chat import update_chat_message
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatMessageUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-1', 'vault-1', 'QA session', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
                )
                VALUES ('msg-1', 'session-1', 'assistant', 'Hello', '[]', '[]', '[]', NULL, 0, ?)
                """,
                (now,),
            )

        session = update_chat_message("msg-1", ChatMessageUpdate(saved=True))
        message = [item for item in session["messages"] if item["id"] == "msg-1"][0]

        self.assertTrue(message["saved"])
        self.assertTrue(session["saved"])

    def test_whitespace_only_text_ingestion_is_rejected_or_marked_no_content(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.sources import create_source_from_text
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceTextCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with self.assertRaises(HTTPException):
            create_source_from_text(
                SourceTextCreate(
                    vault_id="vault-1",
                    title="Whitespace",
                    text="   \n\n   ",
                )
            )

    def test_null_bytes_in_pasted_text_are_sanitized_or_rejected(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.sources import create_source_from_text
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceTextCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        try:
            source = create_source_from_text(
                SourceTextCreate(
                    vault_id="vault-1",
                    title="Null bytes",
                    text="abc\x00def",
                )
            )
        except HTTPException:
            return

        with connect() as conn:
            row = conn.execute(
                "SELECT raw_text, extracted_text FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()

        self.assertNotIn("\x00", row["raw_text"])
        self.assertNotIn("\x00", row["extracted_text"])

    def test_persisted_chat_failure_does_not_leave_in_flight_generation(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with patch("backend.app.api.routes.chat._build_retrieval_context", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                build_chat_context(ChatContextRequest(vault_id="vault-1", prompt="trigger failure"))

        with connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_generations WHERE state = 'in_flight'"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_url_ingestion_404_returns_clean_client_error(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.sources import create_source_from_url
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceUrlCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with patch(
            "backend.app.core.extraction._safe_open",
            side_effect=HTTPError("https://example.com/missing", 404, "missing", {}, None),
        ):
            with self.assertRaises(HTTPException) as raised:
                create_source_from_url(SourceUrlCreate(vault_id="vault-1", url="https://example.com/missing"))
        self.assertEqual(raised.exception.status_code, 400)

    def test_delete_chat_session_cleans_up_attachment_sources(self) -> None:
        from backend.app.api.routes.chat import build_chat_context, delete_chat_session
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatAttachmentInput, ChatContextRequest

        now = utc_now()
        attachment_path = Path(self.tmp.name) / "attached-delete.txt"
        attachment_path.write_text("delete attachment lifecycle " * 40, encoding="utf-8")
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        response = build_chat_context(
            ChatContextRequest(
                vault_id="vault-1",
                prompt="use attachment",
                attachments=[ChatAttachmentInput(path=str(attachment_path))],
            )
        )

        delete_chat_session(response["session_id"])

        with connect() as conn:
            remaining_sources = conn.execute(
                "SELECT COUNT(*) AS count FROM sources WHERE original_path = ?",
                (str(attachment_path),),
            ).fetchone()["count"]
        self.assertEqual(remaining_sources, 0)

    def test_list_chat_sessions_validates_vault_and_paginates_large_history(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.chat import list_chat_sessions
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            for index in range(6):
                session_now = f"2026-06-14T00:00:0{index}Z"
                conn.execute(
                    """
                    INSERT INTO chat_sessions (
                        id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                    )
                    VALUES (?, 'vault-1', ?, NULL, 0, 'idle', NULL, ?, ?)
                    """,
                    (f"session-{index}", f"Session {index}", session_now, session_now),
                )
            large_rows = [
                (
                    f"session-extra-{index:04d}",
                    f"Extra Session {index:04d}",
                    f"2026-06-15T00:00:00Z.{index:04d}",
                    f"2026-06-15T00:00:00Z.{index:04d}",
                )
                for index in range(205)
            ]
            conn.executemany(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES (?, 'vault-1', ?, NULL, 0, 'idle', NULL, ?, ?)
                """,
                large_rows,
            )

        first_page = list_chat_sessions("vault-1", limit=2, offset=0)
        second_page = list_chat_sessions("vault-1", limit=2, offset=2)
        clamped_large = list_chat_sessions("vault-1", limit=500, offset=0)
        tail_page = list_chat_sessions("vault-1", limit=4, offset=204)
        clamped = list_chat_sessions("vault-1", limit=0, offset=-5)

        self.assertEqual([item["id"] for item in first_page], ["session-extra-0204", "session-extra-0203"])
        self.assertEqual([item["id"] for item in second_page], ["session-extra-0202", "session-extra-0201"])
        self.assertEqual(len(clamped_large), 200)
        self.assertEqual([item["id"] for item in tail_page], ["session-extra-0000", "session-5", "session-4", "session-3"])
        self.assertEqual(len(clamped), 1)
        self.assertEqual(clamped[0]["id"], "session-extra-0204")
        with self.assertRaises(HTTPException) as missing_vault:
            list_chat_sessions("vault-missing")
        self.assertEqual(missing_vault.exception.status_code, 404)
        self.assertEqual(missing_vault.exception.detail, "Vault not found")

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("listChatSessions(vaultId?: string, options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn('params.set("limit", String(options.limit))', backend_client)
        self.assertIn('params.set("offset", String(options.offset))', backend_client)

    def test_job_status_caps_running_rows_without_losing_counts(self) -> None:
        from backend.app.core.background_jobs import JOB_STATUS_RUNNING_LIMIT, job_queue_status
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            rows = [
                (
                    f"job-running-{index:03d}",
                    "reindex_source",
                    "running",
                    "{}",
                    "normal",
                    "idempotent",
                    "requeue",
                    "cancel",
                    "source",
                    f"source-{index:03d}",
                    "vector_writer",
                    "medium",
                    0,
                    1,
                    1,
                    1,
                    0,
                    900,
                    None,
                    "fail",
                    None,
                    1,
                    3,
                    "",
                    "",
                    f"2026-06-19T00:00:{index % 60:02d}+00:00",
                    None,
                    f"2026-06-19T00:00:{index % 60:02d}+00:00",
                    f"2026-06-19T00:00:{index % 60:02d}+00:00",
                )
                for index in range(60)
            ]
            conn.executemany(
                """
                INSERT INTO app_jobs (
                    id, job_type, status, payload, priority, idempotency_class, restart_policy,
                    dependency_failure_policy, write_scope, scope_id, concurrency_group, resource_cost,
                    can_run_during_synthesis, user_visible, user_initiated, cancellable, preemptable,
                    timeout_seconds, soft_timeout_seconds, timeout_action, depends_on_job_id, attempts,
                    max_attempts, last_error, status_detail, started_at, completed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            for index in range(12):
                conn.execute(
                    """
                    INSERT INTO app_jobs (
                        id, job_type, status, payload, priority, idempotency_class, restart_policy,
                        dependency_failure_policy, write_scope, resource_cost, can_run_during_synthesis,
                        user_visible, user_initiated, cancellable, preemptable, timeout_action, attempts,
                        max_attempts, last_error, status_detail, created_at, updated_at
                    )
                    VALUES (?, 'diagnostic_bundle', 'succeeded', '{}', 'normal', 'idempotent', 'requeue',
                        'cancel', 'none', 'light', 1, 1, 0, 0, 0, 'fail', 1, 3, '', '', ?, ?)
                    """,
                    (
                        f"job-succeeded-{index:03d}",
                        now,
                        f"2026-06-19T00:01:{index:02d}+00:00",
                    ),
                )

        status = job_queue_status()

        self.assertEqual(status["running"], 60)
        self.assertEqual(len(status["running_jobs"]), JOB_STATUS_RUNNING_LIMIT)
        self.assertEqual(status["running_jobs"][0]["id"], "job-running-000")
        self.assertEqual(status["running_jobs"][-1]["id"], "job-running-049")
        self.assertEqual(len(status["latest"]), 10)
        self.assertEqual(status["latest"][0]["id"], "job-succeeded-011")

    def test_chat_timeline_includes_retriable_generation_item(self) -> None:
        from backend.app.api.routes.chat import get_chat_timeline
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-1', 'vault-1', 'QA session', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
                )
                VALUES ('msg-1', 'session-1', 'user', 'Hello', '[]', '[]', '[]', NULL, 0, ?)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                    runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES ('gen-1', 'session-1', 'msg-1', NULL, 'vault-1', 'Hello', 'retriable', '', '', 'interrupted', NULL, ?, ?, NULL)
                """,
                (now, now),
            )

        timeline = get_chat_timeline("session-1")
        retriable = [item for item in timeline["items"] if item["message_type"] == "retriable_generation"]

        self.assertEqual(len(retriable), 1)
        self.assertEqual(retriable[0]["prompt"], "Hello")

    def test_get_chat_session_returns_latest_message_window_in_chronological_order(self) -> None:
        from backend.app.api.routes.chat import get_chat_session
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-window', 'vault-1', 'Windowed', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            for index in range(5):
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, 'session-window', 'user', ?, ?)",
                    (f"msg-{index}", f"message {index}", f"2026-06-14T00:00:0{index}Z"),
                )

        latest_two = get_chat_session("session-window", limit=2)
        next_two = get_chat_session("session-window", limit=2, offset=2)

        self.assertEqual([item["id"] for item in latest_two["messages"]], ["msg-3", "msg-4"])
        self.assertEqual([item["id"] for item in next_two["messages"]], ["msg-1", "msg-2"])

    def test_chat_timeline_returns_latest_window_with_retriable_items(self) -> None:
        from backend.app.api.routes.chat import get_chat_timeline
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('timeline-window', 'vault-1', 'Timeline', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            for index in range(4):
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, 'timeline-window', 'user', ?, ?)",
                    (f"msg-t{index}", f"message {index}", f"2026-06-14T00:00:0{index}Z"),
                )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                    runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES ('gen-window', 'timeline-window', 'msg-t1', NULL, 'vault-1', 'retry me', 'retriable', '', '', 'interrupted', NULL, ?, ?, NULL)
                """,
                ("2026-06-14T00:00:00Z", "2026-06-14T00:00:05Z"),
            )

        latest = get_chat_timeline("timeline-window", limit=2)
        next_page = get_chat_timeline("timeline-window", limit=2, offset=2)

        self.assertEqual([item["id"] for item in latest["items"]], ["msg-t3", "gen-window"])
        self.assertEqual([item["message_type"] for item in latest["items"]], ["user_message", "retriable_generation"])
        self.assertEqual([item["id"] for item in next_page["items"]], ["msg-t1", "msg-t2"])

    def test_chat_timeline_paginates_across_many_retriable_generations(self) -> None:
        from backend.app.api.routes.chat import get_chat_timeline
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('timeline-retry-window', 'vault-1', 'Timeline retries', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES ('msg-base', 'timeline-retry-window', 'user', 'base', ?)",
                ("2026-06-14T00:00:00Z",),
            )
            for index in range(6):
                updated_at = f"2026-06-14T00:00:1{index}Z"
                conn.execute(
                    """
                    INSERT INTO chat_generations (
                        id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                        runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                    )
                    VALUES (?, 'timeline-retry-window', 'msg-base', NULL, 'vault-1', ?, 'retriable', '', '', 'interrupted', NULL, ?, ?, NULL)
                    """,
                    (f"gen-many-{index}", f"retry {index}", updated_at, updated_at),
                )

        latest = get_chat_timeline("timeline-retry-window", limit=2)
        next_page = get_chat_timeline("timeline-retry-window", limit=2, offset=2)

        self.assertEqual([item["id"] for item in latest["items"]], ["gen-many-4", "gen-many-5"])
        self.assertEqual([item["id"] for item in next_page["items"]], ["gen-many-2", "gen-many-3"])
        self.assertTrue(all(item["message_type"] == "retriable_generation" for item in latest["items"]))

    def test_get_chat_session_batches_snapshot_hydration_for_assistant_messages(self) -> None:
        from backend.app.api.routes.chat import get_chat_session
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('session-batch', 'vault-1', 'Batch hydrate', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            for index in range(3):
                message_id = f"assistant-{index}"
                created_at = f"2026-06-14T00:00:0{index}Z"
                conn.execute(
                    """
                    INSERT INTO chat_messages (
                        id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
                    )
                    VALUES (?, 'session-batch', 'assistant', ?, '[]', '[]', '[]', NULL, 0, ?)
                    """,
                    (message_id, f"answer {index}", created_at),
                )
                conn.execute(
                    """
                    INSERT INTO retrieval_snapshots (
                        id, message_id, session_id, vault_id, query, retrieval_mode, embedding_model_id, created_at
                    )
                    VALUES (?, ?, 'session-batch', 'vault-1', 'q', 'semantic', 'hash', ?)
                    """,
                    (f"snapshot-{index}", message_id, created_at),
                )
                conn.execute(
                    """
                    INSERT INTO retrieval_snapshot_items (
                        id, snapshot_id, source_id, source_title_at_answer_time, short_snippet_excerpt,
                        relevance_score, item_rank, created_at
                    )
                    VALUES (?, ?, NULL, ?, ?, 1, 1, ?)
                    """,
                    (f"item-{index}", f"snapshot-{index}", f"Source {index}", f"snippet {index}", created_at),
                )

        query_log: list[str] = []

        class RecordingConnection:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, params=()):
                query_log.append(str(sql))
                return self._inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        class RecordingConnect:
            def __enter__(self_inner):
                self_inner._ctx = connect()
                inner = self_inner._ctx.__enter__()
                self_inner._wrapped = RecordingConnection(inner)
                return self_inner._wrapped

            def __exit__(self_inner, exc_type, exc, tb):
                return self_inner._ctx.__exit__(exc_type, exc, tb)

        with patch("backend.app.api.routes.chat.connect", return_value=RecordingConnect()):
            session = get_chat_session("session-batch", limit=3)

        self.assertEqual(len(session["messages"]), 3)
        self.assertTrue(all(message["citations"] for message in session["messages"]))
        snapshot_queries = [sql for sql in query_log if "FROM retrieval_snapshots" in sql]
        self.assertEqual(len(snapshot_queries), 1)
        self.assertIn("WHERE message_id IN", snapshot_queries[0])
        self.assertFalse(any("WHERE message_id = ?" in sql for sql in snapshot_queries))

    def test_bridge_operator_lists_are_bounded_and_preserve_order(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.bridge import (
            create_bridge_client,
            list_bridge_captures,
            list_bridge_clients,
            list_bridge_requests,
            list_bridge_writeback_reviews,
            update_bridge_settings,
        )
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeClientCreate, BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        created_ids: list[str] = []
        for index in range(4):
            created = create_bridge_client(
                BridgeClientCreate(
                    name=f"Client {index}",
                    allowed_vault_ids=["vault-1", "vault-1"],
                )
            )
            created_ids.append(created["id"])

        with connect() as conn:
            for index, client_id in enumerate(created_ids):
                conn.execute(
                    "UPDATE bridge_clients SET updated_at = ? WHERE id = ?",
                    (f"2026-06-14T00:00:0{index}Z", client_id),
                )
            conn.execute(
                """
                INSERT INTO bridge_requests (
                    id, client_id, client_name, query, mode, decision, source_count, response_bytes, created_at
                )
                VALUES
                    ('req-1', NULL, 'alpha', 'q1', 'context', 'allowed', 1, 10, '2026-06-14T00:00:01Z'),
                    ('req-2', NULL, 'beta', 'q2', 'context', 'allowed', 1, 10, '2026-06-14T00:00:02Z'),
                    ('req-3', NULL, 'gamma', 'q3', 'context', 'allowed', 1, 10, '2026-06-14T00:00:03Z')
                """
            )
            review_sources = [
                (
                    f"bridge-source-{index:03d}",
                    "vault-1",
                    None,
                    f"Bridge Capture {index:03d}",
                    "external_transcript",
                    "indexed",
                    "",
                    "",
                    "",
                    "bridge_capture",
                    "external_capture",
                    "[]",
                    "{}",
                    f"raw bridge text {index}",
                    f"raw bridge text {index}",
                    "",
                    "[]",
                    None,
                    None,
                    f"2026-06-14T00:{index // 60:02d}:{index % 60:02d}+00:00",
                    f"2026-06-14T00:{index // 60:02d}:{index % 60:02d}+00:00",
                )
                for index in range(205)
            ]
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, original_path, url,
                    checksum, provenance, trust_tier, security_labels, parser_security_json,
                    raw_text, extracted_text, summary, tags, cover_image_url, deleted_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                review_sources,
            )
            review_rows = [
                (
                    f"bridge-review-{index:03d}",
                    f"bridge-source-{index:03d}",
                    "vault-1",
                    f"context-{index:03d}",
                    "ungrounded",
                    "[]",
                    0,
                    f"2026-06-14T01:{index // 60:02d}:{index % 60:02d}+00:00",
                    f"2026-06-14T01:{index // 60:02d}:{index % 60:02d}+00:00",
                )
                for index in range(205)
            ]
            conn.executemany(
                """
                INSERT INTO bridge_writeback_reviews (
                    id, source_id, vault_id, context_request_id, quality_state, reasons_json,
                    approved, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                review_rows,
            )

        client_page = list_bridge_clients(limit=2, offset=1)
        request_page = list_bridge_requests(limit=2, offset=1)
        clamped_clients = list_bridge_clients(limit=500, offset=-2)
        review_page = list_bridge_writeback_reviews(vault_id="vault-1", pending_only=True, limit=2, offset=1)
        clamped_reviews = list_bridge_writeback_reviews(vault_id="vault-1", pending_only=True, limit=500)
        capture_page = list_bridge_captures(vault_id="vault-1", limit=2, offset=203)

        self.assertEqual(len(client_page), 2)
        self.assertEqual(client_page[0]["id"], created_ids[2])
        self.assertEqual(client_page[1]["id"], created_ids[1])
        self.assertEqual(client_page[0]["allowed_vault_ids"], ["vault-1"])
        self.assertEqual([item["id"] for item in request_page], ["req-2", "req-1"])
        self.assertEqual(len(clamped_clients), 4)
        self.assertEqual(clamped_clients[0]["id"], created_ids[3])
        self.assertEqual([item["source_id"] for item in review_page], ["bridge-source-203", "bridge-source-202"])
        self.assertEqual(len(clamped_reviews), 200)
        self.assertEqual([item["source_id"] for item in capture_page], ["bridge-source-001", "bridge-source-000"])
        with self.assertRaises(HTTPException) as missing_review_vault:
            list_bridge_writeback_reviews(vault_id="vault-missing")
        self.assertEqual(missing_review_vault.exception.status_code, 404)
        self.assertEqual(missing_review_vault.exception.detail, "vault_not_found")
        with self.assertRaises(HTTPException) as missing_capture_vault:
            list_bridge_captures(vault_id="vault-missing")
        self.assertEqual(missing_capture_vault.exception.status_code, 404)
        self.assertEqual(missing_capture_vault.exception.detail, "vault_not_found")

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("function paginationQuery(options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn("listBridgeRequests(options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn("listBridgeClients(options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn(
            "listBridgeWritebackReviews(\n  vaultId?: string,\n  pendingOnly = false,\n  options: { limit?: number; offset?: number } = {},",
            backend_client,
        )
        self.assertIn("listBridgeCaptures(vaultId?: string, options: { limit?: number; offset?: number } = {})", backend_client)

    def test_bridge_client_token_lookup_uses_direct_hash_query(self) -> None:
        from backend.app.api.routes.bridge import _bridge_client_for_token, create_bridge_client, update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeClientCreate, BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        first = create_bridge_client(BridgeClientCreate(name="First", allowed_vault_ids=["vault-1"]))
        second = create_bridge_client(BridgeClientCreate(name="Second", allowed_vault_ids=["vault-1"]))
        with connect() as conn:
            conn.execute("UPDATE bridge_clients SET enabled = 0 WHERE id = ?", (first["id"],))

        query_log: list[tuple[str, tuple[object, ...] | None]] = []

        class RecordingConnection:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, params=()):
                normalized_params = tuple(params) if isinstance(params, (list, tuple)) else (params,)
                query_log.append((str(sql), normalized_params))
                return self._inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        class RecordingConnect:
            def __enter__(self_inner):
                self_inner._ctx = connect()
                inner = self_inner._ctx.__enter__()
                self_inner._wrapped = RecordingConnection(inner)
                return self_inner._wrapped

            def __exit__(self_inner, exc_type, exc, tb):
                return self_inner._ctx.__exit__(exc_type, exc, tb)

        with patch("backend.app.api.routes.bridge.connect", return_value=RecordingConnect()):
            resolved = _bridge_client_for_token(second["token"])
            missing = _bridge_client_for_token("not-a-real-token")

        self.assertEqual(resolved["id"], second["id"])
        self.assertIsNone(missing)
        bridge_queries = [
            (sql, params)
            for sql, params in query_log
            if "FROM bridge_clients" in sql
        ]
        self.assertTrue(bridge_queries)
        self.assertTrue(
            all("WHERE enabled = 1 AND token_hash = ? LIMIT 1" in sql for sql, _ in bridge_queries)
        )

    def test_safe_open_stops_redirect_loops(self) -> None:
        from backend.app.core.extraction import ExtractionError, _safe_open
        from urllib.request import Request

        class LoopingOpener:
            def open(self, request, timeout=0):
                raise HTTPError(request.full_url, 302, "loop", {"Location": "/next"}, None)

        with patch("backend.app.core.extraction.build_opener", return_value=LoopingOpener()):
            with self.assertRaises(ExtractionError) as raised:
                _safe_open(Request("https://example.com/start"), timeout=1)
        self.assertIn("Too many redirects", str(raised.exception))

    def test_mcp_backend_unreachable_maps_to_1005(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        with patch("backend.app.bridge_mcp.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/api/v1/bridge/context", request_id="1")
        self.assertEqual(raised.exception.code, 1005)

    def test_mcp_http_error_uses_registered_application_code(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        body = json.dumps({"detail": "cluster_not_allowed"}).encode("utf-8")

        class FakeHTTPError(HTTPError):
            def read(self):
                return body

        error = FakeHTTPError("http://test", 403, "forbidden", {}, None)
        with patch("backend.app.bridge_mcp.urlopen", side_effect=error):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/api/v1/bridge/context", request_id="2")
        self.assertEqual(raised.exception.code, 1004)

    def test_mcp_no_active_vault_maps_to_1001(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        body = json.dumps({"detail": "no_active_vault"}).encode("utf-8")

        class FakeHTTPError(HTTPError):
            def read(self):
                return body

        error = FakeHTTPError("http://test", 409, "conflict", {}, None)
        with patch("backend.app.bridge_mcp.urlopen", side_effect=error):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/api/v1/bridge/clusters", request_id="3")
        self.assertEqual(raised.exception.code, 1001)

    def test_token_store_is_only_local_backend_token_path_literal_in_electron_shell(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        electron_dir = repo_root / "apps" / "desktop" / "electron"
        hits: list[Path] = []
        for path in electron_dir.glob("*.cjs"):
            if path.name.endswith(".test.cjs"):
                continue
            text = path.read_text(encoding="utf-8")
            if '"backend-token"' in text or "'backend-token'" in text:
                hits.append(path)
        self.assertEqual([path.name for path in hits], ["token-store.cjs"])

    def test_contributor_requirements_keep_lora_stack_split_and_update_rule(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        backend_reqs = (repo_root / "requirements" / "contributors-backend.txt").read_text(encoding="utf-8")
        lora_reqs = (repo_root / "requirements" / "contributors-lora-trainer.txt").read_text(encoding="utf-8")
        req_readme = (repo_root / "requirements" / "README.md").read_text(encoding="utf-8")
        update_script = repo_root / "scripts" / "dev" / "update-requirements.ps1"

        self.assertNotIn("llamafactory==0.9.5", backend_reqs)
        self.assertNotIn("gradio==5.50.0", backend_reqs)
        self.assertIn("llamafactory==0.9.5", lora_reqs)
        self.assertIn("peft==0.18.1", lora_reqs)
        self.assertIn("CML_LORA_TRAINER_COMMAND", req_readme)
        self.assertIn("Continuous-update rule", req_readme)
        self.assertTrue(update_script.exists())

    def test_packaging_scripts_stage_local_ocr_runtime(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        stage_script = repo_root / "scripts" / "packaging" / "stage-ocr-runtime.ps1"
        package_script = repo_root / "scripts" / "packaging" / "package-windows.ps1"
        packaged_launch_smoke = repo_root / "scripts" / "packaging" / "smoke-packaged-app-launch.ps1"
        installed_launch_smoke = repo_root / "scripts" / "packaging" / "smoke-installed-app.ps1"
        validate_script = repo_root / "scripts" / "packaging" / "validate-clean-machine-package.ps1"
        root_main = repo_root / "apps" / "desktop" / "main.cjs"
        desktop_icon = repo_root / "apps" / "desktop" / "build" / "icon.ico"
        ocr_readme = repo_root / "backend" / "bin" / "ocr" / "README.md"

        stage_text = stage_script.read_text(encoding="utf-8")
        package_text = package_script.read_text(encoding="utf-8")
        packaged_launch_text = packaged_launch_smoke.read_text(encoding="utf-8")
        installed_launch_text = installed_launch_smoke.read_text(encoding="utf-8")
        validate_text = validate_script.read_text(encoding="utf-8")
        root_main_text = root_main.read_text(encoding="utf-8")
        readme_text = ocr_readme.read_text(encoding="utf-8")

        self.assertIn("tessdata_fast/main/eng.traineddata", stage_text)
        self.assertIn("repos/qpdf/qpdf/releases/latest", stage_text)
        self.assertIn("repos/ArtifexSoftware/ghostpdl-downloads/releases/latest", stage_text)
        self.assertIn("TesseractExePath", stage_text)
        self.assertIn("GhostscriptExePath", stage_text)
        self.assertIn("Find-InstalledTesseract", stage_text)
        self.assertIn("Find-InstalledGhostscript", stage_text)
        self.assertIn("Test-TesseractExecutable", stage_text)
        self.assertIn("Test-GhostscriptExecutable", stage_text)
        self.assertIn("Copy-GhostscriptRuntime", stage_text)
        self.assertIn("SkipGhostscriptInstaller", stage_text)
        self.assertIn("GhostscriptInstallTimeoutSeconds", stage_text)
        self.assertIn('Copy-Item -Path (Join-Path $tesseractDir "*")', stage_text)
        self.assertIn("Staging OCR runtime", package_text)
        self.assertIn("AllowPartialOcrRuntime", package_text)
        self.assertIn("SkipGhostscriptInstaller", package_text)
        self.assertIn("TesseractExePath", package_text)
        self.assertIn("GhostscriptExePath", package_text)
        self.assertIn("$ocrArgs = @{}", package_text)
        self.assertIn('$ocrArgs["TesseractExePath"]', package_text)
        self.assertIn('$ocrArgs["GhostscriptExePath"]', package_text)
        self.assertIn('fastapi==0.136.3', package_text)
        self.assertIn('uvicorn[standard]==0.48.0', package_text)
        self.assertIn('ocrmypdf==17.5.0', package_text)
        self.assertIn('sentence-transformers==5.5.1', package_text)
        self.assertIn('transformers==5.6.0', package_text)
        self.assertIn('peft==0.18.1', package_text)
        self.assertIn('$effectiveBackendRuntimePackages = @($backendRuntimePackages)', package_text)
        self.assertIn('python-runtime-v6', package_text)
        self.assertIn('Embedding runtime is included in the staged backend runtime fingerprint', package_text)
        self.assertIn("renderer ready signal received", packaged_launch_text)
        self.assertIn("renderer ready signal received", installed_launch_text)
        self.assertIn("renderer never signaled readiness", packaged_launch_text)
        self.assertIn("renderer never signaled readiness", installed_launch_text)
        self.assertIn("InstallerTimeoutSeconds", installed_launch_text)
        self.assertIn("Timed out waiting for installer", installed_launch_text)
        self.assertIn("installer_autostart_processes_stopped", installed_launch_text)
        self.assertIn("ELECTRON_RUN_AS_NODE", installed_launch_text)
        self.assertIn("[switch]$RunExecutableSmokes", validate_text)
        self.assertIn("[string]$InstallerPath", validate_text)
        self.assertIn("smoke-windows-installer.ps1", validate_text)
        self.assertEqual(root_main_text.strip(), 'module.exports = require("./electron/main.cjs");')
        icon_header = desktop_icon.read_bytes()[:6]
        self.assertEqual(icon_header[:4], b"\x00\x00\x01\x00")
        self.assertGreaterEqual(int.from_bytes(icon_header[4:6], "little"), 1)
        self.assertIn("scripts/packaging/stage-ocr-runtime.ps1", readme_text)

    def test_ocr_benchmark_script_reports_similarity_metrics(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        benchmark_script = repo_root / "scripts" / "ocr" / "benchmark-ocr.ps1"
        text = benchmark_script.read_text(encoding="utf-8")

        self.assertIn("Normalized sequence similarity", text)
        self.assertIn("Word recall", text)
        self.assertIn("Word precision", text)
        self.assertIn("extract_pages_from_path", text)

    def test_security_validator_blocks_localhost_and_private_targets(self) -> None:
        from backend.app.core.network_security import NetworkSecurityError, validate_public_http_url

        with self.assertRaises(NetworkSecurityError):
            validate_public_http_url("http://localhost/secret")

        fake_public = [(None, None, None, None, ("93.184.216.34", 80))]
        fake_private = [(None, None, None, None, ("0.0.0.0", 80))]
        fake_ipv6_loopback = [(None, None, None, None, ("::ffff:127.0.0.1", 80, 0, 0))]

        with patch("socket.getaddrinfo", return_value=fake_public):
            validate_public_http_url("http://example.com")
        with patch("socket.getaddrinfo", return_value=fake_private):
            with self.assertRaises(NetworkSecurityError):
                validate_public_http_url("http://example.com")
        with patch("socket.getaddrinfo", return_value=fake_ipv6_loopback):
            with self.assertRaises(NetworkSecurityError):
                validate_public_http_url("http://example.com")

    def test_huggingface_url_validator_is_strict(self) -> None:
        from backend.app.core.network_security import NetworkSecurityError, validate_huggingface_url

        validate_huggingface_url("https://huggingface.co/foo/bar")
        with self.assertRaises(NetworkSecurityError):
            validate_huggingface_url("http://huggingface.co/foo/bar")
        with self.assertRaises(NetworkSecurityError):
            validate_huggingface_url("https://example.com/foo/bar")

    def test_extra_patch_field_does_not_mutate_vault(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", "C:\\vault", now, now),
            )

        client = self._client()
        try:
            client.patch("/api/v1/vaults/vault-1", json={"database_path": "C:\\evil.sqlite3"})
        finally:
            client.close()

    def test_create_vault_is_idempotent_for_same_onboarding_folder_retry(self) -> None:
        vault_path = str(Path(self.tmp.name) / "Library")
        client = self._client()
        try:
            first = client.post("/api/v1/vaults", json={"name": "My Library", "path": vault_path})
            second = client.post(
                "/api/v1/vaults",
                json={"name": "My Library Retry", "path": str(Path(vault_path) / ".." / "Library")},
            )
            listed = client.get("/api/v1/vaults")
        finally:
            client.close()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(second.json()["name"], "My Library")
        self.assertEqual(len(listed.json()), 1)

    def test_update_vault_rejects_path_collision_with_existing_library(self) -> None:
        first_path = str(Path(self.tmp.name) / "LibraryA")
        second_path = str(Path(self.tmp.name) / "LibraryB")
        client = self._client()
        try:
            first = client.post("/api/v1/vaults", json={"name": "First", "path": first_path})
            second = client.post("/api/v1/vaults", json={"name": "Second", "path": second_path})
            collision = client.patch(
                f"/api/v1/vaults/{second.json()['id']}",
                json={"path": str(Path(first_path) / ".." / "LibraryA")},
            )
            listed = client.get("/api/v1/vaults")
        finally:
            client.close()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(collision.status_code, 409)
        self.assertIn("already uses this path", collision.json()["detail"])
        rows = {row["id"]: row for row in listed.json()}
        self.assertEqual(rows[second.json()["id"]]["path"], second_path)

    def test_source_url_ingestion_validates_destination_before_network_extraction(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.db_path.parent), now, now),
            )

        client = self._client()
        try:
            with patch(
                "backend.app.api.routes.sources.extract_text_from_url_with_security",
                side_effect=AssertionError("network extraction should not run"),
            ):
                missing_vault = client.post(
                    "/api/v1/sources/from-url",
                    json={"vault_id": "vault-missing", "url": "https://example.com"},
                )
                missing_cluster = client.post(
                    "/api/v1/sources/from-url",
                    json={"vault_id": "vault-1", "cluster_id": "cluster-missing", "url": "https://example.com"},
                )
        finally:
            client.close()

        self.assertEqual(missing_vault.status_code, 404)
        self.assertEqual(missing_vault.json()["detail"], "Vault not found")
        self.assertEqual(missing_cluster.status_code, 404)
        self.assertEqual(missing_cluster.json()["detail"], "Cluster not found")

    def test_source_file_ingestion_validates_destination_before_quarantine_work(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.db_path.parent), now, now),
            )

        client = self._client()
        try:
            with patch(
                "backend.app.api.routes.sources.ingest_file_through_quarantine",
                side_effect=AssertionError("quarantine should not run"),
            ):
                missing_vault = client.post(
                    "/api/v1/sources/from-path",
                    json={"vault_id": "vault-missing", "path": str(Path(self.tmp.name) / "note.txt")},
                )
                missing_cluster = client.post(
                    "/api/v1/sources/from-path",
                    json={
                        "vault_id": "vault-1",
                        "cluster_id": "cluster-missing",
                        "path": str(Path(self.tmp.name) / "note.txt"),
                    },
                )
        finally:
            client.close()

        self.assertEqual(missing_vault.status_code, 404)
        self.assertEqual(missing_vault.json()["detail"], "Vault not found")
        self.assertEqual(missing_cluster.status_code, 404)
        self.assertEqual(missing_cluster.json()["detail"], "Cluster not found")

    def test_query_cache_create_rejects_missing_vault_without_side_effect(self) -> None:
        from backend.app.core.database import connect

        client = self._client()
        try:
            response = client.post(
                "/api/v1/search/query-cache",
                params={"vault_id": "vault-missing", "query_fingerprint": "abc123"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Vault not found")
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM query_evidence_cache").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_source_list_validates_filters_and_paginates_large_library(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.sources import list_sources
        from backend.app.core.database import connect

        now = "2026-06-19T00:00:00+00:00"
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault 1", str(Path(self.tmp.name) / "vault-1"), now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-2", "Vault 2", str(Path(self.tmp.name) / "vault-2"), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Cluster 1', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-2', 'vault-2', 'Cluster 2', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )
            rows = [
                (
                    f"source-{index:04d}",
                    "vault-1",
                    "cluster-1",
                    f"Source {index:04d}",
                    "note",
                    "indexed",
                    "",
                    "",
                    "",
                    "local_import",
                    "trusted_local",
                    "[]",
                    "{}",
                    f"body {index}",
                    f"body {index}",
                    f"summary {index}",
                    "[]",
                    None,
                    None,
                    f"2026-06-19T00:00:00+00:00.{index:04d}",
                    f"2026-06-19T00:00:00+00:00.{index:04d}",
                )
                for index in range(1005)
            ]
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, original_path, url,
                    checksum, provenance, trust_tier, security_labels, parser_security_json,
                    raw_text, extracted_text, summary, tags, cover_image_url, deleted_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        first_page = list_sources(vault_id="vault-1", limit=2000)
        tail_page = list_sources(vault_id="vault-1", limit=10, offset=1000)
        self.assertEqual(len(first_page), 1000)
        self.assertEqual(first_page[0]["id"], "source-1004")
        self.assertEqual([source["id"] for source in tail_page], [f"source-{index:04d}" for index in range(4, -1, -1)])

        with self.assertRaises(HTTPException) as missing_vault:
            list_sources(vault_id="vault-missing")
        self.assertEqual(missing_vault.exception.status_code, 404)
        self.assertEqual(missing_vault.exception.detail, "Vault not found")

        with self.assertRaises(HTTPException) as missing_cluster:
            list_sources(cluster_id="cluster-missing")
        self.assertEqual(missing_cluster.exception.status_code, 404)
        self.assertEqual(missing_cluster.exception.detail, "Cluster not found")

        with self.assertRaises(HTTPException) as cross_vault_cluster:
            list_sources(vault_id="vault-1", cluster_id="cluster-2")
        self.assertEqual(cross_vault_cluster.exception.status_code, 404)
        self.assertEqual(cross_vault_cluster.exception.detail, "Cluster not found")

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("listSources(vaultId?: string, options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn('params.set("limit", String(options.limit))', backend_client)
        self.assertIn('params.set("offset", String(options.offset))', backend_client)

    def test_semantic_search_rejects_missing_vault_before_embedding_probe(self) -> None:
        client = self._client()
        try:
            response = client.post(
                "/api/v1/search/semantic",
                json={"vault_id": "vault-missing", "query": "find my notes", "limit": 5},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Vault not found")

    def test_reindex_rejects_missing_vault_before_embedding_probe(self) -> None:
        client = self._client()
        try:
            response = client.post("/api/v1/search/reindex/vault-missing")
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Vault not found")

    def test_vector_repair_plan_rejects_missing_vault_instead_of_empty_success(self) -> None:
        client = self._client()
        try:
            response = client.get("/api/v1/search/vectors/repair-plan", params={"vault_id": "vault-missing"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Vault not found")

    def test_vector_repair_rejects_missing_vault_before_embedding_probe(self) -> None:
        client = self._client()
        try:
            response = client.post("/api/v1/search/vectors/repair", params={"vault_id": "vault-missing"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Vault not found")

    def test_vector_sidecar_actions_reject_missing_vault_before_work(self) -> None:
        client = self._client()
        try:
            responses = [
                client.get("/api/v1/search/vectors/sidecar/status", params={"vault_id": "vault-missing"}),
                client.post("/api/v1/search/vectors/sidecar/build", params={"vault_id": "vault-missing"}),
                client.get("/api/v1/search/vectors/phase-c/status", params={"vault_id": "vault-missing"}),
                client.post("/api/v1/search/vectors/phase-c/benchmark", params={"vault_id": "vault-missing"}),
            ]
        finally:
            client.close()

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Vault not found")

    def test_extension_operator_lists_are_paginated_and_validate_capture_vault(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.extension import (
            create_extension_client,
            list_extension_captures,
            list_extension_clients,
            list_extension_pairings,
            list_extension_permission_audit,
            start_extension_pairing,
        )
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionClientCreate, ExtensionPairingStartRequest

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("listExtensionClients(options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn("listExtensionPairings(options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn("listExtensionCaptures(", backend_client)
        self.assertIn("options: { limit?: number; offset?: number } = {},", backend_client)
        self.assertIn("listExtensionPermissionAudit(limit = 20, offset = 0)", backend_client)

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.db_path.parent), now, now),
            )

        created_client_ids: list[str] = []
        for index in range(5):
            client = create_extension_client(ExtensionClientCreate(name=f"Browser {index}"))
            created_client_ids.append(client["id"])
            stamp = f"2026-06-19T00:00:0{index}+00:00"
            with connect() as conn:
                conn.execute("UPDATE extension_clients SET updated_at = ? WHERE id = ?", (stamp, client["id"]))
                conn.execute(
                    """
                    INSERT INTO extension_captures (
                        id, client_id, vault_id, source_id, capture_type, title, url, status, created_at
                    )
                    VALUES (?, ?, 'vault-1', NULL, 'selection', ?, '', 'stored', ?)
                    """,
                    (f"capture-{index}", client["id"], f"Capture {index}", stamp),
                )
            start_extension_pairing(
                ExtensionPairingStartRequest(
                    name=f"Pairing {index}",
                    allowed_vault_ids=["vault-1"],
                    ttl_seconds=600,
                )
            )

        client_page = list_extension_clients(limit=2, offset=1)
        capture_page = list_extension_captures("vault-1", limit=2, offset=2)
        pairing_page = list_extension_pairings(limit=2, offset=1)
        audit_page = list_extension_permission_audit(limit=3, offset=2)

        self.assertEqual([item["id"] for item in client_page], [created_client_ids[3], created_client_ids[2]])
        self.assertEqual([item["id"] for item in capture_page], ["capture-2", "capture-1"])
        self.assertEqual(len(pairing_page), 2)
        self.assertEqual(len(audit_page), 3)
        with self.assertRaises(HTTPException) as raised:
            list_extension_captures("vault-missing")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Vault not found")

    def test_persisted_chat_context_rejects_unknown_cluster_before_creating_session(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.chat import build_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.db_path.parent), now, now),
            )

        with self.assertRaises(HTTPException) as raised:
            build_chat_context(
                ChatContextRequest(
                    vault_id="vault-1",
                    cluster_id="cluster-missing",
                    prompt="Summarize my cluster notes.",
                    persist=True,
                )
            )

        self.assertEqual(raised.exception.status_code, 404)
        with connect() as conn:
            session_count = conn.execute("SELECT COUNT(*) AS count FROM chat_sessions").fetchone()["count"]
            generation_count = conn.execute("SELECT COUNT(*) AS count FROM chat_generations").fetchone()["count"]
        self.assertEqual(session_count, 0)
        self.assertEqual(generation_count, 0)

    def test_onboarding_route_uses_internal_scroll_shell_instead_of_hidden_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        onboarding = (repo_root / "apps" / "desktop" / "src" / "routes" / "onboarding.tsx").read_text(encoding="utf-8")
        styles = (repo_root / "apps" / "desktop" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('vault-onboarding-shell h-screen overflow-x-hidden overflow-y-auto', onboarding)
        self.assertIn("prepareActiveVaultFolder", onboarding)
        self.assertIn("setActiveVaultFolder", onboarding)
        self.assertIn('min-h-0 flex-1 overflow-y-auto px-6 sm:px-8', onboarding)
        self.assertIn('lg:max-h-[calc(100vh-4rem)]', onboarding)
        self.assertNotIn('vault-onboarding-shell min-h-screen overflow-hidden', onboarding)
        self.assertIn(".vault-bg-wash", styles)
        self.assertIn("background-position: 28px 28px, 28px 28px;", styles)
        self.assertNotIn("inset: -20%", styles)
        self.assertNotIn("inset: -8%", styles)

    def test_onboarding_model_download_flow_exposes_location_progress_and_continue(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        onboarding = (repo_root / "apps" / "desktop" / "src" / "routes" / "onboarding.tsx").read_text(encoding="utf-8")
        settings = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.settings.tsx").read_text(encoding="utf-8")
        backend = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")

        self.assertIn('Field label="LLM download location"', onboarding)
        self.assertIn("chooseModelDownloadFolder", onboarding)
        self.assertIn("target_dir: modelDownloadRoot.trim() || null", onboarding)
        self.assertIn("ModelDownloadToast", onboarding)
        self.assertIn("fixed bottom-4 right-4", onboarding)
        self.assertIn("setInterval", onboarding)
        self.assertIn("function isChatSetupProgress", onboarding)
        self.assertIn('model.source_kind === "default_choice"', onboarding)
        self.assertIn('downloadStatus === "resolving" || downloadStatus === "downloading"', onboarding)
        self.assertIn("function selectVisibleModelDownload", onboarding)
        self.assertIn("visible.find((download) => isActiveModelDownloadStatus(download.status))", onboarding)
        self.assertIn('state.status === "failed" || state.status === "blocked"', onboarding)
        self.assertIn("model.download?.progress_percent", onboarding)
        self.assertIn("model.download?.total_bytes ?? model.download?.bytes_total", onboarding)
        self.assertIn("model.compatibility?.chat_role_accepted", onboarding)
        self.assertIn("refreshDetectedModels(true)", onboarding)
        self.assertIn("You can continue after a chat model is installed, active, or downloading.", onboarding)
        self.assertNotIn("Continue is enabled only after one accepted chat model and one accepted expert checkpoint are active.", onboarding)
        self.assertIn("LLM download location", settings)
        self.assertIn("target_dir: modelDownloadRoot.trim() || null", settings)
        self.assertIn("ModelDownloadToast", settings)
        self.assertIn("progress_percent", settings)
        self.assertIn("discoverInstalledModels({ max_results: 24, refresh: true })", settings)
        self.assertIn('showSection("models")', settings)
        self.assertIn('showSection("embeddings")', settings)
        self.assertIn('showSection("ocr")', settings)
        self.assertIn('showSection("storage")', settings)
        self.assertIn('showSection("privacy")', settings)
        self.assertIn('showSection("diagnostics", "advanced")', settings)
        self.assertIn("Settings section", settings)
        self.assertIn('htmlFor="settings-section-select"', settings)
        self.assertIn('id="settings-section-select"', settings)
        self.assertIn("xl:hidden", settings)
        self.assertIn("settingsSections.map((section)", settings)
        self.assertNotIn(" Â· ", settings)
        self.assertNotIn(" · ", settings)
        self.assertNotIn(" Â· ", onboarding)
        self.assertNotIn(" · ", onboarding)
        self.assertIn("payload?: { target_dir?: string | null }", backend)
        self.assertIn("refresh?: boolean", backend)
        self.assertIn('query.set("refresh", "true")', backend)
        self.assertIn("body: JSON.stringify(payload ?? {})", backend)

    def test_bridge_route_wraps_long_operator_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        bridge = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.bridge.tsx").read_text(encoding="utf-8")

        self.assertIn("max-w-4xl px-4 py-8 sm:px-6 lg:px-8", bridge)
        self.assertIn("flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between", bridge)
        self.assertIn("max-w-full break-all rounded-md bg-muted", bridge)
        self.assertIn("break-all font-mono text-xs", bridge)
        self.assertIn("Path {item.observed_executable_path", bridge)
        self.assertIn("Path {client.observed_executable_path", bridge)
        self.assertIn("mt-1 break-all text-xs text-muted-foreground", bridge)
        self.assertIn("mt-1 break-words text-xs text-muted-foreground", bridge)
        self.assertIn("sm:grid-cols-[minmax(0,1fr)_auto]", bridge)
        self.assertIn("lg:grid-cols-[minmax(0,1fr)_auto]", bridge)
        self.assertIn("grid gap-1 py-2 sm:grid-cols-[120px_minmax(0,1fr)_90px]", bridge)
        self.assertIn("flex flex-wrap gap-2", bridge)
        self.assertIn("flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between", bridge)
        self.assertNotIn("grid-cols-[1fr_auto]", bridge)
        self.assertNotIn("grid-cols-[120px_1fr_90px]", bridge)
        self.assertNotIn("flex items-center justify-between", bridge)

    def test_timeline_route_stacks_detail_panel_and_wraps_long_activity_text(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        timeline = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.timeline.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", timeline)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_320px] xl:overflow-hidden", timeline)
        self.assertIn("px-4 py-6 sm:px-6 lg:px-8", timeline)
        self.assertIn("md:grid-cols-[minmax(0,1fr)_auto]", timeline)
        self.assertIn("sm:grid-cols-[96px_32px_minmax(0,1fr)]", timeline)
        self.assertIn("md:grid-cols-[116px_32px_minmax(0,1fr)]", timeline)
        self.assertIn("xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)]", timeline)
        self.assertIn("break-words text-xl", timeline)
        self.assertIn("break-words text-sm", timeline)
        self.assertIn("break-all sm:text-right", timeline)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_320px] overflow-hidden", timeline)
        self.assertNotIn("right-panel px-6 py-8", timeline)
        self.assertNotIn("md:grid-cols-[116px_32px_1fr]", timeline)
        self.assertNotIn("md:grid-cols-[1fr_auto]", timeline)

    def test_tasks_route_contains_dense_table_and_wraps_long_job_detail(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        tasks = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.tasks.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", tasks)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_320px] xl:overflow-hidden", tasks)
        self.assertIn("px-4 py-6 sm:px-6 lg:px-8", tasks)
        self.assertIn("md:grid-cols-[minmax(0,1fr)_auto]", tasks)
        self.assertIn("overflow-x-auto", tasks)
        self.assertIn("min-w-[720px]", tasks)
        self.assertIn("grid-cols-[104px_minmax(0,1fr)_120px_112px_104px_80px]", tasks)
        self.assertIn("xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)]", tasks)
        self.assertIn("break-words text-[15px]", tasks)
        self.assertIn("break-words text-sm", tasks)
        self.assertIn("break-all sm:text-right", tasks)
        self.assertIn("mt-5 flex flex-wrap gap-2", tasks)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_320px] overflow-hidden", tasks)
        self.assertNotIn("right-panel px-6 py-8", tasks)
        self.assertNotIn("grid-cols-[104px_1fr_120px_112px_104px_80px]", tasks)
        self.assertNotIn("md:grid-cols-[1fr_auto]", tasks)

    def test_search_route_stacks_library_panel_and_wraps_long_source_content(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        search = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.search.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", search)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_320px] xl:overflow-hidden", search)
        self.assertIn("px-4 py-5 sm:px-6", search)
        self.assertIn("flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between", search)
        self.assertIn("lg:grid-cols-[minmax(0,1fr)_auto_auto]", search)
        self.assertIn("mb-4 break-words rounded-md border", search)
        self.assertIn("border-t border-border bg-card/55 p-4 sm:p-5 xl:border-l xl:border-t-0", search)
        self.assertIn("break-all text-right font-medium", search)
        self.assertIn('DialogTitle className="break-words"', search)
        self.assertIn("flex flex-col gap-2 sm:flex-row", search)
        self.assertIn('className="min-w-0"', search)
        self.assertIn("break-words rounded-md border border-border bg-muted/35", search)
        self.assertIn("max-w-full break-words rounded-md", search)
        self.assertIn("flex flex-wrap justify-end gap-2", search)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_320px] overflow-hidden", search)
        self.assertNotIn("flex items-start justify-between gap-6", search)
        self.assertNotIn("lg:grid-cols-[1fr_auto_auto]", search)
        self.assertNotIn("mb-4 flex items-center justify-between text-sm", search)
        self.assertNotIn("hidden border-l border-border", search)

    def test_sources_route_exposes_inspector_and_wraps_long_source_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sources = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.sources.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", sources)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_326px] xl:overflow-hidden", sources)
        self.assertIn("min-w-0 px-7 py-8 xl:overflow-y-auto", sources)
        self.assertIn("relative mr-auto min-w-0 flex-[1_1_240px] sm:max-w-sm", sources)
        self.assertIn("text-destructive break-words", sources)
        self.assertIn("text-muted-foreground break-words", sources)
        self.assertIn("overflow-x-auto", sources)
        self.assertIn("min-w-[760px] w-full text-sm", sources)
        self.assertIn("break-words font-semibold", sources)
        self.assertIn("line-clamp-2 break-words text-xs", sources)
        self.assertIn("mt-8 flex flex-col gap-3 text-sm", sources)
        self.assertIn("border-t border-border bg-card/35 px-7 py-8 xl:border-l xl:border-t-0", sources)
        self.assertIn("overflow-y-visible border-t border-border bg-card/35", sources)
        self.assertIn("flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", sources)
        self.assertIn("break-words text-lg font-semibold", sources)
        self.assertIn("mt-4 break-words text-sm leading-6", sources)
        self.assertIn("text-muted-foreground break-words", sources)
        self.assertIn("mt-2 break-words", sources)
        self.assertIn("break-words text-right", sources)
        self.assertNotIn("hidden overflow-y-auto border-l border-border", sources)
        self.assertNotIn("hidden border-l border-border bg-card/35", sources)
        self.assertNotIn("grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[1fr_326px]", sources)
        self.assertNotIn("relative mr-auto min-w-[240px] max-w-sm flex-1", sources)
        self.assertNotIn("truncate font-semibold", sources)
        self.assertNotIn("mt-1 truncate text-xs", sources)
        self.assertNotIn("mt-8 flex items-center justify-between text-sm", sources)

    def test_cluster_detail_loads_expert_status_and_wraps_long_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        cluster_detail = (
            repo_root / "apps" / "desktop" / "src" / "routes" / "_app.clusters.$clusterId.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("const [sourceRows, chatRows, jobRows, artifactRows, statusRow] = await Promise.all", cluster_detail)
        self.assertIn("getClusterExpertStatus(clusterRow.id).catch(() => null)", cluster_detail)
        self.assertIn("setExpertStatus(statusRow)", cluster_detail)
        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", cluster_detail)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_326px] xl:overflow-hidden", cluster_detail)
        self.assertIn("px-4 py-6 sm:px-6 lg:px-9 xl:overflow-y-auto", cluster_detail)
        self.assertIn("page-title break-words", cluster_detail)
        self.assertIn("overflow-x-auto border-b border-border", cluster_detail)
        self.assertIn("min-w-[520px]", cluster_detail)
        self.assertIn("min-w-[560px]", cluster_detail)
        self.assertIn("break-words text-muted-foreground", cluster_detail)
        self.assertIn("grid-cols-1 gap-3 rounded-md border", cluster_detail)
        self.assertIn("sm:grid-cols-[minmax(0,1fr)_104px_112px]", cluster_detail)
        self.assertIn("sm:grid-cols-[minmax(0,1fr)_132px_20px]", cluster_detail)
        self.assertIn("flex flex-col gap-3 border-b border-border pb-4", cluster_detail)
        self.assertIn("flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", cluster_detail)
        self.assertIn("break-all font-mono text-[11px]", cluster_detail)
        self.assertIn("grid grid-cols-1 gap-2 px-4 py-3 text-sm", cluster_detail)
        self.assertIn("w-[min(190px,78vw)]", cluster_detail)
        self.assertIn("w-[min(164px,44vw)]", cluster_detail)
        self.assertIn("line-clamp-2 break-words font-medium", cluster_detail)
        self.assertIn("border-t border-border bg-card/35 px-4 py-6", cluster_detail)
        self.assertIn("grid grid-cols-2 gap-4 sm:grid-cols-4", cluster_detail)
        self.assertNotIn("setExpertStatus(statusRow);\n      } catch", cluster_detail.split("statusRow] = await Promise.all")[0])
        self.assertNotIn("grid h-full grid-cols-[minmax(0,1fr)_326px] overflow-hidden", cluster_detail)
        self.assertNotIn("right-panel px-6 py-8", cluster_detail)
        self.assertNotIn("grid-cols-[1.4fr_1fr_72px]", cluster_detail)
        self.assertNotIn("grid-cols-[1fr_44px_92px_72px]", cluster_detail)
        self.assertNotIn("grid-cols-[1fr_48px_120px_20px]", cluster_detail)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_104px_112px] items-center", cluster_detail)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_132px_20px] items-center", cluster_detail)
        self.assertNotIn('className="right-panel', cluster_detail)
        self.assertNotIn("block truncate font-medium", cluster_detail)
        self.assertNotIn("max-w-full truncate", cluster_detail)

    def test_map_route_stacks_detail_rail_and_wraps_long_graph_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        map_route = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.map.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", map_route)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_326px] xl:overflow-hidden", map_route)
        self.assertIn("px-4 py-6 sm:px-6 lg:px-8 xl:overflow-y-auto", map_route)
        self.assertIn("w-full items-center gap-2", map_route)
        self.assertIn("sm:w-[220px]", map_route)
        self.assertIn("h-[520px] overflow-hidden", map_route)
        self.assertIn("sm:h-[660px]", map_route)
        self.assertIn("flex flex-col gap-2 text-xs sm:flex-row", map_route)
        self.assertIn("sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5", map_route)
        self.assertIn("border-t border-border bg-card/35 px-4 py-6", map_route)
        self.assertIn("min-w-0 flex-1 break-words text-lg font-semibold", map_route)
        self.assertIn("max-w-[44vw]", map_route)
        self.assertIn("width: `min(${node.w ?? 170}px, 44vw)`", map_route)
        self.assertIn('width: "min(190px, 78vw)"', map_route)
        self.assertIn('width: "min(150px, 42vw)"', map_route)
        self.assertIn("line-clamp-2 break-words text-sm font-semibold", map_route)
        self.assertIn("line-clamp-2 break-words text-xs font-medium", map_route)
        self.assertIn("grid grid-cols-2 gap-4 sm:grid-cols-4", map_route)
        self.assertIn("flex w-full min-w-0 items-center gap-3", map_route)
        self.assertNotIn("grid h-full grid-cols-[minmax(0,1fr)_326px] overflow-hidden", map_route)
        self.assertNotIn("right-panel px-7 py-8", map_route)
        self.assertNotIn("width: node.w ?? 170", map_route)
        self.assertNotIn("width: 190", map_route)
        self.assertNotIn("width: 150", map_route)
        self.assertNotIn("block truncate text-sm font-medium", map_route)
        self.assertNotIn("truncate text-xs font-medium", map_route)
        self.assertNotIn("mt-1 truncate text-[11px]", map_route)
        self.assertNotIn("grid grid-cols-4 gap-4", map_route)

    def test_clusters_route_exposes_inspector_and_wraps_long_cluster_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        clusters = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.clusters.tsx").read_text(
            encoding="utf-8",
        )

        self.assertIn("xl:grid-cols-[minmax(0,1fr)_340px]", clusters)
        self.assertIn("min-w-0 px-4 py-6 sm:px-7 sm:py-8", clusters)
        self.assertIn("page-title flex flex-wrap items-center gap-3", clusters)
        self.assertIn("vault-card mt-5 break-words", clusters)
        self.assertIn("overflow-x-auto", clusters)
        self.assertIn("min-w-[760px]", clusters)
        self.assertIn("grid-cols-[minmax(0,1fr)_96px_96px_140px_32px]", clusters)
        self.assertIn("break-words text-sm font-semibold", clusters)
        self.assertIn("line-clamp-2 break-words text-sm text-muted-foreground", clusters)
        self.assertIn("flex flex-col gap-3 px-4 py-3 sm:flex-row", clusters)
        self.assertIn("flex shrink-0 flex-wrap items-center gap-2", clusters)
        self.assertIn("border-t border-border bg-card/35 px-4 py-6", clusters)
        self.assertIn("xl:sticky xl:top-8", clusters)
        self.assertIn("min-w-0 break-words text-base font-semibold", clusters)
        self.assertIn("mt-1 break-words text-muted-foreground", clusters)
        self.assertIn("line-clamp-2 break-words font-medium", clusters)
        self.assertIn("break-words text-xl font-semibold tabular-nums", clusters)
        self.assertNotIn("hidden border-l border-border bg-card/35", clusters)
        self.assertNotIn("grid-cols-[1fr_96px_96px_140px_32px]", clusters)
        self.assertNotIn("truncate text-sm font-semibold", clusters)
        self.assertNotIn("mt-1 truncate text-sm", clusters)
        self.assertNotIn("truncate text-sm font-medium", clusters)
        self.assertNotIn("flex items-center justify-between gap-4 px-4 py-3", clusters)

    def test_chat_landing_stacks_panels_and_wraps_long_chat_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        chat = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.chat.tsx").read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", chat)
        self.assertIn("lg:grid-cols-[260px_minmax(0,1fr)]", chat)
        self.assertIn("xl:grid-cols-[320px_minmax(0,1fr)_326px] xl:overflow-hidden", chat)
        self.assertIn("border-b border-border bg-card/35 px-4 py-4", chat)
        self.assertIn("max-h-56 space-y-1 overflow-y-auto lg:max-h-none", chat)
        self.assertIn("min-w-0 flex-1 break-words px-3 py-2 text-sm", chat)
        self.assertIn("px-4 py-5 sm:px-6 lg:px-10", chat)
        self.assertIn("mb-2 break-words rounded-md border", chat)
        self.assertIn("h-8 w-full min-w-0 gap-2", chat)
        self.assertIn("gap-2 sm:ml-auto", chat)
        self.assertIn("max-w-full break-all rounded-md", chat)
        self.assertIn("border-t border-border bg-card/35 px-4 py-6", chat)
        self.assertIn("min-w-0 flex-1 break-words text-lg font-semibold", chat)
        self.assertIn("flex w-full min-w-0 items-center gap-3", chat)
        self.assertIn("break-words font-semibold", chat)
        self.assertNotIn("grid h-full grid-cols-[320px_minmax(0,1fr)_326px] overflow-hidden", chat)
        self.assertNotIn("min-w-0 flex-1 truncate", chat)
        self.assertNotIn("right-panel", chat)
        self.assertNotIn("overflow-y-auto border-l border-border bg-card/35 px-7 py-8", chat)
        self.assertNotIn("className=\"ml-auto gap-2\"", chat)

    def test_chat_detail_stacks_context_and_wraps_long_message_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        chat_detail = (
            repo_root / "apps" / "desktop" / "src" / "routes" / "_app.chat.$chatId.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", chat_detail)
        self.assertIn("lg:grid-cols-[240px_minmax(0,1fr)]", chat_detail)
        self.assertIn("xl:grid-cols-[256px_minmax(0,1fr)_320px] xl:overflow-hidden", chat_detail)
        self.assertIn("border-b border-border bg-card/30 p-2", chat_detail)
        self.assertIn("max-h-48 space-y-0.5 overflow-y-auto lg:max-h-none", chat_detail)
        self.assertIn("block break-words rounded-md px-2.5 py-1.5 text-sm", chat_detail)
        self.assertIn("h-8 w-full gap-2 text-xs sm:w-52", chat_detail)
        self.assertIn("flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto", chat_detail)
        self.assertIn("grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]", chat_detail)
        self.assertIn("border-t border-border bg-card/20 p-4", chat_detail)
        self.assertIn("break-words text-sm font-medium", chat_detail)
        self.assertIn("line-clamp-4 break-words text-xs", chat_detail)
        self.assertIn("li key={warning} className=\"break-words\"", chat_detail)
        self.assertIn("max-w-full break-all rounded-md", chat_detail)
        self.assertIn("mx-auto mt-1.5 max-w-3xl break-words", chat_detail)
        self.assertIn("max-w-[85%] break-words rounded-md", chat_detail)
        self.assertIn("whitespace-pre-wrap break-words text-sm", chat_detail)
        self.assertIn("inline-flex max-w-full items-center gap-1", chat_detail)
        self.assertIn("PopoverContent className=\"w-80 max-w-[calc(100vw-2rem)] text-xs\"", chat_detail)
        self.assertIn("mt-3 flex flex-wrap items-center gap-1", chat_detail)
        self.assertNotIn("hidden w-64", chat_detail)
        self.assertNotIn("hidden w-80", chat_detail)
        self.assertNotIn("block truncate rounded-md", chat_detail)
        self.assertNotIn("w-52 gap-2 text-xs", chat_detail)
        self.assertNotIn("ml-auto flex items-center gap-2", chat_detail)
        self.assertNotIn("truncate text-sm font-medium", chat_detail)
        self.assertNotIn("PopoverContent className=\"w-80 text-xs\"", chat_detail)

    def test_home_shell_and_cluster_map_wrap_long_user_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        home = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.home.tsx").read_text(
            encoding="utf-8",
        )
        shell = (repo_root / "apps" / "desktop" / "src" / "components" / "AppShell.tsx").read_text(
            encoding="utf-8",
        )
        styles = (repo_root / "apps" / "desktop" / "src" / "styles.css").read_text(encoding="utf-8")
        cluster_map = (repo_root / "apps" / "desktop" / "src" / "components" / "ClusterMap.tsx").read_text(
            encoding="utf-8",
        )

        self.assertIn("grid h-full grid-cols-1 overflow-y-auto", home)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_326px] xl:overflow-hidden", home)
        self.assertIn("px-4 py-6 sm:px-8 sm:py-10", home)
        self.assertIn("flex flex-wrap items-center gap-3 px-1 pb-1", home)
        self.assertIn("line-clamp-2 break-words text-sm font-semibold", home)
        self.assertIn("break-words text-sm font-semibold", home)
        self.assertIn("line-clamp-2 break-words text-xs text-muted-foreground", home)
        self.assertIn("max-w-[36%] break-words text-right", home)
        self.assertIn("border-t border-border bg-card/35 px-4 py-6", home)
        self.assertIn("block break-words text-xs text-muted-foreground", home)
        self.assertNotIn("grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[1fr_326px]", home)
        self.assertNotIn("truncate text-sm font-semibold", home)
        self.assertNotIn("mt-1 truncate text-xs", home)
        self.assertNotIn("block truncate text-xs", home)
        self.assertNotIn("hidden overflow-y-auto border-l", home)

        self.assertIn("items-start gap-2 text-left", shell)
        self.assertIn("min-w-0 flex-1 break-all", shell)
        self.assertIn("flex min-h-7 items-start gap-2", shell)
        self.assertIn("min-w-0 flex-1 break-words", shell)
        self.assertIn("block break-words rounded-md", shell)
        self.assertIn("break-all text-[12px]", shell)
        self.assertIn("vault-footer flex shrink-0 flex-wrap", shell)
        self.assertNotIn("flex w-full items-center gap-2 truncate", shell)
        self.assertNotIn("<span className=\"truncate\">", shell)
        self.assertNotIn("block truncate rounded-md", shell)
        self.assertNotIn("truncate text-[13px]", shell)
        self.assertNotIn("truncate text-[12px]", shell)
        self.assertIn("min-height: 32px;", styles)
        self.assertNotIn("\n    height: 32px;", styles)

        self.assertIn("max-w-[min(9rem,40vw)] break-words", cluster_map)
        self.assertIn("w-[min(18rem,calc(100vw-3rem))]", cluster_map)
        self.assertIn("break-words text-sm font-medium text-foreground", cluster_map)
        self.assertIn("line-clamp-4 break-words text-xs", cluster_map)
        self.assertIn("w-[min(340px,calc(100vw-3rem))]", cluster_map)
        self.assertIn("min-w-0 break-words", cluster_map)
        self.assertNotIn("mt-2 max-w-36 text-sm", cluster_map)
        self.assertNotIn("mt-2 max-w-36 text-xs", cluster_map)
        self.assertNotIn("truncate text-sm font-medium text-foreground", cluster_map)
        self.assertNotIn("truncate text-sm font-semibold", cluster_map)
        self.assertNotIn("hidden w-[340px]", cluster_map)

    def test_extension_capture_rejects_core_api_token(self) -> None:
        os.environ["CML_API_TOKEN"] = "core-token"
        client = self._client()
        try:
            response = client.post(
                "/api/v1/extension/capture",
                headers={"x-cml-extension-token": "core-token"},
                json={
                    "vault_id": "vault-1",
                    "capture_type": "selection",
                    "title": "selection",
                    "text": "captured text",
                },
            )
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)

        self.assertEqual(response.status_code, 401)

    def test_extension_upload_rejects_core_api_token_and_invalid_base64(self) -> None:
        from backend.app.api.routes.extension import capture_uploaded_file_from_extension, create_extension_client
        from backend.app.schemas import ExtensionClientCreate, ExtensionUploadCaptureRequest

        os.environ["CML_API_TOKEN"] = "core-token"
        extension_client = create_extension_client(ExtensionClientCreate(name="browser"))
        client = self._client()
        try:
            token_response = client.post(
                "/api/v1/extension/capture-upload",
                headers={"x-cml-extension-token": "core-token"},
                json={
                    "vault_id": "vault-1",
                    "capture_type": "file",
                    "title": "notes.txt",
                    "file_name": "notes.txt",
                    "mime_type": "text/plain",
                    "content_base64": "bm90ZXM=",
                },
            )
            with self.assertRaises(Exception) as invalid_error:
                capture_uploaded_file_from_extension(
                    ExtensionUploadCaptureRequest(
                        vault_id="vault-1",
                        capture_type="file",
                        title="broken.txt",
                        file_name="broken.txt",
                        mime_type="text/plain",
                        content_base64="not-valid-base64***",
                    ),
                    x_cml_extension_token=extension_client["token"],
                )
        finally:
            client.close()
            os.environ.pop("CML_API_TOKEN", None)

        self.assertEqual(token_response.status_code, 401)
        self.assertIn("valid base64", str(invalid_error.exception))

    def test_run_migrations_detects_interrupted_running_record(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.migrations import MigrationError, run_migrations

        with connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, started_at, finished_at, status, error)
                VALUES (1, 'baseline', '2026-01-01T00:00:00+00:00', NULL, 'running', '')
                """
            )

        with self.assertRaises(MigrationError):
            run_migrations()

    def test_run_migrations_retries_failed_record_without_primary_key_collision(self) -> None:
        from backend.app.core import migrations
        from backend.app.core.database import connect

        with connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, started_at, finished_at, status, error)
                VALUES (1, 'old_failure', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00', 'failed', 'boom')
                """
            )

        original_schema_version = migrations.SCHEMA_VERSION
        original_migrations = migrations.MIGRATIONS
        try:
            migrations.SCHEMA_VERSION = 1
            migrations.MIGRATIONS = {1: lambda _conn: None}
            migrations.run_migrations()
        finally:
            migrations.SCHEMA_VERSION = original_schema_version
            migrations.MIGRATIONS = original_migrations

        with connect() as conn:
            row = conn.execute("SELECT status, error FROM schema_migrations WHERE version = 1").fetchone()
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["error"], "")

    def test_source_and_cluster_list_routes_validate_filters_and_paginate_large_libraries(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.clusters import list_clusters
        from backend.app.api.routes.sources import list_sources
        from backend.app.core.database import connect

        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES ('vault-1', 'Vault', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
                (self.tmp.name,),
            )
            for index in range(3):
                created_at = f"2026-01-01T00:00:0{index}+00:00"
                conn.execute(
                    """
                    INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                    VALUES (?, 'vault-1', ?, '', 'sage', 'setting-up', ?, ?)
                    """,
                    (f"cluster-{index}", f"Cluster {index}", created_at, created_at),
                )
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, cluster_id, title, source_type, state, raw_text,
                        extracted_text, summary, tags, created_at, updated_at
                    )
                    VALUES (?, 'vault-1', ?, ?, 'text', 'indexed', ?, ?, '', '[]', ?, ?)
                    """,
                    (
                        f"source-{index}",
                        f"cluster-{index}",
                        f"Source {index}",
                        f"Source body {index}",
                        f"Source body {index}",
                        created_at,
                        created_at,
                    ),
                )
            extra_clusters = [
                (
                    f"cluster-extra-{index:04d}",
                    f"Extra Cluster {index:04d}",
                    f"2026-01-02T00:00:00+00:00.{index:04d}",
                    f"2026-01-02T00:00:00+00:00.{index:04d}",
                )
                for index in range(1005)
            ]
            conn.executemany(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES (?, 'vault-1', ?, '', 'sage', 'setting-up', ?, ?)
                """,
                extra_clusters,
            )

        sources = list_sources(vault_id="vault-1", limit=2)
        clusters = list_clusters(vault_id="vault-1", limit=2)
        all_clusters = list_clusters(vault_id="vault-1", limit=2000)
        next_sources = list_sources(vault_id="vault-1", limit=2, offset=2)
        next_clusters = list_clusters(vault_id="vault-1", limit=3, offset=1004)

        self.assertEqual([source["id"] for source in sources], ["source-2", "source-1"])
        self.assertEqual([cluster["id"] for cluster in clusters], ["cluster-extra-1004", "cluster-extra-1003"])
        self.assertEqual(len(all_clusters), 1000)
        self.assertEqual([source["id"] for source in next_sources], ["source-0"])
        self.assertEqual(
            [cluster["id"] for cluster in next_clusters],
            ["cluster-extra-0000", "cluster-2", "cluster-1"],
        )
        with self.assertRaises(HTTPException) as missing_vault:
            list_clusters(vault_id="vault-missing")
        self.assertEqual(missing_vault.exception.status_code, 404)
        self.assertEqual(missing_vault.exception.detail, "Vault not found")

        repo_root = Path(__file__).resolve().parents[2]
        backend_client = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("listClusters(vaultId?: string, options: { limit?: number; offset?: number } = {})", backend_client)
        self.assertIn('params.set("limit", String(options.limit))', backend_client)
        self.assertIn('params.set("offset", String(options.offset))', backend_client)

    def test_source_cluster_must_belong_to_same_vault(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-a", "A", self.tmp.name, now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-b", "B", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-b', 'vault-b', 'B cluster', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )

        with self.assertRaises(Exception):
            create_source(
                SourceCreate(
                    vault_id="vault-a",
                    cluster_id="cluster-b",
                    title="cross-vault",
                    source_type="note",
                    raw_text="should fail",
                )
            )

    def test_packaged_loopback_origin_is_allowlisted_for_cors(self) -> None:
        client = self._client()
        try:
            response = client.options(
                "/api/v1/system/hardware",
                headers={
                    "Origin": "http://127.0.0.1:5174",
                    "Access-Control-Request-Method": "GET",
                },
            )
        finally:
            client.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:5174")

    def test_windows_1252_text_is_decoded_readably(self) -> None:
        from backend.app.core.extraction import extract_text_from_path

        target = Path(self.tmp.name) / "cp1252.txt"
        target.write_bytes('smart quotes “test” — café'.encode("cp1252", errors="replace"))

        _title, text = extract_text_from_path(str(target))

        self.assertIn("“test”", text)
        self.assertIn("—", text)
        self.assertIn("café", text)

    def test_mixed_windows_bytes_text_falls_back_without_crashing(self) -> None:
        from backend.app.core.extraction import extract_text_from_path

        target = Path(self.tmp.name) / "mixed-bytes.txt"
        target.write_bytes(b"status:\x81 ready\x97 bridge packet")

        _title, text = extract_text_from_path(str(target))

        self.assertIn("status:", text)
        self.assertIn("ready", text)
        self.assertIn("bridge packet", text)

    def test_large_text_file_is_split_into_multiple_pages_instead_of_failing(self) -> None:
        from backend.app.core.extraction import extract_pages_from_path

        target = Path(self.tmp.name) / "large.txt"
        target.write_text(("alpha beta gamma delta\n" * 20000).strip(), encoding="utf-8")

        title, pages = extract_pages_from_path(str(target))

        self.assertEqual(title, "large.txt")
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(page.strip() for page in pages))

    def test_unreadable_pdf_falls_back_to_metadata_text(self) -> None:
        from backend.app.core.extraction import extract_pages_from_validated_path
        from backend.app.core.ocr import OCRError

        target = Path(self.tmp.name) / "scan.pdf"
        target.write_bytes(b"%PDF-1.4\n%mock\n")

        class _EmptyReader:
            def __init__(self, *_args, **_kwargs) -> None:
                self.pages = [type("_Page", (), {"extract_text": lambda self: ""})()]

        with (
            patch("pypdf.PdfReader", _EmptyReader),
            patch("backend.app.core.pdf_pipeline.ocr_pdf_pages", side_effect=OCRError("ocr unavailable")),
        ):
            title, pages = extract_pages_from_validated_path(str(target))

        self.assertEqual(title, "scan.pdf")
        self.assertEqual(len(pages), 1)
        self.assertIn("PDF stored in vault metadata", pages[0])
        self.assertIn("scan.pdf", pages[0])

    def test_extension_capture_cluster_must_belong_to_same_vault(self) -> None:
        from backend.app.api.routes.extension import capture_from_extension, create_extension_client
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionCaptureRequest, ExtensionClientCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-a", "A", self.tmp.name, now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-b", "B", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-b', 'vault-b', 'B cluster', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )

        client = create_extension_client(ExtensionClientCreate(name="browser", allowed_vault_ids=["vault-a"]))
        with self.assertRaises(Exception):
            capture_from_extension(
                ExtensionCaptureRequest(
                    vault_id="vault-a",
                    cluster_id="cluster-b",
                    capture_type="selection",
                    title="cross vault",
                    text="should fail",
                ),
                x_cml_extension_token=client["token"],
            )

    def test_backend_token_is_not_stored_as_plaintext(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        store_path = repo_root / "apps" / "desktop" / "electron" / "token-store.cjs"
        source = store_path.read_text(encoding="utf-8")
        self.assertNotIn("writeFile(this.tokenPath, token", source)

    def test_lora_trainer_json_argv_uses_env_paths_with_spaces(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import run_lora_training_process

        dataset_dir = Path(self.tmp.name) / "dataset with spaces"
        output_dir = Path(self.tmp.name) / "adapter output with spaces"
        dataset_dir.mkdir()
        train_path = dataset_dir / "train data.jsonl"
        validation_path = dataset_dir / "validation data.jsonl"
        train_path.write_text("{}", encoding="utf-8")
        validation_path.write_text("{}", encoding="utf-8")
        script = (
            "import os, pathlib; "
            "out = pathlib.Path(os.environ['CML_LORA_OUTPUT_DIR']); "
            "out.mkdir(parents=True, exist_ok=True); "
            "(out / 'adapter_config.json').write_text('{\"peft_type\":\"LORA\",\"base_model_name_or_path\":\"test\"}', encoding='utf-8'); "
            "(out / 'adapter_model.safetensors').write_bytes(b'ok'); "
            "print(os.environ['CML_LORA_TRAIN_PATH'])"
        )
        os.environ["CML_LORA_TRAINER_COMMAND"] = json.dumps([sys.executable, "-c", script])
        get_settings.cache_clear()
        try:
            result = run_lora_training_process(
                dataset_manifest={
                    "dataset_dir": dataset_dir,
                    "train_path": train_path,
                    "validation_path": validation_path,
                },
                output_dir=output_dir,
                config={"base_model": "test-model"},
            )
        finally:
            os.environ.pop("CML_LORA_TRAINER_COMMAND", None)
            get_settings.cache_clear()

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue((output_dir / "adapter_config.json").exists())
        self.assertIn("train data.jsonl", (output_dir / "trainer.stdout.log").read_text(encoding="utf-8"))
        llamafactory_config_path = output_dir / "llamafactory-train-config.yaml"
        dataset_info = json.loads((dataset_dir / "dataset_info.json").read_text(encoding="utf-8"))
        self.assertEqual(result["llamafactory_config_path"], str(llamafactory_config_path))
        self.assertTrue(llamafactory_config_path.exists())
        self.assertEqual(dataset_info["cml_cluster_train"]["formatting"], "openai")
        self.assertEqual(dataset_info["cml_cluster_train"]["tags"]["role_tag"], "role")
        self.assertEqual(dataset_info["cml_cluster_train"]["tags"]["content_tag"], "content")

    def test_llamafactory_training_config_defaults_to_auto_hardware(self) -> None:
        from backend.app.core.lora_training import _llamafactory_training_config

        output_dir = Path(self.tmp.name) / "auto-hardware-adapter"
        output_dir.mkdir()

        payload = _llamafactory_training_config(
            dataset_manifest={"dataset_dir": Path(self.tmp.name), "train_path": Path("train.jsonl"), "validation_path": Path("validation.jsonl")},
            output_dir=output_dir,
            config={"base_model": "test-model"},
        )

        self.assertFalse(payload["use_cpu"])
        self.assertFalse(payload["fp16"])
        self.assertFalse(payload["bf16"])
        self.assertEqual(payload["eval_strategy"], "steps")
        self.assertEqual(payload["save_strategy"], "steps")
        self.assertEqual(payload["eval_steps"], 200)
        self.assertEqual(payload["save_steps"], 200)
        self.assertEqual(payload["early_stopping_steps"], 2)
        self.assertEqual(payload["save_total_limit"], 3)
        self.assertTrue(payload["load_best_model_at_end"])
        self.assertEqual(payload["metric_for_best_model"], "eval_loss")
        self.assertFalse(payload["greater_is_better"])
        self.assertEqual(payload["per_device_eval_batch_size"], 1)

    def test_llamafactory_training_config_honors_device_and_dtype_overrides(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import _llamafactory_training_config

        output_dir = Path(self.tmp.name) / "cpu-hardware-adapter"
        output_dir.mkdir()
        os.environ["CML_LORA_TRAINING_DEVICE"] = "cpu"
        os.environ["CML_LORA_TRAINING_DTYPE"] = "bf16"
        get_settings.cache_clear()
        try:
            payload = _llamafactory_training_config(
                dataset_manifest={
                    "dataset_dir": Path(self.tmp.name),
                    "train_path": Path("train.jsonl"),
                    "validation_path": Path("validation.jsonl"),
                },
                output_dir=output_dir,
                config={"base_model": "test-model"},
            )
        finally:
            os.environ.pop("CML_LORA_TRAINING_DEVICE", None)
            os.environ.pop("CML_LORA_TRAINING_DTYPE", None)
            get_settings.cache_clear()

        self.assertTrue(payload["use_cpu"])
        self.assertFalse(payload["fp16"])
        self.assertTrue(payload["bf16"])
        self.assertEqual(payload["eval_strategy"], "steps")
        self.assertEqual(payload["save_strategy"], "steps")
        self.assertEqual(payload["eval_steps"], 200)
        self.assertEqual(payload["save_steps"], 200)
        self.assertEqual(payload["early_stopping_steps"], 2)
        self.assertEqual(payload["save_total_limit"], 3)
        self.assertTrue(payload["load_best_model_at_end"])

    def test_lora_adapter_validation_rejects_incomplete_or_malformed_artifacts(self) -> None:
        from backend.app.core.lora_training import adapter_validation_report, verify_adapter_artifact

        adapter_dir = Path(self.tmp.name) / "bad-adapter"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"")

        report = adapter_validation_report(adapter_dir)

        self.assertFalse(report["valid"])
        self.assertTrue(any("peft_type=LORA" in item for item in report["errors"]))
        self.assertTrue(any("empty" in item for item in report["errors"]))
        with self.assertRaises(RuntimeError):
            verify_adapter_artifact(adapter_dir)

    def test_lora_dataset_graduation_report_enforces_source_token_and_validation_gates(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import dataset_graduation_report, graduation_contract

        os.environ["CML_LORA_MIN_SOURCES"] = "2"
        os.environ["CML_LORA_MIN_UNIQUE_SOURCES"] = "2"
        os.environ["CML_LORA_MIN_TOKENS"] = "100"
        os.environ["CML_LORA_MIN_VALIDATION_RECORDS"] = "1"
        os.environ["CML_LORA_MAX_DUPLICATE_RATIO"] = "0.10"
        get_settings.cache_clear()
        try:
            contract = graduation_contract()
            failing = dataset_graduation_report(
                {
                    "source_count": 2,
                    "unique_content_hash_count": 1,
                    "duplicate_content_ratio": 0.5,
                    "estimated_token_count": 99,
                },
                validation_count=0,
            )
            passing = dataset_graduation_report(
                {
                    "source_count": 2,
                    "unique_content_hash_count": 2,
                    "duplicate_content_ratio": 0.0,
                    "estimated_token_count": 120,
                },
                validation_count=1,
            )
        finally:
            os.environ.pop("CML_LORA_MIN_SOURCES", None)
            os.environ.pop("CML_LORA_MIN_UNIQUE_SOURCES", None)
            os.environ.pop("CML_LORA_MIN_TOKENS", None)
            os.environ.pop("CML_LORA_MIN_VALIDATION_RECORDS", None)
            os.environ.pop("CML_LORA_MAX_DUPLICATE_RATIO", None)
            get_settings.cache_clear()

        self.assertEqual(contract["minimum_estimated_tokens"], 100)
        self.assertEqual(contract["minimum_unique_sources"], 2)
        self.assertEqual(contract["maximum_duplicate_ratio"], 0.10)
        self.assertIn("adapter_invalid", contract["failure_codes"])
        self.assertFalse(failing["passes"])
        self.assertTrue(failing["checks"]["minimum_sources"])
        self.assertFalse(failing["checks"]["minimum_unique_sources"])
        self.assertFalse(failing["checks"]["minimum_estimated_tokens"])
        self.assertFalse(failing["checks"]["maximum_duplicate_ratio"])
        self.assertFalse(failing["checks"]["minimum_validation_records"])
        self.assertTrue(passing["passes"])

    def test_lora_training_dataset_exports_quality_benchmark_tasks(self) -> None:
        from backend.app.core.expert_evaluation import EVALUATION_CATEGORIES
        from backend.app.core.training_dataset import write_cluster_training_dataset

        dataset = {
            "cluster_id": "cluster-1",
            "cluster_name": "Cluster One",
            "source_count": 1,
            "unique_content_hash_count": 1,
            "duplicate_content_count": 0,
            "duplicate_content_ratio": 0.0,
            "total_text_chars": 2400,
            "estimated_token_count": 600,
            "dataset_hash": "dataset-hash",
            "documents": [
                {
                    "source_id": "source-1",
                    "title": "Public V1 Blockers",
                    "summary": "Public V1 remains blocked until adapter quality benchmark evidence passes.",
                    "text": "Public V1 remains blocked until adapter quality benchmark evidence passes.",
                    "content_hash": "content-hash",
                }
            ],
        }

        manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "lora-dataset")
        train_rows = [
            json.loads(line)
            for line in Path(manifest["train_path"]).read_text(encoding="utf-8").splitlines()
        ]
        validation_rows = [
            json.loads(line)
            for line in Path(manifest["validation_path"]).read_text(encoding="utf-8").splitlines()
        ]
        rows = train_rows + validation_rows
        prompts = [row["messages"][0]["content"] for row in rows]
        answers = [row["messages"][1]["content"] for row in rows]
        answers_by_category = {row["category"]: row["messages"][1]["content"] for row in rows}

        self.assertEqual(manifest["train_count"] + manifest["validation_count"], len(EVALUATION_CATEGORIES))
        self.assertEqual({row["category"] for row in rows}, set(EVALUATION_CATEGORIES))
        self.assertIn("benchmark_record_accounting", manifest)
        self.assertEqual(manifest["benchmark_record_accounting"]["used_source_count"], 1)
        self.assertTrue(any("key facts" in prompt for prompt in prompts))
        self.assertTrue(any("three grounded bullets" in prompt for prompt in prompts))
        self.assertTrue(any("cite the source title" in prompt for prompt in prompts))
        self.assertTrue(any("preferred terminology" in prompt for prompt in prompts))
        self.assertTrue(any("reasoning pattern" in prompt for prompt in prompts))
        self.assertTrue(any("not covered" in prompt for prompt in prompts))
        self.assertTrue(any("According to source Public V1 Blockers" in answer for answer in answers))
        self.assertTrue(any("missing evidence" in answer for answer in answers))
        self.assertTrue(any("preferred local terms" in answer for answer in answers))
        self.assertTrue(any("First, identify the local evidence" in answer for answer in answers))
        self.assertIn("Grounded takeaway:", answers_by_category["summarization"])
        self.assertIn("Key detail:", answers_by_category["summarization"])
        self.assertIn("practical note:", answers_by_category["style_transfer"])
        self.assertNotIn("```", answers_by_category["style_transfer"])
        self.assertEqual(manifest["benchmark_record_accounting"]["train"]["duplicate_content_ratio"], 0.0)
        self.assertEqual(manifest["benchmark_record_accounting"]["validation"]["duplicate_content_ratio"], 0.0)
        self.assertEqual(manifest["benchmark_record_accounting"]["train_validation_source_overlap_count"], 1)
        self.assertEqual(manifest["benchmark_record_accounting"]["train_validation_content_hash_overlap_count"], 1)

    def test_lora_training_dataset_holds_out_whole_sources_for_validation(self) -> None:
        from backend.app.core.expert_evaluation import EVALUATION_CATEGORIES
        from backend.app.core.training_dataset import write_cluster_training_dataset

        dataset = {
            "cluster_id": "cluster-1",
            "cluster_name": "Cluster One",
            "source_count": 3,
            "unique_content_hash_count": 3,
            "duplicate_content_count": 0,
            "duplicate_content_ratio": 0.0,
            "total_text_chars": 7200,
            "estimated_token_count": 1800,
            "dataset_hash": "dataset-hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Doc {index}",
                    "summary": f"Source {index} summary with enough text for export and benchmark coverage.",
                    "text": f"Source {index} summary with enough text for export and benchmark coverage.",
                    "content_hash": f"content-hash-{index}",
                }
                for index in range(3)
            ],
        }

        manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "heldout-sources-dataset")
        train_rows = [
            json.loads(line)
            for line in Path(manifest["train_path"]).read_text(encoding="utf-8").splitlines()
        ]
        validation_rows = [
            json.loads(line)
            for line in Path(manifest["validation_path"]).read_text(encoding="utf-8").splitlines()
        ]

        train_sources = {row["source_id"] for row in train_rows}
        validation_sources = {row["source_id"] for row in validation_rows}
        train_hashes = {row["content_hash"] for row in train_rows}
        validation_hashes = {row["content_hash"] for row in validation_rows}

        self.assertEqual(train_sources & validation_sources, set())
        self.assertEqual(train_hashes & validation_hashes, set())
        self.assertEqual(
            manifest["benchmark_record_accounting"]["train_validation_source_overlap_count"],
            0,
        )
        self.assertEqual(
            manifest["benchmark_record_accounting"]["train_validation_content_hash_overlap_count"],
            0,
        )
        self.assertEqual(
            len(train_rows) + len(validation_rows),
            len(dataset["documents"]) * len(EVALUATION_CATEGORIES),
        )

    def test_lora_benchmark_eligibility_report_blocks_small_or_concentrated_datasets(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import benchmark_eligibility_report

        os.environ["CML_LORA_BENCHMARK_MIN_TRAIN_RECORDS"] = "4"
        os.environ["CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS"] = "2"
        os.environ["CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS_PER_CATEGORY"] = "1"
        os.environ["CML_LORA_BENCHMARK_MIN_UNIQUE_SOURCES"] = "2"
        os.environ["CML_LORA_BENCHMARK_MIN_UNIQUE_CONTENT_HASHES"] = "2"
        os.environ["CML_LORA_BENCHMARK_MAX_TRAIN_RECORD_SHARE_PER_SOURCE"] = "0.60"
        os.environ["CML_LORA_BENCHMARK_MAX_VALIDATION_RECORD_SHARE_PER_SOURCE"] = "0.60"
        os.environ["CML_LORA_BENCHMARK_MAX_VALIDATION_RECORD_SHARE_PER_SOURCE_PER_CATEGORY"] = "0.60"
        os.environ["CML_LORA_MAX_DUPLICATE_RATIO"] = "0.40"
        get_settings.cache_clear()
        try:
            failing = benchmark_eligibility_report(
                {
                    "benchmark_record_accounting": {
                        "used_source_count": 1,
                        "used_unique_content_hash_count": 1,
                        "train": {
                            "record_count": 4,
                            "duplicate_content_ratio": 0.0,
                            "max_record_share_per_source": 1.0,
                            "category_counts": {"summarization": 1, "style_transfer": 1, "terminology_consistency": 1, "reasoning_pattern": 1},
                            "max_record_share_per_source_per_category": {},
                        },
                        "validation": {
                            "record_count": 2,
                            "duplicate_content_ratio": 0.0,
                            "max_record_share_per_source": 1.0,
                            "category_counts": {"out_of_scope_refusal": 1, "summarization": 1},
                            "max_record_share_per_source_per_category": {"out_of_scope_refusal": 1.0, "summarization": 1.0},
                        },
                    }
                }
            )
            passing = benchmark_eligibility_report(
                {
                    "benchmark_record_accounting": {
                        "used_source_count": 8,
                        "used_unique_content_hash_count": 8,
                        "train": {
                            "record_count": 8,
                            "duplicate_content_ratio": 0.0,
                            "max_record_share_per_source": 0.25,
                            "category_counts": {
                                "summarization": 1,
                                "style_transfer": 1,
                                "terminology_consistency": 1,
                                "reasoning_pattern": 1,
                                "out_of_scope_refusal": 1,
                                "factual_recall": 1,
                                "citation_grounding": 1,
                                "contradiction_handling": 1,
                            },
                            "max_record_share_per_source_per_category": {},
                        },
                        "validation": {
                            "record_count": 8,
                            "duplicate_content_ratio": 0.0,
                            "max_record_share_per_source": 0.25,
                            "category_counts": {
                                "summarization": 1,
                                "style_transfer": 1,
                                "terminology_consistency": 1,
                                "reasoning_pattern": 1,
                                "out_of_scope_refusal": 1,
                                "factual_recall": 1,
                                "citation_grounding": 1,
                                "contradiction_handling": 1,
                            },
                            "max_record_share_per_source_per_category": {
                                "summarization": 0.25,
                                "style_transfer": 0.25,
                                "terminology_consistency": 0.25,
                                "reasoning_pattern": 0.25,
                                "out_of_scope_refusal": 0.25,
                                "factual_recall": 0.25,
                                "citation_grounding": 0.25,
                                "contradiction_handling": 0.25,
                            },
                        },
                    }
                }
            )
        finally:
            os.environ.pop("CML_LORA_BENCHMARK_MIN_TRAIN_RECORDS", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS_PER_CATEGORY", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_UNIQUE_SOURCES", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_UNIQUE_CONTENT_HASHES", None)
            os.environ.pop("CML_LORA_BENCHMARK_MAX_TRAIN_RECORD_SHARE_PER_SOURCE", None)
            os.environ.pop("CML_LORA_BENCHMARK_MAX_VALIDATION_RECORD_SHARE_PER_SOURCE", None)
            os.environ.pop("CML_LORA_BENCHMARK_MAX_VALIDATION_RECORD_SHARE_PER_SOURCE_PER_CATEGORY", None)
            os.environ.pop("CML_LORA_MAX_DUPLICATE_RATIO", None)
            get_settings.cache_clear()

        self.assertFalse(failing["passes"])
        self.assertFalse(failing["checks"]["minimum_unique_sources"])
        self.assertFalse(failing["checks"]["minimum_unique_content_hashes"])
        self.assertFalse(failing["checks"]["maximum_train_record_share_per_source"])
        self.assertFalse(failing["checks"]["maximum_validation_record_share_per_source"])
        self.assertFalse(failing["checks"]["maximum_validation_record_share_per_source_per_category"])
        self.assertFalse(failing["checks"]["minimum_validation_records_per_category"])
        self.assertTrue(passing["passes"])

    def test_lora_benchmark_gate_treats_small_record_sets_as_non_diagnostic(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.lora_training import benchmark_eligibility_report
        from backend.app.core.training_dataset import write_cluster_training_dataset

        os.environ["CML_LORA_BENCHMARK_MIN_TRAIN_RECORDS"] = "20"
        os.environ["CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS"] = "8"
        os.environ["CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS_PER_CATEGORY"] = "1"
        os.environ["CML_LORA_BENCHMARK_MIN_UNIQUE_SOURCES"] = "4"
        os.environ["CML_LORA_BENCHMARK_MIN_UNIQUE_CONTENT_HASHES"] = "4"
        get_settings.cache_clear()
        try:
            dataset = {
                "cluster_id": "cluster-1",
                "cluster_name": "Cluster One",
                "source_count": 3,
                "unique_content_hash_count": 3,
                "duplicate_content_count": 0,
                "duplicate_content_ratio": 0.0,
                "total_text_chars": 6000,
                "estimated_token_count": 1500,
                "dataset_hash": "dataset-hash",
                "documents": [
                    {
                        "source_id": f"source-{index}",
                        "title": f"Doc {index}",
                        "summary": "Cluster evidence that is long enough for record export and benchmark scaffolding.",
                        "text": "Cluster evidence that is long enough for record export and benchmark scaffolding.",
                        "content_hash": f"content-hash-{index}",
                    }
                    for index in range(3)
                ],
            }
            manifest = write_cluster_training_dataset(dataset, Path(self.tmp.name) / "small-lora-benchmark")
            report = benchmark_eligibility_report(manifest)
        finally:
            os.environ.pop("CML_LORA_BENCHMARK_MIN_TRAIN_RECORDS", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_VALIDATION_RECORDS_PER_CATEGORY", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_UNIQUE_SOURCES", None)
            os.environ.pop("CML_LORA_BENCHMARK_MIN_UNIQUE_CONTENT_HASHES", None)
            get_settings.cache_clear()

        self.assertFalse(report["passes"])
        self.assertLess(manifest["train_count"], report["minimum_train_records"])
        self.assertFalse(report["checks"]["minimum_unique_sources"])

    def test_expert_evaluation_harness_covers_strict_categories_and_delta(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.expert_evaluation import (
            DIAGNOSTIC_ONLY_CATEGORIES,
            EVALUATION_CATEGORIES,
            GRADUATION_CATEGORIES,
            build_expert_benchmark_report,
            build_expert_evaluation_plan,
            compare_retrieval_vs_adapter,
            score_expert_response,
        )

        os.environ["CML_LORA_MIN_QUALITY_DELTA"] = "2.5"
        get_settings.cache_clear()
        try:
            dataset = {
                "cluster_id": "cluster-1",
                "dataset_hash": "hash",
                "documents": [
                    {
                        "source_id": f"source-{index}",
                        "title": f"Evaluation source {index}",
                        "summary": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                        "text": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                    }
                    for index in range(len(EVALUATION_CATEGORIES))
                ],
            }
            plan = build_expert_evaluation_plan(dataset)
            scored = score_expert_response(
                plan["cases"][0],
                "According to source Evaluation source 0, adapter retrieval grounded evidence is present.",
            )
            retrieval_scores = [
                {
                    **score_expert_response(
                        case,
                        (
                            f"According to source {case['source_title']}, adapter retrieval evidence is present."
                            if case["category"] in {"factual_recall", "citation_grounding"}
                            else "This answer stays grounded but uses generic wording."
                        ),
                    ),
                    "case_id": case["id"],
                }
                for case in plan["cases"]
            ]
            adapter_scores = [
                {
                    **score_expert_response(
                        case,
                        (
                            f"According to source {case['source_title']}, adapter retrieval grounded citation evidence strict benchmark is present.\n"
                            "- grounded practical note\n"
                            "- preferred local terms stay intact\n"
                            "- first, then, therefore reasoning stays explicit"
                            if case["category"] == "summarization"
                            else f"According to source {case['source_title']}, the practical note is: adapter retrieval grounded citation evidence strict benchmark is present."
                            if case["category"] == "style_transfer"
                            else f"According to source {case['source_title']}, use the preferred local terms and cluster terminology: adapter, retrieval, benchmark."
                            if case["category"] == "terminology_consistency"
                            else f"First, identify the local evidence from source {case['source_title']}. Then interpret it. Therefore, keep the reasoning pattern explicit."
                            if case["category"] == "reasoning_pattern"
                            else f"Source {case['source_title']} does not provide enough evidence; the answer should say it is not covered and evidence is missing."
                            if case["category"] == "out_of_scope_refusal"
                            else f"According to source {case['source_title']}, adapter retrieval grounded citation evidence strict benchmark is present."
                        ),
                    ),
                    "case_id": case["id"],
                }
                for case in plan["cases"]
            ]
            report = build_expert_benchmark_report(
                plan,
                retrieval_case_scores=retrieval_scores,
                adapter_case_scores=adapter_scores,
                mode="unit_strict_category_benchmark",
                live_adapter_backed=True,
            )
            pending_report = build_expert_benchmark_report(
                plan,
                retrieval_case_scores=[],
                adapter_case_scores=[],
                mode="pending_live_adapter_benchmark",
                live_adapter_backed=False,
            )
            passing = compare_retrieval_vs_adapter([60, 62, 61], [65, 67, 66])
            failing = compare_retrieval_vs_adapter([60, 62, 61], [61, 62, 62])
        finally:
            os.environ.pop("CML_LORA_MIN_QUALITY_DELTA", None)
            get_settings.cache_clear()

        self.assertEqual(plan["categories"], list(EVALUATION_CATEGORIES))
        self.assertEqual(plan["graduation_categories"], list(GRADUATION_CATEGORIES))
        self.assertEqual(plan["diagnostic_only_categories"], list(DIAGNOSTIC_ONLY_CATEGORIES))
        self.assertEqual(plan["case_count"], len(EVALUATION_CATEGORIES))
        self.assertGreater(scored["score"], 70)
        self.assertTrue(scored["citation_present"])
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["passes"])
        self.assertEqual(report["mode"], "unit_strict_category_benchmark")
        self.assertFalse(report["missing_categories"])
        self.assertEqual(set(report["category_scores"]), set(EVALUATION_CATEGORIES))
        self.assertEqual(set(report["graduation_categories"]), set(GRADUATION_CATEGORIES))
        self.assertEqual(set(report["diagnostic_only_categories"]), set(DIAGNOSTIC_ONLY_CATEGORIES))
        self.assertTrue(report["graduation_overall"]["passes"])
        self.assertTrue(report["gate_report"]["passes"])
        self.assertTrue(report["gate_report"]["adapter_owned"]["passes"])
        self.assertFalse(report["category_scores"]["factual_recall"]["counts_toward_graduation"])
        self.assertEqual(report["category_scores"]["style_transfer"]["owner"], "adapter")
        self.assertEqual(pending_report["status"], "pending_live_adapter_benchmark")
        self.assertFalse(pending_report["live_adapter_backed"])
        self.assertFalse(pending_report["passes"])
        self.assertTrue(passing["passes"])
        self.assertFalse(failing["passes"])

    def test_out_of_scope_refusal_scoring_accepts_semantic_refusals(self) -> None:
        from backend.app.core.expert_evaluation import build_expert_evaluation_plan, score_expert_response

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Evaluation source {index}",
                    "summary": (
                        "spider mites fungus gnats diagnosis tools practical takeaway "
                        "evidence interpretation conclusion"
                    ),
                    "text": (
                        "The source says spider mites and fungus gnats mattered more than buying new gear. "
                        "It suggests prioritizing diagnosis over tools and keeping a log of changes."
                    ),
                }
                for index in range(8)
            ],
        }
        plan = build_expert_evaluation_plan(dataset)
        case = next(item for item in plan["cases"] if item["category"] == "out_of_scope_refusal")

        scored = score_expert_response(
            case,
            "I cannot answer that from this source because the document does not cover the question and the needed evidence is missing.",
        )

        self.assertTrue(scored["refusal_present"])
        self.assertGreaterEqual(scored["marker_score"], 0.66)
        self.assertGreater(scored["score"], 45.0)

    def test_reasoning_pattern_scoring_penalizes_scaffold_only_and_accepts_substance(self) -> None:
        from backend.app.core.expert_evaluation import (
            REASONING_PATTERN_SCORING_FIXTURES,
            build_expert_evaluation_plan,
            score_expert_response,
        )

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Evaluation source {index}",
                    "summary": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                    "text": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                }
                for index in range(8)
            ],
        }
        plan = build_expert_evaluation_plan(dataset)
        case = next(item for item in plan["cases"] if item["category"] == "reasoning_pattern")

        bad_scores = [score_expert_response(case, text) for text in REASONING_PATTERN_SCORING_FIXTURES["bad_scaffold_only"]]
        good_scores = [score_expert_response(case, text) for text in REASONING_PATTERN_SCORING_FIXTURES["good_without_literal_scaffold"]]

        self.assertTrue(all(item["score"] < 70.0 for item in bad_scores))
        self.assertTrue(all(item["marker_score"] >= 0.7 for item in good_scores))
        self.assertGreater(
            min(item["marker_score"] for item in good_scores),
            max(item["marker_score"] for item in bad_scores),
        )

    def test_factual_recall_scoring_caps_entity_substitution(self) -> None:
        from backend.app.core.expert_evaluation import score_expert_response

        case = {
            "id": "cluster-1-1",
            "category": "factual_recall",
            "owner": "retrieval",
            "counts_toward_graduation": False,
            "expected_terms": ["houseplant", "Toronto", "Tom", "spider mites"],
            "reference_text": (
                "I've been getting into houseplant pest control since moving to Toronto. "
                "Tom from down the street got me started, mostly by accident."
            ),
            "markers": [],
            "requires_citation": True,
        }

        swapped = score_expert_response(
            case,
            (
                "According to source, key facts include: I've been getting into houseplant "
                "pest control since moving to Berlin. Priya from down the street got me started, mostly by accident."
            ),
        )
        grounded = score_expert_response(
            case,
            (
                "According to source, key facts include: I've been getting into houseplant "
                "pest control since moving to Toronto. Tom from down the street got me started, mostly by accident."
            ),
        )

        self.assertEqual(swapped["grounding_consistency_score"], 0.0)
        self.assertLessEqual(swapped["score"], 45.0)
        self.assertEqual(grounded["grounding_consistency_score"], 1.0)
        self.assertGreater(grounded["score"], swapped["score"])

    def test_adapter_training_evaluation_plan_uses_exported_validation_records(self) -> None:
        from backend.app.core.expert_evaluation import build_adapter_training_evaluation_plan

        adapter_dir = Path(self.tmp.name) / "adapter"
        dataset_dir = adapter_dir / "dataset"
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "dataset-manifest.json").write_text(
            json.dumps({"dataset_hash": "adapter-hash"}),
            encoding="utf-8",
        )
        (dataset_dir / "validation.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Explain 'Doc One' using the cluster's preferred terminology and local phrasing.",
                                },
                                {
                                    "role": "assistant",
                                    "content": "According to source Doc One, use the preferred local terms and terminology: adapter, retrieval, benchmark.",
                                },
                            ],
                            "source_id": "source-1",
                            "category": "terminology_consistency",
                        }
                    ),
                    json.dumps(
                        {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Summarize the local source titled 'Doc Two' in three grounded bullets.",
                                },
                                {
                                    "role": "assistant",
                                    "content": "According to source Doc Two:\n- grounded practical note\n- preferred local terms stay intact\n- first, then, therefore reasoning stays explicit",
                                },
                            ],
                            "source_id": "source-2",
                            "category": "summarization",
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )

        plan = build_adapter_training_evaluation_plan(adapter_dir, cluster_id="cluster-smoke")

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["dataset_hash"], "adapter-hash")
        self.assertEqual(plan["case_count"], 2)
        self.assertEqual(plan["cases"][0]["source_title"], "Doc One")
        self.assertEqual(plan["cases"][1]["source_title"], "Doc Two")
        self.assertEqual(plan["cases"][0]["category"], "terminology_consistency")

    def test_lora_mvp_policy_and_smoke_scripts_are_present(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        policy = repo_root / "docs" / "LORA_CLUSTER_EXPERT_MVP_POLICY.md"
        expert_smoke = repo_root / "scripts" / "backend" / "smoke-lora-expert.ps1"
        runtime_smoke = repo_root / "scripts" / "backend" / "smoke-lora-runtime.ps1"
        adapter_benchmark = repo_root / "scripts" / "backend" / "benchmark-lora-adapter.ps1"
        size_matrix = repo_root / "scripts" / "backend" / "run-lora-size-matrix.ps1"
        proof_export = repo_root / "scripts" / "backend" / "export-lora-proof.ps1"
        hardware_proof = repo_root / "scripts" / "backend" / "export-hardware-proof.ps1"

        policy_text = policy.read_text(encoding="utf-8")
        expert_text = expert_smoke.read_text(encoding="utf-8")
        runtime_text = runtime_smoke.read_text(encoding="utf-8")
        adapter_benchmark_text = adapter_benchmark.read_text(encoding="utf-8")
        size_matrix_text = size_matrix.read_text(encoding="utf-8")
        proof_text = proof_export.read_text(encoding="utf-8")
        hardware_text = hardware_proof.read_text(encoding="utf-8")

        self.assertIn("Graduation Gates", policy_text)
        self.assertIn("retrieval owns facts", policy_text.lower())
        self.assertIn("1.5b", policy_text.lower())
        self.assertIn("CML_LORA_TRAINER_COMMAND", expert_text)
        self.assertIn("AllowTestTrainer", expert_text)
        self.assertIn("run_live_expert_benchmark", expert_text)
        self.assertIn("default_expert_benchmark_token_budgets", expert_text)
        self.assertIn("run_live_expert_benchmark", adapter_benchmark_text)
        self.assertIn("default_expert_benchmark_token_budgets", adapter_benchmark_text)
        self.assertIn('benchmark_run.get("benchmark_report")', adapter_benchmark_text)
        self.assertIn("build_adapter_training_evaluation_plan", adapter_benchmark_text)
        self.assertIn("dataset_matches_adapter_training", adapter_benchmark_text)
        self.assertIn("adapter_training_dataset", adapter_benchmark_text)
        self.assertIn("BaseModel15B", size_matrix_text)
        self.assertIn("BaseModel2B", size_matrix_text)
        self.assertIn("BaseModel3B", size_matrix_text)
        self.assertIn("write_lora_smoke_proof", proof_text)
        self.assertIn("hardware_status", hardware_text)
        self.assertIn("avx2_proof_present", hardware_text)
        self.assertIn('benchmark_report = {"status": "runtime_failed", "passes": False, "live_adapter_backed": True}', expert_text)
        self.assertIn('if not runtime_smoke or not runtime_smoke.get("ok"):', expert_text)
        self.assertNotIn("scaffold_case_scores", expert_text)
        self.assertIn("runtime_adapter_load_plan", runtime_text)
        self.assertNotIn("<<'PY'", expert_text)
        self.assertNotIn("<<'PY'", runtime_text)

    def test_run_live_expert_benchmark_scores_real_runtime_outputs(self) -> None:
        from backend.app.core.expert_evaluation import run_live_expert_benchmark

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Evaluation source {index}",
                    "summary": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                    "text": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                }
                for index in range(8)
            ],
        }

        with patch(
            "backend.app.core.expert_evaluation._run_real_retrieval_baseline",
            return_value={
                "ok": True,
                "responses": [{"prompt": "p", "response_text": "Based on the closest local context for: \"p\"\n\n1. grounded citation evidence strict benchmark"}],
                "case_scores": [
                    {
                        "case_id": f"cluster-1-{index + 1}",
                        "category": category,
                        "owner": "retrieval",
                        "counts_toward_graduation": category in {"summarization", "style_transfer", "terminology_consistency", "reasoning_pattern"},
                        "score": 80.0,
                    }
                    for index, category in enumerate(
                        [
                            "factual_recall",
                            "citation_grounding",
                            "contradiction_handling",
                            "summarization",
                            "style_transfer",
                            "terminology_consistency",
                            "reasoning_pattern",
                            "out_of_scope_refusal",
                        ]
                    )
                ],
            },
        ), patch(
            "backend.app.core.expert_runtime.run_adapter_runtime_batch",
            return_value={
                "ok": True,
                "responses": [
                    {
                        "response_text": (
                            f"According to source Evaluation source {index}, adapter retrieval grounded citation evidence strict benchmark is present.\n"
                            if index == 0
                            else f"According to source Evaluation source {index}, adapter retrieval grounded citation evidence strict benchmark is present."
                            if index == 1
                            else "Trust the evidence from source Evaluation source 2 and mark conflicting claims as unverified."
                            if index == 2
                            else "According to source Evaluation source 3, adapter retrieval grounded citation evidence strict benchmark is present.\n- grounded practical note\n- preferred local terms stay intact\n- first, then, therefore reasoning stays explicit"
                            if index == 3
                            else "According to source Evaluation source 4, the practical note is: adapter retrieval grounded citation evidence strict benchmark is present and actionable."
                            if index == 4
                            else "According to source Evaluation source 5, use the preferred local terms and cluster terminology: adapter, retrieval, benchmark."
                            if index == 5
                            else "First, identify the local evidence from source Evaluation source 6 that shows adapter retrieval grounded citation evidence strict benchmark. Then interpret it. Therefore, keep the reasoning pattern explicit."
                            if index == 6
                            else "Source Evaluation source 7 is not covered with sufficient evidence, and key adapter retrieval grounded citation evidence strict benchmark details are missing."
                        )
                    }
                    for index in range(8)
                ],
            },
        ) as runtime_batch:
            report = run_live_expert_benchmark(
                dataset,
                adapter_path="adapter-path",
                base_model="base-model",
                max_new_tokens=64,
            )

        runtime_batch.assert_called_once()
        self.assertTrue(report["runtime"]["ok"])
        self.assertEqual(report["benchmark_report"]["scored_case_count"], 8)
        self.assertEqual(len(report["adapter_case_scores"]), 8)
        self.assertEqual(len(report["retrieval_case_scores"]), 8)
        self.assertGreater(report["benchmark_report"]["graduation_overall"]["adapter_score"], 0)
        self.assertTrue(report["retrieval_runtime"]["ok"])

    def test_run_live_expert_benchmark_reports_runtime_failure(self) -> None:
        from backend.app.core.expert_evaluation import run_live_expert_benchmark

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": "source-1",
                    "title": "Evaluation source",
                    "summary": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                    "text": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                }
            ],
        }

        with patch(
            "backend.app.core.expert_evaluation._run_real_retrieval_baseline",
            return_value={"ok": True, "responses": [], "case_scores": []},
        ), patch(
            "backend.app.core.expert_runtime.run_adapter_runtime_batch",
            return_value={"ok": False, "error": "runtime boom", "responses": []},
        ):
            report = run_live_expert_benchmark(
                dataset,
                adapter_path="adapter-path",
                base_model="base-model",
            )

        self.assertFalse(report["runtime"]["ok"])
        self.assertEqual(report["benchmark_report"]["status"], "runtime_failed")
        self.assertFalse(report["benchmark_report"]["passes"])
        self.assertEqual(report["adapter_case_scores"], [])
        self.assertEqual(report["retrieval_case_scores"], [])

    def test_run_live_expert_benchmark_uses_category_token_budgets_by_default(self) -> None:
        from backend.app.core.expert_evaluation import run_live_expert_benchmark

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Evaluation source {index}",
                    "summary": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                    "text": "adapter retrieval grounded citation evidence strict benchmark preferred terminology reasoning pattern practical note",
                }
                for index in range(8)
            ],
        }

        calls: list[dict] = []

        def fake_runtime_batch(*, adapter_path, base_model, prompts, max_new_tokens, max_new_tokens_per_prompt=None):
            calls.append(
                {
                    "max_new_tokens": int(max_new_tokens),
                    "max_new_tokens_per_prompt": list(max_new_tokens_per_prompt or []),
                }
            )
            return {
                "ok": True,
                "responses": [
                    {"prompt": prompt, "response_text": f"According to source synthetic, response for {prompt}"}
                    for prompt in prompts
                ],
                "stdout": "",
                "stderr": "",
                "unloaded": True,
            }

        with patch(
            "backend.app.core.expert_evaluation._run_real_retrieval_baseline",
            return_value={
                "ok": True,
                "responses": [],
                "case_scores": [
                    {
                        "case_id": f"cluster-1-{index + 1}",
                        "category": category,
                        "owner": "retrieval",
                        "counts_toward_graduation": category in {"summarization", "style_transfer", "terminology_consistency", "reasoning_pattern"},
                        "score": 80.0,
                    }
                    for index, category in enumerate(
                        [
                            "factual_recall",
                            "citation_grounding",
                            "contradiction_handling",
                            "summarization",
                            "style_transfer",
                            "terminology_consistency",
                            "reasoning_pattern",
                            "out_of_scope_refusal",
                        ]
                    )
                ],
            },
        ), patch("backend.app.core.expert_runtime.run_adapter_runtime_batch", side_effect=fake_runtime_batch):
            report = run_live_expert_benchmark(
                dataset,
                adapter_path="adapter-path",
                base_model="base-model",
            )

        self.assertTrue(report["runtime"]["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["max_new_tokens_per_prompt"]), 8)
        self.assertEqual(calls[0]["max_new_tokens"], 640)
        self.assertIn("summarization", report["runtime"]["effective_max_new_tokens"])
        self.assertEqual(report["runtime"]["effective_max_new_tokens"]["summarization"], 640)

    def test_run_live_expert_benchmark_routes_away_retrieval_owned_cases(self) -> None:
        from backend.app.core.expert_evaluation import run_live_expert_benchmark

        dataset = {
            "cluster_id": "cluster-1",
            "dataset_hash": "hash",
            "documents": [
                {
                    "source_id": f"source-{index}",
                    "title": f"Evaluation source {index}",
                    "summary": "Alice moved to Berlin in 2024 and documented a practical workflow.",
                    "text": "Alice moved to Berlin in 2024 and documented a practical workflow.",
                }
                for index in range(8)
            ],
        }

        retrieval_scores = [
            {
                "case_id": f"cluster-1-{index + 1}",
                "category": category,
                "owner": "retrieval",
                "counts_toward_graduation": category in {"summarization", "style_transfer", "terminology_consistency", "reasoning_pattern"},
                "score": 88.0 if category == "factual_recall" else 77.0,
            }
            for index, category in enumerate(
                [
                    "factual_recall",
                    "citation_grounding",
                    "contradiction_handling",
                    "summarization",
                    "style_transfer",
                    "terminology_consistency",
                    "reasoning_pattern",
                    "out_of_scope_refusal",
                ]
            )
        ]

        retrieval_responses = [
            {
                "prompt": "p",
                "response_text": "According to source Evaluation source 0, Alice moved to Berlin in 2024.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "Alice moved to Berlin in 2024. [Source: Evaluation source 1]",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "Trust the local evidence.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "According to source Evaluation source 3:\n- Alice moved to Berlin in 2024.\n- Practical workflow.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "Practical note: Alice moved to Berlin in 2024.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "According to source Evaluation source 5, use the preferred local terms.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "First, the source says Alice moved to Berlin in 2024. Then interpret it. Therefore, keep it practical.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
            {
                "prompt": "p",
                "response_text": "Source Evaluation source 7 does not provide enough evidence.",
                "citations": [{"snippet": "Alice moved to Berlin in 2024."}],
            },
        ]

        with patch(
            "backend.app.core.expert_evaluation._run_real_retrieval_baseline",
            return_value={"ok": True, "responses": retrieval_responses, "case_scores": retrieval_scores},
        ), patch(
            "backend.app.core.expert_runtime.run_adapter_runtime_batch",
            return_value={
                "ok": True,
                "responses": [{"response_text": "bad adapter output"} for _ in range(8)],
            },
        ):
            report = run_live_expert_benchmark(
                dataset,
                adapter_path="adapter-path",
                base_model="base-model",
            )

        adapter_by_case = {item["case_id"]: item for item in report["adapter_case_scores"]}
        self.assertEqual(adapter_by_case["cluster-1-1"]["score"], 88.0)
        self.assertTrue(adapter_by_case["cluster-1-1"]["routed_away"])
        self.assertEqual(adapter_by_case["cluster-1-2"]["score"], 77.0)
        self.assertTrue(adapter_by_case["cluster-1-2"]["routed_away"])
        self.assertNotIn("routed_away", adapter_by_case["cluster-1-5"])

    def test_runtime_batch_timeout_scales_with_prompt_count(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.expert_runtime import _runtime_batch_timeout_seconds

        os.environ["CML_LORA_RUNTIME_BATCH_TIMEOUT_SECONDS"] = "1800"
        os.environ["CML_LORA_RUNTIME_BATCH_TIMEOUT_PER_PROMPT_SECONDS"] = "15"
        get_settings.cache_clear()
        try:
            self.assertEqual(_runtime_batch_timeout_seconds(1), 1815)
            self.assertEqual(_runtime_batch_timeout_seconds(12), 1980)
            self.assertEqual(_runtime_batch_timeout_seconds(328), 6720)
        finally:
            os.environ.pop("CML_LORA_RUNTIME_BATCH_TIMEOUT_SECONDS", None)
            os.environ.pop("CML_LORA_RUNTIME_BATCH_TIMEOUT_PER_PROMPT_SECONDS", None)
            get_settings.cache_clear()

    def test_cluster_expert_assist_routes_retrieval_owned_and_entity_sensitive_prompts_away(self) -> None:
        from backend.app.api.routes.chat import _maybe_run_cluster_expert_assist
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-route", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-route', 'vault-route', 'Route cluster', '', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO expert_artifacts (
                    id, cluster_id, vault_id, job_id, artifact_type, status, local_path, base_model,
                    hardware_tier, quality_score, dataset_hash, training_config_hash, metrics_json,
                    active, rolled_back_at, deleted_at, created_at, updated_at
                )
                VALUES ('artifact-route', 'cluster-route', 'vault-route', NULL, 'lora_adapter', 'ready', 'adapter', 'base', 'gpu', 90, 'hash', 'cfg', '{}', 1, NULL, NULL, ?, ?)
                """,
                (now, now),
            )

        factual = _maybe_run_cluster_expert_assist(
            payload=ChatContextRequest(
                vault_id="vault-route",
                cluster_id="cluster-route",
                prompt="What are the key facts from the local source titled 'foo'?",
            ),
            intent="cluster_question",
            citations=[{"snippet": "Moved to Toronto after meeting Tom during a workshop."}],
        )
        summary = _maybe_run_cluster_expert_assist(
            payload=ChatContextRequest(
                vault_id="vault-route",
                cluster_id="cluster-route",
                prompt="Summarize the local source titled 'foo' in three grounded bullets.",
            ),
            intent="cluster_question",
            citations=[{"snippet": "Moved to Toronto in 2024 after Tom introduced the process."}],
        )
        citation = _maybe_run_cluster_expert_assist(
            payload=ChatContextRequest(
                vault_id="vault-route",
                cluster_id="cluster-route",
                prompt="Answer using only the source 'foo' and cite the source title.",
            ),
            intent="cluster_question",
            citations=[{"snippet": "evidence"}],
        )
        refusal = _maybe_run_cluster_expert_assist(
            payload=ChatContextRequest(
                vault_id="vault-route",
                cluster_id="cluster-route",
                prompt="Answer a question not covered by 'foo' and state what evidence is missing.",
            ),
            intent="cluster_question",
            citations=[{"snippet": "evidence"}],
        )

        self.assertEqual(factual["mode"], "retrieval_routed")
        self.assertFalse(factual["used"])
        self.assertEqual(summary["mode"], "retrieval_routed")
        self.assertFalse(summary["used"])
        self.assertEqual(citation["mode"], "retrieval_routed")
        self.assertFalse(citation["used"])
        self.assertEqual(refusal["mode"], "retrieval_routed")
        self.assertFalse(refusal["used"])

    def test_cluster_expert_assist_allows_low_specificity_summarization_prompts(self) -> None:
        from backend.app.api.routes.chat import _adapter_route_away_category

        category = _adapter_route_away_category(
            "Summarize the local source titled 'foo' in three grounded bullets.",
            [{"snippet": "keep a simple log, focus on the process, and write practical follow-ups"}],
        )

        self.assertIsNone(category)

    def test_lora_smoke_proof_blocks_without_benchmark_or_hardware_proof(self) -> None:
        from backend.app.core.lora_proof import build_lora_smoke_proof

        adapter_dir = Path(self.tmp.name) / "adapter"
        base_dir = Path(self.tmp.name) / "base-model"
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
            "actual_hardware_status": {"avx2": None, "hardware_tier": "cpu_minimum_spec"},
            "hardware_status_used": {"avx2": None, "training_supported": True},
            "artifacts": [{"active": 1, "local_path": str(adapter_dir), "base_model": str(base_dir)}],
            "runtime_smoke": {"ok": True, "adapter_path": str(adapter_dir), "base_model": str(base_dir)},
            "benchmark_report": {
                "passes": False,
                "overall": {"retrieval_only_score": 98.33, "adapter_score": 41.67, "quality_delta": -56.66},
            },
        }

        proof = build_lora_smoke_proof(report)

        self.assertFalse(proof["public_gate"]["passes"])
        self.assertIn("adapter_quality_benchmark_failed", proof["public_gate"]["blocked_reasons"])
        self.assertIn("hardware_avx2_proof_missing", proof["public_gate"]["blocked_reasons"])
        self.assertTrue(proof["pairing"]["adapter_declared_base_matches"])
        self.assertEqual(proof["pairing"]["target_modules"], ["q_proj", "v_proj"])
        self.assertEqual(proof["benchmark"]["baseline_score"], 98.33)
        self.assertEqual(proof["benchmark"]["adapter_score"], 41.67)

        unsupported_report = {
            **report,
            "actual_hardware_status": {"avx2": False, "hardware_tier": "unsupported"},
        }
        unsupported_proof = build_lora_smoke_proof(unsupported_report)
        self.assertIn("hardware_avx2_unsupported", unsupported_proof["public_gate"]["blocked_reasons"])
        self.assertNotIn(
            "hardware_avx2_proof_missing",
            unsupported_proof["public_gate"]["blocked_reasons"],
        )

    def test_bridge_error_code_registry_matches_spec_for_vault_not_found(self) -> None:
        from backend.app.bridge_mcp import app_error_code

        self.assertEqual(app_error_code("vault_not_found"), 1003)

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
