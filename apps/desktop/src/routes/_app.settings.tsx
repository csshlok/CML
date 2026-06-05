import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Database,
  Download,
  FileText,
  Folder,
  Layers,
  Lock,
  MessageSquare,
  Play,
  RefreshCw,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  TerminalSquare,
  UserRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  activateLocalModel,
  cancelModelDownload,
  cancelEmbeddingDownload,
  configureEmbeddingRuntime,
  createDiagnosticBundle,
  createVault,
  enforceChatEvidenceRetention,
  getChatEvidenceRetentionPolicy,
  getEmbeddingRuntimeStatus,
  getEmbeddingDownloadStatus,
  getHardwareStatus,
  getModelCompatibilityReport,
  importLocalModel,
  getJobStatus,
  getModelRuntimeStatus,
  getOCRRuntimeStatus,
  pruneQueryCache,
  listLocalModels,
  listIntegrationImports,
  listVaults,
  refreshIntegrationImport,
  startModelDownload,
  startEmbeddingDownload,
  updateIntegrationImport,
  updateVault,
  type ChatEvidenceRetentionPolicy,
  type ChatEvidenceRetentionResult,
  type EmbeddingRuntimeStatus,
  type EmbeddingModelDownloadState,
  type HardwareStatusRead,
  type IntegrationImportRecord,
  type JobQueueStatus,
  type LocalModelRecord,
  type ModelCompatibilityRecord,
  type ModelRuntimeStatus,
  type OCRRuntimeStatusRead,
  type VaultRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/settings")({
  head: () => ({ meta: [{ title: "Settings" }] }),
  component: SettingsView,
});

const settingsSections = [
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "storage", label: "Vault storage", icon: Database },
  { id: "models", label: "Local models", icon: TerminalSquare },
  { id: "embeddings", label: "Embeddings", icon: Layers },
  { id: "ocr", label: "OCR", icon: Settings2 },
  { id: "diagnostics", label: "Diagnostics", icon: Activity },
  { id: "privacy", label: "Privacy", icon: Lock },
  { id: "advanced", label: "Advanced", icon: SlidersHorizontal },
] as const;

function SettingsView() {
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const [activeSection, setActiveSection] = useState("models");
  const [backendVault, setBackendVault] = useState<VaultRecord | null>(null);
  const [pathDraft, setPathDraft] = useState("");
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingDownload, setEmbeddingDownload] = useState<EmbeddingModelDownloadState | null>(null);
  const [embeddingCacheDraft, setEmbeddingCacheDraft] = useState("");
  const [ocrRuntime, setOcrRuntime] = useState<OCRRuntimeStatusRead | null>(null);
  const [hardware, setHardware] = useState<HardwareStatusRead | null>(null);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [integrationImports, setIntegrationImports] = useState<IntegrationImportRecord[]>([]);
  const [retentionPolicy, setRetentionPolicy] = useState<ChatEvidenceRetentionPolicy | null>(null);
  const [retentionResult, setRetentionResult] = useState<ChatEvidenceRetentionResult | null>(null);
  const [refreshingImportId, setRefreshingImportId] = useState<string | null>(null);
  const [retentionBusy, setRetentionBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [customModelPath, setCustomModelPath] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelReport, setCustomModelReport] = useState<ModelCompatibilityRecord | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [
          vaultRows,
          modelRows,
          runtimeStatus,
          embeddingStatus,
          embeddingDownloadStatus,
          ocrStatus,
          hardwareStatus,
          jobStatus,
          evidencePolicy,
        ] = await Promise.all([
          listVaults(),
          listLocalModels(),
          getModelRuntimeStatus(),
          getEmbeddingRuntimeStatus(),
          getEmbeddingDownloadStatus(),
          getOCRRuntimeStatus(),
          getHardwareStatus(),
          getJobStatus(),
          getChatEvidenceRetentionPolicy(),
        ]);
        if (cancelled) return;
        const firstVault = vaultRows[0] ?? null;
        setBackendVault(firstVault);
        if (firstVault) {
          setPathDraft(firstVault.path);
        }
        const importRows = firstVault ? await listIntegrationImports(firstVault.id) : [];
        if (cancelled) return;
        setModels(modelRows);
        setRuntime(runtimeStatus);
        setEmbeddingRuntime(embeddingStatus);
        setEmbeddingCacheDraft(embeddingStatus.cache_dir ?? "");
        setEmbeddingDownload(embeddingDownloadStatus);
        setOcrRuntime(ocrStatus);
        setHardware(hardwareStatus);
        setJobs(jobStatus);
        setRetentionPolicy(evidencePolicy);
        setIntegrationImports(importRows);
      } catch (error) {
        if (!cancelled) {
          setStatusMessage(error instanceof Error ? error.message : "Settings backend unavailable.");
        }
      }
    }

    void load();
    const id = window.setInterval(load, 6000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  async function saveVaultPath() {
    const path = pathDraft.trim();
    if (!path) return;
    setSaving(true);
    try {
      const nextVault = backendVault
        ? await updateVault(backendVault.id, { path })
        : await createVault({ name: "Local memory", path });
      setBackendVault(nextVault);
      setStatusMessage("Vault location saved.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not save vault location.");
    } finally {
      setSaving(false);
    }
  }

  async function saveEmbeddingRuntime() {
    const modelPath = embeddingCacheDraft.trim();
    if (!modelPath) {
      setStatusMessage("Choose the local embedding model folder before saving.");
      return;
    }
    setSaving(true);
    try {
      const nextStatus = await configureEmbeddingRuntime({
        provider: "sentence-transformers",
        cache_dir: modelPath,
      });
      setEmbeddingRuntime(nextStatus);
      setStatusMessage("Embedding model path saved.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not update embedding settings.");
    } finally {
      setSaving(false);
    }
  }

  async function chooseEmbeddingFolder() {
    const selected = await desktop?.selectEmbeddingFolder?.();
    if (selected) {
      setEmbeddingCacheDraft(selected);
      setStatusMessage("Embedding model folder selected. Test it before using memory search.");
    }
  }

  async function downloadEmbeddingModel() {
    setSaving(true);
    try {
      const state = await startEmbeddingDownload({
        cache_dir: embeddingCacheDraft.trim() || null,
      });
      setEmbeddingDownload(state);
      setStatusMessage("Embedding model download started.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not start embedding download.");
    } finally {
      setSaving(false);
    }
  }

  async function cancelEmbeddingModelDownload() {
    try {
      setEmbeddingDownload(await cancelEmbeddingDownload());
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not cancel embedding download.");
    }
  }

  async function downloadModel(modelId: string) {
    setDownloadingId(modelId);
    try {
      await startModelDownload(modelId);
      setModels(await listLocalModels());
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not start model download.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function activateModel(modelId: string, role: "chat" | "expert" | "pair") {
    setActivatingId(modelId);
    try {
      await activateLocalModel(modelId, role);
      setModels(await listLocalModels());
      setStatusMessage(role === "chat" ? "Chat model activated." : role === "expert" ? "Expert checkpoint activated." : "Chat/expert model activated.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not activate model.");
    } finally {
      setActivatingId(null);
    }
  }

  async function chooseModelFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (selected) {
      setCustomModelPath(selected);
      setCustomModelReport(null);
    }
  }

  async function validateCustomModel() {
    try {
      const report = await getModelCompatibilityReport({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      setCustomModelReport(report);
      setStatusMessage(report.detail);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not validate model.");
    }
  }

  async function importApprovedModel() {
    try {
      const imported = await importLocalModel({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      setModels(await listLocalModels());
      setCustomModelReport(imported.compatibility);
      setStatusMessage(`${imported.name} imported.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not import model.");
    }
  }

  async function cancelDownload(modelId: string) {
    try {
      await cancelModelDownload(modelId);
      setModels(await listLocalModels());
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not cancel model download.");
    }
  }

  async function exportDiagnostics() {
    setStatusMessage("Creating diagnostic bundle...");
    try {
      const bundle = await createDiagnosticBundle();
      setStatusMessage(`Diagnostic bundle saved to ${bundle.bundle_path}`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not create diagnostic bundle.");
    }
  }

  async function refreshLocalImport(importId: string) {
    setRefreshingImportId(importId);
    try {
      const result = await refreshIntegrationImport(importId, {
        import_files: true,
        tombstone_missing: true,
      });
      setIntegrationImports(backendVault ? await listIntegrationImports(backendVault.id) : []);
      setStatusMessage(
        `Import refreshed: ${result.imported_count} new, ${result.updated_count} updated, ` +
          `${result.moved_count} moved, ${result.tombstoned_count} removed, ${result.failed_count} failed.`,
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not refresh local import.");
    } finally {
      setRefreshingImportId(null);
    }
  }

  async function toggleWatchedImport(record: IntegrationImportRecord) {
    try {
      const updated = await updateIntegrationImport(record.id, {
        watch_enabled: !record.watch_enabled,
        watch_interval_seconds: record.watch_interval_seconds || 900,
      });
      setIntegrationImports((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
      setStatusMessage(updated.watch_enabled ? "Watched refresh enabled." : "Watched refresh disabled.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not update watched refresh.");
    }
  }

  async function compactEvidenceRetention() {
    setRetentionBusy(true);
    try {
      const result = await enforceChatEvidenceRetention({
        keep_latest_per_message: retentionPolicy?.default_keep_latest_snapshots_per_message ?? 1,
        excerpt_chars: retentionPolicy?.default_excerpt_chars ?? 240,
      });
      setRetentionResult(result);
      setStatusMessage(
        `Evidence compacted: ${result.compacted_snapshots} snapshots, ${result.trimmed_items} excerpts, ${result.deleted_source_tombstones} tombstones.`,
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not compact chat evidence.");
    } finally {
      setRetentionBusy(false);
    }
  }

  async function pruneStoredQueryEvidence() {
    setRetentionBusy(true);
    try {
      const result = await pruneQueryCache({
        vault_id: backendVault?.id ?? null,
        max_age_days: 30,
        max_items: 500,
        max_payload_bytes: 5_000_000,
      });
      const removed =
        result.deleted_old_or_invalidated + result.deleted_oversized + result.deleted_over_limit;
      setStatusMessage(`Query evidence pruned: ${removed} entries removed.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not prune query evidence.");
    } finally {
      setRetentionBusy(false);
    }
  }

  const suggestedModel = models[0];
  const activeChatModel = models.find((model) => model.active_chat) ?? null;
  const activeExpertModel = models.find((model) => model.active_expert) ?? null;

  return (
    <div className="vault-page-wash grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[205px_1fr_326px]">
      <aside className="hidden border-r border-border px-5 py-9 xl:block">
        <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Settings
        </div>
        <div className="mt-5 space-y-1">
          {settingsSections.map((section) => {
            const Icon = section.icon;
            const active = activeSection === section.id;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className={
                  "flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-colors " +
                  (active ? "bg-sidebar-accent text-foreground" : "text-muted-foreground hover:bg-card")
                }
              >
                <Icon className="h-4 w-4" />
                {section.label}
              </button>
            );
          })}
        </div>
      </aside>

      <main className="min-w-0 overflow-y-auto px-7 py-9">
        <header>
          <h1 className="page-title">Settings</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Local models, storage, privacy, and maintenance.
          </p>
        </header>

        <div className="mt-7 space-y-4">
          {activeSection === "profile" ? (
            <ProfileSettings vaultPath={backendVault?.path ?? ""} />
          ) : (
            <>
          {statusMessage && (
            <div className="rounded-md border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
              {statusMessage}
            </div>
          )}

          <SettingsCard
            icon={<TerminalSquare className="h-4 w-4" />}
            title="Synthesis runtime"
            description="Endpoint used for responses and tool execution."
            status={runtime?.available ? "Ready" : "Missing"}
            statusTone={runtime?.available ? "ready" : "issue"}
          >
            <label className="mt-5 block text-sm font-medium">Endpoint (required)</label>
            <div className="mt-2 flex gap-2">
              <Input value={runtime?.base_url ?? "http://localhost:11434"} readOnly />
              <Button variant="outline" className="gap-2">Test <Play className="h-4 w-4" /></Button>
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<MessageSquare className="h-4 w-4" />}
            title="Chat and expert models"
            description="Chat uses a local runtime model. Expert workflows use a separate accepted checkpoint."
            status={activeChatModel && activeExpertModel ? "Configured" : "Required"}
            statusTone={activeChatModel && activeExpertModel ? "ready" : "issue"}
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              {activeChatModel && activeExpertModel
                ? `Chat: ${activeChatModel.name}. Expert: ${activeExpertModel.name}. Retrieval remains the citation source.`
                : "Pick one accepted chat model and one accepted expert checkpoint. GGUF/runtime downloads satisfy the chat role only."}
            </div>
            <div className="mt-5 space-y-3">
              {models.map((model) => {
                const downloading = model.download?.status === "resolving" || model.download?.status === "downloading";
                return (
                  <div key={model.id} className="rounded-md border border-border bg-background px-3 py-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-medium">{model.name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {model.role} / {model.family || "unclassified"} / {model.approximate_download_gb} GB
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          chat: {model.compatibility?.chat_role_accepted ? "accepted" : "not accepted"} / expert: {model.compatibility?.expert_role_accepted ? "accepted" : "not accepted"}
                        </div>
                      </div>
                      {model.active_chat || model.active_expert ? (
                        <span className="text-primary">
                          {model.active_chat && model.active_expert
                            ? "Chat + Expert"
                            : model.active_chat
                              ? "Chat"
                              : "Expert"}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {!model.installed ? (
                        <Button variant="outline" onClick={() => void downloadModel(model.id)} disabled={downloadingId === model.id}>
                          {downloadingId === model.id ? "Starting..." : "Download default"}
                        </Button>
                      ) : null}
                      {downloading ? (
                        <Button variant="outline" onClick={() => void cancelDownload(model.id)}>
                          Cancel
                        </Button>
                      ) : null}
                      {model.compatibility?.chat_role_accepted && !model.active_chat ? (
                        <Button variant="outline" onClick={() => void activateModel(model.id, "chat")} disabled={activatingId === model.id}>
                          {activatingId === model.id ? "Activating..." : "Use for chat"}
                        </Button>
                      ) : null}
                      {model.compatibility?.expert_role_accepted && !model.active_expert ? (
                        <Button variant="outline" onClick={() => void activateModel(model.id, "expert")} disabled={activatingId === model.id}>
                          {activatingId === model.id ? "Activating..." : "Use for expert"}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-[1fr_220px_auto_auto]">
              <Input
                value={customModelPath}
                onChange={(event) => setCustomModelPath(event.target.value)}
                placeholder="D:\\Models\\Qwen3-4B"
              />
              <Input
                value={customModelName}
                onChange={(event) => setCustomModelName(event.target.value)}
                placeholder="Imported checkpoint"
              />
              <Button variant="outline" onClick={() => void chooseModelFolder()}>
                Browse
              </Button>
              <Button variant="outline" onClick={() => void validateCustomModel()} disabled={!customModelPath.trim()}>
                Validate
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => void importApprovedModel()} disabled={!customModelReport?.accepted}>
                Import approved model
              </Button>
            </div>
            {customModelReport && (
              <div className="mt-4 rounded-md border border-border bg-background px-3 py-3 text-sm">
                <div className="font-medium">{customModelReport.accepted ? "Accepted" : "Rejected"}</div>
                <div className="mt-1 text-muted-foreground">{customModelReport.detail}</div>
                <div className="mt-1 text-xs text-muted-foreground">{customModelReport.pairing_detail}</div>
              </div>
            )}
          </SettingsCard>

          <SettingsCard
            icon={<Layers className="h-4 w-4" />}
            title="Embedding model"
            description="Model used to create vector embeddings for semantic search."
            status={embeddingRuntime?.available ? "Ready" : "Required"}
            statusTone={embeddingRuntime?.available ? "ready" : "issue"}
          >
            {!embeddingRuntime?.available && (
              <div className="mt-5 rounded-md border border-[var(--status-learning)]/35 bg-[var(--status-learning)]/10 px-3 py-2 text-sm">
                Semantic search, clustering, retrieval chat, Bridge retrieval, and new indexing are blocked until this local model test passes.
              </div>
            )}
            <label className="mt-5 block text-sm font-medium">Model path (required)</label>
            <div className="mt-2 flex flex-wrap gap-2">
              <Input
                value={embeddingCacheDraft}
                onChange={(event) => setEmbeddingCacheDraft(event.target.value)}
                placeholder="C:\\AI_Models\\all-MiniLM-L6-v2"
              />
              <Button variant="outline" onClick={() => void chooseEmbeddingFolder()} disabled={!desktop?.selectEmbeddingFolder}>
                Browse
              </Button>
              <Button variant="outline" onClick={() => void saveEmbeddingRuntime()} disabled={saving || !embeddingCacheDraft.trim()}>
                Test
              </Button>
              <Button variant="outline" className="gap-2" onClick={() => void downloadEmbeddingModel()} disabled={saving}>
                <Download className="h-4 w-4" />
                Download recommended
              </Button>
              {embeddingDownload?.status === "queued" || embeddingDownload?.status === "downloading" ? (
                <Button variant="ghost" onClick={() => void cancelEmbeddingModelDownload()}>
                  Cancel
                </Button>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Choose the folder containing `modules.json` or `config.json` for the local SentenceTransformers model.
            </p>
            {embeddingDownload && embeddingDownload.status !== "idle" && (
              <div className="mt-4 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                <div className="flex items-center justify-between gap-3">
                  <span>{embeddingDownload.model_id}</span>
                  <span className="text-foreground">{embeddingDownload.status}</span>
                </div>
                {embeddingDownload.local_path && (
                  <div className="mt-1 truncate font-mono">{embeddingDownload.local_path}</div>
                )}
                {embeddingDownload.error && (
                  <div className="mt-1 text-destructive">{embeddingDownload.error}</div>
                )}
              </div>
            )}
          </SettingsCard>

          <SettingsCard
            icon={<Settings2 className="h-4 w-4" />}
            title="OCR"
            description="Local OCR for scanned documents and images."
            status={ocrRuntime?.available ? "Ready" : "Missing"}
            statusTone={ocrRuntime?.available ? "ready" : "issue"}
          >
            <RuntimeRow label="Image OCR" value={ocrRuntime?.image_ocr_available ? "Ready" : "Missing"} meta={ocrRuntime?.tesseract_path ?? ""} />
            <RuntimeRow label="PDF OCR" value={ocrRuntime?.pdf_ocr_available ? "Ready" : "Missing"} meta={ocrRuntime?.pdf_ocr_engine ?? ""} />
            <RuntimeRow label="OCRmyPDF" value={ocrRuntime?.full_pdf_ocr_available ? "Ready" : "Fallback"} meta={ocrRuntime?.ocrmypdf_command ?? ""} />
            <RuntimeRow label="Ghostscript" value={ocrRuntime?.ghostscript_path ? "Installed" : "Missing"} meta={ocrRuntime?.ghostscript_path ?? ""} />
            <RuntimeRow label="qpdf" value={ocrRuntime?.qpdf_path ? "Installed" : "Missing"} meta={ocrRuntime?.qpdf_path ?? ""} />
            {ocrRuntime?.missing.length ? (
              <p className="mt-4 text-xs text-muted-foreground">Missing: {ocrRuntime.missing.join(", ")}</p>
            ) : null}
          </SettingsCard>

          <SettingsCard
            icon={<Database className="h-4 w-4" />}
            title="Disk usage"
            description="Manage local data and model storage."
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              Disk usage is not exposed by the backend yet. Vault storage is configured at{" "}
              <span className="text-foreground">{pathDraft || "No vault selected"}</span>.
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<Lock className="h-4 w-4" />}
            title="Evidence retention"
            description="Compact saved retrieval evidence without deleting chat messages."
            status={retentionPolicy ? "Policy loaded" : "Unavailable"}
            statusTone={retentionPolicy ? "ready" : "issue"}
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              Keeps the latest {retentionPolicy?.default_keep_latest_snapshots_per_message ?? 1} retrieval snapshot per message and trims excerpts to{" "}
              {retentionPolicy?.default_excerpt_chars ?? 240} characters. Deleted source references are tombstoned.
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void compactEvidenceRetention()} disabled={retentionBusy || !retentionPolicy}>
                Compact chat evidence
              </Button>
              <Button variant="outline" onClick={() => void pruneStoredQueryEvidence()} disabled={retentionBusy}>
                Prune query cache
              </Button>
            </div>
            {retentionResult && (
              <p className="mt-3 text-xs text-muted-foreground">
                Last run: {retentionResult.compacted_snapshots} snapshots compacted, {retentionResult.trimmed_items} excerpts trimmed.
              </p>
            )}
          </SettingsCard>

          <SettingsCard
            icon={<Folder className="h-4 w-4" />}
            title="Local imports"
            description="Manual refresh and reconciliation for local, synced-folder, and Obsidian imports."
            status={integrationImports.length ? `${integrationImports.length} tracked` : "None"}
          >
            <div className="mt-5 space-y-2">
              {integrationImports.length === 0 ? (
                <div className="rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
                  No local folder imports are tracked for this vault yet.
                </div>
              ) : (
                integrationImports.map((record) => (
                  <div
                    key={record.id}
                    className="grid gap-3 rounded-md border border-border bg-background px-3 py-3 text-sm md:grid-cols-[1fr_auto]"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{record.root_path}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {record.integration_type} · {record.supported_count} supported · {record.skipped_count} skipped ·{" "}
                        {record.imported_count} new · {record.updated_count} updated · {record.moved_count} moved ·{" "}
                        {record.tombstoned_count} removed · {record.failed_count} failed
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Watch: {record.watch_enabled ? "on" : "off"}
                        {record.next_watch_at ? ` · next ${new Date(record.next_watch_at).toLocaleString()}` : ""}
                        {record.last_failures.length ? ` · ${record.last_failures.length} recent failure(s)` : ""}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        className="gap-2"
                        onClick={() => void refreshLocalImport(record.id)}
                        disabled={refreshingImportId === record.id}
                      >
                        <RefreshCw className="h-4 w-4" />
                        {refreshingImportId === record.id ? "Refreshing..." : "Refresh + import"}
                      </Button>
                      <Button variant="outline" onClick={() => void toggleWatchedImport(record)}>
                        {record.watch_enabled ? "Stop watch" : "Watch"}
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<Activity className="h-4 w-4" />}
            title="Diagnostics"
            description="Collect logs and system information for troubleshooting."
          >
            <Button variant="outline" className="mt-5 gap-2" onClick={() => void exportDiagnostics()}>
              <Download className="h-4 w-4" /> Export diagnostics
            </Button>
          </SettingsCard>
            </>
          )}
        </div>
      </main>

      <aside className="hidden overflow-y-auto border-l border-border bg-card/35 px-6 py-9 xl:block">
        <h2 className="text-lg font-semibold">Device readiness</h2>
        <div className="mt-7 space-y-6">
          <ReadinessRow label="CPU" value={hardware?.avx2 ? "AVX2" : "Unknown"} meta={hardware?.processor ?? "Capability check"} />
          <ReadinessRow
            label="RAM"
            value={hardware?.total_memory_bytes ? `${Math.round(hardware.total_memory_bytes / 1024 / 1024 / 1024)} GB` : "Unknown"}
            meta="Available locally"
          />
          <ReadinessRow label="GPU" value="Optional" meta={hardware?.detail ?? "No dedicated GPU check yet"} />
          <ReadinessRow label="Backend" value="Online" meta={runtime?.base_url ?? "http://localhost:7343"} />
          <ReadinessRow label="Model runtime" value={runtime?.available ? "Ready" : "Missing"} meta={runtime?.available ? "Local runtime ready." : "Start a model server to chat."} warning={!runtime?.available} />
        </div>

        <div className="my-8 h-px bg-border" />
        <h3 className="text-sm font-semibold">Storage location</h3>
        <div className="mt-4 flex items-center gap-2">
          <Input value={pathDraft} onChange={(event) => setPathDraft(event.target.value)} />
          <Button variant="outline" onClick={() => void saveVaultPath()} disabled={saving}>Change...</Button>
        </div>

        <div className="my-8 h-px bg-border" />
        <h3 className="text-sm font-semibold">Privacy & data</h3>
        <div className="mt-5 space-y-4">
          {["All data stays on this device", "No cloud sync or backups", "No telemetry or analytics", "Local models only"].map((item) => (
            <div key={item} className="flex items-center gap-3 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              {item}
            </div>
          ))}
        </div>

        <div className="my-8 h-px bg-border" />
        <h3 className="text-sm font-semibold">Quick actions</h3>
        <div className="mt-4 space-y-2">
          <SideAction icon={<Folder className="h-4 w-4" />} label="Open data folder" />
          <SideAction icon={<Layers className="h-4 w-4" />} label="Rebuild embeddings" />
          <SideAction icon={<MessageSquare className="h-4 w-4" />} label="Clear chat history" />
        </div>

        <div className="my-8 h-px bg-border" />
        <h3 className="text-sm font-semibold">Need help?</h3>
        <button className="mt-4 flex items-center gap-2 text-sm text-primary" type="button">
          Vault docs <ChevronRight className="h-4 w-4" />
        </button>
      </aside>
    </div>
  );
}

function SettingsCard({
  icon,
  title,
  description,
  status,
  statusTone = "ready",
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  status?: string;
  statusTone?: "ready" | "issue";
  children?: ReactNode;
}) {
  return (
    <section className="vault-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-4">
          <span className="mt-0.5 text-muted-foreground">{icon}</span>
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {status && (
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: statusTone === "ready" ? "var(--status-ready)" : "var(--status-learning)" }}
            />
            {status}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function ProfileSettings({ vaultPath }: { vaultPath: string }) {
  const displayName = vaultPath ? vaultName(vaultPath) : "Local profile";
  return (
    <>
      <section className="vault-card p-5">
        <div className="flex flex-wrap items-center gap-5">
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-foreground text-background">
            <UserRound className="h-7 w-7" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold">{displayName}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{vaultPath || "No vault selected"}</p>
            <div className="mt-3 inline-flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-primary">
              <ShieldCheck className="h-3.5 w-3.5" />
              Local profile
            </div>
          </div>
          <Button variant="outline">Change photo</Button>
        </div>
      </section>

      <section className="vault-card p-5">
        <h2 className="text-sm font-semibold">Display name</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This name appears in the sidebar, diagnostics, and local chat transcripts.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <Input value={displayName} readOnly />
          <Button variant="outline">Save</Button>
        </div>
      </section>

      <section className="vault-card p-5">
        <h2 className="text-sm font-semibold">Sign-in methods</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Vault can remember your account identity without syncing private vault data.
        </p>
        <div className="mt-5 divide-y divide-border border-y border-border">
          <ProfileMethod label="Local vault" value={vaultPath || "No vault selected"} status={vaultPath ? "Connected" : "Not set"} />
          <ProfileMethod label="Google OAuth" value="Optional account connection" status="Not connected" />
        </div>
      </section>

      <section className="vault-card p-5">
        <h2 className="text-sm font-semibold">Local privacy</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {[
            "Profile metadata stays on this device",
            "No telemetry is attached to your identity",
            "Vault backups are controlled by you",
            "Cloud connectors require explicit permission",
          ].map((item) => (
            <div key={item} className="flex items-center gap-3 rounded-md bg-background px-3 py-3 text-sm">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              {item}
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function vaultName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function ProfileMethod({ label, value, status }: { label: string; value: string; status: string }) {
  return (
    <div className="grid gap-2 py-3 text-sm md:grid-cols-[160px_1fr_120px]">
      <span className="font-medium">{label}</span>
      <span className="text-muted-foreground">{value}</span>
      <span className="text-primary">{status}</span>
    </div>
  );
}

function RuntimeRow({ label, value, meta }: { label: string; value: string; meta?: string }) {
  return (
    <div className="mt-5 grid grid-cols-[1fr_120px_80px] items-center gap-4 text-sm">
      <span className="font-medium">{label}</span>
      <span className="flex items-center gap-2 text-primary">
        <span className="h-2 w-2 rounded-full bg-primary" />
        {value}
      </span>
      <span className="text-muted-foreground">{meta}</span>
    </div>
  );
}

function ReadinessRow({
  label,
  value,
  meta,
  warning,
}: {
  label: string;
  value: string;
  meta: string;
  warning?: boolean;
}) {
  return (
    <div className="grid grid-cols-[72px_1fr] gap-5 text-sm">
      <span className="font-medium text-muted-foreground">{label}</span>
      <span>
        <span className="flex items-center gap-3">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: warning ? "var(--status-learning)" : "var(--status-ready)" }}
          />
          <span className="font-medium">{value}</span>
        </span>
        <span className="mt-1 block text-xs text-muted-foreground">{meta}</span>
      </span>
    </div>
  );
}

function SideAction({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-left text-sm hover:bg-accent/45"
    >
      {icon}
      <span className="flex-1">{label}</span>
      <ChevronRight className="h-4 w-4 text-muted-foreground" />
    </button>
  );
}
