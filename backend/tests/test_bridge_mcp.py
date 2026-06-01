import unittest


class BridgeMCPTests(unittest.TestCase):
    def test_initialized_notification_returns_no_response(self) -> None:
        from backend.app.bridge_mcp import handle_message

        response = handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

        self.assertIsNone(response)

    def test_known_bridge_error_codes_are_stable(self) -> None:
        from backend.app.bridge_mcp import app_error_code

        self.assertEqual(app_error_code("no_active_vault"), 1001)
        self.assertEqual(app_error_code("bridge_token_invalid"), 1003)
        self.assertEqual(app_error_code("unexpected"), 1000)


if __name__ == "__main__":
    unittest.main()
