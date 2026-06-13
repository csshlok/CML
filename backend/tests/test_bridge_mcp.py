import unittest
from unittest.mock import patch


class BridgeMCPTests(unittest.TestCase):
    def test_initialized_notification_returns_no_response(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

        self.assertIsNone(response)

    def test_unknown_notification_also_returns_no_response(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message({"jsonrpc": "2.0", "method": "tools/list"})

        self.assertIsNone(response)

    def test_known_bridge_error_codes_are_stable(self) -> None:
        from backend.app.bridge_mcp import app_error_code

        self.assertEqual(app_error_code("no_active_vault"), 1001)
        self.assertEqual(app_error_code("bridge_token_invalid"), 1003)
        self.assertEqual(app_error_code("unexpected"), 1000)

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

    def test_get_cluster_context_tool_exposes_packet_format_by_default(self) -> None:
        from backend.app.bridge_mcp import tools

        tool = next(item for item in tools() if item["name"] == "get_cluster_context")
        properties = tool["inputSchema"]["properties"]

        self.assertIn("format", properties)
        self.assertEqual(properties["format"]["enum"], ["packet", "json"])

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


if __name__ == "__main__":
    unittest.main()
