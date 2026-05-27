import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { ClusterMap } from "@/components/ClusterMap";
import { Switch } from "@/components/ui/switch";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

function MapView() {
  const [showSources, setShowSources] = useState(true);
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="font-serif text-2xl">Map</h1>
        <p className="text-xs text-muted-foreground">
          Your context landscape. Click a cluster to inspect it.
        </p>
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={showSources} onCheckedChange={setShowSources} /> Show sources
        </label>
      </header>
      <div className="flex-1">
        <ClusterMap showSources={showSources} />
      </div>
    </div>
  );
}