import unittest


class BridgeCLITests(unittest.TestCase):
    def test_bridge_cli_uses_configured_api_prefix_for_bridge_context(self) -> None:
        import os

        from backend.app.bridge_cli import api_path

        previous = os.environ.get("CML_API_PREFIX")
        os.environ["CML_API_PREFIX"] = "custom/v2/"
        try:
            self.assertEqual(api_path("/bridge/context"), "/custom/v2/bridge/context")
        finally:
            if previous is None:
                os.environ.pop("CML_API_PREFIX", None)
            else:
                os.environ["CML_API_PREFIX"] = previous

    def test_format_context_prefers_packet_text_when_available(self) -> None:
        from backend.app.bridge_cli import format_context

        payload = {
            "query": "project status",
            "packet_text": "CML Context Packet\n\nHow To Use This Context\n- Answer from the vault.",
            "warnings": ["legacy warning"],
            "selected_clusters": [{"id": "cluster-1", "name": "Roadmap"}],
            "source_snippets": [{"title": "Legacy source", "summary": "Legacy summary"}],
        }

        text = format_context(payload)

        self.assertEqual(text, payload["packet_text"])
        self.assertNotIn("Legacy source", text)

    def test_format_context_falls_back_to_legacy_snippet_rendering_without_packet_text(self) -> None:
        from backend.app.bridge_cli import format_context

        payload = {
            "query": "project status",
            "warnings": ["Bridge context is ranked by local semantic search."],
            "selected_clusters": [{"id": "cluster-1", "name": "Roadmap"}],
            "source_snippets": [
                {
                    "title": "Roadmap note",
                    "summary": "Important roadmap checkpoint for the project.",
                }
            ],
        }

        text = format_context(payload)

        self.assertIn("CML context for: project status", text)
        self.assertIn("Warnings:", text)
        self.assertIn("Roadmap", text)
        self.assertIn("Roadmap note", text)


if __name__ == "__main__":
    unittest.main()
