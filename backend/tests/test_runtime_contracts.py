import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


class RuntimeContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("CML_LLM_TIMEOUT_SECONDS", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_STARTUP_STATUS_PATH", None)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

    def test_interactive_timeout_respects_configured_value(self) -> None:
        os.environ["CML_LLM_TIMEOUT_SECONDS"] = "45"
        from backend.app.core.config import get_settings
        from backend.app.core.llm_runtime import _interactive_timeout

        get_settings.cache_clear()
        self.assertEqual(_interactive_timeout(), 45.0)

    def test_interactive_timeout_has_one_second_floor(self) -> None:
        os.environ["CML_LLM_TIMEOUT_SECONDS"] = "0"
        from backend.app.core.config import get_settings
        from backend.app.core.llm_runtime import _interactive_timeout

        get_settings.cache_clear()
        self.assertEqual(_interactive_timeout(), 1.0)

    def test_ocr_manifest_does_not_ship_build_machine_destination(self) -> None:
        manifest_path = Path(__file__).resolve().parents[1] / "bin" / "ocr" / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload.get("layout"), "self-contained-ocr-runtime-v1")
        self.assertNotIn("destination", payload)

    def test_backend_version_is_loaded_from_pyproject_and_reused_by_runtime_surfaces(self) -> None:
        from backend.app.api.routes.diagnostics import BACKEND_VERSION, create_diagnostic_bundle
        from backend.app.bridge_mcp import handle_message
        from backend.app.core.version import app_version
        from backend.app.main import app

        import tomllib

        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        expected = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]["version"]
        self.assertEqual(app_version(), expected)
        self.assertEqual(BACKEND_VERSION, expected)
        self.assertEqual(app.version, expected)

        initialize = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(initialize["result"]["serverInfo"]["version"], expected)

        temp_dir = Path(__file__).resolve().parents[2] / ".tmp" / "runtime-contracts"
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CML_DATA_DIR"] = str(temp_dir)
        os.environ["CML_DATABASE_PATH"] = str(temp_dir / "test.sqlite3")
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()
        bundle = create_diagnostic_bundle()
        bundle_path = Path(bundle["bundle_path"])
        with ZipFile(bundle_path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest["app_version"], expected)
        self.assertEqual(manifest["backend_version"], expected)

    def test_startup_phase_registry_includes_database_initialization_failure(self) -> None:
        from backend.app.core.startup_status import known_startup_phases

        self.assertIn("database_initialization_failed", known_startup_phases())

    def test_diagnostics_bundle_skips_deep_embedding_probe(self) -> None:
        temp_dir = Path(__file__).resolve().parents[2] / ".tmp" / "runtime-contracts-lightweight"
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CML_DATA_DIR"] = str(temp_dir)
        os.environ["CML_DATABASE_PATH"] = str(temp_dir / "test.sqlite3")
        os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle

        with (
            patch("backend.app.core.embeddings.importlib.util.find_spec", return_value=object()),
            patch("backend.app.core.embeddings._embed_with_sentence_transformers", side_effect=AssertionError("deep probe should be skipped")),
        ):
            bundle = create_diagnostic_bundle()

        with ZipFile(bundle["bundle_path"]) as archive:
            runtime_summary = json.loads(archive.read("runtime-summary.json").decode("utf-8"))
        self.assertIn("Full model probe was skipped", runtime_summary["embedding"]["detail"])

    def test_diagnostics_bundle_includes_packaged_electron_logs_when_startup_status_points_to_user_data(self) -> None:
        temp_dir = Path(__file__).resolve().parents[2] / ".tmp" / "runtime-contracts-electron-logs"
        user_data_dir = temp_dir / "user-data"
        temp_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CML_DATA_DIR"] = str(temp_dir)
        os.environ["CML_DATABASE_PATH"] = str(temp_dir / "test.sqlite3")
        os.environ["CML_STARTUP_STATUS_PATH"] = str(user_data_dir / "startup-status.json")
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

        (user_data_dir / "desktop-runtime.log").write_text("desktop path C:\\Users\\me\\AppData\\Roaming\\CML\n", encoding="utf-8")
        (user_data_dir / "backend-stdout.log").write_text("stdout token=secret-value\n", encoding="utf-8")
        (user_data_dir / "backend-stderr.log").write_text("stderr authorization: bearer abc123\n", encoding="utf-8")

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle

        bundle = create_diagnostic_bundle()
        with ZipFile(bundle["bundle_path"]) as archive:
            names = set(archive.namelist())
            desktop_runtime = archive.read("logs/desktop-runtime.log").decode("utf-8")
            backend_stdout = archive.read("logs/backend-stdout.log").decode("utf-8")
            backend_stderr = archive.read("logs/backend-stderr.log").decode("utf-8")

        self.assertIn("logs/desktop-runtime.log", names)
        self.assertIn("logs/backend-stdout.log", names)
        self.assertIn("logs/backend-stderr.log", names)
        self.assertIn("[local-path]", desktop_runtime)
        self.assertIn("token=[redacted]", backend_stdout)
        self.assertIn("authorization: bearer [redacted]", backend_stderr.lower())

    def test_bridge_entrypoints_use_only_loopback_defaults_and_no_contributor_machine_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        bridge_mcp = (repo_root / "backend" / "app" / "bridge_mcp.py").read_text(encoding="utf-8")
        bridge_cli = (repo_root / "backend" / "app" / "bridge_cli.py").read_text(encoding="utf-8")
        bridge_script = (repo_root / "scripts" / "bridge" / "cml-bridge.ps1").read_text(encoding="utf-8")
        desktop_backend = (repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts").read_text(encoding="utf-8")

        for text in (bridge_mcp, bridge_cli, bridge_script, desktop_backend):
            self.assertNotIn("C:\\Users\\csshl", text)
            self.assertNotIn("Desktop\\CML", text)
            self.assertNotIn("T:\\", text)

        self.assertIn("http://127.0.0.1:7343", bridge_mcp)
        self.assertIn("http://127.0.0.1:7343", bridge_cli)
        self.assertIn("http://127.0.0.1:7343", bridge_script)
        self.assertIn("http://127.0.0.1:7343", desktop_backend)
        self.assertNotIn("http://0.0.0.0", bridge_mcp)
        self.assertNotIn("http://0.0.0.0", bridge_cli)
        self.assertNotIn("http://0.0.0.0", bridge_script)


if __name__ == "__main__":
    unittest.main()
