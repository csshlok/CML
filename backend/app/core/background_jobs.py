import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import content_hash, reindex_source_chunks, require_embeddings_available
from backend.app.core.encrypted_storage import (
    delete_source_encrypted_content,
    delete_source_derived_encrypted_content,
    plaintext_column_for_text,
    update_source_content_fields,
)
from backend.app.core.cluster_lifecycle import mark_cluster_needs_update, refresh_cluster_profile
from backend.app.core.vector_maintenance import vector_repair_plan
from backend.app.core.context_memory import rebuild_chat_session_memory, rebuild_source_memory
from backend.app.core.analysis_packets import build_analysis_packets
from backend.app.core.unlock_state import should_pause_vault_job


JOB_POLL_SECONDS = 1.0
JOB_STATUS_RUNNING_LIMIT = 50
ACTIVE_STATUSES = ("queued", "running", "blocked_by_dependency")
TERMINAL_DEPENDENCY_STATUSES = ("failed", "cancelled", "manual_review")
PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
    "on_demand": 4,
}
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


@dataclass(frozen=True)
class JobPolicy:
    priority: str
    idempotency_class: str
    restart_policy: str
    dependency_failure_policy: str
    write_scope: str
    concurrency_group: str | None
    resource_cost: str
    can_run_during_synthesis: bool
    user_visible: bool
    user_initiated: bool
    cancellable: bool
    preemptable: bool
    timeout_seconds: int | None
    soft_timeout_seconds: int | None
    timeout_action: str


JOB_REGISTRY: dict[str, JobPolicy] = {
    "project_discover": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="project",
        concurrency_group="project_index",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=3600,
        soft_timeout_seconds=600,
        timeout_action="defer",
    ),
    "project_structure_index": JobPolicy(
        priority="high", idempotency_class="idempotent", restart_policy="requeue",
        dependency_failure_policy="cancel", write_scope="project", concurrency_group="project_index",
        resource_cost="heavy", can_run_during_synthesis=False, user_visible=True,
        user_initiated=True, cancellable=True, preemptable=False, timeout_seconds=3600,
        soft_timeout_seconds=600, timeout_action="defer",
    ),
    "project_retrieval_stage": JobPolicy(
        priority="high", idempotency_class="idempotent", restart_policy="requeue",
        dependency_failure_policy="cancel", write_scope="project", concurrency_group="project_index",
        resource_cost="heavy", can_run_during_synthesis=False, user_visible=True,
        user_initiated=True, cancellable=True, preemptable=False, timeout_seconds=3600,
        soft_timeout_seconds=600, timeout_action="defer",
    ),
    "project_snapshot_activate": JobPolicy(
        priority="high", idempotency_class="reconcile_required", restart_policy="reconcile_then_retry",
        dependency_failure_policy="manual_review", write_scope="project", concurrency_group="project_index",
        resource_cost="light", can_run_during_synthesis=False, user_visible=True,
        user_initiated=True, cancellable=False, preemptable=False, timeout_seconds=120,
        soft_timeout_seconds=None, timeout_action="escalate",
    ),
    "project_candidate_cleanup": JobPolicy(
        priority="normal", idempotency_class="idempotent", restart_policy="requeue",
        dependency_failure_policy="cancel", write_scope="project", concurrency_group="project_index",
        resource_cost="light", can_run_during_synthesis=True, user_visible=False,
        user_initiated=False, cancellable=False, preemptable=False, timeout_seconds=300,
        soft_timeout_seconds=None, timeout_action="defer",
    ),
    "reindex_source": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="source",
        concurrency_group="vector_writer",
        resource_cost="medium",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=False,
        timeout_seconds=600,
        soft_timeout_seconds=None,
        timeout_action="defer",
    ),
    "chat_transcript_memory": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="chat",
        concurrency_group="vector_writer",
        resource_cost="medium",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=False,
        cancellable=False,
        preemptable=False,
        timeout_seconds=300,
        soft_timeout_seconds=None,
        timeout_action="defer",
    ),
    "refresh_cluster_profile": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="cluster",
        concurrency_group="cluster_profile",
        resource_cost="light",
        can_run_during_synthesis=True,
        user_visible=False,
        user_initiated=False,
        cancellable=False,
        preemptable=False,
        timeout_seconds=180,
        soft_timeout_seconds=None,
        timeout_action="defer",
    ),
    "ocr_source": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="source",
        concurrency_group="ocr_cpu",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=300,
        timeout_action="defer",
    ),
    "expanded_analysis": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="chat",
        concurrency_group="analysis",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=900,
        soft_timeout_seconds=120,
        timeout_action="defer",
    ),
    "complete_analysis": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="chat",
        concurrency_group="analysis",
        resource_cost="heavy",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=300,
        timeout_action="defer",
    ),
    "delete_source_cleanup": JobPolicy(
        priority="critical",
        idempotency_class="reconcile_required",
        restart_policy="reconcile_then_retry",
        dependency_failure_policy="manual_review",
        write_scope="source",
        concurrency_group="delete_cleanup",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=False,
        preemptable=False,
        timeout_seconds=300,
        soft_timeout_seconds=None,
        timeout_action="escalate",
    ),
    "vector_reconcile_incremental": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vector_index",
        concurrency_group="vector_writer",
        resource_cost="medium",
        can_run_during_synthesis=False,
        user_visible=False,
        user_initiated=False,
        cancellable=False,
        preemptable=False,
        timeout_seconds=900,
        soft_timeout_seconds=None,
        timeout_action="defer",
    ),
    "integration_refresh": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vault",
        concurrency_group="integration_import",
        resource_cost="medium",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=300,
        timeout_action="defer",
    ),
}


UNKNOWN_JOB_POLICY = JobPolicy(
    priority="normal",
    idempotency_class="non_idempotent",
    restart_policy="manual_review",
    dependency_failure_policy="manual_review",
    write_scope="none",
    concurrency_group=None,
    resource_cost="light",
    can_run_during_synthesis=True,
    user_visible=True,
    user_initiated=False,
    cancellable=False,
    preemptable=False,
    timeout_seconds=None,
    soft_timeout_seconds=None,
    timeout_action="escalate",
)


def enqueue_job(
    conn,
    *,
    job_type: str,
    payload: dict,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
    depends_on_job_id: str | None = None,
    scope_id: str | None = None,
    user_initiated: bool | None = None,
) -> dict:
    now = utc_now()
    if dedupe_key:
        existing = conn.execute(
            """
            SELECT * FROM app_jobs
            WHERE dedupe_key = ? AND status IN ('queued', 'running', 'blocked_by_dependency')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (dedupe_key,),
        ).fetchone()
        if existing is not None:
            return dict_from_row(existing)

    policy = _job_policy(job_type)
    policy_values = _policy_row_values(policy)
    status = "queued"
    if depends_on_job_id:
        dependency = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (depends_on_job_id,)).fetchone()
        if dependency is None or dependency["status"] != "succeeded":
            status = "blocked_by_dependency"
    job = {
        "id": f"job-{uuid4()}",
        "job_type": job_type,
        "status": status,
        "payload": json.dumps(payload, separators=(",", ":")),
        "dedupe_key": dedupe_key,
        **policy_values,
        "scope_id": scope_id or _default_scope_id(policy.write_scope, payload),
        "user_initiated": int(policy.user_initiated if user_initiated is None else user_initiated),
        "depends_on_job_id": depends_on_job_id,
        "attempts": 0,
        "max_attempts": max_attempts,
        "last_error": "",
        "status_detail": "",
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO app_jobs (
            id, job_type, status, payload, dedupe_key, priority, idempotency_class,
            restart_policy, dependency_failure_policy, write_scope, scope_id, concurrency_group,
            resource_cost, can_run_during_synthesis, user_visible, user_initiated,
            cancellable, preemptable, timeout_seconds, soft_timeout_seconds, timeout_action,
            depends_on_job_id, attempts, max_attempts, last_error, status_detail, started_at,
            completed_at, created_at, updated_at
        )
        VALUES (
            :id, :job_type, :status, :payload, :dedupe_key, :priority, :idempotency_class,
            :restart_policy, :dependency_failure_policy, :write_scope, :scope_id,
            :concurrency_group, :resource_cost, :can_run_during_synthesis, :user_visible,
            :user_initiated, :cancellable, :preemptable, :timeout_seconds,
            :soft_timeout_seconds, :timeout_action, :depends_on_job_id, :attempts,
            :max_attempts, :last_error, :status_detail, :started_at, :completed_at,
            :created_at, :updated_at
        )
        """,
        job,
    )
    return job


def recover_interrupted_jobs() -> dict[str, int]:
    now = utc_now()
    counts = {"queued": 0, "manual_review": 0}
    with connect() as conn:
        rows = conn.execute("SELECT * FROM app_jobs WHERE status = 'running'").fetchall()
        for row in rows:
            job = dict_from_row(row)
            restart_policy = job.get("restart_policy") or _job_policy(job["job_type"]).restart_policy
            if restart_policy == "reconcile_then_retry" and job["job_type"] == "project_snapshot_activate":
                payload = _decode_payload(job.get("payload") or "{}")
                project = conn.execute(
                    "SELECT active_retrieval_snapshot_id, candidate_snapshot_id FROM projects WHERE id = ?",
                    (str(payload.get("project_id") or ""),),
                ).fetchone()
                activated = (
                    project is not None
                    and project["active_retrieval_snapshot_id"] == payload.get("candidate_snapshot_id")
                    and project["candidate_snapshot_id"] is None
                )
                if activated:
                    conn.execute(
                        "UPDATE app_jobs SET status = 'succeeded', status_detail = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                        ("Activation commit verified after backend restart.", now, now, job["id"]),
                    )
                    continue
                conn.execute(
                    "UPDATE app_jobs SET status = 'queued', status_detail = ?, started_at = NULL, updated_at = ? WHERE id = ?",
                    ("Activation was not committed; queued for an idempotent retry.", now, job["id"]),
                )
                counts["queued"] += 1
            elif restart_policy in {"requeue", "reconcile_then_retry"}:
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET status = 'queued', status_detail = ?, started_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    ("Requeued after backend restart.", now, job["id"]),
                )
                counts["queued"] += 1
            else:
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET status = 'manual_review', status_detail = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("Interrupted job requires reconciliation before retry.", now, job["id"]),
                )
                counts["manual_review"] += 1
    return counts


def start_background_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        recover_interrupted_jobs()
        thread = threading.Thread(target=_worker_loop, name="cml-background-jobs", daemon=True)
        thread.start()
        _WORKER_STARTED = True


def enqueue_startup_reconciliation_jobs() -> None:
    with connect() as conn:
        enqueue_job(
            conn,
            job_type="vector_reconcile_incremental",
            payload={},
            dedupe_key="vector-reconcile:startup",
        )


def run_due_jobs_once(limit: int = 5) -> int:
    _refresh_blocked_dependencies()
    _enqueue_due_integration_refresh_jobs()
    processed = 0
    for _ in range(limit):
        job = _claim_next_job()
        if job is None:
            _refresh_blocked_dependencies()
            job = _claim_next_job()
            if job is None:
                break
        _run_claimed_job(job)
        processed += 1
        _refresh_blocked_dependencies()
    return processed


def job_queue_status() -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM app_jobs
            GROUP BY status
            """
        ).fetchall()
        latest = conn.execute(
            """
            SELECT * FROM app_jobs
            ORDER BY updated_at DESC
            LIMIT 10
            """
        ).fetchall()
        running = conn.execute(
            """
            SELECT * FROM app_jobs
            WHERE status = 'running'
            ORDER BY started_at ASC
            LIMIT ?
            """,
            (JOB_STATUS_RUNNING_LIMIT,),
        ).fetchall()
    counts = {row["status"]: row["count"] for row in rows}
    return {
        "queued": counts.get("queued", 0),
        "blocked_by_dependency": counts.get("blocked_by_dependency", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
        "manual_review": counts.get("manual_review", 0),
        "running_jobs": [_with_runtime_estimate(dict_from_row(row)) for row in running],
        "latest": [dict_from_row(row) for row in latest],
    }


def cancel_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if int(job.get("cancellable") or 0) != 1:
            raise ValueError("Job is not cancellable")
        if job["status"] not in {"queued", "blocked_by_dependency", "running"}:
            raise ValueError("Only queued, blocked, or running jobs can be cancelled")
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'cancelled', status_detail = 'Cancelled by user.', completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict_from_row(updated)


def _worker_loop() -> None:
    while True:
        try:
            run_due_jobs_once(limit=3)
        except Exception:
            pass
        time.sleep(JOB_POLL_SECONDS)


def _claim_next_job() -> dict | None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM app_jobs
            WHERE status = 'queued'
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    WHEN 'on_demand' THEN 4
                    ELSE 5
                END,
                created_at ASC
            LIMIT 25
            """
        ).fetchall()
        for row in rows:
            job = dict_from_row(row)
            dependency_ready = _resolve_dependency(conn, job)
            if not dependency_ready:
                continue
            if should_pause_vault_job(job.get("write_scope")):
                continue
            if _synthesis_conflict(conn, job):
                continue
            if _has_scope_conflict(conn, job):
                continue
            now = utc_now()
            claimed = conn.execute(
                """
                UPDATE app_jobs
                SET status = 'running', attempts = attempts + 1, started_at = ?,
                    status_detail = '', updated_at = ?
                WHERE id = ? AND status = 'queued'
                RETURNING *
                """,
                (now, now, job["id"]),
            ).fetchone()
            if claimed is not None:
                return dict_from_row(claimed)
    return None


def _synthesis_conflict(conn, job: dict) -> bool:
    if int(job.get("can_run_during_synthesis") or 0) == 1:
        return False
    cutoff = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    row = conn.execute(
        """
        SELECT 1 FROM chat_generations
        WHERE state = 'in_flight'
           OR (state = 'retriable' AND updated_at >= ?)
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    return row is not None


def _with_runtime_estimate(job: dict) -> dict:
    timeout = job.get("timeout_seconds")
    started_at = job.get("started_at")
    elapsed = None
    remaining = None
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            elapsed = max(0, int((datetime.now(UTC) - started).total_seconds()))
        except ValueError:
            elapsed = None
    if elapsed is not None and timeout:
        remaining = max(0, int(timeout) - elapsed)
    job["elapsed_seconds"] = elapsed
    job["estimated_remaining_seconds"] = remaining
    return job


def _run_claimed_job(job: dict) -> None:
    if job["job_type"] not in JOB_REGISTRY:
        _mark_job_manual_review(job, f"Unsupported job type: {job['job_type']}")
        return
    try:
        payload = _decode_payload(job["payload"])
        if job["job_type"] in {
            "project_discover", "project_structure_index", "project_retrieval_stage",
            "project_snapshot_activate", "project_candidate_cleanup",
        }:
            _run_project_phase(job["job_type"], payload, job["id"])
        elif job["job_type"] == "reindex_source":
            _run_reindex_source(payload)
        elif job["job_type"] == "chat_transcript_memory":
            _run_chat_transcript_memory(payload)
        elif job["job_type"] == "refresh_cluster_profile":
            _run_refresh_cluster_profile(payload)
        elif job["job_type"] == "ocr_source":
            _run_ocr_source(payload, job["id"])
        elif job["job_type"] == "expanded_analysis":
            _run_expanded_analysis(payload, job["id"])
        elif job["job_type"] == "complete_analysis":
            _run_complete_analysis(payload, job["id"])
        elif job["job_type"] == "delete_source_cleanup":
            _run_delete_source_cleanup(payload)
        elif job["job_type"] == "vector_reconcile_incremental":
            _run_vector_reconcile_incremental(payload)
        elif job["job_type"] == "integration_refresh":
            _run_integration_refresh(payload)
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
    except Exception as exc:
        _mark_job_failed_or_retry(job, str(exc))
        return

    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'succeeded', completed_at = ?, updated_at = ?, last_error = '',
                status_detail = ''
            WHERE id = ? AND status = 'running'
            """,
            (utc_now(), utc_now(), job["id"]),
        )


def _run_reindex_source(payload: dict) -> None:
    require_embeddings_available("Source reindexing")
    source_id = str(payload["source_id"])
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return
        source = dict_from_row(row)
        if source.get("deleted_at") or source["state"] != "indexed":
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            return
        reindex_source_chunks(conn, source)
        mark_cluster_needs_update(conn, source.get("cluster_id"), "Source was indexed in the background.")
        rebuild_source_memory(conn, source_id=source_id)
        _refresh_project_retrieval_status(conn, source_id)


def _run_project_phase(job_type: str, payload: dict, job_id: str) -> None:
    from backend.app.core import project_indexing

    function = {
        "project_discover": project_indexing.discover_candidate,
        "project_structure_index": project_indexing.index_candidate_structure,
        "project_retrieval_stage": project_indexing.stage_candidate_retrieval,
        "project_snapshot_activate": project_indexing.activate_candidate,
        "project_candidate_cleanup": project_indexing.cleanup_candidate,
    }[job_type]
    function(
        project_id=str(payload["project_id"]), run_id=str(payload["run_id"]),
        snapshot_id=str(payload["candidate_snapshot_id"]), job_id=job_id,
    )


def _refresh_project_retrieval_status(conn, source_id: str) -> None:
    project_rows = conn.execute(
        "SELECT project_id FROM project_sources WHERE source_id = ?",
        (source_id,),
    ).fetchall()
    for row in project_rows:
        project_id = row["project_id"]
        missing = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM project_sources ps
            JOIN sources s ON s.id = ps.source_id
            WHERE ps.project_id = ? AND s.deleted_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM source_chunks sc WHERE sc.source_id = ps.source_id)
            """,
            (project_id,),
        ).fetchone()["total"]
        if int(missing or 0) == 0:
            now = utc_now()
            conn.execute(
                "UPDATE projects SET retrieval_status = 'ready', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            conn.execute(
                """
                UPDATE project_snapshots SET retrieval_status = 'ready'
                WHERE id = (SELECT active_snapshot_id FROM projects WHERE id = ?)
                """,
                (project_id,),
            )


def _run_chat_transcript_memory(payload: dict) -> None:
    require_embeddings_available("Chat transcript memory")
    from backend.app.core.chat_memory import upsert_chat_transcript_sources

    vault_id = str(payload["vault_id"])
    session_id = str(payload["session_id"])
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexing', memory_updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        upsert_chat_transcript_sources(conn, vault_id=vault_id, session_id=session_id)
        rebuild_chat_session_memory(conn, vault_id=vault_id, session_id=session_id)
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexed', memory_updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )


def _run_refresh_cluster_profile(payload: dict) -> None:
    cluster_id = str(payload.get("cluster_id") or "")
    if not cluster_id:
        return
    with connect() as conn:
        refresh_cluster_profile(conn, cluster_id)


def _run_ocr_source(payload: dict, job_id: str) -> None:
    require_embeddings_available("OCR source indexing")
    from backend.app.core.extraction import extract_pages_from_path

    source_id = str(payload["source_id"])
    with connect() as conn:
        source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if source is None or source["deleted_at"] is not None:
            return
        path = source["original_path"]
        if not path:
            raise RuntimeError("OCR source job requires an original local path.")
        title, pages = extract_pages_from_path(path)
        text = "\n\n".join(page for page in pages if page.strip()).strip()
        if not text:
            raise RuntimeError("OCR produced no readable text.")
        _update_job_progress(
            conn,
            job_id,
            {
                "phase": "pages_extracted",
                "page_current": 0,
                "page_total": len(pages),
                "progress_percent": 0.0 if pages else 100.0,
            },
        )
        now = utc_now()
        delete_source_derived_encrypted_content(conn, source_id=source_id, vault_id=source["vault_id"])
        conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
        for index, page_text in enumerate(pages, start=1):
            cleaned = (page_text or "").strip()
            if not cleaned:
                _update_ocr_page_progress(conn, job_id, index, len(pages), skipped=True)
                continue
            page_id = f"page-{uuid4()}"
            conn.execute(
                """
                INSERT INTO source_pages (
                    id, source_id, vault_id, page_number, raw_text, extraction_version,
                    content_hash, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'ocrmypdf-tesseract-v1', ?, ?, ?)
                """,
                (
                    page_id,
                    source_id,
                    source["vault_id"],
                    index,
                    plaintext_column_for_text(
                        conn,
                        vault_id=source["vault_id"],
                        entity_type="source_page",
                        entity_id=page_id,
                        field_name="raw_text",
                        text=cleaned,
                        now=now,
                    ),
                    content_hash(cleaned),
                    now,
                    now,
                ),
            )
            _update_ocr_page_progress(conn, job_id, index, len(pages))
        stored_updates = update_source_content_fields(
            conn,
            vault_id=source["vault_id"],
            source_id=source_id,
            updates={"raw_text": text, "extracted_text": text},
            now=now,
        )
        conn.execute(
            """
            UPDATE sources
            SET title = ?, raw_text = ?, extracted_text = ?, state = 'indexed', updated_at = ?
            WHERE id = ?
            """,
            (title or source["title"], stored_updates["raw_text"], stored_updates["extracted_text"], now, source_id),
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None:
            reindex_source_chunks(conn, dict_from_row(row))
            mark_cluster_needs_update(conn, row["cluster_id"], "OCR source text was indexed.")


def _update_ocr_page_progress(conn, job_id: str, page_current: int, page_total: int, *, skipped: bool = False) -> None:
    percent = round((page_current / max(page_total, 1)) * 100, 2)
    _update_job_progress(
        conn,
        job_id,
        {
            "phase": "page_indexing",
            "page_current": page_current,
            "page_total": page_total,
            "progress_percent": percent,
            "last_page_skipped": skipped,
        },
    )


def _update_job_progress(conn, job_id: str, detail: dict) -> None:
    conn.execute(
        "UPDATE app_jobs SET status_detail = ?, updated_at = ? WHERE id = ? AND status = 'running'",
        (json.dumps(detail, separators=(",", ":")), utc_now(), job_id),
    )


def _run_expanded_analysis(payload: dict, job_id: str) -> None:
    _materialize_analysis_packets(payload, job_id, full_scope=False)


def _run_complete_analysis(payload: dict, job_id: str) -> None:
    _materialize_analysis_packets(payload, job_id, full_scope=True)


def _materialize_analysis_packets(payload: dict, job_id: str, *, full_scope: bool) -> None:
    query = str(payload.get("query") or "").strip()
    vault_id = str(payload.get("vault_id") or "").strip()
    cluster_id = str(payload.get("cluster_id") or "").strip() or None
    limit = max(1, min(int(payload.get("limit") or 12), 50))
    if not query or not vault_id:
        raise RuntimeError("Analysis job requires vault_id and query.")
    require_embeddings_available("Analysis job")
    packet_bundle = build_analysis_packets(
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        include_chat_transcripts=False,
        limit=None if full_scope else limit,
        full_scope=full_scope,
    )
    with connect() as conn:
        conn.execute("DELETE FROM analysis_evidence_packets WHERE job_id = ?", (job_id,))
        now = utc_now()
        for packet in packet_bundle["packets"]:
            conn.execute(
                """
                INSERT INTO analysis_evidence_packets (
                    id, job_id, vault_id, cluster_id, query, source_id, source_title,
                    relevance_score, status, read_error, evidence_excerpt, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    f"evidence-{uuid4()}",
                    job_id,
                    vault_id,
                    cluster_id,
                    query,
                    packet["source_id"],
                    packet["source_title"],
                    round(float(packet["score"]), 4),
                    packet["status"],
                    packet["evidence_excerpt"],
                    now,
                ),
            )


def _run_delete_source_cleanup(payload: dict) -> None:
    source_id = str(payload["source_id"])
    with connect() as conn:
        source = conn.execute("SELECT vault_id FROM sources WHERE id = ?", (source_id,)).fetchone()
        delete_source_encrypted_content(
            conn,
            source_id=source_id,
            vault_id=source["vault_id"] if source is not None else None,
        )
        conn.execute(
            """
            UPDATE retrieval_snapshot_items
            SET state = 'source_deleted', source_id = NULL, chunk_id = NULL, page_id = NULL
            WHERE source_id = ? OR chunk_id IN (
                SELECT id FROM source_chunks WHERE source_id = ?
            ) OR page_id IN (
                SELECT id FROM source_pages WHERE source_id = ?
            )
            """,
            (source_id, source_id, source_id),
        )
        conn.execute("DELETE FROM chat_attachments WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
        conn.execute(
            """
            UPDATE sources
            SET raw_text = '', extracted_text = '', summary = '', tags = '[]',
                cover_image_url = NULL, original_path = NULL, url = NULL, checksum = NULL
            WHERE id = ? AND deleted_at IS NOT NULL
            """,
            (source_id,),
        )


def _enqueue_due_integration_refresh_jobs() -> None:
    now = utc_now()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, vault_id
            FROM integration_imports
            WHERE watch_enabled = 1
              AND vault_id IS NOT NULL
              AND (next_watch_at IS NULL OR next_watch_at <= ?)
            LIMIT 25
            """,
            (now,),
        ).fetchall()
        for row in rows:
            enqueue_job(
                conn,
                job_type="integration_refresh",
                payload={"import_id": row["id"], "vault_id": row["vault_id"]},
                dedupe_key=f"integration-refresh:{row['id']}",
                scope_id=row["vault_id"],
            )


def _run_vector_reconcile_incremental(payload: dict) -> None:
    require_embeddings_available("Vector reconciliation")
    vault_id = payload.get("vault_id")
    limit = int(payload.get("limit") or 100)
    plan = vector_repair_plan(str(vault_id) if vault_id else None)
    source_ids = [*plan["missing_vector_source_ids"], *plan["stale_vector_source_ids"]][:limit]
    with connect() as conn:
        for source_id in source_ids:
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": source_id},
                dedupe_key=f"reindex-source:{source_id}",
                scope_id=source_id,
            )


def _run_integration_refresh(payload: dict) -> None:
    from backend.app.api.routes.integrations import refresh_integration_import

    import_id = str(payload.get("import_id") or "")
    if not import_id:
        raise RuntimeError("Integration refresh job requires import_id.")
    refresh_integration_import(
        import_id,
        import_files=True,
        tombstone_missing=True,
        trigger_source="watch_refresh",
    )
def _mark_job_failed_or_retry(job: dict, error: str) -> None:
    with connect() as conn:
        current = conn.execute(
            "SELECT attempts, max_attempts FROM app_jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
        attempts = int(current["attempts"] if current is not None else job.get("attempts") or 0)
        max_attempts = int(current["max_attempts"] if current is not None else job.get("max_attempts") or 3)
        status = "failed" if attempts >= max_attempts else "queued"
        completed_at = utc_now() if status == "failed" else None
        conn.execute(
            """
            UPDATE app_jobs
            SET status = ?, last_error = ?, status_detail = ?,
                completed_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, error[:500], error[:500], completed_at, utc_now(), job["id"]),
        )
        if status == "failed" and job.get("job_type", "").startswith("project_"):
            payload = _decode_payload(job.get("payload") or "{}")
            run_id = str(payload.get("run_id") or "")
            project_id = str(payload.get("project_id") or "")
            snapshot_id = str(payload.get("candidate_snapshot_id") or "")
            if run_id and project_id:
                now = utc_now()
                conn.execute(
                    """
                    UPDATE project_index_runs SET status = 'failed', failure_category = ?,
                        activation_outcome = 'not_activated', finished_at = ?, heartbeat_at = ?, updated_at = ?
                    WHERE id = ? AND status != 'cancelled'
                    """,
                    (job["job_type"], now, now, now, run_id),
                )
                conn.execute(
                    """
                    UPDATE projects SET active_run_id = NULL, candidate_snapshot_id = NULL,
                        status = CASE
                            WHEN active_snapshot_id IS NULL THEN 'issue'
                            WHEN structure_status = 'partial' OR retrieval_status = 'partial' THEN 'partial'
                            ELSE 'ready'
                        END,
                        updated_at = ? WHERE id = ?
                    """,
                    (now, project_id),
                )
                active = conn.execute(
                    """
                    SELECT 1 FROM projects WHERE id = ? AND ? IN (
                        active_snapshot_id, active_manifest_snapshot_id,
                        active_structure_snapshot_id, active_retrieval_snapshot_id
                    )
                    """,
                    (project_id, snapshot_id),
                ).fetchone() if snapshot_id else None
                if snapshot_id and active is None:
                    enqueue_job(
                        conn, job_type="project_candidate_cleanup",
                        payload={"project_id": project_id, "run_id": run_id, "candidate_snapshot_id": snapshot_id},
                        dedupe_key=f"project-cleanup:{snapshot_id}", scope_id=project_id,
                    )


def _decode_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _refresh_blocked_dependencies() -> None:
    now = utc_now()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT blocked.*, dependency.status AS dependency_status
            FROM app_jobs blocked
            JOIN app_jobs dependency ON dependency.id = blocked.depends_on_job_id
            WHERE blocked.status = 'blocked_by_dependency'
            """
        ).fetchall()
        for row in rows:
            job = dict_from_row(row)
            dependency_status = job["dependency_status"]
            if dependency_status == "succeeded":
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET status = 'queued', status_detail = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, job["id"]),
                )
            elif dependency_status in TERMINAL_DEPENDENCY_STATUSES:
                _apply_dependency_failure(conn, job, f"Dependency ended with status {dependency_status}.")
        missing_rows = conn.execute(
            """
            SELECT blocked.*
            FROM app_jobs blocked
            LEFT JOIN app_jobs dependency ON dependency.id = blocked.depends_on_job_id
            WHERE blocked.status = 'blocked_by_dependency'
              AND blocked.depends_on_job_id IS NOT NULL
              AND dependency.id IS NULL
            """
        ).fetchall()
        for row in missing_rows:
            _apply_dependency_failure(conn, dict_from_row(row), "Dependency job is missing.")


def _job_policy(job_type: str) -> JobPolicy:
    return JOB_REGISTRY.get(job_type, UNKNOWN_JOB_POLICY)


def _policy_row_values(policy: JobPolicy) -> dict:
    values = asdict(policy)
    for key in (
        "can_run_during_synthesis",
        "user_visible",
        "user_initiated",
        "cancellable",
        "preemptable",
    ):
        values[key] = int(values[key])
    return values


def _default_scope_id(write_scope: str, payload: dict) -> str | None:
    if write_scope == "source":
        return _optional_string(payload.get("source_id"))
    if write_scope == "chat":
        return _optional_string(payload.get("session_id"))
    if write_scope == "cluster":
        return _optional_string(payload.get("cluster_id"))
    if write_scope == "vault":
        return _optional_string(payload.get("vault_id"))
    return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _resolve_dependency(conn, job: dict) -> bool:
    dependency_id = job.get("depends_on_job_id")
    if not dependency_id:
        return True
    row = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (dependency_id,)).fetchone()
    if row is None:
        _apply_dependency_failure(conn, job, "Dependency job is missing.")
        return False
    status = row["status"]
    if status == "succeeded":
        return True
    if status in TERMINAL_DEPENDENCY_STATUSES:
        _apply_dependency_failure(conn, job, f"Dependency ended with status {status}.")
    return False


def _apply_dependency_failure(conn, job: dict, detail: str) -> None:
    policy = job.get("dependency_failure_policy") or "cancel"
    now = utc_now()
    if policy == "cancel":
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'cancelled', status_detail = ?, completed_at = ?, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'blocked_by_dependency')
            """,
            (detail, now, now, job["id"]),
        )
    elif policy == "manual_review":
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'manual_review', status_detail = ?, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'blocked_by_dependency')
            """,
            (detail, now, job["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'blocked_by_dependency', status_detail = ?, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'blocked_by_dependency')
            """,
            (detail, now, job["id"]),
        )


def _has_scope_conflict(conn, job: dict) -> bool:
    # V1 scheduler assumption: one backend process and one scheduler worker own a vault.
    # This query-before-claim check is sufficient only under that single-worker model.
    group = job.get("concurrency_group")
    if group:
        row = conn.execute(
            """
            SELECT 1 FROM app_jobs
            WHERE status = 'running' AND concurrency_group = ? AND id != ?
            LIMIT 1
            """,
            (group, job["id"]),
        ).fetchone()
        if row is not None:
            return True
    write_scope = job.get("write_scope")
    scope_id = job.get("scope_id")
    if not write_scope or write_scope == "none" or not scope_id:
        return False
    row = conn.execute(
        """
        SELECT 1 FROM app_jobs
        WHERE status = 'running'
            AND write_scope = ?
            AND scope_id = ?
            AND id != ?
        LIMIT 1
        """,
        (write_scope, scope_id, job["id"]),
    ).fetchone()
    return row is not None


def _mark_job_manual_review(job: dict, detail: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'manual_review', last_error = ?, status_detail = ?,
                completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (detail[:500], detail[:500], utc_now(), utc_now(), job["id"]),
        )
