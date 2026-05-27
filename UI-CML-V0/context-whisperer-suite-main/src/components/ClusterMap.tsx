import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "@/lib/mockStore";
import { useNavigate } from "@tanstack/react-router";

type FGType = typeof import("react-force-graph-2d").default;

export function ClusterMap({
  showSources = true,
  focusClusterId,
}: {
  showSources?: boolean;
  focusClusterId?: string;
}) {
  const { clusters, sources } = useStore();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [FG, setFG] = useState<FGType | null>(null);

  useEffect(() => {
    let mounted = true;
    import("react-force-graph-2d").then((m) => {
      if (mounted) setFG(() => m.default);
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setSize({ w: e.contentRect.width, h: e.contentRect.height });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const graph = useMemo(() => {
    const filtered = focusClusterId
      ? clusters.filter((c) => c.id === focusClusterId)
      : clusters;
    const tintMap: Record<string, string> = {
      sage: "#b5cdb1",
      sand: "#e0d4ad",
      sky: "#b6d0e0",
      blush: "#e6c7c5",
      lavender: "#cfc6df",
      terracotta: "#d7a78a",
    };
    const nodes: any[] = filtered.map((c) => {
      const count = sources.filter((s) => s.clusterId === c.id).length;
      return {
        id: c.id,
        kind: "cluster",
        label: c.name,
        color: tintMap[c.tint],
        val: 6 + count * 2,
        learning: c.expert === "learning",
      };
    });
    const links: any[] = [];
    if (showSources) {
      for (const s of sources) {
        if (!s.clusterId) continue;
        if (focusClusterId && s.clusterId !== focusClusterId) continue;
        nodes.push({
          id: s.id,
          kind: "source",
          label: s.title,
          color: "#cfc7bd",
          val: 2,
        });
        links.push({ source: s.clusterId, target: s.id });
      }
    }
    // weak inter-cluster edges
    if (!focusClusterId) {
      for (let i = 0; i < filtered.length; i++) {
        for (let j = i + 1; j < filtered.length; j++) {
          links.push({
            source: filtered[i].id,
            target: filtered[j].id,
            weak: true,
          });
        }
      }
    }
    return { nodes, links };
  }, [clusters, sources, showSources, focusClusterId]);

  return (
    <div ref={containerRef} className="h-full w-full">
      {FG ? (
        <FG
          graphData={graph}
          width={size.w}
          height={size.h}
          backgroundColor="rgba(0,0,0,0)"
          nodeRelSize={4}
          linkColor={(l: any) => (l.weak ? "rgba(0,0,0,0.06)" : "rgba(0,0,0,0.15)")}
          linkWidth={(l: any) => (l.weak ? 0.5 : 1)}
          nodeCanvasObject={(node: any, ctx, scale) => {
            const r = Math.sqrt(node.val) * 3;
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = node.color;
            ctx.fill();
            if (node.learning) {
              ctx.beginPath();
              ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
              ctx.strokeStyle = "rgba(180,140,60,0.6)";
              ctx.lineWidth = 1;
              ctx.stroke();
            }
            if (node.kind === "cluster" || scale > 2.5) {
              ctx.fillStyle = "rgba(40,30,20,0.85)";
              ctx.font = `${Math.max(10, 11 / Math.max(1, scale * 0.3))}px ui-sans-serif, system-ui`;
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.fillText(node.label, node.x, node.y + r + 3);
            }
          }}
          onNodeClick={(node: any) => {
            if (node.kind === "cluster") {
              navigate({
                to: "/clusters/$clusterId",
                params: { clusterId: node.id },
              });
            }
          }}
        />
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
          Loading map…
        </div>
      )}
    </div>
  );
}