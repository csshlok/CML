import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { FileUp, Pause, Play, Square, X } from "lucide-react";
import {
  getActiveSourceImportJob,
  getJob,
  pauseSourceImportJob,
  resumeSourceImportJob,
  startSourceImportJob,
  stopSourceImportJob,
  type AppJobRecord,
  type SourceImportProgress,
} from "@/lib/backend";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { ConfirmAction } from "@/components/product/Feedback";

const activeImportStatuses = new Set(["queued", "running", "paused"]);
const terminalImportStatuses = new Set(["succeeded", "failed", "cancelled", "manual_review"]);

type SourceImportContextValue = {
  job: AppJobRecord | null;
  progress: SourceImportProgress | null;
  active: boolean;
  actionBusy: boolean;
  actionError: string | null;
  start: (payload: {
    vaultId: string;
    paths: string[];
    truncatedAt?: number | null;
  }) => Promise<AppJobRecord>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: () => Promise<void>;
  dismiss: () => void;
};

const SourceImportContext = createContext<SourceImportContextValue | null>(null);

export function SourceImportProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<AppJobRecord | null>(null);
  const [dismissedJobId, setDismissedJobId] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const terminalEventRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (job?.id && (activeImportStatuses.has(job.status) || job.cancellation_requested)) {
      const next = await getJob(job.id);
      setJob(next);
      return;
    }
    if (!job || !terminalImportStatuses.has(job.status)) {
      setJob(await getActiveSourceImportJob());
    }
  }, [job]);

  const active = Boolean(
    job && (activeImportStatuses.has(job.status) || job.cancellation_requested),
  );
  useVisiblePolling(refresh, active ? 750 : 5000);

  useEffect(() => {
    if (!job || !terminalImportStatuses.has(job.status)) return;
    if (terminalEventRef.current === job.id) return;
    terminalEventRef.current = job.id;
    window.dispatchEvent(
      new CustomEvent("vault:sources-changed", {
        detail: { reason: "source-import", jobId: job.id },
      }),
    );
  }, [job]);

  const start = useCallback(
    async ({
      vaultId,
      paths,
      truncatedAt = null,
    }: {
      vaultId: string;
      paths: string[];
      truncatedAt?: number | null;
    }) => {
      setActionBusy(true);
      setActionError(null);
      try {
        const next = await startSourceImportJob({
          vault_id: vaultId,
          paths,
          truncated_at: truncatedAt,
        });
        terminalEventRef.current = null;
        setDismissedJobId(null);
        setJob(next);
        return next;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not start the file import.";
        setActionError(message);
        throw error;
      } finally {
        setActionBusy(false);
      }
    },
    [],
  );

  const runAction = useCallback(
    async (action: (jobId: string) => Promise<AppJobRecord>) => {
      if (!job) return;
      setActionBusy(true);
      setActionError(null);
      try {
        setJob(await action(job.id));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not update the file import.";
        setActionError(message);
        throw error;
      } finally {
        setActionBusy(false);
      }
    },
    [job],
  );

  const value = useMemo<SourceImportContextValue>(
    () => ({
      job,
      progress: parseSourceImportProgress(job),
      active,
      actionBusy,
      actionError,
      start,
      pause: () => runAction(pauseSourceImportJob),
      resume: () => runAction(resumeSourceImportJob),
      stop: () => runAction(stopSourceImportJob),
      dismiss: () => {
        if (job) setDismissedJobId(job.id);
      },
    }),
    [actionBusy, actionError, active, job, runAction, start],
  );

  return (
    <SourceImportContext.Provider value={value}>
      {children}
      <SourceImportViewport hidden={Boolean(job && dismissedJobId === job.id)} />
    </SourceImportContext.Provider>
  );
}

export function useSourceImport() {
  const value = useContext(SourceImportContext);
  if (!value) {
    throw new Error("useSourceImport must be used inside SourceImportProvider");
  }
  return value;
}

export function SourceImportInlineProgress() {
  const sourceImport = useSourceImport();
  if (!sourceImport.job || !sourceImport.progress) return null;
  return (
    <SourceImportStatus
      compact
      job={sourceImport.job}
      progress={sourceImport.progress}
      actionBusy={sourceImport.actionBusy}
      actionError={sourceImport.actionError}
      onPause={sourceImport.pause}
      onResume={sourceImport.resume}
      onStop={sourceImport.stop}
    />
  );
}

function SourceImportViewport({ hidden }: { hidden: boolean }) {
  const sourceImport = useSourceImport();
  if (hidden || !sourceImport.job || !sourceImport.progress) return null;
  return (
    <div className="source-import-popup fixed bottom-4 z-[60] w-[min(21rem,calc(100vw-2rem))]">
      <SourceImportStatus
        job={sourceImport.job}
        progress={sourceImport.progress}
        actionBusy={sourceImport.actionBusy}
        actionError={sourceImport.actionError}
        onPause={sourceImport.pause}
        onResume={sourceImport.resume}
        onStop={sourceImport.stop}
        onDismiss={sourceImport.dismiss}
      />
    </div>
  );
}

function SourceImportStatus({
  job,
  progress,
  actionBusy,
  actionError,
  onPause,
  onResume,
  onStop,
  onDismiss,
  compact = false,
}: {
  job: AppJobRecord;
  progress: SourceImportProgress;
  actionBusy: boolean;
  actionError: string | null;
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  onStop: () => Promise<void>;
  onDismiss?: () => void;
  compact?: boolean;
}) {
  const percent = sourceImportPercent(progress);
  const active = activeImportStatuses.has(job.status) || Boolean(job.cancellation_requested);
  const paused = job.status === "paused";
  const title = sourceImportTitle(job, progress);
  const details = `${progress.completed_files.toLocaleString()} / ${progress.total_files.toLocaleString()} files · ${percent}%`;

  return (
    <section
      className={
        compact
          ? "rounded-md border border-border bg-card px-3 py-3"
          : "rounded-md border border-border bg-card p-4 shadow-[0_2px_8px_rgb(26_25_22_/_0.12)]"
      }
      aria-label="File import progress"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <FileUp className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-foreground">{title}</div>
              <div className="mt-1 text-xs text-muted-foreground">{details}</div>
            </div>
            {onDismiss ? (
              <button
                type="button"
                className="-mr-1 rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={onDismiss}
                aria-label="Dismiss file import progress"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
          <Progress
            value={percent}
            className="mt-3 h-1.5"
            aria-label={`${percent}% of files processed`}
          />
          {progress.current_file && job.status === "running" ? (
            <div className="mt-2 truncate text-xs text-muted-foreground">
              Processing {progress.current_file}
            </div>
          ) : null}
          {progress.failed_files > 0 ? (
            <div className="mt-2 text-xs text-[var(--status-error)]">
              {progress.failed_files.toLocaleString()} failed
              {progress.failures[0] ? ` · ${progress.failures[0].file_name}` : ""}
            </div>
          ) : null}
          {progress.truncated_at ? (
            <div className="mt-2 text-xs text-[var(--status-warn-ink)]">
              Folder scan stopped at {progress.truncated_at.toLocaleString()} files.
            </div>
          ) : null}
          {actionError ? (
            <div className="mt-2 text-xs text-destructive" role="alert">
              {actionError}
            </div>
          ) : null}
          {active ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {paused ? (
                <Button size="sm" variant="outline" disabled={actionBusy} onClick={() => void onResume()}>
                  <Play className="h-3.5 w-3.5" /> Resume
                </Button>
              ) : (
                <Button size="sm" variant="outline" disabled={actionBusy || Boolean(job.cancellation_requested)} onClick={() => void onPause()}>
                  <Pause className="h-3.5 w-3.5" /> Pause
                </Button>
              )}
              <ConfirmAction
                title="Stop importing files?"
                description="Vault will not start the remaining files. Files already being processed may finish and stay in your library."
                confirmLabel="Stop import"
                onConfirm={onStop}
                disabled={actionBusy || Boolean(job.cancellation_requested)}
              >
                <Button size="sm" variant="outline">
                  <Square className="h-3.5 w-3.5" /> Stop
                </Button>
              </ConfirmAction>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function parseSourceImportProgress(job: AppJobRecord | null): SourceImportProgress | null {
  if (!job || job.job_type !== "source_import_batch") return null;
  let value: unknown;
  try {
    value = JSON.parse(job.result_json || "{}");
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const total = finiteCount(record.total_files);
  if (total < 1) return null;
  return {
    kind: "source_import",
    total_files: total,
    completed_files: Math.min(total, finiteCount(record.completed_files)),
    imported_files: finiteCount(record.imported_files),
    updated_files: finiteCount(record.updated_files),
    failed_files: finiteCount(record.failed_files),
    failures: Array.isArray(record.failures)
      ? record.failures
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .slice(0, 100)
          .map((item) => ({
            file_name: String(item.file_name || "File"),
            reason: String(item.reason || "Import failed"),
          }))
      : [],
    current_file: typeof record.current_file === "string" ? record.current_file : "",
    truncated_at:
      typeof record.truncated_at === "number" && Number.isFinite(record.truncated_at)
        ? Math.max(1, Math.floor(record.truncated_at))
        : null,
  };
}

function finiteCount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.floor(value))
    : 0;
}

function sourceImportPercent(progress: SourceImportProgress) {
  return Math.min(
    100,
    Math.max(0, Math.floor((progress.completed_files / progress.total_files) * 100)),
  );
}

function sourceImportTitle(job: AppJobRecord, progress: SourceImportProgress) {
  if (job.cancellation_requested) return "Stopping file import…";
  if (job.status === "paused") return "File import paused";
  if (job.status === "queued") {
    return progress.completed_files > 0 ? "File import queued to resume" : "File import queued";
  }
  if (job.status === "cancelled") return "File import stopped";
  if (job.status === "failed" || job.status === "manual_review") return "File import needs attention";
  if (job.status === "succeeded") {
    return progress.failed_files > 0 ? "File import finished with errors" : "Files imported";
  }
  return "Importing files";
}
