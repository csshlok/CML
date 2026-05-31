import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Bot, Cable, CheckCircle2, Clock3, FileText, GitBranch, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useStore, type Cluster, type Source } from "@/lib/mockStore";
import {
  getJobStatus,
  listBridgeRequests,
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  type AppJobRecord,
  type BridgeRequest,
  type ChatSessionRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord, sourceStateText } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/timeline")({
  head: () => ({ meta: [{ title: "Timeline" }] }),
  component: TimelineRoute,
});

type ActivityKind = "source" | "chat" | "cluster" | "bridge" | "job";

type ActivityItem = {
  id: string;
  kind: ActivityKind;
  time: string;
  title: string;
  detail: string;
  href?: string;
};

export function TimelineRoute() {
  const mock = useStore();
  const [sources, setSources] = useState<Source[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [chats, setChats] = useState<ChatSessionRecord[]>([]);
  const [bridge, setBridge] = useState<BridgeRequest[]>([]);
  const [jobs, setJobs] = useState<AppJobRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<"all" | ActivityKind>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ActivityItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const vault = (await listVaults())[0] ?? null;
        if (!vault) return;
        const [sourceRows, clusterRows, chatRows, bridgeRows, jobRows] = await Promise.all([
          listSources(vault.id),
          listClusters(vault.id),
          listChatSessions(vault.id),
          listBridgeRequests(),
          getJobStatus().catch(() => null),
        ]);
        if (cancelled) return;
        setSources(sourceRows.map(sourceFromRecord));
        setClusters(clusterRows.map(clusterFromRecord));
        setChats(chatRows);
        setBridge(bridgeRows);
        setJobs(jobRows?.latest ?? []);
      } catch {
        if (!cancelled) {
          setSources(mock.sources);
          setClusters(mock.clusters);
          setJobs([]);
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [mock.clusters, mock.sources]);

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
        detail: chat.scope_cluster_id ? "Cluster chat session" : "Vault-wide chat session",
        href: `/chat/${chat.id}`,
      })),
      ...bridge.map((request) => ({
        id: `bridge:${request.id}`,
        kind: "bridge" as const,
        time: request.created_at,
        title: `Bridge request from ${request.client_name || "external client"}`,
        detail: request.query || "Context request processed.",
        href: "/bridge",
      })),
      ...jobs.map((job) => ({
        id: `job:${job.id}`,
        kind: "job" as const,
        time: job.updated_at || job.created_at,
        title: jobTitle(job),
        detail: job.status_detail || job.last_error || job.job_type.replace(/_/g, " "),
        href: "/tasks",
      })),
    ];
    const normalized = query.trim().toLowerCase();
    return rows
      .filter((item) => filter === "all" || item.kind === filter)
      .filter((item) => !normalized || `${item.title} ${item.detail}`.toLowerCase().includes(normalized))
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
  }, [bridge, chats, clusters, filter, jobs, query, sources]);

  const activeItem = selected ?? activities[0] ?? null;

  return (
    <div className="vault-page-wash grid h-full grid-cols-[minmax(0,1fr)_320px] overflow-hidden bg-background">
      <main className="min-w-0 overflow-y-auto px-8 py-8">
        <header className="border-b border-border pb-6">
          <h1 className="page-title">Timeline</h1>
          <p className="mt-2 text-sm text-muted-foreground">Everything Vault processed, indexed, changed, and answered.</p>
          <div className="mt-6 grid gap-3 md:grid-cols-[1fr_auto]">
            <div className="relative max-w-xl">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-9" placeholder="Search activity..." value={query} onChange={(event) => setQuery(event.target.value)} />
            </div>
            <div className="flex flex-wrap gap-1">
              {(["all", "source", "chat", "cluster", "bridge", "job"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setFilter(item)}
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
            {activities.map((item) => {
              const Icon = iconForKind(item.kind);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item)}
                  className="grid w-full gap-4 px-4 py-4 text-left transition-colors hover:bg-accent/35 md:grid-cols-[116px_32px_1fr]"
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
            {loaded && activities.length === 0 && (
              <div className="px-4 py-10 text-sm text-muted-foreground">
                No backend activity has been recorded yet.
              </div>
            )}
            {!loaded && (
              <div className="px-4 py-10 text-sm text-muted-foreground">Loading activity...</div>
            )}
          </div>
        </section>
      </main>

      <aside className="right-panel px-6 py-8">
        <h2 className="text-sm font-semibold">Activity detail</h2>
        {activeItem ? (
          <div className="mt-5">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[var(--cluster-sage)]" />
              <span className="text-sm font-medium">{labelForKind(activeItem.kind)}</span>
            </div>
            <h3 className="mt-6 text-xl font-semibold leading-snug">{activeItem.title}</h3>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{activeItem.detail}</p>
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

function jobTitle(job: AppJobRecord) {
  const label = job.job_type
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
  return `${label || "Job"} ${job.status}`;
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="truncate text-right">{value}</dd>
    </div>
  );
}

function labelForKind(kind: "all" | ActivityKind) {
  return {
    all: "All",
    source: "Ingestion",
    chat: "Chat",
    cluster: "Clusters",
    bridge: "Bridge",
    job: "Jobs",
  }[kind];
}

function iconForKind(kind: ActivityKind) {
  return {
    source: FileText,
    chat: Bot,
    cluster: GitBranch,
    bridge: Cable,
    job: CheckCircle2,
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
