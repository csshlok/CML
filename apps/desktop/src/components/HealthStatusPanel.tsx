import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { GripHorizontal, HeartPulse, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  BackendHealthStatus,
  JobQueueStatus,
  ModelRuntimeStatus,
  VaultRecord,
} from "@/lib/backend";

type PanelPosition = { left: number; top: number };

export function HealthStatusPanel({
  open,
  backendStatus,
  vault,
  jobs,
  runtime,
  checkedAt,
  refreshing,
  onRefresh,
  onClose,
}: {
  open: boolean;
  backendStatus: BackendHealthStatus;
  vault: VaultRecord | null;
  jobs: JobQueueStatus | null;
  runtime: ModelRuntimeStatus | null;
  checkedAt: Date | null;
  refreshing: boolean;
  onRefresh: () => Promise<void>;
  onClose: () => void;
}) {
  const [position, setPosition] = useState<PanelPosition | null>(null);
  const dragStart = useRef<{
    pointerX: number;
    pointerY: number;
    left: number;
    top: number;
  } | null>(null);

  if (!open) return null;

  const activeJobs =
    (jobs?.running ?? 0)
    + (jobs?.queued ?? 0)
    + (jobs?.paused ?? 0)
    + (jobs?.blocked_by_dependency ?? 0)
    + (jobs?.blocked_setup_required ?? 0)
    + (jobs?.deferred ?? 0);
  const failedJobs = (jobs?.failed ?? 0) + (jobs?.partial_success ?? 0) + (jobs?.manual_review ?? 0);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    if (
      event.target instanceof Element
      && event.target.closest("[data-health-panel-control]")
    ) return;
    const panel = event.currentTarget.closest<HTMLElement>("[data-health-panel]");
    if (!panel) return;
    const bounds = panel.getBoundingClientRect();
    dragStart.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      left: bounds.left,
      top: bounds.top,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function drag(event: ReactPointerEvent<HTMLDivElement>) {
    const start = dragStart.current;
    if (!start) return;
    const panelWidth = Math.min(380, window.innerWidth - 24);
    const panelHeight = 390;
    setPosition({
      left: Math.max(12, Math.min(window.innerWidth - panelWidth - 12, start.left + event.clientX - start.pointerX)),
      top: Math.max(12, Math.min(window.innerHeight - panelHeight - 12, start.top + event.clientY - start.pointerY)),
    });
  }

  function stopDrag(event: ReactPointerEvent<HTMLDivElement>) {
    dragStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <aside
      data-health-panel
      role="dialog"
      aria-label="Health status"
      className="fixed bottom-6 right-6 z-50 w-[min(380px,calc(100vw-24px))] overflow-hidden rounded-md border border-border bg-card"
      style={position ? { left: position.left, top: position.top, right: "auto", bottom: "auto" } : undefined}
    >
      <div
        className="flex cursor-move touch-none items-center gap-2 border-b border-border px-4 py-3 select-none"
        onPointerDown={startDrag}
        onPointerMove={drag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <GripHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <HeartPulse className="h-4 w-4" aria-hidden="true" />
        <h2 className="min-w-0 flex-1 text-sm font-semibold">Health status</h2>
        <Button
          data-health-panel-control
          variant="ghost"
          size="icon"
          aria-label="Close health status"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="divide-y divide-border px-4">
        <HealthRow
          label="Local service"
          value={backendStatus === "online" ? "Ready" : backendStatus === "checking" ? "Checking" : backendStatus === "degraded" ? "Needs attention" : "Offline"}
          tone={backendStatus === "online" ? "ready" : backendStatus === "checking" ? "neutral" : "issue"}
        />
        <HealthRow
          label="Library"
          value={vault?.name ?? "No library selected"}
          tone={vault ? "ready" : "neutral"}
        />
        <HealthRow
          label="Local chat"
          value={runtime?.available ? "Ready" : runtime?.state === "starting" ? "Starting" : "Unavailable"}
          tone={runtime?.available ? "ready" : runtime?.state === "starting" ? "neutral" : "issue"}
        />
        <HealthRow
          label="Background work"
          value={failedJobs > 0 ? `${failedJobs} need attention` : activeJobs > 0 ? `${activeJobs} active` : jobs ? "Caught up" : "Checking"}
          tone={failedJobs > 0 ? "issue" : activeJobs > 0 ? "neutral" : jobs ? "ready" : "neutral"}
        />
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
        <p className="text-xs text-muted-foreground">
          Latest check: {checkedAt ? formatCheckTime(checkedAt) : "not run yet"}
        </p>
        <Button variant="outline" size="sm" disabled={refreshing} onClick={() => void onRefresh()}>
          <RefreshCw className={refreshing ? "h-4 w-4 animate-spin motion-reduce:animate-none" : "h-4 w-4"} />
          {refreshing ? "Checking" : "Check now"}
        </Button>
      </div>
    </aside>
  );
}

function HealthRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ready" | "neutral" | "issue";
}) {
  const color =
    tone === "ready"
      ? "var(--status-ready)"
      : tone === "issue"
        ? "var(--status-issue)"
        : "var(--text-muted)";
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex min-w-0 items-center gap-2 text-right font-medium">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
        <span className="break-words">{value}</span>
      </span>
    </div>
  );
}

function formatCheckTime(value: Date) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(value);
}
