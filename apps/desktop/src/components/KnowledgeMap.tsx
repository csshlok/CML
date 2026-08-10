import { type ComponentType, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowLeft, ExternalLink, List, Maximize2, Network, RotateCcw, Search, X, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getMapItem,
  getMapNeighborhood,
  type MapConnectionMode,
  type MapEdgeRecord,
  type MapGraphResponse,
  type MapItemRecord,
  type MapNodeRecord,
} from "@/lib/backend";
import { DegradedState, EmptyState, SkeletonRegion, StatusLabel } from "@/components/product/Feedback";

const clusterColors: Record<string, string> = {
  sage: "#5B8A5B",
  terracotta: "#C0704A",
  sky: "#4A78A8",
  sand: "#9A762F",
  lavender: "#7A6BAF",
  blush: "#A94F64",
};

export function KnowledgeMap({
  vaultId,
  overview,
  onReload,
  onExpandOverview,
  initialFocusId,
  persistView = false,
  connectionMode = "current",
  connectionModeBusy = false,
  onConnectionModeChange,
}: {
  vaultId: string;
  overview: MapGraphResponse;
  onReload: () => void;
  onExpandOverview?: () => void;
  initialFocusId?: string | null;
  persistView?: boolean;
  connectionMode?: MapConnectionMode;
  connectionModeBusy?: boolean;
  onConnectionModeChange?: (mode: MapConnectionMode) => void;
}) {
  const restoredViewRef = useRef(readMapViewFromUrl(persistView));
  const graphRef = useRef<any>(null);
  const inspectRequestRef = useRef(0);
  const focusRequestRef = useRef(0);
  const initialFocusAppliedRef = useRef<string | null>(null);
  const [containerElement, setContainerElement] = useState<HTMLDivElement | null>(null);
  const containerRef = useCallback((element: HTMLDivElement | null) => {
    setContainerElement(element);
  }, []);
  const [ForceGraph, setForceGraph] = useState<ComponentType<any> | null>(null);
  const [graph, setGraph] = useState(overview);
  const [selected, setSelected] = useState<MapItemRecord | null>(null);
  const [root, setRoot] = useState<MapNodeRecord | null>(null);
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | MapNodeRecord["kind"]>("all");
  const [listMode, setListMode] = useState(false);
  const [loadingFocus, setLoadingFocus] = useState(false);
  const [neighborhoodLimit, setNeighborhoodLimit] = useState(80);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState({ width: 900, height: 620 });
  const [viewRevision, setViewRevision] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(restoredViewRef.current?.zoom ?? 1);
  const [viewRestored, setViewRestored] = useState(!persistView);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());

  useEffect(() => {
    if (listMode) {
      setForceGraph(null);
      return;
    }
    let cancelled = false;
    void import("react-force-graph-2d").then((module) => {
      if (!cancelled) setForceGraph(() => module.default as ComponentType<any>);
    });
    return () => {
      cancelled = true;
    };
  }, [listMode]);

  useEffect(
    () => () => {
      const instance = graphRef.current;
      instance?.pauseAnimation?.();
      instance?._destructor?.();
      graphRef.current = null;
    },
    [],
  );

  useEffect(() => {
    setGraph(overview);
    setRoot(null);
    setSelected(null);
    setError(null);
    setViewRevision((current) => current + 1);
  }, [overview]);

  useEffect(() => {
    if (!containerElement) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setSize({
        width: Math.max(320, Math.floor(entry.contentRect.width)),
        height: Math.max(420, Math.floor(entry.contentRect.height)),
      });
    });
    observer.observe(containerElement);
    return () => observer.disconnect();
  }, [containerElement]);

  const visibleNodes = useMemo(() => {
    return graph.nodes.filter((node) => {
      if (kindFilter !== "all" && node.kind !== kindFilter) return false;
      if (!deferredQuery) return true;
      return `${node.label} ${node.summary} ${node.kind}`.toLowerCase().includes(deferredQuery);
    });
  }, [deferredQuery, graph.nodes, kindFilter]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)),
    [graph.edges, visibleIds],
  );
  const graphData = useMemo(
    () => {
      const degrees = new Map<string, number>();
      for (const edge of visibleEdges) {
        degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
        degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
      }
      const priorityLabels = new Set(
        [...visibleNodes]
          .sort((left, right) => (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0))
          .slice(0, 6)
          .map((node) => node.id),
      );
      for (const node of visibleNodes) {
        if (node.kind === "collection" || (degrees.get(node.id) ?? 0) === 0) {
          priorityLabels.add(node.id);
        }
      }
      return {
        nodes: visibleNodes.map((node) => ({
          ...node,
          showLabel: priorityLabels.has(node.id),
          denseGraph: visibleNodes.length > 40,
        })),
        links: visibleEdges.map((edge) => ({ ...edge })),
      };
    },
    [visibleEdges, visibleNodes],
  );
  const unclusteredNode = useMemo(
    () => overview.nodes.find((node) => node.kind === "collection") ?? null,
    [overview.nodes],
  );
  const configureGraph = useCallback(() => {
    const instance = graphRef.current;
    if (!instance) return;
    instance.d3Force?.("charge")?.strength?.(-45);
    instance.d3Force?.("link")?.distance?.((edge: MapEdgeRecord) =>
      edge.kind === "similarity" ? 86 : edge.kind === "related" ? 68 : 52
    );
    instance.d3ReheatSimulation?.();
  }, []);
  const fitGraph = useCallback((duration = 320) => {
    const instance = graphRef.current;
    if (!instance) return;
    const nodes = (instance.graphData?.().nodes ?? []).filter(
      (node: { x?: number; y?: number }) =>
        Number.isFinite(node.x) && Number.isFinite(node.y),
    ) as Array<{ x: number; y: number }>;
    if (nodes.length === 0) return;
    const xs = nodes.map((node) => node.x);
    const ys = nodes.map((node) => node.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const graphWidth = Math.max(48, maxX - minX);
    const graphHeight = Math.max(48, maxY - minY);
    const availableWidth = Math.max(160, size.width - 144);
    const availableHeight = Math.max(160, size.height - 144);
    const zoom = Math.max(
      0.12,
      Math.min(4, Math.min(availableWidth / graphWidth, availableHeight / graphHeight)),
    );
    instance.centerAt?.(centerX, centerY, duration);
    instance.zoom?.(zoom, duration);
    setZoomLevel(zoom);
  }, [size.height, size.width]);

  const changeZoom = useCallback((factor: number) => {
    const instance = graphRef.current;
    if (!instance) return;
    const next = Math.max(0.12, Math.min(4, zoomLevel * factor));
    instance.zoom?.(next, 180);
    setZoomLevel(next);
  }, [zoomLevel]);

  useEffect(() => {
    if (listMode || !ForceGraph) return;
    const first = window.setTimeout(() => {
      configureGraph();
      fitGraph(0);
    }, 80);
    const settled = window.setTimeout(() => fitGraph(280), 520);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(settled);
    };
  }, [ForceGraph, configureGraph, fitGraph, graphData, listMode, size.height, size.width, viewRevision]);

  async function inspect(node: MapNodeRecord) {
    const requestId = ++inspectRequestRef.current;
    setError(null);
    try {
      const item = await getMapItem(vaultId, node.id);
      if (requestId === inspectRequestRef.current) setSelected(item);
    } catch (reason) {
      if (requestId === inspectRequestRef.current) {
        setError(reason instanceof Error ? reason.message : "Vault could not inspect this item.");
      }
    }
  }

  async function focus(node: MapNodeRecord, limit = 80) {
    if (node.kind === "fact") {
      await inspect(node);
      return;
    }
    const requestId = ++focusRequestRef.current;
    ++inspectRequestRef.current;
    setLoadingFocus(true);
    setError(null);
    try {
      const [nextResult, itemResult] = await Promise.allSettled([
        getMapNeighborhood(vaultId, node.id, limit),
        getMapItem(vaultId, node.id),
      ]);
      if (requestId !== focusRequestRef.current) return;
      if (nextResult.status === "rejected") throw nextResult.reason;
      setGraph(nextResult.value);
      setRoot(node);
      setNeighborhoodLimit(limit);
      if (itemResult.status === "fulfilled") setSelected(itemResult.value);
      setViewRevision((current) => current + 1);
      if (itemResult.status === "rejected") {
        setError("The map expanded, but details for this item are unavailable.");
      }
    } catch (reason) {
      if (requestId === focusRequestRef.current) {
        setError(reason instanceof Error ? reason.message : "Vault could not expand this neighborhood.");
      }
    } finally {
      if (requestId === focusRequestRef.current) setLoadingFocus(false);
    }
  }

  useEffect(() => {
    if (!initialFocusId || initialFocusAppliedRef.current === initialFocusId) return;
    const node = overview.nodes.find((candidate) => candidate.id === initialFocusId);
    if (!node) return;
    initialFocusAppliedRef.current = initialFocusId;
    void focus(node);
  }, [initialFocusId, overview.nodes]);

  useEffect(() => {
    if (!persistView || viewRestored || initialFocusId) return;
    const restored = restoredViewRef.current;
    const rootNode = restored?.rootId
      ? overview.nodes.find((candidate) => candidate.id === restored.rootId)
      : null;
    const selectedNode = restored?.selectedId
      ? overview.nodes.find((candidate) => candidate.id === restored.selectedId)
      : null;
    async function restore() {
      if (rootNode) await focus(rootNode);
      else if (selectedNode) await inspect(selectedNode);
      setViewRestored(true);
    }
    void restore();
  }, [initialFocusId, overview.nodes, persistView, viewRestored]);

  useEffect(() => {
    if (!persistView || !viewRestored) return;
    const url = new URL(window.location.href);
    setOrDelete(url.searchParams, "mapRoot", root?.id);
    setOrDelete(url.searchParams, "mapSelected", selected?.id);
    url.searchParams.set("mapZoom", zoomLevel.toFixed(3));
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, [persistView, root?.id, selected?.id, viewRestored, zoomLevel]);

  useEffect(() => {
    if (!persistView || !viewRestored || !ForceGraph || !graphRef.current) return;
    const timer = window.setTimeout(() => graphRef.current?.zoom?.(zoomLevel, 0), 650);
    return () => window.clearTimeout(timer);
  }, [ForceGraph, persistView, viewRestored, viewRevision, zoomLevel]);

  function resetOverview() {
    ++focusRequestRef.current;
    ++inspectRequestRef.current;
    setGraph({
      ...overview,
      nodes: overview.nodes.map((node) => ({ ...node })),
      edges: overview.edges.map((edge) => ({ ...edge })),
    });
    setRoot(null);
    setSelected(null);
    setQuery("");
    setKindFilter("all");
    setError(null);
    setNeighborhoodLimit(80);
    setViewRevision((current) => current + 1);
  }

  return (
    <div className={`grid min-h-[620px] overflow-hidden rounded-md border border-border bg-card ${selected ? "xl:grid-cols-[minmax(0,1fr)_320px]" : ""}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-3">
          {root ? (
            <Button variant="ghost" size="sm" onClick={resetOverview}>
              <ArrowLeft className="h-4 w-4" /> Overview
            </Button>
          ) : null}
          <div className="relative min-w-[180px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 pl-8"
              placeholder="Find a cluster or source"
              aria-label="Filter map"
            />
          </div>
          <select
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value as typeof kindFilter)}
            className="h-9 rounded-md border border-input bg-card px-2.5 text-xs"
            aria-label="Filter map item type"
          >
            <option value="all">All item types</option>
            <option value="cluster">Clusters</option>
            <option value="source">Sources</option>
            <option value="fact">Facts</option>
            <option value="collection">Collections</option>
          </select>
          <Button variant="outline" size="sm" onClick={() => setListMode((current) => !current)}>
            {listMode ? <Network className="h-4 w-4" /> : <List className="h-4 w-4" />}
            {listMode ? "Graph" : "List"}
          </Button>
          {onConnectionModeChange ? (
            <div
              className="flex h-9 items-center rounded-md border border-input bg-card"
              role="group"
              aria-label="Cluster connection mode"
              aria-busy={connectionModeBusy}
            >
              <button
                type="button"
                disabled={connectionModeBusy}
                aria-pressed={connectionMode === "current"}
                className={`h-full rounded-l-md px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50 ${
                  connectionMode === "current"
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                title="Show only saved and evidence-backed relationships"
                onClick={() => onConnectionModeChange("current")}
              >
                Current
              </button>
              <button
                type="button"
                disabled={connectionModeBusy}
                aria-pressed={connectionMode === "similar"}
                className={`h-full rounded-r-md border-l border-input px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50 ${
                  connectionMode === "similar"
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                title="Also show strong semantic similarity between clusters"
                onClick={() => onConnectionModeChange("similar")}
              >
                Connections
              </button>
            </div>
          ) : null}
          {!listMode ? (
            <div className="flex h-9 items-center rounded-md border border-input bg-card" aria-label="Map zoom controls">
              <button
                type="button"
                className="flex h-full w-9 items-center justify-center rounded-l-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                onClick={() => changeZoom(0.8)}
                aria-label="Zoom out"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <span className="w-12 text-center text-[11px] tabular-nums text-muted-foreground">
                {Math.round(zoomLevel * 100)}%
              </span>
              <button
                type="button"
                className="flex h-full w-9 items-center justify-center rounded-r-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                onClick={() => changeZoom(1.25)}
                aria-label="Zoom in"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
          <Button variant="outline" size="sm" onClick={resetOverview}>
            <RotateCcw className="h-4 w-4" />
            Reset view
          </Button>
          {graph.truncated && (root || onExpandOverview) ? (
            <Button
              variant="outline"
              size="sm"
              disabled={loadingFocus || (Boolean(root) && neighborhoodLimit >= 200)}
              onClick={() => {
                if (root) void focus(root, Math.min(200, neighborhoodLimit + 60));
                else onExpandOverview?.();
              }}
            >
              <Maximize2 className="h-4 w-4" />
              Show more
            </Button>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border bg-[var(--bg-canvas)] px-4 py-2.5 text-xs text-muted-foreground">
          <MapLegend color={clusterColors.sage} label="Cluster" />
          <MapLegend color="#7C6E5A" label="Source" />
          <MapLegend color="#9B9A96" label="Unclustered collection" />
          <MapLineLegend label="Verified" />
          {connectionMode === "similar" && !root ? (
            <MapLineLegend dashed label="Similar" />
          ) : null}
          <span className="min-w-[220px] flex-1">
            {root
              ? "This view shows what the selected item contains."
              : connectionMode === "similar"
                ? visibleEdges.length > 0
                  ? `${visibleEdges.length} strong local connection${visibleEdges.length === 1 ? "" : "s"}. Hover any dashed line for details.`
                  : "No strong local connections meet the current evidence threshold yet."
                : "Solid lines show shared facts or explicit project membership."}
          </span>
          {graph.truncated ? (
            <span className="font-medium text-[var(--status-warn-ink)]">
              Showing {Math.max(0, graph.nodes.length - 1).toLocaleString()} of{" "}
              {root?.source_count?.toLocaleString() ?? "the available"} related items
            </span>
          ) : null}
          {unclusteredNode ? (
            <button
              type="button"
              className="min-h-9 rounded-md px-2.5 text-left font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => void focus(unclusteredNode)}
            >
              {unclusteredNode.source_count?.toLocaleString()} unclustered sources
            </button>
          ) : null}
        </div>
        {error ? <div className="p-3"><DegradedState compact description={error} onRetry={root ? () => void focus(root) : onReload} /></div> : null}
        {loadingFocus ? <SkeletonRegion className="p-6" lines={6} /> : listMode ? (
          <MapList nodes={visibleNodes} edges={visibleEdges} selectedId={selected?.id} onInspect={inspect} onFocus={focus} />
        ) : (
          <div ref={containerRef} className="h-[620px] min-w-0" aria-label="Knowledge relationship graph">
            {ForceGraph ? (
              <ForceGraph
                key={viewRevision}
                ref={graphRef}
                width={size.width}
                height={size.height}
                graphData={graphData}
                backgroundColor="#FFFFFF"
                nodeLabel={(node: MapNodeRecord) => `${kindLabel(node.kind)}: ${node.label}`}
                nodeColor={(node: MapNodeRecord) => nodeColor(node)}
                nodeVal={(node: MapNodeRecord) => node.kind === "cluster" || node.kind === "collection" ? Math.max(5, Math.min(16, 5 + (node.source_count ?? 0) / 4)) : 4}
                nodeCanvasObjectMode={() => "replace"}
                nodeCanvasObject={(node: CanvasMapNode, context: CanvasRenderingContext2D, globalScale: number) =>
                  drawMapNode(node, context, globalScale)
                }
                linkColor={(edge: MapEdgeRecord) => edge.kind === "similarity" ? "#8C857A" : "#77736C"}
                linkWidth={(edge: MapEdgeRecord) => edge.kind === "similarity" ? 1.15 : 1.5}
                linkLineDash={(edge: MapEdgeRecord) => edge.kind === "similarity" ? [4, 3] : null}
                linkDirectionalArrowLength={(edge: MapEdgeRecord) => edge.direction === "undirected" ? 0 : 4}
                linkDirectionalArrowRelPos={0.86}
                linkLabel={(edge: MapEdgeRecord) => mapEdgeTooltip(edge)}
                linkCanvasObjectMode={() => "after"}
                linkCanvasObject={(edge: CanvasMapEdge, context: CanvasRenderingContext2D, globalScale: number) =>
                  drawMapLinkLabel(edge, context, globalScale, graphData.nodes.length)
                }
                onNodeClick={(node: MapNodeRecord) => void focus(node)}
                onNodeRightClick={(node: MapNodeRecord) => void inspect(node)}
                onZoom={({ k }: { k: number }) => setZoomLevel(k)}
                cooldownTicks={90}
                onEngineStop={() => fitGraph(280)}
              />
            ) : <SkeletonRegion className="p-6" lines={8} />}
          </div>
        )}
      </div>
      {selected ? (
        <MapInspector
          selected={selected}
          onFocus={focus}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

function MapList({
  nodes,
  edges,
  selectedId,
  onInspect,
  onFocus,
}: {
  nodes: MapNodeRecord[];
  edges: MapEdgeRecord[];
  selectedId?: string;
  onInspect: (node: MapNodeRecord) => void;
  onFocus: (node: MapNodeRecord) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: nodes.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 60,
    getItemKey: (index) => nodes[index]?.id ?? index,
    overscan: 8,
    useFlushSync: false,
  });
  if (nodes.length === 0) {
    return <EmptyState title="No matching map items" description="Clear the filter to see this map again." />;
  }
  return (
    <div
      ref={scrollRef}
      className="overflow-y-auto"
      style={{ height: `${Math.min(nodes.length * 60, 620)}px` }}
      role="list"
    >
      <div className="relative" style={{ height: `${rowVirtualizer.getTotalSize()}px` }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const node = nodes[virtualRow.index];
          if (!node) return null;
          return (
            <div
              key={node.id}
              ref={rowVirtualizer.measureElement}
              data-index={virtualRow.index}
              role="listitem"
              className={`absolute left-0 top-0 flex w-full items-center gap-3 border-b border-border px-4 py-3 ${selectedId === node.id ? "bg-accent" : ""}`}
              style={{ transform: `translateY(${virtualRow.start}px)` }}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: nodeColor(node) }}
                aria-hidden="true"
              />
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => void onInspect(node)}
              >
                <span className="block truncate text-sm font-medium">{node.label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {kindLabel(node.kind)} · {relationshipSummary(node.id, edges)}
                </span>
              </button>
              {node.kind !== "fact" ? (
                <Button variant="ghost" size="sm" onClick={() => void onFocus(node)}>
                  Expand
                </Button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MapInspector({
  selected,
  onFocus,
  onClose,
}: {
  selected: MapItemRecord;
  onFocus: (node: MapNodeRecord) => void;
  onClose: () => void;
}) {
  return (
    <aside className="border-t border-border bg-[var(--bg-canvas)] p-5 xl:border-l xl:border-t-0" aria-label="Map details">
      <div>
          <div className="flex items-start justify-between gap-3">
          <StatusLabel tone={selected.kind === "fact" ? "info" : selected.kind === "collection" ? "neutral" : selected.state === "failed" ? "error" : "ready"}>
            {kindLabel(selected.kind)}
          </StatusLabel>
            <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close map details">
              <X className="h-4 w-4" />
            </Button>
          </div>
          <h2 className="mt-4 break-words text-base font-semibold">{selected.label}</h2>
          {selected.summary ? <p className="mt-3 text-sm leading-6 text-muted-foreground">{selected.summary}</p> : null}
          <dl className="mt-6 space-y-3 text-sm">
            {selected.state ? <InspectorRow label="State" value={formatState(selected.state)} /> : null}
            {selected.source_count !== undefined ? <InspectorRow label="Sources" value={String(selected.source_count)} /> : null}
            {selected.fact_count !== undefined ? <InspectorRow label="Current facts" value={String(selected.fact_count)} /> : null}
            {selected.valid_from ? <InspectorRow label="Valid from" value={formatDate(selected.valid_from)} /> : null}
            {selected.valid_until ? <InspectorRow label="Valid until" value={formatDate(selected.valid_until)} /> : null}
            <InspectorRow label="Updated" value={formatDate(selected.updated_at)} />
          </dl>
          {selected.citation_excerpt ? (
            <blockquote className="mt-6 rounded-md bg-[var(--bg-secondary)] p-3 text-sm leading-6 text-[var(--text-body)]">
              “{selected.citation_excerpt}”
            </blockquote>
          ) : null}
          <div className="mt-7 border-t border-border pt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Provenance</h3>
            {selected.provenance.length ? (
              <div className="mt-3 space-y-2">
                {selected.provenance.map((item, index) => (
                  <div key={String(item.id ?? index)} className="rounded-md border border-border bg-card p-3 text-sm">
                    <div className="break-words font-medium">{String(item.title ?? item.id ?? "Local source")}</div>
                    {item.source_type ? <div className="mt-1 text-xs text-muted-foreground">{String(item.source_type)}</div> : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                {selected.kind === "collection"
                  ? "Select a source node to inspect its individual lineage."
                  : "No source lineage is available for this overview item."}
              </p>
            )}
          </div>
          {selected.kind !== "fact" ? (
            <Button className="mt-6 w-full" variant="outline" onClick={() => void onFocus(selected)}>
              <ExternalLink className="h-4 w-4" /> Expand one hop
            </Button>
          ) : null}
          {selected.kind === "cluster" ? (
            <Button className="mt-2 w-full" asChild>
              <Link to="/clusters/$clusterId" params={{ clusterId: selected.id }}>
                Open cluster
              </Link>
            </Button>
          ) : null}
        </div>
    </aside>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-4"><dt className="text-muted-foreground">{label}</dt><dd className="break-words text-right font-medium">{value}</dd></div>;
}

function nodeColor(node: MapNodeRecord) {
  if (node.kind === "cluster") return clusterColors[node.color ?? "sage"] ?? clusterColors.sage;
  if (node.kind === "collection") return "#9B9A96";
  if (node.kind === "fact") return "#4A78A8";
  return "#7C6E5A";
}

function kindLabel(kind: MapNodeRecord["kind"]) {
  if (kind === "cluster") return "Cluster";
  if (kind === "collection") return "Collection";
  if (kind === "source") return "Source episode";
  return "Fact";
}

function MapLegend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
      {label}
    </span>
  );
}

function MapLineLegend({ label, dashed = false }: { label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={`w-5 border-t-2 ${dashed ? "border-dashed border-[#8C857A]" : "border-[#77736C]"}`}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function mapEdgeTooltip(edge: MapEdgeRecord) {
  if (edge.kind === "similarity") {
    const topics = edge.shared_terms?.length
      ? ` Shared topics: ${edge.shared_terms.join(", ")}.`
      : "";
    return `${Math.round((edge.similarity_score ?? 0) * 100)}% similar.${topics}`;
  }
  const evidence = edge.provenance_ids.length;
  return `${edge.evidence_labels?.join(" · ") || edge.label}; ${evidence} evidence item${evidence === 1 ? "" : "s"}`;
}

function relationshipSummary(nodeId: string, edges: MapEdgeRecord[]) {
  const connected = edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
  if (connected.length === 0) return "No visible relationships";
  const first = connected[0]?.label;
  return `${connected.length} relationship${connected.length === 1 ? "" : "s"}${first ? ` · ${first}` : ""}`;
}

function drawMapNode(
  node: CanvasMapNode,
  context: CanvasRenderingContext2D,
  globalScale: number,
) {
  const radius = node.kind === "cluster" || node.kind === "collection"
    ? Math.max(6, Math.min(13, 6 + (node.source_count ?? 0) / 12))
    : node.kind === "fact" ? 4 : 5;
  context.beginPath();
  context.arc(node.x, node.y, radius, 0, Math.PI * 2);
  context.fillStyle = nodeColor(node);
  context.fill();
  context.lineWidth = 1.5 / globalScale;
  context.strokeStyle = "#FFFFFF";
  context.stroke();

  if (!node.showLabel && globalScale < (node.denseGraph ? 2.4 : 1.25)) return;
  const label = node.label.length > 28 ? `${node.label.slice(0, 26).trimEnd()}…` : node.label;
  const fontSize = Math.max(6, Math.min(11, 9 / Math.sqrt(Math.max(globalScale, 0.08))));
  context.font = `600 ${fontSize}px "Segoe UI", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "top";
  context.lineJoin = "round";
  context.lineWidth = Math.max(1.5, 3 / Math.sqrt(Math.max(globalScale, 0.08)));
  context.strokeStyle = "rgba(255,255,255,0.94)";
  context.strokeText(label, node.x, node.y + radius + 3 / globalScale);
  context.fillStyle = "#3D3C39";
  context.fillText(label, node.x, node.y + radius + 3 / globalScale);
}

function drawMapLinkLabel(
  edge: CanvasMapEdge,
  context: CanvasRenderingContext2D,
  globalScale: number,
  nodeCount: number,
) {
  if (nodeCount > 28 || globalScale < 1.15 || typeof edge.source !== "object" || typeof edge.target !== "object") {
    return;
  }
  const x = (edge.source.x + edge.target.x) / 2;
  const y = (edge.source.y + edge.target.y) / 2;
  const label = edge.label.length > 30 ? `${edge.label.slice(0, 28).trimEnd()}…` : edge.label;
  const fontSize = Math.max(5, Math.min(9, 8 / Math.sqrt(Math.max(globalScale, 0.08))));
  context.font = `500 ${fontSize}px "Segoe UI", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineWidth = Math.max(1.25, 2.5 / Math.sqrt(Math.max(globalScale, 0.08)));
  context.strokeStyle = "rgba(255,255,255,0.92)";
  context.strokeText(label, x, y);
  context.fillStyle = "#6B6A66";
  context.fillText(label, x, y);
}

type CanvasMapEdge = Omit<MapEdgeRecord, "source" | "target"> & {
  source: { x: number; y: number };
  target: { x: number; y: number };
};

type CanvasMapNode = MapNodeRecord & {
  x: number;
  y: number;
  showLabel?: boolean;
  denseGraph?: boolean;
};

function readMapViewFromUrl(enabled: boolean) {
  if (!enabled || typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const zoom = Number(params.get("mapZoom"));
  return {
    rootId: params.get("mapRoot"),
    selectedId: params.get("mapSelected"),
    zoom: Number.isFinite(zoom) && zoom >= 0.12 && zoom <= 4 ? zoom : 1,
  };
}

function setOrDelete(params: URLSearchParams, key: string, value: string | null | undefined) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function formatDate(value: string) {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(timestamp);
}

function formatState(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
