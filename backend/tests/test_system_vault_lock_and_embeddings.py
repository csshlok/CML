import importlib
import json
import os
import shutil
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
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "test.sqlite3"
        self.status_path = self.data_dir / "startup-status.json"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_STARTUP_STATUS_PATH"] = str(self.status_path)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

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
            "CML_BACKEND_MODE",
            "CML_API_TOKEN",
            "CML_VAULT_LOCK_OVERRIDE",
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

        with (
            patch("backend.app.core.model_registry._find_local_model_file", return_value=None),
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
        self.assertIn("browser_rendered_dynamic_fallback", result["extraction_order"])

    def test_backend_benchmark_script_exercises_search_and_vector_repair(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "backend" / "benchmark-backend.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("semantic_search", text)
        self.assertIn("vector_repair_plan", text)
        self.assertIn("repair_vectors", text)
        self.assertIn("compact_vectors", text)

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
