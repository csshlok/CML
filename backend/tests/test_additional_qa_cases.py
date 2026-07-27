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
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_root)
        os.environ["CML_LLM_MODEL"] = model_name
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        return model_dir

    def _write_fake_gguf(self, file_name: str) -> Path:
        model_root = Path(self.tmp.name) / "models"
        model_root.mkdir(parents=True, exist_ok=True)
        model_path = model_root / file_name
        model_path.write_bytes(b"GGUF fixture")
        return model_path

    def _install_default_chat_model(self, model_id: str = "qwen3-4b-q4_k_m") -> Path:
        model_dir = Path(self.tmp.name) / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        gguf_path = model_dir / "qwen3-4b-q4_k_m.gguf"
        gguf_path.write_bytes(b"gguf")
        return gguf_path

    def test_source_search_and_pagination_cover_matches_beyond_first_hundred(self) -> None:
        from backend.app.api.routes.sources import count_sources, list_sources
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-scale", "Scale", self.tmp.name, now, now),
            )
            for index in range(130):
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, title, source_type, state, summary, created_at, updated_at
                    )
                    VALUES (?, 'vault-scale', ?, ?, 'indexed', ?, ?, ?)
                    """,
                    (
                        f"source-{index:03d}",
                        "Needle source" if index == 120 else f"Source {index:03d}",
                        "note" if index % 2 == 0 else "file",
                        "deep needle" if index == 120 else "",
                        now,
                        now,
                    ),
                )

        matches = list_sources(
            vault_id="vault-scale",
            q="needle",
            source_types="note",
            limit=25,
            offset=0,
        )
        count = count_sources(
            vault_id="vault-scale",
            q="needle",
            source_types="note",
        )
        second_page = list_sources(
            vault_id="vault-scale",
            limit=30,
            offset=100,
            order="alphabetical",
        )

        self.assertEqual([row["id"] for row in matches], ["source-120"])
        self.assertEqual(count["total"], 1)
        self.assertEqual(len(second_page), 30)

    def test_activity_feed_is_globally_sorted_and_server_paginated_at_scale(self) -> None:
        from backend.app.api.routes.activity import list_activity
        from backend.app.core.database import connect

        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vaults (id, name, path, created_at, updated_at)
                VALUES ('vault-activity', 'Activity', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (self.tmp.name,),
            )
            for index in range(150):
                timestamp = f"2026-01-{(index % 28) + 1:02d}T{index % 24:02d}:00:00Z"
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, title, source_type, state, created_at, updated_at
                    )
                    VALUES (?, 'vault-activity', ?, 'note', 'indexed', ?, ?)
                    """,
                    (f"activity-source-{index:03d}", f"Source {index:03d}", timestamp, timestamp),
                )

        first = list_activity("vault-activity", limit=100, offset=0)
        second = list_activity("vault-activity", limit=100, offset=100)

        self.assertEqual(first["total"], 150)
        self.assertEqual(len(first["items"]), 100)
        self.assertEqual(len(second["items"]), 50)
        combined = [*first["items"], *second["items"]]
        self.assertEqual(
            [item["time"] for item in combined],
            sorted((item["time"] for item in combined), reverse=True),
        )

    def test_model_compatibility_report_accepts_supported_gguf_checkpoint(self) -> None:
        from backend.app.core.model_registry import model_compatibility_report

        model_file = Path(self.tmp.name) / "accepted-qwen-q4_k_m.gguf"
        model_file.write_bytes(b"GGUF fixture")

        report = model_compatibility_report(model_file)

        self.assertTrue(report["accepted"])
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["family"], "qwen")

    def test_model_compatibility_report_rejects_non_gguf_path(self) -> None:
        from backend.app.core.model_registry import model_compatibility_report

        file_path = Path(self.tmp.name) / "qwen-model.bin"
        file_path.write_bytes(b"not gguf")

        report = model_compatibility_report(file_path)

        self.assertFalse(report["accepted"])
        self.assertEqual(report["status"], "rejected")
        self.assertIn("accepts gguf", report["detail"].lower())

    def test_import_model_checkpoint_rejects_overlapping_managed_destination(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint

        imported = import_model_checkpoint(
            self._write_fake_gguf("managed-qwen-q4_k_m.gguf"),
            name="Managed Qwen",
        )
        managed_path = Path(imported["local_path"])

        with self.assertRaises(ValueError) as raised:
            import_model_checkpoint(managed_path, name="Managed Qwen")

        self.assertIn("separate directories", str(raised.exception))
        self.assertTrue(managed_path.is_file())

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

        model_file = self._write_fake_gguf("detected-qwen-q4_k_m.gguf")
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_file.parent)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        discovery = discover_installed_models(max_results=10)

        self.assertGreaterEqual(discovery["compatible_model_count"], 1)
        self.assertTrue(any(item["local_path"] == str(model_file.resolve()) for item in discovery["models"]))

    def test_windows_model_discovery_includes_every_available_drive(self) -> None:
        from backend.app.core import model_registry

        available = {"C:/", "D:/", "T:/"}
        with (
            patch.object(model_registry.os, "name", "nt"),
            patch.object(model_registry.os.path, "exists", side_effect=lambda path: path in available),
        ):
            roots = model_registry._available_drive_roots()

        self.assertEqual([str(root).replace("\\", "/") for root in roots], ["C:/", "D:/", "T:/"])

    def test_discover_installed_models_prioritizes_late_compatible_results_when_rejected_fill_limit(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, invalidate_model_discovery_cache

        scan_root = Path(self.tmp.name) / "model-scan"
        scan_root.mkdir()
        rejected_files = [
            self._write_fake_gguf(f"rejected-{index:02d}.gguf")
            for index in range(12)
        ]
        compatible = self._write_fake_gguf("zz-compatible-qwen-q4_k_m.gguf")
        for model_file in [*rejected_files, compatible]:
            model_file.rename(scan_root / model_file.name)
        ordered_candidates = [scan_root / path.name for path in rejected_files] + [scan_root / compatible.name]

        os.environ["CML_MODEL_SCAN_ROOTS"] = str(scan_root)
        os.environ["CML_MODEL_SCAN_CACHE_SECONDS"] = "0"
        get_settings.cache_clear()
        invalidate_model_discovery_cache()

        with patch("backend.app.core.model_registry._iter_model_candidates", return_value=ordered_candidates):
            discovery = discover_installed_models(max_results=5, include_rejected=True, refresh=True)

        self.assertTrue(discovery["truncated"])
        self.assertEqual(len(discovery["models"]), 5)
        self.assertEqual(discovery["compatible_model_count"], 1)
        self.assertIn(str((scan_root / compatible.name).resolve()), {item["local_path"] for item in discovery["models"]})
        self.assertTrue(discovery["models"][0]["compatibility"]["accepted"])

    def test_models_discover_route_returns_detected_models(self) -> None:
        model_file = self._write_fake_gguf("route-detected-qwen-q4_k_m.gguf")
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_file.parent)
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
        self.assertTrue(any(item["local_path"] == str(model_file.resolve()) for item in payload["models"]))

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

    def test_derivative_detection_does_not_match_random_path_substrings(self) -> None:
        from backend.app.core.model_recommender.family import is_probably_derivative

        self.assertFalse(is_probably_derivative("C:/temp/rpinsideword/Qwen3-8B-Instruct"))
        self.assertTrue(is_probably_derivative("C:/models/Qwen3-8B-rp"))

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

    def test_discover_installed_models_uses_cache_until_refresh(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, invalidate_model_discovery_cache

        model_file = self._write_fake_gguf("cached-detected-qwen-q4_k_m.gguf")
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_file.parent)
        os.environ["CML_MODEL_SCAN_CACHE_SECONDS"] = "300"
        get_settings.cache_clear()
        invalidate_model_discovery_cache()

        call_counter = {"count": 0}

        def counting_iter(root: Path, *, max_depth: int) -> list[Path]:
            call_counter["count"] += 1
            return [model_file]

        with patch("backend.app.core.model_registry._iter_model_candidates", side_effect=counting_iter):
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
        self.assertEqual(first["import_outcome"], "created")
        self.assertEqual(second["import_outcome"], "updated")
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

    def test_closing_persisted_stream_saves_partial_answer_and_terminal_stopped_state(self) -> None:
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

        context = {
            "answer": "",
            "clusters_used": [],
            "citations": [],
            "coverage_ledger": {"partial_failure_mode": "general_chat_direct"},
            "intent": "general_chat",
            "runtime_state": "ready",
            "warnings": [],
            "recent_turns": [],
            "direct_answer_fallback": False,
        }

        async def read_one_token_then_close(response) -> None:
            iterator = response.body_iterator
            async for chunk in iterator:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                if "event: token" in text:
                    break
            await iterator.aclose()

        with (
            patch("backend.app.api.routes.chat._build_retrieval_context", return_value=context),
            patch(
                "backend.app.api.routes.chat.stream_direct_answer",
                return_value=iter(["first partial", " should not be consumed"]),
            ),
        ):
            response = stream_chat_context(
                ChatContextRequest(vault_id="vault-1", prompt="Hello", persist=True)
            )
            asyncio.run(read_one_token_then_close(response))

        with connect() as conn:
            generation = conn.execute("SELECT * FROM chat_generations").fetchone()
            assistant = conn.execute(
                "SELECT role, content FROM chat_messages WHERE role = 'assistant'"
            ).fetchone()

        self.assertEqual(generation["state"], "stopped")
        self.assertIsNotNone(generation["completed_at"])
        self.assertEqual(assistant["content"], "first partial")
        timeline = get_chat_timeline(generation["session_id"])
        assistant_item = next(item for item in timeline["items"] if item["role"] == "assistant")
        self.assertEqual(assistant_item["reply_to_message_id"], generation["user_message_id"])
        self.assertEqual(assistant_item["generation_state"], "stopped")

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
        self.assertIn("TesseractInstallTimeoutSeconds", stage_text)
        self.assertIn("GhostscriptInstallTimeoutSeconds", stage_text)
        self.assertIn('Copy-Item -Path (Join-Path $tesseractDir "*")', stage_text)
        self.assertIn('"/D=$tesseractTarget"', stage_text)
        self.assertIn('"tesseract-local"', stage_text)
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
        self.assertIn(
            '$effectiveBackendRuntimePackages = @($backendRuntimePackages) + @($embeddingRuntimePackages)',
            package_text,
        )
        self.assertRegex(package_text, r'"python-runtime-v\d+"')
        self.assertIn(
            '(Get-Content -LiteralPath (Join-Path $backendDir "pyproject.toml") -Raw)',
            package_text,
        )
        self.assertIn('SentenceTransformers is included in every packaged backend runtime.', package_text)
        self.assertNotIn('if ($IncludeEmbeddingRuntime)', package_text)
        self.assertNotIn('expert-python-runtime', package_text)
        self.assertNotIn('transformers==5.6.0', package_text)
        self.assertNotIn('peft==0.18.1', package_text)
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
        self.assertIn("sentence_transformers_runtime_exists", validate_text)
        self.assertNotIn("expert_python_runtime_exists", validate_text)
        self.assertEqual(root_main_text.strip(), 'module.exports = require("./electron/main.cjs");')
        icon_header = desktop_icon.read_bytes()[:6]
        self.assertEqual(icon_header[:4], b"\x00\x00\x01\x00")
        self.assertGreaterEqual(int.from_bytes(icon_header[4:6], "little"), 1)
        self.assertIn("scripts/packaging/stage-ocr-runtime.ps1", readme_text)

    def test_windows_dev_package_is_checkout_portable_and_preflighted(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        package_script = (
            repo_root / "scripts" / "packaging" / "package-windows.ps1"
        ).read_text(encoding="utf-8")
        preflight = (
            repo_root / "scripts" / "packaging" / "check-windows-dev-build.ps1"
        ).read_text(encoding="utf-8")
        package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
        commands = (repo_root / "docs" / "WORKING_COMMANDS.md").read_text(encoding="utf-8")

        self.assertIn('& $devBuildCheckScript', package_script)
        self.assertNotIn('$python = "python"', package_script)
        self.assertIn('-CacheDir (Join-Path $tmpDir "llm-runtime-cache")', package_script)
        self.assertIn('.venv\\Scripts\\python.exe', preflight)
        self.assertIn('requirements\\contributors-backend.txt', preflight)
        self.assertIn('[Environment]::Is64BitOperatingSystem', preflight)
        self.assertIn('RecommendedFreeSpaceGB', preflight)
        self.assertEqual(
            package_json["scripts"]["package:win:check"],
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            "scripts\\packaging\\check-windows-dev-build.ps1",
        )
        self.assertIn("npm run package:win:check", commands)
        self.assertIn("npm run package:win", commands)
        self.assertNotIn("expert-python-runtime", commands)

    def test_version_bump_script_updates_every_authoritative_version_surface(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script = (repo_root / "scripts" / "dev" / "set-version.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("npm version $Version --no-git-tag-version", script)
        self.assertIn(
            "npm version $Version --workspace @cml/desktop --no-git-tag-version",
            script,
        )
        self.assertIn('backend\\pyproject.toml', script)
        self.assertIn("npm install --package-lock-only --ignore-scripts", script)
        self.assertIn("$originalContent", script)

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

        self.assertIn('vault-onboarding-shell h-full overflow-x-hidden overflow-y-auto', onboarding)
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
        embeddings = (repo_root / "backend" / "app" / "core" / "embeddings.py").read_text(encoding="utf-8")
        embedding_worker = (
            repo_root / "backend" / "app" / "core" / "embedding_download_worker.py"
        ).read_text(encoding="utf-8")

        self.assertIn('Field label="Save models in"', onboarding)
        self.assertIn('"Welcome",', onboarding)
        self.assertIn('type Step = 0 | 1 | 2 | 3 | 4 | 5 | 6;', onboarding)
        self.assertIn("Start Setup", onboarding)
        self.assertIn("Welcome to Vault", onboarding)
        self.assertIn('title="Name and locate your library"', onboarding)
        self.assertIn("lg:h-[520px]", onboarding)
        self.assertIn("h-[93px] items-center justify-between", onboarding)
        self.assertIn("vault-step-enter py-10 lg:py-16", onboarding)
        self.assertIn('"mt-16 space-y-3"', onboarding)
        self.assertIn('"flex min-w-0 items-center gap-5"', onboarding)
        self.assertNotIn('"mt-auto space-y-3"', onboarding)
        self.assertNotIn("Continue with Google", onboarding)
        self.assertIn("chooseModelDownloadFolder", onboarding)
        self.assertIn("target_dir: modelDownloadRoot.trim()", onboarding)
        self.assertIn("Choose where to save the model before downloading.", onboarding)
        self.assertIn("recommendedModels.map", onboarding)
        self.assertIn("modelRecommendations?.recommended_chat_model_id", onboarding)
        self.assertIn("Confirm skip", onboarding)
        self.assertIn("ModelDownloadToast", onboarding)
        self.assertIn("fixed bottom-4 right-4", onboarding)
        self.assertIn("useVisiblePolling(refreshModels, 750, modelDownloadActive)", onboarding)
        self.assertIn("useVisiblePolling(refreshEmbeddingStatus, 750, embeddingDownloadActive)", onboarding)
        self.assertNotIn("setInterval", onboarding)
        self.assertIn("formatProgressPercent(progress)", onboarding)
        self.assertNotIn("progress || 12", onboarding)
        self.assertIn('modelRuntime?.state === "ready"', onboarding)
        self.assertIn("model.id === modelRuntime.model", onboarding)
        self.assertIn('model.source_kind === "default_choice"', onboarding)
        self.assertIn('status === "resolving" || status === "downloading" || status === "cancelling"', onboarding)
        self.assertIn("function selectVisibleModelDownload", onboarding)
        self.assertIn("visible.find((download) => isActiveModelDownloadStatus(download.status))", onboarding)
        self.assertIn("modelsLoadedRef", onboarding)
        self.assertIn("visible.find((download) => download.model_id === fallback.model_id)", onboarding)
        self.assertIn('leaving && "pointer-events-none translate-y-1 opacity-0"', onboarding)
        self.assertIn('state.status === "failed" || state.status === "blocked"', onboarding)
        self.assertIn("model.download?.progress_percent", onboarding)
        self.assertIn("model.download?.total_bytes ?? model.download?.bytes_total", onboarding)
        self.assertIn("model.compatibility?.chat_role_accepted", onboarding)
        self.assertIn("refreshDetectedModels(true)", onboarding)
        self.assertIn("Skip for now", onboarding)
        self.assertIn("recommendedEmbeddingModel", onboarding)
        self.assertIn("sentence-transformers/all-MiniLM-L6-v2", onboarding)
        self.assertIn("About 100 MB", onboarding)
        self.assertIn("Review download", onboarding)
        self.assertIn("Agree and download", onboarding)
        self.assertIn("showEmbeddingConsent", onboarding)
        self.assertIn("It is not used to generate chat replies.", onboarding)
        self.assertIn("no Hugging Face account token is sent or requested.", onboarding)
        self.assertIn("model: recommendedEmbeddingModel.id", onboarding)
        self.assertIn("embeddingPollFailuresRef", onboarding)
        self.assertIn("if (downloadStatus.status === \"queued\" || downloadStatus.status === \"downloading\")", onboarding)
        self.assertIn("signal: AbortSignal.timeout(120_000)", backend)
        self.assertIn("MANAGED_EMBEDDING_MODELS", embeddings)
        self.assertIn("snapshot_download(", embedding_worker)
        self.assertIn("token=False", embedding_worker)
        self.assertIn("local_files_only=True", embeddings)
        self.assertIn("MINILM_DOWNLOAD_PATTERNS", embeddings)
        self.assertNotIn("Continue is enabled only after one accepted chat model and one accepted expert checkpoint are active.", onboarding)
        self.assertIn("Local model download location", settings)
        self.assertIn("target_dir: modelDownloadRoot.trim() || null", settings)
        self.assertIn("ModelDownloadToast", settings)
        self.assertIn("progress_percent", settings)
        self.assertIn("discoverInstalledModels({ max_results: 24, refresh: true })", settings)
        self.assertIn('showSection("models")', settings)
        self.assertIn('showSection("library")', settings)
        self.assertIn('showSection("connections")', settings)
        self.assertIn('showSection("advanced")', settings)
        self.assertNotIn('showSection("diagnostics", "advanced")', settings)
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
        self.assertIn("Path {displayPath(item.observed_executable_path", bridge)
        self.assertIn("Path {displayPath(client.observed_executable_path", bridge)
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

        self.assertIn("relative h-full overflow-y-auto bg-background", search)
        self.assertIn("px-4 py-5 sm:px-6", search)
        self.assertIn("flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between", search)
        self.assertIn("lg:grid-cols-[minmax(0,1fr)_auto_auto]", search)
        self.assertIn("grid grid-cols-1 gap-3 xl:grid-cols-2", search)
        self.assertIn("line-clamp-3 text-sm leading-6", search)
        self.assertIn('DialogTitle className="break-words"', search)
        self.assertIn('className="min-w-0"', search)
        self.assertIn("break-words rounded-md border border-border bg-muted/35", search)
        self.assertIn("max-w-full break-words rounded-md", search)
        self.assertIn("flex flex-wrap justify-end gap-2", search)
        self.assertNotIn("grid-cols-[minmax(0,1fr)_320px] overflow-hidden", search)
        self.assertNotIn("SourceInspector", search)
        self.assertNotIn("handleDrop", search)
        self.assertNotIn("flex items-start justify-between gap-6", search)
        self.assertNotIn("lg:grid-cols-[1fr_auto_auto]", search)
        self.assertNotIn("mb-4 flex items-center justify-between text-sm", search)
        self.assertNotIn("hidden border-l border-border", search)

    def test_sources_route_exposes_inspector_and_wraps_long_source_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sources = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.sources.tsx").read_text(encoding="utf-8")

        self.assertIn("relative grid h-full grid-cols-1 overflow-y-auto", sources)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_326px] xl:overflow-hidden", sources)
        self.assertIn("min-w-0 px-7 py-8 xl:overflow-y-auto", sources)
        self.assertIn("relative mr-auto min-w-0 flex-[1_1_240px] sm:max-w-sm", sources)
        self.assertIn("text-muted-foreground break-words", sources)
        self.assertIn('className="w-full table-fixed text-sm"', sources)
        self.assertIn("hidden w-28 px-3 py-3 font-normal xl:table-cell", sources)
        self.assertNotIn("min-w-[760px]", sources)
        self.assertNotIn("overflow-x-auto", sources)
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

    def test_map_route_stacks_detail_rail_and_wraps_long_graph_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        map_route = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.map.tsx").read_text(encoding="utf-8")
        knowledge_map = (repo_root / "apps" / "desktop" / "src" / "components" / "KnowledgeMap.tsx").read_text(
            encoding="utf-8",
        )

        self.assertIn("vault-page-wash h-full overflow-y-auto px-4 py-6 sm:px-6 lg:px-8", map_route)
        self.assertIn("<KnowledgeMap", map_route)
        self.assertIn("vaultId={vault.id}", map_route)
        self.assertIn("overview={overview}", map_route)
        self.assertIn("persistView", map_route)
        self.assertIn("Vault could not load the map", map_route)
        self.assertIn("Open Health", map_route)
        self.assertNotIn("mapMockData", map_route)
        self.assertNotIn("demo=cluster-map", map_route)
        self.assertNotIn("right-panel", map_route)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_320px]", knowledge_map)
        self.assertIn("Reset view", knowledge_map)
        self.assertIn("Authoritative relationships", knowledge_map)
        self.assertIn("break-words text-base font-semibold", knowledge_map)
        self.assertIn("window.setTimeout", knowledge_map)

    def test_clusters_route_exposes_inspector_and_wraps_long_cluster_content_on_narrow_windows(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        clusters = (repo_root / "apps" / "desktop" / "src" / "routes" / "_app.clusters.tsx").read_text(
            encoding="utf-8",
        )

        self.assertIn("vault-page-wash h-full overflow-y-auto", clusters)
        self.assertIn("min-w-0 px-4 py-6 sm:px-7 sm:py-8", clusters)
        self.assertIn("page-title flex flex-wrap items-center gap-3", clusters)
        self.assertIn("vault-card mt-5 break-words", clusters)
        self.assertIn("grid-cols-[minmax(0,1fr)_64px_48px]", clusters)
        self.assertIn("md:grid-cols-[minmax(0,1fr)_64px_112px_48px]", clusters)
        self.assertIn("xl:grid-cols-[minmax(0,1fr)_64px_64px_112px_48px]", clusters)
        self.assertNotIn("min-w-[760px]", clusters)
        self.assertNotIn("overflow-x-auto", clusters)
        self.assertIn("break-words text-sm font-semibold", clusters)
        self.assertIn("line-clamp-2 break-words text-sm text-muted-foreground", clusters)
        self.assertIn("flex flex-col gap-3 px-4 py-3 sm:flex-row", clusters)
        self.assertIn("flex shrink-0 flex-wrap items-center gap-2", clusters)
        self.assertIn('to="/clusters/$clusterId"', clusters)
        self.assertNotIn("ClusterInspector", clusters)
        self.assertNotIn("xl:grid-cols-[minmax(0,1fr)_340px]", clusters)
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
        self.assertIn("xl:grid-cols-[320px_minmax(0,1fr)] xl:overflow-hidden", chat)
        self.assertIn("border-b border-border bg-card/35 px-4 py-4", chat)
        self.assertIn("max-h-56 space-y-1 overflow-y-auto lg:max-h-none", chat)
        self.assertIn("min-w-0 flex-1 break-words px-3 py-2 text-sm", chat)
        self.assertIn("px-4 py-5 sm:px-6 lg:px-10", chat)
        self.assertIn("mb-2 break-words rounded-md border", chat)
        self.assertIn("h-8 w-full min-w-0 gap-2", chat)
        self.assertIn("gap-2 sm:ml-auto", chat)
        self.assertIn("max-w-full break-all rounded-md", chat)
        self.assertNotIn("RecentChatInspector", chat)
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
        self.assertIn("xl:grid-cols-[256px_minmax(0,1fr)] xl:overflow-hidden", chat_detail)
        self.assertIn("border-b border-border bg-card/30 p-2", chat_detail)
        self.assertIn("max-h-48 space-y-0.5 overflow-y-auto lg:max-h-none", chat_detail)
        self.assertIn("block break-words rounded-md px-2.5 py-1.5 text-sm", chat_detail)
        self.assertIn("h-8 w-full gap-2 text-xs sm:w-52", chat_detail)
        self.assertIn("flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto", chat_detail)
        self.assertIn("grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]", chat_detail)
        self.assertIn("border-t border-border bg-card/40 p-4", chat_detail)
        self.assertIn("mb-1 break-words font-medium", chat_detail)
        self.assertIn("break-words text-muted-foreground", chat_detail)
        self.assertIn("max-w-full break-all rounded-md", chat_detail)
        self.assertIn("mx-auto mt-1.5 max-w-3xl break-words", chat_detail)
        self.assertIn("max-w-[85%] break-words rounded-md", chat_detail)
        self.assertIn("whitespace-pre-wrap break-words text-sm", chat_detail)
        self.assertIn("inline-flex min-h-8 max-w-full items-center gap-1", chat_detail)
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
        knowledge_map = (repo_root / "apps" / "desktop" / "src" / "components" / "KnowledgeMap.tsx").read_text(
            encoding="utf-8",
        )

        self.assertIn("vault-page-wash h-full overflow-y-auto", home)
        self.assertIn("max-w-[1440px] min-w-0 px-4 py-6 sm:px-8 sm:py-10", home)
        self.assertIn("flex flex-wrap items-center gap-3 px-1 pb-1", home)
        self.assertIn("line-clamp-2 break-words text-sm font-semibold", home)
        self.assertIn("break-words text-sm font-semibold", home)
        self.assertIn("line-clamp-2 break-words text-xs text-muted-foreground", home)
        self.assertIn("grid gap-px sm:grid-cols-2 xl:grid-cols-4", home)
        self.assertIn("Suggested clusters", home)
        self.assertIn("Activity", home)
        self.assertLess(home.index("Quick actions"), home.index("Ask or search your memory"))
        self.assertLess(home.index('title="Suggested clusters"'), home.index('title="Activity"'))
        self.assertNotIn("grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[1fr_326px]", home)
        self.assertNotIn("xl:grid-cols-[minmax(0,1fr)_326px]", home)
        self.assertNotIn("truncate text-sm font-semibold", home)
        self.assertNotIn("mt-1 truncate text-xs", home)
        self.assertNotIn("block truncate text-xs", home)
        self.assertNotIn("hidden overflow-y-auto border-l", home)

        self.assertIn("items-start gap-2 rounded-md px-1 py-1.5 text-left", shell)
        self.assertIn("min-w-0 flex-1 break-all", shell)
        self.assertIn("flex min-h-7 items-start gap-2", shell)
        self.assertIn("min-w-0 flex-1 break-words", shell)
        self.assertIn("data-vault-nav", shell)
        self.assertIn("contentRef.current?.focus()", shell)
        self.assertIn("break-all text-[12px]", shell)
        self.assertIn("vault-footer flex shrink-0 flex-wrap", shell)
        self.assertIn("currentUnlock.secured_vault_count > 0 && !currentUnlock.ready", shell)
        self.assertIn("securityLockActive", shell)
        self.assertIn('{securityLockActive && pathname !== "/settings" ?', shell)
        self.assertNotIn("flex w-full items-center gap-2 truncate", shell)
        self.assertNotIn("<span className=\"truncate\">", shell)
        self.assertNotIn("block truncate rounded-md", shell)
        self.assertNotIn("truncate text-[13px]", shell)
        self.assertNotIn("truncate text-[12px]", shell)
        self.assertIn("min-height: 32px;", styles)
        self.assertNotIn("\n    height: 32px;", styles)

        self.assertIn("break-words text-base font-semibold", knowledge_map)
        self.assertIn("min-w-0 flex-1", knowledge_map)
        self.assertIn("Reset view", knowledge_map)
        self.assertIn("Unclustered collection", knowledge_map)
        self.assertNotIn("mapMockData", knowledge_map)

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

    def test_backend_token_is_not_stored_as_plaintext(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        store_path = repo_root / "apps" / "desktop" / "electron" / "token-store.cjs"
        source = store_path.read_text(encoding="utf-8")
        self.assertNotIn("writeFile(this.tokenPath, token", source)

    def test_extract_answer_formats_grounded_bullets_for_summarization_prompts(self) -> None:
        from backend.app.api.routes.chat import _build_extract_answer

        answer = _build_extract_answer(
            "Summarize the local source titled 'foo' in three grounded bullets.",
            [{"snippet": "Keep a simple log, focus on the process, and write practical follow-ups."}],
        )

        self.assertIn("Based on the closest local context", answer)
        self.assertIn("1. Keep a simple log", answer)

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
