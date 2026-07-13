import { type ComponentType, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Minus, Network, Plus, RotateCcw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ClusterStatusBadge } from "@/components/ClusterChip";
import { clusterLifecycleLabel, type Cluster, type Source } from "@/lib/domain";
import { forceCollide } from "d3-force-3d";

type Point = { x: number; y: number };

type ClusterEdge = {
  id: string;
  source: string;
  target: string;
  weight: number;
  sharedTerms: string[];
  relation: "shared-language" | "shared-medium";
};

type GraphNode = {
  id: string;
  cluster: Cluster;
  sourceCount: number;
  indexedCount: number;
  terms: string[];
  sourceTypes: string[];
  radius: number;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
};

type InspectorCluster = GraphNode & {
  neighbors: Array<{ cluster: Cluster; weight: number; sharedTerms: string[] }>;
  sources: Source[];
};

const tintHex: Record<Cluster["tint"], string> = {
  sage: "var(--cluster-sage)",
  sand: "var(--cluster-sand)",
  sky: "var(--cluster-sky)",
  blush: "var(--cluster-blush)",
  lavender: "var(--cluster-lavender)",
  terracotta: "var(--cluster-terracotta)",
};

const relationLabel: Record<ClusterEdge["relation"], string> = {
  "shared-language": "shared language",
  "shared-medium": "shared medium",
};

const resolvedColorCache = new Map<string, string>();

const commonWords = new Set([
  "about",
  "after",
  "against",
  "also",
  "around",
  "because",
  "before",
  "between",
  "cluster",
  "connected",
  "could",
  "design",
  "first",
  "from",
  "have",
  "here",
  "into",
  "just",
  "local",
  "memory",
  "notes",
  "over",
  "profile",
  "ready",
  "retrieval",
  "search",
  "short",
  "should",
  "source",
  "sources",
  "space",
  "summary",
  "their",
  "these",
  "this",
  "through",
  "used",
  "using",
  "vault",
  "with",
]);

export function ClusterMap({
  clusters,
  sources,
}: {
  clusters: Cluster[];
  sources: Source[];
}) {
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hasFitRef = useRef(false);
  const [size, setSize] = useState({ w: 980, h: 720 });
  const [zoom, setZoom] = useState(1);
  const [query, setQuery] = useState("");
  const [showOnlyMatches, setShowOnlyMatches] = useState(false);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(clusters[0]?.id ?? null);
  const [hoveredClusterId, setHoveredClusterId] = useState<string | null>(null);
  const [manualPositions, setManualPositions] = useState<Record<string, Point>>({});
  const [ForceGraph, setForceGraph] = useState<ComponentType<any> | null>(null);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let cancelled = false;
    void import("react-force-graph-2d").then((module) => {
      if (!cancelled) setForceGraph(() => module.default as ComponentType<any>);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedClusterId && clusters[0]) {
      setSelectedClusterId(clusters[0].id);
      return;
    }
    if (selectedClusterId && !clusters.some((cluster) => cluster.id === selectedClusterId)) {
      setSelectedClusterId(clusters[0]?.id ?? null);
    }
  }, [clusters, selectedClusterId]);

  const sourceGroups = useMemo(() => {
    const counts = new Map<string, number>();
    const byCluster = new Map<string, Source[]>();
    const loose: Source[] = [];
    for (const source of sources) {
      if (!source.clusterId) {
        loose.push(source);
        continue;
      }
      counts.set(source.clusterId, (counts.get(source.clusterId) ?? 0) + 1);
      const list = byCluster.get(source.clusterId);
      if (list) {
        list.push(source);
      } else {
        byCluster.set(source.clusterId, [source]);
      }
    }
    return { counts, byCluster, loose };
  }, [sources]);

  const termsByCluster = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const cluster of clusters) {
      result.set(cluster.id, buildClusterTerms(cluster, sourceGroups.byCluster.get(cluster.id) ?? []));
    }
    return result;
  }, [clusters, sourceGroups.byCluster]);

  const sourceTypesByCluster = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const cluster of clusters) {
      result.set(
        cluster.id,
        Array.from(new Set((sourceGroups.byCluster.get(cluster.id) ?? []).map((source) => source.type))),
      );
    }
    return result;
  }, [clusters, sourceGroups.byCluster]);

  const searchMatches = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    if (!needle) return new Set(clusters.map((cluster) => cluster.id));
    const next = new Set<string>();
    for (const cluster of clusters) {
      const haystack = [
        cluster.name,
        cluster.description,
        cluster.summary,
        cluster.styleProfile,
        ...(termsByCluster.get(cluster.id) ?? []),
      ]
        .join(" ")
        .toLowerCase();
      if (haystack.includes(needle)) next.add(cluster.id);
    }
    return next;
  }, [clusters, deferredQuery, termsByCluster]);

  const visibleClusters = useMemo(() => {
    if (!showOnlyMatches || deferredQuery.trim().length === 0) return clusters;
    return clusters.filter((cluster) => searchMatches.has(cluster.id));
  }, [clusters, deferredQuery, searchMatches, showOnlyMatches]);

  const visibleClusterIds = useMemo(
    () => new Set(visibleClusters.map((cluster) => cluster.id)),
    [visibleClusters],
  );

  const allEdges = useMemo(
    () => buildEdges(clusters, termsByCluster, sourceTypesByCluster),
    [clusters, sourceTypesByCluster, termsByCluster],
  );

  const edges = useMemo(
    () =>
      allEdges.filter(
        (edge) => visibleClusterIds.has(edge.source) && visibleClusterIds.has(edge.target),
      ),
    [allEdges, visibleClusterIds],
  );

  const graphNodes = useMemo(() => {
    const maxSourceCount = Math.max(
      1,
      ...visibleClusters.map((cluster) => sourceGroups.counts.get(cluster.id) ?? 0),
    );
    return visibleClusters.map((cluster, index) => {
      const sourceCount = sourceGroups.counts.get(cluster.id) ?? 0;
      const indexedCount = (sourceGroups.byCluster.get(cluster.id) ?? []).filter(
        (source) => source.state === "indexed",
      ).length;
      const sizeRatio = sourceCount / maxSourceCount;
      const radius = clamp(10 + 30 * sizeRatio, 10, 28);
      const seededPoint = seedPoint(cluster.id, index, size);
      const pinned = manualPositions[cluster.id];
      return {
        id: cluster.id,
        cluster,
        sourceCount,
        indexedCount,
        terms: termsByCluster.get(cluster.id) ?? [],
        sourceTypes: sourceTypesByCluster.get(cluster.id) ?? [],
        radius,
        x: pinned?.x ?? seededPoint.x,
        y: pinned?.y ?? seededPoint.y,
        fx: pinned?.x,
        fy: pinned?.y,
      } satisfies GraphNode;
    });
  }, [
    manualPositions,
    size,
    sourceGroups.byCluster,
    sourceGroups.counts,
    sourceTypesByCluster,
    termsByCluster,
    visibleClusters,
  ]);

  const nodesById = useMemo(
    () => new Map(graphNodes.map((node) => [node.id, node] as const)),
    [graphNodes],
  );

  const activeClusterId = hoveredClusterId ?? selectedClusterId;

  const connectedClusterIds = useMemo(() => {
    if (!activeClusterId) return new Set<string>();
    const next = new Set<string>([activeClusterId]);
    for (const edge of edges) {
      if (edge.source === activeClusterId) next.add(edge.target);
      if (edge.target === activeClusterId) next.add(edge.source);
    }
    return next;
  }, [activeClusterId, edges]);

  const graphData = useMemo(
    () => ({
      nodes: graphNodes.map((node) => ({ ...node })),
      links: edges.map((edge) => ({ ...edge })),
    }),
    [edges, graphNodes],
  );

  const selectedNode = selectedClusterId ? nodesById.get(selectedClusterId) ?? null : null;

  const inspector = useMemo<InspectorCluster | null>(() => {
    if (!selectedNode) return null;
    const neighbors = edges
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .map((edge) => {
        const peerId = edge.source === selectedNode.id ? edge.target : edge.source;
        const peer = nodesById.get(peerId);
        return peer
          ? { cluster: peer.cluster, weight: edge.weight, sharedTerms: edge.sharedTerms }
          : null;
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
      .sort((left, right) => right.weight - left.weight)
      .slice(0, 6);

    return {
      ...selectedNode,
      neighbors,
      sources: sourceGroups.byCluster.get(selectedNode.id) ?? [],
    };
  }, [edges, nodesById, selectedNode, sourceGroups.byCluster]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    const charge = graph.d3Force("charge");
    if (charge) charge.strength(-360);

    const center = graph.d3Force("center");
    if (center) {
      center.x(size.w / 2);
      center.y(size.h / 2);
    }

    const linkForce = graph.d3Force("link");
    if (linkForce) {
      linkForce.distance((link: ClusterEdge) => 170 - Math.min(46, link.weight * 18));
      linkForce.strength((link: ClusterEdge) => 0.08 + Math.min(0.18, link.weight * 0.08));
    }

    graph.d3Force(
      "collision",
      forceCollide((node: GraphNode) => node.radius + 28).strength(0.8),
    );

    graph.d3ReheatSimulation();
  }, [graphData, size]);

  useEffect(() => {
    if (!selectedNode || !graphRef.current || typeof selectedNode.x !== "number" || typeof selectedNode.y !== "number") {
      return;
    }
    graphRef.current.centerAt(selectedNode.x, selectedNode.y, 450);
  }, [selectedNode]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graphNodes.length === 0 || hasFitRef.current) return;
    const timer = window.setTimeout(() => {
      fitGraph(graph, graphNodes.length);
      setZoom(graphNodes.length <= 6 ? 1.32 : Math.min(1.04, graph.zoom?.() ?? 1.04));
      hasFitRef.current = true;
    }, 120);
    return () => window.clearTimeout(timer);
  }, [graphNodes.length]);

  const zoomPercent = Math.round(zoom * 100);

  if (clusters.length === 0) {
    return (
      <div className="grid h-full min-h-[640px] grid-cols-1 overflow-hidden rounded-md border border-border bg-card xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-h-[420px] items-center justify-center bg-[var(--bg-canvas)] px-6 py-10">
          <div className="max-w-md text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md border border-border bg-card">
              <Network className="h-5 w-5 text-muted-foreground" />
            </div>
            <h2 className="mt-5 text-xl font-semibold text-foreground">No graph yet</h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Create your first cluster and attach a few sources. The map starts showing structure
              once Vault has enough indexed content to find useful connections.
            </p>
          </div>
        </div>
        <aside className="border-t border-border bg-card/35 p-6 xl:border-l xl:border-t-0">
          <div className="text-sm font-medium text-foreground">Graph inspector</div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Cluster summaries, related spaces, and connected sources will appear here after the
            first cluster is created.
          </p>
        </aside>
      </div>
    );
  }

  return (
    <div className="grid h-full min-h-[640px] grid-cols-1 overflow-hidden rounded-md border border-border bg-card xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className="min-w-0 border-b border-border xl:border-b-0 xl:border-r">
        <div ref={containerRef} className="relative h-[720px] overflow-hidden bg-[var(--bg-canvas)]">
          <MapBackdrop />

          <div className="absolute left-4 top-4 z-20 flex w-[min(480px,calc(100%-2rem))] items-center gap-2">
            <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
              <Search className="h-4 w-4 shrink-0" />
              <input
                aria-label="Filter map clusters"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground"
                placeholder="Filter notes, clusters, or terms"
              />
            </label>
            <button
              type="button"
              onClick={() => setShowOnlyMatches((current) => !current)}
              className={`rounded-md border px-3 py-2 text-sm ${
                showOnlyMatches
                  ? "border-[var(--status-ready)]/35 bg-[var(--status-ready)]/10 text-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              {showOnlyMatches ? "Matches only" : "Dim non-matches"}
            </button>
          </div>

          <div className="absolute left-4 top-16 z-20 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
            {graphNodes.length} clusters / {edges.length} links / {sourceGroups.loose.length} loose
          </div>

          <div className="absolute bottom-4 left-4 z-20 max-w-52 rounded-md border border-border bg-card px-3 py-3 text-xs text-muted-foreground">
            <div className="font-medium text-foreground">Vault graph</div>
            <div className="mt-1 leading-5">
              Drag to pin. Hover reveals neighbors. Click centers the active cluster in the field.
            </div>
          </div>

          <div className="absolute bottom-4 right-4 z-20 flex items-center gap-2 rounded-md border border-border bg-card p-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => graphRef.current?.zoom(Math.max(0.55, zoom * 0.88), 300)}
              aria-label="Zoom out"
            >
              <Minus className="h-4 w-4" />
            </Button>
            <div className="min-w-12 text-center text-xs font-medium text-foreground">{zoomPercent}%</div>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => {
                if (graphRef.current) {
                  fitGraph(graphRef.current, graphNodes.length);
                  setZoom(graphNodes.length <= 6 ? 1.32 : Math.min(1.04, graphRef.current.zoom?.() ?? 1.04));
                }
              }}
              aria-label="Reset zoom"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => graphRef.current?.zoom(Math.min(2.4, zoom * 1.14), 300)}
              aria-label="Zoom in"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          <div className="absolute right-4 top-4 z-20 flex items-center gap-2 rounded-md border border-border bg-card p-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-3 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => {
                setManualPositions({});
                graphRef.current?.d3ReheatSimulation();
              }}
            >
              Relax layout
            </Button>
          </div>

          <div role="img" aria-label={`Knowledge map with ${graphNodes.length} clusters and ${edges.length} relationships. Use the cluster picker in the inspector for keyboard navigation.`}>
          {ForceGraph ? <ForceGraph
            ref={graphRef}
            width={size.w}
            height={size.h}
            graphData={graphData}
            backgroundColor="rgba(0,0,0,0)"
            cooldownTicks={320}
            d3AlphaDecay={0.032}
            d3VelocityDecay={0.38}
            enableNodeDrag
            minZoom={0.55}
            maxZoom={3.2}
            onZoomEnd={({ k }: { k: number }) => {
              window.setTimeout(() => setZoom(k), 0);
            }}
            onBackgroundClick={() => setHoveredClusterId(null)}
            onNodeHover={(node?: GraphNode | null) => setHoveredClusterId(node?.id ?? null)}
            onNodeClick={(node: GraphNode) => setSelectedClusterId(node.id)}
            onNodeDragEnd={(node: GraphNode) => {
              if (typeof node.x !== "number" || typeof node.y !== "number") return;
              node.fx = node.x;
              node.fy = node.y;
              setManualPositions((current) => ({ ...current, [node.id]: { x: node.x!, y: node.y! } }));
            }}
            linkColor={(link: ClusterEdge) => getLinkColor(link, connectedClusterIds)}
            linkWidth={(link: ClusterEdge) => getLinkWidth(link, connectedClusterIds)}
            linkLineDash={(link: ClusterEdge) =>
              (link as ClusterEdge).relation === "shared-medium" ? [5, 5] : null
            }
            nodePointerAreaPaint={(node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
              const graphNode = node as GraphNode;
              const x = graphNode.x ?? 0;
              const y = graphNode.y ?? 0;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(x, y, graphNode.radius + 10, 0, Math.PI * 2);
              ctx.fill();
            }}
            nodeCanvasObject={(node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
              drawNode({
                ctx,
                globalScale,
                node: node as GraphNode,
                hoveredClusterId,
                selectedClusterId,
                connectedClusterIds,
                queryActive: deferredQuery.trim().length > 0,
                searchMatches,
                sources: sourceGroups.byCluster.get((node as GraphNode).id) ?? [],
              });
            }}
          /> : <div className="h-full w-full animate-pulse bg-muted/30" aria-label="Loading map renderer" />}
          </div>
        </div>
      </section>

      <MapInspector
        inspector={inspector}
        looseSources={sourceGroups.loose}
        clusters={clusters}
        selectedClusterId={selectedClusterId}
        onSelectCluster={setSelectedClusterId}
      />
    </div>
  );
}

function MapBackdrop() {
  return (
    <div
      className="absolute inset-0"
      style={{
        backgroundImage:
          "radial-gradient(circle at 1px 1px, rgba(151,149,144,0.18) 1px, transparent 0), linear-gradient(90deg, rgba(232,231,227,0.9) 1px, transparent 0), linear-gradient(0deg, rgba(232,231,227,0.9) 1px, transparent 0)",
        backgroundSize: "22px 22px, 88px 88px, 88px 88px",
        backgroundColor: "var(--bg-canvas)",
      }}
    />
  );
}

function MapInspector({
  inspector,
  looseSources,
  clusters,
  selectedClusterId,
  onSelectCluster,
}: {
  inspector: InspectorCluster | null;
  looseSources: Source[];
  clusters: Cluster[];
  selectedClusterId: string | null;
  onSelectCluster: (clusterId: string) => void;
}) {
  if (!inspector) {
    return (
      <aside className="border-t border-border bg-[var(--bg-canvas)] px-4 py-6 sm:px-6 xl:border-l xl:border-t-0 xl:overflow-y-auto">
        <ClusterPicker clusters={clusters} selectedClusterId={selectedClusterId} onSelect={onSelectCluster} />
        <div className="text-sm font-medium text-foreground">Graph inspector</div>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          Pick a cluster to inspect its summary, shared language, and connected sources.
        </p>
        {looseSources.length > 0 && (
          <section className="mt-8 rounded-md border border-border bg-card p-4">
            <div className="text-xs font-medium text-muted-foreground">Loose files</div>
            <div className="mt-3 space-y-3">
              {looseSources.slice(0, 5).map((source) => (
                <div key={source.id} className="text-sm">
                  <div className="break-words text-foreground">{source.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {source.type} / {source.state}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </aside>
    );
  }

  const terms = inspector.terms.slice(0, 10);

  return (
    <aside className="border-t border-border bg-[var(--bg-canvas)] px-4 py-6 sm:px-6 xl:border-l xl:border-t-0 xl:overflow-y-auto">
      <ClusterPicker clusters={clusters} selectedClusterId={selectedClusterId} onSelect={onSelectCluster} />
      <div className="flex min-w-0 items-start gap-3">
        <span
          className="mt-1 h-3 w-3 shrink-0 rounded-full"
          style={{ background: tintHex[inspector.cluster.tint] }}
        />
        <div className="min-w-0 flex-1">
          <div className="break-words text-lg font-semibold text-foreground">
            {inspector.cluster.name}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {inspector.sourceCount} notes / {inspector.neighbors.length} related clusters
          </div>
        </div>
        <ClusterStatusBadge status={inspector.cluster.lifecycle} />
      </div>

      <p className="mt-5 break-words text-sm leading-7 text-[var(--text-body)]">
        {inspector.cluster.summary || inspector.cluster.description}
      </p>

      <section className="mt-8 rounded-md border border-border bg-card p-4">
        <div className="text-xs font-medium text-muted-foreground">Cluster state</div>
        <div className="mt-2 text-sm font-medium text-foreground">
          {clusterLifecycleLabel[inspector.cluster.lifecycle]}
        </div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {inspector.indexedCount} of {inspector.sources.length} sources are indexed. The map is
          purely structural: clusters, shared language, media overlap, and source density.
        </p>
      </section>

      <section className="mt-8">
        <div className="text-xs font-medium text-muted-foreground">Local terms</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {terms.length > 0 ? (
            terms.map((term) => (
              <span
                key={term}
                className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
              >
                {term}
              </span>
            ))
          ) : (
            <span className="text-sm text-muted-foreground">No cached terms yet.</span>
          )}
        </div>
      </section>

      <section className="mt-8">
        <div className="text-xs font-medium text-muted-foreground">Related clusters</div>
        <div className="mt-3 space-y-3">
          {inspector.neighbors.length > 0 ? (
            inspector.neighbors.map((neighbor) => (
              <button
                key={neighbor.cluster.id}
                type="button"
                className="w-full rounded-md border border-border bg-card p-3 text-left hover:bg-accent/35"
                onClick={() => onSelectCluster(neighbor.cluster.id)}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: tintHex[neighbor.cluster.tint] }}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="break-words text-sm font-medium text-foreground">
                      {neighbor.cluster.name}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {neighbor.weight.toFixed(2)} link strength /{" "}
                      {neighbor.sharedTerms.slice(0, 3).join(", ") || relationLabel["shared-medium"]}
                    </div>
                  </div>
                </div>
              </button>
            ))
          ) : (
            <div className="text-sm text-muted-foreground">No related clusters found yet.</div>
          )}
        </div>
      </section>

      <section className="mt-8">
        <div className="text-xs font-medium text-muted-foreground">Connected sources</div>
        <div className="mt-3 space-y-3">
          {inspector.sources.slice(0, 8).map((source) => (
            <div key={source.id} className="rounded-md border border-border bg-card p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-words text-sm font-medium text-foreground">{source.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {source.type} / {source.state}
                  </div>
                </div>
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: getSourceStateColor(source.state) }} />
              </div>
              <p className="mt-2 line-clamp-3 break-words text-xs leading-5 text-muted-foreground">
                {source.summary || source.preview || "Preview will appear after extraction."}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-8 rounded-md border border-border bg-card p-4">
        <div className="text-xs font-medium text-muted-foreground">Graph stats</div>
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Indexed</div>
            <div className="mt-1 font-medium text-foreground">{inspector.indexedCount}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Terms</div>
            <div className="mt-1 font-medium text-foreground">{inspector.terms.length}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Source types</div>
            <div className="mt-1 font-medium text-foreground">{inspector.sourceTypes.length}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Neighbors</div>
            <div className="mt-1 font-medium text-foreground">{inspector.neighbors.length}</div>
          </div>
        </div>
      </section>
    </aside>
  );
}

function ClusterPicker({
  clusters,
  selectedClusterId,
  onSelect,
}: {
  clusters: Cluster[];
  selectedClusterId: string | null;
  onSelect: (clusterId: string) => void;
}) {
  return (
    <label className="mb-5 block text-xs font-medium text-muted-foreground">
      Inspect cluster
      <select
        className="mt-2 h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
        value={selectedClusterId ?? ""}
        onChange={(event) => onSelect(event.target.value)}
      >
        {clusters.map((cluster) => (
          <option key={cluster.id} value={cluster.id}>{cluster.name}</option>
        ))}
      </select>
    </label>
  );
}

function drawNode({
  ctx,
  globalScale,
  node,
  hoveredClusterId,
  selectedClusterId,
  connectedClusterIds,
  queryActive,
  searchMatches,
  sources,
}: {
  ctx: CanvasRenderingContext2D;
  globalScale: number;
  node: GraphNode;
  hoveredClusterId: string | null;
  selectedClusterId: string | null;
  connectedClusterIds: Set<string>;
  queryActive: boolean;
  searchMatches: Set<string>;
  sources: Source[];
}) {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const hovered = node.id === hoveredClusterId;
  const selected = node.id === selectedClusterId;
  const matched = searchMatches.has(node.id);
  const active = connectedClusterIds.size === 0 || connectedClusterIds.has(node.id);
  const dimmed = (queryActive && !matched) || (connectedClusterIds.size > 0 && !active);
  const labelSize = Math.max(9, 11 / globalScale);
  const baseOpacity = dimmed ? 0.16 : selected ? 0.96 : hovered ? 0.82 : 0.68;

  if (selected || hovered) {
    const previewSources = sources.slice(0, selected ? 10 : 6);
    for (const anchor of buildSourceAnchors({ x, y }, node.radius, previewSources)) {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(155,154,150,0.28)";
      ctx.lineWidth = 1 / globalScale;
      ctx.moveTo(x, y);
      ctx.lineTo(anchor.x, anchor.y);
      ctx.stroke();

      ctx.beginPath();
      ctx.fillStyle = "rgba(255,255,255,0.98)";
      ctx.arc(anchor.x, anchor.y, 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(138,135,129,0.42)";
      ctx.stroke();
    }
  }

  if (selected) {
    ctx.beginPath();
    ctx.fillStyle = "rgba(255,255,255,0.88)";
    ctx.arc(x, y, node.radius + 6, 0, Math.PI * 2);
    ctx.fill();
  } else if (hovered) {
    ctx.beginPath();
    ctx.fillStyle = "rgba(255,255,255,0.62)";
    ctx.arc(x, y, node.radius + 3, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.beginPath();
  ctx.globalAlpha = baseOpacity;
  ctx.fillStyle = resolveCanvasColor(tintHex[node.cluster.tint]);
  ctx.arc(x, y, node.radius, 0, Math.PI * 2);
  ctx.fill();

  ctx.beginPath();
  ctx.strokeStyle = selected ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.4)";
  ctx.lineWidth = selected ? 2 / globalScale : 1 / globalScale;
  ctx.arc(x, y, Math.max(5, node.radius - 4), 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;

  const font = `${selected || hovered ? 600 : 500} ${labelSize}px ui-sans-serif, system-ui, sans-serif`;
  ctx.font = font;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  const label = node.cluster.name;
  const labelY = y + node.radius + 10;
  const textWidth = ctx.measureText(label).width;
  const boxWidth = textWidth + 10;
  const boxHeight = labelSize + 6;

  if (selected || hovered) {
    ctx.fillStyle = "rgba(255,255,255,0.94)";
    roundRect(ctx, x - boxWidth / 2, labelY - 3, boxWidth, boxHeight, 6 / globalScale);
    ctx.fill();
    ctx.fillStyle = "rgba(54,52,48,0.96)";
  } else {
    ctx.fillStyle = dimmed ? "rgba(98,95,90,0.18)" : "rgba(98,95,90,0.56)";
  }

  ctx.fillText(label, x, labelY);
}

function buildClusterTerms(cluster: Cluster, sources: Source[]) {
  const counts = new Map<string, number>();
  const payload = [
    cluster.name,
    cluster.description,
    cluster.summary,
    ...sources.map((source) => source.title),
    ...sources.map((source) => source.summary),
  ]
    .join(" ")
    .toLowerCase();

  for (const token of payload.match(/[a-z0-9]{3,}/g) ?? []) {
    if (commonWords.has(token)) continue;
    counts.set(token, (counts.get(token) ?? 0) + 1);
  }

  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 12)
    .map(([term]) => term);
}

function buildEdges(
  clusters: Cluster[],
  termsByCluster: Map<string, string[]>,
  sourceTypesByCluster: Map<string, string[]>,
) {
  const edges: ClusterEdge[] = [];
  for (let index = 0; index < clusters.length; index += 1) {
    for (let cursor = index + 1; cursor < clusters.length; cursor += 1) {
      const left = clusters[index];
      const right = clusters[cursor];
      if (!left || !right) continue;
      const leftTerms = termsByCluster.get(left.id) ?? [];
      const rightTerms = termsByCluster.get(right.id) ?? [];
      const sharedTerms = leftTerms.filter((term) => rightTerms.includes(term));
      const leftTypes = sourceTypesByCluster.get(left.id) ?? [];
      const rightTypes = sourceTypesByCluster.get(right.id) ?? [];
      const sharedTypes = leftTypes.filter((type) => rightTypes.includes(type));
      const sharedTermWeight = sharedTerms.length * 0.34;
      const sharedTypeWeight = sharedTypes.length * 0.11;
      const weight = Number((sharedTermWeight + sharedTypeWeight).toFixed(2));
      if (weight < 0.35) continue;
      edges.push({
        id: `${left.id}:${right.id}`,
        source: left.id,
        target: right.id,
        weight,
        sharedTerms,
        relation: sharedTerms.length > 0 ? "shared-language" : "shared-medium",
      });
    }
  }
  return edges;
}

function buildSourceAnchors(center: Point, clusterRadius: number, sources: Source[]) {
  const orbit = clusterRadius + 22;
  return sources.map((source, index) => {
    const seed = hashString(source.id);
    const angle = -Math.PI / 2 + ((seed % 360) / 360) * Math.PI * 2 + index * 0.32;
    const variance = ((seed % 11) - 5) * 1.4;
    return {
      x: center.x + Math.cos(angle) * (orbit + variance),
      y: center.y + Math.sin(angle) * (orbit * 0.74 + variance),
    };
  });
}

function seedPoint(id: string, index: number, size: { w: number; h: number }) {
  const angle = ((hashString(id) % 360) / 360) * Math.PI * 2 + index * 0.6;
  const orbit = Math.min(size.w, size.h) * (0.22 + ((hashString(id) % 10) / 28));
  return {
    x: size.w / 2 + Math.cos(angle) * orbit,
    y: size.h / 2 + Math.sin(angle) * orbit * 0.78,
  };
}

function getLinkColor(link: ClusterEdge, connectedClusterIds: Set<string>) {
  const active =
    connectedClusterIds.size === 0 ||
    connectedClusterIds.has(link.source) ||
    connectedClusterIds.has(link.target);
  if (!active) return "rgba(155,154,150,0.1)";
  return link.relation === "shared-language"
    ? "rgba(120,106,86,0.28)"
    : "rgba(155,154,150,0.24)";
}

function getLinkWidth(link: ClusterEdge, connectedClusterIds: Set<string>) {
  const active =
    connectedClusterIds.size === 0 ||
    connectedClusterIds.has(link.source) ||
    connectedClusterIds.has(link.target);
  return active ? 0.8 + link.weight * 0.54 : 0.45;
}

function getSourceStateColor(state: Source["state"]) {
  if (state === "indexed") return "var(--status-ready)";
  if (state === "processing") return "var(--status-learning)";
  if (state === "failed") return "var(--status-issue)";
  return "var(--status-paused)";
}

function fitGraph(graph: any, nodeCount: number) {
  if (nodeCount <= 6) {
    graph.zoomToFit(500, 180);
    graph.zoom(1.32, 0);
    return;
  }

  graph.zoomToFit(500, 110);
  const fittedZoom = typeof graph.zoom === "function" ? graph.zoom() : null;
  if (typeof fittedZoom === "number" && fittedZoom > 1.04) {
    graph.zoom(1.04, 0);
  }
}

function resolveCanvasColor(color: string) {
  if (!color.startsWith("var(") || typeof window === "undefined") return color;
  const cached = resolvedColorCache.get(color);
  if (cached) return cached;
  const variableName = color.slice(4, -1).trim();
  const resolved =
    getComputedStyle(document.documentElement).getPropertyValue(variableName).trim() || color;
  resolvedColorCache.set(color, resolved);
  return resolved;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function hashString(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}
