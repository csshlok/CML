import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useDeferredValue, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  CheckCircle2,
  Clapperboard,
  ClipboardPaste,
  ExternalLink,
  File,
  FileCode2,
  FilePlus2,
  FileText,
  FolderPlus,
  Image,
  Link2,
  Loader2,
  Mic,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ClusterDot } from "@/components/ClusterChip";
import { notify } from "@/components/product/Notifications";
import {
  SourceImportInlineProgress,
  useSourceImport,
} from "@/components/product/SourceImportProgress";
import {
  sourceStateLabel,
  type Cluster,
  type Source,
} from "@/lib/domain";
import {
  createSourceFromText,
  createSourceFromUrl,
  countSources,
  deleteSource as deleteBackendSource,
  getSourceStats,
  getSource,
  listClusters,
  listSourcePages,
  listSourcesPage,
  listVaults,
  reindexSource,
  type SourceImportProgress,
  type SourcePageRecord,
  type SourceStatsRecord,
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
import { ConfirmAction, DegradedState, EmptyState, SkeletonRegion } from "@/components/product/Feedback";

export const Route = createFileRoute("/_app/sources")({
  validateSearch: (search: Record<string, unknown>): { filter?: "unsorted"; source?: string } => ({
    filter: search.filter === "unsorted" ? "unsorted" : undefined,
    source: typeof search.source === "string" ? search.source : undefined,
  }),
  head: () => ({ meta: [{ title: "Sources" }] }),
  component: SourcesView,
});

const typeIcon = {
  file: FileText,
  link: Link2,
  note: File,
  image: Image,
  audio: Mic,
  video: Clapperboard,
  code: FileCode2,
  external_transcript: Mic,
  external_artifact: FileText,
};

function SourcesView() {
  const navigate = useNavigate();
  const sourceImport = useSourceImport();
  const { filter, source: requestedSourceId } = Route.useSearch();
  const inboxOnly = filter === "unsorted";
  const pageSize = 25;
  const [q, setQ] = useState("");
  const deferredQuery = useDeferredValue(q);
  const [selected, setSelected] = useState<Source | null>(null);
  const [selectedPages, setSelectedPages] = useState<SourcePageRecord[]>([]);
  const [selectedStats, setSelectedStats] = useState<SourceStatsRecord | null>(null);
  const [vault, setActiveVault] = useState<VaultRecord | null>(null);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [textDialogOpen, setTextDialogOpen] = useState(false);
  const [linkDialogOpen, setLinkDialogOpen] = useState(false);
  const [textTitle, setTextTitle] = useState("Pasted note");
  const [textBody, setTextBody] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [pageCursors, setPageCursors] = useState<Array<string | null>>([null]);
  const [nextSourceCursor, setNextSourceCursor] = useState<string | null>(null);
  const sourceRequestRef = useRef(0);
  const hasLoadedSourcesRef = useRef(false);
  const summarizedImportJobRef = useRef<string | null>(null);

  async function refreshBackendSources() {
    const requestId = ++sourceRequestRef.current;
    setLoading(!hasLoadedSourcesRef.current);
    setRefreshing(hasLoadedSourcesRef.current);
    setError(null);
    try {
      const vaults = await listVaults();
      if (requestId !== sourceRequestRef.current) return;
      const activeVault = vaults[0] ?? null;
      setActiveVault(activeVault);
      if (!activeVault) {
        setBackendSources([]);
        setBackendClusters([]);
        return;
      }
      const [sourceResult, clusterResult, countResult, requestedResult] = await Promise.allSettled([
        listSourcesPage(activeVault.id, {
          limit: pageSize,
          cursor: pageCursors[pageIndex] ?? null,
          unclustered: inboxOnly,
          states: inboxOnly ? ["waiting", "processing", "failed"] : undefined,
          query: deferredQuery,
        }),
        listClusters(activeVault.id),
        countSources(activeVault.id, undefined, {
          unclustered: inboxOnly,
          states: inboxOnly ? ["waiting", "processing", "failed"] : undefined,
          query: deferredQuery,
        }),
        requestedSourceId ? getSource(requestedSourceId).catch(() => null) : Promise.resolve(null),
      ]);
      if (requestId !== sourceRequestRef.current) return;
      if (sourceResult.status === "rejected") throw sourceResult.reason;
      const sourcePage = sourceResult.value;
      const clusterRows = clusterResult.status === "fulfilled" ? clusterResult.value : null;
      const count = countResult.status === "fulfilled" ? countResult.value : null;
      const requestedSource = requestedResult.status === "fulfilled" ? requestedResult.value : null;
      if (count && count.total > 0 && sourcePage.items.length === 0 && pageIndex > 0) {
        setPageIndex(Math.max(0, Math.ceil(count.total / pageSize) - 1));
        return;
      }
      const mappedSources = sourcePage.items.map(sourceFromRecord);
      const visibleSources = mappedSources;
      setBackendSources(visibleSources);
      if (clusterRows) setBackendClusters(clusterRows.map(clusterFromRecord));
      if (count) setSourceTotal(count.total);
      setNextSourceCursor(sourcePage.next_cursor);
      if (sourcePage.next_cursor) {
        setPageCursors((current) => {
          if (current[pageIndex + 1] === sourcePage.next_cursor) return current;
          const next = current.slice(0, pageIndex + 1);
          next[pageIndex + 1] = sourcePage.next_cursor;
          return next;
        });
      }
      setSelected((current) =>
        (requestedSource ? sourceFromRecord(requestedSource) : null) ??
        visibleSources.find((source) => source.id === current?.id) ??
        null,
      );
      hasLoadedSourcesRef.current = true;
    } catch (err) {
      if (requestId !== sourceRequestRef.current) return;
      const message = err instanceof Error ? err.message : "Vault could not load your sources.";
      setError(message);
      notify({ title: "Sources could not load", description: message, tone: "error" });
      setActiveVault(null);
    } finally {
      if (requestId === sourceRequestRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }

  useEffect(() => {
    void refreshBackendSources();
  }, [deferredQuery, inboxOnly, pageIndex, requestedSourceId, pageCursors]);

  useEffect(() => {
    setPageIndex(0);
    setPageCursors([null]);
  }, [inboxOnly]);

  useEffect(() => {
    setPageIndex(0);
    setPageCursors([null]);
  }, [deferredQuery]);

  useEffect(() => {
    const job = sourceImport.job;
    const progress = sourceImport.progress;
    if (
      !job ||
      !progress ||
      sourceImport.active ||
      summarizedImportJobRef.current === job.id
    ) {
      return;
    }
    summarizedImportJobRef.current = job.id;
    setIngestMessage(formatSourceImportResult(job.status, progress));
    void refreshBackendSources();
  }, [sourceImport.active, sourceImport.job, sourceImport.progress]);

  const usingBackend = Boolean(vault);
  const sources = usingBackend ? backendSources : [];
  const clusters = usingBackend ? backendClusters : [];

  const filtered = useMemo(() => sources, [sources]);

  const inspectorSource = selected;
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
        const [pagesResult, statsResult] = await Promise.allSettled([
          listSourcePages(inspectorSource.id, { limit: 2 }),
          getSourceStats(inspectorSource.id),
        ]);
        if (!cancelled) {
          setSelectedPages(pagesResult.status === "fulfilled" ? pagesResult.value : []);
          setSelectedStats(statsResult.status === "fulfilled" ? statsResult.value : null);
        }
      } catch {
        if (!cancelled) {
          setSelectedPages([]);
          setSelectedStats(null);
        }
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
        setIngestMessage("Create or open a library before adding text sources.");
        return;
      }
      await createSourceFromText({ vault_id: vault.id, title, text });
      await refreshBackendSources();
      setTextBody("");
      setTextTitle("Pasted note");
      setTextDialogOpen(false);
      setIngestMessage(`Added "${title}" as a text source.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not add this text source.";
      setIngestMessage(message);
      notify({ title: "Text import failed", description: message, tone: "error" });
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
        setIngestMessage("Create or open a library before adding links.");
        return;
      }
      setIngestMessage("Fetching link text...");
      const source = await createSourceFromUrl({ vault_id: vault.id, url });
      await refreshBackendSources();
      setLinkUrl("");
      setLinkDialogOpen(false);
      setIngestMessage(source.import_outcome === "updated" ? "Updated the existing link." : "Imported link text.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not import this link.";
      setIngestMessage(message);
      notify({ title: "Link import failed", description: message, tone: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddFiles() {
    if (!vault || !window.cmlDesktop?.selectSourceFiles) {
      setIngestMessage("File picking is available in the desktop app after a library is created.");
      return;
    }
    const paths = await window.cmlDesktop.selectSourceFiles();
    await importFilePaths(paths);
  }

  async function handleAddFolder() {
    if (!vault || !window.cmlDesktop?.selectSourceFolders || !window.cmlDesktop?.scanSupportedFiles) {
      setIngestMessage("Folder import is available in the desktop app after a library is created.");
      return;
    }
    const folders = await window.cmlDesktop.selectSourceFolders();
    const report = await window.cmlDesktop.scanSupportedFiles(folders);
    await importFilePaths(report.files, report.truncated ? report.limit : null);
  }

  async function importFilePaths(paths: string[], truncatedAt: number | null = null) {
    if (!vault || paths.length === 0) return;
    if (sourceImport.active) {
      setIngestMessage("Finish or stop the current file import before starting another one.");
      return;
    }
    setIngestMessage(null);
    try {
      await sourceImport.start({
        vaultId: vault.id,
        paths,
        truncatedAt,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not start the file import.";
      setIngestMessage(message);
      notify({
        title: "File import could not start",
        description: message,
        tone: "error",
      });
    }
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
    if (sourceImport.active) {
      setIngestMessage("Finish or stop the current file import before starting another one.");
      return;
    }
    const droppedPaths = window.cmlDesktop?.getDroppedFilePaths?.() ?? [];
    if (droppedPaths.length === 0) {
      setIngestMessage(
        window.cmlDesktop?.getDroppedFilePaths
          ? "Vault could not read that drop. Try Browse files."
          : "Drop import is available in the desktop app.",
      );
      return;
    }
    const report = window.cmlDesktop?.scanSupportedFiles
      ? await window.cmlDesktop.scanSupportedFiles(droppedPaths)
      : { files: droppedPaths, truncated: false, limit: 0 };
    const paths = report.files;
    if (paths.length === 0) {
      setIngestMessage("No supported documents found in that drop.");
      return;
    }
    await importFilePaths(paths, report.truncated ? report.limit : null);
  }

  async function handleReindexSource(source: Source) {
    if (!usingBackend) {
      setIngestMessage("Create or open a library before reindexing sources.");
      return;
    }
    try {
      const result = await reindexSource(source.id);
      setBackendSources((current) =>
        current.map((item) =>
          item.id === source.id ? { ...item, state: "processing" as const } : item,
        ),
      );
      setIngestMessage(
        result.status === "running"
          ? `Reindexing “${source.title}” now.`
          : `Queued “${source.title}” for reindexing.`,
      );
      notify({
        title: `Reindexing ${source.title}`,
        description: result.status === "running" ? "Indexing is running now." : "The task is queued.",
        tone: "success",
        actionLabel: "Open Tasks",
        onAction: () => navigate({ to: "/tasks", search: { job: result.job_id } }),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not queue reindexing.";
      setIngestMessage(message);
      notify({ title: "Reindexing failed", description: message, tone: "error" });
    }
  }

  async function handleRemoveSource(source: Source) {
    if (!usingBackend) {
      setIngestMessage("Create or open a library before deleting sources.");
      return;
    }
    try {
      await deleteBackendSource(source.id);
      if (selected?.id === source.id) setSelected(null);
      await refreshBackendSources();
      notify({ title: "Source removed", tone: "success" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not remove this source.";
      setIngestMessage(message);
      notify({ title: "Source removal failed", description: message, tone: "error" });
    }
  }

  return (
    <div
      className="sources-layout vault-page-wash relative grid h-full overflow-y-auto xl:overflow-hidden"
      data-inspector-open={Boolean(inspectorSource)}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => void handleDrop(event)}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-md border border-dashed border-primary bg-background/85 text-sm font-medium text-foreground">
          Drop documents to import them
        </div>
      )}
      <main className="min-w-0 px-7 py-8 xl:overflow-y-auto">
        <header className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="page-title">{inboxOnly ? "Inbox" : "Sources"}</h1>
            {inboxOnly && (
              <Link
                to="/sources"
                search={{}}
                className="text-sm text-primary hover:underline"
              >
                View all sources
              </Link>
            )}
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {inboxOnly
              ? "Unclustered sources that are still waiting, processing, or need review."
              : "Files, links, notes, images, and transcripts stored locally."}
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-2">
            <div className="relative mr-auto min-w-0 flex-[1_1_240px] sm:max-w-sm">
              <Input
                aria-label="Search sources"
                placeholder="Search sources..."
                value={q}
                onChange={(event) => setQ(event.target.value)}
                className="h-10 pl-9 pr-9"
              />
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              {refreshing ? (
                <Loader2
                  className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground motion-reduce:animate-none"
                  aria-label="Refreshing source results"
                />
              ) : null}
            </div>
            <Button onClick={() => void handleAddFiles()} disabled={!vault || sourceImport.active || sourceImport.actionBusy}>
              <FilePlus2 className="h-4 w-4" /> Add files
            </Button>
            <Button variant="outline" onClick={() => setTextDialogOpen(true)}>
              <ClipboardPaste className="h-4 w-4" /> Paste text
            </Button>
            <Button variant="outline" onClick={() => setLinkDialogOpen(true)}>
              <Plus className="h-4 w-4" /> Add link
            </Button>
            <Button variant="outline" onClick={() => void handleAddFolder()} disabled={!vault || sourceImport.active || sourceImport.actionBusy}>
              <FolderPlus className="h-4 w-4" /> Import folder
            </Button>
            <Button variant="outline" asChild>
              <Link to="/projects">
                <FileCode2 className="h-4 w-4" /> Code projects
              </Link>
            </Button>
          </div>
        </header>

        {error && <div className="mb-3"><DegradedState compact description={error} onRetry={() => void refreshBackendSources()} /></div>}
        {sourceImport.active && sourceImport.progress ? (
          <div className="mb-3">
            <SourceImportInlineProgress />
          </div>
        ) : ingestMessage ? (
          <div className="mb-3 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground break-words">
            {ingestMessage}
          </div>
        ) : null}

        {loading ? (
          <SkeletonRegion className="py-8" lines={9} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={inboxOnly ? "Inbox clear" : q ? "No sources match" : "Add your first source"}
            description={inboxOnly
              ? "Everything has been organized or indexed."
              : q
                ? "Try a shorter title, type, or tag."
                : vault
                  ? "Drop files here, paste a note, or add a link. Vault keeps the original material local."
                  : "Choose a library in Settings before adding sources."}
          />
        ) : (
          <div className="min-w-0">
            <table className="w-full table-fixed text-sm">
              <thead className="sticky top-0 bg-background/95 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-3 py-3 font-normal">Name</th>
                  <th className="hidden w-28 px-3 py-3 font-normal 2xl:table-cell">Type</th>
                  <th className="hidden w-28 px-3 py-3 font-normal xl:table-cell">Status</th>
                  <th className="hidden w-40 px-3 py-3 font-normal lg:table-cell">Cluster</th>
                  <th className="hidden w-32 px-3 py-3 font-normal 2xl:table-cell">Last indexed</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((source) => {
                  const Icon = typeIcon[source.type];
                  const cluster = clusters.find((item) => item.id === source.clusterId);
                  return (
                    <tr
                      key={source.id}
                      tabIndex={0}
                      aria-label={`Open ${source.title}`}
                      aria-selected={inspectorSource?.id === source.id}
                      className={
                        "cursor-pointer border-b border-border hover:bg-card/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset " +
                        (inspectorSource?.id === source.id ? "bg-card/80" : "")
                      }
                      onClick={() => setSelected(source)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelected(source);
                        }
                      }}
                    >
                      <td className="px-3 py-5">
                        <div className="flex items-center gap-4">
                          <span className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-md border border-border bg-background text-[10px] font-semibold uppercase text-muted-foreground">
                            <Icon className="mb-0.5 h-4 w-4" />
                            {source.type === "file" ? fileExt(source.title) : source.type}
                          </span>
                          <div className="min-w-0">
                            <div className="break-words font-semibold">{source.title}</div>
                            <div className="mt-1 line-clamp-2 break-words text-xs text-muted-foreground">
                              {source.summary || source.preview || "Waiting for extracted preview"}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="hidden px-3 py-5 text-muted-foreground 2xl:table-cell">{sourceTypeLabel(source)}</td>
                      <td className="hidden px-3 py-5 xl:table-cell">
                        <StateChip state={source.state} />
                      </td>
                      <td className="hidden px-3 py-5 lg:table-cell">
                        {cluster ? (
                          <span className="inline-flex max-w-40 items-center gap-1.5">
                            <ClusterDot tint={cluster.tint} />
                            <span className="break-words text-muted-foreground">{cluster.name}</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="hidden px-3 py-5 text-muted-foreground 2xl:table-cell">{lastIndexed(source)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-8 flex flex-col gap-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>
            Showing {filtered.length} of {sourceTotal.toLocaleString()} sources
          </span>
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="text-muted-foreground disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
              disabled={pageIndex === 0}
            >
              Prev
            </button>
            <span className="rounded-md border border-border bg-card px-4 py-2 text-foreground">
              {pageIndex + 1}
            </span>
            <button
              type="button"
              className="text-muted-foreground disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => setPageIndex((current) => current + 1)}
              disabled={!nextSourceCursor}
            >
              Next
            </button>
          </div>
          <span className="rounded-md border border-border bg-card px-4 py-2">
            {inboxOnly ? "Inbox view" : `${pageSize} / page`}
          </span>
        </div>
      </main>

      {inspectorSource ? (
        <SourceInspector
          source={inspectorSource}
          cluster={inspectorCluster}
          pages={selectedPages}
          stats={selectedStats}
          onClose={() => {
            setSelected(null);
            if (requestedSourceId) {
              navigate({
                to: "/sources",
                search: inboxOnly ? { filter: "unsorted" } : {},
              });
            }
          }}
          onOpen={async (source) => {
            if (source.localPath) return (await window.cmlDesktop?.openPath(source.localPath)) ?? false;
            if (source.url) return (await window.cmlDesktop?.openExternal(source.url)) ?? false;
            return false;
          }}
          onReindex={handleReindexSource}
          onRemove={handleRemoveSource}
        />
      ) : null}

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
  stats,
  onClose,
  onOpen,
  onReindex,
  onRemove,
}: {
  source: Source;
  cluster?: Cluster;
  pages: SourcePageRecord[];
  stats: SourceStatsRecord | null;
  onClose: () => void;
  onOpen: (source: Source) => Promise<boolean | undefined>;
  onReindex: (source: Source) => Promise<void>;
  onRemove: (source: Source) => Promise<void>;
}) {
  const Icon = typeIcon[source.type];
  return (
    <aside className="source-inspector overflow-y-visible border-t border-border bg-card/35 px-7 py-8 xl:overflow-y-auto xl:border-l xl:border-t-0 xl:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-4">
          <span className="flex h-[72px] w-[54px] flex-col items-center justify-center rounded-md border border-border bg-background text-[10px] font-semibold uppercase text-[var(--status-issue)]">
            <Icon className="mb-1 h-5 w-5" />
            {source.type === "file" ? fileExt(source.title) : source.type}
          </span>
          <div className="min-w-0">
            <h2 className="break-words text-lg font-semibold">{source.title}</h2>
            <div className="mt-2 text-sm text-muted-foreground">
              {sourceTypeLabel(source)} <span className="px-1">/</span> {formatFileSize(stats?.size_bytes)}
            </div>
          </div>
        </div>
        <button
          type="button"
          className="rounded-sm p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onClose}
          aria-label="Close source details"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-8 border-b border-border pb-3 text-sm font-medium">Source details</div>

      {source.state === "failed" ? (
        <section className="mt-6 rounded-md border border-[var(--status-error)]/35 bg-[var(--status-error-bg)] p-4">
          <div className="font-medium text-[var(--status-error)]">Indexing did not complete</div>
          <p className="mt-1 break-words text-sm leading-6 text-[var(--text-body)]">
            {stats?.last_error || "Vault could not finish processing this source. Retry after checking the local model and file access."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void onReindex(source)}>
              <RefreshCw className="h-4 w-4" /> Retry indexing
            </Button>
            <ConfirmAction
              title={`Delete “${source.title}”?`}
              description="This removes Vault’s indexed copy and extracted context. The original local file is not deleted."
              confirmLabel="Delete source"
              onConfirm={() => onRemove(source)}
            >
              <Button variant="outline" size="sm" className="border-[var(--status-error)]/40 text-[var(--status-error)]">
                <Trash2 className="h-4 w-4" /> Remove source
              </Button>
            </ConfirmAction>
          </div>
        </section>
      ) : null}

      <section className="mt-6">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Description</div>
        <p className="mt-4 break-words text-sm leading-6 text-muted-foreground">
          {source.state === "failed"
            ? "No description is available because indexing did not complete."
            : source.summary || source.preview || "Vault has not generated a description for this source yet."}
        </p>
      </section>

      <section className="mt-7 space-y-4 text-sm">
        <InspectorRow label="Pages" value={stats ? stats.page_count.toLocaleString() : "—"} icon={<FileText className="h-4 w-4" />} />
        <InspectorRow
          label="OCR status"
          value={source.state === "processing" ? "In progress" : source.state === "failed" ? "Needs review" : "Completed"}
          icon={<RefreshCw className="h-4 w-4" />}
        />
        <InspectorRow
          label="Embeddings"
          value={stats ? `${stats.chunk_count.toLocaleString()} chunks` : "—"}
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
        <div className="mt-4 rounded-md border border-border bg-background p-4 text-sm leading-6 text-muted-foreground break-words">
          <p>{source.preview || source.summary || "No extracted preview is available yet."}</p>
          {pages.length > 0 && (
            <div className="mt-4 border-t border-border pt-3 text-xs">
              {pages.slice(0, 2).map((page) => (
                <div key={page.id} className="mt-2 break-words">
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
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            disabled={!source.localPath && !source.url}
            onClick={() => void onOpen(source)}
          >
            <ExternalLink className="h-4 w-4" /> Open
          </Button>
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            onClick={() => void onReindex(source)}
          >
            <RefreshCw className="h-4 w-4" /> {source.state === "failed" ? "Retry indexing" : "Reindex"}
          </Button>
          <ConfirmAction
            title={`Delete “${source.title}”?`}
            description="This removes Vault’s indexed copy and extracted context. The original local file is not deleted."
            confirmLabel="Delete source"
            onConfirm={() => onRemove(source)}
          >
            <Button
              variant="outline"
              className="w-full justify-start gap-2 border-[var(--status-issue)]/40 text-[var(--status-issue)]"
            >
              <Trash2 className="h-4 w-4" /> Delete source
            </Button>
          </ConfirmAction>
        </div>
      </section>
    </aside>
  );
}

function InspectorRow({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
        {icon}
        {label}
      </span>
      <span className="break-words text-right">{value}</span>
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

function fileExt(title: string) {
  const ext = title.split(".").pop();
  if (!ext || ext === title) return "FILE";
  return ext.slice(0, 4).toUpperCase();
}

function sourceTypeLabel(source: Source) {
  if (source.type === "file") return fileExt(source.title);
  if (source.type === "external_transcript") return "Transcript";
  if (source.type === "external_artifact") return "Artifact";
  return source.type[0].toUpperCase() + source.type.slice(1);
}

function lastIndexed(source: Source) {
  if (source.state === "failed") return "Needs review";
  if (source.state === "processing") return "In progress";
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

function formatFileSize(value?: number | null) {
  if (value === null || value === undefined) return "Size unavailable";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatSourceImportResult(status: string, progress: SourceImportProgress) {
  const processed = `${progress.completed_files.toLocaleString()} of ${progress.total_files.toLocaleString()} files processed`;
  if (status === "cancelled") {
    return `Import stopped. ${processed}.`;
  }
  if (status === "failed" || status === "manual_review") {
    return `Import needs attention. ${processed}.`;
  }
  const imported = `${progress.imported_files.toLocaleString()} imported`;
  const updated = `${progress.updated_files.toLocaleString()} updated`;
  const failed = progress.failed_files
    ? `, ${progress.failed_files.toLocaleString()} failed`
    : "";
  const limitNotice = progress.truncated_at
    ? ` Folder scanning stopped at ${progress.truncated_at.toLocaleString()} files; import the remaining files in another batch.`
    : "";
  return `Import finished: ${imported}, ${updated}${failed}.${limitNotice}`;
}
