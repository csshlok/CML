import { createFileRoute, Link } from "@tanstack/react-router";
import { useDeferredValue, useEffect, useState } from "react";
import { Bot, FileText, GitBranch, RefreshCw, Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/WindowAware";
import {
  listActivity,
  listVaults,
  useBackendGeneration,
  type ActivityRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/timeline")({
  head: () => ({ meta: [{ title: "Timeline" }] }),
  component: TimelineRoute,
});

type ActivityKind = "source" | "chat" | "cluster";

type ActivityItem = ActivityRecord;
const PAGE_SIZE = 100;
const TIMELINE_REFRESH_INTERVAL_MS = 60_000;

function TimelineRoute() {
  const backendGeneration = useBackendGeneration();
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [activityTotal, setActivityTotal] = useState(0);
  const [vaultId, setVaultId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState<"all" | ActivityKind>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ActivityItem | null>(null);
  const [page, setPage] = useState(1);
  const [refreshCycle, setRefreshCycle] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let cancelled = false;
    async function loadVault() {
      try {
        const vault = (await listVaults())[0] ?? null;
        if (!cancelled) setVaultId(vault?.id ?? "");
      } catch {
        if (!cancelled) setLoadError(true);
      }
    }
    void loadVault();
    return () => {
      cancelled = true;
    };
  }, [backendGeneration]);

  useEffect(() => {
    setPage(1);
    setSelected(null);
  }, [backendGeneration, vaultId]);

  useEffect(() => {
    if (!vaultId) {
      setLoaded(true);
      setRefreshing(false);
      return;
    }
    let cancelled = false;
    let timer: number | null = null;

    function scheduleNextRefresh() {
      if (cancelled) return;
      timer = window.setTimeout(() => void loadPage(), TIMELINE_REFRESH_INTERVAL_MS);
    }

    async function loadPage() {
      if (cancelled) return;
      if (document.hidden) {
        scheduleNextRefresh();
        return;
      }
      setLoadError(false);
      setRefreshing(true);
      try {
        const response = await listActivity(vaultId, {
          kind: filter === "all" ? undefined : filter,
          query: deferredQuery,
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
        });
        if (cancelled) return;
        setActivities(response.items);
        setActivityTotal(response.total);
      } catch {
        if (!cancelled) {
          setActivities([]);
          setActivityTotal(0);
          setLoadError(true);
        }
      } finally {
        if (!cancelled) {
          setLoaded(true);
          setRefreshing(false);
          scheduleNextRefresh();
        }
      }
    }
    void loadPage();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [deferredQuery, filter, page, refreshCycle, vaultId]);

  const totalPages = Math.max(1, Math.ceil(activityTotal / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageActivities = activities;
  const activeItem = activities.find((item) => item.id === selected?.id) ?? null;

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <div
      className={
        "vault-page-wash grid h-full grid-cols-1 overflow-y-auto bg-background xl:overflow-hidden " +
        (activeItem ? "xl:grid-cols-[minmax(0,1fr)_320px]" : "")
      }
    >
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 xl:overflow-y-auto">
        <PageHeader className="border-b border-border pb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="page-title">Timeline</h1>
              <p className="mt-2 text-sm text-muted-foreground">Your source, cluster, and conversation history. Operational work stays in Tasks; external access stays in Bridge.</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">Updates automatically every 60 seconds</span>
              <Button
                variant="outline"
                onClick={() => setRefreshCycle((value) => value + 1)}
                disabled={!vaultId || refreshing}
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                {refreshing ? "Refreshing..." : "Refresh"}
              </Button>
            </div>
          </div>
          <div className="mt-6 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="relative min-w-0 max-w-xl">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                aria-label="Search activity"
                placeholder="Search activity..."
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="flex flex-wrap gap-1">
              {(["all", "source", "chat", "cluster"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => {
                    setFilter(item);
                    setPage(1);
                  }}
                  className={`rounded-md border px-3 py-2 text-sm transition-colors ${
                    filter === item ? "border-primary bg-accent text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {labelForKind(item)}
                </button>
              ))}
            </div>
          </div>
        </PageHeader>

        <section className="mt-6 rounded-md border border-border bg-card">
          <div className="divide-y divide-border">
            {pageActivities.map((item) => {
              const Icon = iconForKind(item.kind);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item)}
                  className="grid w-full gap-3 px-4 py-4 text-left transition-colors hover:bg-accent/35 sm:grid-cols-[96px_32px_minmax(0,1fr)] md:grid-cols-[116px_32px_minmax(0,1fr)]"
                >
                  <time className="text-xs text-muted-foreground">{formatActivityTime(item.time)}</time>
                  <span className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{item.title}</span>
                    <span className="mt-1 block line-clamp-1 text-sm text-muted-foreground">{item.detail}</span>
                  </span>
                </button>
              );
            })}
            {loaded && loadError && (
              <div className="px-4 py-10 text-sm text-muted-foreground">
                Vault could not load your activity. Check Settings → Health, then try again.
              </div>
            )}
            {loaded && !loadError && activities.length === 0 && (
              <div className="px-4 py-10 text-sm text-muted-foreground">
                No activity has been recorded yet.
              </div>
            )}
            {!loaded && (
              <div className="px-4 py-10 text-sm text-muted-foreground">Loading activity...</div>
            )}
          </div>
        </section>
        {activityTotal > PAGE_SIZE && (
          <nav className="mt-5 flex items-center justify-between" aria-label="Timeline pages">
            <button type="button" className="rounded-md border border-border bg-card px-3 py-2 text-sm disabled:opacity-50" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
              Previous
            </button>
            <span className="text-sm text-muted-foreground">Page {currentPage} of {totalPages}</span>
            <button type="button" className="rounded-md border border-border bg-card px-3 py-2 text-sm disabled:opacity-50" disabled={currentPage === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
              Next
            </button>
          </nav>
        )}
      </main>

      {activeItem ? <aside className="min-w-0 border-t border-border bg-card px-4 py-6 sm:px-6 xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)] xl:overflow-y-auto xl:border-l xl:border-t-0 xl:py-8">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Activity detail</h2>
          <Button variant="ghost" size="icon" aria-label="Close activity detail" onClick={() => setSelected(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        {
          <div className="mt-5">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[var(--cluster-sage)]" />
              <span className="text-sm font-medium">{labelForKind(activeItem.kind)}</span>
            </div>
            <h3 className="mt-6 break-words text-xl font-semibold leading-snug">{activeItem.title}</h3>
            <p className="mt-3 break-words text-sm leading-6 text-muted-foreground">{activeItem.detail}</p>
            <dl className="mt-7 divide-y divide-border border-y border-border text-sm">
              <Meta label="Time" value={formatActivityTime(activeItem.time)} />
              <Meta label="Type" value={labelForKind(activeItem.kind)} />
              <Meta label="Record" value={activeItem.id} />
            </dl>
            {activeItem.href && (
              <Link to={activeItem.href} className="mt-5 inline-flex text-sm text-primary hover:underline">
                Open related view
              </Link>
            )}
          </div>
        }
      </aside> : null}
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

function labelForKind(kind: "all" | ActivityKind) {
  return {
    all: "All",
    source: "Ingestion",
    chat: "Chat",
    cluster: "Clusters",
  }[kind];
}

function iconForKind(kind: ActivityKind) {
  return {
    source: FileText,
    chat: Bot,
    cluster: GitBranch,
  }[kind];
}

function formatActivityTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
