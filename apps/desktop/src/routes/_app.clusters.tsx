import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Check, FileText, Grid2X2, List, MoreHorizontal, Plus, RefreshCw, X } from "lucide-react";
import { ExpertBadge } from "@/components/ClusterChip";
import { Button } from "@/components/ui/button";
import {
  createCluster,
  listClusterSuggestions,
  listClusters,
  listSources,
  listVaults,
  reindexVaultSearch,
  updateSource,
  type ClusterSuggestionRecord,
  type VaultRecord,
} from "@/lib/backend";
import type { Cluster, ClusterTint, Source } from "@/lib/mockStore";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters")({
  head: () => ({ meta: [{ title: "Clusters" }] }),
  component: ClustersList,
});

function ClustersList() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  const [vault, setBackendVault] = useState<VaultRecord | null>(null);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [suggestions, setSuggestions] = useState<ClusterSuggestionRecord[]>([]);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setBackendVault(activeVault);
      if (!activeVault) return;
      await reindexVaultSearch(activeVault.id).catch(() => undefined);
      const [clusterRows, sourceRows, suggestionRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id),
        listClusterSuggestions(activeVault.id),
      ]);
      const mappedClusters = clusterRows.map(clusterFromRecord);
      setBackendClusters(mappedClusters);
      setSelectedClusterId((current) => current ?? mappedClusters[0]?.id ?? null);
      setBackendSources(sourceRows.map(sourceFromRecord));
      setSuggestions(suggestionRows);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setMounted(true);
    void loadData();
  }, []);

  const clusters = !mounted ? [] : backendClusters;
  const sources = !mounted ? [] : backendSources;
  const visibleSuggestions = suggestions.filter(
    (suggestion) => !dismissedSuggestions.includes(suggestionKey(suggestion)),
  );
  const sourceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const source of sources) {
      if (source.clusterId) counts.set(source.clusterId, (counts.get(source.clusterId) ?? 0) + 1);
    }
    return counts;
  }, [sources]);
  const unclusteredCount = sources.filter((source) => !source.clusterId).length;
  const selectedCluster = clusters.find((cluster) => cluster.id === selectedClusterId) ?? clusters[0] ?? null;
  const selectedSources = selectedCluster
    ? sources.filter((source) => source.clusterId === selectedCluster.id)
    : [];
  const totalMemories = clusters.reduce((sum, cluster) => sum + memoryCount(cluster, sourceCounts.get(cluster.id) ?? 0), 0);
  const selectedMemoryCount = selectedCluster
    ? memoryCount(selectedCluster, sourceCounts.get(selectedCluster.id) ?? 0)
    : 0;

  if (pathname !== "/clusters") return <Outlet />;

  async function handleNewCluster() {
    if (!vault) {
      setMessage("Create or open a vault before adding clusters.");
      return;
    }
    await createCluster({
      vault_id: vault.id,
      name: "New cluster",
      description: "",
      color: nextTint(backendClusters.length),
    });
    await loadData();
  }

  async function acceptSuggestion(suggestion: ClusterSuggestionRecord) {
    await updateSource(suggestion.source_id, { cluster_id: suggestion.suggested_cluster_id });
    setMessage(`Moved "${suggestion.source_title}" to ${suggestion.suggested_cluster_name}.`);
    await loadData();
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <div className="mx-auto grid min-h-full max-w-[1500px] grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
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
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void loadData()} disabled={loading}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
            <Button onClick={() => void handleNewCluster()}>
              <Plus className="h-4 w-4" /> New cluster
            </Button>
            <div className="flex rounded-md border border-border bg-card p-1">
              <button className="rounded px-2 py-1 text-muted-foreground" type="button" aria-label="List view">
                <List className="h-4 w-4" />
              </button>
              <button className="rounded bg-muted px-2 py-1 text-foreground" type="button" aria-label="Grid view">
                <Grid2X2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {message && (
          <div className="vault-card mt-5 break-words px-3 py-2 text-sm text-muted-foreground">
            {message}
          </div>
        )}

          <section className="mt-9">
            <div className="overflow-x-auto">
              <div className="min-w-[760px]">
                <div className="grid grid-cols-[minmax(0,1fr)_96px_96px_140px_32px] border-b border-border px-2 pb-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  <span>Name</span>
                  <span>Sources</span>
                  <span>Memories</span>
                  <span>Last activity</span>
                  <span />
                </div>
                <div>
                  {clusters.map((cluster) => {
                    const count = sourceCounts.get(cluster.id) ?? 0;
                    return (
                      <button
                        key={cluster.id}
                        type="button"
                        onClick={() => setSelectedClusterId(cluster.id)}
                        className={
                          "grid w-full grid-cols-[minmax(0,1fr)_96px_96px_140px_32px] items-center border-b border-border px-2 py-4 text-left transition-colors hover:bg-card/65 " +
                          (selectedCluster?.id === cluster.id ? "bg-card/80" : "")
                        }
                      >
                        <div className="flex min-w-0 items-center gap-4">
                          <ClusterDocument tint={cluster.tint} />
                          <div className="min-w-0">
                            <div className="break-words text-sm font-semibold">{cluster.name}</div>
                            <p className="mt-1 line-clamp-2 break-words text-sm text-muted-foreground">
                              {cluster.summary || cluster.description || "No summary yet."}
                            </p>
                          </div>
                        </div>
                        <span className="text-sm tabular-nums text-muted-foreground">{count}</span>
                        <span className="text-sm tabular-nums text-muted-foreground">
                          {memoryCount(cluster, count).toLocaleString()}
                        </span>
                        <span className="break-words text-sm text-muted-foreground">{clusterLastActivity(cluster, sources)}</span>
                        <MoreHorizontal className="h-4 w-4 justify-self-end text-muted-foreground" />
                      </button>
                    );
                  })}
                  {clusters.length === 0 && (
                    <div className="px-5 py-10 text-center text-sm text-muted-foreground">
                      No clusters yet. Create one or add sources so Vault can suggest memory spaces.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>

          <section className="mt-8">
            <div className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Cluster overview
            </div>
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {clusters.map((cluster, index) => {
                const count = sourceCounts.get(cluster.id) ?? 0;
                const topSource = sources.find((source) => source.clusterId === cluster.id);
                return (
                  <Link
                    key={cluster.id}
                    to="/clusters/$clusterId"
                    params={{ clusterId: cluster.id }}
                    className="vault-cluster-card group min-h-[188px] p-4 transition-colors hover:border-primary/40"
                    style={{ ["--cluster-accent" as string]: `var(--cluster-${cluster.tint})` }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <FileText className="h-4 w-4 text-[var(--cluster-accent)]" />
                        <div className="min-w-0">
                          <div className="break-words text-sm font-semibold">{cluster.name}</div>
                          <div className="mt-1 break-words text-xs text-muted-foreground">
                            {count} sources <span className="px-1.5">/</span>{" "}
                            {memoryCount(cluster, count).toLocaleString()} memories
                          </div>
                        </div>
                      </div>
                      <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="my-4 h-px bg-border" />
                    <div className="text-xs text-muted-foreground">Top memory</div>
                    <div className="mt-2 line-clamp-2 break-words text-sm font-medium">
                      {topSource?.title || "No indexed memory yet"}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded border border-border px-1.5 py-0.5">
                        {topSource?.type?.toUpperCase?.() || "NOTE"}
                      </span>
                      <span>{clusterLastActivity(cluster, sources)}</span>
                    </div>
                  </Link>
                );
              })}
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
                        onClick={() =>
                          setDismissedSuggestions((current) => [...current, suggestionKey(suggestion)])
                        }
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

          <aside className="border-t border-border bg-card/35 px-4 py-6 sm:px-7 xl:border-l xl:border-t-0">
            {selectedCluster ? (
              <div className="xl:sticky xl:top-8">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: `var(--cluster-${selectedCluster.tint})` }}
                    />
                    <h2 className="min-w-0 break-words text-base font-semibold">{selectedCluster.name}</h2>
                  </div>
                  <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
                </div>
                <p className="mt-10 break-words text-sm leading-6 text-muted-foreground">
                  {selectedCluster.summary || selectedCluster.description || "A private local memory space."}
                </p>
                <div className="mt-8 grid grid-cols-2 gap-y-6">
                  <InspectorMetric label="Sources" value={sourceCounts.get(selectedCluster.id) ?? 0} />
                  <InspectorMetric label="Memories" value={selectedMemoryCount} />
                  <InspectorMetric label="Embeddings" value={selectedMemoryCount * 8} compact />
                  <InspectorMetric label="Size" value={`${Math.max(1, Math.round(selectedMemoryCount / 180))}.${selectedMemoryCount % 9} GB`} />
                </div>
                <div className="my-8 h-px bg-border" />
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Activity</div>
                <div className="mt-5 space-y-5 border-l border-border pl-5">
                  {selectedSources.slice(0, 5).map((source) => (
                    <div key={source.id} className="relative text-sm">
                      <span className="absolute -left-[23px] top-1.5 h-1.5 w-1.5 rounded-full bg-muted-foreground" />
                      <div className="font-medium">{formatDate(source.updatedAt)}</div>
                      <div className="mt-1 break-words text-muted-foreground">Added {source.title}</div>
                    </div>
                  ))}
                  {selectedSources.length === 0 && (
                    <div className="text-sm text-muted-foreground">No source activity yet.</div>
                  )}
                </div>
                <div className="my-8 h-px bg-border" />
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Top sources</div>
                <div className="mt-5 space-y-4">
                  {selectedSources.slice(0, 3).map((source) => (
                    <Link
                      key={source.id}
                      to="/sources"
                      className="flex min-w-0 gap-3 text-sm hover:text-primary"
                    >
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-issue)]" />
                      <span className="min-w-0">
                        <span className="line-clamp-2 break-words font-medium">{source.title}</span>
                        <span className="mt-1 block break-words text-xs text-muted-foreground">{source.type.toUpperCase()} / {Math.max(1, Math.round((source.text || "").length / 120))} memories</span>
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">Select a cluster to inspect it.</div>
            )}
          </aside>
      </div>
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

function InspectorMetric({
  label,
  value,
  compact,
}: {
  label: string;
  value: number | string;
  compact?: boolean;
}) {
  const display =
    typeof value === "number" ? (compact ? compactNumber(value) : value.toLocaleString()) : value;
  return (
    <div className="min-w-0">
      <div className="break-words text-xl font-semibold tabular-nums">{display}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function suggestionKey(suggestion: ClusterSuggestionRecord) {
  return `${suggestion.source_id}:${suggestion.suggested_cluster_id}`;
}

function nextTint(index: number) {
  const tints: ClusterTint[] = ["sage", "sand", "sky", "blush", "lavender", "terracotta"];
  return tints[index % tints.length];
}

function memoryCount(cluster: Cluster, sourceCount: number) {
  return Math.max(sourceCount * 64, Math.round((cluster.summary?.length ?? cluster.description?.length ?? 42) * 3.4));
}

function clusterLastActivity(cluster: Cluster, sources: Source[]) {
  const source = sources
    .filter((item) => item.clusterId === cluster.id)
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))[0];
  if (!source) return "No activity";
  if (source.status === "failed" || source.state === "failed") return "Needs review";
  if (source.status === "extracting" || source.state === "extracting") return "In progress";
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

function compactNumber(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString();
}
