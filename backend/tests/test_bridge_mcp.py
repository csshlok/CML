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
            "security_labels": ["lora_excluded"],
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
                    "arguments": {"source_id": "bridge-capture-1", "approved": "yes"},
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


if __name__ == "__main__":
    unittest.main()
