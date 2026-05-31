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
import {
  useStore,
  type Cluster,
  type Source,
} from "@/lib/mockStore";
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
  const { clusters: mockClusters, sources: mockSources, setVault } = useStore();
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [selectedId, setSelectedId] = useState("c-design");

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

  const clusters = backendReady && backendClusters.length > 0 ? backendClusters : mockClusters;
  const sources = backendReady && backendSources.length > 0 ? backendSources : mockSources;
  const selected = clusters.find((cluster) => cluster.id === selectedId) ?? clusters[0];
  const selectedSources = selected
    ? sources.filter((source) => source.clusterId === selected.id)
    : [];

  const graphNodes = useMemo<MapNode[]>(() => {
    const [design, strategy, health, travel, meetings] = clusters;
    const personal: Cluster = {
      id: "c-personal",
      name: "Personal Writing",
      tint: "sage",
      description: "Drafts, essays, and reflective notes.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Writing references and draft thinking.",
      styleProfile: "Reflective and personal.",
    };
    const interviews: Cluster = {
      id: "c-interviews",
      name: "User Interviews",
      tint: "blush",
      description: "Customer interview notes and themes.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Interviews and user research themes.",
      styleProfile: "Evidence-led.",
    };
    const competitor: Cluster = {
      id: "c-competitor",
      name: "Competitor Analysis",
      tint: "sky",
      description: "Competitive analysis and market mapping.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Competitive positioning references.",
      styleProfile: "Analytical.",
    };
    const ux: Cluster = {
      id: "c-ux",
      name: "UX Patterns",
      tint: "lavender",
      description: "Interaction and design pattern library.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Reusable interaction patterns.",
      styleProfile: "Pattern-based.",
    };
    const systems: Cluster = {
      id: "c-systems",
      name: "Design Systems",
      tint: "sand",
      description: "Design system references.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Tokens, components, and systems.",
      styleProfile: "Systematic.",
    };
    const principles: Cluster = {
      id: "c-principles",
      name: "Interface Principles",
      tint: "sand",
      description: "Interface principles and heuristics.",
      expert: "ready",
      lastActive: new Date().toISOString(),
      summary: "Principles for calm interfaces.",
      styleProfile: "Principled.",
    };

    return [
      { id: design?.id ?? "c-design", cluster: design, x: 50, y: 43, w: 170 },
      { id: health?.id ?? "c-health", cluster: health, x: 22, y: 22, label: "informs", w: 182 },
      { id: travel?.id ?? "c-travel", cluster: travel, x: 50, y: 18, label: "references", w: 176 },
      { id: strategy?.id ?? "c-strategy", cluster: strategy, x: 78, y: 25, label: "aligns with", w: 174 },
      { id: personal.id, cluster: personal, x: 82, y: 43, label: "inspires", w: 166 },
      { id: meetings?.id ?? "c-meetings", cluster: meetings, x: 20, y: 43, label: "discussed in", w: 164 },
      { id: interviews.id, cluster: interviews, x: 22, y: 62, label: "validates", w: 160 },
      { id: competitor.id, cluster: competitor, x: 50, y: 66, label: "compares with", w: 188 },
      { id: ux.id, cluster: ux, x: 80, y: 62, label: "uses patterns", w: 158 },
      { id: systems.id, cluster: systems, x: 38, y: 83, label: "influences", w: 158 },
      { id: principles.id, cluster: principles, x: 61, y: 83, label: "foundational to", w: 172 },
    ].filter((node) => node.cluster);
  }, [clusters]);

  if (!selected) return null;

  return (
    <div className="vault-page-wash grid h-full grid-cols-[minmax(0,1fr)_326px] overflow-hidden">
      <main className="min-w-0 overflow-y-auto px-8 py-9">
        <header>
          <h1 className="font-serif text-4xl font-medium tracking-tight">Map</h1>
          <p className="mt-3 text-sm text-muted-foreground">A navigable view of your memory spaces.</p>
        </header>

        <div className="mt-8 flex flex-wrap items-center gap-2">
          <div className="flex h-10 w-[220px] items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
            <Search className="h-4 w-4" />
            Search map
          </div>
          <Button variant="outline" className="gap-2"><Filter className="h-4 w-4" /> Filter</Button>
          <Button variant="outline" className="gap-2"><Maximize2 className="h-4 w-4" /> Fit view</Button>
          <Button variant="outline" className="gap-2"><List className="h-4 w-4" /> List</Button>
          <Button variant="outline" className="ml-auto gap-2"><span className="h-2.5 w-2.5 rounded-full bg-muted-foreground" /> Legend</Button>
        </div>

        <section className="relative mt-6 h-[660px] overflow-hidden rounded-md">
          <svg className="absolute inset-0 h-full w-full" role="presentation">
            <GraphLine nodes={graphNodes} from={0} to={1} />
            <GraphLine nodes={graphNodes} from={0} to={2} />
            <GraphLine nodes={graphNodes} from={0} to={3} />
            <GraphLine nodes={graphNodes} from={0} to={4} />
            <GraphLine nodes={graphNodes} from={0} to={5} />
            <GraphLine nodes={graphNodes} from={0} to={6} />
            <GraphLine nodes={graphNodes} from={0} to={7} />
            <GraphLine nodes={graphNodes} from={0} to={8} />
            <GraphLine nodes={graphNodes} from={7} to={9} />
            <GraphLine nodes={graphNodes} from={7} to={10} />
          </svg>

          {graphNodes.map((node, index) => (
            <MapCard
              key={node.id}
              node={node}
              selected={node.cluster.id === selected.id || (!clusters.some((c) => c.id === node.id) && index === 0)}
              sourceCount={sources.filter((source) => source.clusterId === node.cluster.id).length || nodeSourceCount(index)}
              onSelect={() => setSelectedId(node.cluster.id)}
            />
          ))}

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
            {clusters.slice(0, 5).map((cluster, index) => (
              <button
                key={cluster.id}
                type="button"
                onClick={() => setSelectedId(cluster.id)}
                className="flex items-center gap-3 border-r border-border px-2 py-1.5 text-left last:border-r-0"
              >
                <IconTile tint={cluster.tint} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{cluster.name}</span>
                  <span className="block text-xs text-muted-foreground">{10 - index} connections</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      </main>

      <aside className="overflow-y-auto border-l border-border bg-card/35 px-7 py-8">
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full bg-[var(--cluster-${selected.tint})]`} />
          <h2 className="text-lg font-semibold">{selected.name}</h2>
          <MoreHorizontal className="ml-auto h-4 w-4 text-muted-foreground" />
          <span className="h-6 w-px bg-border" />
          <X className="h-4 w-4 text-muted-foreground" />
        </div>
        <p className="mt-8 text-sm leading-6 text-muted-foreground">{selected.description}</p>
        <p className="mt-4 text-xs text-muted-foreground">Created Jan 12, 2026 <span className="px-2">/</span> Owner: You</p>

        <MetricGrid className="mt-10" />
        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Nearest clusters</h3>
        <div className="mt-5 space-y-5">
          {["Product Strategy", "Health & Longevity", "UX Patterns", "User Interviews", "Competitor Analysis"].map((name, index) => (
            <div key={name} className="flex items-center gap-3 text-sm">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: ["#c47f6f", "#789bb0", "#9486b4", "#d4998d", "#7ca2b9"][index] }} />
              <span className="flex-1">{name}</span>
              <span className="text-muted-foreground">{["0.72", "0.61", "0.57", "0.48", "0.44"][index]}</span>
            </div>
          ))}
        </div>

        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Related sources</h3>
        <div className="mt-5 space-y-5">
          {(selectedSources.length ? selectedSources : sources.slice(0, 3)).slice(0, 3).map((source, index) => (
            <SourceLine key={source.id} source={source} memories={[46, 24, 18][index] ?? 18} />
          ))}
        </div>
        <Link to="/sources" className="mt-6 flex items-center gap-2 text-sm text-primary">
          View all {selectedSources.length || 68} sources <ArrowRight className="h-4 w-4" />
        </Link>

        <Divider />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Actions</h3>
        <div className="mt-4 space-y-2">
          <ActionButton icon={<MoveRight className="h-4 w-4" />} label="Move to another cluster" />
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
      stroke="oklch(0.74 0.01 80)"
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
      className="absolute -translate-x-1/2 -translate-y-1/2 rounded-md border bg-card/95 px-4 py-3 text-left shadow-[0_8px_30px_oklch(0.32_0.02_70_/_0.035)] transition-transform hover:-translate-y-[calc(50%+2px)]"
      style={{
        left: `${node.x}%`,
        top: `${node.y}%`,
        width: node.w ?? 170,
        borderColor: selected ? `var(--cluster-${node.cluster.tint})` : "var(--border)",
        background: `color-mix(in oklab, var(--cluster-${node.cluster.tint}) 9%, var(--card))`,
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

function IconTile({ tint }: { tint: Cluster["tint"] }) {
  return (
    <span
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border"
      style={{
        borderColor: `color-mix(in oklab, var(--cluster-${tint}) 42%, var(--border))`,
        color: `var(--cluster-${tint})`,
        background: `color-mix(in oklab, var(--cluster-${tint}) 14%, var(--card))`,
      }}
    >
      <FileText className="h-4 w-4" />
    </span>
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

function ActionButton({ icon, label, danger }: { icon: ReactNode; label: string; danger?: boolean }) {
  return (
    <button
      type="button"
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

function nodeSourceCount(index: number) {
  return [68, 31, 27, 42, 23, 19, 16, 14, 18, 12, 20][index] ?? 12;
}
