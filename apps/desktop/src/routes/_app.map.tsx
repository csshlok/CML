import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { ClusterMap } from "@/components/ClusterMap";
import { Switch } from "@/components/ui/switch";
import {
  useStore,
  type Cluster,
  type ClusterTint,
  type ExpertStatus,
  type Source,
  type SourceState,
  type SourceType,
} from "@/lib/mockStore";
import { ExpertBadge } from "@/components/ClusterChip";
import {
  listClusters,
  listSources,
  listVaults,
  type ClusterRecord,
  type SourceRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

function MapView() {
  const [showSources, setShowSources] = useState(true);
  const { clusters: mockClusters, sources: mockSources, setVault } = useStore();
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendReady, setBackendReady] = useState(false);

  useEffect(() => {
    async function loadMapData() {
      try {
        const vaults = await listVaults();
        const activeVault = vaults[0] ?? null;
        if (!activeVault) return;
        setVault(activeVault.path);
        const [clusterRows, sourceRows] = await Promise.all([
          listClusters(activeVault.id),
          listSources(activeVault.id),
        ]);
        setBackendClusters(clusterRows.map(clusterFromRecord));
        setBackendSources(sourceRows.map(sourceFromRecord));
        setBackendReady(true);
      } catch {
        setBackendReady(false);
      }
    }

    void loadMapData();
  }, [setVault]);

  const clusters = backendReady ? backendClusters : mockClusters;
  const sources = backendReady ? backendSources : mockSources;
  const indexed = sources.filter((source) => source.state === "indexed").length;
  const learning = clusters.filter((cluster) => cluster.expert === "learning").length;
  const unclustered = useMemo(
    () => sources.filter((source) => !source.clusterId).length,
    [sources],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-border bg-background/80 px-6 py-3">
        <div>
          <h1 className="font-serif text-2xl">Map</h1>
          <p className="text-xs text-muted-foreground">
            A navigable view of spaces, sources, and local expert activity.
          </p>
        </div>
        <div className="ml-4 hidden items-center gap-4 text-xs text-muted-foreground md:flex">
          <span>{clusters.length} clusters</span>
          <span>{indexed} indexed sources</span>
          <span>{unclustered} loose points</span>
          <span>{learning} learning</span>
        </div>
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={showSources} onCheckedChange={setShowSources} /> Show sources
        </label>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_280px]">
        <ClusterMap showSources={showSources} clusters={clusters} sources={sources} />
        <aside className="hidden border-l border-border bg-card/45 p-4 lg:block">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Cluster health
          </div>
          <div className="mt-3 space-y-3">
            {clusters.map((cluster) => {
              const count = sources.filter((source) => source.clusterId === cluster.id).length;
              return (
                <div key={cluster.id} className="rounded-md border border-border bg-background/70 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="truncate text-sm font-medium">{cluster.name}</div>
                    <ExpertBadge status={cluster.expert} />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    {count} sources / {cluster.styleProfile || "Style profile pending"}
                  </div>
                </div>
              );
            })}
            {unclustered > 0 && (
              <div className="rounded-md border border-dashed border-border bg-background/55 p-3">
                <div className="text-sm font-medium">Loose memory</div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {unclustered} source{unclustered === 1 ? "" : "s"} not assigned to a cluster yet.
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function sourceFromRecord(record: SourceRecord): Source {
  return {
    id: record.id,
    title: record.title,
    type: normalizeSourceType(record.source_type),
    clusterId: record.cluster_id,
    state: normalizeSourceState(record.state),
    updatedAt: record.updated_at,
    preview: record.extracted_text || record.raw_text,
    summary: record.summary,
    tags: record.tags ?? [],
    vaultPath: record.original_path ?? undefined,
    localPath: record.original_path ?? undefined,
    url: record.url ?? undefined,
  };
}

function clusterFromRecord(record: ClusterRecord): Cluster {
  return {
    id: record.id,
    name: record.name,
    tint: normalizeTint(record.color),
    description: record.description,
    expert: normalizeExpertStatus(record.expert_status),
    lastActive: record.updated_at,
    summary: record.description,
    styleProfile: "Style profile pending",
  };
}

function normalizeSourceType(value: string): SourceType {
  return value === "file" || value === "link" || value === "note" || value === "image"
    ? value
    : "file";
}

function normalizeSourceState(value: string): SourceState {
  return value === "waiting" ||
    value === "extracting" ||
    value === "indexed" ||
    value === "needs-review" ||
    value === "failed"
    ? value
    : "waiting";
}

function normalizeTint(value: string): ClusterTint {
  return value === "sage" ||
    value === "sand" ||
    value === "sky" ||
    value === "blush" ||
    value === "lavender" ||
    value === "terracotta"
    ? value
    : "sage";
}

function normalizeExpertStatus(value: string): ExpertStatus {
  return value === "setting-up" ||
    value === "learning" ||
    value === "ready" ||
    value === "needs-update" ||
    value === "paused" ||
    value === "issue"
    ? value
    : "setting-up";
}
