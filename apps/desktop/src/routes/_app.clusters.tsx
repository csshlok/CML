import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Check, Code2, FileText, Pencil, Plus, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createCluster,
  getLatestSourcesByCluster,
  getProjectClusterMembershipSummary,
  listClusterSuggestions,
  listClustersPage,
  listVaults,
  sourceCountsByCluster,
  updateCluster,
  updateSource,
  type ClusterSuggestionRecord,
  type VaultRecord,
} from "@/lib/backend";
import type { Cluster, ClusterTint } from "@/lib/domain";
import { clusterFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters")({
  head: () => ({ meta: [{ title: "Clusters" }] }),
  component: ClustersList,
});

function ClustersList() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  const [vault, setBackendVault] = useState<VaultRecord | null>(null);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [latestSources, setLatestSources] = useState<
    Map<string, { state: string; updatedAt: string }>
  >(new Map());
  const [suggestions, setSuggestions] = useState<ClusterSuggestionRecord[]>([]);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<string[]>([]);
  const [lastDismissedSuggestion, setLastDismissedSuggestion] = useState<ClusterSuggestionRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [sourceCountRows, setSourceCountRows] = useState<Array<{ cluster_id: string | null; state: string; total: number }>>([]);
  const [projectClusterIds, setProjectClusterIds] = useState<Set<string>>(new Set());
  const [newClusterName, setNewClusterName] = useState("");
  const [creatingCluster, setCreatingCluster] = useState(false);
  const [renamingCluster, setRenamingCluster] = useState<Cluster | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [nextClusterCursor, setNextClusterCursor] = useState<string | null>(null);
  const [loadingMoreClusters, setLoadingMoreClusters] = useState(false);

  async function loadData() {
    setLoading(true);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setBackendVault(activeVault);
      if (!activeVault) return;
      setDismissedSuggestions(readDismissedSuggestions(activeVault.id));
      const [clusterResult, suggestionResult, countResult, projectResult, latestResult] = await Promise.allSettled([
        listClustersPage(activeVault.id, { limit: 100 }),
        listClusterSuggestions(activeVault.id),
        sourceCountsByCluster(activeVault.id),
        getProjectClusterMembershipSummary(activeVault.id),
        getLatestSourcesByCluster(activeVault.id),
      ]);
      if (clusterResult.status === "rejected") throw clusterResult.reason;
      const clusterPage = clusterResult.value;
      const mappedClusters = clusterPage.items.map(clusterFromRecord);
      setBackendClusters(mappedClusters);
      setNextClusterCursor(clusterPage.next_cursor);
      if (latestResult.status === "fulfilled") {
        setLatestSources(new Map(
          latestResult.value.items.map((item) => [
            item.cluster_id,
            { state: item.state, updatedAt: item.updated_at },
          ]),
        ));
      }
      if (suggestionResult.status === "fulfilled") setSuggestions(suggestionResult.value);
      if (countResult.status === "fulfilled") setSourceCountRows(countResult.value.items);
      if (projectResult.status === "fulfilled") setProjectClusterIds(new Set(projectResult.value.cluster_ids));
      const degraded = [suggestionResult, countResult, projectResult, latestResult].some(
        (result) => result.status === "rejected",
      );
      setMessage(degraded ? "Some cluster details could not load. You can still open and edit clusters." : null);
    } catch {
      setMessage("Vault could not load your clusters. Check Settings / Health, then try again.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setMounted(true);
    void loadData();
  }, []);

  useEffect(() => {
    if (!lastDismissedSuggestion) return;
    const timeout = window.setTimeout(() => setLastDismissedSuggestion(null), 6000);
    return () => window.clearTimeout(timeout);
  }, [lastDismissedSuggestion]);

  const clusters = !mounted ? [] : backendClusters;
  const visibleSuggestions = suggestions.filter(
    (suggestion) => !dismissedSuggestions.includes(suggestionKey(suggestion)),
  );
  const sourceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of sourceCountRows) {
      if (row.cluster_id) counts.set(row.cluster_id, (counts.get(row.cluster_id) ?? 0) + row.total);
    }
    return counts;
  }, [sourceCountRows]);
  const indexedCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of sourceCountRows) {
      if (row.cluster_id && row.state === "indexed") counts.set(row.cluster_id, row.total);
    }
    return counts;
  }, [sourceCountRows]);
  if (pathname !== "/clusters") return <Outlet />;

  async function handleNewCluster() {
    if (!vault) {
      setMessage("Create or open a vault before adding clusters.");
      return;
    }
    const name = newClusterName.trim();
    if (!name) {
      setMessage("Name the cluster before creating it.");
      return;
    }
    setCreatingCluster(true);
    try {
      await createCluster({
        vault_id: vault.id,
        name,
        description: "",
        color: nextTint(backendClusters.length),
      });
      setNewClusterName("");
      await loadData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create this cluster.");
    } finally {
      setCreatingCluster(false);
    }
  }

  async function loadMoreClusters() {
    if (!vault || !nextClusterCursor || loadingMoreClusters) return;
    setLoadingMoreClusters(true);
    try {
      const page = await listClustersPage(vault.id, { limit: 100, cursor: nextClusterCursor });
      setBackendClusters((current) => [...current, ...page.items.map(clusterFromRecord)]);
      setNextClusterCursor(page.next_cursor);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load more clusters.");
    } finally {
      setLoadingMoreClusters(false);
    }
  }

  async function acceptSuggestion(suggestion: ClusterSuggestionRecord) {
    try {
      await updateSource(suggestion.source_id, { cluster_id: suggestion.suggested_cluster_id });
      setMessage(`Moved "${suggestion.source_title}" to ${suggestion.suggested_cluster_name}.`);
      await loadData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not move this source.");
    }
  }

  async function saveRename() {
    if (!renamingCluster || !renameDraft.trim()) return;
    setRenameBusy(true);
    try {
      const updated = clusterFromRecord(
        await updateCluster(renamingCluster.id, { name: renameDraft.trim() }),
      );
      setBackendClusters((current) =>
        current.map((cluster) => (cluster.id === updated.id ? updated : cluster)),
      );
      setRenamingCluster(null);
      setMessage(`Renamed cluster to "${updated.name}".`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not rename this cluster.");
    } finally {
      setRenameBusy(false);
    }
  }

  function dismissSuggestion(suggestion: ClusterSuggestionRecord) {
    if (!vault) return;
    const key = suggestionKey(suggestion);
    setDismissedSuggestions((current) => {
      const next = Array.from(new Set([...current, key]));
      writeDismissedSuggestions(vault.id, next);
      return next;
    });
    setLastDismissedSuggestion(suggestion);
  }

  function undoDismissSuggestion() {
    if (!vault || !lastDismissedSuggestion) return;
    const key = suggestionKey(lastDismissedSuggestion);
    setDismissedSuggestions((current) => {
      const next = current.filter((item) => item !== key);
      writeDismissedSuggestions(vault.id, next);
      return next;
    });
    setLastDismissedSuggestion(null);
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <div className="mx-auto min-h-full max-w-[1240px]">
        <div className="min-w-0 px-4 py-6 sm:px-7 sm:py-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 max-w-2xl">
            <h1 className="page-title flex flex-wrap items-center gap-3">
              Clusters
              <span className="rounded bg-muted px-2 py-1 font-sans text-sm text-muted-foreground">
                {clusters.length}
              </span>
            </h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Your memory spaces. Organized. Private. Under your control.
            </p>
          </div>
          <div className="desktop-window-action flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void loadData()} disabled={loading}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
            <Input
              aria-label="New cluster name"
              className="h-9 w-48"
              value={newClusterName}
              placeholder="Cluster name"
              onChange={(event) => setNewClusterName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleNewCluster();
              }}
            />
            <Button onClick={() => void handleNewCluster()} disabled={!newClusterName.trim() || creatingCluster}>
              <Plus className="h-4 w-4" /> New cluster
            </Button>
          </div>
        </div>

        {message && (
          <div className="vault-card mt-5 break-words px-3 py-2 text-sm text-muted-foreground">
            {message}
          </div>
        )}

          <section className="mt-9">
            <div className="min-w-0">
                <div className="grid grid-cols-[minmax(0,1fr)_64px_48px] border-b border-border px-2 pb-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground md:grid-cols-[minmax(0,1fr)_64px_112px_48px] xl:grid-cols-[minmax(0,1fr)_64px_64px_112px_48px]">
                  <span>Name</span>
                  <span>Sources</span>
                  <span className="hidden xl:block">Indexed</span>
                  <span className="hidden md:block">Activity</span>
                  <span />
                </div>
                <div>
                  {clusters.map((cluster) => {
                    const count = sourceCounts.get(cluster.id) ?? 0;
                    return (
                      <div
                        key={cluster.id}
                        className="grid w-full grid-cols-[minmax(0,1fr)_64px_48px] items-center border-b border-border px-2 py-4 text-left transition-colors hover:bg-card/65 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:grid-cols-[minmax(0,1fr)_64px_112px_48px] xl:grid-cols-[minmax(0,1fr)_64px_64px_112px_48px]"
                      >
                        <Link
                          to="/clusters/$clusterId"
                          params={{ clusterId: cluster.id }}
                          className="contents"
                        >
                        <div className="flex min-w-0 items-center gap-4">
                          <ClusterDocument tint={cluster.tint} />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2 break-words text-sm font-semibold">
                              {cluster.name}
                              {projectClusterIds.has(cluster.id) && (
                                <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                  <Code2 className="h-3 w-3" /> Project
                                </span>
                              )}
                            </div>
                            <p className="mt-1 line-clamp-2 break-words text-sm text-muted-foreground">
                              {cluster.summary || cluster.description || "No summary yet."}
                            </p>
                          </div>
                        </div>
                        <span className="text-sm tabular-nums text-muted-foreground">{count}</span>
                        <span className="hidden text-sm tabular-nums text-muted-foreground xl:block">
                          {(indexedCounts.get(cluster.id) ?? 0).toLocaleString()}
                        </span>
                        <span className="hidden break-words text-sm text-muted-foreground md:block">{clusterLastActivity(cluster, latestSources)}</span>
                        </Link>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="justify-self-end"
                          aria-label={`Rename ${cluster.name}`}
                          title="Rename cluster"
                          onClick={() => {
                            setRenamingCluster(cluster);
                            setRenameDraft(cluster.name);
                          }}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </div>
                    );
                  })}
                  {nextClusterCursor ? (
                    <div className="border-b border-border py-4 text-center">
                      <Button
                        variant="outline"
                        disabled={loadingMoreClusters}
                        onClick={() => void loadMoreClusters()}
                      >
                        {loadingMoreClusters ? "Loading..." : "Load more clusters"}
                      </Button>
                    </div>
                  ) : null}
                  {clusters.length === 0 && (
                    <div className="px-5 py-10 text-center text-sm text-muted-foreground">
                      No clusters yet. Create one or add sources so Vault can suggest memory spaces.
                    </div>
                  )}
                </div>
            </div>
          </section>

          {vault && visibleSuggestions.length > 0 && (
            <section className="mt-8 rounded-md border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <div className="text-sm font-semibold">Suggested moves</div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Review-only. Accepting a suggestion moves the source.
                </p>
              </div>
              <div className="divide-y divide-border">
                {visibleSuggestions.map((suggestion) => (
                  <div
                    key={`${suggestion.source_id}-${suggestion.suggested_cluster_id}`}
                    className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="break-words text-sm font-medium">{suggestion.source_title}</div>
                      <div className="mt-1 break-words text-xs text-muted-foreground">
                        {suggestion.suggested_cluster_name} /{" "}
                        {(suggestion.confidence * 100).toFixed(0)}% confidence
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      <Button size="sm" variant="outline" onClick={() => void acceptSuggestion(suggestion)}>
                        <Check className="h-4 w-4" /> Accept
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => dismissSuggestion(suggestion)}
                      >
                        <X className="h-4 w-4" /> Dismiss
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

      </div>
      {lastDismissedSuggestion ? (
        <div
          className="fixed bottom-10 right-4 z-50 flex max-w-sm items-center gap-3 rounded-md bg-[var(--text-primary)] px-4 py-3 text-sm text-[var(--bg-card)]"
          role="status"
        >
          <span className="min-w-0 flex-1 truncate">Suggestion dismissed</span>
          <button type="button" className="font-medium underline underline-offset-2" onClick={undoDismissSuggestion}>
            Undo
          </button>
        </div>
      ) : null}
      {renamingCluster ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="rename-cluster-title"
            className="w-full max-w-sm rounded-md border border-border bg-card p-5 shadow-xl"
          >
            <h2 id="rename-cluster-title" className="text-lg font-semibold">
              Rename cluster
            </h2>
            <Input
              autoFocus
              className="mt-4"
              value={renameDraft}
              onChange={(event) => setRenameDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setRenamingCluster(null);
                if (event.key === "Enter") void saveRename();
              }}
            />
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setRenamingCluster(null)}>
                Cancel
              </Button>
              <Button disabled={renameBusy || !renameDraft.trim()} onClick={() => void saveRename()}>
                {renameBusy ? "Saving" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ClusterDocument({ tint }: { tint: ClusterTint }) {
  return (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-white"
      style={{ background: `var(--cluster-${tint})` }}
    >
      <FileText className="h-4 w-4" />
    </span>
  );
}

function suggestionKey(suggestion: ClusterSuggestionRecord) {
  return `${suggestion.source_id}:${suggestion.suggested_cluster_id}`;
}

function dismissedSuggestionStorageKey(vaultId: string) {
  return `vault.clusters.dismissedSuggestions.${vaultId}`;
}

function readDismissedSuggestions(vaultId: string) {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(dismissedSuggestionStorageKey(vaultId)) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function writeDismissedSuggestions(vaultId: string, values: string[]) {
  window.localStorage.setItem(dismissedSuggestionStorageKey(vaultId), JSON.stringify(values));
}

function nextTint(index: number) {
  const tints: ClusterTint[] = ["sage", "sand", "sky", "blush", "lavender", "terracotta"];
  return tints[index % tints.length];
}

function clusterLastActivity(
  cluster: Cluster,
  latestSources: Map<string, { state: string; updatedAt: string }>,
) {
  const source = latestSources.get(cluster.id);
  if (!source) return "No activity";
  if (source.state === "failed") return "Needs review";
  if (source.state === "processing") return "In progress";
  return formatDate(source.updatedAt);
}

function formatDate(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
}
