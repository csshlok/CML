import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class BrowserIngestionPhase7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_browser_ingestion_rejects_file_scheme_before_worker_launch(self) -> None:
        from backend.app.core.browser_ingestion import BrowserIngestionError, extract_dynamic_text_from_url_isolated

        with self.assertRaises(BrowserIngestionError) as raised:
            extract_dynamic_text_from_url_isolated("file:///C:/Users/test/secrets.txt")
        self.assertIn("HTTP and HTTPS", str(raised.exception))

    def test_browser_ingestion_rejects_localhost_before_worker_launch(self) -> None:
        from backend.app.core.browser_ingestion import BrowserIngestionError, extract_dynamic_text_from_url_isolated

        with self.assertRaises(BrowserIngestionError) as raised:
            extract_dynamic_text_from_url_isolated("http://127.0.0.1:8000/private")
        self.assertIn("Private", str(raised.exception))

    def test_browser_worker_output_validation_rejects_oversized_text(self) -> None:
        from backend.app.core.browser_ingestion import BrowserIngestionError, validate_browser_worker_output

        payload = {
            "title": "Too large",
            "text": "A" * (2_000_001),
            "final_url": "https://example.com/app",
            "request_count": 1,
        }
        with patch("backend.app.core.network_security.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            with self.assertRaises(BrowserIngestionError) as raised:
                validate_browser_worker_output(payload)
        self.assertIn("text exceeded", str(raised.exception))

    def test_browser_worker_parent_rejects_malformed_json(self) -> None:
        from backend.app.core.browser_ingestion import BrowserIngestionError, extract_dynamic_text_from_url_isolated

        completed = subprocess.CompletedProcess(args=["worker"], returncode=0, stdout="{not-json", stderr="")
        fake_pool = Mock()
        fake_pool.execute.return_value = completed
        with (
            patch("backend.app.core.browser_ingestion.browser_fallback_available", return_value=True),
            patch(
                "backend.app.core.network_security.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("93.184.216.34", 443))],
            ),
            patch("backend.app.core.browser_ingestion._get_browser_worker_pool", return_value=fake_pool),
        ):
            with self.assertRaises(BrowserIngestionError) as raised:
                extract_dynamic_text_from_url_isolated("https://example.com/app")
        self.assertIn("malformed JSON", str(raised.exception))

    def test_browser_worker_admission_rejects_bursts_before_process_launch(self) -> None:
        from backend.app.core.browser_ingestion import BrowserIngestionError, _run_browser_worker

        with (
            patch("backend.app.core.browser_ingestion._BROWSER_WORKER_SLOTS.acquire", return_value=False),
            patch("backend.app.core.browser_ingestion.subprocess.run") as run,
        ):
            with self.assertRaises(BrowserIngestionError) as raised:
                _run_browser_worker(["python", "worker.py"])

        run.assert_not_called()
        self.assertIn("busy", str(raised.exception))

    def test_browser_fallback_is_disabled_by_default_even_when_runtime_exists(self) -> None:
        from backend.app.core.browser_ingestion import browser_ingestion_diagnostics

        with patch("backend.app.core.browser_ingestion.importlib.util.find_spec", return_value=object()):
            diagnostics = browser_ingestion_diagnostics()

        self.assertFalse(diagnostics["available"])
        self.assertFalse(diagnostics["enabled"])
        self.assertTrue(diagnostics["runtime_available"])
        self.assertEqual(diagnostics["max_concurrent_workers"], 2)
        self.assertTrue(diagnostics["persistent_worker_pool"])

    def test_browser_pool_reuses_a_worker_and_recycles_at_the_request_budget(self) -> None:
        import backend.app.core.browser_ingestion as browser_ingestion

        class FakeProcess:
            def __init__(self):
                self.response = ""
                self.returncode = None
                process = self

                class Input:
                    def write(self, value):
                        request = json.loads(value)
                        process.response = json.dumps({
                            "id": request["id"],
                            "ok": True,
                            "payload": {
                                "title": "Rendered",
                                "text": "body",
                                "final_url": request["url"],
                                "request_count": 1,
                            },
                        }) + "\n"

                    def flush(self):
                        return None

                class Output:
                    def readline(self):
                        return process.response

                self.stdin = Input()
                self.stdout = Output()

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        fake_process = FakeProcess()
        with patch("backend.app.core.browser_ingestion.subprocess.Popen", return_value=fake_process) as popen:
            pool = browser_ingestion._BrowserWorkerPool()
            try:
                self.assertEqual(pool.execute("https://example.com/one").returncode, 0)
                self.assertEqual(pool.execute("https://example.com/two").returncode, 0)
            finally:
                pool.close()
        popen.assert_called_once()

    def test_url_source_persists_browser_derived_low_trust_metadata(self) -> None:
        from backend.app.api.routes.sources import create_source_from_url
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceUrlCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        security = {
            "provenance": "browser_derived",
            "trust_tier": "low_trust_web",
            "security_labels": ["external_web", "browser_derived", "low_trust", "external_untrusted"],
            "browser_isolation": {"isolated_worker": True, "request_budget": 80},
            "final_url": "https://example.com/app",
        }
        with patch(
            "backend.app.api.routes.sources.extract_text_from_url_with_security",
            return_value=("Rendered", "Rendered app text " * 80, None, security),
        ):
            source = create_source_from_url(SourceUrlCreate(vault_id="vault-1", url="https://example.com/app"))

        self.assertEqual(source["provenance"], "browser_derived")
        self.assertEqual(source["trust_tier"], "low_trust_web")
        labels = json.loads(source["security_labels"])
        self.assertIn("browser_derived", labels)
        self.assertIn("external_untrusted", labels)
        self.assertIn("browser_derived", source["tags"])


if __name__ == "__main__":
    unittest.main()
