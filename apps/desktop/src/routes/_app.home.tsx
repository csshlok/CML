import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Clapperboard,
  File,
  FileCode2,
  FileText,
  Image as ImageIcon,
  Link2,
  Mail,
  Mic,
  Plus,
  Search,
  Send,
  Settings2,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  ProductSection,
  ProductSectionHeader,
  ProductSectionStack,
} from "@/components/product/Layout";
import type { Cluster, Source } from "@/lib/domain";
import {
  createChatSession,
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  type ChatSessionRecord,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/home")({
  head: () => ({ meta: [{ title: "Home" }] }),
  component: HomeView,
});

function HomeView() {
  const navigate = useNavigate();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [chats, setChats] = useState<ChatSessionRecord[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoadError(false);
        const vaultRows = await listVaults();
        const activeVault = vaultRows[0] ?? null;
        if (cancelled) return;
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
          setLoadError(true);
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

  const unsorted = sources
    .filter((source) => !source.clusterId && source.state !== "indexed")
    .slice(0, 4);
  const clusterMetrics = useMemo(() => {
    const metrics = new Map<string, { total: number; indexed: number }>();
    for (const source of sources) {
      if (!source.clusterId) continue;
      const current = metrics.get(source.clusterId) ?? { total: 0, indexed: 0 };
      current.total += 1;
      if (source.state === "indexed") current.indexed += 1;
      metrics.set(source.clusterId, current);
    }
    return metrics;
  }, [sources]);

  const activityItems = [
    ...recentSources.slice(0, 3).map((source) => ({
      id: `source:${source.id}`,
      kind: "source" as const,
      targetId: source.id,
      time: formatRelativeDay(source.updatedAt),
      title:
        source.state === "indexed" ? `Indexed ${source.title}` : `${source.state} ${source.title}`,
      state: source.state,
    })),
    ...chats.slice(0, 2).map((chat) => ({
      id: `chat:${chat.id}`,
      kind: "chat" as const,
      targetId: chat.id,
      time: formatRelativeDay(chat.updated_at),
      title: chat.title,
      state: null,
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
    <div className="vault-page-wash h-full overflow-y-auto">
      <main className="mx-auto w-full max-w-[1440px] min-w-0 px-4 py-6 sm:px-8 sm:py-10">
        <header className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="page-title break-words">Home</h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Your private AI memory, ready to search.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" className="gap-2" asChild>
              <Link to="/search"><Settings2 className="h-4 w-4" /> Search filters</Link>
            </Button>
          </div>
        </header>

        {loadError ? (
          <div className="mt-6 rounded-md border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
            Vault could not load your library. Check Settings → Health, then try again.
          </div>
        ) : null}

        <div className="mt-10 space-y-4">
          <section className="overflow-hidden rounded-md border border-border bg-border">
            <h2 className="sr-only">Quick actions</h2>
            <div className="grid gap-px sm:grid-cols-2 xl:grid-cols-4">
              <QuickAction
                icon={<FileText className="h-4 w-4" />}
                title="Add source"
                detail="Import files, links, or notes"
                href="/sources"
              />
              <QuickAction
                icon={<Plus className="h-4 w-4" />}
                title="New cluster"
                detail="Organize related memories"
                href="/clusters"
              />
              <QuickAction
                icon={<Search className="h-4 w-4" />}
                title="Run analysis"
                detail="Ask Vault to analyze a topic"
                href="/chat"
              />
              <QuickAction
                icon={<Mail className="h-4 w-4" />}
                title="Open inbox"
                detail="Review unprocessed sources"
                href="/sources"
                search={{ filter: "unsorted" }}
              />
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-3">
            <Textarea
              aria-label="Ask or search your memory"
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
            <div className="flex flex-wrap items-center gap-3 px-1 pb-1">
              <Button variant="outline" className="gap-2" asChild>
                <Link to="/sources"><Settings2 className="h-4 w-4" /> Browse sources</Link>
              </Button>
              <span className="ml-auto text-xs text-muted-foreground">Ctrl Enter to send</span>
              <Button size="icon" aria-label="Send prompt" onClick={() => void startChat()}>
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </section>
        </div>

        <ProductSectionStack className="mt-10 pb-10">
          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Panel title="Recent memories" action="View all" href="/sources">
              {recentSources.map((source) => (
                <MemoryRow
                  key={source.id}
                  source={source}
                  cluster={clusters.find((cluster) => cluster.id === source.clusterId)}
                />
              ))}
            </Panel>

            <Panel
              title="Unsorted sources"
              badge={unsorted.length}
              action="Review"
              href="/sources"
              search={{ filter: "unsorted" }}
            >
              {unsorted.map((source) => (
                <UnsortedRow key={source.id} source={source} />
              ))}
              {unsorted.length === 0 && (
                <div className="px-5 py-6 text-sm text-muted-foreground">
                  Nothing is waiting in your inbox.
                </div>
              )}
              <Link
                to="/sources"
                search={{ filter: "unsorted" }}
                className="flex min-h-12 items-center gap-2 px-5 py-3 text-sm text-primary hover:bg-accent/35"
              >
                Go to inbox <ArrowRight className="h-4 w-4" />
              </Link>
            </Panel>
          </div>

          <ProductSection>
            <ProductSectionHeader
              title="Suggested clusters"
              description="Spaces Vault has recently organized or updated."
              action={<Link to="/clusters" className="text-sm text-primary">View all</Link>}
            />
            <div className="grid gap-4 p-5 md:grid-cols-2 2xl:grid-cols-4">
            {clusters.slice(0, 4).map((cluster) => {
              const metrics = clusterMetrics.get(cluster.id) ?? { total: 0, indexed: 0 };
              const progress = metrics.total > 0 ? Math.round((metrics.indexed / metrics.total) * 100) : 0;
              return (
                <Link
                  key={cluster.id}
                  to="/clusters/$clusterId"
                  params={{ clusterId: cluster.id }}
                  className="rounded-md border border-border bg-background p-4 hover:bg-accent/45"
                  style={{ ["--cluster-accent" as string]: `var(--cluster-${cluster.tint})` }}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[var(--cluster-accent)]/15 text-[var(--cluster-accent)]">
                      <Sparkles className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 break-words text-sm font-semibold">
                        {cluster.name}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {metrics.total} sources <span className="px-1">/</span> {metrics.indexed} indexed
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`${cluster.name} indexing progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                    <span
                      className="block h-full rounded-full bg-[var(--cluster-accent)]"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </Link>
              );
            })}
            </div>
          </ProductSection>

          <ProductSection>
            <ProductSectionHeader
              title="Activity"
              description="The latest changes across your sources and conversations."
              action={<Link to="/timeline" className="text-sm text-primary">View all</Link>}
            />
            <div className="divide-y divide-border">
            {activityItems.map((item) => (
              <ActivityRow key={item.id} item={item} />
            ))}
            {activityItems.length === 0 && (
              <div className="px-5 py-8 text-sm text-muted-foreground">No recent activity yet.</div>
            )}
            </div>
          </ProductSection>
        </ProductSectionStack>
      </main>
    </div>
  );
}

function Panel({
  title,
  action,
  href,
  badge,
  search,
  children,
}: {
  title: string;
  action: string;
  href: "/sources" | "/clusters";
  badge?: number;
  search?: { filter: "unsorted" };
  children: ReactNode;
}) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title={title}
        meta={typeof badge === "number" ? (
          <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">{badge}</span>
        ) : null}
        action={<Link to={href} search={search} className="text-sm text-primary">{action}</Link>}
      />
      <div className="divide-y divide-border">{children}</div>
    </ProductSection>
  );
}

function MemoryRow({ source, cluster }: { source: Source; cluster?: Cluster }) {
  const Icon = sourceTypeIcons[source.type];
  return (
    <Link to="/sources" className="flex min-h-20 items-start gap-4 px-5 py-4 hover:bg-accent/35">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-[var(--status-issue)]/10 text-[var(--status-issue)]">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="break-words text-sm font-semibold">{source.title}</div>
        <div className="mt-1 line-clamp-2 break-words text-xs text-muted-foreground">
          {sourceSummaryText(source)}
        </div>
      </div>
      <span className="max-w-[36%] break-words text-right text-xs text-muted-foreground">
        {cluster?.name ?? sourceStateText(source)}
      </span>
    </Link>
  );
}

function UnsortedRow({ source }: { source: Source }) {
  const Icon = sourceTypeIcons[source.type];
  return (
    <div className="flex min-h-20 items-start gap-4 px-5 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="break-words text-sm font-semibold">{source.title}</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {source.type} <span className="px-1">/</span> {source.state}
        </div>
      </div>
      <span className="text-xs text-muted-foreground">{formatRelativeDay(source.updatedAt)}</span>
    </div>
  );
}

function QuickAction({
  icon,
  title,
  detail,
  href,
  search,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  href: "/sources" | "/clusters" | "/chat";
  search?: { filter: "unsorted" };
}) {
  return (
    <Link
      to={href}
      search={search}
      className="flex min-h-20 items-center gap-3 bg-card p-4 hover:bg-accent/45"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block break-words text-sm font-medium">{title}</span>
        <span className="block break-words text-xs text-muted-foreground">{detail}</span>
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

type ActivityItem = {
  id: string;
  kind: "source" | "chat";
  targetId: string;
  time: string;
  title: string;
  state: Source["state"] | null;
};

function ActivityRow({ item }: { item: ActivityItem }) {
  const content = (
    <>
      <time className="text-xs text-muted-foreground sm:text-sm">{item.time}</time>
      <span
        className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-background"
        style={{ background: activityColor(item.state) }}
        aria-hidden="true"
      />
      <span className="min-w-0">
        <span className="block break-words text-sm font-medium">{item.title}</span>
        <span className="mt-1 block text-xs text-muted-foreground">
          {item.kind === "chat" ? "Conversation" : sourceStateTextFromState(item.state)}
        </span>
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </>
  );

  const className =
    "grid min-h-[76px] grid-cols-[72px_12px_minmax(0,1fr)_16px] items-start gap-4 px-5 py-4 hover:bg-accent/35 sm:grid-cols-[112px_12px_minmax(0,1fr)_16px]";

  if (item.kind === "chat") {
    return (
      <Link to="/chat/$chatId" params={{ chatId: item.targetId }} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <Link to="/sources" search={{ source: item.targetId }} className={className}>
      {content}
    </Link>
  );
}

const sourceTypeIcons = {
  file: FileText,
  link: Link2,
  note: File,
  image: ImageIcon,
  audio: Mic,
  video: Clapperboard,
  code: FileCode2,
  external_transcript: Mic,
  external_artifact: FileText,
} satisfies Record<Source["type"], typeof FileText>;

function sourceSummaryText(source: Source) {
  if (source.state === "waiting") return "In queue to be indexed";
  if (source.state === "processing") return "Reading and indexing...";
  if (source.state === "failed") return "Indexing failed — open Sources to review";
  if (source.summary.trim()) return source.summary;
  const preview = source.preview.trim();
  if (!preview) return "Indexed and ready to search";
  return preview.length > 80 ? `${preview.slice(0, 80).trimEnd()}…` : preview;
}

function activityColor(state: Source["state"] | null) {
  if (state === "indexed") return "var(--status-ready)";
  if (state === "failed") return "var(--status-issue)";
  if (state === "waiting" || state === "processing") return "var(--status-learning)";
  return "var(--status-paused)";
}

function sourceStateText(source: Source) {
  if (source.state === "indexed") return "Indexed";
  if (source.state === "processing") return "Processing";
  if (source.state === "failed") return "Needs review";
  return "Waiting";
}

function sourceStateTextFromState(state: Source["state"] | null) {
  if (state === "indexed") return "Source indexed";
  if (state === "processing") return "Source processing";
  if (state === "failed") return "Source needs review";
  return "Source waiting";
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
