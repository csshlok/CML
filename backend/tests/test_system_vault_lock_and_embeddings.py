import importlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class SystemVaultLockAndEmbeddingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "test.sqlite3"
        self.status_path = self.data_dir / "startup-status.json"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_STARTUP_STATUS_PATH"] = str(self.status_path)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

        import backend.app.core.vault_lock as vault_lock_module

        vault_lock_module._LOCK_PATH = None

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_STARTUP_STATUS_PATH",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_ALLOW_UNAUTHENTICATED_API",
            "CML_BACKEND_MODE",
            "CML_API_TOKEN",
            "CML_VAULT_LOCK_OVERRIDE",
            "CML_MODELS_DIR",
            "CML_MODEL_INTEGRITY_MANIFEST_PATH",
            "CML_MODEL_INTEGRITY_MANIFEST_URL",
        ):
            os.environ.pop(key, None)
        try:
            import backend.app.core.vault_lock as vault_lock_module

            vault_lock_module._LOCK_PATH = None
        except Exception:
            pass
        self.tmp.cleanup()

    def test_pre_vault_startup_status_route_is_available(self) -> None:
        os.environ["CML_BACKEND_MODE"] = "pre_vault"
        client = self._client()
        try:
            response = client.get("/api/v1/system/startup-status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn("phase", response.json())

    def test_pre_vault_embedding_configuration_route_is_available(self) -> None:
        os.environ["CML_BACKEND_MODE"] = "pre_vault"
        client = self._client()
        try:
            response = client.post(
                "/api/v1/models/embeddings/configure",
                json={"provider": "hash", "cache_dir": None, "model": "hash"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "hash")

    def test_pre_vault_vault_lock_audit_route_is_blocked(self) -> None:
        os.environ["CML_BACKEND_MODE"] = "pre_vault"
        client = self._client()
        try:
            response = client.get("/api/v1/system/vault-lock/audit")
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)

    def test_vault_lock_audit_route_returns_recent_rows(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vault_lock_audit (
                    id, event_type, pid, owner_pid, lock_path, detail, user_choice, created_at
                )
                VALUES
                    ('audit-1', 'acquired', 101, NULL, 'C:/vault/.vault.lock', '', '', ?),
                    ('audit-2', 'released', 101, NULL, 'C:/vault/.vault.lock', '', '', ?)
                """,
                (now, now),
            )

        client = self._client()
        try:
            response = client.get("/api/v1/system/vault-lock/audit?limit=10")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 2)
        self.assertIn("event_type", payload[0])
        self.assertIn("lock_path", payload[0])
        self.assertNotIn("raw_text", payload[0])

    def test_embedding_status_reports_setup_required_without_real_model(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.embeddings import embedding_status

        os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "0"
        get_settings.cache_clear()

        with patch(
            "backend.app.core.embeddings._embed_with_sentence_transformers",
            side_effect=RuntimeError("embedding model is not ready"),
        ):
            status = embedding_status()

        self.assertEqual(status["provider"], "sentence-transformers")
        self.assertFalse(status["available"])
        self.assertTrue(status["setup_required"])

    def test_semantic_search_returns_409_when_embeddings_unavailable(self) -> None:
        client = self._client()
        try:
            with patch(
                "backend.app.api.routes.search.require_embeddings_available",
                side_effect=RuntimeError("Semantic search requires embeddings are unavailable"),
            ):
                response = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "hello"},
                )
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)
        self.assertIn("embeddings are unavailable", response.json()["detail"])

    def test_source_listing_still_works_when_embeddings_are_unavailable(self) -> None:
        from backend.app.core.config import get_settings

        os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "0"
        get_settings.cache_clear()
        client = self._client()
        try:
            response = client.get("/api/v1/sources")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_text_ingestion_is_rejected_when_embeddings_are_unavailable(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        client = self._client()
        try:
            with patch(
                "backend.app.api.routes.sources.require_embeddings_available",
                side_effect=RuntimeError("Source ingestion requires the local embedding model, but embeddings are unavailable"),
            ):
                response = client.post(
                    "/api/v1/sources/from-text",
                    json={"vault_id": "vault-1", "title": "Blocked", "text": "memory search content"},
                )
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)
        self.assertIn("requires the local embedding model", response.json()["detail"])

    def test_configure_embeddings_rejects_hash_without_dev_flag(self) -> None:
        from backend.app.core.config import get_settings

        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "0"
        get_settings.cache_clear()
        client = self._client()
        try:
            response = client.post(
                "/api/v1/models/embeddings/configure",
                json={"provider": "hash", "cache_dir": None, "model": "hash"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 400)
        self.assertIn("explicit dev/test mode", response.json()["detail"])

    def test_acquire_vault_lock_creates_lock_file_and_audit_row(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        with patch("backend.app.core.vault_lock._current_command_line", return_value="python -m backend.app.main"):
            vault_lock_module.acquire_vault_lock()

        lock_path = self.data_dir / ".vault.lock"
        self.assertTrue(lock_path.exists())
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(lock["pid"], os.getpid())

        with connect() as conn:
            row = conn.execute(
                "SELECT event_type FROM vault_lock_audit ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["event_type"], "acquired")

    def test_acquire_vault_lock_reclaims_dead_owner(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        lock_path = self.data_dir / ".vault.lock"
        lock_path.write_text(json.dumps({"pid": 98765, "created_at": "old"}), encoding="utf-8")

        with (
            patch("backend.app.core.vault_lock._classify_lock_owner", return_value="dead"),
            patch("backend.app.core.vault_lock._current_command_line", return_value="python -m backend.app.main"),
        ):
            vault_lock_module.acquire_vault_lock()

        with connect() as conn:
            events = [
                row["event_type"]
                for row in conn.execute(
                    "SELECT event_type FROM vault_lock_audit ORDER BY created_at ASC"
                ).fetchall()
            ]
        self.assertIn("reclaimed_dead", events)
        self.assertIn("acquired", events)

    def test_acquire_vault_lock_rejects_live_backend_owner(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        lock_path = self.data_dir / ".vault.lock"
        lock_path.write_text(json.dumps({"pid": 45678, "created_at": "old"}), encoding="utf-8")

        with patch("backend.app.core.vault_lock._classify_lock_owner", return_value="vault_backend"):
            with self.assertRaises(vault_lock_module.VaultLockError):
                vault_lock_module.acquire_vault_lock()

        with connect() as conn:
            row = conn.execute(
                "SELECT event_type FROM vault_lock_audit ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["event_type"], "conflict_live_owner")

    def test_acquire_vault_lock_rejects_unverified_owner(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        lock_path = self.data_dir / ".vault.lock"
        lock_path.write_text(json.dumps({"pid": 45679, "created_at": "old"}), encoding="utf-8")

        with patch("backend.app.core.vault_lock._classify_lock_owner", return_value="unverified"):
            with self.assertRaises(vault_lock_module.VaultLockUnverifiedError):
                vault_lock_module.acquire_vault_lock()

        with connect() as conn:
            row = conn.execute(
                "SELECT event_type FROM vault_lock_audit ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["event_type"], "conflict_unverified_owner")

    def test_acquire_vault_lock_allows_one_time_override(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        os.environ["CML_VAULT_LOCK_OVERRIDE"] = "open_anyway"
        lock_path = self.data_dir / ".vault.lock"
        lock_path.write_text(json.dumps({"pid": 45680, "created_at": "old"}), encoding="utf-8")

        with (
            patch("backend.app.core.vault_lock._classify_lock_owner", return_value="vault_backend"),
            patch("backend.app.core.vault_lock._current_command_line", return_value="python -m backend.app.main"),
        ):
            vault_lock_module.acquire_vault_lock()

        with connect() as conn:
            events = [
                row["event_type"]
                for row in conn.execute(
                    "SELECT event_type FROM vault_lock_audit ORDER BY created_at ASC"
                ).fetchall()
            ]
        self.assertIn("user_choice", events)
        self.assertIn("startup_result", events)
        self.assertIn("acquired", events)

    def test_release_vault_lock_removes_file_and_writes_audit(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        with patch("backend.app.core.vault_lock._current_command_line", return_value="python -m backend.app.main"):
            vault_lock_module.acquire_vault_lock()
        lock_path = self.data_dir / ".vault.lock"
        self.assertTrue(lock_path.exists())

        vault_lock_module.release_vault_lock()

        self.assertFalse(lock_path.exists())
        with connect() as conn:
            row = conn.execute(
                "SELECT event_type FROM vault_lock_audit ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["event_type"], "released")

    @unittest.skipUnless(os.name == "nt", "Windows process command-line probe")
    def test_classify_lock_owner_detects_real_uvicorn_backend(self) -> None:
        from backend.app.core import vault_lock

        probe_root = Path(self.tmp.name) / "live-backend-probe"
        env = os.environ.copy()
        env["CML_DATA_DIR"] = str(probe_root / "data")
        env["CML_DATABASE_PATH"] = str(probe_root / "data" / "probe.sqlite3")
        env["CML_STARTUP_STATUS_PATH"] = str(probe_root / "data" / "startup-status.json")
        env["CML_EMBEDDING_PROVIDER"] = "hash"
        env["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "7355"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:7355/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(0.25)
            else:
                self.fail("Timed out waiting for probe backend health check")

            classify_deadline = time.time() + 5
            while time.time() < classify_deadline:
                if vault_lock._classify_lock_owner(proc.pid) == "vault_backend":
                    break
                time.sleep(0.25)
            else:
                self.fail(f"Expected vault_backend, got {vault_lock._classify_lock_owner(proc.pid)!r}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    @unittest.skipUnless(os.name == "nt", "Windows process command-line probe")
    def test_classify_lock_owner_does_not_trust_backend_token_in_unrelated_process_argv(self) -> None:
        from backend.app.core import vault_lock

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(15)", "backend.app.main"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            time.sleep(1)
            self.assertEqual(vault_lock._classify_lock_owner(proc.pid), "other_process")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def test_full_startup_phase_sequence_matches_spec(self) -> None:
        import backend.app.main as main_module

        phases: list[str] = []

        with (
            patch.object(main_module, "write_startup_status", side_effect=lambda phase, **_: phases.append(phase)),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "acquire_vault_lock"),
            patch.object(main_module, "init_db"),
            patch.object(main_module, "run_migrations"),
            patch.object(main_module, "verify_sqlite_integrity"),
            patch.object(main_module, "verify_schema_version"),
            patch.object(main_module, "recover_interrupted_generations"),
            patch.object(main_module, "enqueue_startup_reconciliation_jobs"),
            patch.object(main_module, "start_background_worker"),
        ):
            main_module.startup()

        self.assertEqual(
            phases,
            [
                "starting",
                "vault_lock_acquiring",
                "vault_lock_acquired",
                "database_initializing",
                "integrity_check_running",
                "schema_check_running",
                "job_recovery_running",
                "reconciliation_queued",
                "runtime_detection_running",
                "ready",
            ],
        )

    def test_lock_override_audit_sequence_is_complete(self) -> None:
        import backend.app.core.vault_lock as vault_lock_module
        from backend.app.core.database import connect

        os.environ["CML_VAULT_LOCK_OVERRIDE"] = "open_anyway"
        lock_path = self.data_dir / ".vault.lock"
        lock_path.write_text(json.dumps({"pid": 45681, "created_at": "old"}), encoding="utf-8")

        with (
            patch("backend.app.core.vault_lock._classify_lock_owner", return_value="unverified"),
            patch("backend.app.core.vault_lock._current_command_line", return_value="python -m backend.app.main"),
        ):
            vault_lock_module.acquire_vault_lock()

        with connect() as conn:
            events = [
                row["event_type"]
                for row in conn.execute(
                    "SELECT event_type FROM vault_lock_audit ORDER BY created_at ASC"
                ).fetchall()
            ]

        self.assertEqual(
            events,
            [
                "lock_override_detection",
                "dialog_shown",
                "user_choice",
                "startup_result",
                "acquired",
            ],
        )

    def test_cancel_embedding_download_marks_state_cancelled(self) -> None:
        from backend.app.core.embeddings import cancel_embedding_model_download, start_embedding_model_download

        with patch("threading.Thread.start", return_value=None):
            queued = start_embedding_model_download(str(self.data_dir / "embeddings"), "sentence-transformers/test-model")
        cancelled = cancel_embedding_model_download()

        self.assertIn(queued["status"], {"queued", "downloading"})
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIn("Cancellation requested", cancelled["error"])

    def test_local_model_cancel_cleans_partial_file(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        class ImmediateThread:
            def __init__(self, *, target, args=(), daemon=None, **_kwargs) -> None:
                self._target = target
                self._args = args
                self.daemon = daemon

            def start(self) -> None:
                self._target(*self._args)

        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeStream:
            def __init__(self) -> None:
                self.headers = FakeHeaders({"Content-Length": str(4 * 1024 * 1024)})
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size: int) -> bytes:
                self.calls += 1
                if self.calls == 1:
                    return b"a" * (1024 * 1024)
                if self.calls == 2:
                    model_registry.cancel_model_download("qwen3-4b-q4_k_m")
                    return b"b" * (1024 * 1024)
                return b""

        target_dir = self.data_dir / "models"
        os.environ["CML_MODELS_DIR"] = str(target_dir)

        get_settings.cache_clear()
        model_registry._download_state.clear()
        model_registry._cancelled_downloads.clear()

        with (
            patch("backend.app.core.model_registry.threading.Thread", ImmediateThread),
            patch("backend.app.core.model_registry._download_expected_model_sha256", return_value="0" * 64),
            patch("backend.app.core.model_registry._resolve_gguf_filename", return_value="model.Q4_K_M.gguf"),
            patch("backend.app.core.model_registry.urlopen", return_value=FakeStream()),
        ):
            model_registry.start_model_download("qwen3-4b-q4_k_m")

        state = model_registry.model_status("qwen3-4b-q4_k_m")["download"]
        partial = target_dir / "qwen3-4b-q4_k_m" / "model.Q4_K_M.gguf.part"
        final = target_dir / "qwen3-4b-q4_k_m" / "model.Q4_K_M.gguf"
        self.assertEqual(state["status"], "cancelled")
        self.assertFalse(partial.exists())
        self.assertFalse(final.exists())

    def test_local_model_status_requires_real_gguf_file(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        model_dir = self.data_dir / "models" / "qwen3-4b-q4_k_m"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "model.txt").write_text("not a gguf", encoding="utf-8")
        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        get_settings.cache_clear()

        status = model_registry.model_status("qwen3-4b-q4_k_m")

        self.assertFalse(status["installed"])
        self.assertIsNone(status["local_path"])

    def test_local_model_status_marks_installed_when_matching_gguf_exists(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        model_dir = self.data_dir / "models" / "qwen3-4b-q4_k_m"
        model_dir.mkdir(parents=True, exist_ok=True)
        expected = model_dir / "Qwen3-Q4_K_M.gguf"
        expected.write_bytes(b"gguf")
        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        get_settings.cache_clear()

        status = model_registry.model_status("qwen3-4b-q4_k_m")

        self.assertTrue(status["installed"])
        self.assertEqual(status["local_path"], str(expected))

    def test_large_model_download_checks_disk_preflight_before_starting(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        empty_manifest = self.data_dir / "empty-model-integrity.json"
        empty_manifest.write_text(json.dumps({"version": 1, "models": {}}), encoding="utf-8")
        os.environ["CML_MODEL_INTEGRITY_MANIFEST_PATH"] = str(empty_manifest)
        get_settings.cache_clear()
        model_registry._download_state.clear()
        model_registry._cancelled_downloads.clear()

        free_bytes = 5 * 1024 * 1024 * 1024

        class FakeUsage:
            total = 100 * 1024 * 1024 * 1024
            used = total - free_bytes
            free = free_bytes

        with (
            patch("backend.app.core.model_registry._find_local_model_file", return_value=None),
            patch("backend.app.core.model_registry.threading.Thread.start", return_value=None),
            patch("shutil.disk_usage", return_value=FakeUsage()),
        ):
            result = model_registry.start_model_download("gemma-3-12b-it-q4_k_m")

        self.assertNotEqual(result["status"], "resolving")

    def test_download_cancel_after_completion_does_not_mask_installed_model(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        empty_manifest = self.data_dir / "empty-download-integrity.json"
        empty_manifest.write_text(json.dumps({"version": 1, "models": {}}), encoding="utf-8")
        os.environ["CML_MODEL_INTEGRITY_MANIFEST_PATH"] = str(empty_manifest)
        get_settings.cache_clear()
        model_registry._download_state.clear()
        model_registry._cancelled_downloads.clear()

        class FastResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Length": str(2 * 1024 * 1024)}
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size: int = -1) -> bytes:
                self.calls += 1
                if self.calls <= 2:
                    return b"x" * (1024 * 1024)
                return b""

        expected_digest = hashlib.sha256(b"x" * (2 * 1024 * 1024)).hexdigest()
        with (
            patch("backend.app.core.model_registry._find_local_model_file", return_value=None),
            patch("backend.app.core.model_registry._download_expected_model_sha256", return_value=expected_digest),
            patch("backend.app.core.model_registry._expected_model_sha256", return_value=expected_digest),
            patch("backend.app.core.model_registry._resolve_gguf_filename", return_value="model.Q4_K_M.gguf"),
            patch("backend.app.core.model_registry.validate_huggingface_url", return_value=None),
            patch("backend.app.core.model_registry.urlopen", return_value=FastResponse()),
        ):
            model_registry.start_model_download("qwen3-4b-q4_k_m")
            for _ in range(40):
                status = model_registry.model_status("qwen3-4b-q4_k_m")
                if status["installed"]:
                    break
                time.sleep(0.05)
            cancelled = model_registry.cancel_model_download("qwen3-4b-q4_k_m")
            final = model_registry.model_status("qwen3-4b-q4_k_m")

        self.assertEqual(cancelled["status"], "installed")
        self.assertTrue(final["installed"])

    def test_second_model_download_is_blocked_while_another_is_active(self) -> None:
        from backend.app.core import model_registry

        model_registry._download_state.clear()
        model_registry._cancelled_downloads.clear()
        model_registry._download_state["qwen3-8b-q4_k_m"] = {
            "model_id": "qwen3-8b-q4_k_m",
            "status": "downloading",
            "bytes_downloaded": 1024,
            "total_bytes": None,
            "error": None,
        }

        with patch("backend.app.core.model_registry._find_local_model_file", return_value=None):
            result = model_registry.start_model_download("qwen3-4b-q4_k_m")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("Another model download", result["error"])

    def test_embedding_download_state_reports_progress_contract(self) -> None:
        from backend.app.core.embeddings import embedding_download_status, start_embedding_model_download

        with patch("threading.Thread.start", return_value=None):
            state = start_embedding_model_download(str(self.data_dir / "embeddings"), "sentence-transformers/test-model")
        current = embedding_download_status()

        self.assertIn("bytes_downloaded", state)
        self.assertIn("bytes_total", current)
        self.assertIn("progress_percent", current)
        self.assertIn("download_speed_bps", current)
        self.assertIn("eta_seconds", current)
        self.assertIn("updated_at", current)

    def test_vector_repair_plan_repair_and_compaction_cover_stale_missing_orphans(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.vector_maintenance import compact_vectors, repair_vectors, vector_repair_plan

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (id, vault_id, title, source_type, state, raw_text, extracted_text, created_at, updated_at)
                VALUES ('source-missing', 'vault-1', 'Missing', 'note', 'indexed', ?, ?, ?, ?)
                """,
                ("missing vector text " * 40, "missing vector text " * 40, now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (id, vault_id, title, source_type, state, raw_text, extracted_text, deleted_at, created_at, updated_at)
                VALUES ('deleted-source', 'vault-1', 'Deleted', 'note', 'indexed', 'deleted', 'deleted', ?, ?, ?)
                """,
                (now, now, now),
            )
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, vault_id, chunk_index, text, embedding, embedding_model_id,
                    content_hash, index_version, indexed_at, created_at
                )
                VALUES ('chunk-orphan', 'deleted-source', 'vault-1', 0, 'orphan', '[]', 'old-model', 'hash', 'old', NULL, ?)
                """,
                (now,),
            )

        plan = vector_repair_plan("vault-1")
        self.assertIn("source-missing", plan["missing_vector_source_ids"])
        self.assertEqual(plan["orphan_chunk_count"], 1)

        repaired = repair_vectors("vault-1")
        compacted = compact_vectors("vault-1")

        self.assertEqual(repaired["sources_repaired"], 1)
        self.assertGreater(repaired["chunks_indexed"], 0)
        self.assertEqual(compacted["orphan_chunks_removed"], 1)

    def test_vector_policy_transition_is_atomic_and_readable(self) -> None:
        from backend.app.core.vector_maintenance import (
            activate_embedding_index,
            begin_embedding_index_transition,
            embedding_index_policy,
        )

        building = begin_embedding_index_transition("sentence-transformers/new-model")
        active = activate_embedding_index("sentence-transformers/new-model")
        current = embedding_index_policy()

        self.assertEqual(building["transition_state"], "building")
        self.assertEqual(active["transition_state"], "active")
        self.assertEqual(current["active_embedding_model_id"], "sentence-transformers/new-model")
        self.assertIsNone(current["building_embedding_model_id"])

    def test_startup_repair_summary_reports_running_jobs_without_mutating_by_default(self) -> None:
        from backend.app.core.background_jobs import enqueue_job
        from backend.app.core.database import connect
        from backend.app.core.startup_repair import startup_repair_summary

        with connect() as conn:
            job = enqueue_job(conn, job_type="reindex_source", payload={"source_id": "source-1"})
            conn.execute("UPDATE app_jobs SET status = 'running' WHERE id = ?", (job["id"],))

        summary = startup_repair_summary()
        self.assertEqual(summary["database_integrity"], "ok")
        self.assertEqual(summary["interrupted_jobs"].get("requeue"), 1)
        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (job["id"],)).fetchone()
        self.assertEqual(row["status"], "running")

        repaired = startup_repair_summary(apply_recovery=True)
        self.assertEqual(repaired["interrupted_jobs"]["queued"], 1)

    def test_diagnostic_bundle_includes_runtime_startup_and_vector_summaries(self) -> None:
        from zipfile import ZipFile

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle

        bundle = create_diagnostic_bundle()
        with ZipFile(bundle["bundle_path"]) as archive:
            names = set(archive.namelist())

        self.assertIn("runtime-summary.json", names)
        self.assertIn("startup-repair-summary.json", names)
        self.assertIn("vector-summary.json", names)

    def test_network_security_blocks_ipv4_mapped_loopback_and_bad_schemes(self) -> None:
        from backend.app.core.network_security import NetworkSecurityError, validate_public_http_url

        with self.assertRaises(NetworkSecurityError):
            validate_public_http_url("http://[::ffff:127.0.0.1]/secret")
        with self.assertRaises(NetworkSecurityError):
            validate_public_http_url("file:///C:/secret.txt")

    def test_link_diagnostics_reports_sanitization_security_and_dynamic_fallback(self) -> None:
        from backend.app.core.extraction import link_extraction_diagnostics

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            result = link_extraction_diagnostics("https://user:pass@example.com/article")

        self.assertTrue(result["input_url_had_credentials"])
        self.assertEqual(result["sanitized_url"], "https://example.com/article")
        self.assertTrue(result["allowed"])
        self.assertIn("static_http", result["extraction_order"])
        self.assertIn("isolated_browser_rendered_dynamic_fallback", result["extraction_order"])
        self.assertTrue(result["browser_isolation"]["isolated_worker"])
        self.assertFalse(result["browser_isolation"]["downloads_allowed"])
        self.assertGreater(result["browser_isolation"]["request_budget"], 0)

    def test_backend_benchmark_script_exercises_search_and_vector_repair(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "backend" / "benchmark-backend.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("semantic_search", text)
        self.assertIn("vector_repair_plan", text)
        self.assertIn("repair_vectors", text)
        self.assertIn("compact_vectors", text)

    def test_scoring_ledger_threshold_benchmark_and_eval_fixtures(self) -> None:
        from backend.app.api.routes.search import get_retrieval_eval_fixtures
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.core.retrieval_scoring import scoring_ledger, threshold_benchmark
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="OCR packaging",
                source_type="note",
                raw_text="ocr packaging ghostscript tesseract qpdf scanned pdf " * 40,
            )
        )
        run_due_jobs_once(limit=1)

        ledger = scoring_ledger("vault-1", "ocr packaging scanned pdf", limit=5)
        benchmark = threshold_benchmark(
            "vault-1",
            fixtures=[
                {
                    "query": "ocr packaging scanned pdf",
                    "must_include_source_ids": [ledger["results"][0]["source_id"]],
                }
            ],
            thresholds=[0.1, 0.5],
        )
        fixtures = get_retrieval_eval_fixtures()

        self.assertGreater(ledger["results"][0]["bm25_score"], 0)
        self.assertIn("semantic_score", ledger["results"][0])
        self.assertEqual(benchmark["fixture_count"], 1)
        self.assertTrue(any(row["passes_fixture"] for row in benchmark["rows"]))
        self.assertTrue(fixtures["fixtures"])

    def test_storage_accounting_reports_source_vector_and_chat_footprint(self) -> None:
        from backend.app.api.routes.system import get_storage_accounting
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, saved, created_at, updated_at)
                VALUES ('chat-1', 'vault-1', 'Storage', 1, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                ("msg-1", "chat-1", "user", "storage accounting message", now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Storage source",
                source_type="note",
                raw_text="storage accounting vector chunk " * 50,
            )
        )
        run_due_jobs_once(limit=1)

        accounting = get_storage_accounting("vault-1")

        self.assertEqual(accounting["sources"]["count"], 1)
        self.assertGreater(accounting["chunks"]["count"], 0)
        self.assertEqual(accounting["chat"]["message_count"], 1)
        self.assertTrue(accounting["estimate"])
        self.assertIn("retrieval_snapshots", accounting)
        self.assertIn("analysis_evidence_packets", accounting)
        self.assertIn("external_captures", accounting)
        self.assertIn("expert_artifacts", accounting)

    def test_diagnostic_bundle_includes_policy_and_storage_accounting(self) -> None:
        from zipfile import ZipFile

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle, log_rotation_policy

        bundle = create_diagnostic_bundle()
        policy = log_rotation_policy()
        with ZipFile(bundle["bundle_path"]) as archive:
            names = set(archive.namelist())

        self.assertIn("log-rotation-policy.json", names)
        self.assertIn("storage-accounting.json", names)
        self.assertEqual(policy["max_log_file_bytes"], 5 * 1024 * 1024)
        self.assertEqual(policy["retained_log_files"], 10)

    def test_startup_repair_reports_interrupted_migrations(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.startup_repair import startup_repair_summary

        now = utc_now()
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
                INSERT INTO schema_migrations (version, name, started_at, status)
                VALUES (99, 'interrupted_test', ?, 'running')
                """,
                (now,),
            )

        summary = startup_repair_summary()

        self.assertEqual(summary["interrupted_migrations"][0]["version"], 99)
        self.assertEqual(summary["interrupted_migrations"][0]["status"], "running")

    def test_startup_repair_reports_failed_migrations(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.startup_repair import startup_repair_summary

        now = utc_now()
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
                VALUES (100, 'failed_test', ?, ?, 'failed', 'boom')
                """,
                (now, now),
            )

        summary = startup_repair_summary()

        self.assertEqual(summary["interrupted_migrations"][0]["version"], 100)
        self.assertEqual(summary["interrupted_migrations"][0]["status"], "failed")
        self.assertEqual(summary["interrupted_migrations"][0]["error"], "boom")

    def test_ocr_source_job_writes_page_progress_detail(self) -> None:
        from backend.app.core.background_jobs import _run_ocr_source, enqueue_job
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        source_path = self.data_dir / "scan.pdf"
        source_path.write_bytes(b"%PDF-1.4")
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, original_path, raw_text,
                    extracted_text, created_at, updated_at
                )
                VALUES ('source-ocr', 'vault-1', 'Scan', 'pdf', 'waiting', ?, '', '', ?, ?)
                """,
                (str(source_path), now, now),
            )
            job = enqueue_job(conn, job_type="ocr_source", payload={"source_id": "source-ocr"})
            conn.execute("UPDATE app_jobs SET status = 'running' WHERE id = ?", (job["id"],))

        with patch(
            "backend.app.core.extraction.extract_pages_from_path",
            return_value=("Scan", ["page one ocr text " * 30, "page two ocr text " * 30]),
        ):
            _run_ocr_source({"source_id": "source-ocr"}, job["id"])

        with connect() as conn:
            row = conn.execute("SELECT status_detail FROM app_jobs WHERE id = ?", (job["id"],)).fetchone()
        detail = json.loads(row["status_detail"])
        self.assertEqual(detail["page_current"], 2)
        self.assertEqual(detail["page_total"], 2)
        self.assertEqual(detail["progress_percent"], 100.0)

    def test_disposable_vault_delete_cleanup_removes_derived_data(self) -> None:
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Disposable",
                source_type="note",
                raw_text="delete cleanup disposable vault evidence " * 60,
            )
        )
        run_due_jobs_once(limit=1)

        delete_source(source["id"])
        run_due_jobs_once(limit=1)

        with connect() as conn:
            source_row = conn.execute("SELECT raw_text, extracted_text FROM sources WHERE id = ?", (source["id"],)).fetchone()
            chunk_count = conn.execute("SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?", (source["id"],)).fetchone()
            page_count = conn.execute("SELECT COUNT(*) AS count FROM source_pages WHERE source_id = ?", (source["id"],)).fetchone()
        self.assertEqual(source_row["raw_text"], "")
        self.assertEqual(source_row["extracted_text"], "")
        self.assertEqual(chunk_count["count"], 0)
        self.assertEqual(page_count["count"], 0)

    def test_download_cancel_smoke_script_exists_and_reports_cancellation_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "backend" / "smoke-download-cancel.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("cancel_embedding_model_download", text)
        self.assertIn("cancel_model_download", text)
        self.assertIn("cancellation_observed", text)

    def test_bridge_external_turn_capture_respects_permissions_and_indexes_source(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.bridge import create_bridge_client, log_external_turn, update_bridge_settings
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeClientCreate, BridgeExternalTurnCapture, BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-2', 'vault-1', 'Private', '', 'sage', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )

        client = create_bridge_client(
            BridgeClientCreate(
                name="Claude Desktop",
                allowed_vault_ids=["vault-1"],
                allowed_cluster_ids=["cluster-1"],
            )
        )
        update_bridge_settings(BridgeSettingsUpdate(enabled=True))
        result = log_external_turn(
            BridgeExternalTurnCapture(
                vault_id="vault-1",
                cluster_id="cluster-1",
                client_name="claude",
                user_prompt="summarize my notes",
                model_response="external model answer",
                model_name="claude-test",
            ),
            x_cml_bridge_token=client["token"],
        )
        run_due_jobs_once(limit=1)

        with connect() as conn:
            source = conn.execute("SELECT * FROM sources WHERE id = ?", (result["source_id"],)).fetchone()
            chunks = conn.execute("SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?", (result["source_id"],)).fetchone()
        self.assertEqual(source["source_type"], "external_transcript")
        self.assertEqual(source["cluster_id"], "cluster-1")
        self.assertGreater(chunks["count"], 0)

        with self.assertRaises(HTTPException) as exc:
            log_external_turn(
                BridgeExternalTurnCapture(
                    vault_id="vault-1",
                    cluster_id="cluster-2",
                    client_name="claude",
                    user_prompt="blocked",
                    model_response="blocked",
                ),
                x_cml_bridge_token=client["token"],
            )
        self.assertEqual(exc.exception.status_code, 403)

    def test_bridge_mcp_exposes_external_capture_tools(self) -> None:
        from backend.app.bridge_mcp import tools

        names = {tool["name"] for tool in tools()}

        self.assertIn("log_external_turn", names)
        self.assertIn("capture_external_artifact", names)

    def test_source_class_weighting_compare_and_report_export(self) -> None:
        from backend.app.api.routes.search import create_benchmark_report
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.core.retrieval_scoring import compare_source_classes, scoring_ledger
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Product note",
                source_type="note",
                raw_text="shared retrieval benchmark product source " * 50,
            )
        )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="External model turn",
                source_type="external_transcript",
                raw_text="shared retrieval benchmark external transcript source " * 50,
            )
        )
        for _ in range(2):
            run_due_jobs_once(limit=1)

        ledger = scoring_ledger("vault-1", "shared retrieval benchmark", limit=10)
        classes = {item["source_class"]: item for item in ledger["results"]}
        comparison = compare_source_classes("vault-1", "shared retrieval benchmark")
        report = create_benchmark_report("vault-1")

        self.assertIn("document", classes)
        self.assertIn("external_transcript", classes)
        self.assertGreater(classes["document"]["source_class_weight"], classes["external_transcript"]["source_class_weight"])
        self.assertIn("document", comparison["groups"])
        self.assertTrue(Path(report["json_path"]).exists())
        self.assertTrue(Path(report["markdown_path"]).exists())

    def test_failed_embedding_write_can_be_retried_without_partial_vectors(self) -> None:
        from backend.app.core.background_jobs import enqueue_job, run_due_jobs_once
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (id, vault_id, title, source_type, state, raw_text, extracted_text, created_at, updated_at)
                VALUES ('source-fail', 'vault-1', 'Fail', 'note', 'indexed', ?, ?, ?, ?)
                """,
                ("failed embedding write " * 50, "failed embedding write " * 50, now, now),
            )
            job = enqueue_job(conn, job_type="reindex_source", payload={"source_id": "source-fail"})

        with patch("backend.app.core.background_jobs.reindex_source_chunks", side_effect=RuntimeError("disk full")):
            run_due_jobs_once(limit=1)

        with connect() as conn:
            job_row = conn.execute("SELECT status, attempts, last_error FROM app_jobs WHERE id = ?", (job["id"],)).fetchone()
            chunk_count = conn.execute("SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = 'source-fail'").fetchone()
        self.assertEqual(job_row["status"], "queued")
        self.assertEqual(job_row["attempts"], 1)
        self.assertIn("disk full", job_row["last_error"])
        self.assertEqual(chunk_count["count"], 0)

    def test_backend_smoke_scripts_cover_active_index_and_retrieval_benchmark(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        active_script = repo_root / "scripts" / "backend" / "smoke-active-index-transition.ps1"
        benchmark_script = repo_root / "scripts" / "backend" / "benchmark-retrieval.ps1"

        self.assertIn("activate_embedding_index", active_script.read_text(encoding="utf-8"))
        benchmark_text = benchmark_script.read_text(encoding="utf-8")
        self.assertIn("export_benchmark_report", benchmark_text)
        self.assertIn("[int]$Sources = 100", benchmark_text)

    def test_query_cache_invalidates_when_contributing_source_changes(self) -> None:
        from backend.app.api.routes.search import create_query_cache, get_query_cache
        from backend.app.api.routes.sources import create_source, update_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate, SourceUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
        source = create_source(
            SourceCreate(vault_id="vault-1", title="Cache", source_type="note", raw_text="cache invalidation source")
        )
        create_query_cache("vault-1", "query:fingerprint", source["id"])
        update_source(source["id"], SourceUpdate(raw_text="cache invalidation source changed"))

        items = get_query_cache("vault-1")["items"]

        self.assertTrue(items[0]["invalidated"])

    def test_chat_pagination_and_retrieval_snapshot_compaction(self) -> None:
        from backend.app.api.routes.chat import compact_chat_retrieval_snapshots, get_chat_messages_page
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                "INSERT INTO chat_sessions (id, vault_id, title, saved, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("chat-1", "vault-1", "Paged", 1, now, now),
            )
            for index in range(3):
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"msg-{index}", "chat-1", "user", f"message {index}", f"{now}-{index}"),
                )
            for index in range(2):
                conn.execute(
                    """
                    INSERT INTO retrieval_snapshots (
                        id, message_id, session_id, vault_id, query, retrieval_mode, embedding_model_id, created_at
                    )
                    VALUES (?, 'msg-0', 'chat-1', 'vault-1', 'q', 'semantic', 'hash', ?)
                    """,
                    (f"snapshot-{index}", f"{now}-{index}"),
                )
                conn.execute(
                    """
                    INSERT INTO retrieval_snapshot_items (
                        id, snapshot_id, source_title_at_answer_time, short_snippet_excerpt,
                        relevance_score, item_rank, created_at
                    )
                    VALUES (?, ?, 'Source', ?, 1, 1, ?)
                    """,
                    (f"snapshot-item-{index}", f"snapshot-{index}", "x" * 500, now),
                )

        page = get_chat_messages_page("chat-1", limit=2)
        compacted = compact_chat_retrieval_snapshots(message_id="msg-0", keep_latest_per_message=1)

        self.assertEqual(len(page["items"]), 2)
        self.assertIsNotNone(page["next_cursor"])
        self.assertEqual(compacted["compacted_snapshots"], 1)

    def test_chat_pagination_cursor_is_stable_when_messages_share_timestamp(self) -> None:
        from backend.app.api.routes.chat import get_chat_messages_page
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
                )
                VALUES ('chat-cursor', 'vault-1', 'Cursor test', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            for message_id in ("msg-a", "msg-b", "msg-c"):
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, 'chat-cursor', 'user', ?, ?)",
                    (message_id, message_id, now),
                )

        first = get_chat_messages_page("chat-cursor", limit=2)
        second = get_chat_messages_page("chat-cursor", limit=2, cursor=first["next_cursor"])

        self.assertEqual([item["id"] for item in first["items"]], ["msg-a", "msg-b"])
        self.assertEqual([item["id"] for item in second["items"]], ["msg-c"])
        self.assertIsNone(second["next_cursor"])

    def test_extension_pairing_and_permission_audit(self) -> None:
        from backend.app.api.routes.extension import (
            approve_extension_pairing,
            list_extension_permission_audit,
            start_extension_pairing,
        )
        from backend.app.schemas import ExtensionPairingStartRequest

        pairing = start_extension_pairing(
            ExtensionPairingStartRequest(name="Browser", allowed_vault_ids=["vault-1"])
        )
        client = approve_extension_pairing(pairing["id"])
        audit = list_extension_permission_audit()

        self.assertEqual(client["name"], "Browser")
        self.assertTrue(any(row["event_type"] == "pairing_approved" for row in audit))

    def test_new_smoke_scripts_are_codex_dynamic_and_second_embedding_aware(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        codex = (repo_root / "scripts" / "backend" / "smoke-codex-mcp.ps1").read_text(encoding="utf-8")
        extension_http = (repo_root / "scripts" / "backend" / "smoke-browser-extension-http.ps1").read_text(encoding="utf-8")
        extension_browser = (repo_root / "scripts" / "backend" / "smoke-browser-extension-playwright.ps1").read_text(encoding="utf-8")
        dynamic = (repo_root / "scripts" / "backend" / "smoke-dynamic-link.ps1").read_text(encoding="utf-8")
        second = (repo_root / "scripts" / "backend" / "smoke-second-embedding-index.ps1").read_text(encoding="utf-8")

        self.assertIn("codex_style_jsonrpc", codex)
        self.assertIn("list_writeback_reviews", codex)
        self.assertIn("decide_writeback_review", codex)
        self.assertIn("list_captures", codex)
        self.assertIn("/api/v1/extension/capture-upload", extension_http)
        self.assertIn("x-cml-extension-token", extension_http)
        self.assertIn("x-cml-api-token", extension_http)
        self.assertIn("playwright.chromium.launch_persistent_context", extension_browser)
        self.assertIn("Save selected file", extension_browser)
        self.assertIn("popup_button_labels", extension_browser)
        self.assertIn("real_popup_target_seen", extension_browser)
        self.assertIn("real_popup_target_title", extension_browser)
        self.assertIn("browser_runtime_available", dynamic)
        self.assertIn("real_second_cache_observed", second)

    def test_bridge_runtime_files_do_not_hardcode_machine_specific_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        targets = [
            repo_root / "backend" / "app" / "bridge_mcp.py",
            repo_root / "backend" / "app" / "bridge_cli.py",
            repo_root / "apps" / "desktop" / "src" / "lib" / "backend.ts",
            repo_root / "apps" / "desktop" / "src" / "routes" / "_app.bridge.tsx",
            repo_root / "scripts" / "backend" / "smoke-codex-mcp.ps1",
            repo_root / "scripts" / "backend" / "smoke-browser-extension-http.ps1",
            repo_root / "scripts" / "backend" / "smoke-browser-extension-playwright.ps1",
        ]
        forbidden = [
            r"C:\\Users\\csshl",
            r"Desktop\\CML",
            r"T:\\",
        ]

        for target in targets:
            text = target.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertNotRegex(text, pattern, msg=f"{target} should not hardcode machine-specific path {pattern}")

    def test_model_integrity_manifest_reports_recorded_and_mismatch(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import (
            _model_integrity_status,
            _sha256_file,
            _write_integrity_manifest,
            get_model,
        )

        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        empty_manifest = self.data_dir / "empty-model-integrity.json"
        empty_manifest.write_text(json.dumps({"version": 1, "models": {}}), encoding="utf-8")
        os.environ["CML_MODEL_INTEGRITY_MANIFEST_PATH"] = str(empty_manifest)
        get_settings.cache_clear()
        model = get_model("qwen3-4b-q4_k_m")
        self.assertIsNotNone(model)
        model_dir = self.data_dir / "models" / model.id
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file = model_dir / "qwen3-test-Q4_K_M.gguf"
        model_file.write_bytes(b"model-bytes")

        digest = _sha256_file(model_file)
        _write_integrity_manifest(model, model_file, digest)
        recorded = _model_integrity_status(model, model_file)
        self.assertEqual(recorded["status"], "recorded")
        self.assertEqual(recorded["sha256"], digest)

        manifest = model_dir / "integrity.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["expected_sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        mismatch = _model_integrity_status(model, model_file)
        self.assertEqual(mismatch["status"], "mismatch")

    def test_trusted_model_integrity_manifest_supplies_expected_sha256(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import _expected_model_sha256, get_model, model_integrity_manifest_status

        manifest = self.data_dir / "model-integrity.json"
        expected = "a" * 64
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "models": {
                        "qwen3-4b-q4_k_m": {
                            "sha256": expected,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["CML_MODEL_INTEGRITY_MANIFEST_PATH"] = str(manifest)
        get_settings.cache_clear()
        model = get_model("qwen3-4b-q4_k_m")

        self.assertEqual(_expected_model_sha256(model), expected)
        self.assertEqual(model_integrity_manifest_status()["model_count"], 1)

    def test_default_model_integrity_manifest_pins_all_managed_models(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import (
            MODEL_REGISTRY,
            _expected_model_sha256,
            _resolve_gguf_filename,
            model_integrity_manifest_status,
        )

        os.environ.pop("CML_MODEL_INTEGRITY_MANIFEST_PATH", None)
        os.environ.pop("CML_MODEL_INTEGRITY_MANIFEST_URL", None)
        get_settings.cache_clear()

        status = model_integrity_manifest_status()

        self.assertTrue(status["available"])
        self.assertGreaterEqual(status["model_count"], len(MODEL_REGISTRY))
        for model in MODEL_REGISTRY:
            self.assertRegex(_expected_model_sha256(model), r"^[0-9a-f]{64}$")
            self.assertTrue(_resolve_gguf_filename(model).lower().endswith(".gguf"))

    def test_managed_model_download_fails_closed_without_trusted_hash(self) -> None:
        from backend.app.core import model_registry
        from backend.app.core.config import get_settings

        os.environ["CML_MODELS_DIR"] = str(self.data_dir / "models")
        empty_manifest = self.data_dir / "empty-model-integrity.json"
        empty_manifest.write_text(json.dumps({"version": 1, "models": {}}), encoding="utf-8")
        os.environ["CML_MODEL_INTEGRITY_MANIFEST_PATH"] = str(empty_manifest)
        get_settings.cache_clear()
        local_manifest = self.data_dir / "models" / "qwen3-4b-q4_k_m" / "integrity.json"
        local_manifest.parent.mkdir(parents=True, exist_ok=True)
        local_manifest.write_text(
            json.dumps({"expected_sha256": "a" * 64, "sha256": "a" * 64, "status": "verified"}),
            encoding="utf-8",
        )
        model_registry._download_state.clear()
        model_registry._download_state["qwen3-4b-q4_k_m"] = {"model_id": "qwen3-4b-q4_k_m", "status": "resolving"}

        with patch("backend.app.core.model_registry.urlopen") as fetch:
            model_registry._download_model(model_registry.get_model("qwen3-4b-q4_k_m"))

        fetch.assert_not_called()
        state = model_registry._download_state["qwen3-4b-q4_k_m"]
        self.assertEqual(state["status"], "failed")
        self.assertIn("integrity pin is missing", state["error"])

    def test_startup_phase_registry_and_staleness_route(self) -> None:
        from backend.app.core.startup_status import write_startup_status

        write_startup_status("database_initializing", status="running")
        old_status = json.loads(self.status_path.read_text(encoding="utf-8"))
        old_status["updated_at"] = "2000-01-01T00:00:00+00:00"
        self.status_path.write_text(json.dumps(old_status), encoding="utf-8")

        client = self._client()
        try:
            response = client.get("/api/v1/system/startup-phases?timeout_seconds=1")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["registry"]["ok"])
        self.assertTrue(payload["staleness"]["stale"])
        self.assertEqual(payload["staleness"]["reason"], "timeout")

    def test_query_cache_prune_removes_invalidated_oversized_and_over_limit_rows(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.retrieval_cache import prune_query_cache, put_query_cache

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
        first = put_query_cache(vault_id="vault-1", query_fingerprint="first", contributing_source_ids=[])
        put_query_cache(vault_id="vault-1", query_fingerprint="second", contributing_source_ids=[], payload={"x": "y" * 200})
        put_query_cache(vault_id="vault-1", query_fingerprint="third", contributing_source_ids=[])
        with connect() as conn:
            conn.execute("UPDATE query_evidence_cache SET invalidated_at = ? WHERE id = ?", (now, first["id"]))

        result = prune_query_cache(vault_id="vault-1", max_age_days=30, max_items=1, max_payload_bytes=50)

        self.assertEqual(result["deleted_old_or_invalidated"], 1)
        self.assertEqual(result["deleted_oversized"], 1)
        self.assertEqual(result["deleted_over_limit"], 0)

    def test_cluster_merge_writes_artifact_before_source_cluster_delete(self) -> None:
        from backend.app.api.routes.clusters import list_cluster_merge_artifacts, merge_cluster, rollback_cluster_merge_artifact
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ClusterMergeRequest

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-source', 'vault-1', 'Source', '', 'sage', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
                VALUES ('cluster-target', 'vault-1', 'Target', '', 'amber', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (id, vault_id, cluster_id, title, source_type, state, raw_text, extracted_text, created_at, updated_at)
                VALUES ('source-1', 'vault-1', 'cluster-source', 'Source', 'note', 'indexed', 'text', 'text', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                "INSERT INTO chat_sessions (id, vault_id, title, scope_cluster_id, saved, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("chat-1", "vault-1", "Scoped", "cluster-source", 1, now, now),
            )

        merged = merge_cluster("cluster-source", ClusterMergeRequest(target_cluster_id="cluster-target"))
        artifacts = list_cluster_merge_artifacts("cluster-target")["items"]

        self.assertEqual(merged["id"], "cluster-target")
        self.assertEqual(artifacts[0]["source_cluster_id"], "cluster-source")
        self.assertEqual(artifacts[0]["moved_source_ids"], ["source-1"])
        self.assertEqual(artifacts[0]["moved_chat_session_ids"], ["chat-1"])

        restored = rollback_cluster_merge_artifact(artifacts[0]["id"])
        with connect() as conn:
            source_row = conn.execute("SELECT cluster_id FROM sources WHERE id = 'source-1'").fetchone()
            chat_row = conn.execute("SELECT scope_cluster_id FROM chat_sessions WHERE id = 'chat-1'").fetchone()
            artifact_row = conn.execute("SELECT rolled_back_at FROM cluster_merge_artifacts WHERE id = ?", (artifacts[0]["id"],)).fetchone()

        self.assertEqual(restored["id"], "cluster-source")
        self.assertEqual(source_row["cluster_id"], "cluster-source")
        self.assertEqual(chat_row["scope_cluster_id"], "cluster-source")
        self.assertIsNotNone(artifact_row["rolled_back_at"])

    def test_watched_folder_scan_reports_backpressure_and_policy(self) -> None:
        from backend.app.core.local_integrations import WATCHED_FOLDER_SCAN_LIMIT, scan_local_folder, watched_folder_limits

        folder = self.data_dir / "watch"
        folder.mkdir()
        for index in range(WATCHED_FOLDER_SCAN_LIMIT + 1):
            (folder / f"note-{index:04d}.md").write_text("watched folder note", encoding="utf-8")

        result = scan_local_folder(str(folder), WATCHED_FOLDER_SCAN_LIMIT)
        limits = watched_folder_limits()

        self.assertTrue(result["truncated"])
        self.assertTrue(result["backpressure_required"])
        self.assertEqual(result["scan_limit"], WATCHED_FOLDER_SCAN_LIMIT)
        self.assertEqual(limits["watched_folder_scan_limit"], WATCHED_FOLDER_SCAN_LIMIT)

    def test_backend_policy_docs_and_packaging_validation_scripts_exist(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        threat_model = (repo_root / "docs" / "THREAT_MODEL.md").read_text(encoding="utf-8")
        merge_policy = (repo_root / "docs" / "CLUSTER_MERGE_POLICY.md").read_text(encoding="utf-8")
        clean_machine = (repo_root / "scripts" / "packaging" / "validate-clean-machine-package.ps1").read_text(encoding="utf-8")
        full_vault = (repo_root / "scripts" / "packaging" / "smoke-packaged-full-vault.ps1").read_text(encoding="utf-8")
        benchmark_1k = (repo_root / "scripts" / "backend" / "benchmark-1k-vault.ps1").read_text(encoding="utf-8")

        self.assertIn("Bridge/MCP capture", threat_model)
        self.assertIn("Every cluster merge must write a merge artifact", merge_policy)
        self.assertIn("clean-machine validation plan", clean_machine)
        self.assertIn("semantic search returned no results", full_vault)
        self.assertIn("[int]$Sources = 1000", benchmark_1k)

    def test_first_run_readiness_reports_setup_required_until_real_runtime_setup(self) -> None:
        from backend.app.core.setup_readiness import first_run_readiness

        readiness = first_run_readiness()

        self.assertFalse(readiness["ready"])
        check_ids = {check["id"] for check in readiness["checks"]}
        self.assertIn("vault_path", check_ids)
        self.assertIn("embedding_setup", check_ids)
        self.assertIn("ocr_runtime", check_ids)
        self.assertEqual(readiness["status"], "setup_required")

    def test_startup_recovery_drills_reports_and_recovers_in_flight_generation(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.recovery_drills import startup_recovery_drills

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                "INSERT INTO chat_sessions (id, vault_id, title, saved, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("chat-1", "vault-1", "Recovery", 1, now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt,
                    state, runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at, completed_at
                )
                VALUES ('gen-1', 'chat-1', NULL, NULL, 'vault-1', 'recover me', 'in_flight',
                    '', '', '', NULL, ?, ?, NULL)
                """,
                (now, now),
            )

        dry_run = startup_recovery_drills(apply_recovery=False)
        applied = startup_recovery_drills(apply_recovery=True)

        self.assertEqual(dry_run["generation_counts_before"]["in_flight"], 1)
        self.assertEqual(applied["generations_recovered"], 1)
        self.assertEqual(applied["generation_counts_after"].get("in_flight", 0), 0)
        self.assertEqual(applied["generation_counts_after"]["retriable"], 1)

    def test_chat_evidence_retention_tombstones_deleted_sources_and_trims_excerpts(self) -> None:
        from backend.app.core.chat_retention import chat_evidence_retention_policy, enforce_chat_evidence_retention
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.data_dir), now, now),
            )
            conn.execute(
                "INSERT INTO chat_sessions (id, vault_id, title, saved, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("chat-1", "vault-1", "Evidence", 1, now, now),
            )
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                ("msg-1", "chat-1", "assistant", "answer", now),
            )
            conn.execute(
                """
                INSERT INTO sources (id, vault_id, title, source_type, state, raw_text, extracted_text, deleted_at, created_at, updated_at)
                VALUES ('source-deleted', 'vault-1', 'Deleted', 'note', 'deleted', '', '', ?, ?, ?)
                """,
                (now, now, now),
            )
            conn.execute(
                """
                INSERT INTO retrieval_snapshots (
                    id, message_id, session_id, vault_id, query, retrieval_mode, embedding_model_id, created_at
                )
                VALUES ('snapshot-1', 'msg-1', 'chat-1', 'vault-1', 'q', 'semantic', 'hash', ?)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO retrieval_snapshot_items (
                    id, snapshot_id, source_id, source_title_at_answer_time,
                    short_snippet_excerpt, relevance_score, item_rank, created_at
                )
                VALUES ('item-1', 'snapshot-1', 'source-deleted', 'Deleted', ?, 1, 1, ?)
                """,
                ("x" * 500, now),
            )

        result = enforce_chat_evidence_retention(message_id="msg-1", excerpt_chars=120)
        policy = chat_evidence_retention_policy()
        with connect() as conn:
            row = conn.execute("SELECT state, source_id, LENGTH(short_snippet_excerpt) AS length FROM retrieval_snapshot_items WHERE id = 'item-1'").fetchone()

        self.assertEqual(policy["deleted_source_state"], "source_deleted")
        self.assertEqual(result["deleted_source_tombstones"], 1)
        self.assertEqual(row["state"], "source_deleted")
        self.assertIsNone(row["source_id"])
        self.assertLessEqual(row["length"], 120)

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
