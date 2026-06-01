import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  ArrowRight,
  FileText,
  Filter,
  List,
  Maximize2,
  MoreHorizontal,
  MoveRight,
  Search,
  SlidersHorizontal,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Cluster, Source } from "@/lib/mockStore";
import {
  listClusters,
  listSources,
  listVaults,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

type MapNode = {
  id: string;
  cluster: Cluster;
  x: number;
  y: number;
  label?: string;
  w?: number;
};

function MapView() {
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drillClusterId, setDrillClusterId] = useState<string | null>(null);

  useEffect(() => {
    async function loadMapData() {
      try {
        const vaults = await listVaults();
        const activeVault = vaults[0] ?? null;
        if (!activeVault) return;
        const [clusterRows, sourceRows] = await Promise.all([
          listClusters(activeVault.id),
          listSources(activeVault.id),
        ]);
        const mappedClusters = clusterRows.map(clusterFromRecord);
        setBackendClusters(mappedClusters);
        setBackendSources(sourceRows.map(sourceFromRecord));
        setSelectedId((current) => current ?? mappedClusters[0]?.id ?? null);
      } catch {
        setBackendClusters([]);
        setBackendSources([]);
      }
    }

    void loadMapData();
  }, []);

  const clusters = backendClusters;
  const sources = backendSources;
  const selected = clusters.find((cluster) => cluster.id === selectedId) ?? clusters[0];
  const selectedSources = selected
    ? sources.filter((source) => source.clusterId === selected.id)
    : [];
  const drilledCluster = drillClusterId
    ? clusters.find((cluster) => cluster.id === drillClusterId) ?? null
    : null;
  const drilledSources = drilledCluster
    ? sources.filter((source) => source.clusterId === drilledCluster.id)
    : [];
  const sourceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const source of sources) {
      if (source.clusterId) counts.set(source.clusterId, (counts.get(source.clusterId) ?? 0) + 1);
    }
    return counts;
  }, [sources]);

  const graphNodes = useMemo<MapNode[]>(() => {
    const ranked = [...clusters]
      .sort((a, b) => (sourceCounts.get(b.id) ?? 0) - (sourceCounts.get(a.id) ?? 0))
      .slice(0, 80);
    return ranked.map((cluster, index) => {
      if (index === 0) return { id: cluster.id, cluster, x: 50, y: 43, w: 178 };
      const angle = index * 2.399963;
      const ring = Math.floor((index - 1) / 8) + 1;
      const radius = 16 + ring * 11;
      return {
        id: cluster.id,
        cluster,
        x: Math.max(12, Math.min(88, 50 + Math.cos(angle) * radius)),
        y: Math.max(16, Math.min(84, 43 + Math.sin(angle) * radius * 0.72)),
        label: relationshipLabel(index),
        w: 154 + Math.min(34, cluster.name.length * 2),
      };
    });
  }, [clusters, sourceCounts]);

  if (!selected) {
    return (
      <div className="vault-page-wash h-full overflow-y-auto px-8 py-9">
        <h1 className="page-title">Map</h1>
        <div className="mt-8 rounded-md border border-border bg-card p-8 text-sm text-muted-foreground">
          No cluster map is available yet. Create a vault, add sources, and index them to populate this view.
        </div>
      </div>
    );
  }

  return (
    <div className="vault-page-wash grid h-full grid-cols-[minmax(0,1fr)_326px] overflow-hidden">
      <main className="min-w-0 overflow-y-auto px-8 py-9">
        <header>
          <h1 className="page-title">Map</h1>
          <p className="mt-3 text-sm text-muted-foreground">A navigable view of your memory spaces.</p>
        </header>

        <div className="mt-8 flex flex-wrap items-center gap-2">
          <div className="flex h-10 w-[220px] items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
            <Search className="h-4 w-4" />
            Search map
          </div>
          <Button variant="outline" className="gap-2"><Filter className="h-4 w-4" /> Filter</Button>
          <Button variant="outline" className="gap-2" onClick={() => setDrillClusterId(null)}><Maximize2 className="h-4 w-4" /> Fit view</Button>
          <Button variant="outline" className="gap-2"><List className="h-4 w-4" /> List</Button>
          {drilledCluster && (
            <Button variant="outline" className="gap-2" onClick={() => setDrillClusterId(null)}>
              Back to map
            </Button>
          )}
          <Button variant="outline" className="ml-auto gap-2"><span className="h-2.5 w-2.5 rounded-full bg-muted-foreground" /> Legend</Button>
        </div>

        <section className="relative mt-6 h-[660px] overflow-hidden rounded-md">
          {drilledCluster ? (
            <ClusterDataPointMap
              cluster={drilledCluster}
              sources={drilledSources}
              onBack={() => setDrillClusterId(null)}
            />
          ) : (
            <>
              <svg className="absolute inset-0 h-full w-full" role="presentation">
                {graphNodes.slice(1).map((_, index) => (
                  <GraphLine key={graphNodes[index + 1]?.id} nodes={graphNodes} from={0} to={index + 1} />
                ))}
              </svg>

              {graphNodes.map((node) => (
                <MapCard
                  key={node.id}
                  node={node}
                  selected={node.cluster.id === selected.id}
                  sourceCount={sourceCounts.get(node.cluster.id) ?? 0}
                  onSelect={() => {
                    setSelectedId(node.cluster.id);
                    setDrillClusterId(node.cluster.id);
                  }}
                />
              ))}
            </>
          )}

          <div className="absolute bottom-12 left-0 flex flex-col overflow-hidden rounded-md border border-border bg-card">
            <button className="flex h-9 w-9 items-center justify-center border-b border-border" type="button"><ZoomIn className="h-4 w-4" /></button>
            <button className="flex h-9 w-9 items-center justify-center border-b border-border" type="button"><ZoomOut className="h-4 w-4" /></button>
            <button className="flex h-9 w-9 items-center justify-center" type="button"><Maximize2 className="h-4 w-4" /></button>
          </div>
        </section>

        <section className="rounded-md border border-border bg-card px-4 py-3">
          <div className="mb-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-4">
              <span className="font-medium uppercase tracking-[0.14em] text-muted-foreground">List fallback</span>
              <span className="text-muted-foreground">Top by connections</span>
            </div>
            <Link to="/clusters" className="flex items-center gap-2 text-primary">
              View all in list <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="grid gap-2 md:grid-cols-5">
            {clusters.slice(0, 5).map((cluster) => (
              <button
                key={cluster.id}
                type="button"
                onClick={() => {
                  setSelectedId(cluster.id);
                  setDrillClusterId(cluster.id);
                }}
                className="flex items-center gap-3 border-r border-border px-2 py-1.5 text-left last:border-r-0"
              >
                <IconTile tint={cluster.tint} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{cluster.name}</span>
                  <span className="block text-xs text-muted-foreground">{sourceCounts.get(cluster.id) ?? 0} sources</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      </main>

      <aside className="right-panel px-7 py-8">
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full bg-[var(--cluster-${selected.tint})]`} />
          <h2 className="text-lg font-semibold">{selected.name}</h2>
          <MoreHorizontal className="ml-auto h-4 w-4 text-muted-foreground" />
          <span className="h-6 w-px bg-border" />
          <X className="h-4 w-4 text-muted-foreground" />
        </div>
        <p className="mt-8 text-sm leading-6 text-muted-foreground">{selected.description}</p>
        <p className="mt-4 text-xs text-muted-foreground">Updated {formatDate(selected.lastActive)} <span className="px-2">/</span> Local vault</p>

        <MetricGrid className="mt-10" sources={selectedSources.length} />
        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Nearest clusters</h3>
        <div className="mt-5 space-y-5">
          {nearestClusters(clusters, selected, sourceCounts).map((cluster) => (
            <div key={cluster.id} className="flex items-center gap-3 text-sm">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: `var(--cluster-${cluster.tint})` }}
              />
              <span className="flex-1">{cluster.name}</span>
              <span className="text-muted-foreground">{sourceCounts.get(cluster.id) ?? 0}</span>
            </div>
          ))}
        </div>

        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Related sources</h3>
        <div className="mt-5 space-y-5">
          {selectedSources.slice(0, 5).map((source) => (
            <SourceLine key={source.id} source={source} memories={memoryEstimate(source)} />
          ))}
          {selectedSources.length === 0 && (
            <div className="text-sm text-muted-foreground">No sources are linked to this cluster yet.</div>
          )}
        </div>
        <Link to="/sources" className="mt-6 flex items-center gap-2 text-sm text-primary">
          View all {selectedSources.length} sources <ArrowRight className="h-4 w-4" />
        </Link>

        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Actions</h3>
        <div className="mt-4 space-y-2">
          <ActionButton icon={<MoveRight className="h-4 w-4" />} label="Open cluster datapoints" onClick={() => setDrillClusterId(selected.id)} />
          <ActionButton icon={<SlidersHorizontal className="h-4 w-4" />} label="Suggest cluster correction" />
          <ActionButton icon={<Archive className="h-4 w-4" />} label="Archive this cluster" danger />
        </div>
      </aside>
    </div>
  );
}

function GraphLine({ nodes, from, to }: { nodes: MapNode[]; from: number; to: number }) {
  const a = nodes[from];
  const b = nodes[to];
  if (!a || !b) return null;
  return (
    <line
      x1={`${a.x}%`}
      y1={`${a.y}%`}
      x2={`${b.x}%`}
      y2={`${b.y}%`}
      stroke="var(--border-default)"
      strokeWidth="1"
    />
  );
}

function MapCard({
  node,
  selected,
  sourceCount,
  onSelect,
}: {
  node: MapNode;
  selected: boolean;
  sourceCount: number;
  onSelect: () => void;
}) {
  const memories = sourceCount * 19 + (node.cluster.name.length % 5) * 23;
  return (
    <button
      type="button"
      onClick={onSelect}
      className="absolute -translate-x-1/2 -translate-y-1/2 rounded-md border bg-card/95 px-4 py-3 text-left transition-transform hover:-translate-y-[calc(50%+2px)]"
      style={{
        left: `${node.x}%`,
        top: `${node.y}%`,
        width: node.w ?? 170,
        borderColor: selected ? `var(--cluster-${node.cluster.tint})` : "var(--border)",
        background: "var(--bg-card)",
      }}
    >
      <div className="flex gap-3">
        <IconTile tint={node.cluster.tint} />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{node.cluster.name}</div>
          <div className="mt-1 text-xs leading-5 text-muted-foreground">
            {sourceCount} sources <span className="px-1">/</span> {memories} memories
          </div>
        </div>
      </div>
    </button>
  );
}

function ClusterDataPointMap({
  cluster,
  sources,
  onBack,
}: {
  cluster: Cluster;
  sources: Source[];
  onBack: () => void;
}) {
  const visibleSources = sources.slice(0, 160);
  const hiddenCount = Math.max(0, sources.length - visibleSources.length);
  const points = visibleSources.map((source, index) => {
    const angle = index * 2.399963;
    const ring = Math.floor(index / 20) + 1;
    const radius = 80 + ring * 42;
    return {
      source,
      x: 50 + Math.cos(angle) * Math.min(38, radius / 11),
      y: 48 + Math.sin(angle) * Math.min(34, radius / 14),
    };
  });

  return (
    <div className="absolute inset-0">
      <svg className="absolute inset-0 h-full w-full" role="presentation">
        {points.map((point) => (
          <line
            key={point.source.id}
            x1="50%"
            y1="48%"
            x2={`${point.x}%`}
            y2={`${point.y}%`}
            stroke="var(--border-default)"
            strokeWidth="1"
          />
        ))}
      </svg>
      <button
        type="button"
        onClick={onBack}
        className="absolute left-0 top-0 z-20 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        Back to clusters
      </button>
      <div
        className="absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-md border px-5 py-4 text-center"
        style={{
          left: "50%",
          top: "48%",
          width: 190,
          borderColor: `var(--cluster-${cluster.tint})`,
          background: "var(--bg-card)",
        }}
      >
        <IconTile tint={cluster.tint} />
        <div className="mt-3 text-sm font-semibold">{cluster.name}</div>
        <div className="mt-1 text-xs text-muted-foreground">{sources.length} data points</div>
      </div>
      {points.map((point) => (
        <Link
          key={point.source.id}
          to="/sources"
          className="absolute z-20 -translate-x-1/2 -translate-y-1/2 rounded-md border border-border bg-card px-3 py-2 text-left hover:bg-accent"
          style={{
            left: `${point.x}%`,
            top: `${point.y}%`,
            width: 150,
          }}
          title={point.source.title}
        >
          <div className="truncate text-xs font-medium">{point.source.title}</div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {point.source.type} / {point.source.state}
          </div>
        </Link>
      ))}
      {hiddenCount > 0 && (
        <div className="absolute bottom-0 left-0 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
          Showing {visibleSources.length} of {sources.length} data points. Use the list fallback for the full set.
        </div>
      )}
      {sources.length === 0 && (
        <div className="absolute left-1/2 top-[62%] -translate-x-1/2 text-sm text-muted-foreground">
          This cluster has no linked data points yet.
        </div>
      )}
    </div>
  );
}

function IconTile({ tint }: { tint: Cluster["tint"] }) {
  return (
    <span
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border"
      style={{
        borderColor: `var(--cluster-${tint})`,
        color: `var(--cluster-${tint})`,
        background: "var(--bg-card)",
      }}
    >
      <FileText className="h-4 w-4" />
    </span>
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

function SourceLine({ source, memories }: { source: Source; memories: number }) {
  return (
    <div className="flex gap-3 text-sm">
      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-issue)]" />
      <div>
        <div className="leading-5">{source.title}</div>
        <div className="mt-1 text-xs text-muted-foreground">{source.type.toUpperCase()} <span className="px-2">/</span> {memories} memories</div>
      </div>
    </div>
  );
}

function ActionButton({ icon, label, danger, onClick }: { icon: ReactNode; label: string; danger?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-md border bg-background px-3 py-2 text-left text-sm ${
        danger ? "border-destructive/30 text-destructive" : "border-border text-foreground"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function Divider() {
  return <div className="my-8 h-px bg-border" />;
}

function relationshipLabel(index: number) {
  return ["informs", "references", "aligns with", "inspires", "discussed in", "validates", "compares with", "uses patterns"][index % 8];
}

function nearestClusters(clusters: Cluster[], selected: Cluster, counts: Map<string, number>) {
  return clusters
    .filter((cluster) => cluster.id !== selected.id)
    .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0))
    .slice(0, 5);
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
