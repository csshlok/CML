import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Search,
  X,
} from "lucide-react";
import {
  useStore,
  type Cluster,
  type Source,
} from "@/lib/mockStore";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  getCluster,
  listChatSessions,
  listClusterExpertArtifacts,
  listClusterExpertJobs,
  listSources,
  type ChatSessionRecord,
  type ClusterExpertJobRecord,
  type ExpertArtifactRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters/$clusterId")({
  head: () => ({ meta: [{ title: "Cluster" }] }),
  component: ClusterDetail,
});

const tabs = ["Overview", "Sources", "Chats", "Memory profile", "Map"] as const;

function ClusterDetail() {
  const { clusterId } = Route.useParams();
  const navigate = useNavigate();
  const { clusters, sources, chats, createChat } = useStore();
  const [backendCluster, setBackendCluster] = useState<Cluster | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendVaultId, setBackendVaultId] = useState<string | null>(null);
  const [expertJobs, setExpertJobs] = useState<ClusterExpertJobRecord[]>([]);
  const [expertArtifacts, setExpertArtifacts] = useState<ExpertArtifactRecord[]>([]);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Overview");

  const mockCluster = clusters.find((cluster) => cluster.id === clusterId) ?? clusters[0] ?? null;
  const cluster = backendCluster ?? mockCluster;
  const activeSources = backendCluster ? backendSources : sources;
  const clusterSources = cluster
    ? activeSources.filter((source) => source.clusterId === cluster.id)
    : [];
  const clusterChats = backendCluster
    ? backendChats
    : chats.filter((chat) => chat.scopeClusterId === cluster?.id);

  useEffect(() => {
    let cancelled = false;
    async function loadBackendCluster() {
      try {
        const clusterRow = await getCluster(clusterId);
        const nextCluster = clusterFromRecord(clusterRow);
        const [sourceRows, chatRows, jobRows, artifactRows] = await Promise.all([
          listSources(clusterRow.vault_id),
          listChatSessions(clusterRow.vault_id),
          listClusterExpertJobs(clusterRow.id).catch(() => []),
          listClusterExpertArtifacts(clusterRow.id).catch(() => []),
        ]);
        if (cancelled) return;
        setBackendVaultId(clusterRow.vault_id);
        setBackendCluster(nextCluster);
        setBackendSources(sourceRows.map(sourceFromRecord));
        setBackendChats(chatRows.filter((chat) => chat.scope_cluster_id === clusterRow.id));
        setExpertJobs(jobRows);
        setExpertArtifacts(artifactRows);
      } catch {
        if (!cancelled) {
          setBackendCluster(null);
          setBackendVaultId(null);
          setBackendSources([]);
          setBackendChats([]);
        }
      }
    }

    void loadBackendCluster();
    return () => {
      cancelled = true;
    };
  }, [clusterId]);

  const topMemories = useMemo(
    () => [
      ["Design principles for calm interfaces", "Aarron Walter - Designing for Emotion", "Today"],
      ["North Star Metric framework", "Amplitude - Product Analytics Guide", "Yesterday"],
      ["Sleep is the multiplier", "Why We Sleep - Matthew Walker", "May 30"],
      ["Information hierarchy in UI", "IDEO - Field Guide to Human Centered Design", "May 28"],
      ["Progressive disclosure patterns", "Nielsen Norman Group", "May 27"],
    ],
    [],
  );

  if (!cluster) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Cluster not found.
      </div>
    );
  }

  async function openClusterChat() {
    if (backendCluster && backendVaultId) {
      const session = await createChatSession({
        vault_id: backendVaultId,
        title: `${backendCluster.name} chat`,
        scope_cluster_id: backendCluster.id,
      });
      navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
      return;
    }
    const chat = createChat(cluster.id);
    navigate({ to: "/chat/$chatId", params: { chatId: chat.id } });
  }

  return (
    <div className="vault-page-wash grid h-full grid-cols-[minmax(0,1fr)_326px] overflow-hidden">
      <main className="min-w-0 overflow-y-auto px-9 py-8">
        <Link to="/clusters" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Back to clusters
        </Link>

        <header className="mt-7 flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-[34px] font-semibold leading-tight">{cluster.name}</h1>
              <span className={`h-2.5 w-2.5 rounded-full bg-[var(--cluster-${cluster.tint})]`} />
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{cluster.description}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button className="gap-2 bg-primary text-primary-foreground" onClick={() => void openClusterChat()}>
              <MessageSquare className="h-4 w-4" />
              Chat with cluster
            </Button>
            <Button variant="outline" className="gap-2">
              <Plus className="h-4 w-4" />
              Add source
            </Button>
            <Button variant="outline" size="icon" aria-label="More cluster actions">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </div>
        </header>

        <nav className="mt-8 flex gap-8 border-b border-border text-sm">
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`relative pb-4 ${activeTab === tab ? "text-foreground" : "text-muted-foreground"}`}
            >
              {tab}
              {activeTab === tab && (
                <span className="absolute inset-x-0 bottom-[-1px] h-px bg-primary" />
              )}
            </button>
          ))}
        </nav>

        {activeTab === "Overview" && (
          <section className="mt-7">
            <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Summary</h2>
            <p className="mt-4 max-w-3xl text-sm leading-7">
              A collection of notes, case studies, and inspiration about product design. Includes interface
              principles, patterns, research from leading teams, and personal observations across web and mobile
              products.
            </p>

            <div className="mt-8 grid gap-4 xl:grid-cols-2">
              <ReferenceTable
                title="Top memories"
                columns={["Memory", "Source", "Last seen"]}
                rows={topMemories}
                action="View all memories"
              />
              <ReferenceTable
                title="Recent sources"
                columns={["Source", "Added", "Memories"]}
                rows={(clusterSources.length ? clusterSources : activeSources).slice(0, 5).map((source, index) => [
                  source.title,
                  ["May 30, 2026", "May 29, 2026", "May 28, 2026", "May 26, 2026", "May 27, 2026"][index] ?? "May 30, 2026",
                  String([68, 42, 31, 24, 19][index] ?? 12),
                ])}
                action={`View all ${clusterSources.length || 68} sources`}
                fileIcons
              />
            </div>

            <LearningStatus cluster={cluster} sourceCount={clusterSources.length || 68} />

            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <RecentSources sources={(clusterSources.length ? clusterSources : activeSources).slice(0, 3)} />
              <RecentChats chats={clusterChats} />
            </div>
          </section>
        )}

        {activeTab !== "Overview" && (
          <section className="mt-7">
            <div className="flex items-center justify-between gap-4 border-b border-border pb-4">
              <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{activeTab}</h2>
              <div className="flex h-9 w-60 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
                <Search className="h-4 w-4" />
                Search {activeTab.toLowerCase()}
              </div>
            </div>
            <div className="mt-5 grid gap-3">
              {(clusterSources.length ? clusterSources : activeSources).slice(0, 8).map((source) => (
                <div key={source.id} className="grid grid-cols-[1fr_90px_80px] items-center gap-4 border-b border-border px-1 py-3 text-sm">
                  <span className="flex min-w-0 items-center gap-3">
                    <FileText className="h-4 w-4 text-[var(--status-issue)]" />
                    <span className="truncate">{source.title}</span>
                  </span>
                  <span className="text-muted-foreground">{source.type.toUpperCase()}</span>
                  <span className="text-right text-muted-foreground">{source.state}</span>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      <ClusterDetailRail cluster={cluster} sources={clusterSources.length ? clusterSources : activeSources} jobs={expertJobs} artifacts={expertArtifacts} />
    </div>
  );
}

function ReferenceTable({
  title,
  columns,
  rows,
  action,
  fileIcons,
}: {
  title: string;
  columns: string[];
  rows: string[][];
  action: string;
  fileIcons?: boolean;
}) {
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{title}</h3>
      <div className="mt-4 grid grid-cols-[1.4fr_1fr_72px] border-b border-border px-4 pb-3 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {columns.map((column) => <span key={column}>{column}</span>)}
      </div>
      <div className="divide-y divide-border">
        {rows.map((row) => (
          <div key={row.join(":")} className="grid grid-cols-[1.4fr_1fr_72px] items-center gap-4 px-4 py-3 text-sm">
            <span className="flex min-w-0 items-center gap-2">
              {fileIcons && <FileText className="h-4 w-4 shrink-0 text-[var(--status-issue)]" />}
              <span className="truncate">{row[0]}</span>
            </span>
            <span className="truncate text-muted-foreground">{row[1]}</span>
            <span className="text-right text-muted-foreground">{row[2]}</span>
          </div>
        ))}
      </div>
      <Link to="/sources" className="flex items-center gap-2 px-4 py-4 text-sm text-primary">
        {action} <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function LearningStatus({ cluster, sourceCount }: { cluster: Cluster; sourceCount: number }) {
  return (
    <section className="mt-4 rounded-md border border-border bg-card px-5 py-5">
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Learning status</h3>
      <div className="mt-5 grid gap-5 md:grid-cols-4">
        <StatusItem icon={<FileText className="h-6 w-6" />} label="Memory profile" value="Ready" meta="Updated May 30, 2026" />
        <StatusItem icon={<span className="h-7 w-7 rounded-full border-4 border-primary border-r-muted" />} label="Coverage" value="High" meta={`${sourceCount} / ${sourceCount} sources indexed`} />
        <StatusItem icon={<Clock3 className="h-6 w-6" />} label="Last updated" value="Today, 9:42 AM" meta="Automatic sync on" />
        <StatusItem icon={<Clock3 className="h-6 w-6" />} label="Next check" value="In 6 hours" meta="Background refresh" />
      </div>
      {cluster.expert === "learning" && (
        <div className="mt-4 text-xs text-muted-foreground">A local memory profile pass is running in the background.</div>
      )}
    </section>
  );
}

function StatusItem({ icon, label, value, meta }: { icon: ReactNode; label: string; value: string; meta: string }) {
  return (
    <div className="flex gap-4 border-r border-border pr-5 last:border-r-0">
      <span className="text-muted-foreground">{icon}</span>
      <span>
        <span className="block text-sm text-muted-foreground">{label}</span>
        <span className="mt-1 block text-base font-medium text-primary">{value}</span>
        <span className="mt-1 block text-xs text-muted-foreground">{meta}</span>
      </span>
    </div>
  );
}

function RecentSources({ sources }: { sources: Source[] }) {
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent sources</h3>
      <div className="mt-4 divide-y divide-border">
        {sources.map((source, index) => (
          <div key={source.id} className="grid grid-cols-[1fr_44px_92px_72px] items-center gap-4 px-4 py-3 text-sm">
            <span className="flex min-w-0 items-center gap-3">
              <FileText className="h-4 w-4 shrink-0 text-[var(--status-issue)]" />
              <span className="truncate">{source.title}</span>
            </span>
            <span className="rounded border border-border bg-muted px-1.5 py-0.5 text-center text-xs text-muted-foreground">PDF</span>
            <span className="text-muted-foreground">{["May 30, 2026", "May 29, 2026", "May 28, 2026"][index] ?? "May 30"}</span>
            <span className="text-right text-xs text-muted-foreground">{[68, 42, 31][index] ?? 18} memories</span>
          </div>
        ))}
      </div>
      <Link to="/sources" className="flex items-center gap-2 px-4 py-4 text-sm text-primary">
        View all sources <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function RecentChats({ chats }: { chats: Array<ChatSessionRecord | { id: string; title: string }> }) {
  const rows = chats.length
    ? chats
    : [
        { id: "mock-chat-1", title: "Q2 Planning Decisions" },
        { id: "mock-chat-2", title: "Interface Simplicity Discussion" },
        { id: "mock-chat-3", title: "Product Research Brainstorm" },
      ];
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent chats</h3>
      <div className="mt-4 divide-y divide-border">
        {rows.slice(0, 3).map((chat, index) => (
          <div key={chat.id} className="grid grid-cols-[1fr_48px_120px_20px] items-center gap-4 px-4 py-3 text-sm">
            <span className="flex min-w-0 items-center gap-3">
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{chat.title}</span>
            </span>
            <span className="text-muted-foreground">You</span>
            <span className="text-muted-foreground">{["May 30, 9:15 AM", "May 29, 7:34 PM", "May 28, 4:20 PM"][index]}</span>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </div>
        ))}
      </div>
      <Link to="/chat" className="flex items-center gap-2 px-4 py-4 text-sm text-primary">
        View all chats <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function ClusterDetailRail({
  cluster,
  sources,
  jobs,
  artifacts,
}: {
  cluster: Cluster;
  sources: Source[];
  jobs: ClusterExpertJobRecord[];
  artifacts: ExpertArtifactRecord[];
}) {
  return (
    <aside className="overflow-y-auto border-l border-border bg-card/35 px-6 py-8">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Cluster details</h2>
        <X className="h-4 w-4 text-muted-foreground" />
      </div>
      <MetricGrid className="mt-10" />
      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Activity</h3>
      <div className="mt-5 space-y-5 border-l border-border pl-4">
        {["Added 3 sources", "Extracted 42 memories", "Chat session", "Cluster summary updated", "Added 6 sources"].map((item, index) => (
          <div key={item} className="relative text-sm">
            <span className={`absolute -left-[19px] top-1.5 h-2 w-2 rounded-full ${index < 4 ? "bg-primary" : "bg-muted-foreground"}`} />
            <div className="text-muted-foreground">{["Today, 9:42 AM", "Today, 9:15 AM", "Yesterday, 11:08 PM", "May 29, 2026", "May 28, 2026"][index]}</div>
            <div className="mt-1">{item}</div>
          </div>
        ))}
      </div>
      <Link to="/activity" className="mt-6 flex items-center gap-2 text-sm text-primary">View all activity <ArrowRight className="h-4 w-4" /></Link>

      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Top sources</h3>
      <div className="mt-5 space-y-5">
        {sources.slice(0, 3).map((source, index) => (
          <div key={source.id} className="flex gap-3 text-sm">
            <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-issue)]" />
            <div>
              <div className="leading-5">{source.title}</div>
              <div className="mt-1 text-xs text-muted-foreground">{[68, 28, 24][index] ?? 18} memories</div>
            </div>
          </div>
        ))}
      </div>
      <Link to="/sources" className="mt-6 flex items-center gap-2 text-sm text-primary">View all {sources.length || 68} sources <ArrowRight className="h-4 w-4" /></Link>

      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Memory profile</h3>
      <section className="mt-4 rounded-md border border-border bg-background p-4">
        <div className="flex items-center gap-2 text-primary">
          <CheckCircle2 className="h-4 w-4" />
          <span className="font-medium">Ready</span>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Last updated May 30, 2026</p>
        <Button variant="outline" className="mt-4 w-full">View profile</Button>
      </section>
      {(jobs.length > 0 || artifacts.length > 0) && (
        <p className="mt-4 text-xs text-muted-foreground">
          {jobs.length} jobs / {artifacts.length} artifacts tracked for this cluster.
        </p>
      )}
    </aside>
  );
}

function MetricGrid({ className = "" }: { className?: string }) {
  return (
    <div className={`grid grid-cols-4 gap-4 ${className}`}>
      <Metric value="68" label="Sources" />
      <Metric value="1,284" label="Memories" />
      <Metric value="12.4k" label="Embeddings" />
      <Metric value="2.1 GB" label="Size" />
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-semibold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function Divider() {
  return <div className="my-8 h-px bg-border" />;
}
