import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import active_embedding_model_id, reindex_source_chunks, require_embeddings_available
from backend.app.core.expert_lifecycle import mark_cluster_needs_update

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
    job = {
        "id": f"job-{uuid4()}",
        "job_type": job_type,
        "status": "queued",
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
            if _synthesis_conflict(conn, job):
                continue
            if _has_scope_conflict(conn, job):
                continue
            now = utc_now()
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'running', attempts = attempts + 1, started_at = ?,
                    status_detail = '', updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job["id"]),
            )
            return job
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
        elif job["job_type"] == "delete_source_cleanup":
            _run_delete_source_cleanup(payload)
        elif job["job_type"] == "vector_reconcile_incremental":
            _run_vector_reconcile_incremental(payload)
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
            WHERE id = ?
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
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexed', memory_updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )


def _run_delete_source_cleanup(payload: dict) -> None:
    source_id = str(payload["source_id"])
    with connect() as conn:
        conn.execute(
            """
            UPDATE retrieval_snapshot_items
            SET state = 'source_deleted', source_id = NULL, chunk_id = NULL, page_id = NULL
            WHERE source_id = ?
            """,
            (source_id,),
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


def _run_vector_reconcile_incremental(payload: dict) -> None:
    require_embeddings_available("Vector reconciliation")
    vault_id = payload.get("vault_id")
    model_id = active_embedding_model_id()
    with connect() as conn:
        params: list[str] = []
        vault_clause = ""
        if vault_id:
            vault_clause = "AND sources.vault_id = ?"
            params.append(str(vault_id))
        params.append(model_id)
        rows = conn.execute(
            f"""
            SELECT sources.id
            FROM sources
            LEFT JOIN source_chunks chunks ON chunks.source_id = sources.id
            WHERE sources.state = 'indexed'
                AND sources.deleted_at IS NULL
                {vault_clause}
            GROUP BY sources.id
            HAVING COUNT(chunks.id) = 0
                OR SUM(CASE WHEN chunks.embedding_model_id != ? THEN 1 ELSE 0 END) > 0
            LIMIT 100
            """,
            params,
        ).fetchall()
        for row in rows:
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": row["id"]},
                dedupe_key=f"reindex-source:{row['id']}",
                scope_id=row["id"],
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
                UPDATE clusters SET expert_status = 'hardware_unsupported', updated_at = ?
                WHERE id = ?
                """,
                (now, cluster_id),
            )
            if expert_job_id:
                conn.execute(
                    """
                    UPDATE cluster_expert_jobs
                    SET status = 'manual_review', failure_code = 'hardware_unsupported',
                        detail = ?, hardware_tier = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (hardware["detail"], hardware["hardware_tier"], now, expert_job_id),
                )
            raise RuntimeError(hardware["detail"])
        conn.execute(
            """
            INSERT INTO expert_artifacts (
                id, cluster_id, vault_id, job_id, artifact_type, status, local_path,
                base_model, hardware_tier, quality_score, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'lora_adapter', 'planned', NULL, '', ?, NULL, ?, ?)
            """,
            (
                f"artifact-{uuid4()}",
                cluster_id,
                vault_id,
                expert_job_id or None,
                hardware["hardware_tier"],
                now,
                now,
            ),
        )
        if expert_job_id:
            conn.execute(
                """
                UPDATE cluster_expert_jobs
                SET status = 'manual_review', failure_code = 'training_not_implemented',
                    detail = 'Adapter training scaffold is ready, but the LoRA runner is not implemented yet.',
                    hardware_tier = ?, updated_at = ?
                WHERE id = ?
                """,
                (hardware["hardware_tier"], now, expert_job_id),
            )
        conn.execute(
            """
            UPDATE clusters SET expert_status = 'expert_training_pending', updated_at = ?
            WHERE id = ?
            """,
            (now, cluster_id),
        )


def _mark_job_failed_or_retry(job: dict, error: str) -> None:
    attempts = int(job.get("attempts") or 0) + 1
    max_attempts = int(job.get("max_attempts") or 3)
    status = "failed" if attempts >= max_attempts else "queued"
    completed_at = utc_now() if status == "failed" else None
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = ?, attempts = ?, last_error = ?, status_detail = ?,
                completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, attempts, error[:500], error[:500], completed_at, utc_now(), job["id"]),
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
