import io
import unittest
import importlib
import os
import threading
import time
import json
from unittest.mock import patch


class BridgeMCPTests(unittest.TestCase):
    def test_stdio_adapter_frames_errors_notifications_and_eof(self) -> None:
        from backend.app.bridge_mcp_stdio import run_stdio

        messages = (
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            b"{not json}\n"
            b"\xff\n"
            b'{"jsonrpc":"2.0","id":7,"method":"unknown"}\n'
        )
        responses: list[dict] = []

        self.assertEqual(run_stdio(stdin=io.BytesIO(messages), writer=responses.append), 0)
        self.assertEqual([item["error"]["code"] for item in responses[:2]], [-32700, -32700])
        self.assertEqual(responses[2]["id"], 7)
        self.assertEqual(responses[2]["error"]["code"], -32601)

    def test_stdio_adapter_discards_an_oversized_line_and_recovers(self) -> None:
        from backend.app.bridge_mcp_stdio import run_stdio

        oversized = b'{"padding":"' + (b"x" * 100) + b'"}\n'
        valid = b'{"jsonrpc":"2.0","id":8,"method":"tools/list"}\n'
        responses: list[dict] = []

        self.assertEqual(
            run_stdio(
                stdin=io.BytesIO(oversized + valid),
                writer=responses.append,
                max_message_bytes=64,
            ),
            0,
        )
        self.assertEqual(responses[0]["error"]["code"], -32001)
        self.assertEqual(responses[1]["id"], 8)
        self.assertIn("tools", responses[1]["result"])

    def test_initialize_negotiates_supported_protocol_and_rejects_unknown_version(self) -> None:
        from backend.app.bridge_mcp import handle_message

        supported = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        unsupported = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            }
        )

        self.assertEqual(supported["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(unsupported["result"]["protocolVersion"], "2025-11-25")

    def test_tool_contracts_are_strict_annotated_and_bounded(self) -> None:
        from backend.app.bridge_mcp_tools import TOOL_CONTRACTS

        for tool in TOOL_CONTRACTS:
            schema = tool["inputSchema"]
            self.assertFalse(schema["additionalProperties"], tool["name"])
            self.assertIn("annotations", tool)
            self.assertIn("readOnlyHint", tool["annotations"])
            self.assertIn("destructiveHint", tool["annotations"])
            self.assertIn("idempotentHint", tool["annotations"])
            self.assertIn("openWorldHint", tool["annotations"])
            self.assertEqual(tool["_meta"]["cml/toolVersion"], "1.0.0")
            for property_schema in schema["properties"].values():
                if property_schema["type"] == "string":
                    self.assertIn("maxLength", property_schema)

    def test_read_only_profile_hides_and_rejects_write_tools(self) -> None:
        from backend.app.bridge_mcp_tools import tools_for_profile, validate_tool_arguments

        names = {tool["name"] for tool in tools_for_profile("read_only")}
        validation = validate_tool_arguments(
            "capture_external_artifact",
            {"title": "Attempt", "content": "No"},
            profile="read_only",
        )

        self.assertIn("list_clusters", names)
        self.assertNotIn("capture_external_artifact", names)
        self.assertIn("read-only", validation)

    def test_tool_contract_rejects_unknown_fields_nul_and_fractional_limits(self) -> None:
        from backend.app.bridge_mcp_tools import validate_tool_arguments

        self.assertIn(
            "Unexpected",
            validate_tool_arguments("list_clusters", {"surprise": True}, profile="read_write"),
        )
        self.assertIn(
            "NUL",
            validate_tool_arguments("get_cluster_context", {"query": "bad\x00query"}, profile="read_write"),
        )
        self.assertIn(
            "integer",
            validate_tool_arguments("get_cluster_context", {"query": "ok", "limit": 1.5}, profile="read_write"),
        )
        for unsafe in ("\ud800", "hidden\u202eexe", "control\x07"):
            self.assertIn(
                "unsafe Unicode control",
                validate_tool_arguments(
                    "get_cluster_context",
                    {"query": unsafe},
                    profile="read_write",
                ),
            )
        self.assertIsNone(
            validate_tool_arguments(
                "get_cluster_context",
                {"query": "Unicode text is valid: सुरक्षा\nsecond line"},
                profile="read_write",
            )
        )

    def test_mcp_bridge_uses_configured_api_prefix_for_tool_calls(self) -> None:
        previous = os.environ.get("CML_API_PREFIX")
        os.environ["CML_API_PREFIX"] = "custom/v2/"
        try:
            import backend.app.bridge_mcp as bridge_mcp

            bridge_mcp = importlib.reload(bridge_mcp)
            self.assertEqual(bridge_mcp.api_path("/bridge/context"), "/custom/v2/bridge/context")
            with patch("backend.app.bridge_mcp.http_json", return_value={"query": "status"}) as http_json:
                bridge_mcp.call_get_cluster_context({"query": "status"}, request_id=42)
                http_json.assert_called_once()
                self.assertEqual(http_json.call_args.args[0], "/custom/v2/bridge/context")
        finally:
            if previous is None:
                os.environ.pop("CML_API_PREFIX", None)
            else:
                os.environ["CML_API_PREFIX"] = previous
            import backend.app.bridge_mcp as bridge_mcp

            importlib.reload(bridge_mcp)

    def test_initialized_notification_returns_no_response(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

        self.assertIsNone(response)

    def test_unknown_notification_also_returns_no_response(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message({"jsonrpc": "2.0", "method": "tools/list"})

        self.assertIsNone(response)

    def test_known_bridge_error_codes_are_stable(self) -> None:
        from backend.app.bridge_mcp import app_error_code, safe_application_error

        self.assertEqual(app_error_code("no_active_vault"), 1001)
        self.assertEqual(app_error_code("bridge_token_invalid"), 1003)
        self.assertEqual(app_error_code("idempotency_key_reused"), 1009)
        self.assertEqual(app_error_code("unexpected"), 1000)
        self.assertEqual(
            safe_application_error("bridge_review_changed"),
            ("conflict", "That review changed. Refresh it before deciding.", False),
        )
        self.assertEqual(safe_application_error("idempotency_request_in_progress")[0], "conflict")

    def test_backend_connection_reset_is_safe_and_retriable(self) -> None:
        from backend.app.bridge_mcp import CMLBridgeApplicationError, http_json

        with patch("backend.app.bridge_mcp.urlopen", side_effect=ConnectionResetError("secret path")):
            with self.assertRaises(CMLBridgeApplicationError) as raised:
                http_json("/bridge/clusters", request_id="reset-1")

        self.assertEqual(raised.exception.error_code, "backend_unavailable")
        self.assertTrue(raised.exception.retriable)
        self.assertNotIn("secret", raised.exception.message)

    def test_maximum_tool_output_is_utf8_safe_and_bounded(self) -> None:
        from backend.app.bridge_mcp import MAX_TOOL_OUTPUT_BYTES, result

        response = result(
            "large-1",
            {"content": [{"type": "text", "text": "सुरक्षा" * MAX_TOOL_OUTPUT_BYTES}]},
        )
        encoded_result = json.dumps(
            response["result"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertLessEqual(len(encoded_result), MAX_TOOL_OUTPUT_BYTES)
        self.assertTrue(response["result"]["_meta"]["output_bounded"])
        self.assertIn("shortened", response["result"]["content"][0]["text"].lower())

    def test_malformed_capture_tool_arguments_are_rejected(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "log_external_turn", "arguments": {"user_prompt": "only prompt"}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("model_response", response["error"]["message"])

    def test_invalid_log_external_turn_format_is_rejected(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "log_external_turn",
                    "arguments": {
                        "user_prompt": "status?",
                        "model_response": "answer",
                        "idempotency_key": "turn-request-0013",
                        "format": "yaml",
                    },
                },
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("receipt or json", response["error"]["message"])

    def test_get_cluster_context_tool_exposes_packet_format_by_default(self) -> None:
        from backend.app.bridge_mcp import tools

        tool = next(item for item in tools() if item["name"] == "get_cluster_context")
        properties = tool["inputSchema"]["properties"]

        self.assertIn("format", properties)
        self.assertEqual(properties["format"]["enum"], ["packet", "json"])

    def test_review_and_capture_tools_are_exposed(self) -> None:
        from backend.app.bridge_mcp import tools

        names = {tool["name"] for tool in tools()}

        self.assertIn("list_writeback_reviews", names)
        self.assertIn("decide_writeback_review", names)
        self.assertIn("list_captures", names)

    def test_get_cluster_context_defaults_to_packet_text(self) -> None:
        from backend.app.bridge_mcp import call_get_cluster_context

        payload = {
            "query": "project status",
            "selected_clusters": [{"id": "cluster-1", "name": "Roadmap"}],
            "source_snippets": [
                {
                    "title": "Roadmap note",
                    "source_type": "note",
                    "trust_tier": "trusted_local",
                    "summary": "Important roadmap checkpoint for the project.",
                }
            ],
            "warnings": ["Bridge context is ranked by local semantic search."],
        }

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_get_cluster_context({"query": "project status"}, request_id=1)

        text = response["content"][0]["text"]
        self.assertIn("CML Context Packet", text)
        self.assertIn("How To Use This Context", text)
        self.assertIn("Roadmap note", text)
        self.assertIn("Packet Telemetry", text)

    def test_get_cluster_context_json_format_is_opt_in(self) -> None:
        from backend.app.bridge_mcp import call_get_cluster_context

        payload = {"query": "project status", "selected_clusters": [], "source_snippets": [], "warnings": []}

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_get_cluster_context({"query": "project status", "format": "json"}, request_id=2)

        text = response["content"][0]["text"]
        self.assertTrue(text.lstrip().startswith("{"))
        self.assertIn('"query": "project status"', text)

    def test_invalid_get_cluster_context_format_is_rejected(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "get_cluster_context",
                    "arguments": {"query": "status", "format": "yaml"},
                },
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("packet or json", response["error"]["message"])

    def test_expand_context_item_tool_is_exposed_and_calls_backend(self) -> None:
        from backend.app.bridge_mcp import call_expand_context_item, tools

        tool = next(item for item in tools() if item["name"] == "expand_context_item")
        self.assertIn("handle", tool["inputSchema"]["properties"])

        payload = {"handle": "source:source-1", "source_id": "source-1", "text": "expanded text", "warnings": []}
        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_expand_context_item({"handle": "source:source-1"}, request_id=3)

        self.assertIn('"handle": "source:source-1"', response["content"][0]["text"])

    def test_expand_context_item_requires_handle(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "expand_context_item", "arguments": {}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("requires handle", response["error"]["message"])

    def test_log_external_turn_defaults_to_capture_receipt(self) -> None:
        from backend.app.bridge_mcp import call_log_external_turn, tools

        tool = next(item for item in tools() if item["name"] == "log_external_turn")
        self.assertIn("format", tool["inputSchema"]["properties"])

        payload = {
            "source_id": "bridge-capture-1",
            "vault_id": "vault-1",
            "cluster_id": "cluster-1",
            "source_type": "external_transcript",
            "indexed": True,
            "quality_state": "ungrounded",
            "review_required": True,
            "trust_tier": "low_trust_web",
            "reasons": ["no_packet_overlap_detected"],
            "security_labels": ["review_needed", "ungrounded_external"],
            "warnings": ["External model output was saved as derived transcript/artifact data."],
        }

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_log_external_turn(
                {"user_prompt": "What is the answer?", "model_response": "The moon is cheese."},
                request_id=14,
            )

        text = response["content"][0]["text"]
        self.assertIn("CML Capture Receipt", text)
        self.assertIn("Quality state: ungrounded", text)
        self.assertIn("Review required: yes", text)
        self.assertIn("no_packet_overlap_detected", text)

    def test_capture_external_artifact_json_format_is_opt_in(self) -> None:
        from backend.app.bridge_mcp import call_capture_external_artifact

        payload = {
            "source_id": "bridge-capture-2",
            "vault_id": "vault-1",
            "cluster_id": None,
            "source_type": "external_artifact",
            "indexed": True,
            "quality_state": "user_artifact",
            "review_required": False,
            "trust_tier": "external_capture",
            "reasons": ["explicit_artifact_capture"],
            "security_labels": ["external_untrusted"],
            "warnings": [],
        }

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_capture_external_artifact(
                {"title": "Summary", "content": "Stored artifact", "format": "json"},
                request_id=15,
            )

        text = response["content"][0]["text"]
        self.assertTrue(text.lstrip().startswith("{"))
        self.assertIn('"quality_state": "user_artifact"', text)

    def test_invalid_decide_writeback_review_arguments_are_rejected(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 16,
                "method": "tools/call",
                "params": {
                    "name": "decide_writeback_review",
                    "arguments": {
                        "source_id": "bridge-capture-1",
                        "approved": "yes",
                        "idempotency_key": "review-request-0016",
                    },
                },
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("boolean approved", response["error"]["message"])

    def test_list_writeback_reviews_defaults_to_summary(self) -> None:
        from backend.app.bridge_mcp import call_list_writeback_reviews

        payload = [
            {
                "source_id": "bridge-capture-1",
                "title": "External model turn - cml-mcp",
                "quality_state": "partially_grounded",
                "approved": False,
                "trust_tier": "external_capture",
            }
        ]

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_list_writeback_reviews({}, request_id=17)

        text = response["content"][0]["text"]
        self.assertIn("CML Writeback Review Queue", text)
        self.assertIn("partially_grounded", text)
        self.assertIn("approved=no", text)

    def test_decide_writeback_review_defaults_to_receipt(self) -> None:
        from backend.app.bridge_mcp import call_decide_writeback_review

        payload = {
            "source_id": "bridge-capture-1",
            "title": "External model turn - cml-mcp",
            "quality_state": "partially_grounded",
            "approved": True,
            "trust_tier": "trusted_reviewed",
            "reasons": ["matched_source_title"],
            "security_labels": [],
        }

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_decide_writeback_review(
                {"source_id": "bridge-capture-1", "approved": True},
                request_id=18,
            )

        text = response["content"][0]["text"]
        self.assertIn("CML Writeback Review Decision", text)
        self.assertIn("Approved: yes", text)
        self.assertIn("trusted_reviewed", text)

    def test_list_captures_defaults_to_summary(self) -> None:
        from backend.app.bridge_mcp import call_list_captures

        payload = [
            {
                "source_id": "bridge-capture-2",
                "title": "Manual summary",
                "source_type": "external_artifact",
                "quality_state": "user_artifact",
                "approved": False,
            }
        ]

        with patch("backend.app.bridge_mcp.http_json", return_value=payload):
            response = call_list_captures({}, request_id=19)

        text = response["content"][0]["text"]
        self.assertIn("CML Recent Captures", text)
        self.assertIn("user_artifact", text)
        self.assertIn("Manual summary", text)

    def test_concurrent_runtime_rejects_duplicate_ids_and_keeps_light_calls_responsive(self) -> None:
        from backend.app.bridge_mcp import ConcurrentMCPRuntime

        release = threading.Event()
        responses: list[dict] = []

        def handler(message):
            if message["id"] == 1:
                release.wait(2)
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"ok": True}}

        runtime = ConcurrentMCPRuntime(handler=handler, writer=responses.append, max_workers=2)
        runtime.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_cluster_context"}})
        runtime.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        runtime.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        deadline = time.monotonic() + 1
        while not any(item.get("id") == 2 for item in responses) and time.monotonic() < deadline:
            time.sleep(0.01)
        release.set()
        runtime.close()

        duplicate = next(item for item in responses if item.get("id") == 1 and "error" in item)
        self.assertIn("Duplicate", duplicate["error"]["message"])
        self.assertTrue(any(item.get("id") == 2 and "result" in item for item in responses))

    def test_concurrent_runtime_cancels_and_bounds_expensive_retrieval(self) -> None:
        from backend.app.bridge_mcp import ConcurrentMCPRuntime

        release = threading.Event()
        responses: list[dict] = []

        def handler(message):
            release.wait(2)
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"ok": True}}

        runtime = ConcurrentMCPRuntime(handler=handler, writer=responses.append, max_workers=8)
        for request_id in range(1, 6):
            runtime.dispatch({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": "get_cluster_context"},
            })
        runtime.dispatch({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 1},
        })
        release.set()
        runtime.close()

        overloaded = next(item for item in responses if item.get("id") == 5)
        cancelled = next(item for item in responses if item.get("id") == 1)
        self.assertEqual(overloaded["error"]["data"]["error_code"], "rate_limited")
        self.assertEqual(cancelled["error"]["data"]["error_code"], "cancelled")


if __name__ == "__main__":
    unittest.main()
