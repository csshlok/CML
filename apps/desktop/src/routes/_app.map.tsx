import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { ClusterMap } from "@/components/ClusterMap";
import { Switch } from "@/components/ui/switch";
import { useStore } from "@/lib/mockStore";
import { ExpertBadge } from "@/components/ClusterChip";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

function MapView() {
  const [showSources, setShowSources] = useState(true);
  const { clusters, sources } = useStore();
  const indexed = sources.filter((source) => source.state === "indexed").length;
  const learning = clusters.filter((cluster) => cluster.expert === "learning").length;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-border bg-background/80 px-6 py-3">
        <div>
          <h1 className="font-serif text-2xl">Map</h1>
          <p className="text-xs text-muted-foreground">
            A navigable view of spaces, sources, and local expert activity.
          </p>
        </div>
        <div className="ml-4 hidden items-center gap-4 text-xs text-muted-foreground md:flex">
          <span>{clusters.length} clusters</span>
          <span>{indexed} indexed sources</span>
          <span>{learning} learning</span>
        </div>
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={showSources} onCheckedChange={setShowSources} /> Show sources
        </label>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_280px]">
        <ClusterMap showSources={showSources} />
        <aside className="hidden border-l border-border bg-card/45 p-4 lg:block">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Cluster health
          </div>
          <div className="mt-3 space-y-3">
            {clusters.map((cluster) => {
              const count = sources.filter((source) => source.clusterId === cluster.id).length;
              return (
                <div key={cluster.id} className="rounded-md border border-border bg-background/70 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="truncate text-sm font-medium">{cluster.name}</div>
                    <ExpertBadge status={cluster.expert} />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    {count} sources · {cluster.styleProfile || "Style profile pending"}
                  </div>
                </div>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}
