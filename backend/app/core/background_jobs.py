import json
import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import (
    content_hash,
    embedding_status,
    reindex_source_chunks,
    require_embeddings_available,
)
from backend.app.core.encrypted_storage import (
    delete_source_encrypted_content,
    delete_source_derived_encrypted_content,
    hydrate_chat_message_rows,
    load_source_content_fields,
    plaintext_column_for_text,
    update_source_content_fields,
)
from backend.app.core.cluster_lifecycle import (
    mark_cluster_metadata_pending,
    mark_cluster_needs_update,
    prune_empty_auto_cluster,
    refresh_cluster_profile,
)
from backend.app.core.vector_maintenance import vector_repair_plan
from backend.app.core.context_memory import rebuild_chat_session_memory, rebuild_source_memory
from backend.app.core.cluster_membership import (
    move_source_cluster_membership,
    repair_cluster_membership_batch,
)
from backend.app.core.memory_card import generate_tags
from backend.app.core.semantic_metadata import (
    SOURCE_METADATA_VERSION,
    SOURCE_SEMANTIC_METADATA_VERSION,
    SemanticModelUnavailable,
    enrich_source_metadata,
    fallback_source_summary,
)
from backend.app.core.atomic_memory import (
    ATOMIC_MEMORY_VERSION,
    ATOMIC_EXTRACTION_RESPONSE_SCHEMA,
    compile_semantic_atomic_session,
    source_content_hash as atomic_source_content_hash,
)
from backend.app.core.atomic_memory_store import (
    LOCAL_SEMANTIC_EXTRACTOR_VERSION,
    LOCAL_SEMANTIC_V2_EXTRACTOR_VERSION,
    chat_session_atomic_payload,
    persist_local_semantic_extraction,
)
from backend.app.core.atomic_memory_v2 import (
    AtomicMemoryV2EvidencePassResponse,
    atomic_memory_v2_session_windows,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
    compile_atomic_memory_v2_evidence,
    merge_atomic_memory_v2_evidence_windows,
)
from backend.app.core.temporal_facts import (
    CHAT_FACT_EXTRACTOR_VERSION,
    sync_chat_session_temporal_facts,
    temporal_fact_source_hash,
)
from backend.app.core.analysis_packets import build_analysis_packets
from backend.app.core.llm_runtime import LLMRuntimeError
from backend.app.core.unlock_state import should_pause_vault_job
from backend.app.core.adaptive_scheduler import (
    job_lane,
    record_lane_observation,
    source_import_worker_count,
)
from backend.app.core.source_ingestion import (
    publish_source_ingestion_stage,
    source_ingestion_identity,
)


logger = logging.getLogger("cml.background_jobs")
_LAST_WORKER_LOOP_ERROR: tuple[str, float] | None = None

JOB_POLL_SECONDS = 1.0
JOB_STATUS_RUNNING_LIMIT = 50
ACTIVE_STATUSES = ("queued", "running", "paused", "blocked_by_dependency", "blocked_setup_required", "deferred")
TERMINAL_DEPENDENCY_STATUSES = ("failed", "partial_success", "cancelled", "manual_review")
PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
    "on_demand": 4,
}
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()
_WORKER_WAKE = threading.Event()
EMBEDDING_JOB_TYPES = {
    "project_delta_apply",
    "project_retrieval_stage",
    "reindex_source",
    "chat_transcript_memory",
    "ocr_source",
    "expanded_analysis",
    "complete_analysis",
    "vector_reconcile_incremental",
}
LOCAL_MODEL_JOB_TYPES = {
    "atomic_semantic_enrichment",
    "cluster_profile_backfill",
    "refresh_cluster_profile",
    "source_semantic_enrichment",
}


class JobCancelled(RuntimeError):
    pass


class JobPaused(RuntimeError):
    pass


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
    "project_delta_probe": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="project",
        concurrency_group="project_probe",
        resource_cost="light",
        can_run_during_synthesis=True,
        user_visible=False,
        user_initiated=False,
        cancellable=True,
        preemptable=True,
        timeout_seconds=120,
        soft_timeout_seconds=30,
        timeout_action="defer",
    ),
    "project_delta_apply": JobPolicy(
        priority="normal",
        idempotency_class="reconcile_required",
        restart_policy="reconcile_then_retry",
        dependency_failure_policy="manual_review",
        write_scope="project",
        concurrency_group="project_index",
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
    "source_import_batch": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vault",
        concurrency_group="source_import",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=86_400,
        soft_timeout_seconds=3_600,
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
    "temporal_fact_backfill": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vault",
        concurrency_group="temporal_facts",
        resource_cost="light",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=True,
        timeout_seconds=1800,
        soft_timeout_seconds=300,
        timeout_action="defer",
    ),
    "atomic_semantic_enrichment": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="chat",
        concurrency_group="local_llm",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=False,
        user_initiated=False,
        cancellable=True,
        preemptable=True,
        timeout_seconds=900,
        soft_timeout_seconds=240,
        timeout_action="defer",
    ),
    "refresh_cluster_profile": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="cluster",
        concurrency_group="local_llm",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=False,
        user_initiated=False,
        cancellable=False,
        preemptable=False,
        timeout_seconds=180,
        soft_timeout_seconds=None,
        timeout_action="defer",
    ),
    "chat_answer_generation": JobPolicy(
        priority="high",
        idempotency_class="reconcile_required",
        restart_policy="reconcile_then_retry",
        dependency_failure_policy="cancel",
        write_scope="chat",
        concurrency_group="chat_generation",
        resource_cost="heavy",
        can_run_during_synthesis=True,
        user_visible=False,
        user_initiated=True,
        cancellable=False,
        preemptable=False,
        timeout_seconds=3600,
        soft_timeout_seconds=600,
        timeout_action="defer",
    ),
    "cluster_profile_backfill": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="cluster",
        concurrency_group="local_llm",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=True,
        timeout_seconds=3600,
        soft_timeout_seconds=300,
        timeout_action="defer",
    ),
    "source_metadata_enrichment": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="source",
        concurrency_group="source_metadata",
        resource_cost="light",
        can_run_during_synthesis=True,
        user_visible=False,
        user_initiated=False,
        cancellable=True,
        preemptable=True,
        timeout_seconds=300,
        soft_timeout_seconds=120,
        timeout_action="defer",
    ),
    "source_semantic_enrichment": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="source",
        concurrency_group="local_llm",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=False,
        user_initiated=False,
        cancellable=True,
        preemptable=True,
        timeout_seconds=300,
        soft_timeout_seconds=120,
        timeout_action="defer",
    ),
    "source_cluster_reconciliation": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vault",
        concurrency_group="cluster_reconciliation",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=False,
        timeout_seconds=900,
        soft_timeout_seconds=180,
        timeout_action="defer",
    ),
    "cluster_membership_repair": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vault",
        concurrency_group="cluster_membership",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=300,
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
    "model_import": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="model_registry",
        concurrency_group="model_storage",
        resource_cost="heavy",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=3600,
        soft_timeout_seconds=600,
        timeout_action="defer",
    ),
    "model_discovery": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="model_registry",
        concurrency_group="model_storage",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=True,
        cancellable=True,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=120,
        timeout_action="defer",
    ),
    "turbovec_evaluate": JobPolicy(
        priority="low",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="vector_index",
        concurrency_group="vector_writer",
        resource_cost="heavy",
        can_run_during_synthesis=False,
        user_visible=True,
        user_initiated=False,
        cancellable=True,
        preemptable=True,
        timeout_seconds=3600,
        soft_timeout_seconds=600,
        timeout_action="defer",
    ),
    "model_runtime_recovery": JobPolicy(
        priority="high",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="model_registry",
        concurrency_group="model_storage",
        resource_cost="medium",
        can_run_during_synthesis=True,
        user_visible=True,
        user_initiated=False,
        cancellable=False,
        preemptable=False,
        timeout_seconds=1800,
        soft_timeout_seconds=180,
        timeout_action="defer",
    ),
    "diagnostic_bundle": JobPolicy(
        priority="normal",
        idempotency_class="idempotent",
        restart_policy="requeue",
        dependency_failure_policy="cancel",
        write_scope="diagnostics",
        concurrency_group="diagnostics",
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
            WHERE dedupe_key = ? AND status IN (
                'queued', 'running', 'blocked_by_dependency', 'blocked_setup_required', 'deferred'
            )
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
    status_detail = ""
    if depends_on_job_id:
        dependency = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (depends_on_job_id,)).fetchone()
        if dependency is None or dependency["status"] != "succeeded":
            status = "blocked_by_dependency"
            status_detail = {
                "project_structure_index": "Waiting for the project scan to finish.",
                "project_retrieval_stage": "Waiting for project structure.",
                "project_snapshot_activate": "Waiting for project files to finish indexing.",
            }.get(job_type, "Waiting for an earlier task to finish.")
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
        "status_detail": status_detail,
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
    counts = {"queued": 0, "manual_review": 0, "cancelled": 0}
    with connect() as conn:
        rows = conn.execute("SELECT * FROM app_jobs WHERE status = 'running'").fetchall()
        for row in rows:
            job = dict_from_row(row)
            if int(job.get("cancellation_requested") or 0) == 1:
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET status = 'cancelled', status_detail = ?, completed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    ("Cancellation acknowledged during backend recovery.", now, now, job["id"]),
                )
                counts["cancelled"] += 1
                continue
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


def wake_background_worker() -> None:
    _WORKER_WAKE.set()


def enqueue_startup_reconciliation_jobs() -> None:
    with connect() as conn:
        if embedding_status(probe_model=False).get("available"):
            enqueue_job(
                conn,
                job_type="vector_reconcile_incremental",
                payload={},
                dedupe_key="vector-reconcile:startup",
            )
        stale_vaults = conn.execute(
            """
            SELECT DISTINCT sessions.vault_id
            FROM chat_sessions sessions
            LEFT JOIN temporal_fact_session_state state
              ON state.session_id = sessions.id AND state.vault_id = sessions.vault_id
            WHERE state.session_id IS NULL
               OR state.extractor_version != ?
               OR state.source_message_count != (
                    SELECT COUNT(*) FROM chat_messages messages
                    WHERE messages.session_id = sessions.id
               )
            """,
            (CHAT_FACT_EXTRACTOR_VERSION,),
        ).fetchall()
        for row in stale_vaults:
            vault_id = str(row["vault_id"])
            enqueue_job(
                conn,
                job_type="temporal_fact_backfill",
                payload={"vault_id": vault_id, "batch_size": 50},
                dedupe_key=f"temporal-fact-backfill:{vault_id}",
                scope_id=vault_id,
                user_initiated=False,
            )
        membership_vaults = conn.execute(
            """
            SELECT DISTINCT sources.vault_id
            FROM sources
            JOIN source_chunks chunks
              ON chunks.source_id = sources.id
             AND chunks.activation_state = 'active'
            WHERE sources.deleted_at IS NULL
              AND sources.activation_state = 'active'
              AND NOT (chunks.cluster_id IS sources.cluster_id)
            """
        ).fetchall()
        for row in membership_vaults:
            vault_id = str(row["vault_id"])
            enqueue_job(
                conn,
                job_type="cluster_membership_repair",
                payload={"vault_id": vault_id, "batch_size": 100},
                dedupe_key=f"cluster-membership-repair:{vault_id}",
                scope_id=vault_id,
                user_initiated=False,
            )


def enqueue_startup_metadata_jobs(*, limit: int = 50) -> None:
    """Repair older descriptions gradually without delaying startup or flooding the model."""
    safe_limit = max(1, min(int(limit), 100))
    with connect() as conn:
        sources = conn.execute(
            """
            SELECT id, updated_at
            FROM sources
            WHERE deleted_at IS NULL
              AND state = 'indexed'
              AND metadata_version < ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (SOURCE_METADATA_VERSION, safe_limit),
        ).fetchall()
        for source in sources:
            enqueue_job(
                conn,
                job_type="source_metadata_enrichment",
                payload={
                    "source_id": source["id"],
                    "source_updated_at": source["updated_at"],
                },
                dedupe_key=f"source-metadata:{source['id']}:{source['updated_at']}",
                scope_id=str(source["id"]),
            )
        clusters = conn.execute(
            """
            SELECT id, vault_id
            FROM clusters
            WHERE (
                profile_status IN ('missing', 'stale')
                OR NOT EXISTS (
                    SELECT 1 FROM cluster_candidate_profiles profiles
                    WHERE profiles.cluster_id = clusters.id
                )
              )
              AND EXISTS (
                  SELECT 1 FROM sources
                  WHERE sources.cluster_id = clusters.id
                    AND sources.deleted_at IS NULL
                    AND sources.state = 'indexed'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM sources
                  WHERE sources.cluster_id = clusters.id
                    AND sources.deleted_at IS NULL
                    AND sources.state = 'indexed'
                    AND sources.metadata_version < ?
              )
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (SOURCE_METADATA_VERSION, safe_limit),
        ).fetchall()
        for cluster in clusters:
            enqueue_job(
                conn,
                job_type="refresh_cluster_profile",
                payload={"cluster_id": cluster["id"], "vault_id": cluster["vault_id"]},
                dedupe_key=f"refresh-cluster-profile:{cluster['id']}",
                scope_id=str(cluster["id"]),
            )


def migrate_legacy_project_index_jobs(*, limit: int = 100) -> int:
    """Terminate unreachable monolithic jobs and queue the phased replacement."""
    safe_limit = max(1, min(int(limit), 500))
    project_ids: list[str] = []
    now = utc_now()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, payload
            FROM app_jobs
            WHERE job_type = 'project_index'
              AND status IN ('queued', 'running', 'blocked_by_dependency')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            project_id = str(payload.get("project_id") or "").strip()
            run_id = str(payload.get("run_id") or "").strip()
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'failed',
                    last_error = 'legacy_project_index_removed',
                    status_detail = 'Replaced by the phased project sync.',
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, row["id"]),
            )
            if run_id:
                conn.execute(
                    """
                    UPDATE project_index_runs
                    SET status = 'failed',
                        failure_category = 'legacy_project_index_removed',
                        finished_at = ?,
                        updated_at = ?
                    WHERE id = ? AND status IN ('queued', 'running')
                    """,
                    (now, now, run_id),
                )
            if project_id:
                project = conn.execute(
                    "SELECT id FROM projects WHERE id = ? AND deleted_at IS NULL",
                    (project_id,),
                ).fetchone()
                if project is not None:
                    conn.execute(
                        """
                        UPDATE projects
                        SET active_run_id = NULL,
                            candidate_snapshot_id = NULL,
                            status = CASE
                                WHEN active_snapshot_id IS NULL THEN 'registered'
                                ELSE 'stale'
                            END,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now, project_id),
                    )
                    project_ids.append(project_id)
    if project_ids:
        from backend.app.core.projects import sync_project

        for project_id in dict.fromkeys(project_ids):
            sync_project(project_id, trigger_source="legacy_job_migration")
    return len(project_ids)


def run_due_jobs_once(limit: int = 5) -> int:
    _refresh_setup_prerequisites()
    _refresh_blocked_dependencies()
    _enqueue_due_integration_refresh_jobs()
    _enqueue_due_project_delta_jobs()
    _enqueue_due_turbovec_evaluations()
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
        local_model_placeholders = ",".join("?" for _ in LOCAL_MODEL_JOB_TYPES)
        blocked_local_model = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM app_jobs
            WHERE status = 'blocked_setup_required'
              AND job_type IN ({local_model_placeholders})
            """,
            sorted(LOCAL_MODEL_JOB_TYPES),
        ).fetchone()
    counts = {row["status"]: row["count"] for row in rows}
    return {
        "queued": counts.get("queued", 0),
        "paused": counts.get("paused", 0),
        "blocked_by_dependency": counts.get("blocked_by_dependency", 0),
        "blocked_setup_required": counts.get("blocked_setup_required", 0),
        "blocked_local_model": int(blocked_local_model["count"] or 0),
        "deferred": counts.get("deferred", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "partial_success": counts.get("partial_success", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
        "manual_review": counts.get("manual_review", 0),
        "running_jobs": [_with_runtime_estimate(public_job_record(dict_from_row(row))) for row in running],
        "latest": [public_job_record(dict_from_row(row)) for row in latest],
    }


def public_job_record(job: dict) -> dict:
    record = dict(job)
    if record.get("status") in {"failed", "partial_success", "manual_review"} and record.get("last_error"):
        record["last_error"] = str(
            record.get("status_detail")
            or "Vault could not finish this task."
        )
    return record


def cancel_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if int(job.get("cancellable") or 0) != 1:
            raise ValueError("Job is not cancellable")
        if job["status"] not in {"queued", "paused", "blocked_by_dependency", "blocked_setup_required", "deferred", "running"}:
            raise ValueError("Only queued, paused, blocked, deferred, or running jobs can be cancelled")
        if job["status"] == "running":
            conn.execute(
                """
                UPDATE app_jobs
                SET cancellation_requested = 1, cancellation_requested_at = ?,
                    status_detail = 'Cancellation requested; waiting for the current work unit to stop.',
                    updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'cancelled', cancellation_requested = 1,
                    cancellation_requested_at = ?, status_detail = 'Cancelled by user.',
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, now, job_id),
            )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict_from_row(updated)


def pause_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if int(job.get("preemptable") or 0) != 1:
            raise ValueError("This task cannot be paused")
        if job["status"] == "paused":
            return job
        if job["status"] not in {"queued", "running"}:
            raise ValueError("Only queued or running tasks can be paused")
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'paused',
                status_detail = 'Paused. The current work unit may still finish.',
                updated_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (now, job_id),
        )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict_from_row(updated)


def resume_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if int(job.get("preemptable") or 0) != 1:
            raise ValueError("This task cannot be resumed")
        if job["status"] != "paused":
            raise ValueError("Only paused tasks can be resumed")
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'queued', status_detail = 'Queued to resume.',
                started_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'paused'
            """,
            (now, job_id),
        )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    wake_background_worker()
    return dict_from_row(updated)


def pause_source_import_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if job["job_type"] != "source_import_batch":
            raise ValueError("Only file imports can be paused here")
        if job["status"] == "paused":
            return job
        if job["status"] not in {"queued", "running"}:
            raise ValueError("Only queued or running file imports can be paused")
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'paused',
                status_detail = 'Paused. Files already being processed may still finish.',
                updated_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (now, job_id),
        )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict_from_row(updated)


def resume_source_import_job(job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict_from_row(row)
        if job["job_type"] != "source_import_batch":
            raise ValueError("Only file imports can be resumed here")
        if job["status"] != "paused":
            raise ValueError("Only paused file imports can be resumed")
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'queued', status_detail = 'Import queued to resume.',
                started_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'paused'
            """,
            (now, job_id),
        )
        updated = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    wake_background_worker()
    return dict_from_row(updated)


def _raise_if_job_cancelled(job_id: str | None) -> None:
    if not job_id:
        return
    with connect() as conn:
        row = conn.execute(
            "SELECT status, cancellation_requested FROM app_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None or row["status"] == "cancelled" or int(row["cancellation_requested"] or 0) == 1:
        raise JobCancelled(job_id)


def _acknowledge_job_cancelled(job_id: str) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'cancelled', cancellation_requested = 1,
                status_detail = 'Cancellation acknowledged by worker.',
                completed_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (now, now, job_id),
        )


def _worker_loop() -> None:
    global _LAST_WORKER_LOOP_ERROR
    while True:
        try:
            run_due_jobs_once(limit=3)
        except Exception as exc:
            signature = f"{type(exc).__name__}:{exc}"
            now = time.monotonic()
            last_signature, last_logged_at = _LAST_WORKER_LOOP_ERROR or ("", 0.0)
            if signature != last_signature or now - last_logged_at >= 60:
                logger.exception(
                    "background_worker_loop_failed error_signature=%s",
                    signature[:300],
                )
                _LAST_WORKER_LOOP_ERROR = (signature, now)
        _WORKER_WAKE.wait(timeout=JOB_POLL_SECONDS)
        _WORKER_WAKE.clear()


def _claim_next_job() -> dict | None:
    embeddings_available = bool(embedding_status(probe_model=False).get("available"))
    local_model_available: bool | None = None
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
            if job["job_type"] in LOCAL_MODEL_JOB_TYPES:
                if local_model_available is None:
                    from backend.app.core.llm_runtime import runtime_status

                    local_model_available = bool(runtime_status().get("available"))
                if not local_model_available:
                    conn.execute(
                        """
                        UPDATE app_jobs
                        SET status = 'blocked_setup_required',
                            status_detail = 'Local model unavailable. Waiting to resume document analysis.',
                            updated_at = ?
                        WHERE id = ? AND status = 'queued'
                        """,
                        (utc_now(), job["id"]),
                    )
                    continue
            if job["job_type"] in EMBEDDING_JOB_TYPES and not embeddings_available:
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET status = 'blocked_setup_required',
                        status_detail = 'Set up memory search to continue this task.',
                        updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (utc_now(), job["id"]),
                )
                if job["job_type"] == "reindex_source":
                    payload = _decode_payload(job.get("payload") or "{}")
                    source_id = str(payload.get("source_id") or "")
                    if source_id:
                        publish_source_ingestion_stage(
                            conn,
                            source_id=source_id,
                            stage="paused",
                            generation=int(payload.get("ingestion_generation") or 0) or None,
                            detail="Set up memory search to publish this source.",
                        )
                continue
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
    observation_started = time.perf_counter()
    try:
        _raise_if_job_cancelled(job["id"])
        payload = _decode_payload(job["payload"])
        if job["job_type"] in {
            "project_discover", "project_structure_index", "project_retrieval_stage",
            "project_snapshot_activate", "project_candidate_cleanup",
        }:
            _run_project_phase(job["job_type"], payload, job["id"])
        elif job["job_type"] == "project_delta_probe":
            _run_project_delta_probe(payload, job["id"])
        elif job["job_type"] == "project_delta_apply":
            _run_project_delta_apply(payload, job["id"])
        elif job["job_type"] == "reindex_source":
            _run_reindex_source(payload, job["id"])
        elif job["job_type"] == "source_import_batch":
            _run_source_import_batch(payload, job["id"])
        elif job["job_type"] == "chat_transcript_memory":
            _run_chat_transcript_memory(payload, job["id"])
        elif job["job_type"] == "chat_answer_generation":
            _run_chat_answer_generation(payload, job["id"])
        elif job["job_type"] == "temporal_fact_backfill":
            _run_temporal_fact_backfill(payload, job["id"])
        elif job["job_type"] == "atomic_semantic_enrichment":
            _run_atomic_semantic_enrichment(payload, job["id"])
        elif job["job_type"] == "refresh_cluster_profile":
            _run_refresh_cluster_profile(payload, job["id"])
        elif job["job_type"] == "cluster_profile_backfill":
            _run_cluster_profile_backfill(payload, job["id"])
        elif job["job_type"] == "source_metadata_enrichment":
            _run_source_metadata_enrichment(payload, job["id"])
        elif job["job_type"] == "source_semantic_enrichment":
            _run_source_semantic_enrichment(payload, job["id"])
        elif job["job_type"] == "source_cluster_reconciliation":
            _run_source_cluster_reconciliation(payload, job["id"])
        elif job["job_type"] == "cluster_membership_repair":
            _run_cluster_membership_repair(payload, job["id"])
        elif job["job_type"] == "ocr_source":
            _run_ocr_source(payload, job["id"])
        elif job["job_type"] == "expanded_analysis":
            _run_expanded_analysis(payload, job["id"])
        elif job["job_type"] == "complete_analysis":
            _run_complete_analysis(payload, job["id"])
        elif job["job_type"] == "delete_source_cleanup":
            _run_delete_source_cleanup(payload, job["id"])
        elif job["job_type"] == "vector_reconcile_incremental":
            _run_vector_reconcile_incremental(payload, job["id"])
        elif job["job_type"] == "turbovec_evaluate":
            _run_turbovec_evaluate(payload, job["id"])
        elif job["job_type"] == "model_import":
            _run_model_import(payload, job["id"])
        elif job["job_type"] == "model_discovery":
            _run_model_discovery(payload, job["id"])
        elif job["job_type"] == "model_runtime_recovery":
            _run_model_runtime_recovery(payload, job["id"])
        elif job["job_type"] == "diagnostic_bundle":
            _run_diagnostic_bundle(payload, job["id"])
        elif job["job_type"] == "integration_refresh":
            _run_integration_refresh(payload, job["id"])
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        _raise_if_job_cancelled(job["id"])
    except JobCancelled:
        _acknowledge_job_cancelled(job["id"])
        if job["job_type"] == "source_semantic_enrichment":
            _finalize_source_semantic_wave(_decode_payload(job["payload"]))
        return
    except JobPaused:
        return
    except Exception as exc:
        if job["job_type"] in EMBEDDING_JOB_TYPES and _is_embedding_setup_error(exc):
            _mark_job_blocked_setup(job)
            return
        if job["job_type"] in LOCAL_MODEL_JOB_TYPES and _is_local_model_setup_error(exc):
            _mark_job_blocked_local_model(job, str(exc))
            return
        record_lane_observation(
            job_lane(job["job_type"]),
            success=False,
            latency_ms=(time.perf_counter() - observation_started) * 1000,
            pressure_event=_scheduler_pressure_event(exc),
        )
        _mark_job_failed_or_retry(job, exc)
        if job["job_type"] == "source_semantic_enrichment":
            _finalize_source_semantic_wave(_decode_payload(job["payload"]))
        return

    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'succeeded', completed_at = ?, updated_at = ?, last_error = ''
            WHERE id = ? AND status = 'running' AND cancellation_requested = 0
            """,
            (utc_now(), utc_now(), job["id"]),
        )
    if job["job_type"] == "source_semantic_enrichment":
        _finalize_source_semantic_wave(_decode_payload(job["payload"]))
    record_lane_observation(
        job_lane(job["job_type"]),
        success=True,
        latency_ms=(time.perf_counter() - observation_started) * 1000,
    )


def _run_reindex_source(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    source_id = str(payload["source_id"])
    expected_generation = int(payload.get("ingestion_generation") or 0)
    expected_checksum = str(payload.get("source_checksum") or "")
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return
        source = dict_from_row(row)
        identity = source_ingestion_identity(conn, source_id)
        if identity is None:
            return
        if expected_generation and identity.generation != expected_generation:
            return
        if expected_checksum and identity.checksum != expected_checksum:
            return
        if source.get("deleted_at") or source["state"] != "indexed":
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            return
        publish_source_ingestion_stage(
            conn,
            source_id=source_id,
            stage="extracting",
            generation=identity.generation,
            detail="Publishing searchable source content.",
        )
    require_embeddings_available("Source reindexing")
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return
        source = dict_from_row(row)
        identity = source_ingestion_identity(conn, source_id)
        if identity is None:
            return
        if expected_generation and identity.generation != expected_generation:
            return
        if expected_checksum and identity.checksum != expected_checksum:
            return
        reindex_source_chunks(conn, source)
        _raise_if_job_cancelled(job_id)
        publish_source_ingestion_stage(
            conn,
            source_id=source_id,
            stage="searchable",
            generation=identity.generation,
            detail="Source is searchable. Organization is continuing.",
        )
        enqueue_job(
            conn,
            job_type="source_metadata_enrichment",
            payload={
                "source_id": source_id,
                "source_updated_at": source["updated_at"],
                "ingestion_generation": identity.generation,
                "source_checksum": identity.checksum,
            },
            dedupe_key=(
                f"source-metadata:{source_id}:{source['updated_at']}:"
                f"{identity.job_suffix}"
            ),
            scope_id=source_id,
        )
        if int(source.get("metadata_version") or 1) < 2:
            mark_cluster_metadata_pending(conn, source.get("cluster_id"))
        else:
            mark_cluster_needs_update(conn, source.get("cluster_id"), "Source was indexed in the background.")
        rebuild_source_memory(conn, source_id=source_id)
        _refresh_project_retrieval_status(conn, source_id)


def _run_source_import_batch(payload: dict, job_id: str) -> None:
    from backend.app.api.routes.sources import create_source_from_path
    from backend.app.schemas import SourcePathCreate

    vault_id = str(payload.get("vault_id") or "")
    cluster_id = _optional_string(payload.get("cluster_id"))
    paths = [str(path) for path in payload.get("paths") or [] if str(path)]
    folder_roots = [str(path) for path in payload.get("folder_roots") or [] if str(path)]
    if not vault_id or not paths:
        raise ValueError("Source import job is missing its vault or file paths.")

    progress = _source_import_progress(job_id, payload, len(paths))
    completed_indices = {
        int(index)
        for index in progress.get("completed_indices") or []
        if isinstance(index, int) and 0 <= index < len(paths)
    }
    remaining = (index for index in range(len(paths)) if index not in completed_indices)
    max_workers = source_import_worker_count(len(paths))
    in_flight: dict[object, tuple[int, str]] = {}
    pause_requested = False
    cancellation_requested = False

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        try:
            index = next(remaining)
        except StopIteration:
            return False
        path = paths[index]
        future = executor.submit(
            create_source_from_path,
            SourcePathCreate(vault_id=vault_id, cluster_id=cluster_id, path=path),
        )
        in_flight[future] = (index, path)
        return True

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cml-source-import") as executor:
        while len(in_flight) < max_workers and submit_next(executor):
            pass

        while in_flight:
            completed, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in completed:
                index, path = in_flight.pop(future)
                completed_indices.add(index)
                try:
                    source = future.result()
                    matching_roots: list[tuple[Path, Path]] = []
                    resolved_path = Path(path).resolve()
                    for raw_root in folder_roots:
                        resolved_root = Path(raw_root).resolve()
                        try:
                            relative_path = resolved_path.relative_to(resolved_root)
                        except ValueError:
                            continue
                        matching_roots.append((resolved_root, relative_path))
                    if matching_roots:
                        root, relative_path = max(matching_roots, key=lambda item: len(item[0].parts))
                        with connect() as conn:
                            conn.execute(
                                """
                                UPDATE sources
                                SET import_root_path = ?, import_relative_path = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (str(root), relative_path.as_posix(), utc_now(), source["id"]),
                            )
                    if source.get("import_outcome") == "updated":
                        progress["updated_files"] = int(progress.get("updated_files") or 0) + 1
                    else:
                        progress["imported_files"] = int(progress.get("imported_files") or 0) + 1
                except Exception as exc:
                    progress["failed_files"] = int(progress.get("failed_files") or 0) + 1
                    failed_indices = {
                        int(item)
                        for item in progress.get("failed_indices") or []
                        if isinstance(item, int)
                    }
                    failed_indices.add(index)
                    progress["failed_indices"] = sorted(failed_indices)
                    failures = list(progress.get("failures") or [])
                    if len(failures) < 100:
                        detail = getattr(exc, "detail", None)
                        failures.append(
                            {
                                "file_name": Path(path).name or "File",
                                "reason": str(detail or exc or "Import failed")[:500],
                                "path_index": index,
                            }
                        )
                    progress["failures"] = failures

                progress["completed_indices"] = sorted(completed_indices)
                progress["completed_files"] = len(completed_indices)
                progress["current_file"] = Path(path).name or "File"
                _set_source_import_progress(job_id, progress)

            control = _source_import_control_state(job_id)
            cancellation_requested = cancellation_requested or control in {"cancelled", "cancelling"}
            pause_requested = pause_requested or control == "paused"
            if not pause_requested and not cancellation_requested:
                while len(in_flight) < max_workers and submit_next(executor):
                    pass

    progress["current_file"] = ""
    _set_source_import_progress(job_id, progress)
    if cancellation_requested:
        raise JobCancelled(job_id)
    if pause_requested and len(completed_indices) == len(paths):
        with connect() as conn:
            conn.execute(
                "UPDATE app_jobs SET status = 'running', updated_at = ? WHERE id = ? AND status = 'paused'",
                (utc_now(), job_id),
            )
        pause_requested = False
    if pause_requested:
        raise JobPaused(job_id)
    if int(progress.get("failed_files") or 0) > 0:
        now = utc_now()
        failed_count = int(progress["failed_files"])
        with connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'partial_success',
                    status_detail = ?,
                    completed_at = ?,
                    updated_at = ?,
                    error_code = 'source_import_partial',
                    diagnostic_id = ''
                WHERE id = ? AND status = 'running'
                """,
                (
                    f"Imported {len(paths) - failed_count} of {len(paths)} files. "
                    f"{failed_count} can be retried.",
                    now,
                    now,
                    job_id,
                ),
            )


def _source_import_progress(job_id: str, payload: dict, total_files: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT result_json FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
    try:
        stored = json.loads(str(row["result_json"] if row else "{}"))
    except (TypeError, json.JSONDecodeError):
        stored = {}
    progress = stored if isinstance(stored, dict) else {}
    progress.update(
        {
            "kind": "source_import",
            "total_files": total_files,
            "truncated_at": payload.get("truncated_at"),
        }
    )
    progress.setdefault("completed_files", 0)
    progress.setdefault("imported_files", 0)
    progress.setdefault("updated_files", 0)
    progress.setdefault("failed_files", 0)
    progress.setdefault("failed_indices", [])
    progress.setdefault("failures", [])
    progress.setdefault("completed_indices", [])
    progress.setdefault("current_file", "")
    return progress


def _set_source_import_progress(job_id: str, progress: dict) -> None:
    total = max(1, int(progress.get("total_files") or 1))
    completed = max(0, min(total, int(progress.get("completed_files") or 0)))
    percent = int((completed / total) * 100)
    failed = max(0, int(progress.get("failed_files") or 0))
    detail = f"Processed {completed} of {total} files ({percent}%)."
    if failed:
        detail += f" {failed} failed."
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET result_json = ?, status_detail = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(progress, ensure_ascii=False, separators=(",", ":")),
                detail,
                utc_now(),
                job_id,
            ),
        )


def _source_import_control_state(job_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT status, cancellation_requested FROM app_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None or row["status"] == "cancelled":
        return "cancelled"
    if int(row["cancellation_requested"] or 0) == 1:
        return "cancelling"
    return str(row["status"])


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


def _run_chat_answer_generation(payload: dict, job_id: str | None = None) -> None:
    from backend.app.api.routes.chat import run_durable_chat_generation

    _raise_if_job_cancelled(job_id)
    generation_id = str(payload.get("generation_id") or "")
    if not generation_id:
        raise ValueError("Chat answer task is missing its answer ID.")
    run_durable_chat_generation(
        generation_id,
        expanded_analysis=bool(payload.get("expanded_analysis")),
        complete_analysis=bool(payload.get("complete_analysis")),
    )
    _set_job_result(
        job_id,
        {"generation_id": generation_id},
        detail="Answer saved.",
    )


def _run_chat_transcript_memory(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
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
        _raise_if_job_cancelled(job_id)
        rebuild_chat_session_memory(conn, vault_id=vault_id, session_id=session_id)
        _raise_if_job_cancelled(job_id)
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexed', memory_updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )
        _enqueue_atomic_semantic_enrichment(
            conn,
            vault_id=vault_id,
            session_id=session_id,
        )


def _enqueue_atomic_semantic_enrichment(
    conn,
    *,
    vault_id: str,
    session_id: str,
) -> dict | None:
    from backend.app.core.config import get_settings

    settings = get_settings()
    if not settings.atomic_semantic_enrichment_enabled:
        return None
    contract = str(settings.atomic_semantic_extractor_contract).strip().casefold()
    if contract not in {"v1", "v2_evidence"}:
        raise ValueError("unsupported_atomic_semantic_extractor_contract")
    extractor_version = (
        LOCAL_SEMANTIC_V2_EXTRACTOR_VERSION
        if contract == "v2_evidence"
        else LOCAL_SEMANTIC_EXTRACTOR_VERSION
    )
    extractor_model = (
        settings.atomic_extractor_model
        if contract == "v2_evidence"
        else settings.llm_model
    )
    state = conn.execute(
        "SELECT status, extractor_version, model FROM atomic_memory_semantic_state WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if (
        state is not None
        and state["status"] == "current"
        and state["extractor_version"] == extractor_version
        and state["model"] == extractor_model
    ):
        return None
    return enqueue_job(
        conn,
        job_type="atomic_semantic_enrichment",
        payload={"vault_id": vault_id, "session_id": session_id},
        dedupe_key=(
            f"atomic-semantic:{session_id}:{extractor_version}:"
            f"{extractor_model}:{settings.atomic_semantic_max_source_chars}:"
            f"{settings.atomic_semantic_max_output_tokens}"
        ),
        max_attempts=2,
    )


def _run_atomic_semantic_enrichment(payload: dict, job_id: str) -> None:
    from backend.app.core.config import get_settings
    from backend.app.core.llm_runtime import generate_local_structured_json

    settings = get_settings()
    if not settings.atomic_semantic_enrichment_enabled:
        raise RuntimeError("Local atomic semantic enrichment is disabled")
    vault_id = str(payload.get("vault_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if not vault_id or not session_id:
        raise ValueError("vault_id and session_id are required")
    with connect() as conn:
        session = conn.execute(
            "SELECT id FROM chat_sessions WHERE id = ? AND vault_id = ?",
            (session_id, vault_id),
        ).fetchone()
        if session is None:
            raise ValueError("chat_session_not_found")
        messages = hydrate_chat_message_rows(conn, conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall())
        session_payload = chat_session_atomic_payload(session_id, messages)
    source_hash = atomic_source_content_hash(
        session_payload["session_id"],
        session_payload["date"],
        session_payload["turns"],
    )

    provider_model: dict[str, str] = {}
    contract = str(settings.atomic_semantic_extractor_contract).strip().casefold()
    extractor_version = LOCAL_SEMANTIC_EXTRACTOR_VERSION
    if contract == "v2_evidence":
        window_results = []
        windows = atomic_memory_v2_session_windows(
            session_payload,
            max_source_chars=max(
                int(settings.atomic_semantic_max_source_chars), 1_000
            ),
        )
        for window in windows:
            _raise_if_job_cancelled(job_id)
            result = generate_local_structured_json(
                system_prompt=(
                    "Extract short, durable, question-independent memories as strict JSON. "
                    "Do not think aloud. Do not invent facts. Every memory must include an "
                    "exact contiguous citation from one supplied turn."
                ),
                user_prompt=atomic_memory_v2_evidence_pass_prompt(window),
                model=settings.atomic_extractor_model,
                max_tokens=settings.atomic_semantic_max_output_tokens,
                json_schema=atomic_memory_v2_evidence_pass_json_schema(),
            )
            provider_model.update(provider=result.provider, model=result.model)
            response = AtomicMemoryV2EvidencePassResponse.model_validate_json(
                result.text
            )
            window_extraction, window_invalid = compile_atomic_memory_v2_evidence(
                window, response
            )
            window_results.append((window, window_extraction, window_invalid))
        extraction, invalid_reasons = merge_atomic_memory_v2_evidence_windows(
            session_payload, window_results
        )
        extractor_version = LOCAL_SEMANTIC_V2_EXTRACTOR_VERSION
    elif contract == "v1":
        def extractor(prompt: str) -> tuple[str, dict]:
            result = generate_local_structured_json(
                system_prompt=(
                    "Extract durable conversational memory as one strict JSON object. "
                    "Do not think aloud. Preserve exact citations, speaker attribution, "
                    "modality, named entities, category membership, and coreference only "
                    "when supported by the supplied conversation."
                ),
                user_prompt=prompt,
                model=settings.llm_model,
                json_schema=ATOMIC_EXTRACTION_RESPONSE_SCHEMA,
            )
            provider_model.update(provider=result.provider, model=result.model)
            return result.text, {}

        extraction, invalid_reasons, _ = compile_semantic_atomic_session(
            session_payload,
            extractor=extractor,
            max_source_chars=max(int(settings.atomic_semantic_max_source_chars), 1_000),
        )
    else:
        raise ValueError("unsupported_atomic_semantic_extractor_contract")
    with connect() as conn:
        summary = persist_local_semantic_extraction(
            conn,
            vault_id=vault_id,
            session_id=session_id,
            source_hash=source_hash,
            extraction=extraction,
            invalid_reasons=invalid_reasons,
            provider=provider_model["provider"],
            model=provider_model["model"],
            extractor_version=extractor_version,
        )
        conn.execute(
            "UPDATE app_jobs SET status_detail = ?, updated_at = ? WHERE id = ?",
            (
                f"Stored {summary['fact_count']} validated local semantic facts; "
                f"rejected {summary['invalid_fact_count']} invalid facts.",
                utc_now(),
                job_id,
            ),
        )


def _run_temporal_fact_backfill(payload: dict, job_id: str) -> None:
    vault_id = str(payload.get("vault_id") or "").strip()
    if not vault_id:
        raise ValueError("vault_id is required")
    batch_size = max(1, min(int(payload.get("batch_size") or 50), 200))
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise ValueError("vault_not_found")
        total = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM chat_sessions WHERE vault_id = ?",
                (vault_id,),
            ).fetchone()["count"]
        )

    processed = 0
    updated = 0
    cursor = ""
    while True:
        with connect() as conn:
            job = conn.execute("SELECT status FROM app_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None or job["status"] == "cancelled":
                return
            sessions = conn.execute(
                """
                SELECT id FROM chat_sessions
                WHERE vault_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?
                """,
                (vault_id, cursor, batch_size),
            ).fetchall()
            if not sessions:
                detail = (
                    f"Temporal history is current for {processed} chat sessions."
                    if updated == processed
                    else f"Checked {processed} chat sessions; refreshed {updated} with changed or upgraded history."
                )
                conn.execute(
                    "UPDATE app_jobs SET status_detail = ?, updated_at = ? WHERE id = ?",
                    (detail, utc_now(), job_id),
                )
                return
            for session in sessions:
                _raise_if_job_cancelled(job_id)
                session_id = str(session["id"])
                messages = hydrate_chat_message_rows(conn, conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at, rowid",
                    (session_id,),
                ).fetchall())
                state = conn.execute(
                    "SELECT * FROM temporal_fact_session_state WHERE session_id = ? AND vault_id = ?",
                    (session_id, vault_id),
                ).fetchone()
                atomic_state = conn.execute(
                    "SELECT * FROM atomic_memory_session_state WHERE session_id = ? AND vault_id = ?",
                    (session_id, vault_id),
                ).fetchone()
                source_hash = temporal_fact_source_hash(messages)
                if (
                    state is None
                    or state["extractor_version"] != CHAT_FACT_EXTRACTOR_VERSION
                    or state["source_content_hash"] != source_hash
                    or int(state["source_message_count"] or 0) != len(messages)
                    or atomic_state is None
                    or atomic_state["compiler_version"] != ATOMIC_MEMORY_VERSION
                    or int(atomic_state["source_message_count"] or 0) != len(messages)
                ):
                    sync_chat_session_temporal_facts(
                        conn,
                        vault_id=vault_id,
                        session_id=session_id,
                        messages=messages,
                    )
                    updated += 1
                _enqueue_atomic_semantic_enrichment(
                    conn,
                    vault_id=vault_id,
                    session_id=session_id,
                )
                cursor = session_id
                processed += 1
            conn.execute(
                "UPDATE app_jobs SET status_detail = ?, updated_at = ? WHERE id = ?",
                (f"Checked {processed} of {total} chat sessions; refreshed {updated}.", utc_now(), job_id),
            )


def _run_refresh_cluster_profile(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    cluster_id = str(payload.get("cluster_id") or "")
    if not cluster_id:
        return
    with connect() as conn:
        refresh_cluster_profile(conn, cluster_id, require_model=True)
        _raise_if_job_cancelled(job_id)


def _run_cluster_profile_backfill(payload: dict, job_id: str) -> None:
    vault_id = str(payload.get("vault_id") or "")
    if not vault_id:
        raise ValueError("cluster_profile_backfill_requires_vault")
    attempted_ids: set[str] = set()
    processed_ids: set[str] = set()
    failures: list[dict[str, str]] = []
    while True:
        _raise_if_job_cancelled(job_id)
        with connect() as conn:
            state = conn.execute(
                "SELECT status FROM app_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if state is not None and state["status"] == "paused":
                raise JobPaused(job_id)
            rows = conn.execute(
                """
                SELECT clusters.id, clusters.name
                FROM clusters
                LEFT JOIN cluster_candidate_profiles profiles
                  ON profiles.cluster_id = clusters.id
                WHERE clusters.vault_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM project_cluster_links links
                      WHERE links.cluster_id = clusters.id
                  )
                  AND (
                      (
                          clusters.name_origin = 'auto'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM sources any_source
                              WHERE any_source.cluster_id = clusters.id
                                AND any_source.deleted_at IS NULL
                          )
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM sources profile_source
                          WHERE profile_source.cluster_id = clusters.id
                            AND profile_source.deleted_at IS NULL
                            AND profile_source.state = 'indexed'
                            AND profile_source.source_type <> 'chat_transcript'
                      )
                  )
                  AND (
                      profiles.cluster_id IS NULL
                      OR profiles.source_hash <> clusters.profile_source_hash
                      OR profiles.profile_version <> 1
                      OR profiles.status <> 'ready'
                      OR clusters.profile_status <> 'ready'
                  )
                ORDER BY
                    CASE WHEN profiles.cluster_id IS NULL THEN 0 ELSE 1 END,
                    CASE WHEN clusters.name_origin = 'auto' THEN 0 ELSE 1 END,
                    clusters.updated_at DESC,
                    clusters.id
                LIMIT 20
                """,
                (vault_id,),
            ).fetchall()
        if not rows:
            break
        fresh_rows = [
            row for row in rows if str(row["id"]) not in attempted_ids
        ]
        if not fresh_rows:
            for row in rows:
                cluster_id = str(row["id"])
                if not any(item["cluster_id"] == cluster_id for item in failures):
                    failures.append(
                        {
                            "cluster_id": cluster_id,
                            "cluster_name": str(row["name"]),
                            "reason": "profile_remained_eligible",
                        }
                    )
            break
        for row in fresh_rows:
            _raise_if_job_cancelled(job_id)
            cluster_id = str(row["id"])
            attempted_ids.add(cluster_id)
            with connect() as conn:
                state = conn.execute(
                    "SELECT status FROM app_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if state is not None and state["status"] == "paused":
                    raise JobPaused(job_id)
                try:
                    if not prune_empty_auto_cluster(conn, cluster_id):
                        refresh_cluster_profile(
                            conn,
                            cluster_id,
                            require_model=True,
                        )
                    processed_ids.add(cluster_id)
                except (SemanticModelUnavailable, LLMRuntimeError):
                    raise
                except Exception as exc:
                    failures.append(
                        {
                            "cluster_id": cluster_id,
                            "cluster_name": str(row["name"]),
                            "reason": type(exc).__name__,
                        }
                    )
                    conn.execute(
                        """
                        UPDATE cluster_candidate_profiles
                        SET status = 'failed', updated_at = ?
                        WHERE cluster_id = ?
                        """,
                        (utc_now(), row["id"]),
                    )
                    if len(failures) >= 50:
                        raise RuntimeError("cluster_profile_backfill_failure_limit") from exc
            _set_job_result(
                job_id,
                {"processed": len(processed_ids), "failures": failures},
                detail=(
                    f"Refreshed {len(processed_ids)} unique clusters. "
                    f"{len(failures)} failed."
                ),
            )
    _set_job_result(
        job_id,
        {"processed": len(processed_ids), "failures": failures},
        detail=(
            f"Refreshed {len(processed_ids)} unique clusters."
            if not failures
            else (
                f"Refreshed {len(processed_ids)} unique clusters. "
                f"{len(failures)} need attention."
            )
        ),
    )


def _enqueue_source_metadata_backlog(
    conn,
    *,
    vault_id: str | None = None,
    limit_per_vault: int = 64,
) -> int:
    vault_rows = (
        [{"id": vault_id}]
        if vault_id
        else conn.execute("SELECT id FROM vaults ORDER BY created_at ASC").fetchall()
    )
    enqueued = 0
    active_statuses = (
        "queued", "running", "paused", "blocked_by_dependency",
        "blocked_setup_required", "deferred",
    )
    placeholders = ",".join("?" for _ in active_statuses)
    for vault in vault_rows:
        current_vault_id = str(vault["id"])
        active = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM app_jobs jobs
            JOIN sources ON sources.id = jobs.scope_id
            WHERE jobs.job_type = 'source_metadata_enrichment'
              AND jobs.status IN ({placeholders})
              AND sources.vault_id = ?
              AND sources.deleted_at IS NULL
            """,
            [*active_statuses, current_vault_id],
        ).fetchone()
        queue_limit = max(1, min(int(limit_per_vault), 128))
        available_slots = max(0, queue_limit - int(active["count"] or 0))
        if available_slots == 0:
            continue
        sources = conn.execute(
            f"""
            SELECT sources.id, sources.updated_at
            FROM sources
            WHERE sources.vault_id = ?
              AND sources.deleted_at IS NULL
              AND sources.state = 'indexed'
              AND sources.metadata_version < ?
              AND NOT EXISTS (
                  SELECT 1 FROM app_jobs jobs
                  WHERE jobs.job_type = 'source_metadata_enrichment'
                    AND jobs.scope_id = sources.id
                    AND jobs.status IN ({placeholders})
              )
            ORDER BY sources.updated_at ASC, sources.id ASC
            LIMIT ?
            """,
            [
                current_vault_id,
                SOURCE_METADATA_VERSION,
                *active_statuses,
                available_slots,
            ],
        ).fetchall()
        for source in sources:
            enqueue_job(
                conn,
                job_type="source_metadata_enrichment",
                payload={
                    "source_id": source["id"],
                    "source_updated_at": source["updated_at"],
                },
                dedupe_key=f"source-metadata:{source['id']}:{source['updated_at']}",
                scope_id=str(source["id"]),
            )
            enqueued += 1
        ready_unclustered = conn.execute(
            """
            SELECT id, updated_at
            FROM sources
            WHERE vault_id = ? AND deleted_at IS NULL AND state = 'indexed'
              AND cluster_id IS NULL AND metadata_version >= ?
            ORDER BY updated_at ASC, id ASC
            LIMIT ?
            """,
            (current_vault_id, SOURCE_METADATA_VERSION, max(1, available_slots or 16)),
        ).fetchall()
        for source in ready_unclustered:
            enqueue_job(
                conn,
                job_type="source_cluster_reconciliation",
                payload={
                    "vault_id": current_vault_id,
                    "source_id": str(source["id"]),
                    "metadata_version": SOURCE_METADATA_VERSION,
                },
                dedupe_key=(
                    f"source-cluster-reconciliation:{source['id']}:"
                    f"{source['updated_at']}:v{SOURCE_METADATA_VERSION}"
                ),
                scope_id=current_vault_id,
                user_initiated=False,
            )
        enqueued += _enqueue_source_semantic_backlog(
            conn,
            vault_id=current_vault_id,
            limit_per_vault=max(4, min(queue_limit // 2, 16)),
        )
    return enqueued


def _enqueue_source_semantic_backlog(
    conn,
    *,
    vault_id: str,
    limit_per_vault: int = 16,
) -> int:
    active_statuses = (
        "queued", "running", "paused", "blocked_by_dependency",
        "blocked_setup_required", "deferred",
    )
    placeholders = ",".join("?" for _ in active_statuses)
    active = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM app_jobs jobs
        JOIN sources ON sources.id = jobs.scope_id
        WHERE jobs.job_type = 'source_semantic_enrichment'
          AND jobs.status IN ({placeholders})
          AND sources.vault_id = ?
          AND sources.deleted_at IS NULL
        """,
        [*active_statuses, vault_id],
    ).fetchone()
    queue_limit = max(1, min(int(limit_per_vault), 32))
    available = max(0, queue_limit - int(active["count"] or 0))
    if available == 0:
        return 0
    rows = conn.execute(
        f"""
        SELECT sources.id, sources.updated_at
        FROM sources
        WHERE sources.vault_id = ?
          AND sources.deleted_at IS NULL
          AND sources.state = 'indexed'
          AND sources.metadata_version >= ?
          AND sources.semantic_metadata_version < ?
          AND NOT EXISTS (
              SELECT 1 FROM app_jobs jobs
              WHERE jobs.job_type = 'source_semantic_enrichment'
                AND jobs.scope_id = sources.id
                AND jobs.status IN ({placeholders})
          )
        ORDER BY sources.updated_at ASC, sources.id ASC
        LIMIT ?
        """,
        [
            vault_id,
            SOURCE_METADATA_VERSION,
            SOURCE_SEMANTIC_METADATA_VERSION,
            *active_statuses,
            available,
        ],
    ).fetchall()
    for source in rows:
        enqueue_job(
            conn,
            job_type="source_semantic_enrichment",
            payload={"source_id": source["id"]},
            dedupe_key=(
                f"source-semantic:{source['id']}:{source['updated_at']}:"
                f"v{SOURCE_SEMANTIC_METADATA_VERSION}"
            ),
            scope_id=str(source["id"]),
            user_initiated=False,
        )
    return len(rows)


def _run_source_metadata_enrichment(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    source_id = str(payload.get("source_id") or "")
    expected_updated_at = str(payload.get("source_updated_at") or "")
    expected_generation = int(payload.get("ingestion_generation") or 0)
    expected_checksum = str(payload.get("source_checksum") or "")
    if not source_id:
        return
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if row is None:
            return
        if expected_updated_at and row["updated_at"] != expected_updated_at:
            enqueue_job(
                conn,
                job_type="source_metadata_enrichment",
                payload={
                    "source_id": source_id,
                    "source_updated_at": row["updated_at"],
                },
                dedupe_key=f"source-metadata:{source_id}:{row['updated_at']}",
                scope_id=source_id,
            )
            return
        identity = source_ingestion_identity(conn, source_id)
        if identity is None:
            return
        if expected_generation and identity.generation != expected_generation:
            return
        if expected_checksum and identity.checksum != expected_checksum:
            return
        source = dict_from_row(row)
        encrypted = load_source_content_fields(
            conn,
            vault_id=str(source["vault_id"]),
            source_id=source_id,
            fields=("raw_text", "extracted_text", "summary", "tags"),
        )
        source.update({key: value for key, value in encrypted.items() if value})
    text = str(source.get("extracted_text") or source.get("raw_text") or "")
    metadata = enrich_source_metadata(
        title=str(source.get("title") or "Document"),
        source_type=str(source.get("source_type") or "file"),
        text=text,
        require_model=False,
        allow_model=False,
    )
    _raise_if_job_cancelled(job_id)
    existing_tags = _json_string_list(source.get("tags"))
    generated_tags = [
        str(item).strip()
        for item in metadata.get("keywords", [])
        if str(item).strip()
    ]
    tags = list(dict.fromkeys([*existing_tags, *generated_tags]))[:12]
    now = utc_now()
    with connect() as conn:
        current = conn.execute(
            """
            SELECT updated_at, vault_id, cluster_id, ingestion_generation, checksum
            FROM sources WHERE id = ? AND deleted_at IS NULL
            """,
            (source_id,),
        ).fetchone()
        if current is None or current["updated_at"] != source["updated_at"]:
            return
        current_generation = max(1, int(current["ingestion_generation"] or 1))
        if expected_generation and current_generation != expected_generation:
            return
        if expected_checksum and str(current["checksum"] or "") != expected_checksum:
            return
        stored = update_source_content_fields(
            conn,
            vault_id=str(current["vault_id"]),
            source_id=source_id,
            updates={
                "summary": str(metadata.get("summary") or ""),
                "tags": json.dumps(tags, ensure_ascii=False),
            },
            now=now,
        )
        conn.execute(
            """
            UPDATE sources
            SET summary = ?, tags = ?, metadata_version = ?,
                metadata_quality = CASE
                    WHEN semantic_metadata_version >= ? THEN metadata_quality
                    ELSE 'fallback'
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                stored["summary"],
                stored["tags"],
                SOURCE_METADATA_VERSION,
                SOURCE_SEMANTIC_METADATA_VERSION,
                now,
                source_id,
            ),
        )
        enqueue_job(
            conn,
            job_type="source_semantic_enrichment",
            payload={
                "source_id": source_id,
                "source_content_hash": content_hash(text),
                "ingestion_generation": current_generation,
                "source_checksum": str(current["checksum"] or ""),
            },
            dedupe_key=(
                f"source-semantic:{source_id}:{content_hash(text)}:"
                f"v{SOURCE_SEMANTIC_METADATA_VERSION}:g{current_generation}"
            ),
            scope_id=source_id,
            user_initiated=False,
        )
        remaining = conn.execute(
            """
            SELECT 1 FROM sources
            WHERE cluster_id = ?
              AND deleted_at IS NULL
              AND state = 'indexed'
              AND metadata_version < ?
            LIMIT 1
            """,
            (current["cluster_id"], SOURCE_METADATA_VERSION),
        ).fetchone()
        if remaining is None:
            mark_cluster_needs_update(conn, current["cluster_id"], "Source description was refreshed.")
        else:
            mark_cluster_metadata_pending(conn, current["cluster_id"])
        if current["cluster_id"] is None:
            publish_source_ingestion_stage(
                conn,
                source_id=source_id,
                stage="organizing",
                generation=current_generation,
                detail="Source is searchable and is being organized.",
            )
            enqueue_job(
                conn,
                job_type="source_cluster_reconciliation",
                payload={
                    "vault_id": str(current["vault_id"]),
                    "source_id": source_id,
                    "metadata_version": SOURCE_METADATA_VERSION,
                    "ingestion_generation": current_generation,
                    "source_checksum": str(current["checksum"] or ""),
                },
                dedupe_key=f"source-cluster-reconciliation:{source_id}:{now}:v{SOURCE_METADATA_VERSION}",
                scope_id=str(current["vault_id"]),
                user_initiated=False,
            )
        else:
            publish_source_ingestion_stage(
                conn,
                source_id=source_id,
                stage="ready",
                generation=current_generation,
                detail="Source is searchable and organized.",
            )
        _enqueue_source_metadata_backlog(
            conn,
            vault_id=str(current["vault_id"]),
        )


def _run_source_semantic_enrichment(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    source_id = str(payload.get("source_id") or "")
    expected_hash = str(payload.get("source_content_hash") or "")
    expected_generation = int(payload.get("ingestion_generation") or 0)
    expected_checksum = str(payload.get("source_checksum") or "")
    if not source_id:
        return
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        if row is None:
            return
        identity = source_ingestion_identity(conn, source_id)
        if identity is None:
            return
        if expected_generation and identity.generation != expected_generation:
            return
        if expected_checksum and identity.checksum != expected_checksum:
            return
        publish_source_ingestion_stage(
            conn,
            source_id=source_id,
            stage="describing",
            generation=identity.generation,
            detail="Improving the source description.",
        )
        source = dict_from_row(row)
        encrypted = load_source_content_fields(
            conn,
            vault_id=str(source["vault_id"]),
            source_id=source_id,
            fields=("raw_text", "extracted_text", "summary", "tags"),
        )
        source.update({key: value for key, value in encrypted.items() if value})
    text = str(source.get("extracted_text") or source.get("raw_text") or "")
    current_hash = content_hash(text)
    if expected_hash and expected_hash != current_hash:
        with connect() as conn:
            enqueue_job(
                conn,
                job_type="source_semantic_enrichment",
                payload={"source_id": source_id, "source_content_hash": current_hash},
                dedupe_key=(
                    f"source-semantic:{source_id}:{current_hash}:"
                    f"v{SOURCE_SEMANTIC_METADATA_VERSION}"
                ),
                scope_id=source_id,
            )
        return
    if not text.strip():
        return
    metadata = enrich_source_metadata(
        title=str(source.get("title") or "Document"),
        source_type=str(source.get("source_type") or "file"),
        text=text,
        require_model=True,
        allow_model=True,
    )
    _raise_if_job_cancelled(job_id)
    generated_tags = [
        str(item).strip()
        for item in metadata.get("keywords", [])
        if str(item).strip()
    ]
    existing_tags = _json_string_list(source.get("tags"))
    tags = list(dict.fromkeys([*generated_tags, *existing_tags]))[:12]
    now = utc_now()
    with connect() as conn:
        current = conn.execute(
            """
            SELECT vault_id, cluster_id, raw_text, extracted_text
            FROM sources WHERE id = ? AND deleted_at IS NULL
            """,
            (source_id,),
        ).fetchone()
        if current is None:
            return
        latest_content = load_source_content_fields(
            conn,
            vault_id=str(current["vault_id"]),
            source_id=source_id,
            fields=("raw_text", "extracted_text"),
        )
        latest_text = str(
            latest_content.get("extracted_text")
            or latest_content.get("raw_text")
            or current["extracted_text"]
            or current["raw_text"]
            or ""
        )
        if content_hash(latest_text) != current_hash:
            enqueue_job(
                conn,
                job_type="source_semantic_enrichment",
                payload={
                    "source_id": source_id,
                    "source_content_hash": content_hash(latest_text),
                },
                dedupe_key=(
                    f"source-semantic:{source_id}:{content_hash(latest_text)}:"
                    f"v{SOURCE_SEMANTIC_METADATA_VERSION}"
                ),
                scope_id=source_id,
            )
            return
        current_identity = source_ingestion_identity(conn, source_id)
        if current_identity is None:
            return
        if expected_generation and current_identity.generation != expected_generation:
            return
        if expected_checksum and current_identity.checksum != expected_checksum:
            return
        stored = update_source_content_fields(
            conn,
            vault_id=str(current["vault_id"]),
            source_id=source_id,
            updates={
                "summary": str(metadata.get("summary") or source.get("summary") or ""),
                "tags": json.dumps(tags, ensure_ascii=False),
            },
            now=now,
        )
        conn.execute(
            """
            UPDATE sources
            SET summary = ?, tags = ?, metadata_quality = 'semantic',
                semantic_metadata_version = ?, semantic_metadata_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                stored["summary"],
                stored["tags"],
                SOURCE_SEMANTIC_METADATA_VERSION,
                now,
                now,
                source_id,
            ),
        )
        cluster_id = str(current["cluster_id"] or "")
        if cluster_id:
            # A large import may have hundreds of source-description jobs sharing
            # one local model with cluster-profile generation. Rebuilding the
            # same profile after every source both duplicates work and starves
            # the remaining descriptions. Keep the cluster visibly stale and
            # publish one profile refresh after the enrichment wave drains.
            mark_cluster_metadata_pending(conn, cluster_id)
        else:
            enqueue_job(
                conn,
                job_type="source_cluster_reconciliation",
                payload={
                    "vault_id": str(current["vault_id"]),
                    "source_id": source_id,
                    "metadata_version": SOURCE_METADATA_VERSION,
                },
                dedupe_key=(
                    f"source-cluster-reconciliation:{source_id}:{now}:"
                    f"semantic-v{SOURCE_SEMANTIC_METADATA_VERSION}"
                ),
                scope_id=str(current["vault_id"]),
            )
        publish_source_ingestion_stage(
            conn,
            source_id=source_id,
            stage="ready",
            generation=current_identity.generation,
            detail="Source is searchable, organized, and described.",
        )
        _enqueue_source_semantic_backlog(
            conn,
            vault_id=str(current["vault_id"]),
        )


def _finalize_source_semantic_wave(payload: dict) -> bool:
    source_id = str(payload.get("source_id") or "")
    if not source_id:
        return False
    with connect() as conn:
        source = conn.execute(
            """
            SELECT sources.cluster_id, clusters.vault_id, clusters.profile_status
            FROM sources
            LEFT JOIN clusters ON clusters.id = sources.cluster_id
            WHERE sources.id = ? AND sources.deleted_at IS NULL
            """,
            (source_id,),
        ).fetchone()
        if (
            source is None
            or not source["cluster_id"]
            or str(source["profile_status"] or "") != "stale"
        ):
            return False
        return _enqueue_cluster_profile_after_semantic_wave(
            conn,
            cluster_id=str(source["cluster_id"]),
            vault_id=str(source["vault_id"]),
        )


def _enqueue_cluster_profile_after_semantic_wave(
    conn,
    *,
    cluster_id: str,
    vault_id: str,
) -> bool:
    """Coalesce per-source invalidations into one cluster-profile refresh."""
    active_statuses = (
        "queued",
        "running",
        "paused",
        "blocked_by_dependency",
        "blocked_setup_required",
        "deferred",
    )
    placeholders = ",".join("?" for _ in active_statuses)
    params: list[object] = [*active_statuses, cluster_id]
    remaining = conn.execute(
        f"""
        SELECT 1
        FROM app_jobs jobs
        JOIN sources ON sources.id = jobs.scope_id
        WHERE jobs.job_type = 'source_semantic_enrichment'
          AND jobs.status IN ({placeholders})
          AND sources.cluster_id = ?
          AND sources.deleted_at IS NULL
        LIMIT 1
        """,
        params,
    ).fetchone()
    if remaining is not None:
        return False
    enqueue_job(
        conn,
        job_type="refresh_cluster_profile",
        payload={"cluster_id": cluster_id, "vault_id": vault_id},
        dedupe_key=f"refresh-cluster-profile:{cluster_id}",
        scope_id=cluster_id,
    )
    return True


def _run_source_cluster_reconciliation(payload: dict, job_id: str | None = None) -> None:
    from backend.app.core.clustering import (
        assign_or_create_cluster,
        create_auto_cluster,
        group_related_unclustered_sources,
        keywords_for_text,
    )

    _raise_if_job_cancelled(job_id)
    vault_id = str(payload.get("vault_id") or "")
    source_id = str(payload.get("source_id") or "")
    expected_generation = int(payload.get("ingestion_generation") or 0)
    expected_checksum = str(payload.get("source_checksum") or "")
    if not vault_id:
        raise ValueError("source_cluster_reconciliation_requires_vault")
    batch_size = max(2, min(int(payload.get("batch_size") or 1000), 1000))
    with connect() as conn:
        source_clause = "AND id = ?" if source_id else ""
        params: list[object] = [vault_id, SOURCE_METADATA_VERSION]
        if source_id:
            params.append(source_id)
        params.append(batch_size)
        rows = conn.execute(
            f"""
            SELECT *
            FROM sources
            WHERE vault_id = ? AND deleted_at IS NULL AND state = 'indexed'
              AND cluster_id IS NULL AND metadata_version >= ?
              {source_clause}
            ORDER BY updated_at ASC, id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        sources: list[dict] = []
        for row in rows:
            source = dict_from_row(row)
            if source_id:
                current_generation = max(1, int(source.get("ingestion_generation") or 1))
                if expected_generation and current_generation != expected_generation:
                    continue
                if expected_checksum and str(source.get("checksum") or "") != expected_checksum:
                    continue
            encrypted = load_source_content_fields(
                conn,
                vault_id=vault_id,
                source_id=str(source["id"]),
                fields=("summary", "extracted_text", "raw_text", "tags"),
            )
            source.update({key: value for key, value in encrypted.items() if value})
            sources.append(source)

        assigned: dict[str, list[str]] = {}
        unmatched: list[dict] = []
        for source in sources:
            _raise_if_job_cancelled(job_id)
            text = str(
                source.get("summary")
                or source.get("extracted_text")
                or source.get("raw_text")
                or ""
            )
            cluster_id = assign_or_create_cluster(
                conn,
                vault_id=vault_id,
                title=str(source.get("title") or "Document"),
                text=f"{text} {source.get('tags') or ''}",
            )
            if cluster_id:
                assigned.setdefault(cluster_id, []).append(str(source["id"]))
            else:
                unmatched.append(source)

        grouped_ids: set[str] = set()
        for group in group_related_unclustered_sources(unmatched):
            combined = " ".join(
                f"{source.get('title') or ''} {source.get('summary') or ''} {source.get('tags') or ''}"
                for source in group
            )
            cluster_id = create_auto_cluster(
                conn,
                vault_id=vault_id,
                title=str(group[0].get("title") or "Documents"),
                keywords=keywords_for_text(combined, limit=8),
            )
            source_ids = [str(source["id"]) for source in group]
            assigned.setdefault(cluster_id, []).extend(source_ids)
            grouped_ids.update(source_ids)

        for cluster_id, source_ids in assigned.items():
            for source_id in dict.fromkeys(source_ids):
                move_source_cluster_membership(
                    conn,
                    source_id=source_id,
                    target_cluster_id=cluster_id,
                    reason="Newly analyzed source was organized.",
                    actor="automatic_cluster_reconciliation",
                    expected_vault_id=vault_id,
                    only_if_unclustered=True,
                )
            mark_cluster_needs_update(
                conn,
                cluster_id,
                "Newly analyzed sources were organized into this cluster.",
            )
        remaining = max(0, len(sources) - sum(len(set(ids)) for ids in assigned.values()))
        result = {
            "sources_checked": len(sources),
            "sources_clustered": len(sources) - remaining,
            "sources_left_unclustered": remaining,
            "clusters_updated": len(assigned),
            "new_groups_created": len(
                {
                    cluster_id
                    for cluster_id, ids in assigned.items()
                    if any(source_id in grouped_ids for source_id in ids)
                }
            ),
        }
        for source in sources:
            publish_source_ingestion_stage(
                conn,
                source_id=str(source["id"]),
                stage="ready",
                generation=max(1, int(source.get("ingestion_generation") or 1)),
                detail=(
                    "Source is searchable and organized."
                    if str(source["id"]) in {
                        item
                        for source_ids in assigned.values()
                        for item in source_ids
                    }
                    else "Source is searchable. No confident cluster match was found."
                ),
            )
    _set_job_result(
        job_id,
        result,
        detail=(
            f"Organized {result['sources_clustered']} of {result['sources_checked']} analyzed sources. "
            f"{result['sources_left_unclustered']} still need a clearer match."
        ),
    )


def _run_cluster_membership_repair(payload: dict, job_id: str | None = None) -> None:
    vault_id = str(payload.get("vault_id") or "")
    if not vault_id:
        raise ValueError("cluster_membership_repair_requires_vault")
    batch_size = max(1, min(int(payload.get("batch_size") or 100), 500))
    cursor = str(payload.get("after_source_id") or "") or None
    totals = {
        "sources_checked": int(payload.get("sources_checked") or 0),
        "sources_mismatched": int(payload.get("sources_mismatched") or 0),
        "chunks_mismatched": int(payload.get("chunks_mismatched") or 0),
        "sources_repaired": int(payload.get("sources_repaired") or 0),
        "chunks_repaired": int(payload.get("chunks_repaired") or 0),
    }
    while True:
        _raise_if_job_cancelled(job_id)
        with connect() as conn:
            batch = repair_cluster_membership_batch(
                conn,
                vault_id=vault_id,
                after_source_id=cursor,
                limit=batch_size,
                dry_run=False,
                actor="startup_membership_repair" if not payload.get("user_initiated") else "user_membership_repair",
            )
            for key in totals:
                totals[key] += int(batch.get(key) or 0)
            cursor = batch.get("next_cursor")
            checkpoint_payload = {
                "vault_id": vault_id,
                "batch_size": batch_size,
                "after_source_id": cursor,
                **totals,
            }
            if job_id:
                conn.execute(
                    """
                    UPDATE app_jobs
                    SET payload = ?, result_json = ?, status_detail = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(checkpoint_payload, separators=(",", ":")),
                        json.dumps(totals, separators=(",", ":")),
                        (
                            f"Checked {totals['sources_checked']} sources. "
                            f"Repaired {totals['chunks_repaired']} chunk memberships."
                        ),
                        utc_now(),
                        job_id,
                    ),
                )
        if not cursor:
            break
    _set_job_result(
        job_id,
        {**totals, "vault_id": vault_id, "complete": True},
        detail=(
            f"Checked {totals['sources_checked']} sources and repaired "
            f"{totals['chunks_repaired']} chunk memberships."
        ),
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
            _raise_if_job_cancelled(job_id)
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
        summary = fallback_source_summary(title=title or source["title"], text=text)
        tags = json.dumps(
            generate_tags(title or source["title"], text, str(source["source_type"])),
            ensure_ascii=False,
        )
        stored_updates = update_source_content_fields(
            conn,
            vault_id=source["vault_id"],
            source_id=source_id,
            updates={
                "raw_text": text,
                "extracted_text": text,
                "summary": summary,
                "tags": tags,
            },
            now=now,
        )
        conn.execute(
            """
            UPDATE sources
            SET title = ?, raw_text = ?, extracted_text = ?, summary = ?, tags = ?,
                metadata_version = 1, state = 'indexed', updated_at = ?
                WHERE id = ?
            """,
            (
                title or source["title"],
                stored_updates["raw_text"],
                stored_updates["extracted_text"],
                stored_updates["summary"],
                stored_updates["tags"],
                now,
                source_id,
            ),
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None:
            reindex_source_chunks(conn, dict_from_row(row))
            _raise_if_job_cancelled(job_id)
            mark_cluster_metadata_pending(conn, row["cluster_id"])
            enqueue_job(
                conn,
                job_type="source_metadata_enrichment",
                payload={"source_id": source_id, "source_updated_at": now},
                dedupe_key=f"source-metadata:{source_id}:{now}",
                scope_id=source_id,
            )


def _json_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


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
            _raise_if_job_cancelled(job_id)
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


def _run_delete_source_cleanup(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
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


def _enqueue_due_project_delta_jobs() -> None:
    cutoff = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM projects
            WHERE deleted_at IS NULL
              AND auto_sync_enabled = 1
              AND (last_change_checked_at IS NULL OR last_change_checked_at <= ?)
            ORDER BY COALESCE(last_change_checked_at, created_at), id
            LIMIT 25
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            enqueue_job(
                conn,
                job_type="project_delta_probe",
                payload={"project_id": row["id"]},
                dedupe_key=f"project-delta-probe:{row['id']}",
                scope_id=str(row["id"]),
            )


def _run_project_delta_probe(payload: dict, job_id: str | None = None) -> None:
    from backend.app.core.projects import probe_project_changes

    _raise_if_job_cancelled(job_id)
    project_id = str(payload.get("project_id") or "")
    if not project_id:
        raise ValueError("Project change check is missing its project.")
    result = probe_project_changes(project_id)
    _set_job_result(
        job_id,
        result,
        detail=(
            "Project changes were found and synchronization was queued."
            if result["changed"]
            else "Project files are current."
        ),
    )


def _run_project_delta_apply(payload: dict, job_id: str) -> None:
    from backend.app.core.project_indexing import apply_project_delta

    _raise_if_job_cancelled(job_id)
    apply_project_delta(
        project_id=str(payload["project_id"]),
        run_id=str(payload["run_id"]),
        snapshot_id=str(payload["candidate_snapshot_id"]),
        job_id=job_id,
        changed_paths=[
            str(path)
            for path in payload.get("changed_paths", [])
            if str(path or "").strip()
        ],
    )


def _run_vector_reconcile_incremental(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
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


def _run_model_import(payload: dict, job_id: str | None = None) -> None:
    from backend.app.core.model_registry import import_model_checkpoint

    source_path = str(payload.get("path") or "")
    name = str(payload.get("name") or "").strip() or None
    if not source_path:
        raise ValueError("Model import requires a source path.")

    def update_progress(copied_bytes: int, total_bytes: int) -> None:
        _raise_if_job_cancelled(job_id)
        percent = round((copied_bytes / total_bytes) * 100, 2) if total_bytes else 100.0
        with connect() as conn:
            _update_job_progress(
                conn,
                str(job_id),
                {
                    "phase": "copying",
                    "bytes_copied": copied_bytes,
                    "bytes_total": total_bytes,
                    "progress_percent": percent,
                },
            )

    imported = import_model_checkpoint(
        source_path,
        name=name,
        progress_callback=update_progress,
        cancellation_callback=lambda: _raise_if_job_cancelled(job_id),
    )
    with connect() as conn:
        _update_job_progress(
            conn,
            str(job_id),
            {
                "phase": "complete",
                "progress_percent": 100.0,
                "model_id": imported["id"],
                "model_name": imported["name"],
                "local_path": imported["local_path"],
            },
        )


def _set_job_result(job_id: str | None, result: dict, *, detail: str) -> None:
    if not job_id:
        return
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET result_json = ?, status_detail = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(result, separators=(",", ":"), ensure_ascii=False),
                detail[:500],
                utc_now(),
                job_id,
            ),
        )


def _run_model_discovery(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    from backend.app.core.model_registry import discover_installed_models

    def update_progress(progress: dict) -> None:
        _raise_if_job_cancelled(job_id)
        if not job_id:
            return
        with connect() as conn:
            _update_job_progress(conn, job_id, progress)

    result = discover_installed_models(
        max_results=max(1, min(int(payload.get("max_results") or 32), 200)),
        include_rejected=bool(payload.get("include_rejected")),
        refresh=True,
        progress_callback=update_progress,
        cancellation_callback=lambda: _raise_if_job_cancelled(job_id),
        scan_all_drives=bool(payload.get("scan_all_drives")),
    )
    _raise_if_job_cancelled(job_id)
    _set_job_result(
        job_id,
        result,
        detail=f"Found {len(result.get('models') or [])} compatible local models.",
    )


def _run_model_runtime_recovery(payload: dict, job_id: str | None = None) -> None:
    from backend.app.core.model_registry import (
        activate_model_runtime,
        active_chat_model_status,
        discover_installed_models,
        list_models,
    )

    _raise_if_job_cancelled(job_id)
    discovery = discover_installed_models(
        max_results=200,
        include_rejected=False,
        refresh=True,
        progress_callback=lambda progress: _update_recovery_scan_progress(job_id, progress),
        cancellation_callback=lambda: _raise_if_job_cancelled(job_id),
    )
    _raise_if_job_cancelled(job_id)
    active_model = active_chat_model_status()
    candidates = []
    if active_model:
        candidates.append(active_model)
    candidates.extend(
        model
        for model in list_models()
        if not active_model or model.get("id") != active_model.get("id")
    )
    compatible = [
        model
        for model in candidates
        if model.get("installed")
        and model.get("local_path")
        and bool((model.get("compatibility") or {}).get("chat_role_accepted"))
    ]
    if not compatible:
        raise RuntimeError(
            "No installed model can run chat. Open Models and choose a compatible GGUF model."
        )
    activation_errors: list[str] = []
    activated = None
    for model in compatible:
        try:
            activated = activate_model_runtime(str(model["id"]), role="chat")
            break
        except ValueError as exc:
            activation_errors.append(str(exc))
    if activated is None:
        raise RuntimeError(
            activation_errors[-1]
            if activation_errors
            else "No installed model could be started."
        )
    _raise_if_job_cancelled(job_id)
    notify_local_model_prerequisite_changed()
    _set_job_result(
        job_id,
        {
            "model_id": activated["id"],
            "model_name": activated["name"],
            "scanned_root_count": int(discovery.get("scanned_root_count") or 0),
            "compatible_model_count": int(discovery.get("compatible_model_count") or 0),
            "reason": str(payload.get("reason") or "runtime_unavailable"),
        },
        detail="The local model was found, restarted, and queued document analysis resumed.",
    )


def _update_recovery_scan_progress(job_id: str | None, progress: dict) -> None:
    if not job_id:
        return
    with connect() as conn:
        _update_job_progress(
            conn,
            job_id,
            {
                **progress,
                "phase": "scanning_for_selected_model",
            },
        )


def _run_diagnostic_bundle(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    from backend.app.api.routes.diagnostics import create_diagnostic_bundle

    result = create_diagnostic_bundle()
    _raise_if_job_cancelled(job_id)
    _set_job_result(job_id, result, detail="Diagnostic bundle is ready.")


def _run_integration_refresh(payload: dict, job_id: str | None = None) -> None:
    _raise_if_job_cancelled(job_id)
    from backend.app.api.routes.integrations import refresh_integration_import

    import_id = str(payload.get("import_id") or "")
    if not import_id:
        raise RuntimeError("Integration refresh job requires import_id.")
    result = refresh_integration_import(
        import_id,
        import_files=bool(payload.get("import_files", True)),
        tombstone_missing=bool(payload.get("tombstone_missing", True)),
        trigger_source=str(payload.get("trigger_source") or "watch_refresh"),
    )
    _raise_if_job_cancelled(job_id)
    _set_job_result(job_id, result, detail="Integration refresh is complete.")


def _mark_job_failed_or_retry(job: dict, error: Exception | str) -> None:
    raw_error = str(error)
    diagnostic_id = f"jobdiag-{uuid4()}"
    error_code = f"{str(job.get('job_type') or 'job')}_failed"[:96]
    if isinstance(error, Exception):
        logger.error(
            "background_job_failed diagnostic_id=%s job_id=%s job_type=%s attempt=%s",
            diagnostic_id,
            job.get("id"),
            job.get("job_type"),
            job.get("attempts"),
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.error(
            "background_job_failed diagnostic_id=%s job_id=%s job_type=%s attempt=%s detail=%r",
            diagnostic_id,
            job.get("id"),
            job.get("job_type"),
            job.get("attempts"),
            raw_error,
        )
    with connect() as conn:
        current = conn.execute(
            "SELECT attempts, max_attempts, cancellation_requested FROM app_jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
        if current is not None and int(current["cancellation_requested"] or 0) == 1:
            now = utc_now()
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'cancelled', status_detail = 'Cancellation acknowledged by worker.',
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job["id"]),
            )
            return
        attempts = int(current["attempts"] if current is not None else job.get("attempts") or 0)
        max_attempts = int(current["max_attempts"] if current is not None else job.get("max_attempts") or 3)
        status = "failed" if attempts >= max_attempts else "queued"
        completed_at = utc_now() if status == "failed" else None
        public_detail = (
            "This task needs attention."
            if status == "failed"
            else "Vault will retry this task."
        )
        conn.execute(
            """
            UPDATE app_jobs
            SET status = ?, last_error = ?, error_code = ?, diagnostic_id = ?,
                status_detail = ?,
                completed_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                status,
                raw_error[:500],
                error_code,
                diagnostic_id,
                public_detail,
                completed_at,
                utc_now(),
                job["id"],
            ),
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
        if status == "failed" and job.get("job_type") == "reindex_source":
            payload = _decode_payload(job.get("payload") or "{}")
            source_id = str(payload.get("source_id") or "")
            if source_id:
                publish_source_ingestion_stage(
                    conn,
                    source_id=source_id,
                    stage="needs_attention",
                    generation=int(payload.get("ingestion_generation") or 0) or None,
                    detail="Search publication failed. Retry this source.",
                    error_code=error_code,
                )
        elif status == "failed" and job.get("job_type") == "source_semantic_enrichment":
            payload = _decode_payload(job.get("payload") or "{}")
            source_id = str(payload.get("source_id") or "")
            if source_id:
                publish_source_ingestion_stage(
                    conn,
                    source_id=source_id,
                    stage="ready",
                    generation=int(payload.get("ingestion_generation") or 0) or None,
                    detail="Source is ready with its fallback description.",
                )


def _decode_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _scheduler_pressure_event(error: Exception) -> str:
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    if isinstance(error, MemoryError) or "out of memory" in message or "cuda oom" in message:
        return "oom"
    if "context" in message and ("limit" in message or "length" in message):
        return "context_limit"
    if "locked" in message and ("database" in message or "sqlite" in message):
        return "database_lock"
    if "runtime" in name or "runtime" in message:
        return "runtime_reset"
    return ""


def _is_embedding_setup_error(error: Exception) -> bool:
    message = str(error).casefold()
    return "embedding" in message or "memory search" in message


def _is_local_model_setup_error(error: Exception) -> bool:
    return isinstance(error, (SemanticModelUnavailable, LLMRuntimeError))


def _mark_job_blocked_setup(job: dict) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'blocked_setup_required',
                attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                last_error = '',
                status_detail = 'Set up memory search to continue this task.',
                started_at = NULL,
                updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (utc_now(), job["id"]),
        )
        if job.get("job_type") == "reindex_source":
            payload = _decode_payload(job.get("payload") or "{}")
            source_id = str(payload.get("source_id") or "")
            if source_id:
                publish_source_ingestion_stage(
                    conn,
                    source_id=source_id,
                    stage="paused",
                    generation=int(payload.get("ingestion_generation") or 0) or None,
                    detail="Set up memory search to publish this source.",
                )


def _mark_job_blocked_local_model(job: dict, detail: str = "") -> None:
    message = detail.strip() or "The selected local model is unavailable."
    with connect() as conn:
        conn.execute(
            """
            UPDATE app_jobs
            SET status = 'blocked_setup_required',
                attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                last_error = '',
                status_detail = ?,
                started_at = NULL,
                updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                f"Local model unavailable. {message[:430]}",
                utc_now(),
                job["id"],
            ),
        )


def _refresh_setup_prerequisites() -> None:
    _refresh_embedding_prerequisite()
    _refresh_local_model_prerequisite()


def _refresh_embedding_prerequisite() -> None:
    available = bool(embedding_status(probe_model=False).get("available"))
    now = utc_now()
    with connect() as conn:
        previous = conn.execute(
            "SELECT state, generation FROM scheduler_prerequisites WHERE name = 'embeddings'"
        ).fetchone()
        previous_state = str(previous["state"]) if previous else "unknown"
        generation = int(previous["generation"] or 0) if previous else 0
        transitioned_to_ready = bool(previous is not None and available and previous_state != "ready")
        if transitioned_to_ready:
            generation += 1
        state = "ready" if available else "setup_required"
        conn.execute(
            """
            INSERT INTO scheduler_prerequisites (name, state, generation, detail, updated_at)
            VALUES ('embeddings', ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                state = excluded.state,
                generation = excluded.generation,
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (
                state,
                generation,
                "" if available else "Set up memory search to continue vector tasks.",
                now,
            ),
        )
        if not available:
            return
        placeholders = ",".join("?" for _ in EMBEDDING_JOB_TYPES)
        conn.execute(
            f"""
            UPDATE app_jobs
            SET status = 'queued', status_detail = '', updated_at = ?
            WHERE status = 'blocked_setup_required'
              AND job_type IN ({placeholders})
            """,
            [now, *sorted(EMBEDDING_JOB_TYPES)],
        )
        conn.execute(
            f"""
            UPDATE sources
            SET ingestion_stage = 'imported',
                ingestion_status_detail = 'Memory search is ready. Source publication will resume.',
                ingestion_error_code = '',
                ingestion_updated_at = ?
            WHERE id IN (
                SELECT scope_id
                FROM app_jobs
                WHERE status = 'queued'
                  AND job_type = 'reindex_source'
                  AND scope_id IS NOT NULL
            )
              AND ingestion_stage = 'paused'
            """,
            (now,),
        )
        if transitioned_to_ready:
            active_reconciliation = conn.execute(
                """
                SELECT id
                FROM app_jobs
                WHERE job_type = 'vector_reconcile_incremental'
                  AND status IN (
                    'queued', 'running', 'blocked_by_dependency',
                    'blocked_setup_required', 'deferred'
                  )
                LIMIT 1
                """
            ).fetchone()
            if active_reconciliation is None:
                enqueue_job(
                    conn,
                    job_type="vector_reconcile_incremental",
                    payload={},
                    dedupe_key=f"vector-reconcile:embedding-generation:{generation}",
                    user_initiated=False,
                )


def _refresh_local_model_prerequisite() -> None:
    from backend.app.core.llm_runtime import runtime_status

    placeholders = ",".join("?" for _ in LOCAL_MODEL_JOB_TYPES)
    with connect() as conn:
        pending = conn.execute(
            f"""
            SELECT
                EXISTS(
                    SELECT 1 FROM app_jobs
                    WHERE job_type IN ({placeholders})
                      AND status IN (
                          'queued', 'running', 'paused', 'blocked_by_dependency',
                          'blocked_setup_required', 'deferred'
                      )
                )
                OR EXISTS(
                    SELECT 1 FROM sources
                    WHERE deleted_at IS NULL AND state = 'indexed'
                      AND metadata_version < ?
                ) AS needed
            """,
            [*sorted(LOCAL_MODEL_JOB_TYPES), SOURCE_METADATA_VERSION],
        ).fetchone()
    if not bool(pending["needed"]):
        return

    runtime = runtime_status()
    available = bool(runtime.get("available"))
    runtime_state = str(runtime.get("state") or "missing")
    detail = str(runtime.get("detail") or "The selected local model is unavailable.")
    now = utc_now()
    with connect() as conn:
        previous = conn.execute(
            "SELECT state, generation FROM scheduler_prerequisites WHERE name = 'local_model'"
        ).fetchone()
        previous_state = str(previous["state"]) if previous else "unknown"
        generation = int(previous["generation"] or 0) if previous else 0
        transitioned_to_ready = available and previous_state != "ready"
        if transitioned_to_ready:
            generation += 1
        state = "ready" if available else "setup_required"
        conn.execute(
            """
            INSERT INTO scheduler_prerequisites (name, state, generation, detail, updated_at)
            VALUES ('local_model', ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                state = excluded.state,
                generation = excluded.generation,
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (state, generation, "" if available else detail[:500], now),
        )
        if available:
            conn.execute(
                f"""
                UPDATE app_jobs
                SET status = 'queued', status_detail = '', updated_at = ?
                WHERE status = 'blocked_setup_required'
                  AND job_type IN ({placeholders})
                """,
                [now, *sorted(LOCAL_MODEL_JOB_TYPES)],
            )
            if transitioned_to_ready:
                _enqueue_source_metadata_backlog(conn)
            return

        waiting = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM app_jobs
            WHERE job_type IN ({placeholders})
              AND status IN ('queued', 'running', 'blocked_setup_required', 'deferred')
            """,
            sorted(LOCAL_MODEL_JOB_TYPES),
        ).fetchone()
        recovery_key = f"model-runtime-recovery:{generation}"
        recovery = conn.execute(
            "SELECT id FROM app_jobs WHERE dedupe_key = ? LIMIT 1",
            (recovery_key,),
        ).fetchone()
        if int(waiting["count"] or 0) > 0 and runtime_state != "starting" and recovery is None:
            enqueue_job(
                conn,
                job_type="model_runtime_recovery",
                payload={"reason": "semantic_jobs_waiting"},
                dedupe_key=recovery_key,
                user_initiated=False,
                max_attempts=1,
            )


def _enqueue_due_turbovec_evaluations() -> None:
    from backend.app.core.config import get_settings
    from backend.app.core.turbovec_runtime import (
        turbovec_phase_c_status,
        turbovec_runtime_available,
    )

    if not turbovec_runtime_available():
        return
    with connect() as conn:
        vault_ids = [
            str(row["id"])
            for row in conn.execute("SELECT id FROM vaults ORDER BY created_at, id LIMIT 25").fetchall()
        ]
    for vault_id in vault_ids:
        try:
            status = turbovec_phase_c_status(vault_id)
        except (KeyError, RuntimeError, OSError):
            continue
        threshold = int(get_settings().turbovec_min_chunk_count)
        if int(status.get("eligible_chunk_count") or 0) < threshold:
            continue
        # A result—passing or failing—is evidence for this derived-state epoch.
        # Re-evaluate only after the epoch changes rather than burning resources
        # on every worker poll.
        if status.get("benchmark") is not None:
            continue
        with connect() as conn:
            enqueue_job(
                conn,
                job_type="turbovec_evaluate",
                payload={
                    "vault_id": vault_id,
                    "derived_state_epoch": status.get("derived_state_epoch"),
                },
                dedupe_key=(
                    f"turbovec-evaluate:{vault_id}:"
                    f"{status.get('derived_state_epoch') or 'current'}"
                ),
                scope_id=vault_id,
            )


def _run_turbovec_evaluate(payload: dict, job_id: str | None = None) -> None:
    from backend.app.core.turbovec_runtime import (
        benchmark_turbovec_phase_c,
        turbovec_phase_c_status,
    )

    _raise_if_job_cancelled(job_id)
    vault_id = str(payload.get("vault_id") or "")
    if not vault_id:
        raise ValueError("Faster search evaluation is missing its library.")
    current = turbovec_phase_c_status(vault_id)
    requested_epoch = payload.get("derived_state_epoch")
    if requested_epoch is not None and int(requested_epoch) != int(current["derived_state_epoch"]):
        _set_job_result(
            job_id,
            {"skipped": True, "reason": "derived_state_changed"},
            detail="Search data changed. Vault will test the current index later.",
        )
        return
    report = benchmark_turbovec_phase_c(vault_id)
    _raise_if_job_cancelled(job_id)
    _set_job_result(
        job_id,
        report,
        detail=(
            "Faster search passed its checks and is ready."
            if report.get("approved")
            else "Exact search remains active because faster search did not pass every check."
        ),
    )


def notify_embedding_prerequisite_changed() -> None:
    _refresh_embedding_prerequisite()
    wake_background_worker()


def notify_local_model_prerequisite_changed() -> None:
    _refresh_local_model_prerequisite()
    wake_background_worker()


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
