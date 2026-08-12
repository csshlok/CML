import io
import json
import unittest
from contextlib import nullcontext
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from backend.app.core.llm_runtime import (
    LLMRuntimeError,
    _openai_post,
    probe_runtime_generation,
)


class LLMRuntimeTransportTests(unittest.TestCase):
    def test_http_rejection_preserves_detail_and_closes_the_response(self) -> None:
        body = io.BytesIO(
            json.dumps(
                {"error": {"message": "request exceeds the available context size"}}
            ).encode("utf-8")
        )
        error = HTTPError(
            "http://127.0.0.1:49960/v1/chat/completions",
            400,
            "Bad Request",
            {},
            body,
        )
        with (
            patch(
                "backend.app.core.llm_runtime.urlopen",
                side_effect=error,
            ),
            self.assertRaises(LLMRuntimeError) as raised,
        ):
            _openai_post(
                "/chat/completions",
                {"messages": []},
                timeout=1,
                config={
                    "provider": "local",
                    "base_url": "http://127.0.0.1:49960/v1",
                    "model": "test",
                },
            )

        self.assertIn("rejected the request", str(raised.exception))
        self.assertIn("exceeds the available context size", str(raised.exception))
        self.assertNotIn("not reachable", str(raised.exception))
        self.assertTrue(body.closed)

    def test_network_failure_remains_an_unreachable_runtime_error(self) -> None:
        with (
            patch(
                "backend.app.core.llm_runtime.urlopen",
                side_effect=URLError("connection refused"),
            ),
            self.assertRaisesRegex(LLMRuntimeError, "not reachable"),
        ):
            _openai_post(
                "/chat/completions",
                {"messages": []},
                timeout=1,
                config={
                    "provider": "local",
                    "base_url": "http://127.0.0.1:49960/v1",
                    "model": "test",
                },
            )

    def test_generation_probe_uses_the_completion_endpoint(self) -> None:
        config = {
            "provider": "managed-llama.cpp",
            "base_url": "http://127.0.0.1:49960/v1",
            "model": "test-model",
        }
        status = {
            **config,
            "available": True,
            "state": "ready",
            "in_flight": 0,
            "detail": "cached status",
        }
        with (
            patch(
                "backend.app.core.llm_runtime.generation_in_flight",
                return_value=nullcontext(config),
            ),
            patch(
                "backend.app.core.llm_runtime._openai_post",
                return_value={"choices": [{"message": {"content": "OK"}}]},
            ) as request,
            patch("backend.app.core.llm_runtime.runtime_status", return_value=status),
        ):
            result = probe_runtime_generation()

        self.assertEqual(request.call_args.args[0], "/chat/completions")
        self.assertEqual(request.call_args.args[1]["max_tokens"], 8)
        self.assertEqual(result["detail"], "Local model completed a test generation.")


if __name__ == "__main__":
    unittest.main()
