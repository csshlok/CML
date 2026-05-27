import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  useStore,
  sourceStateLabel,
  type Cluster,
  type ClusterTint,
  type ExpertStatus,
  type Source,
  type SourceState,
  type SourceType,
} from "@/lib/mockStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ClusterDot } from "@/components/ClusterChip";
import {
  createSource as createBackendSource,
  deleteSource as deleteBackendSource,
  listClusters,
  listSources,
  listVaults,
  updateSource as updateBackendSource,
  type ClusterRecord,
  type SourceRecord,
  type VaultRecord,
} from "@/lib/backend";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { File, Link2, FileText, Image, Plus, RefreshCw, Trash2 } from "lucide-react";

export const Route = createFileRoute("/_app/sources")({
  head: () => ({ meta: [{ title: "Sources" }] }),
  component: SourcesView,
});

const typeIcon = {
  file: File,
  link: Link2,
  note: FileText,
  image: Image,
};

function SourcesView() {
  const {
    sources: mockSources,
    clusters: mockClusters,
    addSource,
    reindexSource,
    removeSource,
    setVault: setStoreVault,
  } = useStore();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Source | null>(null);
  const [vault, setActiveVault] = useState<VaultRecord | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refreshBackendSources() {
    setLoading(true);
    setError(null);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setActiveVault(activeVault);
      if (!activeVault) {
        setBackendSources([]);
        setBackendClusters([]);
        return;
      }
      setStoreVault(activeVault.path);
      const [sourceRows, clusterRows] = await Promise.all([
        listSources(activeVault.id),
        listClusters(activeVault.id),
      ]);
      setBackendSources(sourceRows.map(sourceFromRecord));
      setBackendClusters(clusterRows.map(clusterFromRecord));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load backend sources.");
      setActiveVault(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshBackendSources();
  }, []);

  const usingBackend = Boolean(vault);
  const sources = usingBackend ? backendSources : mockSources;
  const clusters = usingBackend ? backendClusters : mockClusters;

  const filtered = useMemo(() => sources.filter((s) =>
    s.title.toLowerCase().includes(q.toLowerCase()),
  ), [q, sources]);

  async function handleAddSource() {
    if (!vault) {
      addSource({ title: "Untitled note", type: "note", state: "waiting" });
      return;
    }
    await createBackendSource({
      vault_id: vault.id,
      title: "Untitled note",
      source_type: "note",
      raw_text: "",
    });
    await refreshBackendSources();
  }

  async function handleReindexSource(source: Source) {
    if (!usingBackend) {
      reindexSource(source.id);
      return;
    }
    await updateBackendSource(source.id, { state: "extracting" });
    await refreshBackendSources();
  }

  async function handleRemoveSource(source: Source) {
    if (!usingBackend) {
      removeSource(source.id);
      return;
    }
    await deleteBackendSource(source.id);
    if (selected?.id === source.id) setSelected(null);
    await refreshBackendSources();
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-6 py-4">
        <h1 className="font-serif text-2xl">Sources</h1>
        <Input
          placeholder="Search sources…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="ml-4 h-8 max-w-xs"
        />
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => void handleAddSource()}
        >
          <Plus className="mr-1.5 h-4 w-4" /> Add source
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="border-b border-border bg-destructive/5 px-6 py-2 text-xs text-destructive">
            Using local mock data because the backend could not be reached: {error}
          </div>
        )}
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading sources...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {vault ? "Drop files, links, screenshots, or notes to begin." : "Create a vault in Settings to store real sources."}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-6 py-2 font-normal">Title</th>
                <th className="px-3 py-2 font-normal">Type</th>
                <th className="px-3 py-2 font-normal">Cluster</th>
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-6 py-2 font-normal" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => {
                const Icon = typeIcon[s.type];
                const cluster = clusters.find((c) => c.id === s.clusterId);
                return (
                  <tr
                    key={s.id}
                    className="cursor-pointer border-b border-border hover:bg-accent/50"
                    onClick={() => setSelected(s)}
                  >
                    <td className="flex items-center gap-2 px-6 py-2.5">
                      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="truncate">{s.title}</span>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">{s.type}</td>
                    <td className="px-3 py-2.5">
                      {cluster ? (
                        <span className="inline-flex items-center gap-1.5">
                          <ClusterDot tint={cluster.tint} />
                          <span className="text-muted-foreground">{cluster.name}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <StateChip state={s.state} />
                    </td>
                    <td className="px-6 py-2.5 text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleReindexSource(s);
                        }}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleRemoveSource(s);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent className="w-[420px] sm:max-w-[420px]">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="font-serif">{selected.title}</SheetTitle>
              </SheetHeader>
              <div className="mt-4 space-y-4 text-sm">
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span>{selected.type}</span>
                  <span>·</span>
                  <StateChip state={selected.state} />
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Summary
                  </div>
                  <p className="mt-1">{selected.summary || "—"}</p>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Extracted text
                  </div>
                  <p className="mt-1 max-h-48 overflow-y-auto rounded-md border border-border bg-card p-3 text-xs leading-relaxed">
                    {selected.preview || "No preview available."}
                  </p>
                </div>
                {selected.state === "failed" && (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                    <div className="font-medium text-destructive">Extraction failed</div>
                    <p className="mt-1 text-muted-foreground">
                      We couldn't read this source. Try reindexing or open the file to check it.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => void handleReindexSource(selected)}>
                        Retry
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void handleRemoveSource(selected)}>
                        Remove
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function sourceFromRecord(record: SourceRecord): Source {
  return {
    id: record.id,
    title: record.title,
    type: normalizeSourceType(record.source_type),
    clusterId: record.cluster_id,
    state: normalizeSourceState(record.state),
    updatedAt: record.updated_at,
    preview: record.extracted_text || record.raw_text,
    summary: record.summary,
    tags: [],
    vaultPath: record.original_path ?? undefined,
    localPath: record.original_path ?? undefined,
    url: record.url ?? undefined,
  };
}

function clusterFromRecord(record: ClusterRecord): Cluster {
  return {
    id: record.id,
    name: record.name,
    tint: normalizeTint(record.color),
    description: record.description,
    expert: normalizeExpertStatus(record.expert_status),
    lastActive: record.updated_at,
    summary: record.description,
    styleProfile: "Style profile pending",
  };
}

function normalizeSourceType(value: string): SourceType {
  return value === "file" || value === "link" || value === "note" || value === "image"
    ? value
    : "file";
}

function normalizeSourceState(value: string): SourceState {
  return value === "waiting" ||
    value === "extracting" ||
    value === "indexed" ||
    value === "needs-review" ||
    value === "failed"
    ? value
    : "waiting";
}

function normalizeTint(value: string): ClusterTint {
  return value === "sage" ||
    value === "sand" ||
    value === "sky" ||
    value === "blush" ||
    value === "lavender" ||
    value === "terracotta"
    ? value
    : "sage";
}

function normalizeExpertStatus(value: string): ExpertStatus {
  return value === "setting-up" ||
    value === "learning" ||
    value === "ready" ||
    value === "needs-update" ||
    value === "paused" ||
    value === "issue"
    ? value
    : "setting-up";
}

function StateChip({ state }: { state: Source["state"] }) {
  const color =
    state === "indexed"
      ? "var(--status-ready)"
      : state === "failed"
      ? "var(--status-issue)"
      : "var(--status-learning)";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {sourceStateLabel[state]}
    </span>
  );
}
