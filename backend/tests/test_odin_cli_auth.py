import os
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import FastAPI
from fastapi.testclient import TestClient


class OdinCliAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        os.environ["CML_DATABASE_PATH"] = str(self.data_dir / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_API_TOKEN"] = "desktop-token-that-is-long-enough-for-tests"
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.migrations import run_migrations

        init_db()
        run_migrations()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-a", "Vault A", str(self.data_dir / "a"), now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-b", "Vault B", str(self.data_dir / "b"), now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_API_TOKEN",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_process_probe_never_terminates_a_live_process(self) -> None:
        from backend.app.odin_cli import _process_exists

        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertTrue(_process_exists(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)

    def _paired_session(self, *, scopes: list[str], vault_ids: list[str]) -> tuple[dict, dict, str]:
        import secrets

        from backend.app.core.cli_auth import (
            approve_pairing,
            consume_pairing,
            create_pairing_challenge,
            create_session,
            token_hash,
        )
        from backend.app.core.runtime_identity import BACKEND_INSTANCE_ID

        verifier = secrets.token_urlsafe(40)
        challenge = create_pairing_challenge(
            verifier_hash=token_hash(verifier),
            requested_scopes=scopes,
            requester_name="VS Code Odin",
            executable_fingerprint="a" * 64,
            runtime_instance_id=BACKEND_INSTANCE_ID,
        )
        client = approve_pairing(challenge["id"], scopes=scopes, allowed_vault_ids=vault_ids)
        consumed = consume_pairing(challenge["id"], verifier)
        session = create_session(
            client_id=client["id"],
            credential=consumed["credential"],
            executable_fingerprint="a" * 64,
        )
        return client, consumed, session["session_token"]

    def test_pairing_credential_is_single_use_and_only_hashes_are_persisted(self) -> None:
        from backend.app.core.cli_auth import CliAuthError, authenticate_session, consume_pairing
        from backend.app.core.database import connect

        client, consumed, session_token = self._paired_session(
            scopes=["project:read", "context:read"],
            vault_ids=["vault-a"],
        )
        context = authenticate_session(session_token)

        self.assertEqual(context["client_id"], client["id"])
        self.assertEqual(context["allowed_vault_ids"], {"vault-a"})
        with connect() as conn:
            client_row = conn.execute("SELECT * FROM cli_clients WHERE id = ?", (client["id"],)).fetchone()
            session_row = conn.execute("SELECT * FROM cli_sessions WHERE client_id = ?", (client["id"],)).fetchone()
            challenge_row = conn.execute(
                "SELECT * FROM cli_pairing_challenges WHERE client_id = ?", (client["id"],)
            ).fetchone()
        self.assertNotIn(consumed["credential"], tuple(str(value) for value in client_row))
        self.assertNotEqual(session_row["token_hash"], session_token)
        with self.assertRaises(CliAuthError) as replay:
            consume_pairing(challenge_row["id"], "wrong-verifier-value-that-is-long-enough")
        self.assertIn(replay.exception.code, {"invalid_pairing_verifier", "pairing_already_consumed"})

    def test_revocation_and_rotation_invalidate_existing_sessions(self) -> None:
        from backend.app.core.cli_auth import authenticate_session, revoke_client, rotate_client

        client, _consumed, session_token = self._paired_session(
            scopes=["project:read"],
            vault_ids=["vault-a"],
        )
        self.assertIsNotNone(authenticate_session(session_token))
        rotated = rotate_client(client["id"])
        self.assertTrue(rotated["requires_pairing"])
        self.assertIsNone(authenticate_session(session_token))

        other, _consumed, other_token = self._paired_session(
            scopes=["project:read"],
            vault_ids=["vault-a"],
        )
        revoke_client(other["id"])
        self.assertIsNone(authenticate_session(other_token))

    def test_session_exchange_rejects_an_executable_fingerprint_mismatch(self) -> None:
        from backend.app.core.cli_auth import CliAuthError, create_session

        client, consumed, _session_token = self._paired_session(
            scopes=["project:read"], vault_ids=["vault-a"]
        )
        with self.assertRaises(CliAuthError) as mismatch:
            create_session(
                client_id=client["id"],
                credential=consumed["credential"],
                executable_fingerprint="b" * 64,
            )
        self.assertEqual(mismatch.exception.code, "executable_fingerprint_mismatch")

    def test_pairing_rejects_wrong_backend_and_unrequested_scope(self) -> None:
        import secrets

        from backend.app.core.cli_auth import (
            CliAuthError,
            approve_pairing,
            create_pairing_challenge,
            token_hash,
        )
        from backend.app.core.runtime_identity import BACKEND_INSTANCE_ID

        verifier = secrets.token_urlsafe(40)
        with self.assertRaises(CliAuthError) as identity_error:
            create_pairing_challenge(
                verifier_hash=token_hash(verifier),
                requested_scopes=["project:read"],
                requester_name="Odin",
                executable_fingerprint="b" * 64,
                runtime_instance_id="wrong-instance",
            )
        self.assertEqual(identity_error.exception.code, "backend_identity_mismatch")

        challenge = create_pairing_challenge(
            verifier_hash=token_hash(verifier),
            requested_scopes=["project:read"],
            requester_name="Odin",
            executable_fingerprint="b" * 64,
            runtime_instance_id=BACKEND_INSTANCE_ID,
        )
        with self.assertRaises(CliAuthError) as scope_error:
            approve_pairing(
                challenge["id"],
                scopes=["project:read", "project:write"],
                allowed_vault_ids=["vault-a"],
            )
        self.assertEqual(scope_error.exception.code, "scope_not_requested")

    def test_pairing_refresh_is_read_only_and_filters_expired_requests(self) -> None:
        import secrets
        from datetime import UTC, datetime, timedelta

        from backend.app.core.cli_auth import (
            create_pairing_challenge,
            list_pairing_challenges,
            token_hash,
        )
        from backend.app.core.database import connect
        from backend.app.core.runtime_identity import BACKEND_INSTANCE_ID

        verifier = secrets.token_urlsafe(40)
        challenge = create_pairing_challenge(
            verifier_hash=token_hash(verifier),
            requested_scopes=["project:read"],
            requester_name="Odin",
            executable_fingerprint="c" * 64,
            runtime_instance_id=BACKEND_INSTANCE_ID,
        )
        with connect() as conn:
            conn.execute(
                "UPDATE cli_pairing_challenges SET expires_at = ? WHERE id = ?",
                ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), challenge["id"]),
            )

        lock = sqlite3.connect(self.data_dir / "test.sqlite3", timeout=0.1)
        try:
            lock.execute("BEGIN IMMEDIATE")
            self.assertEqual(list_pairing_challenges(status="pending"), [])
            self.assertEqual(
                [item["id"] for item in list_pairing_challenges(status="expired")],
                [challenge["id"]],
            )
        finally:
            lock.rollback()
            lock.close()

    def test_odin_retries_temporary_pairing_store_contention(self) -> None:
        from backend.app.odin_cli import OdinClient

        busy = HTTPError(
            "http://127.0.0.1/api/v1/cli-auth/pairing-challenges",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(json.dumps({"detail": "cli_auth_store_busy"}).encode("utf-8")),
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"id":"cli-pair-test","status":"pending"}'

        with (
            patch("backend.app.odin_cli.urlopen", side_effect=[busy, Response()]) as request,
            patch("backend.app.odin_cli.time.sleep") as sleep,
        ):
            result = OdinClient("http://127.0.0.1:7343", "").request(
                "POST",
                "cli-auth/pairing-challenges",
                {"requester_name": "Odin"},
            )

        self.assertEqual(result["id"], "cli-pair-test")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_odin_reports_exhausted_store_contention_as_backend_unavailable(self) -> None:
        from backend.app.odin_cli import (
            BUSY_RETRY_ATTEMPTS,
            EXIT_BACKEND_UNAVAILABLE,
            OdinClient,
            OdinClientError,
        )

        def busy_response():
            return HTTPError(
                "http://127.0.0.1/api/v1/cli-auth/pairing-challenges",
                503,
                "Service Unavailable",
                {},
                io.BytesIO(json.dumps({"detail": "cli_auth_store_busy"}).encode("utf-8")),
            )

        with (
            patch(
                "backend.app.odin_cli.urlopen",
                side_effect=[busy_response() for _ in range(BUSY_RETRY_ATTEMPTS)],
            ) as request,
            patch("backend.app.odin_cli.time.sleep") as sleep,
            self.assertRaises(OdinClientError) as failure,
        ):
            OdinClient("http://127.0.0.1:7343", "").request(
                "POST",
                "cli-auth/pairing-challenges",
                {"requester_name": "Odin"},
            )

        self.assertEqual(failure.exception.exit_code, EXIT_BACKEND_UNAVAILABLE)
        self.assertIn("busy indexing", str(failure.exception))
        self.assertEqual(request.call_count, BUSY_RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, BUSY_RETRY_ATTEMPTS - 1)

    def test_pairing_route_exposes_database_contention_as_retryable(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.cli_auth import _call

        def locked():
            raise sqlite3.OperationalError("database is locked")

        with self.assertRaises(HTTPException) as response:
            _call(locked)

        self.assertEqual(response.exception.status_code, 503)
        self.assertEqual(response.exception.detail, "cli_auth_store_busy")

    def test_middleware_enforces_scope_endpoint_allowlist_and_vault_boundary(self) -> None:
        from backend.app.api.routes import cli_auth, projects
        from backend.app.core.auth import LocalApiAuthMiddleware
        from backend.app.core.projects import register_project

        project_a = register_project(vault_id="vault-a", root_path=str(self.repo), name="A", sync=False)
        second_repo = self.root / "repo-b"
        second_repo.mkdir()
        (second_repo / "main.py").write_text("value = 2\n", encoding="utf-8")
        project_b = register_project(vault_id="vault-b", root_path=str(second_repo), name="B", sync=False)
        _client, _consumed, session_token = self._paired_session(
            scopes=["project:read"],
            vault_ids=["vault-a"],
        )

        app = FastAPI()
        app.add_middleware(LocalApiAuthMiddleware)
        app.include_router(projects.router, prefix="/api/v1")
        app.include_router(cli_auth.router, prefix="/api/v1")
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {session_token}"}

        allowed = client.get(f"/api/v1/projects/{project_a['id']}", headers=headers)
        denied_scope = client.post(f"/api/v1/projects/{project_a['id']}/sync", headers=headers, json={})
        denied_vault = client.get(f"/api/v1/projects/{project_b['id']}", headers=headers)
        denied_surface = client.get("/api/v1/vaults", headers=headers)
        visible = client.get("/api/v1/projects", headers=headers)
        me = client.get("/api/v1/cli-auth/me", headers=headers)

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied_scope.status_code, 403)
        self.assertEqual(denied_vault.status_code, 403)
        self.assertEqual(denied_surface.status_code, 403)
        self.assertEqual([row["id"] for row in visible.json()], [project_a["id"]])
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["allowed_vault_ids"], ["vault-a"])


if __name__ == "__main__":
    unittest.main()
