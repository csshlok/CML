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
            "CML_LLM_RUNTIME_COMMAND_JSON",
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
