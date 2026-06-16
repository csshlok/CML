import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  ArrowLeft,
  ExternalLink,
  FolderOpen,
  Minus,
  Plus,
  RotateCcw,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ExpertBadge } from "@/components/ClusterChip";
import { expertLabel, useStore, type Cluster, type Source } from "@/lib/mockStore";

type Point = { x: number; y: number };

const tintHex: Record<Cluster["tint"], string> = {
  sage: "var(--cluster-sage)",
  sand: "var(--cluster-sand)",
  sky: "var(--cluster-sky)",
  blush: "var(--cluster-blush)",
  lavender: "var(--cluster-lavender)",
  terracotta: "var(--cluster-terracotta)",
};

const layoutSeeds = [
  { x: 0.46, y: 0.45 },
  { x: 0.62, y: 0.5 },
  { x: 0.34, y: 0.55 },
  { x: 0.53, y: 0.28 },
  { x: 0.73, y: 0.34 },
  { x: 0.27, y: 0.33 },
  { x: 0.42, y: 0.72 },
  { x: 0.68, y: 0.72 },
] as const;

export function ClusterMap({
  showSources = true,
  focusClusterId,
  clusters: providedClusters,
  sources: providedSources,
}: {
  showSources?: boolean;
  focusClusterId?: string;
  clusters?: Cluster[];
  sources?: Source[];
}) {
  const store = useStore();
  const clusters = providedClusters ?? store.clusters;
  const sources = providedSources ?? store.sources;
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: string; dx: number; dy: number; startX: number; startY: number; moved: boolean } | null>(null);
  const suppressClickRef = useRef(false);
  const [size, setSize] = useState({ w: 900, h: 620 });
  const [zoom, setZoom] = useState(1);
  const [manualPositions, setManualPositions] = useState<Record<string, Point>>({});
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(focusClusterId ?? null);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const clusterPoints = useMemo(() => {
    const marginX = Math.max(86, size.w * 0.09);
    const marginY = Math.max(76, size.h * 0.12);
    const usableW = Math.max(360, size.w - marginX * 2);
    const usableH = Math.max(320, size.h - marginY * 2);

    return clusters.map((cluster, index) => {
      const seed = layoutSeeds[index % layoutSeeds.length];
      const count = sources.filter((source) => source.clusterId === cluster.id).length;
      const basePoint = {
        x: marginX + seed.x * usableW,
        y: marginY + seed.y * usableH,
      };
      return {
        cluster,
        count,
        point: manualPositions[cluster.id] ?? basePoint,
        radius: 34 + Math.min(44, Math.sqrt(Math.max(1, count)) * 14),
      };
    });
  }, [clusters, manualPositions, size.h, size.w, sources]);

  const selectedCluster =
    selectedClusterId ? clusters.find((cluster) => cluster.id === selectedClusterId) ?? null : null;
  const selectedSources = selectedCluster
    ? sources.filter((source) => source.clusterId === selectedCluster.id)
    : [];
  const looseSources = sources.filter((source) => !source.clusterId);

  const sourcePoints = useMemo(() => {
    if (!selectedCluster) return [];
    const center = { x: size.w * 0.45, y: size.h * 0.5 };
    const radius = Math.min(290, Math.max(165, selectedSources.length * 18));
    return selectedSources.slice(0, 18).map((source, index) => {
      const angle = -Math.PI * 0.9 + index * ((Math.PI * 1.8) / Math.max(1, selectedSources.length - 1));
      return {
        source,
        point: {
          x: center.x + Math.cos(angle) * radius,
          y: center.y + Math.sin(angle) * radius * 0.72,
        },
      };
    });
  }, [selectedCluster, selectedSources, size.h, size.w]);

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>, clusterId: string) {
    const point = clusterPoints.find((item) => item.cluster.id === clusterId)?.point;
    if (!point) return;
    dragRef.current = {
      id: clusterId,
      dx: event.clientX / zoom - point.x,
      dy: event.clientY / zoom - point.y,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!dragRef.current || selectedCluster) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const moved = Math.hypot(event.clientX - dragRef.current.startX, event.clientY - dragRef.current.startY) > 4;
    dragRef.current.moved = dragRef.current.moved || moved;
    const next = {
      x: (event.clientX - rect.left) / zoom - dragRef.current.dx,
      y: (event.clientY - rect.top) / zoom - dragRef.current.dy,
    };
    setManualPositions((current) => ({ ...current, [dragRef.current!.id]: next }));
  }

  function stopDrag() {
    suppressClickRef.current = Boolean(dragRef.current?.moved);
    dragRef.current = null;
    window.setTimeout(() => {
      suppressClickRef.current = false;
    }, 0);
  }

  function openCluster(clusterId: string) {
    if (suppressClickRef.current) return;
    setSelectedClusterId(clusterId);
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden bg-background"
      onPointerMove={handlePointerMove}
      onPointerUp={stopDrag}
      onPointerCancel={stopDrag}
    >
      <div
        className="absolute inset-0"
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: "center center",
        }}
      >
        {selectedCluster ? (
          <ClusterDetailMap
            cluster={selectedCluster}
            sources={sourcePoints}
            center={{ x: size.w * 0.45, y: size.h * 0.5 }}
          />
        ) : (
          <>
            {clusterPoints.map(({ cluster, count, point, radius }) => (
              <div
                key={cluster.id}
                className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center"
                style={{ left: point.x, top: point.y }}
              >
                <button
                  className="relative rounded-full text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  style={{
                    width: radius * 2,
                    height: radius * 2,
                  }}
                  onClick={() => openCluster(cluster.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      openCluster(cluster.id);
                    }
                  }}
                  onPointerDown={(event) => handlePointerDown(event, cluster.id)}
                  aria-label={`Open ${cluster.name}`}
                  type="button"
                >
                  <span
                    className="absolute inset-0 rounded-full blur-lg"
                    style={{
                      background: tintHex[cluster.tint],
                      animation:
                        cluster.expert === "learning" ? "cml-pulse-glow 3.2s ease-in-out infinite" : undefined,
                    }}
                  />
                  <span
                    className="absolute inset-[26%] rounded-full"
                    style={{ background: tintHex[cluster.tint], opacity: 0.72 }}
                  />
                  <span className="sr-only">{count} sources</span>
                </button>
                <div className="mt-2 max-w-36 text-sm font-medium leading-tight text-foreground">
                  {cluster.name}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{count} sources</div>
              </div>
            ))}

            {showSources &&
              looseSources.slice(0, 24).map((source, index) => {
                const seed = layoutSeeds[(index + 3) % layoutSeeds.length];
                const x = size.w * (0.12 + seed.x * 0.76) + Math.sin(index * 1.7) * 42;
                const y = size.h * (0.16 + seed.y * 0.7) + Math.cos(index * 1.3) * 34;
                return (
                  <div
                    key={source.id}
                    className="group absolute z-[6] -translate-x-1/2 -translate-y-1/2"
                    style={{ left: x, top: y }}
                  >
                    <button
                      className="peer h-5 w-5 rounded-full border border-border bg-card shadow-sm transition-colors hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      aria-label={source.title}
                      type="button"
                    />
                    <SourcePreview source={source} />
                  </div>
                );
              })}
          </>
        )}
      </div>

      <div className="absolute left-6 top-6 z-30">
        {selectedCluster ? (
          <Button variant="secondary" className="gap-2 rounded-full shadow-sm" onClick={() => setSelectedClusterId(null)}>
            <ArrowLeft className="h-4 w-4" />
            Visual map
          </Button>
        ) : (
          <div className="rounded-md border border-border bg-card px-4 py-3 text-xs text-muted-foreground shadow-sm">
            <div className="font-medium text-foreground">Tips</div>
            <div className="mt-1">Drag clusters, zoom the space, or click a cluster to open its memory.</div>
          </div>
        )}
      </div>

      <div className="absolute bottom-6 right-6 z-30 flex items-center gap-2 rounded-md border border-border bg-card p-2 shadow-sm">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setZoom((value) => Math.max(0.65, value - 0.1))} aria-label="Zoom out">
          <Minus className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setZoom(1)} aria-label="Reset zoom">
          <RotateCcw className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setZoom((value) => Math.min(1.55, value + 0.1))} aria-label="Zoom in">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {selectedCluster && <ClusterDetailPanel cluster={selectedCluster} sources={selectedSources} />}
    </div>
  );
}

function ClusterDetailMap({
  cluster,
  sources,
  center,
}: {
  cluster: Cluster;
  sources: { source: Source; point: Point }[];
  center: Point;
}) {
  return (
    <>
      <svg className="absolute inset-0 h-full w-full" role="presentation">
        {sources.map(({ source, point }) => (
          <line
            key={source.id}
            x1={center.x}
            y1={center.y}
            x2={point.x}
            y2={point.y}
            stroke="rgba(93,143,255,0.22)"
            strokeWidth="1.2"
          />
        ))}
      </svg>
      <div
        className="absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          left: center.x,
          top: center.y,
          width: 150,
          height: 150,
          background: tintHex[cluster.tint],
        }}
      />
      <div
        className="absolute z-20 -translate-x-1/2 text-center"
        style={{ left: center.x, top: center.y + 82, width: 180 }}
      >
        <div className="text-sm font-semibold">{cluster.name}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{sources.length} connected sources</div>
      </div>
      <div
        className="absolute z-20 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ left: center.x, top: center.y, width: 150, height: 150 }}
      />
      {sources.map(({ source, point }, index) => (
        <div
          key={source.id}
          className="group absolute z-20 -translate-x-1/2 -translate-y-1/2 text-center"
          style={{ left: point.x, top: point.y }}
        >
          <button
            className="peer h-12 w-12 rounded-full border border-border shadow-sm transition-colors hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            style={{
              background:
                source.type === "link"
                  ? "var(--badge-link-bg)"
                  : source.type === "image"
                    ? "var(--badge-img-bg)"
                    : index % 2
                      ? "var(--badge-doc-bg)"
                      : "var(--badge-pdf-bg)",
            }}
            aria-label={source.title}
            type="button"
          />
          <div className="mt-2 max-w-36 text-xs font-medium leading-tight">{source.title}</div>
          <SourcePreview source={source} />
        </div>
      ))}
    </>
  );
}

function SourcePreview({ source }: { source: Source }) {
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const canOpenLink = Boolean(source.url);
  const canOpenLocalPath = Boolean(source.localPath && desktop?.openPath);
  const canRevealLocalPath = Boolean(source.localPath && desktop?.showItemInFolder);

  return (
    <div className="pointer-events-auto absolute left-6 top-6 z-40 hidden w-72 rounded-md border border-border bg-card p-3 text-left shadow-sm group-hover:block group-focus-within:block peer-focus:block">
      <div className="truncate text-sm font-medium text-foreground">{source.title}</div>
      <div className="mt-1 text-xs text-muted-foreground">
        {source.type} / {source.state}
      </div>
      <p className="mt-2 line-clamp-4 text-xs leading-5 text-muted-foreground">
        {source.preview || source.summary || "Preview will appear after extraction."}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground disabled:opacity-45"
          disabled={!canOpenLocalPath}
          title={canOpenLocalPath ? "Open the source file" : "No local file path saved for this source"}
          onClick={(event) => {
            event.stopPropagation();
            if (source.localPath) void desktop?.openPath(source.localPath);
          }}
          type="button"
        >
          <FolderOpen className="h-3 w-3" />
          Library
        </button>
        <button
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground disabled:opacity-45"
          disabled={!canOpenLink && !canRevealLocalPath}
          title={canOpenLink || canRevealLocalPath ? "Open the source location" : "No source location saved"}
          onClick={(event) => {
            event.stopPropagation();
            if (canOpenLink && source.url) {
              window.open(source.url, "_blank", "noopener,noreferrer");
              return;
            }
            if (source.localPath) void desktop?.showItemInFolder(source.localPath);
          }}
          type="button"
        >
          <ExternalLink className="h-3 w-3" />
          {source.type === "link" ? "Open link" : "Explorer"}
        </button>
      </div>
    </div>
  );
}

function ClusterDetailPanel({ cluster, sources }: { cluster: Cluster; sources: Source[] }) {
  const indexedCount = sources.filter((source) => source.state === "indexed").length;
  const adapterEvents = [
    "Built retrieval memory for this cluster",
    "Generated first-pass summary and tags",
    indexedCount > 0 ? `Indexed ${indexedCount} connected sources` : "Waiting for indexed sources",
    cluster.expert === "learning" ? "Local expert learning pass in progress" : "Local expert ready for next update",
  ];

  return (
    <aside className="absolute bottom-6 right-6 top-24 z-30 hidden w-[340px] overflow-hidden rounded-md border border-border bg-card shadow-sm xl:block">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{cluster.name}</div>
            <div className="text-xs text-muted-foreground">{sources.length} connected data points</div>
          </div>
          <ExpertBadge status={cluster.expert} />
        </div>
      </div>
      <div className="h-[calc(100%-57px)] overflow-y-auto p-4">
        <section className="rounded-md border border-border bg-card p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Zap className="h-4 w-4 text-muted-foreground" />
            {expertLabel[cluster.expert]}
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            This cluster can already retrieve context. The local expert will use accepted sources,
            summaries, tags, style profile, and useful chat feedback as its learning set.
          </p>
        </section>

        <section className="mt-5">
          <div className="text-xs font-medium text-muted-foreground">Learning activity</div>
          <div className="mt-3 space-y-2">
            {adapterEvents.map((event) => (
              <div key={event} className="flex gap-2 text-xs text-muted-foreground">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary/55" />
                <span>{event}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-5">
          <div className="text-xs font-medium text-muted-foreground">Expert controls</div>
          <div className="mt-3 rounded-md border border-dashed border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
            Retrain, pause, rollback, and expert settings appear here after the training queue is implemented.
          </div>
        </section>
      </div>
    </aside>
  );
}
