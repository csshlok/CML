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

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        os.environ.pop("CML_ALLOW_UNAUTHENTICATED_API", None)
        os.environ.pop("CML_LORA_MIN_QUALITY_DELTA", None)
        os.environ.pop("CML_LORA_MIN_UNIQUE_SOURCES", None)
        os.environ.pop("CML_LORA_MAX_DUPLICATE_RATIO", None)
        os.environ.pop("CML_LORA_MODEL_DIRS", None)
        os.environ.pop("CML_MODEL_SCAN_ROOTS", None)
        os.environ.pop("CML_MODELS_DIR", None)
        os.environ.pop("CML_LLM_MODEL", None)
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
                "phi-local",
                model_type="phi3",
                repo_hint="microsoft/Phi-4-mini-instruct",
            ),
            name="Phi Local",
        )

        readiness = first_run_readiness()
        chat_check = next(check for check in readiness["checks"] if check["id"] == "chat_model")
        expert_check = next(check for check in readiness["checks"] if check["id"] == "expert_model")
        pair_check = next(check for check in readiness["checks"] if check["id"] == "approved_model_pair")
        self.assertTrue(chat_check["ok"])
        self.assertTrue(expert_check["ok"])
        self.assertTrue(pair_check["ok"])

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
        self.assertIn("Install peft, transformers, and torch", plan["detail"])

    def test_run_adapter_runtime_smoke_reads_worker_report(self) -> None:
        import subprocess

        from backend.app.core.expert_runtime import run_adapter_runtime_smoke

        self._write_fake_local_transformers_model("smoke-model")
        adapter_dir = Path(self.tmp.name) / "adapter-smoke"
        adapter_dir.mkdir()
        (adapter_dir / "adapter_config.json").write_text(
            '{"peft_type":"LORA","base_model_name_or_path":"smoke-model"}',
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

        def fake_run(command, capture_output, text, timeout, cwd):
            payload_path = Path(command[-1])
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
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

    def test_modified_file_after_first_ingest_is_not_deduplicated(self) -> None:
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

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(count, 2)

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
        self.assertIn('fastapi==0.136.3', package_text)
        self.assertIn('uvicorn[standard]==0.48.0', package_text)
        self.assertIn('ocrmypdf==17.5.0', package_text)
        self.assertIn('sentence-transformers==5.5.1', package_text)
        self.assertIn('transformers==5.6.0', package_text)
        self.assertIn('peft==0.18.1', package_text)
        self.assertIn("renderer ready signal received", packaged_launch_text)
        self.assertIn("renderer ready signal received", installed_launch_text)
        self.assertIn("renderer never signaled readiness", packaged_launch_text)
        self.assertIn("renderer never signaled readiness", installed_launch_text)
        self.assertIn("[switch]$RunExecutableSmokes", validate_text)
        self.assertIn("[string]$InstallerPath", validate_text)
        self.assertIn("smoke-windows-installer.ps1", validate_text)
        self.assertEqual(root_main_text.strip(), 'module.exports = require("./electron/main.cjs");')
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
            response = client.patch("/api/v1/vaults/vault-1", json={"database_path": "C:\\evil.sqlite3"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        with connect() as conn:
            row = conn.execute("SELECT path FROM vaults WHERE id = 'vault-1'").fetchone()
        self.assertEqual(row["path"], "C:\\vault")

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

    def test_expert_evaluation_harness_covers_strict_categories_and_delta(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.expert_evaluation import (
            EVALUATION_CATEGORIES,
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
                        "summary": "adapter retrieval grounded citation evidence strict benchmark",
                        "text": "adapter retrieval grounded citation evidence strict benchmark",
                    }
                    for index in range(6)
                ],
            }
            plan = build_expert_evaluation_plan(dataset)
            scored = score_expert_response(
                plan["cases"][0],
                "According to source Evaluation source 0, adapter retrieval grounded evidence is present.",
            )
            passing = compare_retrieval_vs_adapter([60, 62, 61], [65, 67, 66])
            failing = compare_retrieval_vs_adapter([60, 62, 61], [61, 62, 62])
        finally:
            os.environ.pop("CML_LORA_MIN_QUALITY_DELTA", None)
            get_settings.cache_clear()

        self.assertEqual(plan["categories"], list(EVALUATION_CATEGORIES))
        self.assertEqual(plan["case_count"], 6)
        self.assertGreater(scored["score"], 70)
        self.assertTrue(scored["citation_present"])
        self.assertTrue(passing["passes"])
        self.assertFalse(failing["passes"])

    def test_lora_mvp_policy_and_smoke_scripts_are_present(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        policy = repo_root / "docs" / "LORA_CLUSTER_EXPERT_MVP_POLICY.md"
        expert_smoke = repo_root / "scripts" / "backend" / "smoke-lora-expert.ps1"
        runtime_smoke = repo_root / "scripts" / "backend" / "smoke-lora-runtime.ps1"

        policy_text = policy.read_text(encoding="utf-8")
        expert_text = expert_smoke.read_text(encoding="utf-8")
        runtime_text = runtime_smoke.read_text(encoding="utf-8")

        self.assertIn("Graduation Gates", policy_text)
        self.assertIn("retrieval-vs-adapter", policy_text.lower())
        self.assertIn("CML_LORA_TRAINER_COMMAND", expert_text)
        self.assertIn("AllowTestTrainer", expert_text)
        self.assertIn("runtime_adapter_load_plan", runtime_text)
        self.assertNotIn("<<'PY'", expert_text)
        self.assertNotIn("<<'PY'", runtime_text)

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
