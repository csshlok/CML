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
from backend.app.core.expert_lifecycle import mark_cluster_needs_update
from backend.app.core.config import get_settings
from backend.app.core.expert_runtime import runtime_adapter_load_plan
from backend.app.core.model_registry import preferred_expert_base_model
from backend.app.core.vector_maintenance import vector_repair_plan
from backend.app.core.context_memory import rebuild_chat_session_memory, rebuild_source_memory
from backend.app.core.analysis_packets import build_analysis_packets
from backend.app.core.training_dataset import build_cluster_dataset, write_cluster_training_dataset
from backend.app.core.training_evaluation import evaluate_adapter_quality, evaluate_cluster_dataset
from backend.app.core.unlock_state import should_pause_vault_job
from backend.app.core.expert_evaluation import build_expert_benchmark_report, build_expert_evaluation_plan
from backend.app.core.lora_training import (
    LoraTrainerMissingError,
    adapter_validation_report,
    dataset_graduation_report,
    new_artifact_dir,
    run_lora_training_process,
    training_config,
)


JOB_POLL_SECONDS = 1.0
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
    "train_cluster_adapter": JobPolicy(
        priority="low",
        idempotency_class="reconcile_required",
        restart_policy="manual_review",
        dependency_failure_policy="manual_review",
        write_scope="expert",
        concurrency_group="adapter_training",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=7200,
        soft_timeout_seconds=1800,
        timeout_action="escalate",
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
            if restart_policy == "requeue":
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
            break
        _run_claimed_job(job)
        processed += 1
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
            """
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
        if job["job_type"] == "reindex_source":
            _run_reindex_source(payload)
        elif job["job_type"] == "chat_transcript_memory":
            _run_chat_transcript_memory(payload)
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
        elif job["job_type"] == "train_cluster_adapter":
            _run_train_cluster_adapter(payload)
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


def _run_train_cluster_adapter(payload: dict) -> None:
    from backend.app.core.hardware import hardware_status

    cluster_id = str(payload.get("cluster_id") or "")
    vault_id = str(payload.get("vault_id") or "")
    expert_job_id = str(payload.get("expert_job_id") or "")

    hardware = hardware_status()
    now = utc_now()

    with connect() as conn:
        if hardware["training_supported"] is not True:
            conn.execute(
                """
                UPDATE clusters
                SET expert_status = 'hardware_unsupported',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, cluster_id),
            )

            if expert_job_id:
                conn.execute(
                    """
                    UPDATE cluster_expert_jobs
                    SET status = 'manual_review',
                        failure_code = 'hardware_unsupported',
                        detail = ?,
                        hardware_tier = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        hardware["detail"],
                        hardware["hardware_tier"],
                        now,
                        expert_job_id,
                    ),
                )

            conn.commit()
            raise RuntimeError(hardware["detail"])

        conn.execute(
            """
            UPDATE clusters
            SET expert_status = 'training_running',
                updated_at = ?
            WHERE id = ?
            """,
            (now, cluster_id),
        )
        if expert_job_id:
            conn.execute(
                """
                UPDATE cluster_expert_jobs
                SET status = 'running',
                    detail = 'LoRA adapter training is running.',
                    hardware_tier = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (hardware["hardware_tier"], now, expert_job_id),
            )

        dataset = build_cluster_dataset(cluster_id)
        dataset_gate = dataset_graduation_report(dataset)
        if not dataset_gate["passes"]:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="insufficient_dataset",
                detail=f"Cluster does not meet LoRA graduation dataset gates: {dataset_gate}",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Cluster does not meet LoRA graduation dataset gates.")

        quality_score = evaluate_cluster_dataset(dataset)
        artifact_dir = new_artifact_dir(cluster_id)
        dataset_manifest = write_cluster_training_dataset(dataset, artifact_dir / "dataset")
        dataset_gate = dataset_graduation_report(dataset, validation_count=int(dataset_manifest["validation_count"]))
        if not dataset_gate["passes"]:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="insufficient_dataset",
                detail=f"Cluster does not meet LoRA graduation validation gates: {dataset_gate}",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Cluster does not meet LoRA graduation validation gates.")
        preferred_model = preferred_expert_base_model()
        if preferred_model is None:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="runtime_load_failed",
                detail="No accepted local base model is active for expert training.",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("No accepted local base model is active for expert training.")
        config = training_config(
            base_model=str(preferred_model.get("local_path") or preferred_model.get("id") or get_settings().llm_model),
            dataset_hash=dataset["dataset_hash"],
        )

        try:
            train_result = run_lora_training_process(
                dataset_manifest=dataset_manifest,
                output_dir=artifact_dir,
                config=config,
            )
        except LoraTrainerMissingError as exc:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="trainer_missing",
                detail=str(exc),
                hardware_tier=hardware["hardware_tier"],
            )
            raise
        except Exception as exc:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="trainer_failed",
                detail=str(exc),
                hardware_tier=hardware["hardware_tier"],
            )
            raise

        adapter_validation = adapter_validation_report(train_result["adapter_path"])
        if not adapter_validation["valid"]:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="adapter_invalid",
                detail=f"Adapter artifact validation failed: {adapter_validation['errors']}",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Adapter artifact validation failed.")

        runtime_load = runtime_adapter_load_plan(
            adapter_path=train_result["adapter_path"],
            base_model=config["base_model"],
        )
        if not runtime_load["available"]:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="runtime_load_failed",
                detail=runtime_load["detail"],
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Adapter runtime load contract is unavailable.")

        current_dataset = build_cluster_dataset(cluster_id)
        if str(current_dataset.get("dataset_hash") or "") != str(dataset.get("dataset_hash") or ""):
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="dataset_changed",
                detail="Cluster sources changed before the adapter could be activated. Queue a fresh retrain pass.",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Cluster sources changed before adapter activation.")

        metrics = evaluate_adapter_quality(
            dataset_score=quality_score,
            adapter_dir_exists=True,
            adapter_valid=True,
            validation_count=int(dataset_manifest["validation_count"]),
        )
        evaluation_plan = build_expert_evaluation_plan(dataset)
        metrics["dataset_gate"] = dataset_gate
        metrics["adapter_validation"] = adapter_validation
        metrics["runtime_load"] = runtime_load
        metrics["evaluation_plan"] = {
            "case_count": evaluation_plan["case_count"],
            "categories": evaluation_plan["categories"],
            "dataset_hash": evaluation_plan.get("dataset_hash"),
        }
        metrics["benchmark_report"] = build_expert_benchmark_report(
            evaluation_plan,
            retrieval_case_scores=[],
            adapter_case_scores=[],
            mode="pending_live_adapter_benchmark",
            live_adapter_backed=False,
        )
        min_quality = get_settings().lora_min_quality_score
        min_delta = get_settings().lora_min_quality_delta
        if float(metrics["adapter_score"]) < min_quality or float(metrics["quality_delta"]) < min_delta:
            _mark_expert_training_failed(
                conn,
                cluster_id=cluster_id,
                expert_job_id=expert_job_id,
                failure_code="quality_gate_failed",
                detail=f"Adapter did not pass quality gate: {metrics}",
                hardware_tier=hardware["hardware_tier"],
            )
            raise RuntimeError("Adapter did not pass the LoRA quality gate.")

        artifact_id = f"artifact-{uuid4()}"
        conn.execute(
            """
            UPDATE expert_artifacts
            SET active = 0,
                updated_at = ?
            WHERE cluster_id = ? AND active = 1
            """,
            (now, cluster_id),
        )

        conn.execute(
            """
            INSERT INTO expert_artifacts (
                id,
                cluster_id,
                vault_id,
                job_id,
                artifact_type,
                status,
                local_path,
                base_model,
                hardware_tier,
                quality_score,
                dataset_hash,
                training_config_hash,
                metrics_json,
                active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                cluster_id,
                vault_id,
                expert_job_id or None,
                "lora_adapter",
                "ready",
                train_result["adapter_path"],
                config["base_model"],
                hardware["hardware_tier"],
                metrics["adapter_score"],
                dataset["dataset_hash"],
                config["training_config_hash"],
                json.dumps(metrics, separators=(",", ":")),
                1,
                now,
                now,
            ),
        )

        if expert_job_id:
            conn.execute(
                """
                UPDATE cluster_expert_jobs
                SET status = ?,
                    detail = ?,
                    hardware_tier = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    "completed",
                    f"LoRA adapter trained and activated. Adapter score={metrics['adapter_score']}",
                    hardware["hardware_tier"],
                    now,
                    expert_job_id,
                ),
            )

        conn.execute(
            """
            UPDATE clusters
            SET expert_status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                "training_ready",
                now,
                cluster_id,
            ),
        )


def _mark_expert_training_failed(
    conn,
    *,
    cluster_id: str,
    expert_job_id: str,
    failure_code: str,
    detail: str,
    hardware_tier: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE clusters
        SET expert_status = 'training_failed',
            updated_at = ?
        WHERE id = ?
        """,
        (now, cluster_id),
    )
    if expert_job_id:
        conn.execute(
            """
            UPDATE cluster_expert_jobs
            SET status = 'failed',
                failure_code = ?,
                detail = ?,
                hardware_tier = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (failure_code, detail[:1000], hardware_tier, now, expert_job_id),
        )
    conn.commit()


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
            WHERE id = ?
            """,
            (status, error[:500], error[:500], completed_at, utc_now(), job["id"]),
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
    if write_scope == "expert":
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
