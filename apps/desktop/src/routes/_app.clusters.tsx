import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Check, Code2, FileText, Plus, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createCluster,
  listClusterSuggestions,
  listClusters,
  listProjects,
  listSources,
  listVaults,
  sourceCountsByCluster,
  updateSource,
  type ClusterSuggestionRecord,
  type VaultRecord,
} from "@/lib/backend";
import type { Cluster, ClusterTint, Source } from "@/lib/domain";
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
  const [sourceCountRows, setSourceCountRows] = useState<Array<{ cluster_id: string | null; state: string; total: number }>>([]);
  const [projectClusterIds, setProjectClusterIds] = useState<Set<string>>(new Set());
  const [newClusterName, setNewClusterName] = useState("");
  const [creatingCluster, setCreatingCluster] = useState(false);

  async function loadData() {
    setLoading(true);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setBackendVault(activeVault);
      if (!activeVault) return;
      const [clusterRows, sourceRows, suggestionRows, countResult, projectRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id, { limit: 200 }),
        listClusterSuggestions(activeVault.id),
        sourceCountsByCluster(activeVault.id),
        listProjects(activeVault.id),
      ]);
      const mappedClusters = clusterRows.map(clusterFromRecord);
      setBackendClusters(mappedClusters);
      setBackendSources(sourceRows.map(sourceFromRecord));
      setSuggestions(suggestionRows);
      setSourceCountRows(countResult.items);
      setProjectClusterIds(new Set(projectRows.map((project) => project.primary_cluster_id)));
      setMessage(null);
    } catch {
      setMessage("Vault could not load your clusters. Check Settings → Health, then try again.");
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
    await createCluster({
      vault_id: vault.id,
      name,
      description: "",
      color: nextTint(backendClusters.length),
    });
    setNewClusterName("");
    await loadData().finally(() => setCreatingCluster(false));
  }

  async function acceptSuggestion(suggestion: ClusterSuggestionRecord) {
    await updateSource(suggestion.source_id, { cluster_id: suggestion.suggested_cluster_id });
    setMessage(`Moved "${suggestion.source_title}" to ${suggestion.suggested_cluster_name}.`);
    await loadData();
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
          <div className="flex flex-wrap gap-2">
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
            <div className="overflow-x-auto">
              <div className="min-w-[760px]">
                <div className="grid grid-cols-[minmax(0,1fr)_96px_96px_140px_32px] border-b border-border px-2 pb-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  <span>Name</span>
                  <span>Sources</span>
                  <span>Indexed</span>
                  <span>Last activity</span>
                  <span />
                </div>
                <div>
                  {clusters.map((cluster) => {
                    const count = sourceCounts.get(cluster.id) ?? 0;
                    return (
                      <Link
                        key={cluster.id}
                        to="/clusters/$clusterId"
                        params={{ clusterId: cluster.id }}
                        className="grid w-full grid-cols-[minmax(0,1fr)_96px_96px_140px_32px] items-center border-b border-border px-2 py-4 text-left transition-colors hover:bg-card/65"
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
                        <span className="text-sm tabular-nums text-muted-foreground">
                          {(indexedCounts.get(cluster.id) ?? 0).toLocaleString()}
                        </span>
                        <span className="break-words text-sm text-muted-foreground">{clusterLastActivity(cluster, sources)}</span>
                        <span className="justify-self-end text-xs text-muted-foreground">Open</span>
                      </Link>
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

function suggestionKey(suggestion: ClusterSuggestionRecord) {
  return `${suggestion.source_id}:${suggestion.suggested_cluster_id}`;
}

function nextTint(index: number) {
  const tints: ClusterTint[] = ["sage", "sand", "sky", "blush", "lavender", "terracotta"];
  return tints[index % tints.length];
}

function clusterLastActivity(cluster: Cluster, sources: Source[]) {
  const source = sources
    .filter((item) => item.clusterId === cluster.id)
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))[0];
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
