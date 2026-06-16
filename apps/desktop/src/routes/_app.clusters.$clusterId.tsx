import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  Gauge,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Search,
  X,
} from "lucide-react";
import {
  type Cluster,
  type Source,
} from "@/lib/mockStore";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  getCluster,
  getClusterExpertStatus,
  listChatSessions,
  listClusterExpertArtifacts,
  listClusterExpertJobs,
  listSources,
  type ChatSessionRecord,
  type ClusterExpertJobRecord,
  type ClusterExpertStatusRecord,
  type ExpertArtifactRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters/$clusterId")({
  head: () => ({ meta: [{ title: "Cluster" }] }),
  component: ClusterDetail,
});

const tabs = ["Overview", "Sources", "Chats", "Expert", "Memory profile", "Map"] as const;

function ClusterDetail() {
  const { clusterId } = Route.useParams();
  const navigate = useNavigate();
  const [backendCluster, setBackendCluster] = useState<Cluster | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendVaultId, setBackendVaultId] = useState<string | null>(null);
  const [expertJobs, setExpertJobs] = useState<ClusterExpertJobRecord[]>([]);
  const [expertArtifacts, setExpertArtifacts] = useState<ExpertArtifactRecord[]>([]);
  const [expertStatus, setExpertStatus] = useState<ClusterExpertStatusRecord | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Overview");
  const [mounted, setMounted] = useState(false);

  const cluster = backendCluster;
  const activeSources = !mounted ? [] : backendSources;
  const clusterSources = cluster
    ? activeSources.filter((source) => source.clusterId === cluster.id)
    : [];
  const clusterChats = backendChats;

  useEffect(() => {
    let cancelled = false;
    setMounted(true);
    async function loadBackendCluster() {
      try {
        const clusterRow = await getCluster(clusterId);
        const nextCluster = clusterFromRecord(clusterRow);
        const [sourceRows, chatRows, jobRows, artifactRows] = await Promise.all([
          listSources(clusterRow.vault_id),
          listChatSessions(clusterRow.vault_id),
          listClusterExpertJobs(clusterRow.id).catch(() => []),
          listClusterExpertArtifacts(clusterRow.id).catch(() => []),
          getClusterExpertStatus(clusterRow.id).catch(() => null),
        ]);
        if (cancelled) return;
        setBackendVaultId(clusterRow.vault_id);
        setBackendCluster(nextCluster);
        setBackendSources(sourceRows.map(sourceFromRecord));
        setBackendChats(chatRows.filter((chat) => chat.scope_cluster_id === clusterRow.id));
        setExpertJobs(jobRows);
        setExpertArtifacts(artifactRows);
        setExpertStatus(statusRow);
      } catch {
        if (!cancelled) {
          setBackendCluster(null);
          setBackendVaultId(null);
          setBackendSources([]);
          setBackendChats([]);
          setExpertStatus(null);
        }
      }
    }

    void loadBackendCluster();
    return () => {
      cancelled = true;
    };
  }, [clusterId]);

  const topMemories = useMemo(
    () =>
      clusterSources.slice(0, 5).map((source) => [
        source.summary || source.preview || source.title,
        source.title,
        formatDate(source.updatedAt),
      ]),
    [clusterSources],
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
    navigate({ to: "/chat" });
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
              <h1 className="page-title">{cluster.name}</h1>
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
              {cluster.summary || cluster.description || "This memory space is ready for sources, chats, and local context."}
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
                rows={clusterSources.slice(0, 5).map((source) => [
                  source.title,
                  formatDate(source.updatedAt),
                  String(memoryEstimate(source)),
                ])}
                action={`View all ${clusterSources.length} sources`}
                fileIcons
              />
            </div>

            <LearningStatus cluster={cluster} sourceCount={clusterSources.length} />

            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <RecentSources sources={clusterSources.slice(0, 3)} />
              <RecentChats chats={clusterChats} />
            </div>
          </section>
        )}

        {activeTab === "Sources" && <ClusterSourcesPanel sources={clusterSources} />}
        {activeTab === "Chats" && <ClusterChatsPanel chats={clusterChats} />}
        {activeTab === "Expert" && (
          <ClusterExpertPanel
            cluster={cluster}
            status={expertStatus}
            artifacts={expertArtifacts}
            jobs={expertJobs}
            sourceCount={clusterSources.length}
          />
        )}
        {activeTab === "Memory profile" && (
          <ClusterMemoryProfile cluster={cluster} sources={clusterSources} artifacts={expertArtifacts} jobs={expertJobs} />
        )}
        {activeTab === "Map" && <ClusterPointMap cluster={cluster} sources={clusterSources} />}
      </main>

      <ClusterDetailRail cluster={cluster} sources={clusterSources} jobs={expertJobs} artifacts={expertArtifacts} />
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
        <StatusItem icon={<FileText className="h-6 w-6" />} label="Memory profile" value={sourceCount > 0 ? "Ready" : "Empty"} meta={`Updated ${formatDate(cluster.lastActive)}`} />
        <StatusItem icon={<span className="h-7 w-7 rounded-full border-4 border-primary border-r-muted" />} label="Coverage" value={`${sourceCount} sources`} meta={`${sourceCount} linked sources`} />
        <StatusItem icon={<Clock3 className="h-6 w-6" />} label="Last updated" value={formatDate(cluster.lastActive)} meta="Automatic sync on" />
        <StatusItem icon={<Clock3 className="h-6 w-6" />} label="Next check" value="Queued by backend" meta="Background refresh" />
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
        {sources.map((source) => (
          <div key={source.id} className="grid grid-cols-[1fr_44px_92px_72px] items-center gap-4 px-4 py-3 text-sm">
            <span className="flex min-w-0 items-center gap-3">
              <FileText className="h-4 w-4 shrink-0 text-[var(--status-issue)]" />
              <span className="truncate">{source.title}</span>
            </span>
            <span className="rounded border border-border bg-muted px-1.5 py-0.5 text-center text-xs text-muted-foreground">{source.type.toUpperCase()}</span>
            <span className="text-muted-foreground">{formatDate(source.updatedAt)}</span>
            <span className="text-right text-xs text-muted-foreground">{memoryEstimate(source)} memories</span>
          </div>
        ))}
        {sources.length === 0 && (
          <div className="px-4 py-10 text-sm text-muted-foreground">No recent sources yet.</div>
        )}
      </div>
      <Link to="/sources" className="flex items-center gap-2 px-4 py-4 text-sm text-primary">
        View all sources <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function RecentChats({ chats }: { chats: Array<ChatSessionRecord | { id: string; title: string }> }) {
  const rows = chats;
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent chats</h3>
      <div className="mt-4 divide-y divide-border">
        {rows.slice(0, 3).map((chat) => (
          <div key={chat.id} className="grid grid-cols-[1fr_48px_120px_20px] items-center gap-4 px-4 py-3 text-sm">
            <span className="flex min-w-0 items-center gap-3">
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{chat.title}</span>
            </span>
            <span className="text-muted-foreground">You</span>
            <span className="text-muted-foreground">{"updated_at" in chat ? formatDate(chat.updated_at) : ""}</span>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </div>
        ))}
        {rows.length === 0 && (
          <div className="px-4 py-10 text-sm text-muted-foreground">No scoped chats yet.</div>
        )}
      </div>
      <Link to="/chat" className="flex items-center gap-2 px-4 py-4 text-sm text-primary">
        View all chats <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function ClusterSourcesPanel({ sources }: { sources: Source[] }) {
  return (
    <section className="mt-7">
      <div className="flex items-center justify-between gap-4 border-b border-border pb-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Sources</h2>
        <div className="flex h-9 w-60 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
          <Search className="h-4 w-4" />
          Search sources
        </div>
      </div>
      <div className="mt-5 grid gap-3">
        {sources.map((source) => (
          <Link
            key={source.id}
            to="/sources"
            className="grid min-h-[74px] grid-cols-[minmax(0,1fr)_104px_112px] items-center gap-5 rounded-md border border-border bg-card px-4 py-3 text-sm hover:border-primary/40"
          >
            <span className="flex min-w-0 items-start gap-3">
              <FileText className="mt-1 h-4 w-4 shrink-0 text-[var(--cluster-sky)]" />
              <span className="min-w-0">
                <span className="block truncate font-medium">{source.title}</span>
                <span className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {source.summary || source.preview || "No extracted preview yet."}
                </span>
              </span>
            </span>
            <span className="text-muted-foreground">{source.type.toUpperCase()}</span>
            <span className="text-right text-muted-foreground">{source.state}</span>
          </Link>
        ))}
        {sources.length === 0 && (
          <div className="py-10 text-sm text-muted-foreground">No sources are linked to this cluster yet.</div>
        )}
      </div>
    </section>
  );
}

function ClusterChatsPanel({ chats }: { chats: Array<ChatSessionRecord | { id: string; title: string }> }) {
  return (
    <section className="mt-7">
      <div className="border-b border-border pb-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Chats</h2>
      </div>
      <div className="mt-5 grid gap-3">
        {chats.map((chat) => (
          <Link
            key={chat.id}
            to="/chat/$chatId"
            params={{ chatId: chat.id }}
            className="grid min-h-[62px] grid-cols-[minmax(0,1fr)_132px_20px] items-center gap-5 rounded-md border border-border bg-card px-4 py-3 text-sm hover:border-primary/40"
          >
            <span className="flex min-w-0 items-center gap-3">
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate font-medium">{chat.title}</span>
            </span>
            <span className="text-muted-foreground">{"updated_at" in chat ? formatDate(chat.updated_at) : ""}</span>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </Link>
        ))}
        {chats.length === 0 && <div className="py-10 text-sm text-muted-foreground">No scoped chats yet.</div>}
      </div>
    </section>
  );
}

function ClusterExpertPanel({
  cluster,
  status,
  artifacts,
  jobs,
  sourceCount,
}: {
  cluster: Cluster;
  status: ClusterExpertStatusRecord | null;
  artifacts: ExpertArtifactRecord[];
  jobs: ClusterExpertJobRecord[];
  sourceCount: number;
}) {
  const activeArtifact = artifacts.find((artifact) => artifact.active);
  const latestJob = jobs[0];
  const runtimeReady = Boolean(status?.runtime_load?.available);
  return (
    <section className="mt-7">
      <div className="flex items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Cluster expert</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Retrieval is available before training. The UI only shows a trained expert after adapter graduation passes.
          </p>
        </div>
        <span className="rounded-full border border-border bg-card px-3 py-1 text-sm">
          {status?.user_status || "Searchable now"}
        </span>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-md border border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold">Graduation state</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {status?.detail || "This cluster can answer through retrieval while local LoRA training is pending."}
              </p>
            </div>
            <Gauge className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-4">
            <Metric value={sourceCount.toLocaleString()} label="Sources" />
            <Metric value={status?.searchable ? "Yes" : "No"} label="Retrieval" />
            <Metric value={status?.trained ? "Yes" : "No"} label="Trained" />
            <Metric value={status?.stale ? "Yes" : "No"} label="Stale" />
          </div>
          <div className="mt-6 grid gap-3 text-xs text-muted-foreground">
            <HashRow label="Active dataset" value={status?.active_dataset_hash} />
            <HashRow label="Current dataset" value={status?.current_dataset_hash} />
            <HashRow label="Active artifact" value={status?.active_artifact_id || activeArtifact?.id} />
          </div>
        </section>

        <section className="rounded-md border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Runtime load</h3>
          <div className="mt-4 flex items-center gap-2 text-sm">
            <span className={`h-2 w-2 rounded-full ${runtimeReady ? "bg-primary" : "bg-muted-foreground"}`} />
            <span>{runtimeReady ? "Adapter load contract ready" : "Runtime smoke still required"}</span>
          </div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {status?.runtime_load?.detail || "Connect a real local inference runtime and run the adapter smoke before public trained-expert claims."}
          </p>
          {status?.failure_code && (
            <p className="mt-4 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
              Failure: {status.failure_code}
            </p>
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ExpertList title="Recent jobs" empty="No expert jobs yet.">
          {jobs.slice(0, 5).map((job) => (
            <ExpertListRow
              key={job.id}
              title={`${job.action} / ${job.status}`}
              detail={job.failure_code || job.detail || job.hardware_tier || "Queued by backend"}
              meta={formatDate(job.updated_at)}
            />
          ))}
        </ExpertList>
        <ExpertList title="Adapter artifacts" empty="No adapter artifacts yet.">
          {artifacts.slice(0, 5).map((artifact) => (
            <ExpertListRow
              key={artifact.id}
              title={`${artifact.status}${artifact.active ? " / active" : ""}`}
              detail={artifact.local_path || artifact.base_model || "No local path recorded"}
              meta={artifact.quality_score == null ? "No score" : `${artifact.quality_score.toFixed(1)} score`}
            />
          ))}
        </ExpertList>
      </div>

      {latestJob?.failure_code && (
        <p className="mt-4 text-xs text-muted-foreground">
          Latest blocked gate: {latestJob.failure_code}. Keep the cluster retrieval-backed until this is cleared.
        </p>
      )}
    </section>
  );
}

function HashRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-3">
      <span>{label}</span>
      <span className="truncate font-mono text-[11px] text-foreground">{value || "Not available"}</span>
    </div>
  );
}

function ExpertList({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{title}</h3>
      <div className="mt-4 divide-y divide-border">
        {hasChildren ? children : <div className="px-4 py-10 text-sm text-muted-foreground">{empty}</div>}
      </div>
    </section>
  );
}

function ExpertListRow({ title, detail, meta }: { title: string; detail: string; meta: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-4 px-4 py-3 text-sm">
      <span className="min-w-0">
        <span className="block truncate font-medium">{title}</span>
        <span className="mt-1 block truncate text-xs text-muted-foreground">{detail}</span>
      </span>
      <span className="text-right text-xs text-muted-foreground">{meta}</span>
    </div>
  );
}

function ClusterMemoryProfile({
  cluster,
  sources,
  artifacts,
  jobs,
}: {
  cluster: Cluster;
  sources: Source[];
  artifacts: ExpertArtifactRecord[];
  jobs: ClusterExpertJobRecord[];
}) {
  return (
    <section className="mt-7">
      <div className="border-b border-border pb-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Memory profile</h2>
      </div>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Profile state</h3>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {cluster.summary || cluster.description || "Ponytail has not generated a profile summary for this cluster yet."}
          </p>
          <div className="mt-5 grid grid-cols-3 gap-4">
            <Metric value={sources.length.toLocaleString()} label="Sources" />
            <Metric value={artifacts.length.toLocaleString()} label="Artifacts" />
            <Metric value={jobs.length.toLocaleString()} label="Jobs" />
          </div>
        </section>
        <section className="rounded-md border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Recent profile inputs</h3>
          <div className="mt-4 space-y-3">
            {sources.slice(0, 5).map((source) => (
              <div key={source.id} className="flex items-start gap-3 text-sm">
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--cluster-sage)]" />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{source.title}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{formatDate(source.updatedAt)}</span>
                </span>
              </div>
            ))}
            {sources.length === 0 && <div className="text-sm text-muted-foreground">No profile inputs yet.</div>}
          </div>
        </section>
      </div>
    </section>
  );
}

function ClusterPointMap({ cluster, sources }: { cluster: Cluster; sources: Source[] }) {
  const visibleSources = sources.slice(0, 180);
  const hiddenCount = Math.max(0, sources.length - visibleSources.length);
  const points = visibleSources.map((source, index) => {
    const angle = index * 2.399963;
    const ring = Math.floor(index / 24) + 1;
    const radius = Math.min(38, 8 + ring * 4.2);
    return {
      source,
      x: 50 + Math.cos(angle) * radius,
      y: 49 + Math.sin(angle) * Math.min(34, radius * 0.78),
    };
  });

  return (
    <section className="mt-7">
      <div className="flex items-center justify-between gap-4 border-b border-border pb-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Map</h2>
        <span className="text-sm text-muted-foreground">{sources.length.toLocaleString()} data points</span>
      </div>
      <div className="mt-5 grid gap-5 2xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="relative min-h-[620px] overflow-hidden rounded-md border border-border bg-card">
          <div
            className="absolute left-1/2 top-[49%] z-20 flex w-[190px] -translate-x-1/2 -translate-y-1/2 flex-col items-center rounded-md border bg-card px-5 py-4 text-center"
            style={{ borderColor: `var(--cluster-${cluster.tint})` }}
          >
            <span className={`h-2.5 w-2.5 rounded-full bg-[var(--cluster-${cluster.tint})]`} />
            <div className="mt-3 max-w-full truncate text-sm font-semibold">{cluster.name}</div>
            <div className="mt-1 text-xs text-muted-foreground">{sources.length} sources</div>
          </div>
          <svg className="absolute inset-0 h-full w-full" role="presentation">
            {points.map((point) => (
              <line
                key={point.source.id}
                x1="50%"
                y1="49%"
                x2={`${point.x}%`}
                y2={`${point.y}%`}
                stroke="var(--border-default)"
                strokeWidth="1"
              />
            ))}
          </svg>
          {points.map((point) => (
            <Link
              key={point.source.id}
              to="/sources"
              className="absolute z-30 block w-[164px] -translate-x-1/2 -translate-y-1/2 rounded-md border border-border bg-card px-3 py-2 text-left text-xs shadow-sm hover:border-primary/40"
              style={{ left: `${point.x}%`, top: `${point.y}%` }}
              title={point.source.title}
            >
              <span className="block truncate font-medium">{point.source.title}</span>
              <span className="mt-1 block truncate text-[11px] text-muted-foreground">
                {point.source.type} / {point.source.state}
              </span>
            </Link>
          ))}
          {sources.length === 0 && (
            <div className="absolute left-1/2 top-[62%] -translate-x-1/2 text-sm text-muted-foreground">
              This cluster has no linked data points yet.
            </div>
          )}
        </div>
        <aside className="max-h-[620px] overflow-y-auto rounded-md border border-border bg-card">
          <div className="sticky top-0 border-b border-border bg-card px-4 py-3 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Data points
          </div>
          <div className="divide-y divide-border">
            {sources.map((source) => (
              <Link key={source.id} to="/sources" className="block px-4 py-3 text-sm hover:bg-accent">
                <span className="block truncate font-medium">{source.title}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{source.type} / {formatDate(source.updatedAt)}</span>
              </Link>
            ))}
          </div>
          {hiddenCount > 0 && (
            <div className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
              Map shows {visibleSources.length} points. The list includes all {sources.length} sources.
            </div>
          )}
        </aside>
      </div>
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
    <aside className="right-panel px-6 py-8">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Cluster details</h2>
        <X className="h-4 w-4 text-muted-foreground" />
      </div>
      <MetricGrid className="mt-10" sources={sources.length} />
      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Activity</h3>
      <div className="mt-5 space-y-5 border-l border-border pl-4">
        {sources.slice(0, 5).map((source, index) => (
          <div key={source.id} className="relative text-sm">
            <span className={`absolute -left-[19px] top-1.5 h-2 w-2 rounded-full ${index < 4 ? "bg-primary" : "bg-muted-foreground"}`} />
            <div className="text-muted-foreground">{formatDate(source.updatedAt)}</div>
            <div className="mt-1">{source.state === "indexed" ? "Indexed" : source.state} {source.title}</div>
          </div>
        ))}
        {sources.length === 0 && <div className="text-sm text-muted-foreground">No source activity yet.</div>}
      </div>
      <Link to="/timeline" className="mt-6 flex items-center gap-2 text-sm text-primary">View all activity <ArrowRight className="h-4 w-4" /></Link>

      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Top sources</h3>
      <div className="mt-5 space-y-5">
        {sources.slice(0, 3).map((source) => (
          <div key={source.id} className="flex gap-3 text-sm">
            <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-issue)]" />
            <div>
              <div className="leading-5">{source.title}</div>
              <div className="mt-1 text-xs text-muted-foreground">{memoryEstimate(source)} memories</div>
            </div>
          </div>
        ))}
      </div>
      <Link to="/sources" className="mt-6 flex items-center gap-2 text-sm text-primary">View all {sources.length} sources <ArrowRight className="h-4 w-4" /></Link>

      <Divider />
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Memory profile</h3>
      <section className="mt-4 rounded-md border border-border bg-background p-4">
        <div className="flex items-center gap-2 text-primary">
          <CheckCircle2 className="h-4 w-4" />
          <span className="font-medium">Ready</span>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Last updated {formatDate(cluster.lastActive)}</p>
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

function MetricGrid({ className = "", sources }: { className?: string; sources: number }) {
  return (
    <div className={`grid grid-cols-4 gap-4 ${className}`}>
      <Metric value={sources.toLocaleString()} label="Sources" />
      <Metric value={(sources * 64).toLocaleString()} label="Memories" />
      <Metric value={compactNumber(sources * 512)} label="Embeddings" />
      <Metric value={`${Math.max(1, Math.round(sources / 40))} MB`} label="Size" />
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

function memoryEstimate(source: Source) {
  return Math.max(1, Math.round((source.preview || source.summary || source.title).length / 120));
}

function compactNumber(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString();
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}
