import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class BackgroundJobSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        self.tmp.cleanup()

    def test_high_priority_runs_before_low_priority(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "low-job", priority="low")
            self._insert_job(conn, "high-job", priority="high")

        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertEqual(job["id"], "high-job")

    def test_dependency_failure_policy_cancel_cancels_dependent_job(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", status="failed")
            self._insert_job(
                conn,
                "job-b",
                depends_on_job_id="job-a",
                dependency_failure_policy="cancel",
            )

        job = _claim_next_job()

        self.assertIsNone(job)
        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE id = 'job-b'").fetchone()
        self.assertEqual(row["status"], "cancelled")

    def test_dependent_job_is_blocked_until_dependency_succeeds(self) -> None:
        from backend.app.core.background_jobs import _refresh_blocked_dependencies, enqueue_job
        from backend.app.core.database import connect

        with connect() as conn:
            parent = enqueue_job(conn, job_type="reindex_source", payload={"source_id": "source-1"})
            child = enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": "source-2"},
                depends_on_job_id=parent["id"],
            )

        self.assertEqual(child["status"], "blocked_by_dependency")
        with connect() as conn:
            conn.execute("UPDATE app_jobs SET status = 'succeeded' WHERE id = ?", (parent["id"],))

        _refresh_blocked_dependencies()

        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (child["id"],)).fetchone()
        self.assertEqual(row["status"], "queued")

    def test_missing_blocked_dependency_cancels_dependent_job(self) -> None:
        from backend.app.core.background_jobs import _refresh_blocked_dependencies
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "job-b",
                status="blocked_by_dependency",
                depends_on_job_id="missing-job",
                dependency_failure_policy="cancel",
            )

        _refresh_blocked_dependencies()

        with connect() as conn:
            row = conn.execute("SELECT status, status_detail FROM app_jobs WHERE id = 'job-b'").fetchone()
        self.assertEqual(row["status"], "cancelled")
        self.assertIn("missing", row["status_detail"])

    def test_running_requeue_job_recovers_to_queued_on_startup(self) -> None:
        from backend.app.core.background_jobs import recover_interrupted_jobs
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", status="running", restart_policy="requeue")

        result = recover_interrupted_jobs()

        self.assertEqual(result["queued"], 1)
        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE id = 'job-a'").fetchone()
        self.assertEqual(row["status"], "queued")

    def test_unknown_job_type_moves_to_manual_review(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", job_type="unknown_job")

        processed = run_due_jobs_once(limit=1)

        self.assertEqual(processed, 1)
        with connect() as conn:
            row = conn.execute("SELECT status FROM app_jobs WHERE id = 'job-a'").fetchone()
        self.assertEqual(row["status"], "manual_review")

    def test_same_write_scope_waits_for_running_job(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "running-job",
                status="running",
                write_scope="source",
                scope_id="source-1",
            )
            self._insert_job(
                conn,
                "queued-job",
                write_scope="source",
                scope_id="source-1",
            )

        job = _claim_next_job()

        self.assertIsNone(job)

    def test_concurrent_run_once_calls_do_not_execute_same_job_twice(self) -> None:
        import backend.app.core.background_jobs as background_jobs
        import backend.app.api.routes.jobs as job_routes
        from backend.app.core.database import connect

        calls: list[str] = []
        started = threading.Event()

        def fake_run_claimed_job(job: dict) -> None:
            calls.append(job["id"])
            started.set()
            time.sleep(0.1)

        with connect() as conn:
            self._insert_job(conn, "job-a")

        with patch.object(background_jobs, "_run_claimed_job", side_effect=fake_run_claimed_job):
            first = threading.Thread(target=background_jobs.run_due_jobs_once, kwargs={"limit": 1})
            first.start()
            self.assertTrue(started.wait(timeout=2))
            job_routes.run_jobs_once()
            first.join(timeout=2)

        self.assertEqual(calls, ["job-a"])

    def test_cancelled_running_job_is_not_requeued_when_worker_later_fails(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job, _mark_job_failed_or_retry, cancel_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", cancellable=1)

        job = _claim_next_job()
        self.assertIsNotNone(job)

        cancelled = cancel_job("job-a")
        _mark_job_failed_or_retry(job, "worker noticed cancellation after an I/O failure")

        with connect() as conn:
            row = conn.execute("SELECT status, status_detail FROM app_jobs WHERE id = 'job-a'").fetchone()

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["status_detail"], "Cancelled by user.")

    def test_claimed_job_returns_current_attempt_count(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a")

        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertEqual(job["attempts"], 1)

    def _insert_job(self, conn, job_id: str, **overrides) -> None:
        from backend.app.core.database import utc_now

        now = utc_now()
        job = {
            "id": job_id,
            "job_type": "reindex_source",
            "status": "queued",
            "payload": "{}",
            "dedupe_key": None,
            "priority": "normal",
            "idempotency_class": "idempotent",
            "restart_policy": "requeue",
            "dependency_failure_policy": "cancel",
            "write_scope": "none",
            "scope_id": None,
            "concurrency_group": None,
            "resource_cost": "light",
            "can_run_during_synthesis": 1,
            "user_visible": 0,
            "user_initiated": 0,
            "cancellable": 0,
            "preemptable": 0,
            "timeout_seconds": None,
            "soft_timeout_seconds": None,
            "timeout_action": "fail",
            "depends_on_job_id": None,
            "attempts": 0,
            "max_attempts": 3,
            "last_error": "",
            "status_detail": "",
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        job.update(overrides)
        conn.execute(
            """
            INSERT INTO app_jobs (
                id, job_type, status, payload, dedupe_key, priority, idempotency_class,
                restart_policy, dependency_failure_policy, write_scope, scope_id,
                concurrency_group, resource_cost, can_run_during_synthesis, user_visible,
                user_initiated, cancellable, preemptable, timeout_seconds,
                soft_timeout_seconds, timeout_action, depends_on_job_id, attempts,
                max_attempts, last_error, status_detail, started_at, completed_at,
                created_at, updated_at
            )
            VALUES (
                :id, :job_type, :status, :payload, :dedupe_key, :priority,
                :idempotency_class, :restart_policy, :dependency_failure_policy,
                :write_scope, :scope_id, :concurrency_group, :resource_cost,
                :can_run_during_synthesis, :user_visible, :user_initiated,
                :cancellable, :preemptable, :timeout_seconds, :soft_timeout_seconds,
                :timeout_action, :depends_on_job_id, :attempts, :max_attempts,
                :last_error, :status_detail, :started_at, :completed_at,
                :created_at, :updated_at
            )
            """,
            job,
        )


if __name__ == "__main__":
    unittest.main()
