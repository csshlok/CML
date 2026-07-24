import { createFileRoute, Link } from "@tanstack/react-router";
import { useDeferredValue, useEffect, useMemo, useState, type ComponentType } from "react";
import {
  ArrowUpDown,
  Clapperboard,
  ExternalLink,
  FileCode2,
  FileText,
  FolderOpen,
  Image,
  Link as LinkIcon,
  Mic,
  NotebookText,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  type Cluster,
  type Source,
  type SourceType,
} from "@/lib/domain";
import {
  getSource,
  listClusters,
  listSources,
  listVaults,
  semanticSearch,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord, sourceStateText } from "@/lib/recordAdapters";

type FilterType = "all" | "note" | "link" | "file" | "image" | "unclustered";
type SortMode = "newest" | "oldest" | "alphabetical";
const PAGE_SIZE = 50;

export const Route = createFileRoute("/_app/search")({
  head: () => ({ meta: [{ title: "Search" }] }),
  component: SearchView,
});

function SearchView() {
  const [vault, setBackendVault] = useState<VaultRecord | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");
  const [sortMode, setSortMode] = useState<SortMode>("newest");
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [semanticRanks, setSemanticRanks] = useState<Map<string, number>>(new Map());
  const [page, setPage] = useState(1);

  async function loadVaultData() {
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      if (!activeVault) return;
      setBackendVault(activeVault);
      const [clusterRows, sourceRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id, { limit: 100 }),
      ]);
      setBackendClusters(clusterRows.map(clusterFromRecord));
      setBackendSources(sourceRows.map(sourceFromRecord));
      setBackendReady(true);
    } catch {
      setBackendReady(false);
    }
  }

  useEffect(() => {
    setMounted(true);
    void loadVaultData();
  }, []);

  useEffect(() => {
    if (query.length === 0) void loadVaultData();
  }, [query]);

  useEffect(() => {
    if (!vault || !backendReady || query.trim().length < 3) {
      setSemanticRanks(new Map());
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        const response = await semanticSearch({
          vault_id: vault.id,
          query: query.trim(),
          limit: 24,
        });
        if (cancelled) return;
        const ranks = new Map<string, number>();
        for (const result of response.results) {
          const current = ranks.get(result.source_id) ?? 0;
          ranks.set(result.source_id, Math.max(current, result.score));
        }
        const resultSources = await Promise.all(
          Array.from(new Set(response.results.map((result) => result.source_id)))
            .slice(0, 50)
            .map((sourceId) => getSource(sourceId).catch(() => null)),
        );
        if (cancelled) return;
        setBackendSources(
          resultSources
            .filter((item): item is NonNullable<typeof item> => item !== null)
            .map(sourceFromRecord),
        );
        setSemanticRanks(ranks);
      } catch {
        if (!cancelled) setSemanticRanks(new Map());
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [backendReady, query, vault]);

  const sources = !mounted ? [] : backendReady ? backendSources : [];
  const clusters = !mounted ? [] : backendReady ? backendClusters : [];
  const deferredQuery = useDeferredValue(query);
  const clusterById = useMemo(() => new Map(clusters.map((cluster) => [cluster.id, cluster])), [clusters]);

  const visibleSources = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    const semanticActive = backendReady && normalizedQuery.length >= 3 && semanticRanks.size > 0;
    return sources
      .filter((source) => {
        if (filter === "unclustered" && source.clusterId) return false;
        if (filter !== "all" && filter !== "unclustered" && source.type !== filter) return false;
        if (semanticActive) return semanticRanks.has(source.id);
        if (!normalizedQuery) return true;
        return `${source.title} ${source.preview} ${source.summary} ${source.tags.join(" ")}`
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .sort((a, b) => {
        if (semanticActive) {
          return (semanticRanks.get(b.id) ?? 0) - (semanticRanks.get(a.id) ?? 0);
        }
        if (sortMode === "alphabetical") return a.title.localeCompare(b.title);
        const dateA = new Date(a.updatedAt).getTime();
        const dateB = new Date(b.updatedAt).getTime();
        return sortMode === "newest" ? dateB - dateA : dateA - dateB;
      });
  }, [backendReady, deferredQuery, filter, semanticRanks, sortMode, sources]);

  const totalPages = Math.max(1, Math.ceil(visibleSources.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageSources = visibleSources.slice(pageStart, pageStart + PAGE_SIZE);

  return (
    <div className="relative h-full overflow-y-auto bg-background">
      <main className="min-w-0 xl:overflow-y-auto">
        <div className="border-b border-border bg-background px-4 py-5 sm:px-6">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <h1 className="page-title">Search</h1>
              <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
                Search saved sources, review unclustered items, and open the context you need.
              </p>
            </div>
            <Button variant="outline" asChild>
              <Link to="/sources">Manage sources</Link>
            </Button>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div className="relative min-w-0">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoFocus
                aria-label="Search sources, tags, and summaries"
                placeholder="Search sources, tags, summaries..."
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                className="h-10 rounded-md pl-9"
              />
            </div>
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={filter}
              onChange={(event) => {
                setFilter(event.target.value as FilterType);
                setPage(1);
              }}
              aria-label="Filter sources by type"
            >
              <option value="all">All types</option>
              <option value="note">Notes</option>
              <option value="link">Links</option>
              <option value="file">Files</option>
              <option value="image">Images</option>
              <option value="unclustered">Unclustered</option>
            </select>
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={sortMode}
              onChange={(event) => {
                setSortMode(event.target.value as SortMode);
                setPage(1);
              }}
              aria-label="Sort sources"
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="alphabetical">Alphabetical</option>
            </select>
          </div>
        </div>

        <div className="px-4 py-5 sm:px-6">
          {!vault && (
            <div className="mb-4 rounded-md border border-border bg-card px-4 py-3 text-sm">
              <div className="font-medium">No active library</div>
              <div className="mt-1 text-muted-foreground">
                Create or open a library before adding files and using semantic search.
              </div>
              <Link to="/settings" className="mt-3 inline-block text-primary underline-offset-4 hover:underline">
                Open storage settings
              </Link>
            </div>
          )}
          <div className="mb-4 flex flex-col gap-2 text-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="text-muted-foreground">
              {visibleSources.length === 0
                ? `0 shown from ${sources.length} sources`
                : `${pageStart + 1}-${Math.min(pageStart + PAGE_SIZE, visibleSources.length)} of ${visibleSources.length} shown from ${sources.length} sources`}
            </div>
            <Button variant="ghost" size="sm" className="gap-2" onClick={() => {
              setSortMode(sortMode === "newest" ? "oldest" : "newest");
              setPage(1);
            }}>
              <ArrowUpDown className="h-4 w-4" />
              {sortMode === "newest" ? "Newest first" : sortMode === "oldest" ? "Oldest first" : "Alphabetical"}
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {pageSources.map((source) => {
              const cluster = source.clusterId ? clusterById.get(source.clusterId) : undefined;
              return (
                <MemoryCard
                  key={source.id}
                  source={source}
                  cluster={cluster}
                  onOpen={() => setSelectedSource(source)}
                />
              );
            })}
          </div>

          {visibleSources.length > PAGE_SIZE && (
            <nav className="mt-5 flex items-center justify-between border-t border-border pt-4" aria-label="Search results pages">
              <Button variant="outline" size="sm" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">Page {currentPage} of {totalPages}</span>
              <Button variant="outline" size="sm" disabled={currentPage === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
                Next
              </Button>
            </nav>
          )}

          {visibleSources.length === 0 && (
            <div className="rounded-md border border-dashed border-border bg-card p-8 text-sm">
              <div className="font-medium">No sources match this view</div>
              <div className="mt-1 text-muted-foreground">
                Adjust the search or filters, or add a source to this library.
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => {
                  setQuery("");
                  setPage(1);
                }}>
                  Clear search
                </Button>
                <Button variant="outline" size="sm" onClick={() => {
                  setFilter("all");
                  setPage(1);
                }}>
                  Show all types
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>

      <SourceDetailDialog
        source={selectedSource}
        cluster={selectedSource?.clusterId ? clusterById.get(selectedSource.clusterId) : undefined}
        onOpenChange={(open) => !open && setSelectedSource(null)}
      />
    </div>
  );
}

function MemoryCard({
  source,
  cluster,
  onOpen,
}: {
  source: Source;
  cluster?: Cluster;
  onOpen: () => void;
}) {
  const Icon = sourceIcon[source.type] ?? FileText;
  const coverImageUrl = imageSrc(source.coverImageUrl);

  return (
    <button
      className="overflow-hidden rounded-md border border-border bg-card text-left transition-colors hover:bg-accent/50"
      onClick={onOpen}
      type="button"
    >
      {coverImageUrl && (
        <div className="h-28 border-b border-border bg-muted">
          <img src={coverImageUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
        </div>
      )}
      <div className="flex items-start gap-3 p-4">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <h2 className="truncate text-sm font-semibold">{source.title}</h2>
            <span className="shrink-0 text-xs text-muted-foreground">{sourceStateText(source.state)}</span>
          </div>
          <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">
            {source.summary || source.preview || "Preview will appear after extraction."}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {cluster && <span className="min-w-0 max-w-full truncate text-xs text-muted-foreground">{cluster.name}</span>}
            {source.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="max-w-full truncate rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}

function SourceDetailDialog({
  source,
  cluster,
  onOpenChange,
}: {
  source: Source | null;
  cluster?: Cluster;
  onOpenChange: (open: boolean) => void;
}) {
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;

  if (!source) return null;
  const coverImageUrl = imageSrc(source.coverImageUrl);

  return (
    <Dialog open={Boolean(source)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="break-words">{source.title}</DialogTitle>
          <DialogDescription>
            Inspect the extracted source preview, tags, cluster assignment, and available open actions.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="overflow-hidden rounded-md border border-border bg-muted">
            {coverImageUrl ? (
              <img src={coverImageUrl} alt="" className="h-44 w-full object-cover" />
            ) : (
              <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">
                No card image selected.
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>{source.type}</span>
            <span>/</span>
            <span>{sourceStateText(source.state)}</span>
            {cluster && (
              <>
                <span>/</span>
                <Link to="/clusters/$clusterId" params={{ clusterId: cluster.id }} className="break-words underline-offset-4 hover:underline">
                  {cluster.name}
                </Link>
              </>
            )}
          </div>
          <div className="break-words rounded-md border border-border bg-muted/35 p-4 text-sm leading-6">
            {source.preview || source.summary || "No extracted preview is available yet."}
          </div>
          {source.tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {source.tags.map((tag) => (
                <span key={tag} className="max-w-full break-words rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
                  {tag}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" className="gap-2" asChild>
              <Link to="/sources" search={{ source: source.id }}>Open in Sources</Link>
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              disabled={!source.localPath || !desktop?.showItemInFolder}
              onClick={() => source.localPath && void desktop?.showItemInFolder(source.localPath)}
            >
              <FolderOpen className="h-4 w-4" />
              Reveal file
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              disabled={!source.url}
              onClick={() => source.url && window.open(source.url, "_blank", "noopener,noreferrer")}
            >
              <ExternalLink className="h-4 w-4" />
              Open link
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const sourceIcon: Record<SourceType, ComponentType<{ className?: string }>> = {
  file: FileText,
  link: LinkIcon,
  note: NotebookText,
  image: Image,
  audio: Mic,
  video: Clapperboard,
  code: FileCode2,
  external_transcript: Mic,
  external_artifact: FileText,
};

function imageSrc(value?: string) {
  if (!value) return undefined;
  if (/^https:\/\//i.test(value) || value.startsWith("data:") || value.startsWith("file://")) {
    return value;
  }
  return `file:///${value.replace(/\\/g, "/")}`;
}

