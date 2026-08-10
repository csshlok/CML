import { type ComponentType, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowLeft,
  ChevronDown,
  GitBranch,
  ListTree,
  Maximize2,
  Network,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Waypoints,
  X,
} from "lucide-react";
import {
  getProjectGraphPath,
  getProjectGraphView,
  type ProjectGraphEdge,
  type ProjectGraphNode,
  type ProjectGraphPath,
  type ProjectGraphView,
} from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layout/WindowAware";
import { displayPath } from "@/lib/displayPath";

type GraphNode = ProjectGraphNode & { x?: number; y?: number; color?: string };
type GraphLink = ProjectGraphEdge & { source: string | GraphNode; target: string | GraphNode };
const MAX_QUERY_LENGTH = 500;
const STANDARD_GRAPH_LIMIT = 300;
const ALL_RELEVANT_GRAPH_LIMIT = 2000;
const QUESTION_GRAPH_MAX_DEPTH = 2;

export type ProjectVisualizationRequest = {
  mode: "graph" | "tree";
  query: string;
};

export function detectProjectVisualizationRequest(prompt: string): ProjectVisualizationRequest | null {
  const normalized = prompt.trim();
  const asksToShow = /\b(show|draw|display|render|visuali[sz]e|map|diagram|give me|open)\b/i.test(normalized);
  const graphTerm = /\b(graph|project map|dependency map|call flow|relationship map|architecture diagram)\b/i.test(normalized);
  const treeTerm = /\b(tree|hierarchy|directory structure|project structure|file structure)\b/i.test(normalized);
  if (!asksToShow || (!graphTerm && !treeTerm)) return null;
  return { mode: treeTerm && !graphTerm ? "tree" : "graph", query: normalized };
}

export function ProjectGraphLink({
  projectId,
  request,
}: {
  projectId: string;
  request: ProjectVisualizationRequest;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-y border-border py-3">
      <div className="min-w-0">
        <div className="text-sm font-medium">Project map ready</div>
        <div className="mt-1 text-xs text-muted-foreground">
          Open a larger view with filters, flows, and source details.
        </div>
      </div>
      <Button asChild size="sm">
        <Link
          to="/project-map"
          search={{ project: projectId, mode: request.mode, q: request.query }}
        >
          <Maximize2 className="h-4 w-4" /> Open map
        </Link>
      </Button>
    </div>
  );
}

export function ProjectGraphWorkspace({
  projectId,
  projectName,
  initialMode,
  initialQuery,
}: {
  projectId: string;
  projectName: string;
  initialMode: "graph" | "tree";
  initialQuery: string;
}) {
  const [mode, setMode] = useState<"graph" | "tree">(initialMode);
  const [query, setQuery] = useState(initialQuery.slice(0, MAX_QUERY_LENGTH));
  const [submittedQuery, setSubmittedQuery] = useState(initialQuery.slice(0, MAX_QUERY_LENGTH));
  const [direction, setDirection] = useState<"outbound" | "inbound" | "balanced">("balanced");
  const [maxDepth, setMaxDepth] = useState(2);
  const [maxNodes, setMaxNodes] = useState(initialMode === "tree" ? 180 : 90);
  const [spread, setSpread] = useState<"normal" | "wide">("normal");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pathSource, setPathSource] = useState("");
  const [pathTarget, setPathTarget] = useState("");
  const [pathResult, setPathResult] = useState<ProjectGraphPath | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [pathLoading, setPathLoading] = useState(false);
  const [view, setView] = useState<ProjectGraphView | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const graphRef = useRef<any>(null);
  const [containerElement, setContainerElement] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 900, height: 620 });
  const [ForceGraph, setForceGraph] = useState<ComponentType<any> | null>(null);

  useEffect(() => {
    if (mode !== "graph") {
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
  }, [mode]);

  useEffect(() => {
    if (!containerElement) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setSize({
        width: Math.max(360, Math.floor(entry.contentRect.width)),
        height: Math.max(520, Math.floor(entry.contentRect.height)),
      });
    });
    observer.observe(containerElement);
    return () => observer.disconnect();
  }, [containerElement]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getProjectGraphView(projectId, {
      mode,
      query: submittedQuery,
      maxDepth,
      maxNodes,
      direction,
    })
      .then((next) => {
        if (cancelled) return;
        setView(next);
        setSelectedId(null);
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load this project map.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [direction, maxDepth, maxNodes, mode, projectId, submittedQuery]);

  const graphData = useMemo(
    () => ({
      nodes: (view?.nodes ?? []).map((node) => ({ ...node, color: colorForKind(node.kind) })),
      links: (view?.edges ?? []).map((edge) => ({ ...edge })),
    }),
    [view],
  );
  const selected = view?.nodes.find((node) => node.id === selectedId) ?? null;
  const selectedConnections = useMemo(() => {
    if (!view || !selectedId) return { upstream: [], downstream: [] };
    const byId = new Map(view.nodes.map((node) => [node.id, node]));
    return {
      upstream: view.edges
        .filter((edge) => String(edge.target) === selectedId)
        .map((edge) => ({ edge, node: byId.get(String(edge.source)) }))
        .filter((item): item is { edge: ProjectGraphEdge; node: ProjectGraphNode } => Boolean(item.node)),
      downstream: view.edges
        .filter((edge) => String(edge.source) === selectedId)
        .map((edge) => ({ edge, node: byId.get(String(edge.target)) }))
        .filter((item): item is { edge: ProjectGraphEdge; node: ProjectGraphNode } => Boolean(item.node)),
    };
  }, [selectedId, view]);

  useEffect(() => {
    if (mode !== "graph" || !ForceGraph || !view || view.nodes.length === 0) return;
    let fitTimer: number | null = null;
    const timer = window.setTimeout(() => {
      const graph = graphRef.current;
      graph?.d3Force?.("charge")?.strength?.(spread === "wide" ? -260 : -120);
      graph?.d3Force?.("link")?.distance?.(spread === "wide" ? 100 : 58);
      graph?.d3ReheatSimulation?.();
      fitTimer = window.setTimeout(() => graph?.zoomToFit?.(280, 56), 240);
    }, 30);
    return () => {
      window.clearTimeout(timer);
      if (fitTimer !== null) window.clearTimeout(fitTimer);
    };
  }, [ForceGraph, mode, spread, view]);

  useEffect(
    () => () => {
      const graph = graphRef.current;
      graph?.pauseAnimation?.();
      graph?._destructor?.();
      graphRef.current = null;
    },
    [],
  );

  function expandView() {
    setMaxDepth((current) => Math.min(submittedQuery ? QUESTION_GRAPH_MAX_DEPTH : 4, current + 1));
    setMaxNodes((current) =>
      current < STANDARD_GRAPH_LIMIT
        ? Math.min(STANDARD_GRAPH_LIMIT, Math.max(current + 70, Math.round(current * 1.5)))
        : ALL_RELEVANT_GRAPH_LIMIT,
    );
    setSpread("wide");
  }

  const depthLimit = submittedQuery ? QUESTION_GRAPH_MAX_DEPTH : 4;
  const canExpand = Boolean(view?.truncated) && (maxDepth < depthLimit || maxNodes < ALL_RELEVANT_GRAPH_LIMIT);
  const showAllRelevant = maxDepth >= depthLimit && maxNodes >= STANDARD_GRAPH_LIMIT;

  async function findPath() {
    if (!pathSource.trim() || !pathTarget.trim()) return;
    setPathLoading(true);
    setPathError(null);
    try {
      setPathResult(await getProjectGraphPath(projectId, pathSource.trim(), pathTarget.trim()));
    } catch (reason) {
      setPathResult(null);
      setPathError(pathErrorMessage(reason));
    } finally {
      setPathLoading(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col bg-background">
      <PageHeader className="border-b border-border px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
              <Link to="/projects/$projectId" params={{ projectId }}>
                <ArrowLeft className="h-4 w-4" /> {projectName}
              </Link>
            </Button>
            <h1 className="text-xl font-semibold">Project map</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Follow indexed code relationships. Every node links back to a local file.
            </p>
          </div>
          <div className="flex items-center border border-border bg-card">
            <button
              type="button"
              className={`flex h-9 items-center gap-1.5 px-3 text-sm ${mode === "graph" ? "bg-accent" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setMode("graph")}
            >
              <Network className="h-4 w-4" /> Graph
            </button>
            <button
              type="button"
              className={`flex h-9 items-center gap-1.5 border-l border-border px-3 text-sm ${mode === "tree" ? "bg-accent" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setMode("tree")}
            >
              <ListTree className="h-4 w-4" /> Tree
            </button>
          </div>
        </div>
        <form
          className="mt-4 flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmittedQuery(query.trim());
            setMaxDepth(2);
            setMaxNodes(mode === "tree" ? 180 : 90);
          }}
        >
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={query}
              maxLength={MAX_QUERY_LENGTH}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-9"
              placeholder="Find a flow, file, route, or symbol"
              aria-label="Filter project map"
            />
          </div>
          <Button type="submit">Show</Button>
          {mode === "graph" ? (
            <Button type="button" variant="outline" disabled={!canExpand || loading} onClick={expandView}>
              <Maximize2 className="h-4 w-4" /> {showAllRelevant ? "Show all relevant" : "Show more"}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((current) => !current)}
          >
            <SlidersHorizontal className="h-4 w-4" /> Advanced
          </Button>
        </form>
        {advancedOpen ? (
          <div className={`mt-4 grid gap-4 border-t border-border pt-4 ${mode === "graph" ? "lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]" : ""}`}>
            {mode === "graph" ? <div>
              <div className="text-sm font-medium">Relationship view</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Change which side of a matched item Odin follows. These controls never change the index.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <label className="relative">
                  <span className="sr-only">Relationship direction</span>
                  <select
                    value={direction}
                    onChange={(event) => setDirection(event.target.value as typeof direction)}
                    className="h-9 appearance-none rounded-md border border-input bg-card pl-3 pr-8 text-sm"
                  >
                    <option value="balanced">Both directions</option>
                    <option value="outbound">What this calls</option>
                    <option value="inbound">What calls this</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                </label>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setSpread((current) => (current === "normal" ? "wide" : "normal"))}
                >
                  {spread === "wide" ? "Normal spacing" : "Spread out"}
                </Button>
              </div>
            </div> : null}
            <div className={mode === "graph" ? "border-t border-border pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" : ""}>
              <div className="flex items-center gap-2 text-sm font-medium">
                <Waypoints className="h-4 w-4" /> Trace a path
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Enter two exact file, route, class, or function names to see whether indexed relationships connect them.
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Input value={pathSource} list={`${projectId}-path-items`} onChange={(event) => setPathSource(event.target.value)} placeholder="Start item" aria-label="Path start item" />
                <Input value={pathTarget} list={`${projectId}-path-items`} onChange={(event) => setPathTarget(event.target.value)} placeholder="End item" aria-label="Path end item" />
                <Button type="button" variant="outline" disabled={pathLoading || !pathSource.trim() || !pathTarget.trim()} onClick={() => void findPath()}>
                  {pathLoading ? "Tracing…" : "Trace"}
                </Button>
              </div>
              <datalist id={`${projectId}-path-items`}>
                {(view?.nodes ?? []).map((node) => (
                  <option key={node.id} value={node.qualified_id}>{node.label}</option>
                ))}
              </datalist>
              {pathError ? <p className="mt-2 text-xs text-destructive">{pathError}</p> : null}
              {pathResult ? (
                <div className="mt-3 border-l-2 border-primary/50 pl-3 text-xs leading-5">
                  {pathResult.status === "found"
                    ? pathResult.path.map((node) => node.label || node.display_label || node.qualified_id).join(" → ")
                    : `No path was found in this bounded search (${humanize(pathResult.status)}).`}
                  <div className="mt-1 text-muted-foreground">
                    Checked {pathResult.visited_nodes.toLocaleString()} items in {pathResult.elapsed_ms.toLocaleString()} ms.
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </PageHeader>

      {error ? (
        <div className="m-6 border border-destructive/40 px-4 py-3 text-sm text-destructive">{error}</div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {view && !loading ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-card/40 px-4 py-2 text-xs text-muted-foreground sm:px-6">
              <span>
                {submittedQuery ? `Focused on “${submittedQuery}”` : "Showing the most connected indexed areas"}
                {` · ${mode === "graph" ? humanize(direction) : "File hierarchy"}`}
              </span>
              <span>
                {submittedQuery
                  ? `Showing ${view.nodes.length.toLocaleString()} question-focused ${view.nodes.length === 1 ? "item" : "items"} · ${view.project_totals.nodes.toLocaleString()} indexed in project`
                  : `Showing ${view.nodes.length.toLocaleString()} of ${view.project_totals.nodes.toLocaleString()} indexed items`}
                {view.truncated
                  ? maxNodes >= ALL_RELEVANT_GRAPH_LIMIT
                    ? " · safe rendering limit reached"
                    : " · more relevant relationships are available"
                  : ""}
              </span>
            </div>
          ) : null}
          <div className={`grid min-h-0 flex-1 ${selected ? "xl:grid-cols-[minmax(0,1fr)_320px]" : ""}`}>
          <main className="grid min-h-0 min-w-0 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div ref={setContainerElement} className="relative min-h-[560px] overflow-hidden">
              {loading ? (
                <div className="h-full min-h-[560px] animate-pulse bg-muted/35" aria-label="Loading project map" />
              ) : !view || view.nodes.length === 0 ? (
                <div className="flex min-h-[560px] items-center justify-center px-6 text-center text-sm text-muted-foreground">
                  No indexed symbols matched this view. Try a file, route, or symbol name.
                </div>
              ) : mode === "graph" && ForceGraph ? (
                <>
                  <div className="pointer-events-none absolute left-4 top-4 z-10 border border-border bg-card/95 px-3 py-2 text-[11px] text-muted-foreground">
                    <div className="font-medium text-foreground">Color key</div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                      <LegendDot color={colorForKind("file")} label="file" />
                      <LegendDot color={colorForKind("function")} label="function" />
                      <LegendDot color={colorForKind("class")} label="class" />
                      <LegendDot color={colorForKind("route")} label="route" />
                    </div>
                    <div className="mt-1">Arrows follow the indexed relationship.</div>
                  </div>
                  <ForceGraph
                    ref={graphRef}
                    width={size.width}
                    height={size.height}
                    graphData={graphData}
                    backgroundColor="rgba(0,0,0,0)"
                    warmupTicks={80}
                    cooldownTicks={150}
                    d3VelocityDecay={0.34}
                    nodeRelSize={5}
                    nodeLabel={(node: GraphNode) => `${node.kind}: ${node.label}`}
                    nodeColor={(node: GraphNode) => node.color ?? "#6B6A66"}
                    linkColor={() => "#B9B7B0"}
                    linkWidth={(link: GraphLink) => (link.type === "calls" ? 1.8 : 1)}
                    linkDirectionalArrowLength={3}
                    linkDirectionalArrowRelPos={0.86}
                    onNodeClick={(node: GraphNode) => setSelectedId(node.id)}
                    nodeCanvasObjectMode={() => "after"}
                    nodeCanvasObject={(node: GraphNode, context: CanvasRenderingContext2D, scale: number) => {
                      const important = node.id === selectedId || (view.insights.key_areas ?? []).some((area) => area.id === node.id);
                      if (!important || node.x == null || node.y == null) return;
                      const fontSize = Math.max(11 / scale, 3);
                      context.font = `${fontSize}px sans-serif`;
                      context.fillStyle = "#25231F";
                      context.fillText(node.label, node.x + 8 / scale, node.y + 3 / scale);
                    }}
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    className="absolute bottom-4 left-4 bg-card"
                    onClick={() => graphRef.current?.zoomToFit?.(280, 56)}
                    aria-label="Fit map to view"
                  >
                    <RotateCcw className="h-4 w-4" />
                  </Button>
                </>
              ) : mode === "tree" && view ? (
                <ProjectTree view={view} selectedId={selectedId} onSelect={setSelectedId} />
              ) : (
                <div className="h-full min-h-[560px] animate-pulse bg-muted/35" />
              )}
            </div>
            {view && !loading ? <GraphExplanation view={view} onSelect={setSelectedId} /> : null}
          </main>
          {selected ? (
            <aside className="min-w-0 border-l border-border bg-card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="break-words font-medium">{selected.label}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {selected.kind}{selected.language ? ` / ${selected.language}` : ""}
                  </div>
                </div>
                <Button variant="ghost" size="icon" onClick={() => setSelectedId(null)} aria-label="Close node details">
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <div className="mt-5 break-all font-mono text-xs leading-6 text-muted-foreground">
                {displayPath(selected.relative_path) || "Project root"}
                {selected.start_line ? `:${selected.start_line}` : ""}
              </div>
              {selected.signature ? (
                <div className="mt-4 break-words border-t border-border pt-4 font-mono text-xs leading-6">
                  {selected.signature}
                </div>
              ) : null}
              {selected.matched_terms?.length ? (
                <div className="mt-4 border-t border-border pt-4 text-xs text-muted-foreground">
                  Direct question match: {selected.matched_terms.join(", ")}
                </div>
              ) : null}
              <p className="mt-5 border-t border-border pt-4 text-xs leading-5 text-muted-foreground">
                {submittedQuery
                  ? `This item appears because it is connected to the “${submittedQuery}” slice.`
                  : "This item appears in Odin's most connected project slice."}
                {selected.source_id ? " Its location is backed by an indexed source file." : " It is a structural project node."}
              </p>
              <ConnectionList title="Called or contained by" items={selectedConnections.upstream} onSelect={setSelectedId} />
              <ConnectionList title="Calls or contains" items={selectedConnections.downstream} onSelect={setSelectedId} />
              <Button
                className="mt-5"
                size="sm"
                variant="outline"
                onClick={() => {
                  setQuery(selected.label);
                   setSubmittedQuery(selected.label);
                   setMaxDepth(2);
                   setMaxNodes(90);
                 }}
              >
                Focus here
              </Button>
            </aside>
          ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function GraphExplanation({
  view,
  onSelect,
}: {
  view: ProjectGraphView;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="min-w-0 overflow-y-auto border-l border-border p-5">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <GitBranch className="h-4 w-4" /> What this view shows
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{view.insights.summary}</p>
      {view.insights.key_areas.length ? (
        <section className="mt-6">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Key areas</h2>
          <div className="mt-2 divide-y divide-border border-y border-border">
            {view.insights.key_areas.map((area) => (
              <button
                key={area.id}
                type="button"
                className="block w-full py-2.5 text-left hover:text-primary"
                onClick={() => onSelect(area.id)}
              >
                <span className="block truncate text-sm">{area.label}</span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                  {area.connections} connections · {displayPath(area.relative_path) || area.kind}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {area.why || "Connected to several items in this bounded view"}
                  {area.community?.label ? ` · ${area.community.label}` : ""}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {view.insights.flows.length ? (
        <section className="mt-6">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Observed flows</h2>
          <ol className="mt-3 divide-y divide-border border-y border-border">
            {view.insights.flows.map((flow, index) => (
              <li key={`${flow.node_ids.join(":")}-${index}`}>
                <button
                  type="button"
                  className="w-full py-3 text-left"
                  onClick={() => onSelect(flow.node_ids[0])}
                >
                  <span className="block text-sm text-foreground">
                    {flow.steps[0]} → {flow.steps.at(-1)}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {flow.relationships.map(humanize).join(" → ")} · {humanize(flow.confidence)}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">{flow.reason}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <div className="mt-6 border-t border-border pt-3 text-xs text-muted-foreground">
        Showing {view.nodes.length.toLocaleString()} {view.nodes.length === 1 ? "item" : "items"} and {view.edges.length.toLocaleString()} {view.edges.length === 1 ? "relationship" : "relationships"}
        {view.truncated
          ? ` · more relevant relationships remain beyond these ${view.limits.max_nodes.toLocaleString()} items`
          : " · complete relevant slice"}
      </div>
    </aside>
  );
}

function ConnectionList({
  title,
  items,
  onSelect,
}: {
  title: string;
  items: Array<{ edge: ProjectGraphEdge; node: ProjectGraphNode }>;
  onSelect: (id: string) => void;
}) {
  if (!items.length) return null;
  return (
    <section className="mt-5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="mt-2 divide-y divide-border border-y border-border">
        {items.slice(0, 8).map(({ edge, node }) => (
          <button
            key={edge.id}
            type="button"
            className="block w-full py-2 text-left"
            onClick={() => onSelect(node.id)}
          >
            <span className="block truncate text-xs text-foreground">{node.label}</span>
            <span className="mt-0.5 block text-[11px] text-muted-foreground">
              {humanize(edge.type)} · {humanize(edge.confidence)}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} /> {label}
    </span>
  );
}

function ProjectTree({
  view,
  selectedId,
  onSelect,
}: {
  view: ProjectGraphView;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const depthById = useMemo(() => {
    const parentByTarget = new Map(
      view.edges.map((edge) => [String(edge.target), String(edge.source)]),
    );
    return new Map(
      view.nodes.map((node) => {
        let depth = 0;
        let cursor = parentByTarget.get(node.id);
        const seen = new Set<string>();
        while (cursor && !seen.has(cursor) && depth < 12) {
          seen.add(cursor);
          depth += 1;
          cursor = parentByTarget.get(cursor);
        }
        return [node.id, depth] as const;
      }),
    );
  }, [view.edges, view.nodes]);
  const rowVirtualizer = useVirtualizer({
    count: view.nodes.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 32,
    getItemKey: (index) => view.nodes[index]?.id ?? index,
    overscan: 8,
    useFlushSync: false,
  });
  return (
    <div ref={scrollRef} className="h-full min-h-[560px] overflow-auto py-3 font-mono text-xs">
      <div className="relative" style={{ height: `${rowVirtualizer.getTotalSize()}px` }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const node = view.nodes[virtualRow.index];
          if (!node) return null;
          return (
            <button
              key={node.id}
              ref={rowVirtualizer.measureElement}
              data-index={virtualRow.index}
              type="button"
              className={`absolute left-0 top-0 flex w-full items-center gap-2 px-3 py-2 text-left ${selectedId === node.id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}
              style={{
                paddingLeft: `${12 + (depthById.get(node.id) ?? 0) * 16}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
              onClick={() => onSelect(node.id)}
            >
              <span className="w-16 shrink-0 text-[10px] text-muted-foreground">{node.kind}</span>
              <span className="truncate">{node.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function colorForKind(kind: string) {
  if (kind === "route") return "#C0704A";
  if (kind === "class") return "#8A7CC0";
  if (kind === "function" || kind === "method") return "#5B8A5B";
  if (kind === "file" || kind === "module") return "#4A78A8";
  if (kind === "package") return "#B8944A";
  return "#7C6E5A";
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
}

function pathErrorMessage(reason: unknown) {
  const message = reason instanceof Error ? reason.message : "";
  if (/ambiguous/i.test(message)) {
    return "More than one indexed item has that name. Choose a specific item from the field suggestions.";
  }
  if (/not found|could not find/i.test(message)) {
    return "Odin could not find one of those items in the active project map.";
  }
  return message || "Could not trace a path between these items.";
}
