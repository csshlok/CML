import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Copy,
  FileText,
  Image as ImageIcon,
  Loader2,
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
import { copyElementToFigma } from "@/lib/figmaExport";

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
  const [figmaExporting, setFigmaExporting] = useState(false);
  const [canExportToFigma, setCanExportToFigma] = useState(false);

  useEffect(() => {
    setCanExportToFigma(import.meta.env.DEV && !window.cmlDesktop);
  }, []);

  async function exportHomeScreenToFigma() {
    setFigmaExporting(true);

    try {
      await copyElementToFigma({
        element: document.body,
        name: "Vault Home",
      });

      window.alert("Copied Home screen to clipboard. Now paste it into Figma.");
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Could not copy the Home screen to Figma.");
    } finally {
      setFigmaExporting(false);
    }
  }

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

  const unsorted = sources.filter((source) => !source.clusterId).slice(0, 4);
  const indexedCount = sources.filter((source) => source.state === "indexed").length;
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
      time: formatRelativeDay(source.updatedAt),
      title:
        source.state === "indexed" ? `Indexed ${source.title}` : `${source.state} ${source.title}`,
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
    <div className="vault-page-wash h-full overflow-y-auto">
      <main className="mx-auto w-full max-w-[1440px] min-w-0 px-4 py-6 sm:px-8 sm:py-10">
        <header className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="page-title break-words">Mind</h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Your private AI memory, ready to search.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {canExportToFigma && (
              <Button
                type="button"
                variant="outline"
                className="gap-2"
                onClick={() => void exportHomeScreenToFigma()}
                disabled={figmaExporting}
              >
                {figmaExporting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                Copy to Figma
              </Button>
            )}

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

        <section className="mt-10 overflow-hidden rounded-md border border-border bg-border">
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
            />
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-card p-3">
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="break-words text-lg font-medium">Suggested clusters</h2>
            <Link to="/clusters" className="text-sm text-primary">
              View all
            </Link>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {clusters.slice(0, 4).map((cluster) => {
              const metrics = clusterMetrics.get(cluster.id) ?? { total: 0, indexed: 0 };
              const progress = metrics.total > 0 ? Math.round((metrics.indexed / metrics.total) * 100) : 0;
              return (
                <Link
                  key={cluster.id}
                  to="/clusters/$clusterId"
                  params={{ clusterId: cluster.id }}
                  className="rounded-md border border-border bg-background p-3 hover:bg-accent/45"
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
        </section>

        <section className="mt-4 rounded-md border border-border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-medium">Activity</h2>
            <Link to="/timeline" className="text-sm text-primary">
              View all
            </Link>
          </div>
          <div className="mt-5 grid gap-x-8 gap-y-5 border-l border-border pl-4 md:grid-cols-2">
            {activityItems.map((item) => (
              <div key={item.id} className="relative text-sm">
                <span className="absolute -left-[18px] top-1.5 h-2 w-2 rounded-full bg-[var(--cluster-sage)]" />
                <div className="text-muted-foreground">{item.time}</div>
                <div className="mt-1 break-words">{item.title}</div>
              </div>
            ))}
            {activityItems.length === 0 && (
              <div className="text-sm text-muted-foreground">No recent activity yet.</div>
            )}
          </div>
        </section>
      </main>
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
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="break-words text-lg font-medium">
          {title}{" "}
          {typeof badge === "number" && (
            <span className="ml-2 rounded bg-muted px-1.5 text-sm text-muted-foreground">
              {badge}
            </span>
          )}
        </h2>
        <Link to={href} className="text-sm text-primary">
          {action}
        </Link>
      </div>
      <div className="divide-y divide-border">{children}</div>
    </section>
  );
}

function MemoryRow({ source, cluster }: { source: Source; cluster?: Cluster }) {
  return (
    <div className="flex items-start gap-4 px-4 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-[var(--status-issue)]/10 text-[var(--status-issue)]">
        <FileText className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="break-words text-sm font-semibold">{source.title}</div>
        <div className="mt-1 line-clamp-2 break-words text-xs text-muted-foreground">
          {source.summary || source.preview || "Key memory summary will appear after indexing."}
        </div>
      </div>
      <span className="max-w-[36%] break-words text-right text-xs text-muted-foreground">
        {cluster?.name ?? sourceStateText(source)}
      </span>
    </div>
  );
}

function UnsortedRow({ source, index }: { source: Source; index: number }) {
  const icons = [Mic, FileText, ImageIcon, Mic];
  const Icon = icons[index % icons.length];
  return (
    <div className="flex items-start gap-4 px-4 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="break-words text-sm font-semibold">{source.title}</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {source.type} <span className="px-1">/</span> {source.state}
        </div>
      </div>
      <span className="text-xs text-muted-foreground">{index === 0 ? "Today" : "Yesterday"}</span>
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
    <Link to={href} className="flex min-h-20 items-center gap-3 bg-card p-4 hover:bg-accent/45">
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

function sourceStateText(source: Source) {
  if (source.state === "indexed") return "Indexed";
  if (source.state === "processing") return "Processing";
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
