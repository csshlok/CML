import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Check, Plus, RefreshCw } from "lucide-react";
import { ClusterDot, ExpertBadge } from "@/components/ClusterChip";
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
import {
  useStore,
  type Cluster,
  type ClusterTint,
  type Source,
} from "@/lib/mockStore";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/clusters")({
  head: () => ({ meta: [{ title: "Clusters" }] }),
  component: ClustersList,
});

function ClustersList() {
  const { clusters: mockClusters, sources: mockSources, addCluster, setVault } = useStore();
  const [vault, setBackendVault] = useState<VaultRecord | null>(null);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [suggestions, setSuggestions] = useState<ClusterSuggestionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setBackendVault(activeVault);
      if (!activeVault) return;
      setVault(activeVault.path);
      await reindexVaultSearch(activeVault.id).catch(() => undefined);
      const [clusterRows, sourceRows, suggestionRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id),
        listClusterSuggestions(activeVault.id),
      ]);
      setBackendClusters(clusterRows.map(clusterFromRecord));
      setBackendSources(sourceRows.map(sourceFromRecord));
      setSuggestions(suggestionRows);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const clusters = vault ? backendClusters : mockClusters;
  const sources = vault ? backendSources : mockSources;
  const sourceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const source of sources) {
      if (source.clusterId) counts.set(source.clusterId, (counts.get(source.clusterId) ?? 0) + 1);
    }
    return counts;
  }, [sources]);

  async function handleNewCluster() {
    if (!vault) {
      addCluster({ name: "New cluster" });
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
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-8 py-8">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Clusters</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Review context spaces and apply suggested source moves.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void loadData()} disabled={loading}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Refresh
            </Button>
            <Button onClick={() => void handleNewCluster()}>
              <Plus className="mr-1.5 h-4 w-4" /> New cluster
            </Button>
          </div>
        </div>

        {message && (
          <div className="mt-5 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
            {message}
          </div>
        )}

        {vault && (
          <section className="mt-6 rounded-md border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Suggested moves</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                These are review-only. Nothing changes until you accept a suggestion.
              </p>
            </div>
            <div className="divide-y divide-border">
              {suggestions.length === 0 ? (
                <div className="px-4 py-4 text-sm text-muted-foreground">
                  No cluster moves suggested right now.
                </div>
              ) : (
                suggestions.map((suggestion) => (
                  <div key={`${suggestion.source_id}-${suggestion.suggested_cluster_id}`} className="flex items-center gap-4 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{suggestion.source_title}</div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        Suggested: {suggestion.suggested_cluster_name} / {(suggestion.confidence * 100).toFixed(0)}% confidence
                      </div>
                    </div>
                    <Button size="sm" variant="outline" onClick={() => void acceptSuggestion(suggestion)}>
                      <Check className="mr-1.5 h-4 w-4" /> Accept
                    </Button>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.map((cluster) => {
            const count = sourceCounts.get(cluster.id) ?? 0;
            return (
              <Link
                key={cluster.id}
                to="/clusters/$clusterId"
                params={{ clusterId: cluster.id }}
                className="group rounded-md border border-border bg-card p-4 transition-colors hover:bg-accent"
              >
                <div className="flex items-center gap-2">
                  <ClusterDot tint={cluster.tint} />
                  <span className="truncate font-medium">{cluster.name}</span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                  {cluster.summary || cluster.description || "No summary yet."}
                </p>
                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{count} sources</span>
                  <ExpertBadge status={cluster.expert} />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function nextTint(index: number) {
  const tints: ClusterTint[] = ["sage", "sand", "sky", "blush", "lavender", "terracotta"];
  return tints[index % tints.length];
}
