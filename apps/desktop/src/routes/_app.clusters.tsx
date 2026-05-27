import { createFileRoute, Link } from "@tanstack/react-router";
import { useStore } from "@/lib/mockStore";
import { ClusterDot, ExpertBadge } from "@/components/ClusterChip";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

export const Route = createFileRoute("/_app/clusters")({
  head: () => ({ meta: [{ title: "Clusters" }] }),
  component: ClustersList,
});

function ClustersList() {
  const { clusters, sources, addCluster } = useStore();
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-8 py-10">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="font-serif text-3xl">Clusters</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Spaces of context that inform your chats.
            </p>
          </div>
          <Button onClick={() => addCluster({ name: "New cluster" })}>
            <Plus className="mr-1.5 h-4 w-4" /> New cluster
          </Button>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.map((c) => {
            const count = sources.filter((s) => s.clusterId === c.id).length;
            return (
              <Link
                key={c.id}
                to="/clusters/$clusterId"
                params={{ clusterId: c.id }}
                className="group rounded-md border border-border bg-card p-4 transition-colors hover:bg-accent"
              >
                <div className="flex items-center gap-2">
                  <ClusterDot tint={c.tint} />
                  <span className="font-medium">{c.name}</span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                  {c.summary || c.description}
                </p>
                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{count} sources</span>
                  <ExpertBadge status={c.expert} />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}