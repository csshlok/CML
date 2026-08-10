import os
import io
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class QuarantinePhase6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-q", "Quarantine", str(self.data_dir), now, now),
            )

        from backend.app.core import vault_crypto

        vault_crypto.initialize_vault_security(
            "vault-q",
            "phase six passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )

    def tearDown(self) -> None:
        try:
            from backend.app.core import vault_crypto

            vault_crypto.lock_all_vaults()
        except Exception:
            pass
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_symlink_file_is_rejected_before_parser_worker(self) -> None:
        from backend.app.core.quarantine import QuarantineError, validate_candidate_file

        target = Path(self.tmp.name) / "target.txt"
        link = Path(self.tmp.name) / "link.txt"
        target.write_text("secret", encoding="utf-8")
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation is not available in this environment")

        with self.assertRaises(QuarantineError) as raised:
            validate_candidate_file(str(link))
        self.assertIn("symlink", str(raised.exception).lower())

    def test_docx_zip_bomb_is_rejected_by_structural_validator(self) -> None:
        from backend.app.core.quarantine import QuarantineError, validate_candidate_file

        path = Path(self.tmp.name) / "bomb.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "A" * (5 * 1024 * 1024))

        with self.assertRaises(QuarantineError) as raised:
            validate_candidate_file(str(path))
        self.assertIn("expansion ratio", str(raised.exception).lower())

    def test_malformed_worker_json_is_rejected_parent_side(self) -> None:
        from backend.app.core.quarantine import QuarantineError, run_parser_worker

        class FakeJob:
            def close(self): pass

        class FakeProcess:
            def __init__(self, *_args, stdout=None, **_kwargs):
                stdout.write(b"{not-json")

            def wait(self, timeout=None):
                return 0

        with patch("backend.app.core.quarantine.subprocess.Popen", FakeProcess), patch(
            "backend.app.core.quarantine._assign_windows_parser_job", return_value=FakeJob()
        ):
            with self.assertRaises(QuarantineError) as raised:
                run_parser_worker(str(Path(self.tmp.name) / "note.txt"))
        self.assertIn("malformed json", str(raised.exception).lower())

    def test_missing_worker_stdout_is_rejected_cleanly(self) -> None:
        from backend.app.core.quarantine import QuarantineError, run_parser_worker

        class FakeJob:
            def close(self): pass

        class FakeProcess:
            def __init__(self, *_args, **_kwargs):
                pass

            def wait(self, timeout=None):
                return 0

        with patch("backend.app.core.quarantine.subprocess.Popen", FakeProcess), patch(
            "backend.app.core.quarantine._assign_windows_parser_job", return_value=FakeJob()
        ):
            with self.assertRaises(QuarantineError) as raised:
                run_parser_worker(str(Path(self.tmp.name) / "note.txt"))
        self.assertIn("malformed json", str(raised.exception).lower())

    def test_defender_unavailable_is_advisory_not_safety_claim(self) -> None:
        from backend.app.core.quarantine import defender_scan

        with patch("backend.app.core.quarantine.platform.system", return_value="Linux"):
            result = defender_scan(str(Path(self.tmp.name) / "note.txt"))
        self.assertEqual(result["status"], "unavailable")

    def test_defender_retries_transient_failure_then_recovers(self) -> None:
        from backend.app.core.quarantine import defender_scan

        with patch(
            "backend.app.core.quarantine._defender_scan_once",
            side_effect=[
                {"status": "unavailable", "classification": "transient", "detail": "busy"},
                {"status": "passed", "classification": "clean", "detail": "clean"},
            ],
        ) as scan_once, patch("backend.app.core.quarantine.time.sleep") as sleep:
            result = defender_scan("note.txt")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(scan_once.call_count, 2)
        sleep.assert_called_once()

    def test_defender_does_not_retry_permanent_unavailability(self) -> None:
        from backend.app.core.quarantine import defender_scan

        with patch(
            "backend.app.core.quarantine._defender_scan_once",
            return_value={
                "status": "unavailable",
                "classification": "permanent",
                "detail": "not installed",
            },
        ) as scan_once, patch("backend.app.core.quarantine.time.sleep") as sleep:
            result = defender_scan("note.txt")

        self.assertEqual(result["attempts"], 1)
        scan_once.assert_called_once()
        sleep.assert_not_called()

    def test_warned_sandbox_policy_never_uses_in_process_parser(self) -> None:
        from backend.app.core.quarantine import ingest_file_through_quarantine

        path = Path(self.tmp.name) / "sandbox-only.txt"
        path.write_text("sandbox only import", encoding="utf-8")
        parsed = {"title": "sandbox-only.txt", "pages": ["sandbox only import"], "parser": {}}
        with patch.dict(
            os.environ,
            {"CML_SANDBOX_ONLY_ALLOW_DEFENDER_UNAVAILABLE": "1"},
        ), patch(
            "backend.app.core.quarantine.platform.system", return_value="Windows"
        ), patch(
            "backend.app.core.quarantine.defender_scan",
            return_value={"status": "unavailable", "classification": "permanent", "detail": "missing"},
        ), patch(
            "backend.app.core.quarantine.run_parser_worker", return_value=parsed
        ) as sandbox_parser, patch(
            "backend.app.core.quarantine.extract_pages_from_validated_path"
        ) as in_process_parser:
            result = ingest_file_through_quarantine("vault-q", str(path))

        sandbox_parser.assert_called_once_with(str(path.resolve()))
        in_process_parser.assert_not_called()
        self.assertEqual(result["security"]["trust_tier"], "quarantined")
        self.assertIn("sandbox_only_policy", result["security"]["security_labels"])

    def test_failed_windows_defender_scan_blocks_parser_entry(self) -> None:
        from backend.app.core.quarantine import QuarantineError, ingest_file_through_quarantine

        path = Path(self.tmp.name) / "blocked.txt"
        path.write_text("must never reach parser", encoding="utf-8")
        with patch(
            "backend.app.core.quarantine.defender_scan",
            return_value={"status": "failed", "detail": "detected"},
        ), patch("backend.app.core.quarantine.parse_candidate_file") as parser:
            with self.assertRaises(QuarantineError):
                ingest_file_through_quarantine("vault-q", str(path))
        parser.assert_not_called()

    def test_parser_worker_writes_utf8_json_under_cp1252_stdout(self) -> None:
        from backend.app.core import parser_worker

        stdout_bytes = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252")
        with patch(
            "backend.app.core.parser_worker.extract_pages_from_validated_path",
            return_value=("note.txt", ["unicode payload: सुरक्षा"]),
        ), patch.object(parser_worker.sys, "stdout", stdout):
            result = parser_worker.main(["ignored.txt"])

        self.assertEqual(result, 0)
        payload = stdout_bytes.getvalue().decode("utf-8").strip()
        self.assertIn("सुरक्षा", payload)

    def test_from_path_ingestion_records_quarantine_and_trust_metadata(self) -> None:
        from backend.app.api.routes.sources import create_source_from_path
        from backend.app.core.database import connect
        from backend.app.schemas import SourcePathCreate

        path = Path(self.tmp.name) / "note.txt"
        path.write_text("phase six quarantine parser worker evidence", encoding="utf-8")

        source = create_source_from_path(SourcePathCreate(vault_id="vault-q", path=str(path)))
        self.assertEqual(source["trust_tier"], "imported_local")

        with connect() as conn:
            record = conn.execute("SELECT * FROM source_quarantine_records WHERE source_id = ?", (source["id"],)).fetchone()
            stored = conn.execute(
                "SELECT trust_tier, provenance, security_labels, parser_security_json FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
        self.assertIsNotNone(record)
        self.assertEqual(record["validation_status"], "passed")
        self.assertEqual(record["parser_status"], "passed")
        self.assertEqual(record["trust_tier"], "imported_local")
        self.assertEqual(stored["trust_tier"], "imported_local")
        self.assertIn("parser_worker", stored["security_labels"])
        self.assertIn("defender_", stored["parser_security_json"])


if __name__ == "__main__":
    unittest.main()
