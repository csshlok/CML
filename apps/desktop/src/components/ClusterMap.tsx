import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ExternalLink,
  FolderOpen,
  RotateCcw,
  Settings2,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ExpertBadge } from "@/components/ClusterChip";
import { expertLabel, useStore, type Cluster, type Source } from "@/lib/mockStore";

type Point = { x: number; y: number };

type ClusterPoint = {
  cluster: Cluster;
  count: number;
  point: Point;
  radius: number;
};

type DataPoint = {
  source: Source;
  clusterId: string;
  point: Point;
  radius: number;
};

const tintHex: Record<Cluster["tint"], string> = {
  sage: "#7f9f79",
  sand: "#b8a86f",
  sky: "#759ab0",
  blush: "#b78986",
  lavender: "#9282aa",
  terracotta: "#b17758",
};

const positions = [
  { x: 0.5, y: 0.28 },
  { x: 0.72, y: 0.62 },
  { x: 0.28, y: 0.62 },
  { x: 0.22, y: 0.34 },
  { x: 0.78, y: 0.34 },
  { x: 0.5, y: 0.76 },
] as const;

export function ClusterMap({
  showSources = true,
  focusClusterId,
}: {
  showSources?: boolean;
  focusClusterId?: string;
}) {
  const { clusters, sources } = useStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 600 });
  const [mounted, setMounted] = useState(false);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(focusClusterId ?? null);

  useEffect(() => {
    setMounted(true);
    if (!containerRef.current) return;
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    const visibleClusters = selectedClusterId
      ? clusters.filter((cluster) => cluster.id === selectedClusterId)
      : clusters;

    const marginX = Math.max(96, size.w * 0.1);
    const marginY = Math.max(82, size.h * 0.12);
    const usableW = Math.max(320, size.w - marginX * 2);
    const usableH = Math.max(260, size.h - marginY * 2);

    const clusterPoints: ClusterPoint[] = visibleClusters.map((cluster, index) => {
      const count = sources.filter((source) => source.clusterId === cluster.id).length;
      const pos = visibleClusters.length === 1 ? { x: 0.5, y: 0.5 } : positions[index % positions.length];
      return {
        cluster,
        count,
        point: {
          x: marginX + pos.x * usableW,
          y: marginY + pos.y * usableH,
        },
        radius: 8 + Math.min(16, Math.sqrt(Math.max(1, count)) * 5),
      };
    });

    const dataPoints: DataPoint[] = [];
    if (showSources) {
      for (const clusterPoint of clusterPoints) {
        const clusterSources = sources
          .filter((source) => source.clusterId === clusterPoint.cluster.id)
          .slice(0, 12);
        const feedDistance = 54 + clusterPoint.radius * 1.2;
        const arcStart = clusterPoint.point.x < size.w / 2 ? -0.55 : Math.PI - 0.55;
        const spread = Math.min(Math.PI * 1.2, 0.42 * Math.max(2, clusterSources.length));

        clusterSources.forEach((source, index) => {
          const centeredIndex = index - (clusterSources.length - 1) / 2;
          const angle = arcStart + centeredIndex * (spread / Math.max(1, clusterSources.length - 1));
          const stagger = 1 + (index % 3) * 0.16;
          dataPoints.push({
            source,
            clusterId: clusterPoint.cluster.id,
            radius: source.state === "indexed" ? 4 : 3,
            point: {
              x: clusterPoint.point.x + Math.cos(angle) * feedDistance * stagger,
              y: clusterPoint.point.y + Math.sin(angle) * feedDistance * 0.82 * stagger,
            },
          });
        });
      }
    }

    return { clusterPoints, dataPoints };
  }, [clusters, selectedClusterId, showSources, size.h, size.w, sources]);

  const selectedCluster = selectedClusterId
    ? clusters.find((cluster) => cluster.id === selectedClusterId) ?? null
    : null;
  const selectedSources = selectedCluster
    ? sources.filter((source) => source.clusterId === selectedCluster.id)
    : [];

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-[#fbfaf7]">
      {!mounted ? null : (
        <>
      <svg className="absolute inset-0 h-full w-full" role="presentation">
        <defs>
          <pattern id="atlas-grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M32 0H0V32" fill="none" stroke="rgba(74,66,56,0.045)" />
          </pattern>
          <radialGradient id="cluster-halo">
            <stop offset="0%" stopColor="rgba(255,255,255,0.92)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0)" />
          </radialGradient>
        </defs>

        <rect width="100%" height="100%" fill="url(#atlas-grid)" />
        <g opacity="0.42">
          {layout.clusterPoints.map((a, index) =>
            layout.clusterPoints.slice(index + 1).map((b) => {
              const strength = similarityStrength(a, b);
              return (
                <path
                  key={`${a.cluster.id}-${b.cluster.id}`}
                  d={arcPath(a.point, b.point)}
                  fill="none"
                  stroke="rgba(67,59,50,0.42)"
                  strokeDasharray={strength > 0.7 ? "none" : "4 7"}
                  strokeLinecap="round"
                  strokeWidth={0.65 + strength * 1.2}
                />
              );
            }),
          )}
        </g>

        {layout.dataPoints.map((dataPoint) => {
          const clusterPoint = layout.clusterPoints.find(
            (point) => point.cluster.id === dataPoint.clusterId,
          );
          if (!clusterPoint) return null;
          return (
            <line
              key={`${dataPoint.clusterId}-${dataPoint.source.id}`}
              x1={dataPoint.point.x}
              y1={dataPoint.point.y}
              x2={clusterPoint.point.x}
              y2={clusterPoint.point.y}
              stroke="rgba(67,59,50,0.18)"
              strokeWidth="0.8"
            />
          );
        })}

        {layout.clusterPoints.map((point) => (
          <circle
            key={`${point.cluster.id}-halo`}
            cx={point.point.x}
            cy={point.point.y}
            r={point.radius + 34}
            fill="url(#cluster-halo)"
          />
        ))}
      </svg>

      {layout.dataPoints.map((dataPoint) => {
        const clusterPoint = layout.clusterPoints.find(
          (point) => point.cluster.id === dataPoint.clusterId,
        );
        return (
          <div
            key={dataPoint.source.id}
            className="group absolute z-[5] -translate-x-1/2 -translate-y-1/2"
            style={{
              left: dataPoint.point.x,
              top: dataPoint.point.y,
            }}
          >
            <button
              className="rounded-full border border-background shadow-[0_3px_10px_rgba(45,39,33,0.16)] transition group-hover:scale-150"
              style={{
              width: dataPoint.radius * 2 + 3,
              height: dataPoint.radius * 2 + 3,
              background: clusterPoint ? tintHex[clusterPoint.cluster.tint] : "#9a9288",
            }}
              aria-label={dataPoint.source.title}
            />
            <SourcePreview source={dataPoint.source} />
          </div>
        );
      })}

      {layout.clusterPoints.map((clusterPoint) => (
        <button
          key={clusterPoint.cluster.id}
          className="absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/90 bg-background text-left shadow-[0_10px_30px_rgba(45,39,33,0.16)] transition hover:scale-[1.04]"
          style={{
            left: clusterPoint.point.x,
            top: clusterPoint.point.y,
            width: clusterPoint.radius * 2,
            height: clusterPoint.radius * 2,
            background: tintHex[clusterPoint.cluster.tint],
            boxShadow:
              clusterPoint.cluster.expert === "learning"
                ? `0 0 0 8px color-mix(in oklab, ${tintHex[clusterPoint.cluster.tint]} 22%, transparent), 0 14px 34px rgba(45,39,33,0.16)`
                : undefined,
          }}
          onClick={() => setSelectedClusterId(clusterPoint.cluster.id)}
          aria-label={`Open ${clusterPoint.cluster.name}`}
        />
      ))}

      {layout.clusterPoints.map((clusterPoint) => (
        <div
          key={`${clusterPoint.cluster.id}-label`}
          className="pointer-events-none absolute z-10 -translate-x-1/2"
          style={{
            left: clusterPoint.point.x,
            top: clusterPoint.point.y + clusterPoint.radius + 10,
            width: 180,
          }}
        >
          <div className="truncate text-center text-sm font-medium text-foreground">
            {clusterPoint.cluster.name}
          </div>
          <div className="mt-0.5 text-center text-[11px] text-muted-foreground">
            {clusterPoint.count} sources
          </div>
        </div>
      ))}

      <div className="pointer-events-none absolute left-5 top-5 max-w-72 rounded-md border border-border/70 bg-background/75 px-3 py-2 text-xs text-muted-foreground shadow-sm backdrop-blur">
        {selectedCluster ? (
          <>
            <div className="font-medium text-foreground">{selectedCluster.name}</div>
            <div className="mt-0.5">
              Cluster detail view. Connected data points and adapter state are shown here.
            </div>
          </>
        ) : (
          <>
            <div className="font-medium text-foreground">Context atlas</div>
            <div className="mt-0.5">
              Larger anchors hold more material. Fine lines show data feeding each cluster and
              similarity between clusters.
            </div>
          </>
        )}
      </div>
      {selectedCluster && (
        <ClusterDetailOverlay
          cluster={selectedCluster}
          sources={selectedSources}
          onBack={() => setSelectedClusterId(null)}
        />
      )}
        </>
      )}
    </div>
  );
}

function SourcePreview({ source }: { source: Source }) {
  const canOpenLink = Boolean(source.url);
  const canOpenLocalPath = Boolean(source.localPath && window.cmlDesktop?.openPath);
  const canRevealLocalPath = Boolean(source.localPath && window.cmlDesktop?.showItemInFolder);

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-30 hidden w-72 rounded-md border border-border bg-background/95 p-3 text-left shadow-[0_18px_55px_rgba(45,39,33,0.18)] backdrop-blur group-hover:block">
      <div className="truncate text-sm font-medium text-foreground">{source.title}</div>
      <div className="mt-1 text-[11px] uppercase tracking-wider text-muted-foreground">
        {source.type} · {source.state}
      </div>
      <p className="mt-2 line-clamp-4 text-xs leading-5 text-muted-foreground">
        {source.preview || source.summary || "Preview will appear after extraction."}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground disabled:opacity-45"
          disabled={!canOpenLocalPath}
          onClick={(event) => {
            event.stopPropagation();
            if (source.localPath) void window.cmlDesktop?.openPath(source.localPath);
          }}
          title={
            canOpenLocalPath
              ? source.vaultPath ?? "Open source from the vault."
              : "Available in the desktop app after this source has a vault file path."
          }
          type="button"
        >
          <FolderOpen className="h-3 w-3" />
          Vault
        </button>
        <button
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground disabled:opacity-45"
          disabled={!canOpenLink && !canRevealLocalPath}
          onClick={(event) => {
            event.stopPropagation();
            if (canOpenLink && source.url) {
              window.open(source.url, "_blank", "noopener,noreferrer");
              return;
            }
            if (source.localPath) void window.cmlDesktop?.showItemInFolder(source.localPath);
          }}
          title={
            canOpenLink
              ? "Open source link."
              : canRevealLocalPath
                ? "Reveal this source in Explorer."
                : "Available in the desktop app after this source has a local file path."
          }
          type="button"
        >
          <ExternalLink className="h-3 w-3" />
          {source.type === "link" ? "Open link" : "Explorer"}
        </button>
      </div>
    </div>
  );
}

function ClusterDetailOverlay({
  cluster,
  sources,
  onBack,
}: {
  cluster: Cluster;
  sources: Source[];
  onBack: () => void;
}) {
  const indexedCount = sources.filter((source) => source.state === "indexed").length;
  const adapterEvents = [
    "Created cluster expert record",
    "Built initial style profile",
    indexedCount > 0 ? `Indexed ${indexedCount} sources for retrieval` : "Waiting for indexed sources",
    cluster.expert === "learning" ? "Adapter learning pass in progress" : "Adapter ready for next update",
  ];

  return (
    <aside className="absolute bottom-5 right-5 top-5 z-30 w-[360px] overflow-hidden rounded-md border border-border bg-background/95 shadow-[0_24px_80px_rgba(45,39,33,0.2)] backdrop-blur">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{cluster.name}</div>
          <div className="text-xs text-muted-foreground">{sources.length} connected data points</div>
        </div>
      </div>

      <div className="h-[calc(100%-57px)] overflow-y-auto p-4">
        <section>
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Adapter
            </div>
            <ExpertBadge status={cluster.expert} />
          </div>
          <div className="mt-3 rounded-md border border-border bg-card p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Zap className="h-4 w-4 text-muted-foreground" />
              {expertLabel[cluster.expert]}
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              The local expert is using this cluster's style profile, indexed source memory,
              and accepted interactions. Fine-tuning artifacts will appear here once training is
              wired.
            </p>
          </div>
        </section>

        <section className="mt-5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Learning activity
          </div>
          <div className="mt-3 space-y-2">
            {adapterEvents.map((event, index) => (
              <div key={event} className="flex gap-2 text-xs text-muted-foreground">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-foreground/35" />
                <span>{event}</span>
                {index === adapterEvents.length - 1 && (
                  <span className="ml-auto text-[10px] uppercase tracking-wider">latest</span>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="mt-5">
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Connected data
            </div>
            <span className="text-xs text-muted-foreground">{indexedCount} indexed</span>
          </div>
          <div className="mt-3 space-y-2">
            {sources.map((source) => (
              <div key={source.id} className="rounded-md border border-border bg-card p-3">
                <div className="truncate text-sm font-medium">{source.title}</div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {source.preview || source.summary || "Preview pending."}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" disabled>
                    <FolderOpen className="h-3 w-3" />
                    Vault
                  </Button>
                  <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" disabled>
                    <ExternalLink className="h-3 w-3" />
                    Explorer
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Actions
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="outline" size="sm" className="gap-1" disabled>
              <RotateCcw className="h-3.5 w-3.5" />
              Retrain
            </Button>
            <Button variant="outline" size="sm" className="gap-1" disabled>
              <Settings2 className="h-3.5 w-3.5" />
              Expert settings
            </Button>
          </div>
        </section>
      </div>
    </aside>
  );
}

function similarityStrength(a: ClusterPoint, b: ClusterPoint) {
  const sharedWords = new Set(
    `${a.cluster.name} ${a.cluster.description} ${a.cluster.summary}`
      .toLowerCase()
      .split(/\W+/)
      .filter(Boolean),
  );
  const bWords = `${b.cluster.name} ${b.cluster.description} ${b.cluster.summary}`
    .toLowerCase()
    .split(/\W+/)
    .filter(Boolean);
  const overlap = bWords.filter((word) => sharedWords.has(word)).length;
  const sizeSimilarity = 1 - Math.min(1, Math.abs(a.count - b.count) / Math.max(1, a.count + b.count));
  return Math.min(1, 0.25 + overlap * 0.14 + sizeSimilarity * 0.35);
}

function arcPath(a: Point, b: Point) {
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const control = {
    x: mid.x - dy * 0.08,
    y: mid.y + dx * 0.08,
  };
  return `M ${a.x} ${a.y} Q ${control.x} ${control.y} ${b.x} ${b.y}`;
}
