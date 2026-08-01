import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


class ManagedModelRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_MODELS_DIR"] = str(Path(self.tmp.name) / "models")
        os.environ["CML_LLM_RUNTIME_BINARY"] = sys.executable
        os.environ["CML_LLM_RUNTIME_START_TIMEOUT_SECONDS"] = "4"
        os.environ["CML_LLM_RUNTIME_PROBE_TIMEOUT_SECONDS"] = "4"
        from backend.app.core.config import get_settings
        from backend.app.core.model_runtime_supervisor import stop_managed_runtime

        get_settings.cache_clear()
        stop_managed_runtime()
        self.model_path = self._write_verified_model()
        self.server_script = self._write_fake_server()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_runtime_supervisor import stop_managed_runtime

        stop_managed_runtime()
        for name in (
            "CML_DATA_DIR",
            "CML_MODELS_DIR",
            "CML_LLM_RUNTIME_BINARY",
            "CML_LLM_RUNTIME_CUDA_BINARY",
            "CML_LLM_RUNTIME_COMMAND_JSON",
            "CML_LLM_RUNTIME_PREFERENCE",
            "CML_LLM_RUNTIME_THREADS",
            "CML_LLM_RUNTIME_BATCH_THREADS",
            "CML_LLM_RUNTIME_CONTEXT_SIZE",
            "CML_LLM_RUNTIME_START_TIMEOUT_SECONDS",
            "CML_LLM_RUNTIME_PROBE_TIMEOUT_SECONDS",
        ):
            os.environ.pop(name, None)
        get_settings.cache_clear()
        self.tmp.cleanup()

    def test_activation_requires_live_generation_before_registry_commit(self) -> None:
        from backend.app.core.model_registry import activate_model_runtime, registry_state
        from backend.app.core.model_runtime_supervisor import managed_runtime_status

        self._configure_server("ok")
        activated = activate_model_runtime("qwen3-4b-q4_k_m")

        self.assertTrue(activated["active_chat"])
        self.assertEqual(registry_state()["active_chat_model_id"], "qwen3-4b-q4_k_m")
        status = managed_runtime_status()
        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["available"])
        self.assertEqual(status["model_id"], "qwen3-4b-q4_k_m")
        self.assertIsInstance(status["pid"], int)
        self.assertEqual(status["runtime_backend"], "cpu")

    def test_runtime_candidates_prefer_cuda_and_keep_cpu_fallback(self) -> None:
        from backend.app.core.model_runtime_supervisor import _runtime_candidates

        cuda_binary = Path(self.tmp.name) / "cuda" / "llama-server.exe"
        cuda_binary.parent.mkdir()
        cuda_binary.write_bytes(b"cuda")
        os.environ["CML_LLM_RUNTIME_CUDA_BINARY"] = str(cuda_binary)
        with patch(
            "backend.app.core.model_runtime_supervisor._nvidia_gpu_available",
            return_value=True,
        ):
            candidates = _runtime_candidates()

        self.assertEqual(candidates[0], ("cuda", str(cuda_binary.resolve())))
        self.assertEqual(candidates[1], ("cpu", str(Path(sys.executable).resolve())))

    def test_runtime_command_tunes_threads_and_gpu_offload(self) -> None:
        from backend.app.core.model_runtime_supervisor import _runtime_command

        with patch(
            "backend.app.core.model_runtime_supervisor._runtime_thread_counts",
            return_value=(8, 16),
        ):
            cuda = _runtime_command(
                "cuda-server.exe",
                "model.gguf",
                "qwen",
                1234,
                runtime_backend="cuda",
            )
            cpu = _runtime_command(
                "cpu-server.exe",
                "model.gguf",
                "qwen",
                1235,
                runtime_backend="cpu",
            )

        self.assertEqual(cuda[cuda.index("--threads") + 1], "8")
        self.assertEqual(cuda[cuda.index("--threads-batch") + 1], "16")
        self.assertEqual(cuda[cuda.index("--ctx-size") + 1], "4096")
        self.assertEqual(cuda[cuda.index("--n-gpu-layers") + 1], "auto")
        self.assertEqual(cuda[cuda.index("--fit") + 1], "on")
        self.assertEqual(cpu[cpu.index("--device") + 1], "none")
        self.assertNotIn("--n-gpu-layers", cpu)

    def test_gpu_start_failure_falls_back_to_cpu(self) -> None:
        from backend.app.core.model_runtime_supervisor import (
            ManagedRuntimeError,
            activate_managed_model,
        )

        with (
            patch(
                "backend.app.core.model_runtime_supervisor._runtime_candidates",
                return_value=[
                    ("cuda", "cuda-server.exe"),
                    ("cpu", "cpu-server.exe"),
                ],
            ),
            patch(
                "backend.app.core.model_runtime_supervisor._terminate_verified_orphans_locked",
                return_value={"count": 0, "pids": []},
            ),
            patch(
                "backend.app.core.model_runtime_supervisor._start_locked",
                side_effect=[
                    ManagedRuntimeError("CUDA driver unavailable"),
                    {"state": "ready", "runtime_backend": "cpu"},
                ],
            ) as start,
        ):
            result = activate_managed_model("qwen3-4b-q4_k_m", str(self.model_path))

        self.assertEqual(result["runtime_backend"], "cpu")
        self.assertEqual(start.call_count, 2)
        self.assertEqual(start.call_args_list[1].kwargs["attempts"][0]["runtime_backend"], "cuda")

    def test_orphan_cleanup_requires_exact_binary_model_and_loopback_host(self) -> None:
        from backend.app.core.model_runtime_supervisor import (
            _terminate_verified_orphans_locked,
        )

        runtime = Path(self.tmp.name) / "runtime" / "llama-server.exe"
        runtime.parent.mkdir()
        runtime.write_bytes(b"runtime")
        model = self.model_path.resolve()

        class Process:
            def __init__(self, pid: int, *, executable: str, model_path: str, host: str):
                self.pid = pid
                self.terminated = False
                self.info = {
                    "pid": pid,
                    "exe": executable,
                    "cmdline": [
                        executable,
                        "--model",
                        model_path,
                        "--host",
                        host,
                    ],
                }

            def terminate(self):
                self.terminated = True

            def kill(self):
                raise AssertionError("Matched fixture should terminate without a forced kill.")

        matched = Process(
            101,
            executable=str(runtime),
            model_path=str(model),
            host="127.0.0.1",
        )
        wrong_model = Process(
            102,
            executable=str(runtime),
            model_path=str(Path(self.tmp.name) / "other.gguf"),
            host="127.0.0.1",
        )
        wrong_binary = Process(
            103,
            executable=str(Path(self.tmp.name) / "other-server.exe"),
            model_path=str(model),
            host="127.0.0.1",
        )
        non_loopback = Process(
            104,
            executable=str(runtime),
            model_path=str(model),
            host="0.0.0.0",
        )
        with (
            patch("psutil.process_iter", return_value=[matched, wrong_model, wrong_binary, non_loopback]),
            patch("psutil.wait_procs", return_value=([matched], [])),
        ):
            result = _terminate_verified_orphans_locked(
                runtime_binaries={str(runtime)},
                model_paths={str(model)},
            )

        self.assertEqual(result, {"count": 1, "pids": [101]})
        self.assertTrue(matched.terminated)
        self.assertFalse(wrong_model.terminated)
        self.assertFalse(wrong_binary.terminated)
        self.assertFalse(non_loopback.terminated)

    def test_orphan_cleanup_blocks_duplicate_start_when_process_survives(self) -> None:
        from backend.app.core.model_runtime_supervisor import (
            ManagedRuntimeError,
            _terminate_verified_orphans_locked,
        )

        runtime = Path(self.tmp.name) / "runtime" / "llama-server.exe"
        runtime.parent.mkdir()
        runtime.write_bytes(b"runtime")
        model_path = str(self.model_path)

        class Process:
            pid = 105
            info = {
                "pid": 105,
                "exe": str(runtime),
                "cmdline": [
                    str(runtime),
                    "--model",
                    model_path,
                    "--host",
                    "127.0.0.1",
                ],
            }

            @staticmethod
            def terminate():
                return None

            @staticmethod
            def kill():
                return None

        process = Process()
        with (
            patch("psutil.process_iter", return_value=[process]),
            patch("psutil.wait_procs", side_effect=[([], [process]), ([], [process])]),
            self.assertRaisesRegex(ManagedRuntimeError, "could not stop"),
        ):
            _terminate_verified_orphans_locked(
                runtime_binaries={str(runtime)},
                model_paths={str(self.model_path)},
            )

    def test_stop_recovers_verified_runtime_orphan_from_persisted_state(self) -> None:
        from backend.app.core.model_runtime_supervisor import stop_managed_runtime

        persisted = {
            "state": "stopped",
            "available": False,
            "pid": None,
            "runtime_binary": "C:/Vault/runtime/llama-server.exe",
            "model_path": "C:/Vault/models/model.gguf",
        }
        with (
            patch(
                "backend.app.core.model_runtime_supervisor._load_state_locked",
                return_value=persisted,
            ),
            patch("backend.app.core.model_runtime_supervisor._stop_locked") as stop,
            patch(
                "backend.app.core.model_runtime_supervisor._terminate_verified_orphans_locked",
                return_value={"count": 1, "pids": [27904]},
            ) as terminate_orphans,
            patch("backend.app.core.model_runtime_supervisor._persist_state_locked") as persist,
        ):
            stop_managed_runtime()

        stop.assert_called_once_with(mark_stopped=False)
        terminate_orphans.assert_called_once_with(
            runtime_binaries={"C:/Vault/runtime/llama-server.exe"},
            model_paths={"C:/Vault/models/model.gguf"},
        )
        saved = persist.call_args.args[0]
        self.assertEqual(saved["state"], "stopped")
        self.assertFalse(saved["available"])
        self.assertIsNone(saved["pid"])
        self.assertEqual(saved["orphan_cleanup"], {"count": 1, "pids": [27904]})

    def test_models_health_without_generation_does_not_activate(self) -> None:
        from backend.app.core.model_registry import activate_model_runtime, registry_state
        from backend.app.core.model_runtime_supervisor import managed_runtime_status

        self._configure_server("empty")
        with self.assertRaisesRegex(ValueError, "generation check"):
            activate_model_runtime("qwen3-4b-q4_k_m")

        self.assertFalse(registry_state().get("active_chat_model_id"))
        self.assertEqual(managed_runtime_status()["state"], "failed")

    def test_generation_probe_disables_thinking_and_allows_a_visible_answer(self) -> None:
        from backend.app.core.model_runtime_supervisor import _probe_generation

        class RunningProcess:
            @staticmethod
            def poll() -> None:
                return None

        with patch(
            "backend.app.core.model_runtime_supervisor._json_request",
            return_value={"choices": [{"message": {"content": "OK"}}]},
        ) as request:
            _probe_generation("http://127.0.0.1:1234/v1", "qwen3-4b-q4_k_m", RunningProcess())

        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertGreaterEqual(payload["max_tokens"], 32)
        self.assertIn("/no_think", payload["messages"][0]["content"])

    def test_missing_runtime_binary_never_marks_installed_model_ready(self) -> None:
        from backend.app.core.model_registry import activate_model_runtime, registry_state

        os.environ["CML_LLM_RUNTIME_BINARY"] = str(Path(self.tmp.name) / "missing.exe")
        with self.assertRaisesRegex(ValueError, "engine is missing"):
            activate_model_runtime("qwen3-4b-q4_k_m")
        self.assertFalse(registry_state().get("active_chat_model_id"))

    def _configure_server(self, mode: str) -> None:
        os.environ["CML_LLM_RUNTIME_COMMAND_JSON"] = json.dumps(
            [
                sys.executable,
                str(self.server_script),
                "{port}",
                mode,
            ]
        )

    def _write_verified_model(self) -> Path:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import get_model, _expected_model_sha256

        get_settings.cache_clear()
        model = get_model("qwen3-4b-q4_k_m")
        assert model is not None
        model_dir = Path(os.environ["CML_MODELS_DIR"]) / model.id
        model_dir.mkdir(parents=True)
        model_path = model_dir / "Qwen3-4B-Q4_K_M.gguf"
        model_path.write_bytes(b"fixture")
        expected = _expected_model_sha256(model)
        (model_dir / "integrity.json").write_text(
            json.dumps({"sha256": expected, "expected_sha256": expected}),
            encoding="utf-8",
        )
        return model_path

    def _write_fake_server(self) -> Path:
        script = Path(self.tmp.name) / "fake_openai_server.py"
        script.write_text(
            textwrap.dedent(
                """
                import json
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
                import sys

                port = int(sys.argv[1])
                mode = sys.argv[2]

                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        if self.path == "/v1/models":
                            self.respond({"data": [{"id": "fixture"}]})
                        else:
                            self.send_error(404)

                    def do_POST(self):
                        length = int(self.headers.get("content-length", "0"))
                        self.rfile.read(length)
                        if self.path == "/v1/chat/completions":
                            content = "" if mode == "empty" else "OK"
                            self.respond({"choices": [{"message": {"content": content}}]})
                        else:
                            self.send_error(404)

                    def respond(self, payload):
                        body = json.dumps(payload).encode()
                        self.send_response(200)
                        self.send_header("content-type", "application/json")
                        self.send_header("content-length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                    def log_message(self, *_args):
                        return

                ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
                """
            ),
            encoding="utf-8",
        )
        return script


if __name__ == "__main__":
    unittest.main()
