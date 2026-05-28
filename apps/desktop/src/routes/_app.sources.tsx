import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type DragEvent } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { ClusterDot } from "@/components/ClusterChip";
import {
  createSourceFromPath,
  createSourceFromText,
  createSourceFromUrl,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  ClipboardPaste,
  File,
  FilePlus2,
  FolderPlus,
  Link2,
  FileText,
  Image,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";

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
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [textDialogOpen, setTextDialogOpen] = useState(false);
  const [linkDialogOpen, setLinkDialogOpen] = useState(false);
  const [textTitle, setTextTitle] = useState("Pasted note");
  const [textBody, setTextBody] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);

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

  async function handleAddText() {
    const text = textBody.trim();
    const title = textTitle.trim() || "Pasted note";
    if (!text) return;
    setSubmitting(true);
    if (!vault) {
      addSource({ title, type: "note", state: "indexed", preview: text });
      setTextDialogOpen(false);
      setSubmitting(false);
      return;
    }
    try {
      await createSourceFromText({
        vault_id: vault.id,
        title,
        text,
      });
      await refreshBackendSources();
      setTextBody("");
      setTextTitle("Pasted note");
      setTextDialogOpen(false);
      setIngestMessage(`Added "${title}" as a text source.`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddLink() {
    const url = linkUrl.trim();
    if (!url) return;
    setSubmitting(true);
    if (!vault) {
      addSource({ title: url, type: "link", state: "waiting", url });
      setLinkDialogOpen(false);
      setSubmitting(false);
      return;
    }
    try {
      setIngestMessage("Fetching link text...");
      await createSourceFromUrl({
        vault_id: vault.id,
        url,
      });
      await refreshBackendSources();
      setLinkUrl("");
      setLinkDialogOpen(false);
      setIngestMessage("Imported link text.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddFiles() {
    if (!vault || !window.cmlDesktop?.selectSourceFiles) {
      setIngestMessage("File picking is available in the desktop app after a vault is created.");
      return;
    }
    const paths = await window.cmlDesktop.selectSourceFiles();
    await importFilePaths(paths);
  }

  async function handleAddFolder() {
    if (!vault || !window.cmlDesktop?.selectSourceFolders || !window.cmlDesktop?.listSupportedFiles) {
      setIngestMessage("Folder import is available in the desktop app after a vault is created.");
      return;
    }
    const folders = await window.cmlDesktop.selectSourceFolders();
    const paths = await window.cmlDesktop.listSupportedFiles(folders);
    await importFilePaths(paths);
  }

  async function importFilePaths(paths: string[]) {
    if (!vault || paths.length === 0) return;
    setIngestMessage(`Importing ${paths.length} file${paths.length === 1 ? "" : "s"}...`);
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
    await refreshBackendSources();
    setIngestMessage(formatImportResult(imported, failures));
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
    const droppedPaths = window.cmlDesktop?.getDroppedFilePaths?.(event.dataTransfer.files) ?? [];
    const paths = window.cmlDesktop?.listSupportedFiles
      ? await window.cmlDesktop.listSupportedFiles(droppedPaths)
      : droppedPaths;
    if (paths.length === 0) {
      setIngestMessage("Drop import is available in the desktop app.");
      return;
    }
    await importFilePaths(paths);
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
    <div
      className="relative flex h-full flex-col"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => void handleDrop(event)}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-md border border-dashed border-primary bg-background/85 text-sm font-medium text-foreground">
          Drop documents to import them
        </div>
      )}
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
          onClick={() => void handleAddFiles()}
          disabled={!vault}
          title="Imports TXT, Markdown, DOCX, and PDF files in this build."
        >
          <FilePlus2 className="mr-1.5 h-4 w-4" /> Add files
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void handleAddFolder()}
          disabled={!vault}
          title="Imports supported documents from synced folders like Drive, Dropbox, OneDrive, or iCloud."
        >
          <FolderPlus className="mr-1.5 h-4 w-4" /> Add folder
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setTextDialogOpen(true)}
        >
          <ClipboardPaste className="mr-1.5 h-4 w-4" /> Paste text
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setLinkDialogOpen(true)}
        >
          <Plus className="mr-1.5 h-4 w-4" /> Add link
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="border-b border-border bg-destructive/5 px-6 py-2 text-xs text-destructive">
            Using local mock data because the backend could not be reached: {error}
          </div>
        )}
        {ingestMessage && (
          <div className="border-b border-border bg-card px-6 py-2 text-xs text-muted-foreground">
            {ingestMessage}
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
                    Tags
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {selected.tags.length > 0 ? (
                      selected.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground"
                        >
                          {tag}
                        </span>
                      ))
                    ) : (
                      <span className="text-muted-foreground">No tags yet.</span>
                    )}
                  </div>
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

      <Dialog open={textDialogOpen} onOpenChange={setTextDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Text</DialogTitle>
            <DialogDescription>
              Save pasted notes, chat excerpts, drafts, or copied text as a memory card.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={textTitle}
              onChange={(event) => setTextTitle(event.target.value)}
              placeholder="Source name"
            />
            <Textarea
              value={textBody}
              onChange={(event) => setTextBody(event.target.value)}
              placeholder="Paste text here"
              className="min-h-56 resize-none"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTextDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleAddText()} disabled={submitting || !textBody.trim()}>
              Save text
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={linkDialogOpen} onOpenChange={setLinkDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Link</DialogTitle>
            <DialogDescription>
              Fetch readable text from a web page and store it as a link memory card.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)}
            placeholder="https://example.com/article"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleAddLink()} disabled={submitting || !linkUrl.trim()}>
              Import link
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
    tags: record.tags ?? [],
    coverImageUrl: record.cover_image_url ?? undefined,
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
