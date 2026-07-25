import { type ComponentType, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, ListTree, Network, RotateCcw, Search, X } from "lucide-react";
import {
  getProjectGraphView,
  type ProjectGraphEdge,
  type ProjectGraphNode,
  type ProjectGraphView,
} from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  const graphTerm = /\b(graph|dependency map|call flow|relationship map|architecture diagram)\b/i.test(normalized);
  const treeTerm = /\b(tree|hierarchy|directory structure|project structure|file structure)\b/i.test(normalized);
  if (!asksToShow || (!graphTerm && !treeTerm)) return null;
  return { mode: treeTerm && !graphTerm ? "tree" : "graph", query: normalized };
}

export function ProjectGraphArtifact({
  projectId,
  request,
}: {
  projectId: string;
  request: ProjectVisualizationRequest;
}) {
  const [mode, setMode] = useState<"graph" | "tree">(request.mode);
  const initialQuery = request.query.slice(0, MAX_QUERY_LENGTH);
  const [query, setQuery] = useState(initialQuery);
  const [submittedQuery, setSubmittedQuery] = useState(initialQuery);
  const [view, setView] = useState<ProjectGraphView | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const graphRef = useRef<any>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const [graphWidth, setGraphWidth] = useState(720);
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
    const element = graphContainerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setGraphWidth(Math.max(320, Math.floor(entry.contentRect.width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getProjectGraphView(projectId, {
      mode,
      query: submittedQuery,
      maxDepth: 2,
      maxNodes: mode === "tree" ? 180 : 72,
    })
      .then((next) => {
        if (cancelled) return;
        setView(next);
        setSelectedId(next.nodes[0]?.id ?? null);
        window.setTimeout(() => graphRef.current?.zoomToFit?.(250, 34), 0);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the project graph.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, mode, submittedQuery]);

  const graphData = useMemo(
    () => ({
      nodes: (view?.nodes ?? []).map((node) => ({ ...node, color: colorForKind(node.kind) })),
      links: (view?.edges ?? []).map((edge) => ({ ...edge })),
    }),
    [view],
  );
  const selected = view?.nodes.find((node) => node.id === selectedId) ?? null;

  if (hidden) {
    return (
      <button
        type="button"
        className="flex items-center gap-2 border border-border bg-card px-3 py-2 text-sm hover:bg-accent"
        onClick={() => setHidden(false)}
      >
        <Network className="h-4 w-4" /> Show requested architecture view
      </button>
    );
  }

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-card" aria-label="Requested project architecture">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <GitBranch className="h-4 w-4 text-muted-foreground" />
        <div className="mr-auto text-sm font-medium">Requested architecture view</div>
        <div className="flex border border-border">
          <button
            type="button"
            className={`flex h-8 items-center gap-1.5 px-2.5 text-xs ${mode === "graph" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setMode("graph")}
          >
            <Network className="h-3.5 w-3.5" /> Graph
          </button>
          <button
            type="button"
            className={`flex h-8 items-center gap-1.5 border-l border-border px-2.5 text-xs ${mode === "tree" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setMode("tree")}
          >
            <ListTree className="h-3.5 w-3.5" /> Tree
          </button>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setHidden(true)} aria-label="Hide architecture view">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <form
        className="flex items-center gap-2 border-b border-border px-3 py-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmittedQuery(query.trim());
        }}
      >
        <Search className="h-4 w-4 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={MAX_QUERY_LENGTH}
          className="h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
          aria-label="Filter architecture view"
        />
        <Button type="submit" variant="outline" size="sm" className="h-8">Apply</Button>
        <span className="sr-only" aria-live="polite">{query.length} of {MAX_QUERY_LENGTH} characters</span>
      </form>

      {loading ? (
        <div className="h-[420px] animate-pulse bg-muted/40" aria-label="Loading architecture view" />
      ) : error ? (
        <div className="p-4 text-sm text-destructive">{error}</div>
      ) : !view || view.nodes.length === 0 ? (
        <div className="p-6 text-sm text-muted-foreground">No indexed symbols matched this request. Try a file path or symbol name.</div>
      ) : (
        <div className="min-h-[420px]">
          <div
            ref={graphContainerRef}
            className="relative min-h-[420px] overflow-hidden bg-background"
            role={mode === "graph" ? "img" : undefined}
            aria-label={mode === "graph" ? `Project architecture graph with ${view.nodes.length} nodes and ${view.edges.length} relationships. Use Tree for a keyboard-navigable view.` : undefined}
          >
            {mode === "graph" && ForceGraph ? (
              <ForceGraph
                ref={graphRef}
                width={graphWidth}
                height={420}
                graphData={graphData}
                backgroundColor="rgba(0,0,0,0)"
                warmupTicks={60}
                cooldownTicks={100}
                d3VelocityDecay={0.42}
                nodeRelSize={5}
                nodeLabel={(node: GraphNode) => `${node.kind}: ${node.label}`}
                nodeColor={(node: GraphNode) => node.color ?? "#6B6A66"}
                linkColor={() => "#C8C7C2"}
                linkWidth={(link: GraphLink) => (link.type === "calls" ? 1.8 : 1)}
                linkDirectionalArrowLength={3}
                linkDirectionalArrowRelPos={0.86}
                onNodeClick={(node: GraphNode) => setSelectedId(node.id)}
                onEngineStop={() => graphRef.current?.zoomToFit?.(250, 34)}
                nodeCanvasObjectMode={() => "after"}
                nodeCanvasObject={(node: GraphNode, context: CanvasRenderingContext2D, globalScale: number) => {
                  const graphNode = node;
                  if (graphNode.id !== selectedId || graphNode.x == null || graphNode.y == null) return;
                  context.beginPath();
                  context.arc(graphNode.x, graphNode.y, 8 / globalScale, 0, Math.PI * 2);
                  context.strokeStyle = "#1A1916";
                  context.lineWidth = 1.5 / globalScale;
                  context.stroke();
                  const fontSize = Math.max(10 / globalScale, 3);
                  context.font = `${fontSize}px sans-serif`;
                  const labelWidth = context.measureText(graphNode.label).width;
                  const placeLeft = graphNode.x > 0;
                  const labelX = placeLeft
                    ? graphNode.x - labelWidth - 10 / globalScale
                    : graphNode.x + 10 / globalScale;
                  const labelY = graphNode.y + 3 / globalScale;
                  context.fillStyle = "rgba(255,255,255,0.9)";
                  context.fillRect(labelX - 2 / globalScale, labelY - fontSize, labelWidth + 4 / globalScale, fontSize + 4 / globalScale);
                  context.fillStyle = "#1A1916";
                  context.fillText(graphNode.label, labelX, labelY);
                }}
              />
            ) : mode === "graph" ? (
              <div className="h-[420px] animate-pulse bg-muted/40" aria-label="Loading graph renderer" />
            ) : (
              <ProjectTree view={view} selectedId={selectedId} onSelect={setSelectedId} />
            )}
            {mode === "graph" && (
              <Button
                variant="outline"
                size="icon"
                className="absolute bottom-3 left-3 h-8 w-8 bg-card"
                onClick={() => graphRef.current?.zoomToFit?.(250, 34)}
                aria-label="Fit graph to view"
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
            )}
          </div>
          <aside className="border-t border-border p-3">
            {selected ? (
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <div className="text-sm font-medium break-words">{selected.label}</div>
                <div className="text-xs text-muted-foreground">{selected.kind}{selected.language ? ` / ${selected.language}` : ""}</div>
                <div className="break-all font-mono text-xs leading-5 text-muted-foreground">
                  {displayPath(selected.relative_path) || "Project root"}{selected.start_line ? `:${selected.start_line}` : ""}
                </div>
                {selected.signature && <div className="w-full break-words border-t border-border pt-2 font-mono text-xs">{selected.signature}</div>}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">Select a node to inspect its source evidence.</div>
            )}
            <div className="mt-3 border-t border-border pt-2 text-xs text-muted-foreground">
              {view.nodes.length} nodes / {view.edges.length} relationships
              {view.truncated ? " / bounded result" : ""}
            </div>
          </aside>
        </div>
      )}
    </section>
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
    <div className="h-[420px] overflow-auto py-2 font-mono text-xs">
      {view.nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left ${selectedId === node.id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}
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
