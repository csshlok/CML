# Job And Maintenance Architecture

Last updated: 2026-05-30

## Purpose

Vault needs one scheduler model for ingestion, indexing, chat memory, diagnostics, cleanup, merge repair, vector reconciliation, and future expert training. The current backend has a simple FIFO `app_jobs` worker for `reindex_source` and `chat_transcript_memory`. That is enough for early development, but it is not enough for production maintenance.

This document defines the target V1 job taxonomy and scheduler rules before more background systems are added.

## Current State

Current `app_jobs` fields:

| Field | Current purpose |
| --- | --- |
| `id` | Job ID. |
| `job_type` | String job type. |
| `status` | `queued`, `running`, `succeeded`, or `failed`. |
| `payload` | JSON payload. |
| `dedupe_key` | Optional active-job dedupe key. |
| `attempts` | Retry attempt count. |
| `max_attempts` | Max attempts before failure. |
| `last_error` | Last error text. |
| `created_at` | Creation timestamp. |
| `updated_at` | Last update timestamp. |

Current implemented job types:

| Job type | Current behavior |
| --- | --- |
| `reindex_source` | Rebuilds local source chunks/embeddings for one source and marks the cluster expert stale. |
| `chat_transcript_memory` | Converts a chat session into indexed transcript memory sources. |

## Target Job Record

The scheduler needs these fields either stored on the job row or resolved from a job registry by `job_type`.

| Field | Type | Meaning |
| --- | --- | --- |
| `job_type` | enum/string | Registered job type. |
| `status` | enum | `queued`, `blocked_by_dependency`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`, `manual_review`. |
| `priority` | enum | `critical`, `high`, `normal`, `low`, `on_demand`. |
| `idempotency_class` | enum | `idempotent`, `reconcile_required`, `non_idempotent`. |
| `restart_policy` | enum | `requeue`, `reconcile_then_retry`, `manual_review`. |
| `write_scope` | enum | Declared write conflict scope. |
| `scope_id` | string/null | ID for scoped locks, such as source ID or cluster ID. |
| `concurrency_group` | string/null | Global group lock, such as `vector_writer`. |
| `depends_on_job_id` | string/null | Optional predecessor job. |
| `dependency_failure_policy` | enum | `cancel`, `requeue_on_retry`, or `manual_review`. No null/default ambiguity. |
| `resource_cost` | enum | `light`, `medium`, `heavy`, `very_heavy`. |
| `can_run_during_synthesis` | bool | Whether job can run while local chat generation is active. |
| `user_visible` | bool | Whether progress/failure should appear in user-facing job UI. |
| `user_initiated` | bool | Whether the user explicitly triggered the job. |
| `cancellable` | bool | Whether cancellation can leave state clean. |
| `preemptable` | bool | Whether the scheduler may interrupt it for critical work. |
| `timeout_seconds` | int/null | Hard wall-clock timeout. |
| `soft_timeout_seconds` | int/null | Warning/defer threshold. |
| `timeout_action` | enum | `fail`, `defer`, `escalate`. |

## Write Scope Vocabulary

`write_scope` must use this fixed vocabulary so the scheduler can reason about conflicts.

| Scope | Meaning | Conflict rule |
| --- | --- | --- |
| `vault` | Vault-level metadata or schema. | One per vault. Blocks most writes. |
| `cluster` | One cluster's records or membership. | Conflicts with same cluster `scope_id`; may block expert jobs. |
| `source` | One source item, pages, chunks, or extraction state. | Conflicts with same source `scope_id`. |
| `vector_index` | Vector store/index writes. | Single writer for V1. |
| `expert` | Expert artifacts/training records. | One expert job per cluster/vault. |
| `chat` | Chat sessions/messages/snapshots/transcript memory. | Conflicts with same chat `scope_id` when mutating. |
| `system` | App settings, tokens, logs, diagnostics, maintenance state. | Conflicts by `concurrency_group`. |
| `none` | Read-only or external-only. | No write lock. |

V1 should keep a single writer for `vector_index` and avoid per-cluster vector concurrency until benchmarks prove it is needed.

V1 scheduler assumption: one backend process and one scheduler worker owns job claims for a vault. Scope locking can use query-before-claim checks against currently `running` jobs. This assumption must remain visible in code; adding a second worker/thread requires replacing that check with an atomic claim/lock mechanism.

## Timeout Policy

Timeout is structured, not a single number.

| Field | Meaning |
| --- | --- |
| `timeout_seconds` | Hard wall-clock limit. If reached, apply `timeout_action`. |
| `soft_timeout_seconds` | Log/mark slow at this point, but do not kill yet. |
| `timeout_action` | `fail`, `defer`, or `escalate`. |

`defer` is for maintenance work that can resume later without alarming the user. `escalate` is for jobs that should enter `manual_review` or repair flow.

## Dependency Model

V1 uses a single optional dependency:

```txt
depends_on_job_id TEXT NULL
dependency_failure_policy TEXT NOT NULL
```

Scheduler rule:

| Dependency state | Dependent job action |
| --- | --- |
| no dependency | Eligible if other rules pass. |
| dependency `succeeded` | Eligible if other rules pass. |
| dependency `queued`/`running`/`blocked_by_dependency` | Leave queued or blocked. |
| dependency `failed`/`cancelled`/`manual_review` | Mark dependent `blocked_by_dependency`. |

This is not a full DAG engine. It is enough for V1 chains such as extract -> embed -> suggest cluster, merge -> reindex -> retrain, and integrity check -> diagnostic bundle.

Dependency failure policy:

| Policy | Action when dependency cannot succeed |
| --- | --- |
| `cancel` | Mark dependent job `cancelled`; this is expected, not an error. |
| `requeue_on_retry` | Keep blocked while dependency is retried; if dependency later succeeds, run. |
| `manual_review` | Mark dependent job `manual_review` with the dependency failure details. |

## Scheduler Rules

Rules should be implemented as executable ordering logic, not comments.

1. Do not accept background jobs until startup reaches the traffic-ready stage:
   - vault ownership verified
   - SQLite integrity/schema/migrations passed
   - old jobs recovered
   - vector/index reconciliation initialized
   - runtime detected

2. Pick runnable jobs by:
   - dependency satisfied
   - priority order
   - created time within same priority
   - write scope/concurrency group available
   - runtime/synthesis compatibility

3. Critical jobs jump to the front of the queue, but do not preempt a running job unless `preemptable = true`.

4. If a local chat generation is running:
   - jobs with `can_run_during_synthesis = true` may run
   - jobs with `can_run_during_synthesis = false` are deferred
   - critical repair/delete jobs may still run if their scope does not conflict and they are lightweight

5. User-initiated failures are surfaced prominently with retry/details. Non-user-initiated maintenance failures are logged and retried/deferred according to policy.

6. One `vector_index` writer runs at a time in V1.

7. Vault/schema/migration/repair jobs block normal writes.

8. Diagnostic bundle generation is on-demand and must not include raw source/chat text unless the user explicitly opts in.

## Priority Levels

| Priority | Meaning | Examples |
| --- | --- | --- |
| `critical` | Data safety, repair, privacy cleanup. | Vault repair, migration recovery, direct delete cleanup. |
| `high` | User-visible active work or missing critical index data. | Active ingestion, missing-vector re-embedding, generation recovery. |
| `normal` | Standard background product work. | OCR, link extraction, cluster suggestions. |
| `low` | Maintenance that can wait. | Artifact cleanup, compaction, log cleanup. |
| `on_demand` | User-requested support/export work. | Diagnostic bundle generation, manual repair report. |

## Job Type Registry

This table is the source of truth for current and planned V1 job types. Values can change after benchmarks, but every new job type must fill these fields before implementation.

| Job type | Status | Priority | Idempotency | Restart policy | Dependency failure | Write scope | Concurrency group | Resource | During synthesis | User visible | User initiated | Cancellable | Preemptable | Timeout policy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `reindex_source` | implemented | high | idempotent | requeue | cancel | source | vector_writer | medium | false | true | sometimes | true | false | 600s / defer |
| `chat_transcript_memory` | implemented | normal | idempotent | requeue | cancel | chat | vector_writer | medium | false | true | false | false | false | 300s / defer |
| `extract_source` | planned | high | idempotent | requeue | cancel | source | null | medium | true | true | true | true | false | 600s / fail |
| `ocr_source` | implemented | normal | idempotent | requeue | cancel | source | ocr_cpu | heavy | false | true | true | true | false | 1800s / defer |
| `expanded_analysis` | implemented | normal | idempotent | requeue | cancel | chat | analysis | medium | true | true | true | true | false | 900s / defer |
| `fetch_link` | planned | normal | idempotent | requeue | cancel | source | network_fetch | medium | true | true | true | true | false | 180s / fail |
| `embed_source_chunks` | planned | high | idempotent | requeue | requeue_on_retry | vector_index | vector_writer | medium | false | true | false | true | false | 900s / defer |
| `orphan_vector_cleanup` | planned | high | idempotent | requeue | cancel | vector_index | vector_writer | medium | false | false | false | false | false | 600s / defer |
| `vector_reconcile_incremental` | implemented | high | idempotent | requeue | cancel | vector_index | vector_writer | medium | false | false | false | false | false | 900s / defer |
| `vector_reconcile_full` | planned | on_demand | idempotent | requeue | manual_review | vector_index | vector_writer | very_heavy | false | true | true | true | false | null / escalate |
| `vector_compact` | planned | low | idempotent | requeue | cancel | vector_index | vector_writer | heavy | false | false | false | false | false | 1800s / defer |
| `cluster_suggestion` | planned | normal | idempotent | requeue | cancel | cluster | null | medium | false | true | false | true | false | 600s / defer |
| `cluster_merge_prepare` | planned | high | reconcile_required | reconcile_then_retry | manual_review | cluster | merge_workflow | medium | false | true | true | false | false | 300s / escalate |
| `cluster_merge_apply` | planned | critical | reconcile_required | reconcile_then_retry | manual_review | cluster | merge_workflow | medium | false | true | true | false | false | 300s / escalate |
| `cluster_merge_rollback` | planned | critical | reconcile_required | reconcile_then_retry | manual_review | cluster | merge_workflow | medium | false | true | true | false | false | 600s / escalate |
| `expert_train` | planned | normal | non_idempotent | reconcile_then_retry | manual_review | expert | expert_training | very_heavy | false | true | true | true | false | null / escalate |
| `expert_status_update` | planned | normal | idempotent | requeue | cancel | expert | null | light | true | true | false | false | false | 60s / fail |
| `artifact_cleanup` | planned | low | reconcile_required | reconcile_then_retry | cancel | system | maintenance | medium | true | false | false | false | false | 600s / defer |
| `log_cleanup` | planned | low | idempotent | requeue | cancel | system | maintenance | light | true | false | false | false | false | 60s / defer |
| `diagnostic_bundle` | planned | on_demand | idempotent | manual_review | manual_review | system | diagnostics | medium | true | true | true | true | false | 300s / fail |
| `vault_integrity_check` | planned | critical | idempotent | manual_review | manual_review | vault | vault_repair | medium | false | true | true | false | false | null / escalate |
| `vault_migration` | planned | critical | reconcile_required | manual_review | manual_review | vault | vault_repair | heavy | false | true | false | false | false | null / escalate |
| `delete_source_cleanup` | implemented | critical | reconcile_required | reconcile_then_retry | manual_review | source | delete_cleanup | medium | true | true | true | false | false | 300s / escalate |
| `map_position_save` | planned | low | idempotent | requeue | cancel | system | map_layout | light | true | false | false | false | false | 30s / defer |

## Dependency Examples

| Flow | Jobs |
| --- | --- |
| Local file ingestion | `extract_source` -> `embed_source_chunks` -> `cluster_suggestion` |
| OCR PDF ingestion | `extract_source` -> `ocr_source` -> `embed_source_chunks` -> `cluster_suggestion` |
| Link ingestion | `fetch_link` -> `extract_source` -> `embed_source_chunks` |
| Cluster merge | `cluster_merge_prepare` -> `cluster_merge_apply` -> `embed_source_chunks` or `vector_reconcile_incremental` -> `expert_train` |
| Diagnostic bundle | `vault_integrity_check` -> `diagnostic_bundle` |
| Source delete | synchronous SQLite tombstone/filter -> `delete_source_cleanup` -> `vector_reconcile_incremental` |

## Startup Recovery Tables

### Runtime Crash During Generation

| Current state | Event | Backend action | Job action | UI action |
| --- | --- | --- | --- | --- |
| generation `running`, runtime `ready` | Managed runtime exits | Mark runtime `crashed`; mark generation `retriable` or `failed_runtime`. | Continue jobs that do not need runtime. Defer runtime-dependent jobs. | Show restart, retry, and context-only actions. |
| generation `running`, PID alive | Health timeout threshold + heartbeat silent | Mark runtime `hung`; kill/restart only if managed. | Continue safe jobs; block new synthesis. | Show "model stopped responding" with retry after restart. |
| generation `running` | User chooses context-only | Mark generation as completed by fallback path with runtime warning. | No scheduler change. | Show answer with visible runtime note. |

### Backend Restart During Active Indexing

Startup order is mandatory:

```txt
vault ownership -> SQLite integrity/schema/migrations -> job recovery -> vector reconciliation -> runtime detection -> traffic
```

| Found job state | Restart policy | Recovery action |
| --- | --- | --- |
| old-session `running` + `requeue` | `requeue` | Mark `interrupted`, then queue fresh attempt if dependency still valid. |
| old-session `running` + `reconcile_then_retry` | `reconcile_then_retry` | Run reconciliation/checkpoint logic before retry. |
| old-session `running` + `manual_review` | `manual_review` | Mark `manual_review`; expose repair/details. |
| dependent job whose parent failed | any | Mark `blocked_by_dependency`. |
| in-flight generation from old session | n/a | Mark `retriable`; do not auto-run. |

### Vault Lock Contention On Launch

| Lock state | Action |
| --- | --- |
| No lock file | Claim lock and continue startup. |
| Lock file exists, PID not running | Reclaim lock and continue startup. |
| PID running but process identity does not match Vault backend/app | Reclaim lock and continue startup. |
| PID running and process identity matches | Refuse second writer; focus existing Electron window if same app instance. |
| Different vault path requested while Vault is open | V1 refuses and explains that only one vault window is supported. |

Age of the lock file alone is never a reclaim condition.

## Migration From Current Worker

1. Add registry metadata in code for existing job types.
2. Add schema fields: `priority`, `depends_on_job_id`, `dependency_failure_policy`, `scope_id`, `status_detail`, `started_at`, `completed_at`, and optional persisted resolved policy fields.
3. Replace FIFO claim with dependency/scope/priority-aware claim.
4. Add startup recovery before worker starts.
5. Split `reindex_source` into extraction and embedding jobs when OCR/PDF/link pipelines are expanded.
6. Add maintenance jobs only after scheduler rules are enforced.

## Phase 1 Checkpoint Tests

These tests define "done" for the scheduler foundation.

| Scenario | Expected result |
| --- | --- |
| High-priority job queued while low-priority job is already running. | Low-priority job completes; high-priority job runs next. |
| Job A fails; job B depends on A with `dependency_failure_policy = cancel`. | Job B transitions to `cancelled`, not `failed`. |
| Backend restarts with a job in `running` state and `restart_policy = requeue`. | Startup recovery transitions job to `queued`. |
| Unknown job type arrives. | Job transitions to `manual_review`; worker does not crash. |
| Two jobs with the same write scope; one is running. | Second job waits until first completes. |

## Non-Goals For V1

- No multi-vault concurrent writers.
- No per-cluster vector write parallelism until measured.
- No full DAG workflow engine.
- No remote telemetry dependency for job recovery.
- No automatic raw-content diagnostic upload.
