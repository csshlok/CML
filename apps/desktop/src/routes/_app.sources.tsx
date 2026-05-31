import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import {
  CheckCircle2,
  ClipboardPaste,
  ExternalLink,
  File,
  FilePlus2,
  FileText,
  FolderPlus,
  Image,
  Link2,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ClusterDot } from "@/components/ClusterChip";
import {
  sourceStateLabel,
  useStore,
  type Cluster,
  type Source,
} from "@/lib/mockStore";
import {
  createSourceFromPath,
  createSourceFromText,
  createSourceFromUrl,
  deleteSource as deleteBackendSource,
  listClusters,
  listSourcePages,
  listSources,
  listVaults,
  updateSource as updateBackendSource,
  type SourcePageRecord,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export const Route = createFileRoute("/_app/sources")({
  head: () => ({ meta: [{ title: "Sources" }] }),
  component: SourcesView,
});

const typeIcon = {
  file: FileText,
  link: Link2,
  note: File,
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
  const [selectedPages, setSelectedPages] = useState<SourcePageRecord[]>([]);
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
      const mappedSources = sourceRows.map(sourceFromRecord);
      setBackendSources(mappedSources);
      setBackendClusters(clusterRows.map(clusterFromRecord));
      setSelected((current) => current ?? mappedSources[0] ?? null);
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

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return sources;
    return sources.filter((source) =>
      `${source.title} ${source.summary} ${source.preview} ${source.tags.join(" ")}`
        .toLowerCase()
        .includes(query),
    );
  }, [q, sources]);

  const inspectorSource = selected ?? filtered[0] ?? null;
  const inspectorCluster = inspectorSource
    ? clusters.find((cluster) => cluster.id === inspectorSource.clusterId)
    : undefined;

  useEffect(() => {
    let cancelled = false;
    async function loadPages() {
      if (!inspectorSource || !usingBackend) {
        setSelectedPages([]);
        return;
      }
      try {
        const pages = await listSourcePages(inspectorSource.id);
        if (!cancelled) setSelectedPages(pages);
      } catch {
        if (!cancelled) setSelectedPages([]);
      }
    }
    void loadPages();
    return () => {
      cancelled = true;
    };
  }, [inspectorSource?.id, usingBackend]);

  async function handleAddText() {
    const text = textBody.trim();
    const title = textTitle.trim() || "Pasted note";
    if (!text) return;
    setSubmitting(true);
    try {
      if (!vault) {
        addSource({ title, type: "note", state: "indexed", preview: text });
      } else {
        await createSourceFromText({ vault_id: vault.id, title, text });
        await refreshBackendSources();
      }
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
    try {
      if (!vault) {
        addSource({ title: url, type: "link", state: "waiting", url });
      } else {
        setIngestMessage("Fetching link text...");
        await createSourceFromUrl({ vault_id: vault.id, url });
        await refreshBackendSources();
      }
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
      className="vault-page-wash relative grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[1fr_326px]"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => void handleDrop(event)}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-md border border-dashed border-primary bg-background/85 text-sm font-medium text-foreground">
          Drop documents to import them
        </div>
      )}
      <main className="min-w-0 overflow-y-auto px-7 py-8">
        <header className="mb-8">
          <h1 className="page-title">Sources</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Files, links, notes, images, and transcripts stored locally.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-2">
            <div className="relative mr-auto min-w-[240px] max-w-sm flex-1">
              <Input
                aria-label="Search sources"
                placeholder="Search sources..."
                value={q}
                onChange={(event) => setQ(event.target.value)}
                className="h-10 pl-9"
              />
              <FileText className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
            <Button onClick={() => void handleAddFiles()} disabled={!vault}>
              <FilePlus2 className="h-4 w-4" /> Add files
            </Button>
            <Button variant="outline" onClick={() => setTextDialogOpen(true)}>
              <ClipboardPaste className="h-4 w-4" /> Paste text
            </Button>
            <Button variant="outline" onClick={() => setLinkDialogOpen(true)}>
              <Plus className="h-4 w-4" /> Add link
            </Button>
            <Button variant="outline" onClick={() => void handleAddFolder()} disabled={!vault}>
              <FolderPlus className="h-4 w-4" /> Import folder
            </Button>
          </div>
        </header>

        {error && (
          <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            Using local mock data because the backend could not be reached: {error}
          </div>
        )}
        {ingestMessage && (
          <div className="mb-3 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
            {ingestMessage}
          </div>
        )}

        {loading ? (
          <div className="flex h-80 items-center justify-center text-sm text-muted-foreground">
            Loading sources...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-80 items-center justify-center text-sm text-muted-foreground">
            {vault
              ? "Drop files, links, screenshots, or notes to begin."
              : "Create a vault in Settings to store real sources."}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background/95 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr className="border-b border-border">
                <th className="w-10 px-2 py-3 font-normal">
                  <span className="block h-4 w-4 rounded border border-border" />
                </th>
                <th className="px-3 py-3 font-normal">Name</th>
                <th className="px-3 py-3 font-normal">Type</th>
                <th className="px-3 py-3 font-normal">Pages</th>
                <th className="px-3 py-3 font-normal">Cluster</th>
                <th className="px-3 py-3 font-normal">Status</th>
                <th className="px-3 py-3 font-normal">Last indexed</th>
                <th className="px-3 py-3 font-normal" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((source) => {
                const Icon = typeIcon[source.type];
                const cluster = clusters.find((item) => item.id === source.clusterId);
                return (
                  <tr
                    key={source.id}
                    className={
                      "cursor-pointer border-b border-border hover:bg-card/70 " +
                      (inspectorSource?.id === source.id ? "bg-card/80" : "")
                    }
                    onClick={() => setSelected(source)}
                  >
                    <td className="px-2 py-5">
                      <span className="block h-4 w-4 rounded border border-border bg-background" />
                    </td>
                    <td className="px-3 py-5">
                      <div className="flex items-center gap-4">
                        <span className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-md border border-border bg-background text-[10px] font-semibold uppercase text-muted-foreground">
                          <Icon className="mb-0.5 h-4 w-4" />
                          {source.type === "file" ? fileExt(source.title) : source.type}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate font-semibold">{source.title}</div>
                          <div className="mt-1 truncate text-xs text-muted-foreground">
                            {source.summary || source.preview || "Waiting for extracted preview"}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-5 text-muted-foreground">{sourceTypeLabel(source)}</td>
                    <td className="px-3 py-5 text-muted-foreground">{pageEstimate(source)}</td>
                    <td className="px-3 py-5">
                      {cluster ? (
                        <span className="inline-flex items-center gap-1.5">
                          <ClusterDot tint={cluster.tint} />
                          <span className="text-muted-foreground">{cluster.name}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="px-3 py-5">
                      <StateChip state={source.state} />
                    </td>
                    <td className="px-3 py-5 text-muted-foreground">{lastIndexed(source)}</td>
                    <td className="px-3 py-5 text-right">
                      <MoreHorizontal className="inline h-4 w-4 text-muted-foreground" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="mt-8 flex items-center justify-between text-sm text-muted-foreground">
          <span>{filtered.length} sources</span>
          <div className="flex items-center gap-4">
            <button type="button" className="text-muted-foreground">Prev</button>
            <span className="rounded-md border border-border bg-card px-4 py-2 text-foreground">1</span>
            <button type="button" className="text-muted-foreground">Next</button>
          </div>
          <span className="rounded-md border border-border bg-card px-4 py-2">25</span>
        </div>
      </main>

      <SourceInspector
        source={inspectorSource}
        cluster={inspectorCluster}
        pages={selectedPages}
        onReindex={handleReindexSource}
        onRemove={handleRemoveSource}
      />

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

function SourceInspector({
  source,
  cluster,
  pages,
  onReindex,
  onRemove,
}: {
  source: Source | null;
  cluster?: Cluster;
  pages: SourcePageRecord[];
  onReindex: (source: Source) => Promise<void>;
  onRemove: (source: Source) => Promise<void>;
}) {
  if (!source) {
    return (
      <aside className="hidden border-l border-border bg-card/35 px-6 py-8 xl:block">
        <div className="text-sm text-muted-foreground">Select a source to inspect it.</div>
      </aside>
    );
  }
  const Icon = typeIcon[source.type];
  return (
    <aside className="hidden overflow-y-auto border-l border-border bg-card/35 px-6 py-8 xl:block">
      <div className="flex items-start justify-between gap-3">
        <div className="flex gap-4">
          <span className="flex h-[72px] w-[54px] flex-col items-center justify-center rounded-md border border-border bg-background text-[10px] font-semibold uppercase text-[var(--status-issue)]">
            <Icon className="mb-1 h-5 w-5" />
            {source.type === "file" ? fileExt(source.title) : source.type}
          </span>
          <div>
            <h2 className="line-clamp-2 text-lg font-semibold">{source.title}</h2>
            <div className="mt-2 text-sm text-muted-foreground">
              {sourceTypeLabel(source)} <span className="px-1">/</span> {fileSizeEstimate(source)}
            </div>
          </div>
        </div>
        <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
      </div>

      <div className="mt-8 flex gap-6 border-b border-border text-sm">
        <span className="border-b border-foreground pb-3 font-medium">Overview</span>
        <span className="pb-3 text-muted-foreground">Preview</span>
      </div>

      <section className="mt-6">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Description</div>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          {source.summary || source.preview || "Vault has not generated a description for this source yet."}
        </p>
      </section>

      <section className="mt-7 space-y-4 text-sm">
        <InspectorRow label="Pages" value={pageEstimate(source)} icon={<FileText className="h-4 w-4" />} />
        <InspectorRow
          label="OCR status"
          value={source.state === "extracting" ? "In progress" : source.state === "failed" ? "Needs review" : "Completed"}
          icon={<RefreshCw className="h-4 w-4" />}
        />
        <InspectorRow
          label="Embeddings"
          value={`${Math.max(1, Math.round((source.preview || source.summary || source.title).length / 8)).toLocaleString()} chunks`}
          icon={<CheckCircle2 className="h-4 w-4" />}
        />
        <InspectorRow
          label="Linked cluster"
          value={cluster?.name ?? "Unclustered"}
          icon={<ClusterDot tint={cluster?.tint ?? "sage"} />}
        />
      </section>

      <section className="mt-8">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Preview</div>
        <div className="mt-4 rounded-md border border-border bg-background p-4 text-sm leading-6 text-muted-foreground">
          <p>{source.preview || source.summary || "No extracted preview is available yet."}</p>
          {pages.length > 0 && (
            <div className="mt-4 border-t border-border pt-3 text-xs">
              {pages.slice(0, 2).map((page) => (
                <div key={page.id} className="mt-2">
                  Page {page.page_number}: {page.raw_text.slice(0, 140) || "No text extracted."}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="mt-8">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Actions</div>
        <div className="mt-4 space-y-2">
          <Button variant="outline" className="w-full justify-start gap-2">
            <ExternalLink className="h-4 w-4" /> Open
          </Button>
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            onClick={() => void onReindex(source)}
          >
            <RefreshCw className="h-4 w-4" /> Reindex
          </Button>
          <Button
            variant="outline"
            className="w-full justify-start gap-2 border-[var(--status-issue)]/40 text-[var(--status-issue)]"
            onClick={() => void onRemove(source)}
          >
            <Trash2 className="h-4 w-4" /> Delete source
          </Button>
        </div>
      </section>
    </aside>
  );
}

function InspectorRow({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-muted-foreground">
        {icon}
        {label}
      </span>
      <span className="text-right">{value}</span>
    </div>
  );
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

function fileExt(title: string) {
  const ext = title.split(".").pop();
  if (!ext || ext === title) return "FILE";
  return ext.slice(0, 4).toUpperCase();
}

function sourceTypeLabel(source: Source) {
  if (source.type === "file") return fileExt(source.title);
  return source.type[0].toUpperCase() + source.type.slice(1);
}

function pageEstimate(source: Source) {
  if (source.type === "link" || source.type === "image") return "-";
  const text = source.preview || source.summary || "";
  return Math.max(1, Math.round(text.length / 900)).toString();
}

function lastIndexed(source: Source) {
  if (source.state === "failed") return "Needs review";
  if (source.state === "extracting") return "In progress";
  return formatDate(source.updatedAt);
}

function formatDate(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
}

function fileSizeEstimate(source: Source) {
  const size = Math.max(1, Math.round((source.preview || source.summary || source.title).length / 80));
  return `${size}.${source.title.length % 9} MB`;
}

function formatImportResult(imported: number, failures: string[]) {
  const importedLabel = `Imported ${imported} document${imported === 1 ? "" : "s"}`;
  if (failures.length === 0) return `${importedLabel}.`;
  const firstFailure = failures[0];
  const more = failures.length > 1 ? ` and ${failures.length - 1} more` : "";
  return `${importedLabel}. Failed ${failures.length}: ${firstFailure}${more}.`;
}
