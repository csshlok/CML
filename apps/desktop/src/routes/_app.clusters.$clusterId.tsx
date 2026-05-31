import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { MessageSquare } from "lucide-react";
import {
  useStore,
  expertLabel,
  sourceStateLabel,
  type Cluster,
  type Source,
} from "@/lib/mockStore";
import { ClusterDot, ExpertBadge } from "@/components/ClusterChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClusterMap } from "@/components/ClusterMap";
import {
  createChatSession,
  createCluster,
  getCluster,
  listClusterExpertJobs,
  listClusterExpertArtifacts,
  listChatSessions,
  listClusters,
  listSources,
  mergeClusterInto,
  pauseClusterExpert,
  retrainClusterExpert,
  updateSource,
  updateCluster,
  type ClusterExpertJobRecord,
  type ExpertArtifactRecord,
  type ChatSessionRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters/$clusterId")({
  head: () => ({ meta: [{ title: "Cluster" }] }),
  component: ClusterDetail,
});

function ClusterDetail() {
  const { clusterId } = Route.useParams();
  const navigate = useNavigate();
  const { clusters, sources, chats, renameCluster, createChat } = useStore();
  const [backendCluster, setBackendCluster] = useState<Cluster | null>(null);
  const [backendVaultId, setBackendVaultId] = useState<string | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [allBackendClusters, setAllBackendClusters] = useState<Cluster[]>([]);
  const [expertJobs, setExpertJobs] = useState<ClusterExpertJobRecord[]>([]);
  const [expertArtifacts, setExpertArtifacts] = useState<ExpertArtifactRecord[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [nameDraft, setNameDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mockCluster = clusters.find((cluster) => cluster.id === clusterId) ?? null;
  const cluster = backendCluster ?? mockCluster;
  const usingBackend = Boolean(backendCluster);

  async function loadBackendCluster() {
    setLoading(true);
    setError(null);
    try {
      const clusterRow = await getCluster(clusterId);
      const nextCluster = clusterFromRecord(clusterRow);
      setBackendVaultId(clusterRow.vault_id);
      const [sourceRows, chatRows, clusterRows, jobRows, artifactRows] = await Promise.all([
        listSources(clusterRow.vault_id),
        listChatSessions(clusterRow.vault_id),
        listClusters(clusterRow.vault_id),
        listClusterExpertJobs(clusterRow.id).catch(() => []),
        listClusterExpertArtifacts(clusterRow.id).catch(() => []),
      ]);
      setBackendCluster(nextCluster);
      setNameDraft(nextCluster.name);
      setBackendSources(sourceRows.map(sourceFromRecord));
      setBackendChats(chatRows.filter((chat) => chat.scope_cluster_id === clusterRow.id));
      setAllBackendClusters(clusterRows.map(clusterFromRecord));
      setExpertJobs(jobRows);
      setExpertArtifacts(artifactRows);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not load this cluster from the backend.",
      );
      setBackendCluster(null);
      setBackendVaultId(null);
      if (mockCluster) setNameDraft(mockCluster.name);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBackendCluster();
  }, [clusterId]);

  useEffect(() => {
    if (!backendCluster && mockCluster) setNameDraft(mockCluster.name);
  }, [backendCluster, mockCluster?.name]);

  if (loading && !cluster) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading cluster...
      </div>
    );
  }

  if (!cluster) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Cluster not found.
      </div>
    );
  }

  const activeSources = usingBackend ? backendSources : sources;
  const clusterSources = activeSources.filter((source) => source.clusterId === cluster.id);
  const availableSources = activeSources.filter((source) => source.clusterId !== cluster.id);
  const clusterChats = usingBackend
    ? backendChats
    : chats.filter((chat) => chat.scopeClusterId === cluster.id);

  async function commitName() {
    const nextName = nameDraft.trim();
    if (!nextName || nextName === cluster.name) return;
    if (usingBackend) {
      try {
        const updated = clusterFromRecord(await updateCluster(cluster.id, { name: nextName }));
        setBackendCluster(updated);
        setNameDraft(updated.name);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not rename this cluster.");
        setNameDraft(cluster.name);
      }
      return;
    }
    renameCluster(cluster.id, nextName);
  }

  async function openClusterChat() {
    if (usingBackend && backendCluster && backendVaultId) {
      try {
        const session = await createChatSession({
          vault_id: backendVaultId,
          title: `${backendCluster.name} chat`,
          scope_cluster_id: backendCluster.id,
        });
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not create a cluster chat.");
      }
    }
    const chat = createChat(cluster.id);
    navigate({ to: "/chat/$chatId", params: { chatId: chat.id } });
  }

  async function moveSource(sourceId: string, nextClusterId: string | null) {
    if (!usingBackend) return;
    await updateSource(sourceId, { cluster_id: nextClusterId });
    await loadBackendCluster();
  }

  async function createClusterFromSelected() {
    if (!backendVaultId || selectedSourceIds.length === 0) return;
    const created = await createCluster({
      vault_id: backendVaultId,
      name: `${cluster.name} selection`,
      description: `Created from ${selectedSourceIds.length} selected source(s).`,
      color: cluster.tint,
    });
    await Promise.all(
      selectedSourceIds.map((sourceId) => updateSource(sourceId, { cluster_id: created.id })),
    );
    setSelectedSourceIds([]);
    navigate({ to: "/clusters/$clusterId", params: { clusterId: created.id } });
  }

  async function queueExpertLearning() {
    if (!usingBackend) return;
    await retrainClusterExpert(cluster.id);
    await loadBackendCluster();
  }

  async function pauseExpertLearning() {
    if (!usingBackend) return;
    const updated = clusterFromRecord(await pauseClusterExpert(cluster.id));
    setBackendCluster(updated);
    setNameDraft(updated.name);
  }

  async function mergeIntoTarget() {
    if (!usingBackend || !mergeTargetId || mergeTargetId === cluster.id) return;
    try {
      const target = await mergeClusterInto(cluster.id, mergeTargetId);
      navigate({ to: "/clusters/$clusterId", params: { clusterId: target.id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not merge this cluster.");
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="flex items-center gap-3">
          <ClusterDot tint={cluster.tint} size={12} />
          <Input
            value={nameDraft}
            onChange={(event) => setNameDraft(event.target.value)}
            onBlur={() => void commitName()}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
            aria-label="Cluster name"
            className="h-9 max-w-sm border-transparent bg-transparent px-1 text-2xl font-semibold tracking-tight shadow-none focus-visible:bg-card"
          />
          <div className="ml-auto flex items-center gap-2">
            <ExpertBadge status={cluster.expert} />
            <Button size="sm" onClick={() => void openClusterChat()}>
              <MessageSquare className="mr-1.5 h-4 w-4" /> Chat with cluster
            </Button>
          </div>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {cluster.description || "No description yet."}
        </p>
        {usingBackend && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-3 py-2">
            <span className="text-sm text-muted-foreground">Merge this cluster into</span>
            <Select value={mergeTargetId} onValueChange={setMergeTargetId}>
              <SelectTrigger className="h-8 w-56">
                <SelectValue placeholder="Choose cluster" />
              </SelectTrigger>
              <SelectContent>
                {allBackendClusters
                  .filter((candidate) => candidate.id !== cluster.id)
                  .map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              disabled={!mergeTargetId}
              onClick={() => void mergeIntoTarget()}
            >
              Merge
            </Button>
          </div>
        )}
        {error && (
          <div className="mt-4 rounded-md border border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
            {usingBackend ? error : `Using local fallback data: ${error}`}
          </div>
        )}

        <Tabs defaultValue="overview" className="mt-8">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="sources">Sources ({clusterSources.length})</TabsTrigger>
            <TabsTrigger value="chats">Chats ({clusterChats.length})</TabsTrigger>
            <TabsTrigger value="expert">Expert</TabsTrigger>
            <TabsTrigger value="map">Map</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-6 space-y-4">
            <Card title="Summary">{cluster.summary || "Summary pending."}</Card>
            <Card title="Style profile">{cluster.styleProfile || "Style profile pending."}</Card>
            <Card title="Recent activity">
              <ul className="space-y-1.5 text-sm">
                {clusterChats.slice(0, 4).map((chat) => (
                  <li key={chat.id} className="text-muted-foreground">
                    - {chat.title}
                  </li>
                ))}
                {clusterChats.length === 0 && (
                  <li className="text-muted-foreground">No chats yet.</li>
                )}
              </ul>
            </Card>
          </TabsContent>

          <TabsContent value="sources" className="mt-6">
            {usingBackend && (
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-sm text-muted-foreground">
                  {selectedSourceIds.length} selected
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={selectedSourceIds.length === 0}
                  onClick={() => void createClusterFromSelected()}
                >
                  New cluster from selected
                </Button>
              </div>
            )}
            <div className="rounded-md border border-border">
              {clusterSources.map((source) => (
                <div
                  key={source.id}
                  className="flex items-center justify-between gap-4 border-b border-border px-4 py-2.5 text-sm last:border-b-0"
                >
                  <label className="flex min-w-0 flex-1 items-center gap-2">
                    {usingBackend && (
                      <input
                        type="checkbox"
                        checked={selectedSourceIds.includes(source.id)}
                        onChange={(event) => {
                          setSelectedSourceIds((current) =>
                            event.target.checked
                              ? [...current, source.id]
                              : current.filter((id) => id !== source.id),
                          );
                        }}
                      />
                    )}
                    <span className="truncate">{source.title}</span>
                  </label>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {sourceStateLabel[source.state]}
                    </span>
                    {usingBackend && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void moveSource(source.id, null)}
                      >
                        Remove
                      </Button>
                    )}
                  </div>
                </div>
              ))}
              {clusterSources.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                  No sources in this cluster yet.
                </div>
              )}
            </div>
            {usingBackend && (
              <div className="mt-4 rounded-md border border-border">
                <div className="border-b border-border px-4 py-2 text-sm font-medium">
                  Add from vault
                </div>
                {availableSources.slice(0, 8).map((source) => (
                  <div
                    key={source.id}
                    className="flex items-center justify-between gap-3 border-b border-border px-4 py-2 text-sm last:border-b-0"
                  >
                    <span className="truncate text-muted-foreground">{source.title}</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void moveSource(source.id, cluster.id)}
                    >
                      Add
                    </Button>
                  </div>
                ))}
                {availableSources.length === 0 && (
                  <div className="px-4 py-4 text-sm text-muted-foreground">
                    No other vault sources available.
                  </div>
                )}
              </div>
            )}
          </TabsContent>

          <TabsContent value="chats" className="mt-6 space-y-1">
            {clusterChats.map((chat) => (
              <button
                key={chat.id}
                className="block w-full rounded-md border border-border bg-card px-4 py-3 text-left text-sm hover:bg-accent"
                onClick={() => navigate({ to: "/chat/$chatId", params: { chatId: chat.id } })}
                type="button"
              >
                {chat.title}
              </button>
            ))}
            {clusterChats.length === 0 && (
              <p className="text-sm text-muted-foreground">No chats yet for this cluster.</p>
            )}
          </TabsContent>

          <TabsContent value="expert" className="mt-6 space-y-4">
            <Card title="Status">
              <div className="flex items-center justify-between">
                <ExpertBadge status={cluster.expert} />
                <span className="text-xs text-muted-foreground">{expertLabel[cluster.expert]}</span>
              </div>
              <p className="mt-3 text-sm text-muted-foreground">{expertStatusCopy(cluster)}</p>
              <div className="mt-4 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!usingBackend}
                  onClick={() => void queueExpertLearning()}
                >
                  Queue learning
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!usingBackend}
                  onClick={() => void pauseExpertLearning()}
                >
                  Pause
                </Button>
              </div>
            </Card>
            <details className="rounded-md border border-border bg-card px-4 py-3 text-sm">
              <summary className="cursor-pointer text-muted-foreground">Advanced details</summary>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Training data</dt>
                <dd>{clusterSources.length} sources</dd>
                <dt className="text-muted-foreground">Last trained</dt>
                <dd>Pending</dd>
                <dt className="text-muted-foreground">Version</dt>
                <dd>Pending</dd>
                <dt className="text-muted-foreground">Expert record</dt>
                <dd className="truncate">{cluster.id}</dd>
              </dl>
            </details>
            <Card title="Recent expert jobs">
              <div className="space-y-2">
                {expertJobs.slice(0, 5).map((job) => (
                  <div key={job.id} className="grid gap-1 text-xs sm:grid-cols-[1fr_auto]">
                    <span className="truncate">{job.action}</span>
                    <span className="text-muted-foreground">
                      {job.failure_code ? `${job.status} / ${job.failure_code}` : job.status}
                    </span>
                  </div>
                ))}
                {expertJobs.length === 0 && (
                  <div className="text-sm text-muted-foreground">No expert jobs yet.</div>
                )}
              </div>
            </Card>
            <Card title="Adapter artifacts">
              <div className="space-y-2">
                {expertArtifacts.slice(0, 5).map((artifact) => (
                  <div key={artifact.id} className="grid gap-1 text-xs sm:grid-cols-[1fr_auto]">
                    <span className="truncate">
                      {artifact.artifact_type} · {artifact.hardware_tier || "unknown hardware"}
                    </span>
                    <span className="text-muted-foreground">{artifact.status}</span>
                  </div>
                ))}
                {expertArtifacts.length === 0 && (
                  <div className="text-sm text-muted-foreground">
                    No adapter artifacts yet. The LoRA runner is still scaffolded.
                  </div>
                )}
              </div>
            </Card>
          </TabsContent>

          <TabsContent value="map" className="mt-6">
            <div className="h-[420px] rounded-md border border-border bg-card">
              <ClusterMap
                focusClusterId={cluster.id}
                clusters={usingBackend ? [cluster] : undefined}
                sources={usingBackend ? activeSources : undefined}
              />
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function expertStatusCopy(cluster: Cluster) {
  if (cluster.expert === "ready")
    return "This local expert is ready to inform answers in your voice.";
  if (cluster.expert === "learning") {
    return "This cluster is usable now. Its local expert is still learning in the background.";
  }
  if (cluster.expert === "needs-update")
    return "New source changes are ready for the next learning pass.";
  if (cluster.expert === "paused") return "Learning is paused for this cluster.";
  if (cluster.expert === "issue")
    return "This expert needs attention before it can continue learning.";
  return "This local expert is being set up.";
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div className="mt-2 text-sm">{children}</div>
    </div>
  );
}
