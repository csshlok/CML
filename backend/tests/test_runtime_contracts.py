import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


class RuntimeContractTests(unittest.TestCase):
    def test_existing_integration_imports_gain_restartable_scan_cycle_state(self) -> None:
        import sqlite3
        import tempfile

        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            database_path = root / "legacy-integration.sqlite3"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE integration_imports (
                        id TEXT PRIMARY KEY,
                        vault_id TEXT,
                        integration_type TEXT NOT NULL,
                        root_path TEXT NOT NULL,
                        status TEXT NOT NULL,
                        supported_count INTEGER NOT NULL DEFAULT 0,
                        skipped_count INTEGER NOT NULL DEFAULT 0,
                        truncated INTEGER NOT NULL DEFAULT 0,
                        last_scan_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO integration_imports (
                        id, integration_type, root_path, status, last_scan_at, created_at, updated_at
                    ) VALUES ('legacy-watch', 'local_folder', ?, 'scanned', 'now', 'now', 'now')
                    """,
                    (str(root),),
                )
            with patch.dict(
                os.environ,
                {"CML_DATA_DIR": str(root), "CML_DATABASE_PATH": str(database_path)},
            ):
                get_settings.cache_clear()
                init_db()
                with sqlite3.connect(database_path) as conn:
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(integration_imports)")}
                    row = conn.execute(
                        """
                        SELECT scan_cursor, scan_cycle_id, scan_phase, scan_processed_count
                        FROM integration_imports WHERE id = 'legacy-watch'
                        """
                    ).fetchone()
                    seen_table = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'integration_scan_seen'"
                    ).fetchone()
            get_settings.cache_clear()

        self.assertTrue(
            {"scan_cursor", "scan_cycle_id", "scan_phase", "scan_processed_count"} <= columns
        )
        self.assertEqual(row, ("", "", "discovery", 0))
        self.assertIsNotNone(seen_table)

    def test_existing_chat_generation_table_is_upgraded_before_request_index(self) -> None:
        import sqlite3
        import tempfile

        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            database_path = root / "legacy.sqlite3"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE chat_generations (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        vault_id TEXT NOT NULL,
                        user_message_id TEXT,
                        assistant_message_id TEXT,
                        prompt TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL DEFAULT 'queued',
                        error TEXT NOT NULL DEFAULT '',
                        citations_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT
                    )
                    """
                )
            with patch.dict(
                os.environ,
                {
                    "CML_DATA_DIR": str(root),
                    "CML_DATABASE_PATH": str(database_path),
                },
            ):
                get_settings.cache_clear()
                init_db()
                with sqlite3.connect(database_path) as conn:
                    columns = {
                        row[1] for row in conn.execute("PRAGMA table_info(chat_generations)")
                    }
                    indexes = {
                        row[1] for row in conn.execute("PRAGMA index_list(chat_generations)")
                    }
            get_settings.cache_clear()

        self.assertIn("request_id", columns)
        self.assertIn("idx_chat_generations_request_id", indexes)

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

    def test_packaged_runtime_pypdf_pin_matches_backend_project(self) -> None:
        import tomllib

        repo_root = Path(__file__).resolve().parents[2]
        project = tomllib.loads(
            (repo_root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
        )
        expected = next(
            dependency
            for dependency in project["project"]["dependencies"]
            if dependency.lower().startswith("pypdf==")
        )
        package_script = (
            repo_root / "scripts" / "packaging" / "package-windows.ps1"
        ).read_text(encoding="utf-8")
        packaged_pin = re.search(r'^\s*"(pypdf==[^"]+)",?\s*$', package_script, re.MULTILINE)

        self.assertIsNotNone(packaged_pin)
        self.assertEqual(packaged_pin.group(1).lower(), expected.lower())

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
        self.assertIn("SentenceTransformers", runtime_summary["embedding"]["detail"])

    def test_diagnostics_bundle_summarizes_packaged_logs_without_including_content(self) -> None:
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
            summary = json.loads(archive.read("log-summary.json").decode("utf-8"))
            bundle_text = "\n".join(
                archive.read(name).decode("utf-8") for name in archive.namelist()
            )

        self.assertNotIn("logs/desktop-runtime.log", names)
        self.assertNotIn("logs/backend-stdout.log", names)
        self.assertNotIn("logs/backend-stderr.log", names)
        self.assertFalse(summary["raw_logs_included"])
        self.assertEqual(
            {item["name"] for item in summary["files"]},
            {"desktop-runtime.log", "backend-stdout.log", "backend-stderr.log"},
        )
        self.assertNotIn("secret-value", bundle_text)
        self.assertNotIn("abc123", bundle_text)
        self.assertNotIn("C:\\Users\\me", bundle_text)

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

def test_model_runtime_stop_route_stops_managed_child_before_reporting_status() -> None:
    from backend.app.api.routes import models

    stopped: list[str] = []
    with (
        patch.object(
            models,
            "stop_managed_runtime",
            side_effect=lambda: stopped.append("stopped"),
        ),
        patch.object(
            models,
            "runtime_status",
            return_value={
                "provider": "managed-llama.cpp",
                "base_url": "",
                "model": "",
                "available": False,
                "state": "stopped",
                "in_flight": 0,
                "detail": "The managed local model is stopped.",
            },
        ),
    ):
        result = models.stop_runtime()

    assert stopped == ["stopped"]
    assert result["state"] == "stopped"


if __name__ == "__main__":
    unittest.main()
