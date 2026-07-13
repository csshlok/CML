import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Network } from "lucide-react";
import { ClusterMap } from "@/components/ClusterMap";
import type { Cluster, Source } from "@/lib/domain";
import { listClusters, listSources, listVaults } from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";

export const Route = createFileRoute("/_app/map")({
  head: () => ({ meta: [{ title: "Map" }] }),
  component: MapView,
});

function MapView() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadMapData() {
      setLoading(true);
      setError(false);
      try {
        const vaults = await listVaults();
        const activeVault = vaults[0] ?? null;
        if (!activeVault) {
          if (!cancelled) {
            setClusters([]);
            setSources([]);
          }
          return;
        }
        const [clusterRows, sourceRows] = await Promise.all([
          listClusters(activeVault.id),
          listSources(activeVault.id),
        ]);
        if (cancelled) return;
        setClusters(clusterRows.map(clusterFromRecord));
        setSources(sourceRows.map(sourceFromRecord));
      } catch {
        if (!cancelled) {
          setClusters([]);
          setSources([]);
          setError(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadMapData();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="vault-page-wash h-full overflow-y-auto px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <h1 className="page-title">Knowledge map</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          Inspect how your clusters relate through shared language, media patterns, and source
          density.
        </p>
      </header>

      <section className="mt-6">
        {loading ? (
          <div className="grid h-[720px] place-items-center rounded-md border border-border bg-card">
            <div className="text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md border border-border bg-background">
                <Network className="h-5 w-5 text-muted-foreground" />
              </div>
              <div className="mt-4 text-sm font-medium text-foreground">Building the map</div>
              <div className="mt-1 text-sm text-muted-foreground">
                Loading clusters and sources from your active vault.
              </div>
            </div>
          </div>
        ) : error ? (
          <div className="grid min-h-[420px] place-items-center rounded-md border border-border bg-card px-6 text-center">
            <div className="max-w-md">
              <Network className="mx-auto h-5 w-5 text-muted-foreground" />
              <h2 className="mt-4 text-base font-semibold">Map unavailable</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Vault could not load your clusters and sources. Check Settings → Health, then reopen Map.
              </p>
            </div>
          </div>
        ) : (
          <ClusterMap clusters={clusters} sources={sources} />
        )}
      </section>
    </div>
  );
}
