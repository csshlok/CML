import { createFileRoute, Link, Navigate, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  FolderInput,
  MessageSquare,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { type Cluster, type Source } from "@/lib/domain";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/WindowAware";
import { KnowledgeMap } from "@/components/KnowledgeMap";
import {
  createChatSession,
  deleteCluster,
  getCluster,
  getMapNeighborhood,
  listClusterMergeArtifacts,
  listClustersPage,
  listChatSessions,
  listProjects,
  listSources,
  mergeClusterInto,
  refreshClusterProfile,
  rollbackClusterMerge,
  updateSource,
  updateCluster,
  type ClusterMergeArtifact,
  type ChatSessionRecord,
  type ProjectRecord,
  type MapGraphResponse,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { notify } from "@/components/product/Notifications";
import { ConfirmAction } from "@/components/product/Feedback";

export const Route = createFileRoute("/_app/clusters/$clusterId")({
  head: () => ({ meta: [{ title: "Cluster" }] }),
  component: ClusterDetail,
});

const tabs = ["Overview", "Sources", "Chats", "Map", "Memory profile"] as const;

async function listClusterDestinations(vaultId: string, query = "") {
  const page = await listClustersPage(vaultId, { limit: 50, query });
  return page.items;
}

function ClusterDetail() {
  const { clusterId } = Route.useParams();
  const navigate = useNavigate();
  const [backendCluster, setBackendCluster] = useState<Cluster | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendVaultId, setBackendVaultId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Overview");
  const [mounted, setMounted] = useState(false);
  const [peerClusters, setPeerClusters] = useState<Cluster[]>([]);
  const [mergeArtifacts, setMergeArtifacts] = useState<ClusterMergeArtifact[]>([]);
  const [manageOpen, setManageOpen] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [mergeDestinationQuery, setMergeDestinationQuery] = useState("");
  const [manageMessage, setManageMessage] = useState<string | null>(null);
  const [manageBusy, setManageBusy] = useState(false);
  const [backendProject, setBackendProject] = useState<ProjectRecord | null>(null);
  const [linkedProjects, setLinkedProjects] = useState<ProjectRecord[]>([]);
  const [profileRefreshBusy, setProfileRefreshBusy] = useState(false);
  const [profileRefreshMessage, setProfileRefreshMessage] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "not-found" | "error">("loading");
  const [mapOverview, setMapOverview] = useState<MapGraphResponse | null>(null);
  const [sourceToMove, setSourceToMove] = useState<Source | null>(null);
  const [moveTargetId, setMoveTargetId] = useState("");
  const [moveDestinationQuery, setMoveDestinationQuery] = useState("");
  const [moveSourceBusy, setMoveSourceBusy] = useState(false);
  const [moveSourceError, setMoveSourceError] = useState<string | null>(null);

  const cluster = backendCluster;
  const activeSources = !mounted ? [] : backendSources;
  const clusterSources = cluster
    ? activeSources.filter((source) => source.clusterId === cluster.id)
    : [];
  const clusterChats = backendChats;

  useEffect(() => {
    let cancelled = false;
    setMounted(true);
    setLoadState("loading");
    async function loadBackendCluster() {
      try {
        const clusterRow = await getCluster(clusterId);
        if (cancelled) return;
        const nextCluster = clusterFromRecord(clusterRow);
        setBackendVaultId(clusterRow.vault_id);
        setBackendCluster(nextCluster);
        setNameDraft(nextCluster.name);
        setLoadState("ready");

        const [sourceResult, chatResult, clusterResult, artifactResult, projectResult, mapResult] = await Promise.allSettled([
          listSources(clusterRow.vault_id, { clusterId: clusterRow.id, limit: 1000 }),
          listChatSessions(clusterRow.vault_id, { clusterId: clusterRow.id }),
          listClusterDestinations(clusterRow.vault_id),
          listClusterMergeArtifacts(clusterRow.id),
          listProjects(clusterRow.vault_id, { clusterId: clusterRow.id, limit: 200 }),
          getMapNeighborhood(clusterRow.vault_id, clusterRow.id),
        ]);
        if (cancelled) return;
        if (sourceResult.status === "fulfilled") setBackendSources(sourceResult.value.map(sourceFromRecord));
        if (chatResult.status === "fulfilled") {
          setBackendChats(chatResult.value.filter((chat) => chat.scope_cluster_id === clusterRow.id));
        }
        if (clusterResult.status === "fulfilled") {
          setPeerClusters(
            clusterResult.value.filter((item) => item.id !== clusterRow.id).map(clusterFromRecord),
          );
        }
        if (artifactResult.status === "fulfilled") setMergeArtifacts(artifactResult.value.items);
        if (projectResult.status === "fulfilled") {
          const primary = projectResult.value.find((project) => project.primary_cluster_id === clusterRow.id) ?? null;
          setBackendProject(primary);
          setLinkedProjects(projectResult.value.filter((project) => project.id !== primary?.id));
        }
        if (mapResult.status === "fulfilled") setMapOverview(mapResult.value);
      } catch (error) {
        if (!cancelled) {
          setBackendCluster(null);
          setBackendVaultId(null);
          setBackendSources([]);
          setBackendChats([]);
          setBackendProject(null);
          setLinkedProjects([]);
          setLoadState(
            error instanceof Error && /not found/i.test(error.message) ? "not-found" : "error",
          );
        }
      }
    }

    void loadBackendCluster();
    return () => {
      cancelled = true;
    };
  }, [clusterId]);

  useEffect(() => {
    if (!backendVaultId || (!manageOpen && !sourceToMove)) return;
    let cancelled = false;
    const query = sourceToMove ? moveDestinationQuery : mergeDestinationQuery;
    const timer = window.setTimeout(() => {
      void listClusterDestinations(backendVaultId, query)
        .then((items) => {
          if (!cancelled) {
            setPeerClusters(
              items.filter((item) => item.id !== clusterId).map(clusterFromRecord),
            );
          }
        })
        .catch(() => {
          if (!cancelled) setPeerClusters([]);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    backendVaultId,
    clusterId,
    manageOpen,
    mergeDestinationQuery,
    moveDestinationQuery,
    sourceToMove,
  ]);

  if (loadState === "loading") {
    return (
      <div className="h-full overflow-y-auto p-8" aria-label="Loading cluster">
        <div className="mx-auto max-w-[1240px] animate-pulse space-y-5">
          <div className="h-4 w-32 rounded bg-muted" />
          <div className="h-10 w-2/5 rounded bg-muted" />
          <div className="h-28 rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (!cluster) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {loadState === "not-found"
          ? "This cluster no longer exists."
          : "This cluster could not be loaded. Try again from Clusters."}
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

  if (backendProject && backendVaultId) {
    return <Navigate to="/projects/$projectId" params={{ projectId: backendProject.id }} replace />;
  }
  const clusterIdForActions = cluster.id;
  const clusterNameForActions = cluster.name;

  async function saveClusterName() {
    const name = nameDraft.trim();
    if (!name || name === clusterNameForActions) return;
    setManageBusy(true);
    setManageMessage(null);
    try {
      const updated = await updateCluster(clusterIdForActions, { name });
      setBackendCluster(clusterFromRecord(updated));
      setManageMessage("Cluster name updated.");
    } catch (error) {
      setManageMessage(error instanceof Error ? error.message : "Could not rename this cluster.");
    } finally {
      setManageBusy(false);
    }
  }

  async function mergeCluster() {
    if (!mergeTargetId) return;
    const target = peerClusters.find((candidate) => candidate.id === mergeTargetId);
    if (!target) return;
    setManageBusy(true);
    setManageMessage(null);
    try {
      await mergeClusterInto(clusterIdForActions, mergeTargetId);
      navigate({ to: "/clusters/$clusterId", params: { clusterId: mergeTargetId } });
    } catch (error) {
      setManageMessage(error instanceof Error ? error.message : "Could not merge this cluster.");
      setManageBusy(false);
    }
  }

  async function rollbackMerge(artifactId: string) {
    setManageBusy(true);
    setManageMessage(null);
    try {
      const restored = await rollbackClusterMerge(artifactId);
      navigate({ to: "/clusters/$clusterId", params: { clusterId: restored.id } });
    } catch (error) {
      setManageMessage(error instanceof Error ? error.message : "Could not restore the merged cluster.");
      setManageBusy(false);
    }
  }

  async function deleteCurrentCluster() {
    setManageBusy(true);
    setManageMessage(null);
    try {
      await deleteCluster(clusterIdForActions);
      notify({
        title: "Cluster deleted",
        description: `${clusterNameForActions} was deleted. Its sources are now unclustered.`,
        tone: "success",
      });
      setManageOpen(false);
      navigate({ to: "/clusters" });
    } catch (error) {
      setManageBusy(false);
      throw error;
    }
  }

  async function generateClusterSummary() {
    setProfileRefreshBusy(true);
    setProfileRefreshMessage(null);
    try {
      const updated = await refreshClusterProfile(clusterIdForActions);
      setBackendCluster(clusterFromRecord(updated));
      setProfileRefreshMessage(
        "Summary generation is queued. Vault will update this profile in the background.",
      );
    } catch (error) {
      setProfileRefreshMessage(
        error instanceof Error ? error.message : "Could not generate this summary.",
      );
    } finally {
      setProfileRefreshBusy(false);
    }
  }

  function openMoveSource(source: Source) {
    setSourceToMove(source);
    setMoveTargetId("");
    setMoveDestinationQuery("");
    setMoveSourceError(null);
  }

  async function moveSource() {
    if (!sourceToMove || !moveTargetId || !backendVaultId) return;
    const target = peerClusters.find((candidate) => candidate.id === moveTargetId);
    if (!target) {
      setMoveSourceError("Choose an available destination cluster.");
      return;
    }

    setMoveSourceBusy(true);
    setMoveSourceError(null);
    try {
      const moved = await updateSource(sourceToMove.id, {
        cluster_id: target.id,
      });
      if (moved.cluster_id !== target.id) {
        throw new Error("Vault could not confirm the new cluster.");
      }

      setBackendSources((current) =>
        current.filter((source) => source.id !== sourceToMove.id),
      );
      setSourceToMove(null);
      setMoveTargetId("");
      setMoveDestinationQuery("");
      notify({
        title: "Source moved",
        description: `${sourceToMove.title} is now in ${target.name}.`,
        tone: "success",
      });

      const [clusterResult, mapResult] = await Promise.allSettled([
        getCluster(clusterIdForActions),
        getMapNeighborhood(backendVaultId, clusterIdForActions),
      ]);
      if (clusterResult.status === "fulfilled") {
        setBackendCluster(clusterFromRecord(clusterResult.value));
      }
      if (mapResult.status === "fulfilled") {
        setMapOverview(mapResult.value);
      }
    } catch (error) {
      setMoveSourceError(
        error instanceof Error ? error.message : "Could not move this source.",
      );
    } finally {
      setMoveSourceBusy(false);
    }
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <main className="mx-auto min-h-full w-full max-w-[1240px] min-w-0 px-4 py-6 sm:px-6 lg:px-9">
        <Link to="/clusters" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Back to clusters
        </Link>

        <PageHeader className="mt-7 flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-3">
              <h1 className="page-title break-words">{cluster.name}</h1>
              <span className={`h-2.5 w-2.5 rounded-full bg-[var(--cluster-${cluster.tint})]`} />
            </div>
            <p className="mt-2 max-w-3xl break-words text-sm text-muted-foreground">{cluster.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button className="gap-2 bg-primary text-primary-foreground" onClick={() => void openClusterChat()}>
              <MessageSquare className="h-4 w-4" />
              Chat with cluster
            </Button>
            <Button variant="outline" className="gap-2" asChild>
              <Link to="/sources" search={{ cluster: clusterIdForActions }}>
                <Plus className="h-4 w-4" />
                Add source
              </Link>
            </Button>
            <Button variant="outline" size="icon" aria-label="More cluster actions" onClick={() => setManageOpen(true)}>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </div>
        </PageHeader>

        <nav className="mt-8 flex gap-6 overflow-x-auto border-b border-border text-sm sm:gap-8">
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
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Summary</h2>
              {!cluster.summary && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  disabled={profileRefreshBusy}
                  onClick={() => void generateClusterSummary()}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${profileRefreshBusy ? "animate-spin" : ""}`} />
                  {profileRefreshBusy ? "Queuing…" : "Generate summary"}
                </Button>
              )}
            </div>
            <p className="mt-4 max-w-3xl break-words text-sm leading-7">
              {cluster.summary || cluster.description || "This memory space is ready for sources, chats, and local context."}
            </p>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
              <span>{clusterSources.length.toLocaleString()} sources</span>
              <span>{clusterSources.filter((source) => source.state === "indexed").length.toLocaleString()} indexed</span>
              <span>Updated {formatDate(cluster.lastActive)}</span>
              <span className="capitalize">Profile {cluster.lifecycle.replaceAll("_", " ")}</span>
            </div>
            {profileRefreshMessage && (
              <p className="mt-2 max-w-3xl text-xs text-muted-foreground" role="status">
                {profileRefreshMessage}
              </p>
            )}

            {cluster.glossary.length > 0 && (
              <div className="mt-6 max-w-3xl">
                <h3 className="text-sm font-medium">Key terms</h3>
                <div className="mt-3 flex flex-wrap gap-2">
                  {cluster.glossary.map((term) => (
                    <span key={term} className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground">
                      {term}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {linkedProjects.length > 0 && <section className="mt-8"><h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Linked projects</h3><div className="mt-3 divide-y divide-border rounded-md border border-border bg-card">{linkedProjects.map((project) => <div key={project.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="font-medium">{project.name}</div><p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{project.brief || `${project.source_count.toLocaleString()} indexed project files.`}</p><div className="mt-1 text-xs text-muted-foreground">{project.changed_file_count ? `${project.changed_file_count} newer changes` : "Index current with registered folder"}</div></div><div className="flex shrink-0 gap-2"><Button variant="outline" size="sm" onClick={() => void createChatSession({ vault_id: project.vault_id, title: `${project.name} chat`, scope_cluster_id: project.primary_cluster_id, scope_project_id: project.id }).then((session) => navigate({ to: "/chat/$chatId", params: { chatId: session.id } }))}>Ask with project</Button><Button size="sm" asChild><Link to="/projects/$projectId" params={{ projectId: project.id }}>Open project</Link></Button></div></div>)}</div></section>}

            <div className="mt-8 grid gap-5 xl:grid-cols-2">
              <RecentSources
                sources={clusterSources.slice(0, 5)}
                clusterId={clusterIdForActions}
              />
              <RecentChats chats={clusterChats} clusterId={clusterIdForActions} />
            </div>
          </section>
        )}

        {activeTab === "Sources" && (
          <ClusterSourcesPanel
            sources={clusterSources}
            peerClusters={peerClusters}
            clusterId={clusterIdForActions}
            onMove={openMoveSource}
          />
        )}
        {activeTab === "Chats" && <ClusterChatsPanel chats={clusterChats} />}
        {activeTab === "Map" && backendVaultId && (
          <section className="mt-7">
            {mapOverview ? (
              <KnowledgeMap
                vaultId={backendVaultId}
                overview={mapOverview}
                initialFocusId={clusterIdForActions}
                onReload={() => {
                  void getMapNeighborhood(backendVaultId, clusterIdForActions).then(setMapOverview);
                }}
              />
            ) : (
              <div className="rounded-md border border-border bg-card p-8 text-sm text-muted-foreground">
                This cluster map could not be loaded. The rest of the cluster is still available.
              </div>
            )}
          </section>
        )}
        {activeTab === "Memory profile" && (
          <ClusterMemoryProfile cluster={cluster} sources={clusterSources} />
        )}
      </main>

      <Dialog
        open={manageOpen}
        onOpenChange={(open) => {
          setManageOpen(open);
          if (!open) {
            setMergeDestinationQuery("");
            setMergeTargetId("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manage cluster</DialogTitle>
            <DialogDescription>
              Rename this cluster, merge it into another cluster, or restore a recent merge.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div>
              <label className="text-sm font-medium" htmlFor="cluster-name">Cluster name</label>
              <div className="mt-2 flex gap-2">
                <Input id="cluster-name" value={nameDraft} onChange={(event) => setNameDraft(event.target.value)} />
                <Button variant="outline" disabled={manageBusy || !nameDraft.trim()} onClick={() => void saveClusterName()}>
                  Save
                </Button>
              </div>
            </div>
            <div>
              <label className="text-sm font-medium" htmlFor="merge-target">Merge into</label>
              <Input
                className="mt-2"
                value={mergeDestinationQuery}
                onChange={(event) => setMergeDestinationQuery(event.target.value)}
                placeholder="Search clusters"
                aria-label="Search merge destinations"
              />
              <select
                id="merge-target"
                className="mt-2 h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
                value={mergeTargetId}
                onChange={(event) => setMergeTargetId(event.target.value)}
              >
                <option value="">Choose a target cluster</option>
                {peerClusters.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Sources and scoped chats move to the target. CML keeps a reversible merge record.
              </p>
              <ConfirmAction
                title={`Merge ${clusterNameForActions}?`}
                description={
                  mergeTargetId
                    ? `${clusterSources.length} source${clusterSources.length === 1 ? "" : "s"} and ${clusterChats.length} chat${clusterChats.length === 1 ? "" : "s"} will move to ${peerClusters.find((item) => item.id === mergeTargetId)?.name ?? "the selected cluster"}. You can restore this merge later.`
                    : "Choose a destination cluster first."
                }
                confirmLabel="Merge cluster"
                onConfirm={mergeCluster}
                disabled={manageBusy || !mergeTargetId}
              >
                <Button className="mt-3" disabled={manageBusy || !mergeTargetId}>
                  Merge cluster
                </Button>
              </ConfirmAction>
            </div>
            {mergeArtifacts.some((item) => item.reversible && !item.rolled_back_at) && (
              <div>
                <div className="text-sm font-medium">Recent reversible merges</div>
                <div className="mt-2 space-y-2">
                  {mergeArtifacts.filter((item) => item.reversible && !item.rolled_back_at).map((item) => (
                    <div key={item.id} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm">
                      <span>{item.moved_source_ids.length} sources · {formatDate(item.created_at)}</span>
                      <Button size="sm" variant="outline" disabled={manageBusy} onClick={() => void rollbackMerge(item.id)}>
                        Restore
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="border-t border-border pt-5">
              <div className="text-sm font-medium text-destructive">Delete cluster</div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Sources remain in Vault and move to Unclustered. Scoped chats become unscoped.
              </p>
              <ConfirmAction
                title={`Delete ${clusterNameForActions}?`}
                description={`This permanently deletes the cluster. Its ${clusterSources.length} source${clusterSources.length === 1 ? "" : "s"} will remain available under Unclustered.`}
                confirmLabel="Delete cluster"
                onConfirm={deleteCurrentCluster}
                disabled={manageBusy}
              >
                <Button
                  variant="outline"
                  className="mt-3 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  disabled={manageBusy}
                >
                  <Trash2 className="h-4 w-4" /> Delete cluster
                </Button>
              </ConfirmAction>
            </div>
            {manageMessage && <p className="text-sm text-muted-foreground">{manageMessage}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setManageOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(sourceToMove)}
        onOpenChange={(open) => {
          if (!open && !moveSourceBusy) {
            setSourceToMove(null);
            setMoveTargetId("");
            setMoveDestinationQuery("");
            setMoveSourceError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Move source</DialogTitle>
            <DialogDescription>
              Move <span className="break-words font-medium text-foreground">{sourceToMove?.title}</span>{" "}
              to another cluster. The original file and saved source content stay unchanged.
            </DialogDescription>
          </DialogHeader>
          <div>
            <label className="text-sm font-medium" htmlFor="move-source-target">
              Destination cluster
            </label>
            <Input
              className="mt-2"
              value={moveDestinationQuery}
              onChange={(event) => setMoveDestinationQuery(event.target.value)}
              placeholder="Search clusters"
              aria-label="Search move destinations"
              disabled={moveSourceBusy}
            />
            <select
              id="move-source-target"
              className="mt-2 h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
              value={moveTargetId}
              onChange={(event) => {
                setMoveTargetId(event.target.value);
                if (moveSourceError) setMoveSourceError(null);
              }}
              disabled={moveSourceBusy}
            >
              <option value="">Choose a cluster</option>
              {peerClusters.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            {moveSourceError ? (
              <p className="mt-2 text-sm text-destructive" role="alert">
                {moveSourceError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setSourceToMove(null);
                setMoveTargetId("");
                setMoveDestinationQuery("");
                setMoveSourceError(null);
              }}
              disabled={moveSourceBusy}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void moveSource()}
              disabled={moveSourceBusy || !moveTargetId}
            >
              {moveSourceBusy ? "Moving…" : "Move source"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RecentSources({ sources, clusterId }: { sources: Source[]; clusterId: string }) {
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent sources</h3>
      <div className="mt-4 divide-y divide-border">
          {sources.map((source) => (
            <div key={source.id} className="flex min-w-0 items-start gap-3 px-4 py-3 text-sm">
                <FileText className="h-4 w-4 shrink-0 text-[var(--status-issue)]" />
                <span className="min-w-0 flex-1">
                  <span className="block break-words font-medium">{source.title}</span>
                  {(source.summary || source.preview) && (
                    <span className="mt-1 line-clamp-2 block break-words text-xs leading-5 text-muted-foreground">
                      {source.summary || source.preview}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-right text-xs text-muted-foreground">
                  <span className="block">{sourceStateLabel(source.state)}</span>
                  <span className="mt-1 block">{formatDate(source.updatedAt)}</span>
                </span>
            </div>
          ))}
          {sources.length === 0 && (
            <div className="px-4 py-10 text-sm text-muted-foreground">No recent sources yet.</div>
          )}
      </div>
      <Link
        to="/sources"
        search={{ cluster: clusterId }}
        className="flex items-center gap-2 px-4 py-4 text-sm text-primary"
      >
        View all sources <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function RecentChats({
  chats,
  clusterId,
}: {
  chats: Array<ChatSessionRecord | { id: string; title: string }>;
  clusterId: string;
}) {
  const rows = chats;
  return (
    <section className="rounded-md border border-border bg-card">
      <h3 className="px-4 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent chats</h3>
      <div className="mt-4 overflow-x-auto">
        <div className="divide-y divide-border">
          {rows.slice(0, 3).map((chat) => (
            <Link
              key={chat.id}
              to="/chat/$chatId"
              params={{ chatId: chat.id }}
              className="flex min-w-0 items-center gap-3 px-4 py-3 text-sm hover:bg-accent"
            >
              <span className="flex min-w-0 items-center gap-3">
                <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="break-words">{chat.title}</span>
              </span>
              {"updated_at" in chat && (
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">{formatDate(chat.updated_at)}</span>
              )}
              <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </Link>
          ))}
          {rows.length === 0 && (
            <div className="px-4 py-10 text-sm text-muted-foreground">No scoped chats yet.</div>
          )}
        </div>
      </div>
      <Link
        to="/chat"
        search={{ cluster: clusterId }}
        className="flex items-center gap-2 px-4 py-4 text-sm text-primary"
      >
        View all chats <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

function ClusterSourcesPanel({
  sources,
  peerClusters,
  clusterId,
  onMove,
}: {
  sources: Source[];
  peerClusters: Cluster[];
  clusterId: string;
  onMove: (source: Source) => void;
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleSources = normalizedQuery
    ? sources.filter((source) =>
        [source.title, source.summary, source.preview, source.type]
          .filter(Boolean)
          .some((value) => value!.toLocaleLowerCase().includes(normalizedQuery)),
      )
    : sources;

  return (
    <section className="mt-7">
      <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Sources</h2>
        <div className="relative w-full sm:w-60">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search sources in this cluster"
            className="h-9 pl-9"
            placeholder="Search sources"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>
      <div className="mt-5 grid gap-3">
        {visibleSources.map((source) => (
          <div
            key={source.id}
            className="grid min-h-[74px] grid-cols-1 gap-3 rounded-md border border-border bg-card px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_90px_100px_auto] sm:items-center sm:gap-4"
          >
            <Link
              to="/sources"
              search={{ cluster: clusterId, source: source.id }}
              className="flex min-w-0 items-start gap-3 hover:text-primary"
            >
              <FileText className="mt-1 h-4 w-4 shrink-0 text-[var(--cluster-sky)]" />
              <span className="min-w-0">
                <span className="block break-words font-medium">{source.title}</span>
                <span className="mt-1 line-clamp-2 break-words text-xs leading-5 text-muted-foreground">
                  {source.summary || source.preview || "No extracted preview yet."}
                </span>
              </span>
            </Link>
            <span className="text-muted-foreground">{source.type.toUpperCase()}</span>
            <span className="text-muted-foreground sm:text-right">{source.state}</span>
            <Button
              variant="outline"
              size="sm"
              className="w-fit gap-2"
              onClick={() => onMove(source)}
              disabled={peerClusters.length === 0}
              title={
                peerClusters.length === 0
                  ? "Create another cluster before moving this source."
                  : `Move ${source.title}`
              }
              aria-label={`Move ${source.title} to another cluster`}
            >
              <FolderInput className="h-4 w-4" />
              Move
            </Button>
          </div>
        ))}
        {sources.length === 0 && (
          <div className="py-10 text-sm text-muted-foreground">No sources are linked to this cluster yet.</div>
        )}
        {sources.length > 0 && visibleSources.length === 0 && (
          <div className="py-10 text-sm text-muted-foreground">No cluster sources match this search.</div>
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
            className="grid min-h-[62px] grid-cols-1 gap-3 rounded-md border border-border bg-card px-4 py-3 text-sm hover:border-primary/40 sm:grid-cols-[minmax(0,1fr)_132px_20px] sm:items-center sm:gap-5"
          >
            <span className="flex min-w-0 items-center gap-3">
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="break-words font-medium">{chat.title}</span>
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

function ClusterMemoryProfile({
  cluster,
  sources,
}: {
  cluster: Cluster;
  sources: Source[];
}) {
  return (
    <section className="mt-7">
      <div className="border-b border-border pb-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Memory profile</h2>
      </div>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Profile state</h3>
          <p className="mt-3 break-words text-sm leading-6 text-muted-foreground">
            {cluster.summary || cluster.description || "Vault has not generated a profile summary for this cluster yet."}
          </p>
          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Metric value={sources.length.toLocaleString()} label="Sources" />
            <Metric value={sources.filter((source) => source.state === "indexed").length.toLocaleString()} label="Indexed" />
            <Metric value={formatDate(cluster.lastActive)} label="Updated" />
          </div>
        </section>
        <section className="rounded-md border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Recent profile inputs</h3>
          <div className="mt-4 space-y-3">
            {sources.slice(0, 5).map((source) => (
              <div key={source.id} className="flex items-start gap-3 text-sm">
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--cluster-sage)]" />
                <span className="min-w-0">
                  <span className="block break-words font-medium">{source.title}</span>
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

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div className="min-w-0">
      <div className="break-words font-semibold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function sourceStateLabel(state: Source["state"]) {
  if (state === "indexed") return "Indexed";
  if (state === "processing") return "Processing";
  if (state === "failed") return "Needs review";
  return "Waiting";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}
