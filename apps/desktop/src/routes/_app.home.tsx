import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
  Image as ImageIcon,
  Mail,
  MessageSquare,
  Mic,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Cluster, Source } from "@/lib/mockStore";
import {
  createChatSession,
  getJobStatus,
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  type ChatSessionRecord,
  type JobQueueStatus,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/home")({
  head: () => ({ meta: [{ title: "Home" }] }),
  component: HomeView,
});

export function HomeView() {
  const navigate = useNavigate();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [chats, setChats] = useState<ChatSessionRecord[]>([]);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const vaultRows = await listVaults();
        const activeVault = vaultRows[0] ?? null;
        const jobRows = await getJobStatus().catch(() => null);
        if (cancelled) return;
        setJobs(jobRows);
        if (!activeVault) return;
        const [sourceRows, clusterRows, chatRows] = await Promise.all([
          listSources(activeVault.id),
          listClusters(activeVault.id),
          listChatSessions(activeVault.id),
        ]);
        if (cancelled) return;
        setVault(activeVault);
        setSources(sourceRows.map(sourceFromRecord));
        setClusters(clusterRows.map(clusterFromRecord));
        setChats(chatRows);
      } catch {
        if (!cancelled) {
          setSources([]);
          setClusters([]);
          setChats([]);
        }
      }
    }

    void load();
    const id = window.setInterval(load, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const recentSources = useMemo(
    () =>
      [...sources]
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
        .slice(0, 5),
    [sources],
  );
  const unsorted = sources.filter((source) => !source.clusterId).slice(0, 4);
  const indexedCount = sources.filter((source) => source.state === "indexed").length;
  const activeJobs = (jobs?.running ?? 0) + (jobs?.queued ?? 0);
  const activityItems = [
    ...recentSources.slice(0, 3).map((source) => ({
      id: `source:${source.id}`,
      time: formatRelativeDay(source.updatedAt),
      title: source.state === "indexed" ? `Indexed ${source.title}` : `${source.state} ${source.title}`,
    })),
    ...chats.slice(0, 2).map((chat) => ({
      id: `chat:${chat.id}`,
      time: formatRelativeDay(chat.updated_at),
      title: chat.title,
    })),
  ];

  async function startChat() {
    const text = query.trim();
    if (vault) {
      const session = await createChatSession({ vault_id: vault.id, title: text || "New chat" });
      if (text) window.sessionStorage.setItem(`cml.pendingPrompt.${session.id}`, text);
      navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
      return;
    }
    navigate({ to: "/chat" });
  }

  return (
    <div className="vault-page-wash grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[1fr_326px]">
      <main className="min-w-0 overflow-y-auto px-8 py-10">
        <header className="flex items-start justify-between gap-6">
          <div>
            <h1 className="page-title">Mind</h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Your private AI memory, ready to search.
            </p>
          </div>
          <Button variant="outline" className="gap-2">
            <Settings2 className="h-4 w-4" /> Filters
          </Button>
        </header>

        <section className="mt-16 rounded-md border border-border bg-card p-3">
          <Textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask anything or search your memory..."
            className="min-h-[108px] resize-none border-0 bg-transparent p-3 text-base shadow-none focus-visible:ring-0"
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void startChat();
              }
            }}
          />
          <div className="flex items-center gap-3 px-1 pb-1">
            <Button variant="outline" className="gap-2">
              <Settings2 className="h-4 w-4" /> All sources
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">Ctrl Enter to send</span>
            <Button size="icon" aria-label="Send prompt" onClick={() => void startChat()}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </section>

        <section className="mt-8 grid gap-4 xl:grid-cols-2">
          <Panel title="Recent memories" action="View all" href="/sources">
            {recentSources.map((source) => (
              <MemoryRow
                key={source.id}
                source={source}
                cluster={clusters.find((cluster) => cluster.id === source.clusterId)}
              />
            ))}
          </Panel>

          <Panel title="Unsorted sources" badge={unsorted.length} action="Review" href="/sources">
            {(unsorted.length > 0 ? unsorted : sources.slice(0, 4)).map((source, index) => (
              <UnsortedRow key={source.id} source={source} index={index} />
            ))}
            <Link to="/sources" className="flex items-center gap-2 px-4 py-3 text-sm text-primary">
              Go to inbox <ArrowRight className="h-4 w-4" />
            </Link>
          </Panel>
        </section>

        <section className="mt-4 rounded-md border border-border/80 bg-card/95 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium">Suggested clusters</h2>
            <Link to="/clusters" className="text-sm text-primary">View all</Link>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {clusters.slice(0, 4).map((cluster) => {
              const count = sources.filter((source) => source.clusterId === cluster.id).length;
              return (
                <Link
                  key={cluster.id}
                  to="/clusters/$clusterId"
                  params={{ clusterId: cluster.id }}
                  className="rounded-md border border-border bg-background p-3 hover:bg-accent/45"
                  style={{ ["--cluster-accent" as string]: `var(--cluster-${cluster.tint})` }}
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[var(--cluster-accent)]/15 text-[var(--cluster-accent)]">
                      <Sparkles className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">{cluster.name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {count} sources <span className="px-1">/</span> {Math.max(64, count * 64)} memories
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 h-1 rounded-full bg-muted">
                    <span
                      className="block h-full rounded-full bg-[var(--cluster-accent)]"
                      style={{ width: `${Math.max(18, count * 18)}%` }}
                    />
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      </main>

      <aside className="hidden overflow-y-auto border-l border-border bg-card/35 px-6 py-8 xl:block">
        <section className="rounded-md border border-border bg-background p-4">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-medium">Today's health</h2>
              <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--status-ready)]" />
                Good
              </div>
            </div>
            <div className="h-10 w-10 rounded-full border-4 border-[var(--status-ready)]/80 border-r-muted" />
          </div>
          <div className="mt-6 space-y-4 border-t border-border pt-5">
            <HealthRow icon={<ShieldCheck className="h-4 w-4" />} label="Vault" value="Healthy" />
            <HealthRow icon={<Database className="h-4 w-4" />} label="Database" value="Healthy" />
            <HealthRow icon={<CheckCircle2 className="h-4 w-4" />} label="Embeddings" value="Healthy" />
            <HealthRow icon={<MessageSquare className="h-4 w-4" />} label="Model" value="Ready" />
            <HealthRow icon={<FileText className="h-4 w-4" />} label="Jobs" value={`${activeJobs} running`} />
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-background p-4">
          <h2 className="text-lg font-medium">Quick actions</h2>
          <div className="mt-4 space-y-4">
            <QuickAction icon={<FileText className="h-4 w-4" />} title="Add source" detail="Import files, links, or notes" href="/sources" />
            <QuickAction icon={<Plus className="h-4 w-4" />} title="New cluster" detail="Organize related memories" href="/clusters" />
            <QuickAction icon={<Search className="h-4 w-4" />} title="Run analysis" detail="Ask Vault to analyze a topic" href="/chat" />
            <QuickAction icon={<Mail className="h-4 w-4" />} title="Open inbox" detail="Review unprocessed sources" href="/sources" />
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-background p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium">Activity</h2>
            <Link to="/activity" className="text-sm text-primary">View all</Link>
          </div>
          <div className="mt-5 space-y-4 border-l border-border pl-4">
            {activityItems.map((item) => (
              <div key={item.id} className="relative text-sm">
                <span className="absolute -left-[18px] top-1.5 h-2 w-2 rounded-full bg-[var(--cluster-sage)]" />
                <div className="text-muted-foreground">{item.time}</div>
                <div className="mt-1">{item.title}</div>
              </div>
            ))}
            {activityItems.length === 0 && (
              <div className="text-sm text-muted-foreground">No recent activity yet.</div>
            )}
          </div>
        </section>
      </aside>
    </div>
  );
}

function Panel({
  title,
  action,
  href,
  badge,
  children,
}: {
  title: string;
  action: string;
  href: "/sources" | "/clusters";
  badge?: number;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-lg font-medium">
          {title} {typeof badge === "number" && <span className="ml-2 rounded bg-muted px-1.5 text-sm text-muted-foreground">{badge}</span>}
        </h2>
        <Link to={href} className="text-sm text-primary">{action}</Link>
      </div>
      <div className="divide-y divide-border">{children}</div>
    </section>
  );
}

function MemoryRow({ source, cluster }: { source: Source; cluster?: Cluster }) {
  return (
    <div className="flex items-center gap-4 px-4 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-[var(--status-issue)]/10 text-[var(--status-issue)]">
        <FileText className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{source.title}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">
          {source.summary || source.preview || "Key memory summary will appear after indexing."}
        </div>
      </div>
      <span className="text-xs text-muted-foreground">{cluster?.name ?? sourceStateText(source)}</span>
    </div>
  );
}

function UnsortedRow({ source, index }: { source: Source; index: number }) {
  const icons = [Mic, FileText, ImageIcon, Mic];
  const Icon = icons[index % icons.length];
  return (
    <div className="flex items-center gap-4 px-4 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{source.title}</div>
        <div className="mt-1 text-xs text-muted-foreground">{source.type} <span className="px-1">/</span> {source.state}</div>
      </div>
      <span className="text-xs text-muted-foreground">{index === 0 ? "Today" : "Yesterday"}</span>
    </div>
  );
}

function HealthRow({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="flex items-center gap-3 text-muted-foreground">{icon}{label}</span>
      <span className="text-primary">{value}</span>
    </div>
  );
}

function QuickAction({
  icon,
  title,
  detail,
  href,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  href: "/sources" | "/clusters" | "/chat";
}) {
  return (
    <Link to={href} className="flex items-center gap-3 rounded-md p-1.5 hover:bg-accent/45">
      <span className="flex h-9 w-9 items-center justify-center rounded-md bg-muted text-primary">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">{detail}</span>
      </span>
      <ArrowRight className="h-4 w-4 text-muted-foreground" />
    </Link>
  );
}

function sourceStateText(source: Source) {
  if (source.state === "indexed") return "Indexed";
  if (source.state === "extracting") return "Processing";
  if (source.state === "failed") return "Needs review";
  return "Waiting";
}

function formatRelativeDay(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}
