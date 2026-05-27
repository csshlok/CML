import { Link } from "@tanstack/react-router";
import type { Cluster, ExpertStatus } from "@/lib/mockStore";

export function ClusterDot({ tint, size = 8 }: { tint: Cluster["tint"]; size?: number }) {
  return (
    <span
      className="inline-block rounded-full"
      style={{
        width: size,
        height: size,
        background: `var(--cluster-${tint})`,
      }}
    />
  );
}

export function ClusterChip({ cluster, asLink = true }: { cluster: Cluster; asLink?: boolean }) {
  const inner = (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2 py-0.5 text-xs">
      <ClusterDot tint={cluster.tint} />
      {cluster.name}
    </span>
  );
  if (!asLink) return inner;
  return (
    <Link to="/clusters/$clusterId" params={{ clusterId: cluster.id }} className="hover:opacity-80">
      {inner}
    </Link>
  );
}

export function ExpertBadge({ status }: { status: ExpertStatus }) {
  const color =
    status === "ready"
      ? "var(--status-ready)"
      : status === "issue"
      ? "var(--status-issue)"
      : status === "paused"
      ? "var(--status-paused)"
      : "var(--status-learning)";
  const label = {
    "setting-up": "Setting up",
    learning: "Learning",
    ready: "Ready",
    "needs-update": "Needs update",
    paused: "Paused",
    issue: "Issue",
  }[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}