import json
import unittest

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError


def _request(path: str = "/api/v1/system/backup") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 7343),
        }
    )


class PublicErrorTests(unittest.TestCase):
    def test_technical_http_error_is_redacted_with_diagnostic_reference(self) -> None:
        from backend.app.core.public_errors import public_http_exception

        response = public_http_exception(
            _request(),
            HTTPException(
                status_code=500,
                detail=r"Permission denied: C:\Users\person\private\vault.sqlite3",
            ),
        )
        body = json.loads(response.body)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["error"]["code"], "internal_error")
        self.assertTrue(body["error"]["diagnostic_id"].startswith("diag-"))
        self.assertNotIn("Users", response.body.decode("utf-8"))
        self.assertNotIn("vault.sqlite3", response.body.decode("utf-8"))

    def test_safe_domain_code_keeps_simple_specific_copy(self) -> None:
        from backend.app.core.public_errors import public_http_exception

        response = public_http_exception(
            _request("/api/v1/system/unlock"),
            HTTPException(status_code=400, detail="invalid_vault_secret"),
        )
        body = json.loads(response.body)

        self.assertEqual(body["error"]["code"], "invalid_vault_secret")
        self.assertEqual(body["detail"], "Incorrect passphrase. Try again.")
        self.assertIsNone(body["error"]["diagnostic_id"])

    def test_typed_public_error_preserves_action_and_retry_contract(self) -> None:
        from backend.app.core.public_errors import api_error, public_http_exception

        response = public_http_exception(
            _request("/api/v1/jobs/job-1/resume"),
            api_error(
                status_code=409,
                code="job_not_resumable",
                message="This task cannot be resumed.",
                action="Open task details.",
                retryable=False,
            ),
        )
        body = json.loads(response.body)

        self.assertEqual(body["error"]["code"], "job_not_resumable")
        self.assertEqual(body["error"]["message"], "This task cannot be resumed.")
        self.assertEqual(body["error"]["action"], "Open task details.")
        self.assertFalse(body["error"]["retryable"])

    def test_validation_error_does_not_expose_payload_or_schema_internals(self) -> None:
        from backend.app.core.public_errors import public_validation_exception

        response = public_validation_exception(
            _request("/api/v1/projects"),
            RequestValidationError(
                [
                    {
                        "type": "string_type",
                        "loc": ("body", "root_path"),
                        "msg": r"Input should be a string: C:\Users\person\private",
                        "input": r"C:\Users\person\private",
                    }
                ]
            ),
        )
        body = json.loads(response.body)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertTrue(body["error"]["diagnostic_id"].startswith("diag-"))
        self.assertNotIn("root_path", response.body.decode("utf-8"))
        self.assertNotIn("Users", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
