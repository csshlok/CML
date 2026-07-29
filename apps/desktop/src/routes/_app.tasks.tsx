import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Pause, Play, RefreshCw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import {
  cancelJob,
  cancelProjectRun,
  getJobStatus,
  listJobsPage,
  listProjectRunSummary,
  reindexProject,
  runJobsOnce,
  type AppJobRecord,
  type JobQueueStatus,
  type ProjectIndexRunRecord,
  type ProjectRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/tasks")({
  validateSearch: (search: Record<string, unknown>): { job?: string } => ({
    job: typeof search.job === "string" ? search.job : undefined,
  }),
  head: () => ({ meta: [{ title: "Tasks" }] }),
  component: TasksView,
});

type TaskFilter = "running" | "queued" | "failed" | "completed" | "maintenance";
type ProjectTask = { project: ProjectRecord; run: ProjectIndexRunRecord };

function TasksView() {
  const { job: requestedJobId } = Route.useSearch();
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [filter, setFilter] = useState<TaskFilter>("running");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AppJobRecord | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [projectTasks, setProjectTasks] = useState<ProjectTask[]>([]);
  const [jobRows, setJobRows] = useState<AppJobRecord[]>([]);
  const [nextJobCursor, setNextJobCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  async function load() {
    const [statusResult, jobsResult, summaryResult] = await Promise.allSettled([
      getJobStatus(),
      listJobsPage({ limit: 100 }),
      listProjectRunSummary(200),
    ]);
    if (statusResult.status === "fulfilled") {
      const status = statusResult.value;
      setJobs(status);
      const requested = requestedJobId
        ? [...status.running_jobs, ...status.latest].find((job) => job.id === requestedJobId)
        : null;
      setSelected((current) => requested ?? current);
    }
    if (jobsResult.status === "fulfilled") {
      setJobRows(jobsResult.value.items);
      setNextJobCursor(jobsResult.value.next_cursor);
    }
    if (summaryResult.status === "fulfilled") {
      setProjectTasks(
        summaryResult.value.items
          .map(({ project, run }) => ({ project: project as ProjectRecord, run }))
          .sort((a, b) => b.run.updated_at.localeCompare(a.run.updated_at)),
      );
    }
    if (statusResult.status === "rejected" && jobsResult.status === "rejected") {
      setJobs(null);
      setMessage("Tasks are temporarily unavailable.");
    }
  }

  const hasActiveWork = Boolean(
    (jobs?.running ?? 0) +
    (jobs?.queued ?? 0) +
    (jobs?.paused ?? 0) +
    (jobs?.blocked_by_dependency ?? 0) +
    (jobs?.blocked_setup_required ?? 0) +
    (jobs?.deferred ?? 0),
  );
  useVisiblePolling(load, hasActiveWork ? 5000 : 30000);

  const rows = useMemo(() => {
    const running = jobs?.running_jobs ?? [];
    const merged = uniqueJobs([...running, ...jobRows, ...(jobs?.latest ?? [])]);
    const normalized = query.trim().toLowerCase();
    return merged
      .filter((job) => matchesFilter(job, filter))
      .filter((job) => !normalized || `${job.job_type} ${job.status} ${job.write_scope ?? ""}`.toLowerCase().includes(normalized));
  }, [filter, jobRows, jobs, query]);

  async function loadMoreJobs() {
    if (!nextJobCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await listJobsPage({ limit: 100, cursor: nextJobCursor });
      setJobRows((current) => uniqueJobs([...current, ...page.items]));
      setNextJobCursor(page.next_cursor);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load more tasks.");
    } finally {
      setLoadingMore(false);
    }
  }
  const visibleProjectTasks = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return projectTasks.filter(({ run }) => matchesProjectFilter(run, filter))
      .filter(({ project, run }) => !normalized || `${project.name} ${run.phase} ${run.status} ${run.trigger_source}`.toLowerCase().includes(normalized));
  }, [filter, projectTasks, query]);

  async function runOnce() {
    try {
      setJobs(await runJobsOnce());
      setMessage("Background work is running.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not run jobs.");
    }
  }

  async function cancelSelected() {
    if (!selected) return;
    try {
      const next = await cancelJob(selected.id);
      setSelected(next);
      setMessage(
        next.status === "cancelled"
          ? `Cancelled ${next.job_type}.`
          : `Cancellation requested for ${next.job_type}. It will stop after the current work unit.`,
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not cancel this job.");
    }
  }

  const activeJob = rows.find((job) => job.id === selected?.id) ?? null;

  return (
    <div
      className={
        "vault-page-wash grid h-full grid-cols-1 overflow-y-auto bg-background xl:overflow-hidden " +
        (activeJob ? "xl:grid-cols-[minmax(0,1fr)_320px]" : "")
      }
    >
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 xl:overflow-y-auto">
        <header className="border-b border-border pb-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="page-title">Tasks</h1>
              <p className="mt-2 text-sm text-muted-foreground">Background work that keeps your vault current.</p>
            </div>
            <div className="desktop-window-action flex w-full gap-2 sm:w-auto">
              <Button variant="outline" onClick={() => void load()}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
              <Button onClick={() => void runOnce()}>
                <Play className="h-4 w-4" />
                Run due jobs
              </Button>
            </div>
          </div>
          <div className="mt-6 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="relative min-w-0 max-w-xl">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input aria-label="Search tasks" className="pl-9" placeholder="Search tasks..." value={query} onChange={(event) => setQuery(event.target.value)} />
            </div>
            <div className="flex flex-wrap gap-1">
              {(["running", "queued", "failed", "completed", "maintenance"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setFilter(item)}
                  className={`rounded-md border px-3 py-2 text-sm transition-colors ${
                    filter === item ? "border-primary bg-accent text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {labelForFilter(item)}
                </button>
              ))}
            </div>
          </div>
        </header>

        {message && (
          <div className="mt-5 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
            {message}
          </div>
        )}

        {visibleProjectTasks.length > 0 && (
          <section className="mt-6">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2"><div><h2 className="text-sm font-semibold">Project indexing</h2><p className="mt-1 text-xs text-muted-foreground">Each synchronization is grouped separately from its discovery, structure, search, activation, and cleanup phases.</p></div></div>
            <div className="divide-y divide-border overflow-hidden rounded-md border border-border bg-card">
              {visibleProjectTasks.slice(0, 20).map(({ project, run }) => {
                const detail = parseRunDetail(run.detail_json);
                const total = run.phase_total_count || run.eligible_total;
                const complete = run.phase_completed_count || run.completed_count;
                return (
                  <details key={run.id} className="group px-4 py-3">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <div className="min-w-0"><div className="flex items-center gap-2 text-sm font-medium">{statusIcon(run.status)}<span className="truncate">{project.name}</span></div><div className="mt-1 text-xs text-muted-foreground">{run.phase.replaceAll("_", " ")} · {complete.toLocaleString()} / {total.toLocaleString()} · {formatDate(run.updated_at)}</div></div>
                      <span className="text-xs capitalize text-muted-foreground">{run.status.replaceAll("_", " ")}</span>
                    </summary>
                    <div className="mt-4 grid gap-4 border-t border-border pt-4 text-xs text-muted-foreground sm:grid-cols-2">
                      <div className="space-y-2"><Meta label="Triggered by" value={run.trigger_source.replaceAll("_", " ")} /><Meta label="Heartbeat" value={run.heartbeat_at ? formatDate(run.heartbeat_at) : "not reported"} /><Meta label="Skipped" value={run.skipped_count.toLocaleString()} /><Meta label="Failed" value={run.failed_count.toLocaleString()} /></div>
                      <div><div className="font-medium text-foreground">Persisted phases</div><ul className="mt-2 space-y-1">{Object.keys(detail).filter((key) => key.endsWith("_job_id")).map((key) => <li key={key}>{key.replace("_job_id", "").replaceAll("_", " ")}</li>)}{Object.keys(detail).filter((key) => key.endsWith("_job_id")).length === 0 && <li>No child phase IDs were reported.</li>}</ul></div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2"><Button variant="outline" size="sm" asChild><Link to="/projects/$projectId" params={{ projectId: project.id }}>Open project</Link></Button>{["queued", "running"].includes(run.status) && <Button variant="outline" size="sm" onClick={() => void cancelProjectRun(project.id).then(load)}>Cancel</Button>}{["failed", "partial", "cancelled"].includes(run.status) && <Button variant="outline" size="sm" onClick={() => void reindexProject(project.id, run.phase.includes("retrieval") ? "retrieval" : "structure").then(load)}>Retry failed layer</Button>}</div>
                  </details>
                );
              })}
            </div>
          </section>
        )}

        <section className="mt-6 overflow-hidden rounded-md border border-border bg-card">
          <div className="overflow-x-auto">
            <div className="min-w-[720px]">
              <div className="grid grid-cols-[104px_minmax(0,1fr)_120px_112px_104px_80px] border-b border-border px-4 py-3 text-xs text-muted-foreground">
                <span>Priority</span>
                <span>Job</span>
                <span>Scope</span>
                <span>Status</span>
                <span>Estimate</span>
                <span className="text-right">Control</span>
              </div>
              <div className="divide-y divide-border">
                {rows.map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    onClick={() => setSelected(job)}
                    className="grid w-full grid-cols-[104px_minmax(0,1fr)_120px_112px_104px_80px] items-center px-4 py-4 text-left text-sm transition-colors hover:bg-accent/35"
                  >
                    <span className="capitalize text-muted-foreground">{job.priority ?? "normal"}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{jobTitle(job.job_type)}</span>
                      <span className="mt-1 block truncate text-xs text-muted-foreground">{job.status_detail || job.dedupe_key || job.id}</span>
                    </span>
                    <span className="truncate text-muted-foreground">{job.write_scope ?? "none"}</span>
                    <span className="flex items-center gap-2">
                      {statusIcon(job.status)}
                      <span className="capitalize">{job.status.replace(/_/g, " ")}</span>
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">{formatEstimate(job)}</span>
                    <span className="text-right text-xs text-muted-foreground">{job.cancellable && ["queued", "running", "paused", "blocked_by_dependency", "blocked_setup_required", "deferred"].includes(job.status) ? "Cancel" : "-"}</span>
                  </button>
                ))}
                {rows.length === 0 && (
                  <div className="px-4 py-10 text-center text-sm text-muted-foreground">No jobs in this view.</div>
                )}
              </div>
            </div>
          </div>
        </section>
        {nextJobCursor ? (
          <div className="mt-4 flex justify-center">
            <Button variant="outline" onClick={() => void loadMoreJobs()} disabled={loadingMore}>
              {loadingMore ? "Loading..." : "Load more tasks"}
            </Button>
          </div>
        ) : null}
      </main>

      {activeJob ? <aside className="min-w-0 border-t border-border bg-card px-4 py-6 sm:px-6 xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)] xl:overflow-y-auto xl:border-l xl:border-t-0 xl:py-8">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Job detail</h2>
          <Button variant="ghost" size="icon" aria-label="Close job detail" onClick={() => setSelected(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        {
          <div className="mt-5">
            <div className="flex items-center gap-2 text-sm">
              {statusIcon(activeJob.status)}
              <span className="font-medium">{activeJob.status.replace(/_/g, " ")}</span>
            </div>
            <h3 className="mt-6 break-words text-[15px] font-semibold leading-snug">{jobTitle(activeJob.job_type)}</h3>
            <p className="mt-3 break-words text-sm leading-6 text-muted-foreground">
              {activeJob.status_detail || activeJob.last_error || "No additional job detail was reported."}
            </p>
            <dl className="mt-7 divide-y divide-border border-y border-border text-sm">
              <Meta label="Write scope" value={activeJob.write_scope ?? "none"}/>
              <Meta label="Resource cost" value={activeJob.resource_cost ?? "normal"}/>
              <Meta label="Attempts" value={`${activeJob.attempts} / ${activeJob.max_attempts}`}/>
              <Meta label="Timeout" value={activeJob.timeout_seconds ? `${activeJob.timeout_seconds}s` : "none"}/>
              <Meta label="Started" value={activeJob.started_at ? formatDate(activeJob.started_at) : "not started"}/>
            </dl>
            <ImportFailures job={activeJob} />
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void load()}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
              <Button variant="outline" disabled={!activeJob.cancellable} onClick={() => void cancelSelected()}>
                <X className="h-4 w-4" />
                Cancel
              </Button>
            </div>
          </div>
        }
      </aside> : null}
    </div>
  );
}

function ImportFailures({ job }: { job: AppJobRecord }) {
  if (job.job_type !== "source_import_batch" || !job.result_json) return null;
  try {
    const result = JSON.parse(job.result_json) as {
      failures?: Array<{ file_name?: string; reason?: string }>;
    };
    const failures = Array.isArray(result.failures) ? result.failures : [];
    if (failures.length === 0) return null;
    return (
      <div className="mt-6">
        <h3 className="text-sm font-medium">Files not imported</h3>
        <ul className="mt-2 divide-y divide-border border-y border-border">
          {failures.map((failure, index) => (
            <li key={`${failure.file_name ?? "file"}:${index}`} className="py-3 text-xs">
              <div className="break-all font-medium">{failure.file_name || "File"}</div>
              <div className="mt-1 break-words text-muted-foreground">
                {failure.reason || "Import failed"}
              </div>
            </li>
          ))}
        </ul>
      </div>
    );
  } catch {
    return null;
  }
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-all sm:text-right">{value}</dd>
    </div>
  );
}

function uniqueJobs(rows: AppJobRecord[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    if (seen.has(row.id)) return false;
    seen.add(row.id);
    return true;
  });
}

function matchesFilter(job: AppJobRecord, filter: TaskFilter) {
  if (filter === "running") return job.status === "running";
  if (filter === "queued") return ["queued", "paused", "blocked_by_dependency", "blocked_setup_required", "deferred"].includes(job.status);
  if (filter === "failed") return ["failed", "manual_review"].includes(job.status);
  if (filter === "completed") return ["succeeded", "cancelled"].includes(job.status) && job.user_visible !== 0;
  return ["orphan_vector_cleanup", "artifact_cleanup", "vault_integrity_check", "diagnostic_bundle"].includes(job.job_type);
}

function labelForFilter(filter: TaskFilter) {
  return {
    running: "Running",
    queued: "Queued",
    failed: "Failed",
    completed: "Completed",
    maintenance: "Maintenance",
  }[filter];
}

function jobTitle(type: string) {
  return type.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusIcon(status: string) {
  if (status === "running") return <Clock3 className="h-4 w-4 text-primary" />;
  if (status === "failed" || status === "manual_review") return <AlertTriangle className="h-4 w-4 text-destructive" />;
  if (status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-[var(--status-ready)]" />;
  if (status === "paused" || status === "cancelled") return <Pause className="h-4 w-4 text-muted-foreground" />;
  return <Clock3 className="h-4 w-4 text-muted-foreground" />;
}

function formatEstimate(job: AppJobRecord) {
  if (job.estimated_remaining_seconds != null) return `${Math.max(0, Math.round(job.estimated_remaining_seconds))}s`;
  if (job.elapsed_seconds != null && job.status === "running") return `${Math.round(job.elapsed_seconds)}s elapsed`;
  return "-";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function matchesProjectFilter(run: ProjectIndexRunRecord, filter: TaskFilter) {
  if (filter === "running") return run.status === "running";
  if (filter === "queued") return run.status === "queued";
  if (filter === "failed") return ["failed", "partial", "interrupted"].includes(run.status);
  if (filter === "completed") return ["succeeded", "cancelled"].includes(run.status);
  return false;
}

function parseRunDetail(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}
