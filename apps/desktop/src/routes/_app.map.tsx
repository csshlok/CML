import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { Button } from "@/components/ui/button";
import { KnowledgeMap } from "@/components/KnowledgeMap";
import { DegradedState, EmptyState, SkeletonRegion } from "@/components/product/Feedback";
import {
  getMapOverview,
  listVaults,
  type MapGraphResponse,
  type VaultRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

function MapView() {
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [overview, setOverview] = useState<MapGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const activeVault = (await listVaults())[0] ?? null;
      setVault(activeVault);
      setOverview(activeVault ? await getMapOverview(activeVault.id, { limit: 160 }) : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Vault could not load the map.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="vault-page-wash h-full overflow-y-auto px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Knowledge map</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Explore clusters, source episodes, and facts that Vault can trace back to your local
            material. The map never invents connections from word overlap.
          </p>
        </div>
        {overview?.truncated ? (
          <span className="text-xs text-muted-foreground">
            Showing {overview.nodes.length} of {overview.total?.toLocaleString()} clusters
          </span>
        ) : null}
      </header>

      <section className="mt-6">
        {loading ? (
          <div className="min-h-[620px] rounded-md border border-border bg-card p-6">
            <SkeletonRegion lines={10} />
          </div>
        ) : error ? (
          <DegradedState description={error} onRetry={() => void load()} action={
            <Button size="sm" variant="outline" asChild>
              <Link to="/settings" search={{ section: "health" }}>Open Health</Link>
            </Button>
          } />
        ) : !vault ? (
          <EmptyState
            icon={<Network className="h-7 w-7" />}
            title="Open a library to build its map"
            description="A map is a view over one local library. Choose a folder before exploring relationships."
            action={<Button asChild><Link to="/settings" search={{ section: "storage" }}>Choose library</Link></Button>}
          />
        ) : !overview || overview.nodes.length === 0 ? (
          <EmptyState
            icon={<Network className="h-7 w-7" />}
            title="Your map starts with a cluster"
            description="Create a named cluster and add sources. Vault will show only relationships it can explain and trace."
            action={<Button asChild><Link to="/clusters">Create a cluster</Link></Button>}
          />
        ) : (
          <KnowledgeMap vaultId={vault.id} overview={overview} onReload={() => void load()} />
        )}
      </section>
    </div>
  );
}
