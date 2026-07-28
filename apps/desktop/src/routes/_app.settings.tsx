import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  Camera,
  Database,
  Download,
  FileText,
  Folder,
  HeartPulse,
  Layers,
  Lock,
  MessageSquare,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  TerminalSquare,
  UserRound,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  activateLocalModel,
  approveModelDiscoveryRoot,
  approveCliPairingChallenge,
  backfillTemporalFacts,
  cancelModelDownload,
  cancelEmbeddingDownload,
  configureEmbeddingRuntime,
  correctTemporalFact,
  createVaultBackup,
  createDiagnosticBundle,
  createVault,
  authorizeVaultDeletion,
  denyCliPairingChallenge,
  discoverInstalledModels,
  enforceChatEvidenceRetention,
  getChatEvidenceRetentionPolicy,
  getEmbeddingRuntimeStatus,
  getEmbeddingDownloadStatus,
  getHardwareStatus,
  getUnlockStatus,
  getModelCompatibilityReport,
  getModelRecommendations,
  importLocalModel,
  initializeVaultSecurity,
  getJobStatus,
  lockVault,
  getModelRuntimeStatus,
  getOCRRuntimeStatus,
  getRetrievalPackingDiagnostics,
  getTemporalFactStatus,
  pruneQueryCache,
  resetVaultPassphrase,
  reindexVaultSearch,
  listLocalModels,
  listIntegrationImports,
  listIntegrationReconciliationItems,
  listIntegrationReconciliationRuns,
  listCliClients,
  listCliPairingChallenges,
  listVaults,
  listProjects,
  listTemporalFacts,
  refreshIntegrationImport,
  retractTemporalFact,
  revokeCliClient,
  retryIntegrationReconciliationItem,
  rotateCliClient,
  startModelDownload,
  startEmbeddingDownload,
  unlockVaultWithPassphrase,
  updateIntegrationImport,
  updateVault,
  useBackendHealth,
  type ChatEvidenceRetentionPolicy,
  type ChatEvidenceRetentionResult,
  type EmbeddingRuntimeStatus,
  type EmbeddingModelDownloadState,
  type HardwareStatusRead,
  type CliClientRecord,
  type CliPairingChallenge,
  type IntegrationImportRecord,
  type JobQueueStatus,
  type DiscoveredInstalledModelRecord,
  type LocalModelRecord,
  type ModelCompatibilityRecord,
  type ModelRecommendationsRecord,
  type ModelRuntimeStatus,
  type OCRRuntimeStatusRead,
  type ProjectRecord,
  type RetrievalPackingDiagnostics,
  type ReconciliationItemPage,
  type ReconciliationRunRecord,
  type TemporalFactDiagnostics,
  type TemporalFactRecord,
  type UnlockStatusRead,
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
import { displayPath } from "@/lib/displayPath";
import { isModelRuntimeReady, modelReadinessLabel } from "@/lib/modelState";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import { useLocalImage } from "@/lib/useLocalImage";
import { cn } from "@/lib/utils";
import {
  normalizeDesktopProfile,
  profileDisplayName,
  saveDesktopProfile,
  subscribeDesktopProfile,
  type DesktopProfile,
} from "@/lib/profileState";

export const Route = createFileRoute("/_app/settings")({
  validateSearch: (search: Record<string, unknown>): { section?: string } => ({
    section: typeof search.section === "string" ? search.section : undefined,
  }),
  head: () => ({ meta: [{ title: "Settings" }] }),
  component: SettingsView,
});

const settingsSections = [
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "library", label: "Library & security", icon: Database },
  { id: "models", label: "Models & search", icon: TerminalSquare },
  { id: "connections", label: "Code connections", icon: Folder },
  { id: "health", label: "System health", icon: HeartPulse },
  { id: "advanced", label: "Advanced", icon: SlidersHorizontal },
] as const;

const settingsAliases: Record<string, (typeof settingsSections)[number]["id"]> = {
  storage: "library",
  privacy: "library",
  embeddings: "models",
  ocr: "models",
  odin: "connections",
  diagnostics: "advanced",
};

function canonicalSettingsSection(value?: string) {
  const candidate = value ? settingsAliases[value] ?? value : "profile";
  return settingsSections.some((item) => item.id === candidate)
    ? (candidate as (typeof settingsSections)[number]["id"])
    : "profile";
}

function SettingsView() {
  const { section } = Route.useSearch();
  const navigate = useNavigate();
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const backendHealth = useBackendHealth();
  const [mounted, setMounted] = useState(false);
  const [activeSection, setActiveSection] = useState(() => canonicalSettingsSection(section));
  const [backendVault, setBackendVault] = useState<VaultRecord | null>(null);
  const [pathDraft, setPathDraft] = useState("");
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [modelRecommendations, setModelRecommendations] = useState<ModelRecommendationsRecord | null>(null);
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingDownload, setEmbeddingDownload] = useState<EmbeddingModelDownloadState | null>(null);
  const [embeddingCacheDraft, setEmbeddingCacheDraft] = useState("");
  const [ocrRuntime, setOcrRuntime] = useState<OCRRuntimeStatusRead | null>(null);
  const [hardware, setHardware] = useState<HardwareStatusRead | null>(null);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [temporalFacts, setTemporalFacts] = useState<TemporalFactDiagnostics | null>(null);
  const [reviewableFacts, setReviewableFacts] = useState<TemporalFactRecord[]>([]);
  const [retrievalPacking, setRetrievalPacking] = useState<RetrievalPackingDiagnostics | null>(null);
  const [temporalBackfillBusy, setTemporalBackfillBusy] = useState(false);
  const [editingFactId, setEditingFactId] = useState<string | null>(null);
  const [factCorrectionDraft, setFactCorrectionDraft] = useState("");
  const [factReviewBusyId, setFactReviewBusyId] = useState<string | null>(null);
  const [retractConfirmId, setRetractConfirmId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [cliPairings, setCliPairings] = useState<CliPairingChallenge[]>([]);
  const [cliClients, setCliClients] = useState<CliClientRecord[]>([]);
  const [cliAccessBusyId, setCliAccessBusyId] = useState<string | null>(null);
  const [cliAccessError, setCliAccessError] = useState<string | null>(null);
  const [odinLauncher, setOdinLauncher] = useState<{
    launcher_path: string;
    installed: boolean;
    needs_repair: boolean;
  } | null>(null);
  const [odinLauncherBusy, setOdinLauncherBusy] = useState(false);
  const [integrationImports, setIntegrationImports] = useState<IntegrationImportRecord[]>([]);
  const [reconciliationRunsByImport, setReconciliationRunsByImport] = useState<Record<string, ReconciliationRunRecord[]>>({});
  const [reconciliationItemsByRun, setReconciliationItemsByRun] = useState<Record<string, ReconciliationItemPage>>({});
  const [expandedImportId, setExpandedImportId] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [retentionPolicy, setRetentionPolicy] = useState<ChatEvidenceRetentionPolicy | null>(null);
  const [retentionResult, setRetentionResult] = useState<ChatEvidenceRetentionResult | null>(null);
  const [unlockStatus, setUnlockStatus] = useState<UnlockStatusRead | null>(null);
  const [vaultPassphrase, setVaultPassphrase] = useState("");
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);
  const [recoveryKeyDraft, setRecoveryKeyDraft] = useState("");
  const [newPassphraseDraft, setNewPassphraseDraft] = useState("");
  const [newPassphraseConfirm, setNewPassphraseConfirm] = useState("");
  const [refreshingImportId, setRefreshingImportId] = useState<string | null>(null);
  const [loadingImportHistoryId, setLoadingImportHistoryId] = useState<string | null>(null);
  const [loadingRunItemsId, setLoadingRunItemsId] = useState<string | null>(null);
  const [retryingReconciliationItemId, setRetryingReconciliationItemId] = useState<string | null>(null);
  const [retentionBusy, setRetentionBusy] = useState(false);
  const [busyActions, setBusyActions] = useState<Set<string>>(() => new Set());
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [healthLoadError, setHealthLoadError] = useState<string | null>(null);
  const [healthCheckedAt, setHealthCheckedAt] = useState<Date | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [modelDownload, setModelDownload] = useState<LocalModelRecord["download"] | null>(null);
  const [modelDownloadRoot, setModelDownloadRoot] = useState("");
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [customModelPath, setCustomModelPath] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelReport, setCustomModelReport] = useState<ModelCompatibilityRecord | null>(null);
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredInstalledModelRecord[]>([]);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteNameDraft, setDeleteNameDraft] = useState("");
  const [deletePassphrase, setDeletePassphrase] = useState("");
  const [destructiveAction, setDestructiveAction] = useState<"delete" | "restart">("delete");
  const [profile, setProfile] = useState<DesktopProfile>(() => normalizeDesktopProfile(null));
  const pathDraftDirtyRef = useRef(false);
  const embeddingDraftDirtyRef = useRef(false);

  const activeModelDownload = useMemo(() => selectVisibleModelDownload(models, modelDownload), [modelDownload, models]);
  const modelDownloadActive = isActiveModelDownloadStatus(activeModelDownload?.status);
  const embeddingDownloadActive =
    embeddingDownload?.status === "queued" ||
    embeddingDownload?.status === "downloading" ||
    embeddingDownload?.status === "cancelling";
  const isActionBusy = (action: string) => busyActions.has(action);

  function setActionBusy(action: string, busy: boolean) {
    setBusyActions((current) => {
      const next = new Set(current);
      if (busy) next.add(action);
      else next.delete(action);
      return next;
    });
  }

  useEffect(() => {
    setMounted(true);
    void desktop?.getSetupState?.().then((state) => {
      setProfile(normalizeDesktopProfile(state?.profile));
      setModelDownloadRoot(state?.model_storage.download_root ?? "");
    });
    return subscribeDesktopProfile(setProfile);
  }, []);

  useEffect(() => {
    const nextSection = canonicalSettingsSection(section);
    setActiveSection(nextSection);
  }, [section]);

  function selectSettingsSection(nextSection: string) {
    const validSection = canonicalSettingsSection(nextSection);
    setActiveSection(validSection);
    void navigate({
      to: "/settings",
      search: { section: validSection },
      replace: true,
    });
  }

  const refreshCliAccess = useCallback(async () => {
    const [pairings, clients] = await Promise.allSettled([
      listCliPairingChallenges(),
      listCliClients(),
    ]);
    const failures: string[] = [];
    if (pairings.status === "fulfilled") setCliPairings(pairings.value);
    else failures.push("pairing requests");
    if (clients.status === "fulfilled") setCliClients(clients.value);
    else failures.push("connected clients");
    setCliAccessError(
      failures.length ? `Could not refresh ${failures.join(" and ")}.` : null,
    );
  }, []);

  useVisiblePolling(
    refreshCliAccess,
    2000,
    activeSection === "connections" && Boolean(backendVault),
  );

  useEffect(() => {
    if (activeSection !== "connections") return;
    void desktop?.getOdinLauncherStatus?.()
      .then(setOdinLauncher)
      .catch(() => setOdinLauncher(null));
  }, [activeSection, desktop]);

  const loadSettings = useCallback(async () => {
      try {
        const currentUnlock = await getUnlockStatus();
        setHealthLoadError(null);
        setUnlockStatus(currentUnlock);
        if (currentUnlock.secured_vault_count > 0 && currentUnlock.state !== "ready") {
          const vaultRows = await listVaults();
          const firstVault = vaultRows[0] ?? null;
          setBackendVault(firstVault ? { ...firstVault, path: "" } : null);
          setTemporalFacts(null);
          setReviewableFacts([]);
          setRetrievalPacking(null);
          if (!pathDraftDirtyRef.current) setPathDraft("");
          setHealthCheckedAt(new Date());
          setStatusMessage(currentUnlock.message || "Library is locked. Unlock it from Privacy settings.");
          return;
        }
        const results = await Promise.allSettled([
          listVaults(),
          listLocalModels(),
          getModelRecommendations(),
          discoverInstalledModels({ max_results: 24 }),
          getModelRuntimeStatus(),
          getEmbeddingRuntimeStatus(),
          getEmbeddingDownloadStatus(),
          getOCRRuntimeStatus(),
          getHardwareStatus(),
          getJobStatus(),
          getChatEvidenceRetentionPolicy(),
        ]);
        const failures: string[] = [];
        const readResult = <T,>(index: number, label: string): T | undefined => {
          const result = results[index] as PromiseSettledResult<T>;
          if (result.status === "fulfilled") return result.value;
          failures.push(label);
          return undefined;
        };
        const vaultRows = readResult<VaultRecord[]>(0, "library");
        const modelRows = readResult<LocalModelRecord[]>(1, "models");
        const recommendations = readResult<ModelRecommendationsRecord>(2, "recommendations");
        const discoveredRows = readResult<{ models: DiscoveredInstalledModelRecord[] }>(3, "model scan");
        const runtimeStatus = readResult<ModelRuntimeStatus>(4, "model runtime");
        const embeddingStatus = readResult<EmbeddingRuntimeStatus>(5, "memory search");
        const embeddingDownloadStatus = readResult<EmbeddingModelDownloadState>(6, "memory download");
        const ocrStatus = readResult<OCRRuntimeStatusRead>(7, "document reading");
        const hardwareStatus = readResult<HardwareStatusRead>(8, "hardware");
        const jobStatus = readResult<JobQueueStatus>(9, "tasks");
        const evidencePolicy = readResult<ChatEvidenceRetentionPolicy>(10, "chat evidence");
        const firstVault = vaultRows?.[0];
        if (vaultRows) {
          setBackendVault(firstVault ?? null);
          if (firstVault && !pathDraftDirtyRef.current) setPathDraft(firstVault.path);
        }
        if (firstVault) {
          const dependent = await Promise.allSettled([
              listIntegrationImports(firstVault.id),
              listProjects(firstVault.id),
              getTemporalFactStatus(firstVault.id),
              listTemporalFacts(firstVault.id),
              getRetrievalPackingDiagnostics(firstVault.id),
          ]);
          const readDependent = <T,>(index: number, label: string): T | undefined => {
            const result = dependent[index] as PromiseSettledResult<T>;
            if (result.status === "fulfilled") return result.value;
            failures.push(label);
            return undefined;
          };
          const importRows = readDependent<IntegrationImportRecord[]>(0, "connections");
          const projectRows = readDependent<ProjectRecord[]>(1, "projects");
          const temporalStatus = readDependent<TemporalFactDiagnostics>(2, "memory status");
          const factRows = readDependent<TemporalFactRecord[]>(3, "memory facts");
          const packingStatus = readDependent<RetrievalPackingDiagnostics>(4, "retrieval");
          if (importRows) setIntegrationImports(importRows);
          if (projectRows) setProjects(projectRows);
          if (temporalStatus) setTemporalFacts(temporalStatus);
          if (factRows) setReviewableFacts(factRows);
          if (packingStatus) setRetrievalPacking(packingStatus);
        }
        if (modelRows) setModels(modelRows);
        if (recommendations) setModelRecommendations(recommendations);
        if (discoveredRows) setDiscoveredModels(discoveredRows.models);
        if (runtimeStatus) setRuntime(runtimeStatus);
        if (embeddingStatus) setEmbeddingRuntime(embeddingStatus);
        if (embeddingStatus && !embeddingDraftDirtyRef.current) {
          setEmbeddingCacheDraft(embeddingStatus.cache_dir ?? "");
        }
        if (embeddingDownloadStatus) setEmbeddingDownload(embeddingDownloadStatus);
        if (ocrStatus) setOcrRuntime(ocrStatus);
        if (hardwareStatus) setHardware(hardwareStatus);
        if (jobStatus) setJobs(jobStatus);
        if (evidencePolicy) setRetentionPolicy(evidencePolicy);
        setHealthLoadError(
          failures.length ? `Some settings could not refresh: ${failures.join(", ")}.` : null,
        );
        setHealthCheckedAt(new Date());
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Vault settings are unavailable. Check Health and try again.";
        setHealthLoadError(message);
        setHealthCheckedAt(new Date());
        setStatusMessage(message);
      }
  }, []);

  useVisiblePolling(loadSettings, 6000);
  useVisiblePolling(refreshModelRows, 750, modelDownloadActive);
  useVisiblePolling(refreshEmbeddingRows, 750, embeddingDownloadActive);

  async function refreshEmbeddingRows() {
    const download = await getEmbeddingDownloadStatus();
    setEmbeddingDownload(download);
    if (!["queued", "downloading", "cancelling"].includes(download.status)) {
      setEmbeddingRuntime(await getEmbeddingRuntimeStatus());
    }
  }

  async function unlockVault() {
    const vaultId = backendVault?.id ?? unlockStatus?.secured_vault_ids[0];
    if (!vaultId || !vaultPassphrase.trim()) {
      setUnlockError(
        vaultId
          ? "Enter your library passphrase."
          : "Choose a library before unlocking.",
      );
      return;
    }
    setUnlockError(null);
    setActionBusy("security", true);
    try {
      const next = unlockStatus?.secured_vault_count
        ? await unlockVaultWithPassphrase({ vault_id: vaultId, passphrase: vaultPassphrase })
        : await initializeVaultSecurity({ vault_id: vaultId, passphrase: vaultPassphrase, unlock_mode: "strict" });
      setUnlockStatus(next);
      window.dispatchEvent(new CustomEvent("vault:lock-state", { detail: next }));
      const recoveryKey = "recovery_key" in next && typeof next.recovery_key === "string" ? next.recovery_key : null;
      if (recoveryKey) setRecoveryKey(recoveryKey);
      setVaultPassphrase("");
      setUnlockError(null);
      setStatusMessage(next.state === "ready" ? "Library ready." : next.message);
    } catch (error) {
      setUnlockError(
        error instanceof Error ? error.message : "Could not unlock library.",
      );
    } finally {
      setActionBusy("security", false);
    }
  }

  async function lockCurrentVault() {
    setActionBusy("security", true);
    try {
      const next = await lockVault(unlockStatus?.vault_id ?? backendVault?.id ?? null);
      setUnlockStatus(next);
      window.dispatchEvent(new CustomEvent("vault:lock-state", { detail: next }));
      setStatusMessage("Library locked.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not lock library.");
    } finally {
      setActionBusy("security", false);
    }
  }

  async function saveVaultPath() {
    const path = pathDraft.trim();
    if (!path) return;
    if (backendVault && displayPath(backendVault.path) === displayPath(path)) {
      pathDraftDirtyRef.current = false;
      setStatusMessage("Library location is already current.");
      return;
    }
    if (
      backendVault &&
      !window.confirm(
        "Move this library to the selected folder? Vault will verify the copied database before switching and will roll back if startup fails.",
      )
    ) {
      return;
    }
    setActionBusy("vault-path", true);
    try {
      let oldCopyRemoved = true;
      if (backendVault) {
        const moved = await desktop?.moveActiveVaultFolder?.(path);
        if (!moved) {
          throw new Error("Library moves are available only in the installed desktop app.");
        }
        oldCopyRemoved = moved.old_copy_removed;
      }
      const nextVault = backendVault
        ? await updateVault(backendVault.id, { path })
        : await createVault({ name: "Local memory", path });
      setBackendVault(nextVault);
      setPathDraft(nextVault.path);
      pathDraftDirtyRef.current = false;
      setStatusMessage(
        oldCopyRemoved
          ? "Library moved and verified."
          : "Library moved and verified. The old data copy could not be removed; you may remove it after checking the new location.",
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not save library location.");
    } finally {
      setActionBusy("vault-path", false);
    }
  }

  async function saveEmbeddingRuntime() {
    const modelPath = embeddingCacheDraft.trim();
    if (!modelPath) {
      setStatusMessage("Choose the local embedding model folder before saving.");
      return;
    }
    setActionBusy("embedding-runtime", true);
    try {
      const nextStatus = await configureEmbeddingRuntime({
        provider: "sentence-transformers",
        cache_dir: modelPath,
      });
      setEmbeddingRuntime(nextStatus);
      embeddingDraftDirtyRef.current = false;
      setStatusMessage("Embedding model path saved.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not update embedding settings.");
    } finally {
      setActionBusy("embedding-runtime", false);
    }
  }

  async function chooseEmbeddingFolder() {
    const selected = await desktop?.selectEmbeddingFolder?.();
    if (selected) {
      setEmbeddingCacheDraft(selected);
      embeddingDraftDirtyRef.current = true;
      setStatusMessage("Embedding model folder selected. Test it before using memory search.");
    }
  }

  async function downloadEmbeddingModel() {
    setActionBusy("embedding-download", true);
    try {
      const state = await startEmbeddingDownload({
        cache_dir: embeddingCacheDraft.trim() || null,
      });
      setEmbeddingDownload(state);
      setStatusMessage("Embedding model download started.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not start embedding download.");
    } finally {
      setActionBusy("embedding-download", false);
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
      const state = await startModelDownload(modelId, {
        target_dir: modelDownloadRoot.trim() || null,
      });
      setModelDownload(state);
      await refreshModelRows();
      setStatusMessage(state.status === "failed" ? state.error : "Model download started.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not start model download.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function activateModel(
    modelId: string,
    messages?: { success?: string; importedName?: string },
  ) {
    setActivatingId(modelId);
    try {
      const activated = await activateLocalModel(modelId, "chat");
      setModels((current) => {
        const found = current.some((model) => model.id === activated.id);
        return found
          ? current.map((model) => (model.id === activated.id ? activated : model))
          : [...current, activated];
      });
      const [nextRuntime] = await Promise.all([
        getModelRuntimeStatus(),
        refreshModelRows(),
      ]);
      setRuntime(nextRuntime);
      if (!isModelRuntimeReady(activated, nextRuntime)) {
        throw new Error(nextRuntime.error || "Vault could not confirm that the chat model is ready.");
      }
      setStatusMessage(messages?.success ?? "Chat model is ready.");
      return true;
    } catch (error) {
      await refreshModelRows();
      const detail = error instanceof Error ? error.message : "Could not start the chat model.";
      setStatusMessage(
        messages?.importedName
          ? `${messages.importedName} was added, but it could not start. ${detail}`
          : detail,
      );
      return false;
    } finally {
      setActivatingId(null);
    }
  }

  async function chooseModelFolder() {
    const selected = await desktop?.selectModelCheckpoint?.();
    if (selected) {
      setCustomModelPath(selected);
      setCustomModelReport(null);
    }
  }

  async function chooseModelDownloadFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (selected) {
      setModelDownloadRoot(selected);
      await desktop?.updateSetupState?.({
        model_storage: { download_root: selected },
      });
      await approveModelDiscoveryRoot(selected);
      setStatusMessage("Model download location selected.");
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
      setStatusMessage("Adding model...");
      const imported = await importLocalModel({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      await refreshModelRows();
      setCustomModelReport(imported.compatibility);
      if (isModelRuntimeReady(imported, runtime)) {
        setStatusMessage(`${imported.name} is already ready for chat.`);
        return;
      }
      setStatusMessage(`${imported.name} was added. Starting it now...`);
      await activateModel(imported.id, {
        success: `${imported.name} is ready for chat.`,
        importedName: imported.name,
      });
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not import model.");
    }
  }

  async function scanInstalledModels() {
    setDiscoveringModels(true);
    try {
      const discovered = await discoverInstalledModels({ max_results: 24, refresh: true });
      setDiscoveredModels(discovered.models);
      setStatusMessage(
        discovered.models.length
          ? `Found ${discovered.models.length} compatible local checkpoint${discovered.models.length === 1 ? "" : "s"}.`
          : "No accepted local Transformers checkpoints were found in the scanned folders.",
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not scan for installed models.");
    } finally {
      setDiscoveringModels(false);
    }
  }

  async function importDiscoveredModel(model: DiscoveredInstalledModelRecord) {
    try {
      setStatusMessage(`Adding ${model.name}...`);
      const imported = await importLocalModel({
        path: model.local_path,
        name: model.name,
      });
      await refreshModelRows();
      setCustomModelReport(imported.compatibility);
      const discovery = await discoverInstalledModels({ max_results: 24, refresh: true });
      setDiscoveredModels(discovery.models);
      if (isModelRuntimeReady(imported, runtime)) {
        setStatusMessage(`${imported.name} is already ready for chat.`);
        return;
      }
      setStatusMessage(`${imported.name} was added. Starting it now...`);
      await activateModel(imported.id, {
        success: `${imported.name} is ready for chat.`,
        importedName: imported.name,
      });
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not import detected model.");
    }
  }

  async function cancelDownload(modelId: string) {
    try {
      setModelDownload(await cancelModelDownload(modelId));
      await refreshModelRows();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not cancel model download.");
    }
  }

  async function refreshModelRows() {
    const [modelsResult, recommendationsResult] = await Promise.allSettled([
      listLocalModels(),
      getModelRecommendations(),
    ]);
    if (modelsResult.status === "fulfilled") {
      const modelRows = modelsResult.value;
      setModels(modelRows);
      setModelDownload((current) => {
        const active = modelRows
          .map((row) => row.download)
          .find((download) => isActiveModelDownloadStatus(download?.status));
        if (!current) return active ?? null;
        return modelRows.find((row) => row.id === current.model_id)?.download ?? current;
      });
    }
    if (recommendationsResult.status === "fulfilled") {
      setModelRecommendations(recommendationsResult.value);
    }
  }

  async function exportDiagnostics() {
    setStatusMessage("Creating diagnostic bundle...");
    try {
      const bundle = await createDiagnosticBundle();
      setStatusMessage(`Diagnostic bundle saved to ${displayPath(bundle.bundle_path)}`);
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
      await reloadIntegrationImports();
      if (result.reconciliation_run_id) {
        const runs = await listIntegrationReconciliationRuns(importId, 5);
        setReconciliationRunsByImport((current) => ({ ...current, [importId]: runs }));
      }
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

  async function reloadIntegrationImports() {
    if (!backendVault) {
      setIntegrationImports([]);
      return;
    }
    setIntegrationImports(await listIntegrationImports(backendVault.id));
  }

  async function toggleImportHistory(importId: string) {
    if (expandedImportId === importId) {
      setExpandedImportId(null);
      setExpandedRunId(null);
      return;
    }
    setExpandedImportId(importId);
    setExpandedRunId(null);
    setLoadingImportHistoryId(importId);
    try {
      const runs = await listIntegrationReconciliationRuns(importId, 5);
      setReconciliationRunsByImport((current) => ({ ...current, [importId]: runs }));
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not load reconciliation history.");
    } finally {
      setLoadingImportHistoryId(null);
    }
  }

  async function loadReconciliationItems(run: ReconciliationRunRecord, append = false) {
    const current = reconciliationItemsByRun[run.id];
    const offset = append && current ? current.items.length : 0;
    const resultFilter = run.failed_count > 0 ? "failed" : undefined;
    setLoadingRunItemsId(run.id);
    try {
      const page = await listIntegrationReconciliationItems(run.id, {
        limit: 25,
        offset,
        result: resultFilter,
      });
      setExpandedRunId(run.id);
      setReconciliationItemsByRun((existing) => ({
        ...existing,
        [run.id]:
          append && current
            ? { ...page, items: [...current.items, ...page.items] }
            : page,
      }));
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not load reconciliation details.");
    } finally {
      setLoadingRunItemsId(null);
    }
  }

  async function retryReconciliationItem(importId: string, itemId: string) {
    setRetryingReconciliationItemId(itemId);
    try {
      const result = await retryIntegrationReconciliationItem(itemId);
      await reloadIntegrationImports();
      const runs = await listIntegrationReconciliationRuns(importId, 5);
      setReconciliationRunsByImport((current) => ({ ...current, [importId]: runs }));
      setExpandedImportId(importId);
      setExpandedRunId(result.new_run.id);
      const resultFilter = result.new_run.failed_count > 0 ? "failed" : undefined;
      const page = await listIntegrationReconciliationItems(result.new_run.id, {
        limit: 25,
        offset: 0,
        result: resultFilter,
      });
      setReconciliationItemsByRun((existing) => ({ ...existing, [result.new_run.id]: page }));
      setStatusMessage(
        result.new_item?.result === "failed"
          ? `Retry still failed: ${result.new_item.error || "check reconciliation details"}`
          : "Reconciliation item retried successfully.",
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not retry reconciliation item.");
    } finally {
      setRetryingReconciliationItemId(null);
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

  async function testRuntimeConnection() {
    setActionBusy("runtime-test", true);
    try {
      const nextRuntime = await getModelRuntimeStatus();
      setRuntime(nextRuntime);
      setStatusMessage(
        nextRuntime.available
          ? `Connected to the local synthesis runtime at ${nextRuntime.base_url}.`
          : "The configured synthesis runtime is not responding.",
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Runtime connection test failed.");
    } finally {
      setActionBusy("runtime-test", false);
    }
  }

  async function rebuildEmbeddings() {
    if (!backendVault) return;
    setActionBusy("embedding-rebuild", true);
    try {
      const result = await reindexVaultSearch(backendVault.id);
      setStatusMessage(`Queued ${result.jobs_queued ?? 0} source reindex jobs.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not queue embedding rebuild.");
    } finally {
      setActionBusy("embedding-rebuild", false);
    }
  }

  async function createBackup() {
    setActionBusy("backup", true);
    try {
      await createVaultBackup();
      setStatusMessage("Created a local vault backup.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not create a vault backup.");
    } finally {
      setActionBusy("backup", false);
    }
  }

  async function saveDisplayName(name: string) {
    const displayName = name.trim();
    if (!displayName) return;
    setActionBusy("profile-name", true);
    try {
      setProfile(await saveDesktopProfile({ display_name: displayName }));
      setStatusMessage("Display name saved.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not save the display name.");
    } finally {
      setActionBusy("profile-name", false);
    }
  }

  async function changeVaultPassphrase() {
    const vaultId = backendVault?.id ?? unlockStatus?.vault_id;
    if (!vaultId || newPassphraseDraft !== newPassphraseConfirm) {
      setStatusMessage("Enter the recovery key and matching new passphrases.");
      return;
    }
    setActionBusy("passphrase-reset", true);
    try {
      const next = await resetVaultPassphrase({
        vault_id: vaultId,
        recovery_key: recoveryKeyDraft.trim(),
        new_passphrase: newPassphraseDraft,
      });
      setUnlockStatus(next);
      setRecoveryKeyDraft("");
      setNewPassphraseDraft("");
      setNewPassphraseConfirm("");
      setStatusMessage("Library passphrase changed.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not change the passphrase.");
    } finally {
      setActionBusy("passphrase-reset", false);
    }
  }

  async function chooseProfileImage() {
    const selected = await desktop?.selectCoverImage?.();
    if (!selected) return;
    const previousAvatar = profile.avatar_path;
    setActionBusy("profile-photo", true);
    try {
      setProfile(await saveDesktopProfile({ avatar_path: selected }));
      if (previousAvatar && previousAvatar !== selected) {
        await desktop?.deleteLocalMedia?.(previousAvatar);
      }
      setStatusMessage("Profile photo saved.");
    } catch (error) {
      if (selected !== previousAvatar) {
        await desktop?.deleteLocalMedia?.(selected);
      }
      setStatusMessage(error instanceof Error ? error.message : "Could not save the profile photo.");
    } finally {
      setActionBusy("profile-photo", false);
    }
  }

  async function installOrRepairOdin() {
    setOdinLauncherBusy(true);
    setCliAccessError(null);
    try {
      const installed = await desktop?.installOdinLauncher?.();
      if (!installed) throw new Error("Odin is available only in the desktop app.");
      setOdinLauncher(installed);
      setStatusMessage("Odin is ready. New PowerShell windows can use the odin command.");
    } catch (error) {
      setCliAccessError(error instanceof Error ? error.message : "Could not install Odin.");
    } finally {
      setOdinLauncherBusy(false);
    }
  }

  async function startOdinPairing() {
    setOdinLauncherBusy(true);
    setCliAccessError(null);
    try {
      await desktop?.startOdinPairing?.();
      setStatusMessage("Odin pairing opened in PowerShell.");
    } catch (error) {
      setCliAccessError(error instanceof Error ? error.message : "Could not start Odin pairing.");
    } finally {
      setOdinLauncherBusy(false);
    }
  }

  async function deleteCurrentVault() {
    if (!backendVault) return;
    setActionBusy("delete", true);
    try {
      await authorizeVaultDeletion(backendVault.id, {
        confirmation_name: deleteNameDraft.trim(),
        passphrase: deletePassphrase || null,
      });
      const finalized = await window.cmlDesktop?.finalizeActiveVaultDeletion?.();
      if (!finalized?.deleted) {
        throw new Error("The library was authorized for deletion, but its local data folder could not be finalized.");
      }
      window.location.assign("/onboarding");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not delete the library.");
      setActionBusy("delete", false);
    }
  }

  async function refreshTemporalHistory() {
    if (!backendVault) return;
    setTemporalBackfillBusy(true);
    try {
      const job = await backfillTemporalFacts(backendVault.id);
      setJobs(await getJobStatus());
      setStatusMessage(
        job.status === "running"
          ? "Refreshing memory history now."
          : "Memory history refresh added to Tasks.",
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not refresh memory history.");
    } finally {
      setTemporalBackfillBusy(false);
    }
  }

  async function refreshMemoryInsights() {
    if (!backendVault) return;
    const [statusResult, factsResult, packingResult] = await Promise.allSettled([
      getTemporalFactStatus(backendVault.id),
      listTemporalFacts(backendVault.id),
      getRetrievalPackingDiagnostics(backendVault.id),
    ]);
    if (statusResult.status === "fulfilled") setTemporalFacts(statusResult.value);
    if (factsResult.status === "fulfilled") setReviewableFacts(factsResult.value);
    if (packingResult.status === "fulfilled") setRetrievalPacking(packingResult.value);
    const failures = [statusResult, factsResult, packingResult].filter((result) => result.status === "rejected");
    if (failures.length) setStatusMessage("Some memory details could not refresh.");
  }

  async function saveFactCorrection(factId: string) {
    if (!backendVault || !factCorrectionDraft.trim()) return;
    setFactReviewBusyId(factId);
    try {
      await correctTemporalFact(
        factId,
        backendVault.id,
        factCorrectionDraft.trim(),
        "Corrected from Memory history.",
      );
      await refreshMemoryInsights();
      setEditingFactId(null);
      setFactCorrectionDraft("");
      setStatusMessage("Memory corrected. The previous version remains in its history.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not correct this memory.");
    } finally {
      setFactReviewBusyId(null);
    }
  }

  async function removeFact(factId: string) {
    if (!backendVault) return;
    setFactReviewBusyId(factId);
    try {
      await retractTemporalFact(factId, backendVault.id, "Removed from Memory history.");
      await refreshMemoryInsights();
      setRetractConfirmId(null);
      setStatusMessage("Memory removed from future answers.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not remove this memory.");
    } finally {
      setFactReviewBusyId(null);
    }
  }

  async function decideCliPairing(challenge: CliPairingChallenge, approve: boolean) {
    if (!backendVault) return;
    setCliAccessBusyId(challenge.id);
    setCliAccessError(null);
    try {
      if (approve) {
        await approveCliPairingChallenge(challenge.id, challenge.requested_scopes, [backendVault.id]);
        setStatusMessage(`${challenge.requester_name} can now access this library through Odin.`);
      } else {
        await denyCliPairingChallenge(challenge.id);
        setStatusMessage("The Odin access request was denied.");
      }
      setCliPairings(await listCliPairingChallenges());
      setCliClients(await listCliClients());
    } catch (error) {
      setCliAccessError(error instanceof Error ? error.message : "The access request could not be updated.");
    } finally {
      setCliAccessBusyId(null);
    }
  }

  async function updateCliClient(client: CliClientRecord, action: "revoke" | "rotate") {
    setCliAccessBusyId(client.id);
    setCliAccessError(null);
    try {
      if (action === "revoke") {
        await revokeCliClient(client.id);
        setStatusMessage(`${client.display_name} no longer has access to this library.`);
      } else {
        await rotateCliClient(client.id);
        setStatusMessage(`${client.display_name} must pair again before its next Odin command.`);
      }
      setCliClients(await listCliClients());
    } catch (error) {
      setCliAccessError(error instanceof Error ? error.message : "Command-line access could not be updated.");
    } finally {
      setCliAccessBusyId(null);
    }
  }

  const activeChatModel = models.find((model) => model.active_chat) ?? null;
  const recommendedChatModelId = modelRecommendations?.recommended_chat_model_id ?? "";
  const recommendedChatSummary = modelRecommendations?.chat_recommendation?.summary ?? "";
  const recommendedChatSpeed = modelRecommendations?.chat_estimated_tok_per_sec;
  const showSection = (...sections: string[]) => sections.includes(activeSection);
  const coreHealthReady =
    backendHealth.status === "online" &&
    Boolean(backendVault) &&
    unlockStatus?.ready === true &&
    embeddingRuntime?.available === true &&
    !healthLoadError;
  const temporalBackfillActive = Boolean(
    [...(jobs?.running_jobs ?? []), ...(jobs?.latest ?? [])].some(
      (job) => job.job_type === "temporal_fact_backfill" && ["queued", "running"].includes(job.status),
    ),
  );

  return (
    <div className="vault-page-wash grid h-full grid-cols-1 overflow-hidden xl:grid-cols-[205px_minmax(0,1fr)]">
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
                onClick={() => selectSettingsSection(section.id)}
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

        <label
          htmlFor="settings-section-select"
          className="mt-6 block text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground xl:hidden"
        >
          Settings section
        </label>
        <select
          id="settings-section-select"
          value={activeSection}
          onChange={(event) => selectSettingsSection(event.target.value)}
          className="mt-2 w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground outline-none xl:hidden"
        >
          {settingsSections.map((section) => (
            <option key={section.id} value={section.id}>
              {section.label}
            </option>
          ))}
        </select>

        <div className="mt-7 space-y-4">
          {statusMessage && (
            <div className="rounded-md border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
              {statusMessage}
            </div>
          )}
          {activeSection === "profile" ? (
            <>
              <ProfileSettings
                profile={profile}
                vaultPath={backendVault?.path ?? ""}
                savingName={isActionBusy("profile-name")}
                savingPhoto={isActionBusy("profile-photo")}
                onSaveName={saveDisplayName}
                onChooseImage={chooseProfileImage}
              />
              <SettingsCard
                icon={<RotateCcw className="h-4 w-4" />}
                title="Vault tour"
                description="Replay the short walkthrough of Search, Sources, Chat, Clusters, and Settings."
              >
                <Button
                  variant="outline"
                  className="mt-5"
                  onClick={() => window.dispatchEvent(new Event("vault:start-tour"))}
                >
                  Start tour
                </Button>
              </SettingsCard>
            </>
          ) : (
            <>
          {showSection("health") && (
            <>
              <SettingsCard
                icon={<HeartPulse className="h-4 w-4" />}
                title="System health"
                description="Live checks for this library and its local services. Values refresh every six seconds."
                status={backendHealth.status === "checking" ? "Checking" : coreHealthReady ? "Core services ready" : "Needs attention"}
                statusTone={coreHealthReady ? "ready" : "issue"}
              >
                <div className="mt-5 divide-y divide-border rounded-md border border-border bg-background">
                  <HealthStatusRow
                    icon={<Server className="h-4 w-4" />}
                    label="Vault service"
                    value={backendHealthLabel(backendHealth.status)}
                    detail={backendHealth.url}
                    tone={backendHealth.status === "online" ? "ready" : backendHealth.status === "checking" ? "neutral" : "issue"}
                  />
                  <HealthStatusRow
                    icon={<ShieldCheck className="h-4 w-4" />}
                    label="Library"
                    value={backendVault ? unlockStatus?.ready ? "Ready" : unlockStatus?.state ? formatHealthLabel(unlockStatus.state) : "Checking" : "Not configured"}
                    detail={displayPath(backendVault?.path) || unlockStatus?.message || "Create a library to store and index sources."}
                    tone={backendVault && unlockStatus?.ready ? "ready" : "warning"}
                  />
                  <HealthStatusRow
                    icon={<Database className="h-4 w-4" />}
                    label="Library database"
                    value={healthLoadError ? "Check failed" : backendVault ? "Responding" : "No library"}
                    detail={healthLoadError ?? (healthCheckedAt ? `Metadata query completed ${formatHealthTime(healthCheckedAt)}.` : "Waiting for the first metadata query.")}
                    tone={healthLoadError ? "issue" : backendVault ? "ready" : "warning"}
                  />
                  <HealthStatusRow
                    icon={<Layers className="h-4 w-4" />}
                    label="Memory search"
                    value={embeddingRuntime?.available ? "Ready" : embeddingRuntime?.setup_required ? "Setup required" : "Unavailable"}
                    detail={embeddingRuntime?.detail ?? "Waiting for the embedding runtime check."}
                    tone={embeddingRuntime?.available ? "ready" : "warning"}
                  />
                  <HealthStatusRow
                    icon={<MessageSquare className="h-4 w-4" />}
                    label="Local chat"
                    value={runtime?.available ? "Ready" : "Unavailable"}
                    detail={runtime?.detail ?? "Waiting for the local model runtime check."}
                    tone={runtime?.available ? "ready" : "warning"}
                  />
                  <HealthStatusRow
                    icon={<FileText className="h-4 w-4" />}
                    label="Tasks"
                    value={jobHealthLabel(jobs)}
                    detail={jobHealthDetail(jobs)}
                    tone={(jobs?.failed ?? 0) > 0 ? "issue" : (jobs?.running ?? 0) + (jobs?.queued ?? 0) > 0 ? "neutral" : "ready"}
                  />
                  <HealthStatusRow
                    icon={<Settings2 className="h-4 w-4" />}
                    label="OCR"
                    value={ocrRuntime?.available ? "Available" : "Optional setup"}
                    detail={ocrRuntime?.detail ?? "Waiting for the OCR capability check."}
                    tone={ocrRuntime?.available ? "ready" : "neutral"}
                  />
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  Last checked: {healthCheckedAt ? formatHealthTime(healthCheckedAt) : "waiting for first check"}
                </p>
              </SettingsCard>

              <SettingsCard
                icon={<TerminalSquare className="h-4 w-4" />}
                title="Device capability"
                description="Read directly from this device."
                status={hardware ? formatHealthLabel(hardware.hardware_tier) : "Checking"}
                statusTone={hardware ? "ready" : "issue"}
              >
                <div className="mt-5 grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2">
                  <HealthMetric label="System" value={hardware ? `${hardware.os} / ${hardware.machine}` : "Checking…"} />
                  <HealthMetric label="CPU" value={hardware ? `${hardware.cpu_count} logical cores${hardware.avx2 === null ? "" : hardware.avx2 ? " / AVX2" : " / No AVX2"}` : "Checking…"} />
                  <HealthMetric label="Memory" value={hardware?.total_memory_bytes ? `${Math.round(hardware.total_memory_bytes / 1024 / 1024 / 1024)} GB` : "Not reported"} />
                  <HealthMetric label="Processor" value={hardware?.processor || "Not reported"} />
                </div>
                {hardware?.detail ? <p className="mt-3 break-words text-xs text-muted-foreground">{hardware.detail}</p> : null}
              </SettingsCard>
            </>
          )}

          {showSection("connections") && (<>
            <SettingsCard
              icon={<Folder className="h-4 w-4" />}
              title="Odin code projects"
              description="Code projects available in this library. Odin reads and indexes them without changing repository files."
              status={projects.length ? `${projects.length} registered` : "None"}
              statusTone={projects.some((project) => project.status === "issue") ? "issue" : "ready"}
            >
              <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm">
                <div className="font-medium">Add a project from your IDE</div>
                <code className="mt-2 block overflow-x-auto rounded bg-card px-3 py-2 text-xs text-muted-foreground">
                  odin project add . --name &quot;My Project&quot;
                </code>
              </div>
              <div className="mt-4 divide-y divide-border rounded-md border border-border bg-background">
                {projects.length ? projects.map((project) => (
                  <div key={project.id} className="px-3 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">{project.name}</span>
                      <span className="text-xs capitalize text-muted-foreground">{project.status}</span>
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground" title={project.root_path}>
                      {displayPath(project.root_path)}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {project.source_count.toLocaleString()} files / Code map {formatHealthLabel(project.structure_status)} / Search {formatHealthLabel(project.retrieval_status)}
                    </div>
                  </div>
                )) : (
                  <div className="px-3 py-4 text-sm text-muted-foreground">No code projects are registered in this library.</div>
                )}
              </div>
            </SettingsCard>

            <SettingsCard
              icon={<TerminalSquare className="h-4 w-4" />}
              title="Odin command"
              description="Use Odin from PowerShell or your IDE terminal."
              status={odinLauncher?.installed ? "Ready" : odinLauncher?.needs_repair ? "Repair needed" : "Not installed"}
              statusTone={odinLauncher?.installed ? "ready" : "issue"}
            >
              <div className="mt-5 flex flex-wrap gap-2">
                <Button onClick={() => void installOrRepairOdin()} disabled={odinLauncherBusy || !desktop?.installOdinLauncher}>
                  {odinLauncher?.installed ? "Repair Odin" : "Install Odin"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void startOdinPairing()}
                  disabled={odinLauncherBusy || !odinLauncher?.installed}
                >
                  Pair Odin
                </Button>
              </div>
              {odinLauncher?.launcher_path ? (
                <div className="mt-3 break-all font-mono text-xs text-muted-foreground">
                  {odinLauncher.launcher_path}
                </div>
              ) : null}
              <p className="mt-3 text-xs text-muted-foreground">
                Open a new PowerShell window after installation, then run <code>odin --help</code>.
              </p>
            </SettingsCard>

            <SettingsCard
              icon={<ShieldCheck className="h-4 w-4" />}
              title="Odin command-line access"
              description="Approve this computer before Odin can read or update code-project context in this library. Credentials stay protected by Windows."
              status={cliPairings.length ? `${cliPairings.length} waiting` : `${cliClients.filter((client) => !client.revoked_at).length} connected`}
              statusTone={cliPairings.length ? "issue" : "ready"}
            >
              {cliAccessError ? (
                <div role="alert" className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {cliAccessError}
                </div>
              ) : null}

              <div className="mt-5">
                <div className="text-sm font-medium">Waiting for approval</div>
                <div className="mt-2 divide-y divide-border rounded-md border border-border bg-background">
                  {cliPairings.length ? cliPairings.map((challenge) => (
                    <div key={challenge.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-3">
                      <div className="min-w-0">
                        <div className="font-medium">{challenge.requester_name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Requested {challenge.requested_scopes.length} permissions / expires {new Date(challenge.expires_at).toLocaleTimeString()}
                        </div>
                        <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground" title={challenge.executable_fingerprint}>
                          App identity {challenge.executable_fingerprint.slice(0, 16)}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button variant="outline" onClick={() => void decideCliPairing(challenge, false)} disabled={cliAccessBusyId === challenge.id}>
                          Deny
                        </Button>
                        <Button onClick={() => void decideCliPairing(challenge, true)} disabled={cliAccessBusyId === challenge.id || !backendVault}>
                          Approve for this library
                        </Button>
                      </div>
                    </div>
                  )) : (
                    <div className="px-3 py-4 text-sm text-muted-foreground">
                      Run <code className="text-foreground">odin auth pair</code> in PowerShell to request access.
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-5">
                <div className="text-sm font-medium">Connected clients</div>
                <div className="mt-2 divide-y divide-border rounded-md border border-border bg-background">
                  {cliClients.length ? cliClients.map((client) => (
                    <div key={client.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{client.display_name}</span>
                          <span className="text-xs text-muted-foreground">{client.revoked_at ? "Revoked" : "Connected"}</span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {client.last_used_at ? `Last used ${new Date(client.last_used_at).toLocaleString()}` : "Not used yet"}
                          {` / ${client.scopes.length} permissions`}
                        </div>
                      </div>
                      {!client.revoked_at ? (
                        <div className="flex gap-2">
                          <Button variant="outline" onClick={() => void updateCliClient(client, "rotate")} disabled={cliAccessBusyId === client.id}>
                            Require pairing again
                          </Button>
                          <Button variant="outline" onClick={() => void updateCliClient(client, "revoke")} disabled={cliAccessBusyId === client.id}>
                            Revoke
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  )) : (
                    <div className="px-3 py-4 text-sm text-muted-foreground">No computers have been approved for Odin yet.</div>
                  )}
                </div>
              </div>
            </SettingsCard>
          </>)}

          {showSection("models") && (
          <SettingsCard
            icon={<TerminalSquare className="h-4 w-4" />}
            title="Local model connection"
            description="Vault uses this address to reach the local model that writes answers."
            status={runtime?.available ? "Ready" : "Missing"}
            statusTone={runtime?.available ? "ready" : "issue"}
          >
            <label className="mt-5 block text-sm font-medium">Connection address</label>
            <div className="mt-2 flex gap-2">
              <Input value={runtime?.base_url ?? "http://localhost:11434"} readOnly />
              <Button variant="outline" className="gap-2" disabled={isActionBusy("runtime-test")} onClick={() => void testRuntimeConnection()}>
                Test <Play className="h-4 w-4" />
              </Button>
            </div>
          </SettingsCard>
          )}

          {showSection("models") && (
          <>
          <SettingsCard
            icon={<MessageSquare className="h-4 w-4" />}
            title="Local chat model"
            description="Vault uses one local model to write answers from your sources."
            status={activeChatModel ? "Configured" : "Required"}
            statusTone={activeChatModel ? "ready" : "issue"}
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">Recommended for this device</div>
                <span className="text-xs text-muted-foreground">
                  Confidence: {modelRecommendations?.confidence ?? "low"}
                </span>
              </div>
              <div className="mt-2 text-foreground">
                {recommendedChatSummary || "A recommendation will appear after Vault checks which models this device can run comfortably."}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {modelRecommendations?.detail ?? "Recommendations favor responsive everyday use over the largest possible model."}
              </div>
              {(recommendedChatSpeed || modelRecommendations?.evidence_level || modelRecommendations?.chat_fit_type) && (
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {modelRecommendations?.chat_fit_type ? <span>Fit: {modelRecommendations.chat_fit_type.replaceAll("_", " ")}</span> : null}
                  {recommendedChatSpeed ? <span>Estimated speed: {recommendedChatSpeed} tok/s</span> : null}
                  {modelRecommendations?.evidence_level ? <span>Evidence: {modelRecommendations.evidence_level.replaceAll("_", " ")}</span> : null}
                </div>
              )}
              {modelRecommendations?.warnings?.length ? (
                <div className="mt-3 text-xs text-muted-foreground">
                  {modelRecommendations.warnings[0]}
                </div>
              ) : null}
            </div>
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              {activeChatModel
                ? `Active model: ${activeChatModel.name}. Retrieval remains the citation source.`
                : "Pick one accepted chat model. Retrieval remains the citation source."}
            </div>
            <label className="mt-5 block text-sm font-medium">Local model download location</label>
            <div className="mt-2 flex flex-wrap gap-2">
              <Input
                value={modelDownloadRoot}
                onChange={(event) => setModelDownloadRoot(event.target.value)}
                placeholder="Choose where downloaded GGUF chat models should be stored"
              />
              <Button variant="outline" onClick={() => void chooseModelDownloadFolder()} disabled={!mounted || !desktop?.selectModelFolder}>
                <Folder className="h-4 w-4" />
                Browse
              </Button>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Leave blank to use Vault's default model folder.
            </p>
            <div className="mt-5 space-y-3">
              {models.map((model) => {
                const downloading = model.download?.status === "resolving" || model.download?.status === "downloading";
                const needsVerification =
                  model.installed &&
                  model.source_kind === "default_choice" &&
                  model.integrity?.status !== "verified";
                const totalBytes = model.download?.total_bytes ?? model.download?.bytes_total ?? null;
                const progress = model.download?.progress_percent ?? (
                  model.download?.bytes_downloaded && totalBytes
                    ? Math.round((model.download.bytes_downloaded / totalBytes) * 100)
                    : null
                );
                return (
                  <div key={model.id} className="rounded-md border border-border bg-background px-3 py-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-medium">{model.name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {model.role} / {model.family || "unclassified"} / {model.approximate_download_gb} GB
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {needsVerification
                            ? "Needs verification before chat"
                            : modelReadinessLabel(model, runtime)}
                        </div>
                        {model.id === recommendedChatModelId ? (
                          <div className="mt-1 text-xs text-primary">
                            Recommended chat model for this device
                          </div>
                        ) : null}
                      </div>
                      {model.active_chat ? (
                        <span className="text-primary">
                          {isModelRuntimeReady(model, runtime) ? "Chat" : "Selected"}
                        </span>
                      ) : null}
                    </div>
                    {downloading && (
                      <div className="mt-3">
                        <Progress value={progress ?? 0} className="download-progress-active h-1.5" />
                        <div className="mt-1 flex justify-between gap-3 text-xs text-muted-foreground">
                          <span>{model.download?.status}</span>
                          <span>{progress !== null && progress !== undefined ? `${Math.round(progress)}%` : "Preparing download"}</span>
                        </div>
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {!model.installed || needsVerification ? (
                        <Button variant="outline" onClick={() => void downloadModel(model.id)} disabled={downloadingId === model.id}>
                          {downloadingId === model.id
                            ? "Starting..."
                            : needsVerification
                              ? "Download again"
                              : "Download"}
                        </Button>
                      ) : null}
                      {downloading ? (
                        <Button variant="outline" onClick={() => void cancelDownload(model.id)}>
                          Cancel
                        </Button>
                      ) : null}
                      {model.compatibility?.chat_role_accepted &&
                      !model.active_chat &&
                      (model.source_kind !== "default_choice" || model.integrity?.status === "verified") ? (
                        <Button variant="outline" onClick={() => void activateModel(model.id)} disabled={activatingId === model.id}>
                          {activatingId === model.id ? "Activating..." : "Use for chat"}
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
                onChange={(event) => setCustomModelPath(displayPath(event.target.value))}
                placeholder="D:/Models/Qwen3-4B-Q4_K_M.gguf"
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
              <Button variant="outline" onClick={() => void scanInstalledModels()} disabled={discoveringModels}>
                {discoveringModels ? "Scanning..." : "Scan installed models"}
              </Button>
            </div>
            {customModelReport && (
              <div className="mt-4 rounded-md border border-border bg-background px-3 py-3 text-sm">
                <div className="font-medium">{customModelReport.accepted ? "Accepted" : "Rejected"}</div>
                <div className="mt-1 text-muted-foreground">{customModelReport.detail}</div>
                <div className="mt-1 text-xs text-muted-foreground">{customModelReport.selection_detail}</div>
              </div>
            )}
            <div className="mt-4 space-y-3">
              {discoveredModels.length ? (
                discoveredModels.map((model) => (
                  <div key={model.id} className="rounded-md border border-border bg-background px-3 py-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-medium">{model.name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {model.family_name || model.family || "Approved family"} / {displayPath(model.local_path)}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">{model.detail}</div>
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => void importDiscoveredModel(model)}
                        disabled={model.already_imported}
                      >
                        {model.already_imported ? "Already imported" : "Import"}
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-muted-foreground">
                  Scan common local model folders to detect accepted local chat checkpoints already installed on this device.
                </p>
              )}
            </div>
          </SettingsCard>
          {activeModelDownload &&
            (isActiveModelDownloadStatus(activeModelDownload.status) ||
              modelDownload?.model_id === activeModelDownload.model_id) && (
            <ModelDownloadToast
              download={activeModelDownload}
              onCancel={() => void cancelDownload(activeModelDownload.model_id)}
            />
          )}
          </>
          )}

          {showSection("models") && (
          <SettingsCard
            icon={<Layers className="h-4 w-4" />}
            title="Memory search model"
            description="The local model Vault uses to find related ideas and sources."
            status={embeddingRuntime?.available ? "Ready" : "Required"}
            statusTone={embeddingRuntime?.available ? "ready" : "issue"}
          >
            {!embeddingRuntime?.available && (
              <div className="mt-5 rounded-md border border-[var(--status-learning)]/35 bg-[var(--status-learning)]/10 px-3 py-2 text-sm">
                Search, clustering, source-grounded chat, Bridge, and new indexing stay unavailable until this memory-search model passes its check.
              </div>
            )}
            <label className="mt-5 block text-sm font-medium">Model path (required)</label>
            <div className="mt-2 flex flex-wrap gap-2">
              <Input
                value={embeddingCacheDraft}
                onChange={(event) => {
                  embeddingDraftDirtyRef.current = true;
                  setEmbeddingCacheDraft(event.target.value);
                }}
                placeholder="C:/AI_Models/all-MiniLM-L6-v2"
              />
              <Button variant="outline" onClick={() => void chooseEmbeddingFolder()} disabled={!mounted || !desktop?.selectEmbeddingFolder}>
                Browse
              </Button>
              <Button variant="outline" onClick={() => void saveEmbeddingRuntime()} disabled={isActionBusy("embedding-runtime") || !embeddingCacheDraft.trim()}>
                Test
              </Button>
              <Button variant="outline" className="gap-2" onClick={() => void downloadEmbeddingModel()} disabled={isActionBusy("embedding-download")}>
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
                  <div className="mt-1 truncate font-mono">{displayPath(embeddingDownload.local_path)}</div>
                )}
                {embeddingDownload.error && (
                  <div className="mt-1 text-destructive">{embeddingDownload.error}</div>
                )}
              </div>
            )}
            <div className="mt-4 border-t border-border pt-4">
              <Button
                variant="outline"
                onClick={() => void rebuildEmbeddings()}
                disabled={isActionBusy("embedding-rebuild") || !backendVault}
              >
                Rebuild search index
              </Button>
            </div>
          </SettingsCard>
          )}

          {showSection("models") && (
          <SettingsCard
            icon={<Settings2 className="h-4 w-4" />}
            title="OCR"
            description="Local OCR for scanned documents and images."
            status={ocrRuntime?.available ? "Ready" : "Missing"}
            statusTone={ocrRuntime?.available ? "ready" : "issue"}
          >
            <div className="mt-6 divide-y divide-border border-y border-border">
              <RuntimeRow
                label="Image OCR"
                value={ocrRuntime?.image_ocr_available ? "Ready" : "Missing"}
                tone={ocrRuntime?.image_ocr_available ? "ready" : "issue"}
                meta={displayPath(ocrRuntime?.tesseract_path)}
              />
              <RuntimeRow
                label="PDF OCR"
                value={ocrRuntime?.pdf_ocr_available ? "Ready" : "Missing"}
                tone={ocrRuntime?.pdf_ocr_available ? "ready" : "issue"}
                meta={ocrRuntime?.pdf_ocr_engine ?? ""}
              />
              <RuntimeRow
                label="OCRmyPDF"
                value={ocrRuntime?.full_pdf_ocr_available ? "Ready" : "Fallback"}
                tone={ocrRuntime?.full_pdf_ocr_available ? "ready" : "warning"}
                meta={ocrRuntime?.ocrmypdf_command ?? ""}
              />
              <RuntimeRow
                label="Ghostscript"
                value={ocrRuntime?.ghostscript_path ? "Installed" : "Missing"}
                tone={ocrRuntime?.ghostscript_path ? "ready" : "issue"}
                meta={displayPath(ocrRuntime?.ghostscript_path)}
              />
              <RuntimeRow
                label="qpdf"
                value={ocrRuntime?.qpdf_path ? "Installed" : "Missing"}
                tone={ocrRuntime?.qpdf_path ? "ready" : "issue"}
                meta={displayPath(ocrRuntime?.qpdf_path)}
              />
            </div>
            {ocrRuntime?.missing.length ? (
              <div className="mt-5 rounded-md bg-[var(--status-warn-bg)] px-4 py-3 text-sm text-[var(--status-warn-ink)]">
                <span className="font-medium">Optional tools not detected</span>
                <span className="mt-1 block break-words leading-5">
                  {ocrRuntime.missing.join(", ")}
                </span>
              </div>
            ) : null}
          </SettingsCard>
          )}

          {showSection("library") && (<>
          <SettingsCard
            icon={<Database className="h-4 w-4" />}
            title="Library storage"
            description="Manage this library's local location and backups."
          >
            <div className="mt-5">
              <label className="text-sm font-medium" htmlFor="library-storage-path">Storage location</label>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <Input
                  id="library-storage-path"
                  value={pathDraft}
                  onChange={(event) => {
                    pathDraftDirtyRef.current = true;
                    setPathDraft(displayPath(event.target.value));
                  }}
                />
                <Button variant="outline" onClick={() => void saveVaultPath()} disabled={isActionBusy("vault-path")}>
                  Change location
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={!backendVault}
                  onClick={() => {
                    if (backendVault) return window.cmlDesktop?.showItemInFolder(backendVault.path);
                  }}
                >
                  Show data folder
                </Button>
                <Button
                  variant="outline"
                  disabled={isActionBusy("backup") || !backendVault}
                  onClick={() => void createBackup()}
                >
                  Create local backup
                </Button>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                Storage usage totals are not available yet.
              </p>
            </div>
          </SettingsCard>
          <SettingsCard
            icon={<MessageSquare className="h-4 w-4" />}
            title="Memory history"
            description="Keep dated conversation facts and preferences aligned with your saved chats. This runs locally."
            status={
              temporalBackfillActive
                ? "Refreshing"
                : temporalFacts
                  ? `${temporalFacts.indexed_session_count} of ${temporalFacts.session_count} conversations`
                  : "Checking"
            }
            statusTone={
              temporalFacts && temporalFacts.indexed_session_count < temporalFacts.session_count
                ? "issue"
                : "ready"
            }
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              {temporalFacts ? (
                <>
                  {temporalFacts.status_counts.current ?? 0} current facts and preferences are available for grounded answers.
                  {temporalFacts.latest_observed_at
                    ? ` Latest saved history: ${new Date(temporalFacts.latest_observed_at).toLocaleString()}.`
                    : " No dated history has been derived yet."}
                </>
              ) : (
                "Waiting for the local history check."
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => void refreshTemporalHistory()}
                disabled={!backendVault || temporalBackfillBusy || temporalBackfillActive}
              >
                <RefreshCw className={`h-4 w-4 ${temporalBackfillActive ? "animate-spin" : ""}`} />
                {temporalBackfillActive ? "Refreshing..." : "Refresh memory history"}
              </Button>
            </div>
            {retrievalPacking && retrievalPacking.query_count > 0 ? (
              <div className="mt-5 border-t border-border pt-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <p className="text-sm font-medium text-foreground">Answer context</p>
                  <p className="text-xs text-muted-foreground">
                    {retrievalPacking.context_reduction_percent}% less context across {retrievalPacking.query_count} saved {retrievalPacking.query_count === 1 ? "answer" : "answers"}
                  </p>
                </div>
                <p className="mt-1 max-w-[70ch] text-xs text-muted-foreground">
                  Vault keeps the most relevant evidence before asking the local model. Recent answers averaged {retrievalPacking.average_final_context_tokens.toLocaleString()} estimated context tokens.
                </p>
              </div>
            ) : null}
            <div className="mt-5 border-t border-border pt-4">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-sm font-medium text-foreground">What Vault remembers</p>
                <p className="text-xs text-muted-foreground">Recent current facts</p>
              </div>
              {reviewableFacts.length ? (
                <div className="mt-2 divide-y divide-border">
                  {reviewableFacts.slice(0, 8).map((fact) => (
                    <div key={fact.id} className="py-3 first:pt-2">
                      {editingFactId === fact.id ? (
                        <div className="space-y-2">
                          <label className="block text-xs font-medium text-foreground" htmlFor={`fact-${fact.id}`}>
                            Correct {fact.predicate_key.replaceAll("_", " ")}
                          </label>
                          <Input
                            id={`fact-${fact.id}`}
                            value={factCorrectionDraft}
                            onChange={(event) => setFactCorrectionDraft(event.target.value)}
                            autoFocus
                          />
                          <div className="flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              onClick={() => void saveFactCorrection(fact.id)}
                              disabled={factReviewBusyId === fact.id || !factCorrectionDraft.trim()}
                            >
                              Save correction
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setEditingFactId(null);
                                setFactCorrectionDraft("");
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="break-words text-sm text-foreground">
                              <span className="text-muted-foreground">{fact.predicate_key.replaceAll("_", " ")}: </span>
                              {fact.modality === "negated" ? "no longer " : ""}{fact.object_text}
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              Saved {new Date(fact.observed_at).toLocaleDateString()} from {fact.source_type === "manual" ? "your correction" : "a conversation"}
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setEditingFactId(fact.id);
                                setFactCorrectionDraft(fact.object_text);
                                setRetractConfirmId(null);
                              }}
                            >
                              Correct
                            </Button>
                            {retractConfirmId === fact.id ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  onClick={() => void removeFact(fact.id)}
                                  disabled={factReviewBusyId === fact.id}
                                >
                                  Confirm remove
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setRetractConfirmId(null)}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  setRetractConfirmId(fact.id);
                                  setEditingFactId(null);
                                }}
                              >
                                Remove
                              </Button>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">
                  No current conversation facts are available to review yet.
                </p>
              )}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              Suggestions remain separate from actions. Corrections preserve the older version for dated questions and audit history.
            </p>
          </SettingsCard>
          </>)}

          {showSection("library") && (
          <SettingsCard
            icon={<Lock className="h-4 w-4" />}
            title="Library unlock"
            description="Protect this library with a full passphrase. A protected library always starts locked after the app restarts."
            status={unlockStatus?.state ?? "Unknown"}
            statusTone={unlockStatus?.state === "ready" ? "ready" : "issue"}
          >
            <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
              State: <span className="text-foreground">{unlockStatus?.state ?? "unknown"}</span>
              {" / "}Protection: <span className="text-foreground">
                {unlockStatus?.secured_vault_count ? "Full passphrase" : "Not enabled"}
              </span>
            </div>
            {unlockStatus?.verification_error ? (
              <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                Repair required: {unlockStatus.verification_error}
              </div>
            ) : null}
            <div className="mt-4 grid gap-2 md:grid-cols-[1fr_auto_auto]">
              <div>
                <Input
                  type="password"
                  autoComplete={
                    unlockStatus?.secured_vault_count
                      ? "current-password"
                      : "new-password"
                  }
                  aria-label={
                    unlockStatus?.secured_vault_count
                      ? "Library passphrase"
                      : "Create library passphrase"
                  }
                  aria-invalid={Boolean(unlockError)}
                  aria-describedby={unlockError ? "library-unlock-error" : undefined}
                  value={vaultPassphrase}
                  onChange={(event) => {
                    setVaultPassphrase(event.target.value);
                    if (unlockError) setUnlockError(null);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !isActionBusy("security")) {
                      event.preventDefault();
                      void unlockVault();
                    }
                  }}
                  disabled={isActionBusy("security")}
                  placeholder={unlockStatus?.secured_vault_count ? "Library passphrase" : "Create library passphrase"}
                />
                {unlockError ? (
                  <p
                    id="library-unlock-error"
                    className="mt-1.5 text-sm text-destructive"
                    role="alert"
                  >
                    {unlockError}
                  </p>
                ) : null}
              </div>
              <Button
                onClick={() => void unlockVault()}
                disabled={
                  isActionBusy("security") ||
                  !(backendVault?.id ?? unlockStatus?.secured_vault_ids[0])
                }
              >
                {unlockStatus?.secured_vault_count ? "Unlock" : "Initialize security"}
              </Button>
              <Button
                variant="outline"
                className="border-[var(--status-warn)]/45 text-[var(--status-warn-ink)]"
                onClick={() => void lockCurrentVault()}
                disabled={isActionBusy("security") || unlockStatus?.state !== "ready"}
              >
                Lock library
              </Button>
            </div>
            {recoveryKey ? (
              <div className="mt-4 rounded-md border border-[var(--status-learning)]/35 bg-[var(--status-learning)]/10 px-3 py-3 text-sm">
                <div className="font-medium">Offline recovery key. Store it now; Vault has no vendor recovery path.</div>
                <div className="mt-2 break-all font-mono text-xs">{recoveryKey}</div>
              </div>
            ) : null}
            <p className="mt-3 text-xs text-muted-foreground">
              Vault does not store your passphrase. Keep the offline recovery key somewhere safe.
            </p>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Passphrase protection encrypts source text, extracted pages and chunks, chat
              message bodies and evidence, and generation prompts. Library and source names,
              file locations, timestamps, cluster and project labels, and operational metadata
              remain readable on this device.
            </p>
            {unlockStatus?.secured_vault_count ? (
              <details className="mt-5 rounded-md border border-border bg-background">
                <summary className="cursor-pointer px-3 py-3 text-sm font-medium">
                  Change a forgotten passphrase
                </summary>
                <div className="space-y-3 border-t border-border p-3">
                  <p className="text-xs leading-5 text-muted-foreground">
                    Use the offline recovery key created when protection was enabled.
                  </p>
                  <Input
                    value={recoveryKeyDraft}
                    onChange={(event) => setRecoveryKeyDraft(event.target.value)}
                    placeholder="Recovery key"
                  />
                  <Input
                    type="password"
                    value={newPassphraseDraft}
                    onChange={(event) => setNewPassphraseDraft(event.target.value)}
                    placeholder="New passphrase"
                  />
                  <Input
                    type="password"
                    value={newPassphraseConfirm}
                    onChange={(event) => setNewPassphraseConfirm(event.target.value)}
                    placeholder="Confirm new passphrase"
                  />
                  <Button
                    variant="outline"
                    disabled={
                      isActionBusy("passphrase-reset") ||
                      !recoveryKeyDraft.trim() ||
                      newPassphraseDraft.length < 12 ||
                      newPassphraseDraft !== newPassphraseConfirm
                    }
                    onClick={() => void changeVaultPassphrase()}
                  >
                    Change passphrase
                  </Button>
                </div>
              </details>
            ) : null}
          </SettingsCard>
          )}

          {showSection("advanced") && (
          <SettingsCard
            icon={<ShieldCheck className="h-4 w-4" />}
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
          )}

          {showSection("library") && (
          <SettingsCard
            icon={<Folder className="h-4 w-4" />}
            title="Local imports"
            description="Manual refresh and reconciliation for local, synced-folder, and Obsidian imports."
            status={integrationImports.length ? `${integrationImports.length} tracked` : "None"}
          >
            <div className="mt-5 space-y-2">
              {integrationImports.length === 0 ? (
                <div className="rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
                  No local folder imports are tracked for this library yet.
                </div>
              ) : (
                integrationImports.map((record) => (
                  <div
                    key={record.id}
                    className="grid gap-3 rounded-md border border-border bg-background px-3 py-3 text-sm md:grid-cols-[1fr_auto]"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{displayPath(record.root_path)}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {record.integration_type} / {record.supported_count} supported / {record.skipped_count} skipped /{" "}
                        {record.imported_count} new / {record.updated_count} updated / {record.moved_count} moved /{" "}
                        {record.tombstoned_count} removed / {record.failed_count} failed
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Watch: {record.watch_enabled ? "on" : "off"}
                        {record.next_watch_at ? ` / next ${new Date(record.next_watch_at).toLocaleString()}` : ""}
                        {record.last_failures.length ? ` / ${record.last_failures.length} recent failure(s)` : ""}
                      </div>
                      {record.last_reconciliation_run_id ? (
                        <div className="mt-1 text-xs text-muted-foreground">
                          Last reconciliation: {record.last_reconciliation_status ?? "completed"}
                          {record.last_reconciliation_trigger_source
                            ? ` via ${record.last_reconciliation_trigger_source.replaceAll("_", " ")}`
                            : ""}
                          {record.last_reconciliation_finished_at
                            ? ` at ${new Date(record.last_reconciliation_finished_at).toLocaleString()}`
                            : ""}
                          {record.last_reconciliation_retryable_failed_count
                            ? ` / ${record.last_reconciliation_retryable_failed_count} retryable failure(s)`
                            : ""}
                        </div>
                      ) : null}
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
                      {record.last_reconciliation_run_id ? (
                        <Button
                          variant="outline"
                          onClick={() => void toggleImportHistory(record.id)}
                          disabled={loadingImportHistoryId === record.id}
                        >
                          {expandedImportId === record.id ? "Hide history" : "Review history"}
                        </Button>
                      ) : null}
                    </div>
                    {expandedImportId === record.id ? (
                      <div className="md:col-span-2 rounded-md border border-border/70 bg-card/40 px-3 py-3">
                        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Post-unlock reconciliation history
                        </div>
                        <div className="mt-3 space-y-3">
                          {(reconciliationRunsByImport[record.id] ?? []).map((run) => {
                            const page = reconciliationItemsByRun[run.id];
                            const hasMore = page ? page.items.length < page.total : false;
                            return (
                              <div key={run.id} className="rounded-md border border-border bg-background px-3 py-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div>
                                    <div className="font-medium text-foreground">
                                      {run.status.replaceAll("_", " ")} / {run.trigger_source.replaceAll("_", " ")}
                                    </div>
                                    <div className="mt-1 text-xs text-muted-foreground">
                                      {run.imported_count} new / {run.updated_count} updated / {run.moved_count} moved /{" "}
                                      {run.tombstoned_count} removed / {run.failed_count} failed / {run.unchanged_count} unchanged
                                    </div>
                                    <div className="mt-1 text-xs text-muted-foreground">
                                      {new Date(run.created_at).toLocaleString()}
                                      {run.detail_count ? ` / ${run.detail_count} detail item(s)` : ""}
                                    </div>
                                  </div>
                                  <div className="flex flex-wrap gap-2">
                                    <Button
                                      variant="outline"
                                      onClick={() => void loadReconciliationItems(run)}
                                      disabled={loadingRunItemsId === run.id}
                                    >
                                      {expandedRunId === run.id ? "Refresh details" : "View details"}
                                    </Button>
                                  </div>
                                </div>
                                {expandedRunId === run.id && page ? (
                                  <div className="mt-3 space-y-2">
                                    {page.items.length === 0 ? (
                                      <div className="rounded-md border border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground">
                                        No detail items stored for this run.
                                      </div>
                                    ) : (
                                      page.items.map((item) => (
                                        <div
                                          key={item.id}
                                          className="rounded-md border border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground"
                                        >
                                          <div className="flex flex-wrap items-center justify-between gap-2">
                                            <div className="font-medium text-foreground">
                                              {item.action.replaceAll("_", " ")} / {item.result}
                                            </div>
                                            {item.retryable ? (
                                              <Button
                                                variant="outline"
                                                className="h-7 px-2 text-xs"
                                                onClick={() => void retryReconciliationItem(record.id, item.id)}
                                                disabled={retryingReconciliationItemId === item.id}
                                              >
                                                <RotateCcw className="mr-1 h-3 w-3" />
                                                {retryingReconciliationItemId === item.id ? "Retrying..." : "Retry"}
                                              </Button>
                                            ) : null}
                                          </div>
                                          <div className="mt-1 break-all">{item.item_reference}</div>
                                          {item.error ? <div className="mt-1 text-red-300">{item.error}</div> : null}
                                        </div>
                                      ))
                                    )}
                                    {hasMore ? (
                                      <Button
                                        variant="outline"
                                        className="h-8 px-3 text-xs"
                                        onClick={() => void loadReconciliationItems(run, true)}
                                        disabled={loadingRunItemsId === run.id}
                                      >
                                        Load more
                                      </Button>
                                    ) : null}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })}
                          {loadingImportHistoryId === record.id ? (
                            <div className="rounded-md border border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground">
                              Loading reconciliation history...
                            </div>
                          ) : (reconciliationRunsByImport[record.id] ?? []).length === 0 ? (
                            <div className="rounded-md border border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground">
                              No reconciliation runs have been recorded for this import yet.
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </SettingsCard>
          )}

          {showSection("advanced") && (
          <SettingsCard
            icon={<Activity className="h-4 w-4" />}
            title="Diagnostics"
            description="Collect logs and system information for troubleshooting."
          >
            <Button variant="outline" className="mt-5 gap-2" onClick={() => void exportDiagnostics()}>
              <Download className="h-4 w-4" /> Export diagnostics
            </Button>
          </SettingsCard>
          )}
          {showSection("advanced") && (
            <SettingsCard
              icon={<Lock className="h-4 w-4" />}
              title="Reset or remove"
              description="Delete this library without removing downloaded models or your original source files."
              status="Destructive"
              statusTone="issue"
              danger
            >
              <div className="mt-5 flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  disabled={isActionBusy("delete") || !backendVault}
                  onClick={() => {
                    setDestructiveAction("delete");
                    setDeleteNameDraft("");
                    setDeletePassphrase("");
                    setDeleteDialogOpen(true);
                  }}
                >
                  Delete library…
                </Button>
                <Button
                  variant="destructive"
                  disabled={isActionBusy("delete") || !backendVault}
                  onClick={() => {
                    setDestructiveAction("restart");
                    setDeleteNameDraft("");
                    setDeletePassphrase("");
                    setDeleteDialogOpen(true);
                  }}
                >
                  Restart setup…
                </Button>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Restart setup wipes this library and returns to onboarding. Downloaded model files
                and original documents stay where they are, so they can be reused.
              </p>
            </SettingsCard>
          )}
            </>
          )}
        </div>
      </main>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open && !isActionBusy("delete")) {
            setDeleteNameDraft("");
            setDeletePassphrase("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {destructiveAction === "restart" ? "Wipe this library and restart setup?" : "Delete this library?"}
            </DialogTitle>
            <DialogDescription>
              {destructiveAction === "restart"
                ? "Vault will remove this library's database and setup choices, then open onboarding. Downloaded models and original source files remain in place."
                : "This removes the library database. Downloaded models and original source files remain in place."}{" "}
              Enter the exact library name
              {unlockStatus?.secured_vault_count ? " and the full passphrase." : "."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input value={deleteNameDraft} onChange={(event) => setDeleteNameDraft(event.target.value)} placeholder={backendVault?.name ?? "Library name"} />
            {unlockStatus?.secured_vault_count ? (
              <Input type="password" value={deletePassphrase} onChange={(event) => setDeletePassphrase(event.target.value)} placeholder="Full library passphrase" />
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={isActionBusy("delete")} onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={
                isActionBusy("delete") ||
                deleteNameDraft.trim() !== backendVault?.name ||
                (Boolean(unlockStatus?.secured_vault_count) && !deletePassphrase)
              }
              onClick={() => void deleteCurrentVault()}
            >
              {isActionBusy("delete")
                ? "Removing…"
                : destructiveAction === "restart"
                  ? "Wipe and restart"
                  : "Delete library"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SettingsCard({
  icon,
  title,
  description,
  status,
  statusTone = "ready",
  danger = false,
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  status?: string;
  statusTone?: "ready" | "issue";
  danger?: boolean;
  children?: ReactNode;
}) {
  return (
    <section
      className={
        danger
          ? "rounded-md border border-[var(--status-error)]/40 bg-[var(--status-error-bg)] p-4"
          : "vault-card p-4"
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 gap-4">
          <span className="mt-0.5 shrink-0 text-muted-foreground">{icon}</span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">{title}</h2>
            <p className="mt-1 break-words text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {status && (
          <span className="flex shrink-0 items-center gap-2 text-sm text-muted-foreground">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: statusTone === "ready" ? "var(--status-ready)" : "var(--status-issue)" }}
            />
            {status}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function selectVisibleModelDownload(
  models: LocalModelRecord[],
  fallback: LocalModelRecord["download"] | null,
) {
  const visible = models
    .map((model) => model.download)
    .filter((download): download is NonNullable<LocalModelRecord["download"]> => Boolean(download?.status && download.status !== "idle"));
  return (
    visible.find((download) => isActiveModelDownloadStatus(download.status)) ??
    (fallback
      ? visible.find((download) => download.model_id === fallback.model_id) ?? fallback
      : null) ??
    visible[0] ??
    (fallback?.status && fallback.status !== "idle" ? fallback : null)
  );
}

function isActiveModelDownloadStatus(status: string | null | undefined) {
  return status === "resolving" || status === "downloading" || status === "cancelling";
}

function ModelDownloadToast({
  download,
  onCancel,
}: {
  download: NonNullable<LocalModelRecord["download"]>;
  onCancel: () => void;
}) {
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const totalBytes = download.total_bytes ?? download.bytes_total ?? null;
  const progress = download.progress_percent ?? (
    download.bytes_downloaded && totalBytes
      ? Math.round((download.bytes_downloaded / totalBytes) * 100)
      : null
  );
  const active = isActiveModelDownloadStatus(download.status);
  const fallbackProgress = download.status === "installed" ? 100 : 0;

  useEffect(() => {
    setVisible(true);
    setLeaving(false);
    if (active) return;
    const fadeTimer = window.setTimeout(() => setLeaving(true), 1800);
    const hideTimer = window.setTimeout(() => setVisible(false), 2400);
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(hideTimer);
    };
  }, [active, download.model_id, download.status]);

  if (!visible) return null;

  return (
    <div
      className={cn(
        "fixed bottom-4 right-4 z-50 w-[min(18rem,calc(100vw-2rem))] rounded-md border border-border bg-card p-3 shadow-lg transition-all duration-500",
        leaving && "pointer-events-none translate-y-1 opacity-0",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 truncate text-sm font-medium">{compactModelName(download.model_id)}</div>
        {active ? (
          <button
            type="button"
            className="rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Cancel model download"
            onClick={onCancel}
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <div className="mt-3">
        <Progress
          value={progress ?? fallbackProgress}
          className={cn("h-1.5", active && "download-progress-active")}
        />
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>{progress !== null && progress !== undefined ? `${Math.round(progress)}%` : "Preparing download"}</span>
          <span>
            {formatBytes(download.bytes_downloaded ?? 0)}
            {totalBytes ? ` / ${formatBytes(totalBytes)}` : ""}
          </span>
        </div>
      </div>
      {download.error && <div className="mt-2 text-xs text-destructive">{download.error}</div>}
    </div>
  );
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 GB";
  const gib = value / 1024 / 1024 / 1024;
  if (gib >= 1) return `${gib.toFixed(1)} GB`;
  const mib = value / 1024 / 1024;
  return `${Math.round(mib)} MB`;
}

function ProfileSettings({
  profile,
  vaultPath,
  savingName,
  savingPhoto,
  onSaveName,
  onChooseImage,
}: {
  profile: DesktopProfile;
  vaultPath: string;
  savingName: boolean;
  savingPhoto: boolean;
  onSaveName: (name: string) => Promise<void>;
  onChooseImage: () => Promise<void>;
}) {
  const [displayName, setDisplayName] = useState(profile.display_name);
  const avatarSource = useLocalImage(profile.avatar_path);
  useEffect(() => {
    setDisplayName(profile.display_name);
  }, [profile.display_name]);
  const savedDisplayName = profileDisplayName(profile);
  return (
    <>
      <section className="vault-card p-5">
        <div className="flex flex-wrap items-center gap-5">
          <div className="relative">
            <span className="flex h-20 w-20 overflow-hidden rounded-xl bg-foreground text-background">
              {avatarSource ? (
                <img
                  src={avatarSource}
                  alt={`${savedDisplayName} profile`}
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center">
                  <UserRound className="h-8 w-8" />
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => void onChooseImage()}
              disabled={savingPhoto}
              className="absolute -bottom-2 -right-2 flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card shadow-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Choose profile photo"
            >
              <Camera className="h-4 w-4" />
            </button>
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold">{displayName.trim() || savedDisplayName}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{displayPath(vaultPath) || "No library selected"}</p>
            <Button variant="outline" size="sm" className="mt-3" disabled={savingPhoto} onClick={() => void onChooseImage()}>
              {savingPhoto ? "Saving…" : "Change photo"}
            </Button>
          </div>
        </div>
      </section>

      <section className="vault-card p-5">
        <h2 className="text-sm font-semibold">Display name</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This name appears in your profile and sidebar.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          <Button
            variant="outline"
            disabled={
              savingName ||
              !displayName.trim() ||
              displayName.trim() === profile.display_name
            }
            onClick={() => void onSaveName(displayName)}
          >
            {savingName ? "Saving…" : "Save"}
          </Button>
        </div>
      </section>

    </>
  );
}

function RuntimeRow({
  label,
  value,
  meta,
  tone,
}: {
  label: string;
  value: string;
  meta?: string;
  tone: "ready" | "warning" | "issue";
}) {
  const color =
    tone === "ready"
      ? "var(--status-ready)"
      : tone === "warning"
        ? "var(--status-learning)"
        : "var(--status-issue)";

  return (
    <div className="grid min-w-0 gap-3 py-4 text-sm sm:grid-cols-[minmax(0,128px)_minmax(0,1fr)] sm:gap-6">
      <span className="break-words font-medium">{label}</span>
      <span className="min-w-0">
        <span className="flex min-w-0 items-center gap-2 font-medium">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
          <span className="break-words">{value}</span>
        </span>
        <span
          className="mt-1.5 block min-w-0 break-all font-mono text-xs leading-5 text-muted-foreground"
          title={meta || "Not detected"}
        >
          {meta || "Not detected"}
        </span>
      </span>
    </div>
  );
}

function compactModelName(value: string) {
  const qwen = value.match(/qwen[-_]?(\d+)[-_]?(\d+)b/i);
  if (qwen) return `Qwen${qwen[1]}-${qwen[2]}B`;
  const gemma = value.match(/gemma[-_]?(\d+)[-_]?(\d+)b/i);
  if (gemma) return `Gemma-${gemma[1]}-${gemma[2]}B`;
  return value.replace(/q4[_-]k[_-]m/gi, "").replace(/[_-]+/g, " ").trim();
}

type HealthTone = "ready" | "warning" | "issue" | "neutral";

function HealthStatusRow({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: HealthTone;
}) {
  const color =
    tone === "ready"
      ? "var(--status-ready)"
      : tone === "issue" || tone === "warning"
        ? "var(--status-learning)"
        : "var(--muted-foreground)";

  return (
    <div className="grid min-w-0 gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,180px)_minmax(0,1fr)] sm:gap-5">
      <span className="flex min-w-0 items-center gap-3 font-medium">
        <span className="shrink-0 text-muted-foreground">{icon}</span>
        <span className="break-words">{label}</span>
      </span>
      <span className="min-w-0 sm:text-right">
        <span className="inline-flex max-w-full items-center gap-2 font-medium">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
          <span className="break-words">{value}</span>
        </span>
        <span className="mt-1 block break-words text-xs text-muted-foreground">{detail}</span>
      </span>
    </div>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 bg-background px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-sm font-medium">{value}</div>
    </div>
  );
}

function backendHealthLabel(status: "checking" | "online" | "degraded" | "offline") {
  if (status === "online") return "Online";
  if (status === "degraded") return "Reachable, identity check failed";
  if (status === "offline") return "Offline";
  return "Checking";
}

function formatHealthLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatHealthTime(value: Date) {
  return value.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function jobHealthLabel(jobs: JobQueueStatus | null) {
  if (!jobs) return "Checking";
  if (jobs.running > 0) return `${jobs.running} running`;
  if (jobs.queued > 0) return `${jobs.queued} queued`;
  if (jobs.failed > 0) return `${jobs.failed} failed`;
  return "Idle";
}

function jobHealthDetail(jobs: JobQueueStatus | null) {
  if (!jobs) return "Waiting for the queue status check.";
  return `${jobs.queued} queued / ${jobs.running} running / ${jobs.failed} failed / ${jobs.blocked_by_dependency} blocked`;
}
