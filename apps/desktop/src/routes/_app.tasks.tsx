import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Pause, Play, RotateCcw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  cancelJob,
  getJobStatus,
  runJobsOnce,
  type AppJobRecord,
  type JobQueueStatus,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/tasks")({
  head: () => ({ meta: [{ title: "Tasks" }] }),
  component: TasksView,
});

type TaskFilter = "running" | "queued" | "failed" | "completed" | "maintenance";

function TasksView() {
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [filter, setFilter] = useState<TaskFilter>("running");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AppJobRecord | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    try {
      const status = await getJobStatus();
      setJobs(status);
      setSelected((current) => current ?? status.running_jobs[0] ?? status.latest[0] ?? null);
    } catch {
      setJobs(null);
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, []);

  const rows = useMemo(() => {
    const latest = jobs?.latest ?? [];
    const running = jobs?.running_jobs ?? [];
    const merged = uniqueJobs([...running, ...latest]);
    const normalized = query.trim().toLowerCase();
    return merged
      .filter((job) => matchesFilter(job, filter))
      .filter((job) => !normalized || `${job.job_type} ${job.status} ${job.write_scope ?? ""}`.toLowerCase().includes(normalized));
  }, [filter, jobs, query]);

  async function runOnce() {
    try {
      setJobs(await runJobsOnce());
      setMessage("Ran due jobs once.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not run jobs.");
    }
  }

  async function cancelSelected() {
    if (!selected) return;
    try {
      const next = await cancelJob(selected.id);
      setSelected(next);
      setMessage(`Cancelled ${next.job_type}.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not cancel this job.");
    }
  }

  const activeJob = rows.find((job) => job.id === selected?.id) ?? rows[0] ?? null;

  return (
    <div className="vault-page-wash grid h-full grid-cols-1 overflow-y-auto bg-background xl:grid-cols-[minmax(0,1fr)_320px] xl:overflow-hidden">
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 xl:overflow-y-auto">
        <header className="border-b border-border pb-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="page-title">Tasks</h1>
              <p className="mt-2 text-sm text-muted-foreground">Background work that keeps your vault current.</p>
            </div>
            <Button className="w-full sm:w-auto" onClick={() => void runOnce()}>
              <Play className="h-4 w-4" />
              Run due jobs
            </Button>
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
                    <span className="text-right text-xs text-muted-foreground">{job.cancellable ? "Cancel" : "-"}</span>
                  </button>
                ))}
                {rows.length === 0 && (
                  <div className="px-4 py-10 text-center text-sm text-muted-foreground">No jobs in this view.</div>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      <aside className="min-w-0 border-t border-border bg-card px-4 py-6 sm:px-6 xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)] xl:overflow-y-auto xl:border-l xl:border-t-0 xl:py-8">
        <h2 className="text-sm font-semibold">Job detail</h2>
        {activeJob ? (
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
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void load()}>
                <RotateCcw className="h-4 w-4" />
                Refresh
              </Button>
              <Button variant="outline" disabled={!activeJob.cancellable} onClick={() => void cancelSelected()}>
                <X className="h-4 w-4" />
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <p className="mt-5 text-sm text-muted-foreground">No task selected.</p>
        )}
      </aside>
    </div>
  );
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
  if (filter === "queued") return ["queued", "blocked_by_dependency"].includes(job.status);
  if (filter === "failed") return ["failed", "manual_review"].includes(job.status);
  if (filter === "completed") return ["succeeded", "cancelled"].includes(job.status);
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
  if (status === "cancelled") return <Pause className="h-4 w-4 text-muted-foreground" />;
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
