import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ComponentType, type DragEvent } from "react";
import {
  ArrowUpDown,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  Image,
  Link as LinkIcon,
  NotebookText,
  Plus,
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
import { Textarea } from "@/components/ui/textarea";
import {
  type Cluster,
  type Source,
  type SourceType,
} from "@/lib/mockStore";
import {
  createSourceFromPath,
  createSourceFromText,
  createSourceFromUrl,
  listClusters,
  listSources,
  listVaults,
  reindexVaultSearch,
  semanticSearch,
  updateSource,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord, sourceStateText } from "@/lib/recordAdapters";

type FilterType = "all" | "note" | "link" | "file" | "image" | "unclustered";
type SortMode = "newest" | "oldest" | "alphabetical";
type AddMode = "note" | "link" | null;

export const Route = createFileRoute("/_app/search")({
  head: () => ({ meta: [{ title: "Mind" }] }),
  component: MindView,
});

function MindView() {
  const [vault, setBackendVault] = useState<VaultRecord | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");
  const [sortMode, setSortMode] = useState<SortMode>("newest");
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [semanticRanks, setSemanticRanks] = useState<Map<string, number>>(new Map());

  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;

  async function loadVaultData() {
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      if (!activeVault) return;
      setBackendVault(activeVault);
      void reindexVaultSearch(activeVault.id).catch(() => undefined);
      const [clusterRows, sourceRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id),
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

  const visibleSources = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
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
  }, [backendReady, filter, query, semanticRanks, sortMode, sources]);

  const unclusteredCount = sources.filter((source) => !source.clusterId).length;
  const needsReviewCount = sources.filter((source) => source.state !== "indexed").length;

  async function addFiles() {
    if (!vault || !desktop?.selectSourceFiles) return;
    const paths = await desktop.selectSourceFiles();
    await importFilePaths(paths);
  }

  async function addFolder() {
    if (!vault || !desktop?.selectSourceFolders || !desktop?.listSupportedFiles) return;
    const folders = await desktop.selectSourceFolders();
    const paths = await desktop.listSupportedFiles(folders);
    await importFilePaths(paths);
  }

  async function importFilePaths(paths: string[]) {
    if (!vault || paths.length === 0) return;
    setImportMessage(`Importing ${paths.length} document${paths.length === 1 ? "" : "s"}...`);
    const failures: string[] = [];
    let imported = 0;
    for (const path of paths) {
      try {
        await createSourceFromPath({ vault_id: vault.id, path });
        imported += 1;
      } catch (error) {
        const reason = error instanceof Error ? error.message : "Import failed";
        failures.push(`${fileNameFromPath(path)}: ${reason}`);
      }
    }
    await loadVaultData();
    setImportMessage(formatImportResult(imported, failures));
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!vault || event.dataTransfer.types.includes("Files") === false) return;
    event.preventDefault();
    setDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragActive(false);
  }

  async function handleDrop(event: DragEvent<HTMLDivElement>) {
    if (!vault) return;
    event.preventDefault();
    setDragActive(false);
    const droppedPaths = desktop?.getDroppedFilePaths?.(event.dataTransfer.files) ?? [];
    const paths = desktop?.listSupportedFiles ? await desktop.listSupportedFiles(droppedPaths) : droppedPaths;
    await importFilePaths(paths);
  }

  async function submitNote() {
    if (!vault || !noteText.trim()) return;
    setSubmitting(true);
    try {
      await createSourceFromText({
        vault_id: vault.id,
        title: noteTitle.trim() || "Untitled note",
        text: noteText.trim(),
      });
      setNoteTitle("");
      setNoteText("");
      setAddMode(null);
      await loadVaultData();
    } finally {
      setSubmitting(false);
    }
  }

  async function submitLink() {
    if (!vault || !linkUrl.trim()) return;
    setSubmitting(true);
    try {
      await createSourceFromUrl({ vault_id: vault.id, url: linkUrl.trim() });
      setLinkUrl("");
      setAddMode(null);
      await loadVaultData();
    } finally {
      setSubmitting(false);
    }
  }

  async function updateCardImage(source: Source, coverImageUrl: string | null) {
    const updated = source.id.startsWith("source-")
      ? sourceFromRecord(await updateSource(source.id, { cover_image_url: coverImageUrl }))
      : { ...source, coverImageUrl: coverImageUrl ?? undefined };
    setSelectedSource(updated);
    setBackendSources((items) => items.map((item) => (item.id === source.id ? updated : item)));
    await loadVaultData();
  }

  return (
    <div
      className="relative grid h-full grid-cols-[minmax(0,1fr)_320px] overflow-hidden bg-background"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => void handleDrop(event)}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-md border border-dashed border-primary bg-background/85 text-sm font-medium text-foreground">
          Drop documents to add them to this vault
        </div>
      )}
      <main className="min-w-0 overflow-y-auto">
        <div className="border-b border-border bg-background px-6 py-5">
          <div className="flex items-start justify-between gap-6">
            <div>
              <h1 className="page-title">Mind</h1>
              <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
                Search saved sources, review unclustered items, and open the context you need.
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" className="gap-2" onClick={() => setAddMode("note")}>
                <NotebookText className="h-4 w-4" />
                Add note
              </Button>
              <Button variant="outline" className="gap-2" onClick={() => setAddMode("link")}>
                <LinkIcon className="h-4 w-4" />
                Add link
              </Button>
              <Button className="gap-2" onClick={addFiles} disabled={!vault || !desktop?.selectSourceFiles}>
                <Plus className="h-4 w-4" />
                Add file
              </Button>
              <Button variant="outline" className="gap-2" onClick={addFolder} disabled={!vault || !desktop?.selectSourceFolders}>
                <Folder className="h-4 w-4" />
                Add folder
              </Button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-[1fr_auto_auto]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoFocus
                aria-label="Search sources, tags, and summaries"
                placeholder="Search sources, tags, summaries..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-10 rounded-md pl-9"
              />
            </div>
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={filter}
              onChange={(event) => setFilter(event.target.value as FilterType)}
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
              onChange={(event) => setSortMode(event.target.value as SortMode)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="alphabetical">Alphabetical</option>
            </select>
          </div>
        </div>

        <div className="px-6 py-5">
          {importMessage && (
            <div className="mb-4 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
              {importMessage}
            </div>
          )}
          {!vault && (
            <div className="mb-4 rounded-md border border-border bg-card px-4 py-3 text-sm">
              <div className="font-medium">No active vault</div>
              <div className="mt-1 text-muted-foreground">
                Create or open a vault before adding files and using semantic search.
              </div>
              <Link to="/settings" className="mt-3 inline-block text-primary underline-offset-4 hover:underline">
                Open storage settings
              </Link>
            </div>
          )}
          <div className="mb-4 flex items-center justify-between text-sm">
            <div className="text-muted-foreground">
              {visibleSources.length} shown from {sources.length} sources
            </div>
            <Button variant="ghost" size="sm" className="gap-2" onClick={() => setSortMode(sortMode === "newest" ? "oldest" : "newest")}>
              <ArrowUpDown className="h-4 w-4" />
              {sortMode === "newest" ? "Newest first" : sortMode === "oldest" ? "Oldest first" : "Alphabetical"}
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {visibleSources.map((source) => {
              const cluster = clusters.find((item) => item.id === source.clusterId);
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

          {visibleSources.length === 0 && (
            <div className="rounded-md border border-dashed border-border bg-card p-8 text-sm">
              <div className="font-medium">No sources match this view</div>
              <div className="mt-1 text-muted-foreground">
                Adjust the search or filters, or add a source to this vault.
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                  Clear search
                </Button>
                <Button variant="outline" size="sm" onClick={() => setFilter("all")}>
                  Show all types
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>

      <aside className="hidden border-l border-border bg-card/55 p-5 lg:block">
        <h2 className="text-sm font-semibold">Current vault</h2>
        <div className="mt-4 space-y-2">
          <StateRow label="Sources" value={sources.length.toString()} />
          <StateRow label="Clusters" value={clusters.length.toString()} />
          <StateRow label="Unclustered" value={unclusteredCount.toString()} />
          <StateRow label="Needs review" value={needsReviewCount.toString()} />
        </div>

        <h2 className="mt-7 text-sm font-semibold">Clusters</h2>
        <div className="mt-3 space-y-2">
          {clusters.slice(0, 8).map((cluster) => {
            const count = sources.filter((source) => source.clusterId === cluster.id).length;
            return (
              <Link
                key={cluster.id}
                to="/clusters/$clusterId"
                params={{ clusterId: cluster.id }}
                className="block rounded-md border border-border bg-background px-3 py-2 text-sm hover:bg-accent"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate font-medium">{cluster.name}</span>
                  <span className="text-xs text-muted-foreground">{count}</span>
                </div>
              </Link>
            );
          })}
          {clusters.length === 0 && (
            <div className="rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
              Clusters will appear after sources are indexed.
            </div>
          )}
        </div>
      </aside>

      <SourceDetailDialog
        source={selectedSource}
        cluster={selectedSource ? clusters.find((item) => item.id === selectedSource.clusterId) : undefined}
        onOpenChange={(open) => !open && setSelectedSource(null)}
        onCoverImageChange={updateCardImage}
      />

      <Dialog open={addMode === "note"} onOpenChange={(open) => !open && setAddMode(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add note</DialogTitle>
            <DialogDescription>
              Save pasted or written text into the active local vault.
            </DialogDescription>
          </DialogHeader>
          <label className="grid gap-1 text-sm">
            Title
            <Input value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm">
            Text
            <Textarea className="min-h-40" value={noteText} onChange={(event) => setNoteText(event.target.value)} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAddMode(null)}>Cancel</Button>
            <Button onClick={submitNote} disabled={submitting || !noteText.trim()}>Add note</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={addMode === "link"} onOpenChange={(open) => !open && setAddMode(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add link</DialogTitle>
            <DialogDescription>
              Fetch a web page, extract readable content, and store it in the active vault.
            </DialogDescription>
          </DialogHeader>
          <label className="grid gap-1 text-sm">
            URL
            <Input placeholder="https://..." value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} />
          </label>
          <div className="rounded-md border border-border bg-muted/45 p-3 text-sm">
            Vault stores the readable text and queues it for indexing.
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAddMode(null)}>Cancel</Button>
            <Button onClick={submitLink} disabled={submitting || !linkUrl.trim()}>
              {submitting ? "Extracting..." : "Add link"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-background px-3 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
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
            {cluster && <span className="text-xs text-muted-foreground">{cluster.name}</span>}
            {source.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
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
  onCoverImageChange,
}: {
  source: Source | null;
  cluster?: Cluster;
  onOpenChange: (open: boolean) => void;
  onCoverImageChange: (source: Source, coverImageUrl: string | null) => Promise<void>;
}) {
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const [coverImageValue, setCoverImageValue] = useState("");

  useEffect(() => {
    setCoverImageValue(source?.coverImageUrl ?? "");
  }, [source?.id, source?.coverImageUrl]);

  if (!source) return null;
  const coverImageUrl = imageSrc(source.coverImageUrl);

  async function chooseLocalImage() {
    const selectedPath = await desktop?.selectCoverImage?.();
    if (!selectedPath || !source) return;
    setCoverImageValue(selectedPath);
    await onCoverImageChange(source, selectedPath);
  }

  async function saveImageUrl() {
    await onCoverImageChange(source, coverImageValue.trim() || null);
  }

  return (
    <Dialog open={Boolean(source)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{source.title}</DialogTitle>
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
          <div className="grid gap-2">
            <label className="text-sm font-medium" htmlFor="cover-image-url">Card image</label>
            <div className="flex gap-2">
              <Input
                id="cover-image-url"
                value={coverImageValue}
                onChange={(event) => setCoverImageValue(event.target.value)}
                placeholder="Image URL or local image path"
              />
              <Button variant="outline" onClick={saveImageUrl}>Save</Button>
              <Button variant="outline" onClick={chooseLocalImage} disabled={!desktop?.selectCoverImage}>
                Choose
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>{source.type}</span>
            <span>/</span>
            <span>{sourceStateText(source.state)}</span>
            {cluster && (
              <>
                <span>/</span>
                <Link to="/clusters/$clusterId" params={{ clusterId: cluster.id }} className="underline-offset-4 hover:underline">
                  {cluster.name}
                </Link>
              </>
            )}
          </div>
          <div className="rounded-md border border-border bg-muted/35 p-4 text-sm leading-6">
            {source.preview || source.summary || "No extracted preview is available yet."}
          </div>
          {source.tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {source.tags.map((tag) => (
                <span key={tag} className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
                  {tag}
                </span>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              className="gap-2"
              disabled={!source.coverImageUrl}
              onClick={() => source && void onCoverImageChange(source, null)}
            >
              <Image className="h-4 w-4" />
              Remove image
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
};

function imageSrc(value?: string) {
  if (!value) return undefined;
  if (/^https:\/\//i.test(value) || value.startsWith("data:") || value.startsWith("file://")) {
    return value;
  }
  return `file:///${value.replace(/\\/g, "/")}`;
}

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function formatImportResult(imported: number, failures: string[]) {
  const importedLabel = `Imported ${imported} document${imported === 1 ? "" : "s"}`;
  if (failures.length === 0) return `${importedLabel}.`;
  const firstFailure = failures[0];
  const more = failures.length > 1 ? ` and ${failures.length - 1} more` : "";
  return `${importedLabel}. Failed ${failures.length}: ${firstFailure}${more}.`;
}
