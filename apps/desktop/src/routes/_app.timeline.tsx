import { createFileRoute, Link } from "@tanstack/react-router";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Bot, FileText, GitBranch, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { Cluster, Source } from "@/lib/domain";
import {
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  type ChatSessionRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord, sourceStateText } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/timeline")({
  head: () => ({ meta: [{ title: "Timeline" }] }),
  component: TimelineRoute,
});

type ActivityKind = "source" | "chat" | "cluster";

type ActivityItem = {
  id: string;
  kind: ActivityKind;
  time: string;
  title: string;
  detail: string;
  href?: string;
};
const PAGE_SIZE = 100;

function TimelineRoute() {
  const [sources, setSources] = useState<Source[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [chats, setChats] = useState<ChatSessionRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState<"all" | ActivityKind>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ActivityItem | null>(null);
  const [page, setPage] = useState(1);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoadError(false);
        const vault = (await listVaults())[0] ?? null;
        if (!vault) return;
        const [sourceRows, clusterRows, chatRows] = await Promise.all([
          listSources(vault.id),
          listClusters(vault.id),
          listChatSessions(vault.id),
        ]);
        if (cancelled) return;
        setSources(sourceRows.map(sourceFromRecord));
        setClusters(clusterRows.map(clusterFromRecord));
        setChats(chatRows);
      } catch {
        if (!cancelled) {
          setSources([]);
          setClusters([]);
          setLoadError(true);
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const activities = useMemo(() => {
    const rows: ActivityItem[] = [
      ...sources.map((source) => ({
        id: `source:${source.id}`,
        kind: "source" as const,
        time: source.updatedAt,
        title: source.state === "indexed" ? `Indexed ${source.title}` : `${sourceStateText(source.state)} ${source.title}`,
        detail: source.summary || source.preview || "Source metadata updated.",
        href: "/sources",
      })),
      ...clusters.map((cluster) => ({
        id: `cluster:${cluster.id}`,
        kind: "cluster" as const,
        time: cluster.lastActive,
        title: `${cluster.name} updated`,
        detail: cluster.summary || cluster.description || "Cluster memory changed.",
        href: `/clusters/${cluster.id}`,
      })),
      ...chats.map((chat) => ({
        id: `chat:${chat.id}`,
        kind: "chat" as const,
        time: chat.updated_at,
        title: chat.title,
        detail: chat.scope_cluster_id ? "Cluster chat session" : "Library-wide chat session",
        href: `/chat/${chat.id}`,
      })),
    ];
    const normalized = deferredQuery.trim().toLowerCase();
    return rows
      .filter((item) => filter === "all" || item.kind === filter)
      .filter((item) => !normalized || `${item.title} ${item.detail}`.toLowerCase().includes(normalized))
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
  }, [chats, clusters, deferredQuery, filter, sources]);

  const totalPages = Math.max(1, Math.ceil(activities.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageActivities = activities.slice(pageStart, pageStart + PAGE_SIZE);
  const activeItem = activities.find((item) => item.id === selected?.id) ?? pageActivities[0] ?? null;

  return (
    <div className="vault-page-wash grid h-full grid-cols-1 overflow-y-auto bg-background xl:grid-cols-[minmax(0,1fr)_320px] xl:overflow-hidden">
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 xl:overflow-y-auto">
        <header className="border-b border-border pb-6">
          <h1 className="page-title">Timeline</h1>
          <p className="mt-2 text-sm text-muted-foreground">Your source, cluster, and conversation history. Operational work stays in Tasks; external access stays in Bridge.</p>
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
        </header>

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
        {activities.length > PAGE_SIZE && (
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

      <aside className="min-w-0 border-t border-border bg-card px-4 py-6 sm:px-6 xl:w-[var(--panel-width)] xl:min-w-[var(--panel-width)] xl:overflow-y-auto xl:border-l xl:border-t-0 xl:py-8">
        <h2 className="text-sm font-semibold">Activity detail</h2>
        {activeItem ? (
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
        ) : (
          <p className="mt-5 text-sm text-muted-foreground">No activity yet.</p>
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
