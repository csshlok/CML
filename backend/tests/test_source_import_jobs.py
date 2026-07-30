import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


class SourceImportJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.migrations import run_migrations

        get_settings.cache_clear()
        init_db()
        run_migrations()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-import", "Import", self.tmp.name, now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        self.tmp.cleanup()

    def paths(self, count: int) -> list[str]:
        paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f"document-{index}.txt"
            path.write_text(f"Document {index}", encoding="utf-8")
            paths.append(str(path))
        return paths

    def test_batch_job_reports_created_updated_and_failed_files(self) -> None:
        from backend.app.api.routes.sources import create_source_import_job
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.schemas import SourceImportJobRequest

        paths = self.paths(3)

        def fake_import(payload):
            if payload.path.endswith("document-1.txt"):
                return {"import_outcome": "updated"}
            if payload.path.endswith("document-2.txt"):
                raise HTTPException(status_code=400, detail="Unreadable document")
            return {"import_outcome": "created"}

        job = create_source_import_job(
            SourceImportJobRequest(vault_id="vault-import", paths=paths)
        )
        with patch(
            "backend.app.api.routes.sources.create_source_from_path",
            side_effect=fake_import,
        ):
            self.assertEqual(run_due_jobs_once(limit=1), 1)

        with connect() as conn:
            stored = conn.execute(
                "SELECT status, result_json, status_detail FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
        progress = json.loads(stored["result_json"])
        self.assertEqual(stored["status"], "partial_success")
        self.assertEqual(progress["completed_files"], 3)
        self.assertEqual(progress["imported_files"], 1)
        self.assertEqual(progress["updated_files"], 1)
        self.assertEqual(progress["failed_files"], 1)
        self.assertEqual(progress["failures"][0]["file_name"], "document-2.txt")
        self.assertEqual(progress["failures"][0]["path_index"], 2)
        self.assertEqual(progress["failed_indices"], [2])
        self.assertNotIn(self.tmp.name, json.dumps(progress["failures"]))
        self.assertIn("1 can be retried", stored["status_detail"])

    def test_partial_import_retries_only_failed_files_in_the_same_job(self) -> None:
        from backend.app.api.routes.sources import (
            create_source_import_job,
            retry_source_import_failures,
        )
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.schemas import SourceImportJobRequest

        paths = self.paths(3)
        attempted: list[str] = []

        def first_import(payload):
            attempted.append(Path(payload.path).name)
            if payload.path.endswith("document-1.txt"):
                raise HTTPException(status_code=400, detail="Unreadable document")
            return {"import_outcome": "created"}

        job = create_source_import_job(
            SourceImportJobRequest(vault_id="vault-import", paths=paths)
        )
        with patch(
            "backend.app.api.routes.sources.create_source_from_path",
            side_effect=first_import,
        ):
            self.assertEqual(run_due_jobs_once(limit=1), 1)
        retried = retry_source_import_failures(job["id"])
        self.assertEqual(retried["id"], job["id"])
        self.assertEqual(retried["status"], "queued")

        attempted.clear()
        with patch(
            "backend.app.api.routes.sources.create_source_from_path",
            side_effect=lambda payload: attempted.append(Path(payload.path).name)
            or {"import_outcome": "created"},
        ):
            self.assertEqual(run_due_jobs_once(limit=1), 1)

        with connect() as conn:
            stored = conn.execute(
                "SELECT status, result_json FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()["count"]
        progress = json.loads(stored["result_json"])
        self.assertEqual(attempted, ["document-1.txt"])
        self.assertEqual(count, 1)
        self.assertEqual(stored["status"], "succeeded")
        self.assertEqual(progress["completed_files"], 3)
        self.assertEqual(progress["failed_files"], 0)
        self.assertEqual(progress["failures"], [])

    def test_import_can_pause_resume_and_stop_without_losing_progress(self) -> None:
        from backend.app.api.routes.sources import (
            create_source_import_job,
            get_active_source_import_job,
            pause_source_import,
            resume_source_import,
            stop_source_import,
        )
        from backend.app.schemas import SourceImportJobRequest

        job = create_source_import_job(
            SourceImportJobRequest(vault_id="vault-import", paths=self.paths(2))
        )
        paused = pause_source_import(job["id"])
        active = get_active_source_import_job("vault-import")
        resumed = resume_source_import(job["id"])
        stopped = stop_source_import(job["id"])

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(active["id"], job["id"])
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(stopped["status"], "cancelled")
        self.assertEqual(json.loads(stopped["result_json"])["completed_files"], 0)

    def test_second_active_batch_is_rejected_and_duplicate_paths_are_counted_once(self) -> None:
        from backend.app.api.routes.sources import create_source_import_job
        from backend.app.schemas import SourceImportJobRequest

        path = self.paths(1)[0]
        first = create_source_import_job(
            SourceImportJobRequest(vault_id="vault-import", paths=[path, path])
        )
        self.assertEqual(json.loads(first["result_json"])["total_files"], 1)

        with self.assertRaises(HTTPException) as raised:
            create_source_import_job(
                SourceImportJobRequest(vault_id="vault-import", paths=[path])
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_running_pause_finishes_inflight_files_then_resume_continues_remaining(self) -> None:
        from backend.app.api.routes.sources import (
            create_source_import_job,
            pause_source_import,
            resume_source_import,
        )
        from backend.app.core.adaptive_scheduler import source_import_worker_count
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.schemas import SourceImportJobRequest

        paths = self.paths(6)
        job = create_source_import_job(
            SourceImportJobRequest(vault_id="vault-import", paths=paths)
        )
        in_flight_count = min(len(paths), source_import_worker_count(len(paths)))
        started = threading.Barrier(in_flight_count + 1)
        release = threading.Event()

        def blocked_import(_payload):
            started.wait(timeout=5)
            release.wait(timeout=5)
            return {"import_outcome": "created"}

        with patch(
            "backend.app.api.routes.sources.create_source_from_path",
            side_effect=blocked_import,
        ):
            runner = threading.Thread(target=run_due_jobs_once, kwargs={"limit": 1})
            runner.start()
            try:
                started.wait(timeout=5)
                paused = pause_source_import(job["id"])
            finally:
                release.set()
                runner.join(timeout=10)

        self.assertFalse(runner.is_alive())
        self.assertEqual(paused["status"], "paused")
        with connect() as conn:
            stored = conn.execute(
                "SELECT status, result_json FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
        paused_progress = json.loads(stored["result_json"])
        self.assertEqual(stored["status"], "paused")
        self.assertEqual(paused_progress["completed_files"], in_flight_count)

        resume_source_import(job["id"])
        with patch(
            "backend.app.api.routes.sources.create_source_from_path",
            return_value={"import_outcome": "created"},
        ):
            self.assertEqual(run_due_jobs_once(limit=1), 1)
        with connect() as conn:
            finished = conn.execute(
                "SELECT status, result_json FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
        finished_progress = json.loads(finished["result_json"])
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished_progress["completed_files"], 6)
        self.assertEqual(finished_progress["imported_files"], 6)

    def test_large_folder_import_is_grouped_and_browsable(self) -> None:
        from backend.app.api.routes.sources import (
            count_sources,
            create_source_import_job,
            list_source_folders,
            list_sources_page,
        )
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.schemas import SourceImportJobRequest

        folder = Path(self.tmp.name) / "large-folder"
        folder.mkdir()
        paths = []
        for index in range(20):
            path = folder / f"item-{index:02d}.txt"
            path.write_text(f"Folder item {index}", encoding="utf-8")
            paths.append(str(path))

        create_source_import_job(
            SourceImportJobRequest(
                vault_id="vault-import",
                paths=paths,
                folder_roots=[str(folder)],
            )
        )
        self.assertEqual(run_due_jobs_once(limit=1), 1)

        second_folder = Path(self.tmp.name) / "second-large-folder"
        second_folder.mkdir()
        second_paths = []
        for index in range(20):
            path = second_folder / f"item-{index:02d}.txt"
            path.write_text(f"Second folder item {index}", encoding="utf-8")
            second_paths.append(str(path))
        second_job = create_source_import_job(
            SourceImportJobRequest(
                vault_id="vault-import",
                paths=second_paths,
                folder_roots=[str(second_folder)],
            )
        )
        for _ in range(10):
            run_due_jobs_once(limit=5)
            with connect() as conn:
                row = conn.execute(
                    "SELECT status FROM app_jobs WHERE id = ?",
                    (second_job["id"],),
                ).fetchone()
            if row and row["status"] in {"succeeded", "partial_success", "failed"}:
                break
        self.assertEqual(row["status"], "succeeded")

        folder_result = list_source_folders("vault-import")
        folders = folder_result["items"]
        first_page = list_source_folders("vault-import", limit=1)
        second_page = list_source_folders("vault-import", limit=1, offset=1)
        root_page = list_sources_page(
            vault_id="vault-import",
            exclude_grouped_projects=True,
            limit=100,
        )
        folder_page = list_sources_page(
            vault_id="vault-import",
            import_root_path=str(folder.resolve()),
            limit=100,
        )

        self.assertEqual(
            {(item["name"], item["source_count"]) for item in folders},
            {("large-folder", 20), ("second-large-folder", 20)},
        )
        self.assertEqual(folder_result["total"], 2)
        self.assertEqual(len(first_page["items"]), 1)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(len(second_page["items"]), 1)
        self.assertFalse(second_page["has_more"])
        self.assertEqual(root_page["items"], [])
        self.assertEqual(count_sources(vault_id="vault-import", exclude_grouped_projects=True)["total"], 0)
        self.assertEqual(len(folder_page["items"]), 20)

    def test_source_content_persists_and_reports_paused_when_embeddings_are_unavailable(self) -> None:
        from backend.app.api.routes.sources import create_source_from_text, get_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.schemas import SourceTextCreate

        source = create_source_from_text(
            SourceTextCreate(
                vault_id="vault-import",
                title="Offline source",
                text="Extracted content remains durable before search publication.",
            )
        )
        self.assertEqual(source["ingestion_stage"], "imported")

        with patch(
            "backend.app.core.background_jobs.embedding_status",
            return_value={"available": False},
        ):
            run_due_jobs_once(limit=1)

        paused = get_source(source["id"])
        self.assertEqual(paused["ingestion_stage"], "paused")
        self.assertIn("Extracted content", paused["extracted_text"])

    def test_newer_ingestion_generation_supersedes_an_older_reindex_job(self) -> None:
        from backend.app.api.routes.sources import (
            create_source_from_text,
            get_source,
            reindex_source,
        )
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.schemas import SourceTextCreate

        source = create_source_from_text(
            SourceTextCreate(
                vault_id="vault-import",
                title="Versioned source",
                text="A source generation must publish atomically.",
            )
        )
        initial_generation = source["ingestion_generation"]
        reindex_source(source["id"])
        restarted = get_source(source["id"])
        self.assertEqual(restarted["ingestion_generation"], initial_generation + 1)

        # The older queued job is claimed first and must not publish over the
        # newer source generation.
        self.assertEqual(run_due_jobs_once(limit=1), 1)
        after_stale_job = get_source(source["id"])
        self.assertEqual(
            after_stale_job["ingestion_generation"],
            restarted["ingestion_generation"],
        )
        self.assertEqual(after_stale_job["ingestion_stage"], "imported")

        self.assertEqual(run_due_jobs_once(limit=1), 1)
        searchable = get_source(source["id"])
        self.assertEqual(searchable["ingestion_stage"], "searchable")


if __name__ == "__main__":
    unittest.main()
