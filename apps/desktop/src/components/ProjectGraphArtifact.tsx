import { type ComponentType, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  ArrowLeft,
  ChevronDown,
  GitBranch,
  ListTree,
  Maximize2,
  Network,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  getProjectGraphView,
  type ProjectGraphEdge,
  type ProjectGraphNode,
  type ProjectGraphView,
} from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layout/WindowAware";
import { displayPath } from "@/lib/displayPath";

type GraphNode = ProjectGraphNode & { x?: number; y?: number; color?: string };
type GraphLink = ProjectGraphEdge & { source: string | GraphNode; target: string | GraphNode };
const MAX_QUERY_LENGTH = 500;

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
  const [view, setView] = useState<ProjectGraphView | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const graphRef = useRef<any>(null);
  const [containerElement, setContainerElement] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 900, height: 620 });
  const [ForceGraph, setForceGraph] = useState<ComponentType<any> | null>(null);

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

  function expandView() {
    setMaxDepth((current) => Math.min(4, current + 1));
    setMaxNodes((current) => Math.min(300, Math.max(current + 70, Math.round(current * 1.5))));
    setSpread("wide");
  }

  const canExpand = maxDepth < 4 || maxNodes < 300;

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
          {mode === "graph" ? (
            <>
              <label className="relative">
                <span className="sr-only">Relationship direction</span>
                <select
                  value={direction}
                  onChange={(event) => setDirection(event.target.value as typeof direction)}
                  className="h-10 appearance-none rounded-md border border-input bg-card pl-3 pr-8 text-sm"
                >
                  <option value="balanced">Both directions</option>
                  <option value="outbound">What this calls</option>
                  <option value="inbound">What calls this</option>
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 top-3 h-4 w-4 text-muted-foreground" />
              </label>
              <Button
                type="button"
                variant="outline"
                onClick={() => setSpread((current) => (current === "normal" ? "wide" : "normal"))}
              >
                {spread === "wide" ? "Normal spacing" : "Spread out"}
              </Button>
              <Button type="button" variant="outline" disabled={!canExpand || loading} onClick={expandView}>
                <Maximize2 className="h-4 w-4" /> Show more
              </Button>
            </>
          ) : null}
          <Button type="submit">Apply</Button>
        </form>
      </PageHeader>

      {error ? (
        <div className="m-6 border border-destructive/40 px-4 py-3 text-sm text-destructive">{error}</div>
      ) : (
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
              <Button
                className="mt-5"
                size="sm"
                variant="outline"
                onClick={() => {
                  setQuery(selected.label);
                  setSubmittedQuery(selected.label);
                  setMaxDepth(Math.max(2, maxDepth));
                }}
              >
                Focus here
              </Button>
            </aside>
          ) : null}
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
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {view.insights.flows.length ? (
        <section className="mt-6">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Observed flows</h2>
          <ol className="mt-3 space-y-3">
            {view.insights.flows.map((flow, index) => (
              <li key={`${flow.node_ids.join(":")}-${index}`} className="text-xs leading-5 text-muted-foreground">
                {flow.steps.join(" → ")}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <div className="mt-6 border-t border-border pt-3 text-xs text-muted-foreground">
        {view.nodes.length} items · {view.edges.length} relationships
        {view.truncated ? " · more available" : ""}
      </div>
    </aside>
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
  const parentByTarget = new Map(view.edges.map((edge) => [String(edge.target), String(edge.source)]));
  const depthFor = (node: ProjectGraphNode) => {
    let depth = 0;
    let cursor = parentByTarget.get(node.id);
    const seen = new Set<string>();
    while (cursor && !seen.has(cursor) && depth < 12) {
      seen.add(cursor);
      depth += 1;
      cursor = parentByTarget.get(cursor);
    }
    return depth;
  };
  return (
    <div className="h-full min-h-[560px] overflow-auto py-3 font-mono text-xs">
      {view.nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          className={`flex w-full items-center gap-2 px-3 py-2 text-left ${selectedId === node.id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}
          style={{ paddingLeft: `${12 + depthFor(node) * 16}px` }}
          onClick={() => onSelect(node.id)}
        >
          <span className="w-16 shrink-0 text-[10px] text-muted-foreground">{node.kind}</span>
          <span className="truncate">{node.label}</span>
        </button>
      ))}
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
