import os
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
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

    def test_ingestion_priority_runs_before_other_high_priority_work(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "project-job", job_type="project_discover", priority="high")
            self._insert_job(
                conn,
                "import-job",
                job_type="source_import_batch",
                priority="ingestion",
            )

        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertEqual(job["id"], "import-job")

    def test_critical_work_remains_above_ingestion(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "import-job",
                job_type="source_import_batch",
                priority="ingestion",
            )
            self._insert_job(
                conn,
                "delete-job",
                job_type="delete_source_cleanup",
                priority="critical",
            )

        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertEqual(job["id"], "delete-job")

    def test_dedicated_ingestion_lane_can_claim_while_normal_work_is_running(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "normal-job", job_type="diagnostic_bundle", priority="normal")
            self._insert_job(
                conn,
                "import-job",
                job_type="source_import_batch",
                priority="ingestion",
            )

        normal = _claim_next_job(excluded_job_types={"source_import_batch"})
        ingestion = _claim_next_job(only_job_types={"source_import_batch"})

        self.assertEqual(normal["id"], "normal-job")
        self.assertEqual(ingestion["id"], "import-job")

    def test_running_critical_work_blocks_the_dedicated_ingestion_lane(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "delete-job",
                job_type="delete_source_cleanup",
                status="running",
                priority="critical",
            )
            self._insert_job(
                conn,
                "import-job",
                job_type="source_import_batch",
                priority="ingestion",
            )

        ingestion = _claim_next_job(only_job_types={"source_import_batch"})

        self.assertIsNone(ingestion)

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

    def test_running_job_with_pending_cancellation_recovers_as_cancelled(self) -> None:
        from backend.app.core.background_jobs import recover_interrupted_jobs
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", status="running", restart_policy="requeue")
            conn.execute(
                "UPDATE app_jobs SET cancellation_requested = 1 WHERE id = 'job-a'",
            )

        result = recover_interrupted_jobs()

        self.assertEqual(result["cancelled"], 1)
        with connect() as conn:
            row = conn.execute(
                "SELECT status, completed_at FROM app_jobs WHERE id = 'job-a'",
            ).fetchone()
        self.assertEqual(row["status"], "cancelled")
        self.assertIsNotNone(row["completed_at"])

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

    def test_running_job_cancellation_is_requested_then_acknowledged_by_worker(self) -> None:
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

        self.assertEqual(cancelled["status"], "running")
        self.assertEqual(cancelled["cancellation_requested"], 1)
        self.assertIsNone(cancelled["completed_at"])
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["status_detail"], "Cancellation acknowledged by worker.")

    def test_failed_job_keeps_internal_detail_private_and_exposes_diagnostic_reference(self) -> None:
        from backend.app.core.background_jobs import (
            _claim_next_job,
            _mark_job_failed_or_retry,
            public_job_record,
        )
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", max_attempts=1)

        job = _claim_next_job()
        self.assertIsNotNone(job)
        _mark_job_failed_or_retry(
            job,
            RuntimeError(r"Permission denied: C:\Users\person\private\model.gguf"),
        )

        with connect() as conn:
            stored = dict(conn.execute("SELECT * FROM app_jobs WHERE id = 'job-a'").fetchone())
        public = public_job_record(stored)

        self.assertIn("Users", stored["last_error"])
        self.assertNotIn("Users", public["last_error"])
        self.assertEqual(public["last_error"], "This task needs attention.")
        self.assertEqual(stored["error_code"], "reindex_source_failed")
        self.assertTrue(stored["diagnostic_id"].startswith("jobdiag-"))

    def test_running_cancellation_is_acknowledged_before_handler_writes_commit(self) -> None:
        import json

        from backend.app.core import background_jobs
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, raw_text, extracted_text,
                    created_at, updated_at
                )
                VALUES ('source-1', 'vault-1', 'Original', 'note', 'indexed', 'text', 'text', ?, ?)
                """,
                (now, now),
            )
            self._insert_job(
                conn,
                "job-cancel-running",
                job_type="reindex_source",
                payload=json.dumps({"source_id": "source-1"}),
                cancellable=1,
            )

        claimed = background_jobs._claim_next_job()

        def cancel_before_work(_feature: str) -> None:
            background_jobs.cancel_job("job-cancel-running")

        def attempted_write(conn, _source) -> None:
            conn.execute("UPDATE sources SET title = 'Should roll back' WHERE id = 'source-1'")

        with (
            patch.object(
                background_jobs,
                "require_embeddings_available",
                side_effect=cancel_before_work,
            ),
            patch.object(background_jobs, "reindex_source_chunks", side_effect=attempted_write),
        ):
            background_jobs._run_claimed_job(claimed)

        with connect() as conn:
            job = conn.execute(
                "SELECT status FROM app_jobs WHERE id = 'job-cancel-running'"
            ).fetchone()
            source = conn.execute("SELECT title FROM sources WHERE id = 'source-1'").fetchone()

        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(source["title"], "Original")

    def test_claimed_job_returns_current_attempt_count(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a")

        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertEqual(job["attempts"], 1)

    def test_claim_assigns_lease_and_hard_deadline(self) -> None:
        from backend.app.core.background_jobs import _claim_next_job
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(conn, "job-a", timeout_seconds=30)

        before = datetime.now(UTC)
        job = _claim_next_job()

        self.assertIsNotNone(job)
        self.assertTrue(str(job["claim_token"]).startswith("job-claim-"))
        self.assertIsNotNone(job["heartbeat_at"])
        deadline = datetime.fromisoformat(job["deadline_at"])
        self.assertGreaterEqual(deadline, before + timedelta(seconds=29))
        self.assertLessEqual(deadline, datetime.now(UTC) + timedelta(seconds=31))

    def test_expired_deferred_job_is_requeued_and_old_worker_cannot_finish_it(self) -> None:
        from backend.app.core import background_jobs
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "job-a",
                timeout_seconds=30,
                timeout_action="defer",
                max_attempts=3,
            )

        old_claim = background_jobs._claim_next_job()
        self.assertIsNotNone(old_claim)
        future = (datetime.now(UTC) + timedelta(seconds=31)).isoformat()

        result = background_jobs.reclaim_expired_jobs(now=future)
        background_jobs._run_claimed_job(old_claim)

        with connect() as conn:
            row = conn.execute(
                "SELECT status, claim_token, started_at, completed_at FROM app_jobs WHERE id = 'job-a'"
            ).fetchone()
        self.assertEqual(result["queued"], 1)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["claim_token"], "")
        self.assertIsNone(row["started_at"])
        self.assertIsNone(row["completed_at"])

    def test_expired_job_obeys_terminal_timeout_policies(self) -> None:
        from backend.app.core.background_jobs import reclaim_expired_jobs
        from backend.app.core.database import connect

        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with connect() as conn:
            self._insert_job(
                conn,
                "failed-job",
                status="running",
                attempts=1,
                timeout_action="fail",
                claim_token="failed-claim",
                heartbeat_at=expired,
                deadline_at=expired,
            )
            self._insert_job(
                conn,
                "review-job",
                status="running",
                attempts=1,
                timeout_action="escalate",
                claim_token="review-claim",
                heartbeat_at=expired,
                deadline_at=expired,
            )
            self._insert_job(
                conn,
                "cancelled-job",
                status="running",
                attempts=1,
                timeout_action="defer",
                claim_token="cancelled-claim",
                heartbeat_at=expired,
                deadline_at=expired,
            )
            conn.execute(
                "UPDATE app_jobs SET cancellation_requested = 1 WHERE id = 'cancelled-job'"
            )

        result = reclaim_expired_jobs()

        with connect() as conn:
            rows = {
                row["id"]: dict(row)
                for row in conn.execute(
                    "SELECT id, status, completed_at, claim_token FROM app_jobs"
                ).fetchall()
            }
        self.assertEqual(result, {"queued": 0, "failed": 1, "manual_review": 1, "cancelled": 1})
        self.assertEqual(rows["failed-job"]["status"], "failed")
        self.assertEqual(rows["review-job"]["status"], "manual_review")
        self.assertEqual(rows["cancelled-job"]["status"], "cancelled")
        for row in rows.values():
            self.assertEqual(row["claim_token"], "")
            self.assertIsNotNone(row["completed_at"])

    def test_scoped_delete_cancels_pending_and_signals_running_worker(self) -> None:
        from backend.app.core import background_jobs
        from backend.app.core.database import connect

        with connect() as conn:
            self._insert_job(
                conn,
                "queued-job",
                write_scope="source",
                scope_id="source-1",
            )
            self._insert_job(
                conn,
                "running-job",
                status="running",
                attempts=1,
                write_scope="source",
                scope_id="source-1",
                claim_token="active-claim",
            )
            result = background_jobs.cancel_jobs_for_scope(
                conn,
                write_scope="source",
                scope_id="source-1",
                detail="Source was deleted.",
            )

        background_jobs._mark_job_failed_or_retry(
            {"id": "running-job", "job_type": "reindex_source", "claim_token": "active-claim"},
            "late worker failure",
        )

        with connect() as conn:
            rows = {
                row["id"]: dict(row)
                for row in conn.execute(
                    "SELECT id, status, cancellation_requested, completed_at FROM app_jobs"
                ).fetchall()
            }
        self.assertEqual(result, {"cancelled": 1, "cancellation_requested": 1})
        self.assertEqual(rows["queued-job"]["status"], "cancelled")
        self.assertIsNotNone(rows["queued-job"]["completed_at"])
        self.assertEqual(rows["running-job"]["status"], "cancelled")
        self.assertEqual(rows["running-job"]["cancellation_requested"], 1)

    def test_paused_job_retains_dedupe_ownership(self) -> None:
        from backend.app.core.background_jobs import enqueue_job
        from backend.app.core.database import connect

        with connect() as conn:
            first = enqueue_job(
                conn,
                job_type="source_import_batch",
                payload={"vault_id": "vault-1", "paths": ["first.txt"]},
                dedupe_key="import:paused-owner",
            )
            conn.execute("UPDATE app_jobs SET status = 'paused' WHERE id = ?", (first["id"],))
            duplicate = enqueue_job(
                conn,
                job_type="source_import_batch",
                payload={"vault_id": "vault-1", "paths": ["second.txt"]},
                dedupe_key="import:paused-owner",
            )

        self.assertEqual(duplicate["id"], first["id"])
        with connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM app_jobs WHERE dedupe_key = 'import:paused-owner'"
            ).fetchone()["count"]
        self.assertEqual(count, 1)

    def test_turbovec_evaluation_is_queued_only_after_threshold_without_epoch_evidence(self) -> None:
        from backend.app.core import background_jobs
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        status = {
            "eligible_chunk_count": 10000,
            "derived_state_epoch": 3,
            "benchmark": None,
        }
        with (
            patch(
                "backend.app.core.turbovec_runtime.turbovec_runtime_available",
                return_value=True,
            ),
            patch(
                "backend.app.core.turbovec_runtime.turbovec_phase_c_status",
                return_value=status,
            ),
        ):
            background_jobs._enqueue_due_turbovec_evaluations()
            background_jobs._enqueue_due_turbovec_evaluations()

        with connect() as conn:
            jobs = conn.execute(
                "SELECT job_type, dedupe_key FROM app_jobs WHERE job_type = 'turbovec_evaluate'"
            ).fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["dedupe_key"], "turbovec-evaluate:vault-1:3")

        status["benchmark"] = {"approved": False}
        with (
            patch(
                "backend.app.core.turbovec_runtime.turbovec_runtime_available",
                return_value=True,
            ),
            patch(
                "backend.app.core.turbovec_runtime.turbovec_phase_c_status",
                return_value=status,
            ),
        ):
            background_jobs._enqueue_due_turbovec_evaluations()
        with connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM app_jobs WHERE job_type = 'turbovec_evaluate'"
            ).fetchone()["count"]
        self.assertEqual(count, 1)

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
            "claim_token": "",
            "heartbeat_at": None,
            "deadline_at": None,
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
                claim_token, heartbeat_at, deadline_at, created_at, updated_at
            )
            VALUES (
                :id, :job_type, :status, :payload, :dedupe_key, :priority,
                :idempotency_class, :restart_policy, :dependency_failure_policy,
                :write_scope, :scope_id, :concurrency_group, :resource_cost,
                :can_run_during_synthesis, :user_visible, :user_initiated,
                :cancellable, :preemptable, :timeout_seconds, :soft_timeout_seconds,
                :timeout_action, :depends_on_job_id, :attempts, :max_attempts,
                :last_error, :status_detail, :started_at, :completed_at,
                :claim_token, :heartbeat_at, :deadline_at, :created_at, :updated_at
            )
            """,
            job,
        )


if __name__ == "__main__":
    unittest.main()
