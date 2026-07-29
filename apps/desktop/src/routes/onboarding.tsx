import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
  Check,
  Download,
  FolderOpen,
  HardDrive,
  Loader2,
  PlugZap,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/BrandLogo";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  activateLocalModel,
  approveModelDiscoveryRoot,
  cancelModelDownload,
  cancelEmbeddingDownload,
  checkDiskPreflight,
  configureEmbeddingRuntime,
  createVault,
  discoverInstalledModels,
  getEmbeddingDownloadStatus,
  getModelCompatibilityReport,
  getModelRecommendations,
  getModelRuntimeStatus,
  getEmbeddingRuntimeStatus,
  importLocalModel,
  initializeVaultSecurity,
  listLocalModels,
  startEmbeddingDownload,
  startModelDownload,
  type EmbeddingModelDownloadState,
  type EmbeddingRuntimeStatus,
  type DiskPreflightResponse,
  type DiscoveredInstalledModelRecord,
  type InstalledModelDiscoveryRecord,
  type LocalModelRecord,
  type ModelCompatibilityRecord,
  type ModelRecommendationsRecord,
  type ModelRuntimeStatus,
  type VaultRecord,
} from "@/lib/backend";
import { cn } from "@/lib/utils";
import { displayPath } from "@/lib/displayPath";
import { isModelRuntimeReady } from "@/lib/modelState";
import { useVisiblePolling } from "@/lib/useVisiblePolling";

type Step = 0 | 1 | 2 | 3 | 4 | 5 | 6;
type ModelChoice = "recommended" | "custom";
type EmbeddingChoice = "recommended" | "existing";
type ModelOperation = {
  kind: "scan" | "validate" | "import" | "activate";
  state: "active" | "complete" | "error";
  title: string;
  detail: string;
  progress: number;
};

const steps = ["Welcome", "Name", "Library", "Models", "Memory search", "Security", "Finish"] as const;
const recommendedEmbeddingModel = {
  id: "sentence-transformers/all-MiniLM-L6-v2",
  name: "all-MiniLM-L6-v2",
  source: "Hugging Face",
  approximateSize: "About 100 MB",
} as const;

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Set up Vault" }] }),
  component: Onboarding,
});

function Onboarding() {
  const navigate = useNavigate();
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const shellRef = useRef<HTMLElement | null>(null);
  const embeddingPollFailuresRef = useRef(0);
  const modelsLoadedRef = useRef(false);
  const modelSelectionDirtyRef = useRef(false);
  const autoActivationAttemptRef = useRef<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const [setupLoaded, setSetupLoaded] = useState(false);
  const [missingLibraryPath, setMissingLibraryPath] = useState("");

  const [step, setStep] = useState<Step>(0);
  const [displayName, setDisplayName] = useState("");
  const [vaultName, setVaultName] = useState("My Library");
  const [vaultPath, setVaultPath] = useState("");
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [setupVaultId, setSetupVaultId] = useState("");
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelRecommendations, setModelRecommendations] =
    useState<ModelRecommendationsRecord | null>(null);
  const [modelChoice, setModelChoice] = useState<ModelChoice>("recommended");
  const [selectedModelId, setSelectedModelId] = useState("qwen3-4b-q4_k_m");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [modelDownload, setModelDownload] = useState<LocalModelRecord["download"] | null>(null);
  const [modelDownloadRoot, setModelDownloadRoot] = useState("");
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [modelRuntime, setModelRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [customModelPath, setCustomModelPath] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelReport, setCustomModelReport] = useState<ModelCompatibilityRecord | null>(null);
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredInstalledModelRecord[]>([]);
  const [modelDiscovery, setModelDiscovery] = useState<InstalledModelDiscoveryRecord | null>(null);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [hasScannedModels, setHasScannedModels] = useState(false);
  const [modelOperation, setModelOperation] = useState<ModelOperation | null>(null);
  const [embeddingChoice, setEmbeddingChoice] = useState<EmbeddingChoice>("recommended");
  const [embeddingCacheDir, setEmbeddingCacheDir] = useState("");
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingDownload, setEmbeddingDownload] = useState<EmbeddingModelDownloadState | null>(
    null,
  );
  const [diskPreflight, setDiskPreflight] = useState<DiskPreflightResponse | null>(null);
  const [modelDiskPreflight, setModelDiskPreflight] = useState<DiskPreflightResponse | null>(null);
  const [embeddingSaving, setEmbeddingSaving] = useState(false);
  const [showSkipModels, setShowSkipModels] = useState(false);
  const [showEmbeddingConsent, setShowEmbeddingConsent] = useState(false);
  const [showSkipSecurity, setShowSkipSecurity] = useState(false);
  const [securityPassphrase, setSecurityPassphrase] = useState("");
  const [securityPassphraseConfirm, setSecurityPassphraseConfirm] = useState("");
  const [securitySaving, setSecuritySaving] = useState(false);
  const [securityRecoveryKey, setSecurityRecoveryKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeModelDownload = useMemo(() => {
    return selectVisibleModelDownload(models, modelDownload);
  }, [modelDownload, models]);

  const modelDownloadActive = isActiveModelDownloadStatus(activeModelDownload?.status);
  const embeddingDownloadActive =
    embeddingDownload?.status === "queued" || embeddingDownload?.status === "downloading";

  const recommendedModels = useMemo(() => {
    const availableBytes = modelDiskPreflight?.available_bytes ?? Number.POSITIVE_INFINITY;
    const recommendedId = modelRecommendations?.recommended_chat_model_id;
    return models
      .filter(
        (model) =>
          (model.source_kind === "default_choice" || model.compatibility?.chat_role_accepted) &&
          model.approximate_download_gb * 1024 * 1024 * 1024 <= availableBytes,
      )
      .sort((left, right) => {
        if (left.id === recommendedId) return -1;
        if (right.id === recommendedId) return 1;
        return left.approximate_download_gb - right.approximate_download_gb;
      })
      .slice(0, 3);
  }, [
    modelDiskPreflight?.available_bytes,
    modelRecommendations?.recommended_chat_model_id,
    models,
  ]);
  const importedModels = useMemo(
    () => models.filter((model) => model.source_kind === "custom_import"),
    [models],
  );
  const readyChatModel = useMemo(
    () => models.find((model) => isModelRuntimeReady(model, modelRuntime)) ?? null,
    [modelRuntime, models],
  );
  const modelSetupProgress = useMemo((): ModelOperation | null => {
    if (modelDownloadActive && activeModelDownload) {
      const downloadProgress = activeModelDownload.progress_percent ?? 0;
      return {
        kind: "import",
        state: "active",
        title: "Downloading model",
        detail: "Vault will verify and start it when the download finishes.",
        progress: Math.max(3, Math.min(76, downloadProgress * 0.76)),
      };
    }
    if (modelOperation?.state === "active" || modelOperation?.state === "error") {
      return modelOperation;
    }
    if (readyChatModel) {
      return {
        kind: "activate",
        state: "complete",
        title: "Chat model ready",
        detail: `${shortModelName(readyChatModel.name)} is active and ready to answer.`,
        progress: 100,
      };
    }
    return modelOperation;
  }, [activeModelDownload, modelDownloadActive, modelOperation, readyChatModel]);

  const resolvedVaultPath = useMemo(() => {
    const path = vaultPath.trim();
    return path ? `${displayPath(path).replace(/\/+$/, "")}/.vault` : "";
  }, [vaultPath]);

  const canContinue = useMemo(() => {
    if (step === 0) return true;
    if (step === 1) return displayName.trim().length >= 2;
    if (step === 2) return vaultName.trim().length >= 2 && vaultPath.trim().length > 0;
    if (step === 3) {
      return models.some((model) => isModelRuntimeReady(model, modelRuntime));
    }
    if (step === 4) return Boolean(embeddingRuntime?.available);
    if (step === 5) {
      return (
        securityPassphrase.length >= 12 &&
        securityPassphrase === securityPassphraseConfirm &&
        Boolean(vault?.id || setupVaultId)
      );
    }
    return true;
  }, [
    displayName,
    embeddingRuntime?.available,
    modelRuntime?.available,
    modelRuntime?.model,
    modelRuntime?.state,
    models,
    step,
    securityPassphrase,
    securityPassphraseConfirm,
    setupVaultId,
    vault?.id,
    vaultName,
    vaultPath,
  ]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function resumeSetup() {
      try {
        const state = await desktop?.getSetupState?.();
        if (!state || cancelled) return;
        if (state.phase === "complete") {
          await navigate({ to: "/home" });
          return;
        }
        setDisplayName(state.profile.display_name);
        setVaultName(state.vault.name || "My Library");
        setVaultPath(state.vault.path);
        setSetupVaultId(state.vault.id);
        setModelDownloadRoot(state.model_storage.download_root);
        if (state.chat_setup.model_id) {
          setSelectedModelId(state.chat_setup.model_id);
          modelSelectionDirtyRef.current = true;
        }
        const resumedStep = setupPhaseToStep(state.phase);
        setStep(resumedStep);
        if (state.phase === "recovery") {
          if (state.recovery_reason === "missing_vault_data" && state.vault.path) {
            setMissingLibraryPath(state.vault.path);
          } else {
            setError("Vault could not read the previous setup progress. Review these choices to continue.");
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not restore setup progress.");
        }
      } finally {
        if (!cancelled) setSetupLoaded(true);
      }
    }
    void resumeSetup();
    return () => {
      cancelled = true;
    };
  }, [desktop, navigate]);

  useEffect(() => {
    setMessage(null);
    setError(null);
  }, [step]);

  useEffect(() => {
    if (!message) return;
    const timeout = window.setTimeout(() => setMessage(null), 5500);
    return () => window.clearTimeout(timeout);
  }, [message]);

  useEffect(() => {
    if (step !== 3 && step !== 4) return;
    void refreshModels();
    if (step === 3) {
      void refreshModelRecommendations();
    } else {
      void refreshEmbeddingStatus();
    }
  }, [step]);

  useVisiblePolling(refreshModels, 750, modelDownloadActive);
  useVisiblePolling(refreshEmbeddingStatus, 750, embeddingDownloadActive);

  useEffect(() => {
    if (!activeModelDownload || modelDownloadActive) return;
    if (activeModelDownload.status === "failed" || activeModelDownload.status === "blocked") {
      setModelOperation({
        kind: "import",
        state: "error",
        title: "Download stopped",
        detail: activeModelDownload.error || "The model download did not finish.",
        progress: 100,
      });
    } else if (activeModelDownload.status === "cancelled") {
      setModelOperation(null);
    } else if (activeModelDownload.status === "installed" && !readyChatModel && !activatingId) {
      setModelOperation({
        kind: "activate",
        state: "active",
        title: "Preparing chat model",
        detail: "The download is complete. Vault is checking the model now.",
        progress: 78,
      });
    }
  }, [activeModelDownload, activatingId, modelDownloadActive, readyChatModel]);

  useEffect(() => {
    if (step !== 3 || activatingId) return;
    const selected = models.find((model) => model.id === selectedModelId);
    if (
      !selected?.installed ||
      selected.integrity?.status !== "verified" ||
      selected.active_chat ||
      !selected.compatibility?.chat_role_accepted ||
      autoActivationAttemptRef.current === selected.id
    ) {
      return;
    }
    autoActivationAttemptRef.current = selected.id;
    void activateModel(selected.id);
  }, [activatingId, models, selectedModelId, step]);

  async function refreshModels() {
    const showInitialLoading = !modelsLoadedRef.current;
    if (showInitialLoading) setModelsLoading(true);
    try {
      const [rowsResult, runtimeResult] = await Promise.allSettled([
        listLocalModels(),
        getModelRuntimeStatus(),
      ]);
      if (rowsResult.status === "rejected") throw rowsResult.reason;
      const rows = rowsResult.value;
      setModels(rows);
      if (runtimeResult.status === "fulfilled") setModelRuntime(runtimeResult.value);
      setModelDownload((current) => {
        const active = rows
          .map((row) => row.download)
          .find((download) => isActiveModelDownloadStatus(download?.status));
        if (!current) return active ?? null;
        return rows.find((row) => row.id === current.model_id)?.download ?? current;
      });
      if (!rows.some((row) => row.id === selectedModelId) && rows[0]) {
        setSelectedModelId(rows[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load local models.");
    } finally {
      if (showInitialLoading) {
        modelsLoadedRef.current = true;
        setModelsLoading(false);
      }
    }
  }

  async function refreshModelRecommendations() {
    try {
      const recommendations = await getModelRecommendations();
      setModelRecommendations(recommendations);
      if (recommendations.recommended_chat_model_id && !modelSelectionDirtyRef.current) {
        setSelectedModelId(recommendations.recommended_chat_model_id);
      }
    } catch {
      setModelRecommendations(null);
    }
  }

  async function chooseModelFolder() {
    const selected = await desktop?.selectModelCheckpoint?.();
    if (selected) {
      setCustomModelPath(displayPath(selected));
      setCustomModelReport(null);
    }
  }

  async function chooseModelDownloadFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (selected) {
      const normalized = displayPath(selected);
      setModelDownloadRoot(normalized);
      setMessage("Model download location selected.");
      await desktop?.updateSetupState?.({
        model_storage: { download_root: normalized },
      });
      await approveModelDiscoveryRoot(normalized);
      await runModelDiskPreflight(normalized);
    }
  }

  async function runModelDiskPreflight(path: string) {
    if (!path.trim()) {
      setModelDiskPreflight(null);
      return;
    }
    try {
      setModelDiskPreflight(
        await checkDiskPreflight({
          path: path.trim(),
          required_bytes: 1,
        }),
      );
    } catch (err) {
      setModelDiskPreflight(null);
      setError(err instanceof Error ? err.message : "Could not check this location.");
    }
  }

  async function chooseModelScanFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (!selected) return;
    const normalized = displayPath(selected);
    try {
      await approveModelDiscoveryRoot(normalized);
      await refreshDetectedModels(true, normalized);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Could not scan this folder.";
      setModelOperation({
        kind: "scan",
        state: "error",
        title: "Scan stopped",
        detail,
        progress: 100,
      });
      setError(detail);
    }
  }

  async function refreshDetectedModels(refresh = false, selectedRoot = "") {
    setDiscoveringModels(true);
    setError(null);
    setModelOperation({
      kind: "scan",
      state: "active",
      title: "Scanning for models",
      detail: selectedRoot ? `Checking ${displayPath(selectedRoot)}` : "Checking known model folders.",
      progress: 8,
    });
    try {
      const discovered = await discoverInstalledModels(
        { max_results: 24, refresh },
        (_job, detail) => {
          const candidates = numberFromJobDetail(detail.candidates_checked);
          const found = numberFromJobDetail(detail.models_found);
          setModelOperation({
            kind: "scan",
            state: "active",
            title: "Scanning for models",
            detail:
              candidates > 0
                ? `Checked ${candidates.toLocaleString()} files · ${found.toLocaleString()} found`
                : selectedRoot
                  ? `Checking ${displayPath(selectedRoot)}`
                  : "Checking known model folders.",
            progress: Math.min(88, 8 + Math.sqrt(candidates) * 5),
          });
        },
      );
      setDiscoveredModels(discovered.models);
      setModelDiscovery(discovered);
      setModelOperation({
        kind: "scan",
        state: "complete",
        title:
          discovered.models.length === 1
            ? "1 model found"
            : `${discovered.models.length} models found`,
        detail: `Scanned ${discovered.scanned_root_count} ${discovered.scanned_root_count === 1 ? "folder" : "folders"}.`,
        progress: 100,
      });
    } catch (err) {
      setDiscoveredModels([]);
      setModelDiscovery(null);
      const detail =
        err instanceof Error ? err.message : "Could not scan for installed compatible models.";
      setModelOperation({
        kind: "scan",
        state: "error",
        title: "Scan stopped",
        detail,
        progress: 100,
      });
      setError(detail);
    } finally {
      setDiscoveringModels(false);
      setHasScannedModels(true);
    }
  }

  async function validateCustomModel() {
    setError(null);
    setModelOperation({
      kind: "validate",
      state: "active",
      title: "Checking model",
      detail: "Reading the model metadata and chat format.",
      progress: 18,
    });
    try {
      const report = await getModelCompatibilityReport({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      setCustomModelReport(report);
      setModelOperation({
        kind: "validate",
        state: report.accepted ? "complete" : "error",
        title: report.accepted ? "Model is compatible" : "Model cannot be used",
        detail: report.accepted ? "Ready to add to Vault." : report.detail,
        progress: 100,
      });
      if (!report.accepted) setError(report.detail);
    } catch (err) {
      setCustomModelReport(null);
      const detail = err instanceof Error ? err.message : "Could not validate the model.";
      setModelOperation({
        kind: "validate",
        state: "error",
        title: "Model check stopped",
        detail,
        progress: 100,
      });
      setError(detail);
    }
  }

  async function importApprovedModel() {
    setError(null);
    setModelOperation({
      kind: "import",
      state: "active",
      title: "Adding model",
      detail: "Preparing the model for Vault.",
      progress: 12,
    });
    try {
      const imported = await importLocalModel(
        {
          path: customModelPath.trim(),
          name: customModelName.trim() || null,
        },
        (_job, detail) => updateModelImportProgress(detail),
      );
      setCustomModelReport(imported.compatibility);
      await activateImportedModel(imported);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Could not import the model.";
      setModelOperation({
        kind: "import",
        state: "error",
        title: "Model was not added",
        detail,
        progress: 100,
      });
      setError(detail);
    }
  }

  async function importDiscoveredModel(model: DiscoveredInstalledModelRecord) {
    setError(null);
    setModelOperation({
      kind: "import",
      state: "active",
      title: `Adding ${shortModelName(model.name)}`,
      detail: "Copying the model into Vault.",
      progress: 12,
    });
    try {
      const imported = await importLocalModel(
        {
          path: model.local_path,
          name: model.name,
        },
        (_job, detail) => updateModelImportProgress(detail, model.name),
      );
      setCustomModelReport(imported.compatibility);
      await activateImportedModel(imported);
      const refreshed = await discoverInstalledModels({ max_results: 24 });
      setDiscoveredModels(refreshed.models);
      setModelDiscovery(refreshed);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Could not import the detected model.";
      setModelOperation({
        kind: "import",
        state: "error",
        title: "Model was not added",
        detail,
        progress: 100,
      });
      setError(detail);
    }
  }

  function updateModelImportProgress(detail: Record<string, unknown>, modelName = "") {
    const copiedPercent = numberFromJobDetail(detail.progress_percent);
    setModelOperation({
      kind: "import",
      state: "active",
      title: modelName ? `Adding ${shortModelName(modelName)}` : "Adding model",
      detail: copiedPercent > 0 ? `Copying model · ${formatProgressPercent(copiedPercent)}` : "Preparing the model for Vault.",
      progress: Math.min(76, 12 + copiedPercent * 0.64),
    });
  }

  async function activateModel(modelId: string) {
    setError(null);
    modelSelectionDirtyRef.current = true;
    autoActivationAttemptRef.current = modelId;
    setSelectedModelId(modelId);
    setActivatingId(modelId);
    setModelOperation({
      kind: "activate",
      state: "active",
      title: "Starting chat model",
      detail: "Loading the model and checking that it can answer.",
      progress: 82,
    });
    try {
      const activated = await activateLocalModel(modelId, "chat");
      setModels((current) => {
        const found = current.some((model) => model.id === activated.id);
        return found
          ? current.map((model) => (model.id === activated.id ? activated : model))
          : [...current, activated];
      });
      setModelOperation({
        kind: "activate",
        state: "active",
        title: "Checking chat model",
        detail: "Confirming the local model is ready.",
        progress: 94,
      });
      const runtime = await getModelRuntimeStatus();
      setModelRuntime(runtime);
      if (!isModelRuntimeReady(activated, runtime)) {
        throw new Error(runtime.error || "Vault could not confirm that the chat model is ready.");
      }
      await refreshModels();
      setModelOperation({
        kind: "activate",
        state: "complete",
        title: "Chat model ready",
        detail: `${shortModelName(activated.name)} is active and ready to answer.`,
        progress: 100,
      });
      return true;
    } catch (err) {
      await refreshModels();
      const detail = err instanceof Error ? err.message : "Could not activate the model.";
      setModelOperation({
        kind: "activate",
        state: "error",
        title: "Model could not start",
        detail,
        progress: 100,
      });
      setError(detail);
      return false;
    } finally {
      setActivatingId(null);
    }
  }

  async function activateImportedModel(imported: LocalModelRecord) {
    modelSelectionDirtyRef.current = true;
    autoActivationAttemptRef.current = imported.id;
    setSelectedModelId(imported.id);
    setModels((current) => {
      const found = current.some((model) => model.id === imported.id);
      return found
        ? current.map((model) => (model.id === imported.id ? imported : model))
        : [...current, imported];
    });
    if (isModelRuntimeReady(imported, modelRuntime)) {
      setModelOperation({
        kind: "activate",
        state: "complete",
        title: "Chat model ready",
        detail: `${shortModelName(imported.name)} is active and ready to answer.`,
        progress: 100,
      });
      return;
    }
    const activated = await activateModel(imported.id);
    if (activated) {
      return;
    }
    setError((current) =>
      current
        ? `${imported.name} was added, but it could not start. ${current}`
        : `${imported.name} was added, but it could not start. Try Use for chat again.`,
    );
  }

  async function refreshEmbeddingStatus() {
    try {
      const downloadStatus = await getEmbeddingDownloadStatus();
      setEmbeddingDownload(downloadStatus);
      embeddingPollFailuresRef.current = 0;
      setError((current) =>
        current?.includes("local service is unavailable") ||
        current?.includes("Memory search status is reconnecting")
          ? null
          : current,
      );
      if (downloadStatus.status === "queued" || downloadStatus.status === "downloading") {
        return;
      }
      const status = await getEmbeddingRuntimeStatus();
      setEmbeddingRuntime(status);
      if (status.available) setMessage("Memory search is ready.");
    } catch (err) {
      embeddingPollFailuresRef.current += 1;
      if (embeddingPollFailuresRef.current >= 3) {
        setError(
          "Memory search status is reconnecting. An active download will continue while Vault reconnects.",
        );
      }
    }
  }

  async function chooseVaultFolder() {
    const selected = await desktop?.selectVaultFolder?.();
    if (selected) {
      setVaultPath(displayPath(selected));
      await runVaultDiskPreflight(selected);
    }
  }

  async function runVaultDiskPreflight(path: string) {
    if (!path.trim()) return;
    setError(null);
    try {
      const result = await checkDiskPreflight({
        path: `${displayPath(path).replace(/\/+$/, "")}/.vault`,
        required_bytes: 5 * 1024 * 1024 * 1024,
      });
      setDiskPreflight(result);
      if (!result.ok) setError(result.message);
    } catch (err) {
      setDiskPreflight(null);
      setError(err instanceof Error ? err.message : "Could not check disk space.");
    }
  }

  async function createVaultAfterFolderSelection() {
    setError(null);
    setMessage("Opening your vault folder...");
    try {
      const preflight = await checkDiskPreflight({
        path: resolvedVaultPath,
        required_bytes: 5 * 1024 * 1024 * 1024,
      });
      setDiskPreflight(preflight);
      if (!preflight.ok) {
        setError(preflight.message);
        setMessage(null);
        return;
      }
      await desktop?.prepareActiveVaultFolder?.(vaultPath.trim());
      await desktop?.updateSetupState?.({
        phase: "vault_prepared",
        profile: { display_name: displayName.trim() },
        vault: { id: "", name: vaultName.trim(), path: vaultPath.trim() },
      });
      const created = await createVaultWithRetry(vaultName.trim(), vaultPath.trim());
      await desktop?.setActiveVaultFolder?.(vaultPath.trim());
      await desktop?.updateSetupState?.({
        phase: "vault_committed",
        vault: {
          id: created.id,
          name: created.name,
          path: vaultPath.trim(),
        },
      });
      setVault(created);
      setSetupVaultId(created.id);
      setMessage("Library folder is ready.");
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the vault.");
      setMessage(null);
    }
  }

  async function createVaultWithRetry(name: string, path: string) {
    let lastError: unknown;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        return await createVault({ name, path });
      } catch (err) {
        lastError = err;
        await new Promise((resolve) => setTimeout(resolve, 650));
      }
    }
    throw lastError instanceof Error
      ? lastError
      : new Error("The backend did not reopen the vault in time.");
  }

  async function startDownload(modelId: string) {
    setError(null);
    if (!modelDownloadRoot.trim()) {
      setError("Choose where to save the model before downloading.");
      return;
    }
    modelSelectionDirtyRef.current = true;
    setSelectedModelId(modelId);
    autoActivationAttemptRef.current = null;
    setDownloadingId(modelId);
    setModelOperation({
      kind: "import",
      state: "active",
      title: "Preparing download",
      detail: "Checking the model source and available space.",
      progress: 3,
    });
    try {
      const state = await startModelDownload(modelId, {
        target_dir: modelDownloadRoot.trim(),
      });
      setModelDownload(state);
      if (state.status === "failed" || state.status === "blocked") {
        const detail = state.error || "Could not start model download.";
        setModelOperation({
          kind: "import",
          state: "error",
          title: "Download could not start",
          detail,
          progress: 100,
        });
        setError(detail);
      } else {
        setModelOperation({
          kind: "import",
          state: "active",
          title: "Downloading model",
          detail: "Vault will verify and start it when the download finishes.",
          progress: 3,
        });
      }
      await refreshModels();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Could not start model download.";
      setModelOperation({
        kind: "import",
        state: "error",
        title: "Download could not start",
        detail,
        progress: 100,
      });
      setError(detail);
    } finally {
      setDownloadingId(null);
    }
  }

  async function cancelDownload(modelId: string) {
    setError(null);
    try {
      await cancelModelDownload(modelId);
      setModelDownload(null);
      setModelOperation(null);
      await refreshModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel model download.");
    }
  }

  async function saveEmbeddingRuntime() {
    setEmbeddingSaving(true);
    setError(null);
    setMessage("Testing memory search...");
    try {
      const modelPath = embeddingCacheDir.trim();
      if (!modelPath) {
        setError("Choose the folder where your local embedding model is stored before continuing.");
        setMessage(null);
        return;
      }
      const status = await configureEmbeddingRuntime({
        provider: "sentence-transformers",
        cache_dir: modelPath,
      });
      setEmbeddingRuntime(status);
      setMessage(status.available ? "Memory search is ready." : status.detail);
      if (!status.available) {
        setError(status.detail);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not configure memory search.");
    } finally {
      setEmbeddingSaving(false);
    }
  }

  async function chooseEmbeddingFolder() {
    const selected = await desktop?.selectEmbeddingFolder?.();
    if (selected) {
      setEmbeddingCacheDir(selected);
      setMessage("Embedding model folder selected. Test memory search to continue.");
    }
  }

  async function startEmbeddingModelDownload() {
    setError(null);
    if (!embeddingCacheDir.trim()) {
      setError("Choose where to save the model before downloading.");
      return;
    }
    setShowEmbeddingConsent(false);
    setMessage("Starting memory-search model download...");
    try {
      setEmbeddingDownload(
        await startEmbeddingDownload({
          cache_dir: embeddingCacheDir.trim() || null,
          model: recommendedEmbeddingModel.id,
        }),
      );
      setMessage(
        "Memory-search model download started. Keep this setup window open to watch status.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the memory-search download.");
      setMessage(null);
    }
  }

  async function cancelEmbeddingModelDownload() {
    setError(null);
    try {
      setEmbeddingDownload(await cancelEmbeddingDownload());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel the memory-search download.");
    }
  }

  async function next() {
    setError(null);
    setMessage(null);
    if (step === 1) {
      await desktop?.updateSetupState?.({
        phase: "profile_complete",
        profile: { display_name: displayName.trim() },
      });
    } else if (step === 3) {
      const selected = models.find((model) => model.id === selectedModelId);
      await desktop?.updateSetupState?.({
        phase: "models_complete",
        chat_setup: {
          status:
            isModelRuntimeReady(selected, modelRuntime) ? "ready" : "pending",
          model_id: selectedModelId,
        },
      });
    } else if (step === 4) {
      await desktop?.updateSetupState?.({
        phase: "memory_complete",
        memory_setup: {
          status: embeddingRuntime?.available ? "ready" : "pending",
          model_id: recommendedEmbeddingModel.id,
        },
      });
    }
    if (step === 5) {
      const vaultId = vault?.id || setupVaultId;
      if (!vaultId) {
        setError("Vault could not find the library to protect. Go back and check the library step.");
        return;
      }
      setSecuritySaving(true);
      try {
        if (!securityRecoveryKey) {
          const result = await initializeVaultSecurity({
            vault_id: vaultId,
            passphrase: securityPassphrase,
            unlock_mode: "strict",
          });
          setSecurityRecoveryKey(result.recovery_key);
        }
        await desktop?.updateSetupState?.({ phase: "security_complete" });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not protect this library.");
        return;
      } finally {
        setSecuritySaving(false);
      }
    }
    setStep(Math.min(step + 1, 6) as Step);
  }

  async function confirmSkipModels() {
    setShowSkipModels(false);
    setError(null);
    setMessage(null);
    await desktop?.updateSetupState?.({
      phase: "models_complete",
      chat_setup: { status: "skipped", model_id: "" },
    });
    setStep(4);
  }

  async function confirmSkipSecurity() {
    setShowSkipSecurity(false);
    await desktop?.updateSetupState?.({ phase: "security_complete" });
    setStep(6);
  }

  function back() {
    setError(null);
    setMessage(null);
    setStep(Math.max(step - 1, 0) as Step);
  }

  async function finish() {
    const readyChatModel = models.find(
      (model) => isModelRuntimeReady(model, modelRuntime),
    );
    await desktop?.updateSetupState?.({
      phase: "complete",
      profile: { display_name: displayName.trim() },
      vault: {
        id: vault?.id || "",
        name: vault?.name || vaultName.trim(),
        path: vaultPath.trim(),
      },
      chat_setup: {
        status: readyChatModel ? "ready" : "skipped",
        model_id: readyChatModel?.id ?? "",
      },
      memory_setup: {
        status: embeddingRuntime?.available ? "ready" : "skipped",
        model_id: embeddingRuntime?.available ? recommendedEmbeddingModel.id : "",
      },
      tour: { status: "pending", step: 0, version: 1 },
    });
    await navigate({ to: "/home" });
  }

  async function restartAfterMissingLibrary() {
    await desktop?.resetAppSetup?.();
    setMissingLibraryPath("");
    setDisplayName("");
    setVaultName("My Library");
    setVaultPath("");
    setVault(null);
    setSetupVaultId("");
    setStep(0);
  }

  if (!setupLoaded) {
    return <main className="h-full bg-[#fbfbfb]" aria-label="Loading setup" />;
  }

  if (missingLibraryPath) {
    return (
      <main className="flex h-full items-center justify-center bg-[#fbfbfb] px-6 text-[#171717]">
        <section className="w-full max-w-xl rounded-lg border border-[#dedbd5] bg-white p-8 shadow-[0_18px_60px_rgba(50,43,35,0.08)]">
          <BrandLogo className="h-12 w-auto select-none" />
          <div className="mt-10 flex h-11 w-11 items-center justify-center rounded-md bg-[#f4e9dc] text-[#9a5d26]">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">Your library data is missing</h1>
          <p className="mt-3 max-w-lg text-sm leading-6 text-[#655f58]">
            Vault found your completed setup, but the <code>.vault</code> folder is no longer at
            the saved location. It may have been moved or deleted.
          </p>
          <div className="mt-5 rounded-md bg-[#f6f4f0] px-3 py-2 font-mono text-xs text-[#655f58]">
            {displayPath(missingLibraryPath)}/.vault
          </div>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button onClick={() => void restartAfterMissingLibrary()}>
              Start setup again
            </Button>
            <Button
              variant="outline"
              onClick={() => void desktop?.openPath?.(missingLibraryPath)}
            >
              Open saved location
            </Button>
          </div>
          <p className="mt-4 text-xs leading-5 text-[#777069]">
            Starting again clears the broken setup pointer. It does not delete downloaded models
            or files outside the missing library folder.
          </p>
        </section>
      </main>
    );
  }

  if (step === 0) {
    return (
      <main className="flex h-full items-center justify-center bg-[#fbfbfb] text-[#171717]">
        <div className="flex -translate-y-28 flex-col items-center">
          <BrandLogo className="h-[132px] w-auto select-none" />
          <h1 className="mt-20 text-[46px] font-bold tracking-[-0.035em]">Welcome to Vault</h1>
          <Button
            className="mt-11 h-[53px] min-w-[194px] rounded-[3px] bg-[#8d806e] text-white hover:bg-[#786d5f]"
            onClick={() => void next()}
          >
            Start Setup
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main
      ref={shellRef}
      className="vault-onboarding-shell h-full overflow-x-hidden overflow-y-auto bg-background text-foreground"
    >
      <div className="relative z-10 grid min-h-full grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-background px-10 py-10 lg:flex lg:min-h-full lg:flex-col lg:pb-16">
          <div className="flex items-center gap-3">
            <BrandLogo className="h-[92px] w-auto select-none" />
          </div>

          <div className="mt-6">
            <div className="max-w-[280px] text-[30px] font-semibold leading-tight">
              Private memory starts here
            </div>
            <p className="mt-5 max-w-[280px] text-sm leading-6 text-muted-foreground">
              Choose your name, library folder, and local models. Vault will guide you through each
              step.
            </p>
          </div>

          <StepRail step={step} />
        </aside>

        <section className="flex min-h-full min-w-0 items-start justify-center px-4 py-8 sm:px-8 lg:items-center lg:px-10">
          <div className="vault-onboarding-card flex w-full max-w-[860px] min-w-0 flex-col overflow-hidden lg:h-[520px] lg:max-h-[calc(100vh-4rem)]">
            <div className="shrink-0 px-6 pt-6 sm:px-8 lg:pt-0">
              <MobileHeader step={step} />

              <div className="flex h-[93px] items-center justify-between gap-4 border-b border-border">
                <div className="text-sm font-semibold">Vault setup</div>
                <div className="text-sm text-muted-foreground">{steps[step]}</div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 sm:px-8">
              <div key={step} className="vault-step-enter py-10 lg:py-16">
                {step === 1 && (
                  <SetupPanel
                    icon={<UserRound className="h-5 w-5" />}
                    title="What should Vault call you?"
                    sub=""
                  >
                    <Field label="Display name">
                      <Input
                        value={displayName}
                        onChange={(event) => setDisplayName(event.target.value)}
                        placeholder="Your name"
                        autoFocus
                      />
                    </Field>
                  </SetupPanel>
                )}

                {step === 2 && (
                  <SetupPanel
                    icon={<FolderOpen className="h-5 w-5" />}
                    title="Name and locate your library"
                    sub="Choose a recognizable name and the local folder where its sources, index, and chats will live."
                  >
                    <Field label="Library name">
                      <Input
                        value={vaultName}
                        onChange={(event) => setVaultName(event.target.value)}
                        placeholder="My Library"
                        autoFocus
                      />
                    </Field>
                    <div className="mt-5">
                      <Field label="Library location">
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <Input
                            value={vaultPath}
                            onChange={(event) => {
                              setVaultPath(event.target.value);
                              setDiskPreflight(null);
                            }}
                            onBlur={(event) => void runVaultDiskPreflight(event.target.value)}
                            placeholder="C:/Users/You/Documents/Vault"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            onClick={chooseVaultFolder}
                            disabled={!mounted || !desktop?.selectVaultFolder}
                          >
                            <FolderOpen className="h-4 w-4" />
                            Browse
                          </Button>
                        </div>
                      </Field>
                    </div>
                    {resolvedVaultPath && (
                      <div className="rounded-md border border-border bg-secondary/55 p-4 text-sm">
                        <div className="flex items-center gap-2 font-medium">
                          <HardDrive className="h-4 w-4" />
                          Data path
                        </div>
                        <div className="mt-2 break-all font-mono text-xs text-muted-foreground">
                          {resolvedVaultPath}
                        </div>
                        {diskPreflight && (
                          <div
                            className={cn(
                              "mt-3 text-xs",
                              diskPreflight.ok ? "text-[var(--status-ready)]" : "text-destructive",
                            )}
                          >
                            {diskPreflight.message} {formatBytes(diskPreflight.available_bytes)}{" "}
                            available.
                          </div>
                        )}
                      </div>
                    )}
                  </SetupPanel>
                )}

                {step === 3 && (
                  <SetupPanel
                    icon={<PlugZap className="h-5 w-5" />}
                    title="Set up a chat model"
                    sub="Vault uses a model on your computer to write answers. First, choose where to keep it."
                  >
                    {modelSetupProgress ? (
                      <ModelSetupProgress operation={modelSetupProgress} />
                    ) : null}

                    <Field label="Save models in">
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <Input
                          value={modelDownloadRoot}
                          onChange={(event) => {
                            const value = displayPath(event.target.value);
                            setModelDownloadRoot(value);
                            setModelDiskPreflight(null);
                          }}
                          onBlur={(event) => void runModelDiskPreflight(event.target.value)}
                          placeholder="Choose a folder"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void chooseModelDownloadFolder()}
                          disabled={!mounted || !desktop?.selectModelFolder}
                        >
                          <FolderOpen className="h-4 w-4" />
                          Browse
                        </Button>
                      </div>
                      {modelDiskPreflight && (
                        <p className="mt-2 text-xs text-muted-foreground">
                          {formatBytes(modelDiskPreflight.available_bytes)} free in this location.
                        </p>
                      )}
                    </Field>

                    {!modelDownloadRoot.trim() ? (
                      <div className="rounded-md border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                        Choose a location to see the models that fit your computer and available
                        space.
                      </div>
                    ) : (
                      <>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <ChoiceButton
                            selected={modelChoice === "recommended"}
                            title="Download a model"
                            description="Show the best choices for this computer."
                            onClick={() => setModelChoice("recommended")}
                          />
                          <ChoiceButton
                            selected={modelChoice === "custom"}
                            title="Use a model I have"
                            description="Find or choose a model already on this computer."
                            onClick={() => setModelChoice("custom")}
                          />
                        </div>

                        {modelChoice === "recommended" ? (
                          <div className="grid gap-3">
                            <div>
                              <div className="text-sm font-medium">
                                Best choices for this computer
                              </div>
                              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                {modelRecommendations?.chat_recommendation?.summary ??
                                  "Vault checked your memory, processor, graphics, and free space."}
                              </p>
                            </div>
                            {modelsLoading && (
                              <p className="text-sm text-muted-foreground">
                                Loading model options...
                              </p>
                            )}
                            {recommendedModels.map((model) => (
                              <ModelRow
                                key={`chat-${model.id}`}
                                model={model}
                                recommended={
                                  model.id === modelRecommendations?.recommended_chat_model_id
                                }
                                selected={selectedModelId === model.id}
                                busy={downloadingId === model.id}
                                activating={activatingId === model.id}
                                roleActive={Boolean(model.active_chat)}
                                onSelect={() => {
                                  modelSelectionDirtyRef.current = true;
                                  setSelectedModelId(model.id);
                                }}
                                onDownload={() => void startDownload(model.id)}
                                onCancel={() => void cancelDownload(model.id)}
                                onActivate={() => void activateModel(model.id)}
                              />
                            ))}
                            {!modelsLoading && recommendedModels.length === 0 && (
                              <p className="text-sm text-muted-foreground">
                                No model fits the free space in this location. Choose another
                                folder.
                              </p>
                            )}
                          </div>
                        ) : (
                          <div className="grid gap-4">
                            {importedModels.length ? (
                              <div className="grid gap-3">
                                <div>
                                  <div className="text-sm font-medium">Added models</div>
                                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                    Select a model, then use it for chat. Vault checks that it can
                                    answer before setup continues.
                                  </p>
                                </div>
                                {importedModels.map((model) => (
                                  <ModelRow
                                    key={`imported-${model.id}`}
                                    model={model}
                                    recommended={false}
                                    selected={selectedModelId === model.id}
                                    busy={false}
                                    activating={activatingId === model.id}
                                    roleActive={Boolean(model.active_chat)}
                                    onSelect={() => {
                                      modelSelectionDirtyRef.current = true;
                                      setSelectedModelId(model.id);
                                    }}
                                    onDownload={() => undefined}
                                    onCancel={() => undefined}
                                    onActivate={() => void activateModel(model.id)}
                                  />
                                ))}
                              </div>
                            ) : null}
                            <div className="rounded-md border border-border bg-secondary/35 p-4 text-sm">
                              <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                  <div className="font-medium text-foreground">
                                    Models found on this computer
                                  </div>
                                  <div className="mt-1 text-muted-foreground">
                                    Scan known model folders, or choose the folder that contains
                                    your GGUF files.
                                  </div>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  <Button
                                    variant="outline"
                                    onClick={() => void refreshDetectedModels(true)}
                                    disabled={discoveringModels}
                                  >
                                    {discoveringModels ? "Scanning..." : "Scan known folders"}
                                  </Button>
                                  <Button
                                    variant="outline"
                                    onClick={() => void chooseModelScanFolder()}
                                    disabled={
                                      discoveringModels || !mounted || !desktop?.selectModelFolder
                                    }
                                  >
                                    <FolderOpen className="h-4 w-4" />
                                    Choose folder
                                  </Button>
                                </div>
                              </div>
                              <div className="mt-3 grid gap-3">
                                {discoveringModels ? (
                                  <p className="text-xs text-muted-foreground">
                                    Scanning available drives...
                                  </p>
                                ) : discoveredModels.length ? (
                                  discoveredModels.map((model) => (
                                    <div
                                      key={model.id}
                                      className="rounded-md border border-border bg-card p-3"
                                    >
                                      <div className="flex flex-wrap items-start justify-between gap-3">
                                        <div>
                                          <div className="font-medium">{model.name}</div>
                                          <div className="mt-1 text-xs text-muted-foreground">
                                            {model.family_name || model.family || "Supported model"}{" "}
                                            / {displayPath(model.local_path)}
                                          </div>
                                          <div className="mt-1 text-xs text-muted-foreground">
                                            {model.detail}
                                          </div>
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
                                ) : hasScannedModels ? (
                                  <div className="text-xs leading-5 text-muted-foreground">
                                    <p>No supported chat models were found.</p>
                                    {modelDiscovery ? (
                                      <p>
                                        Scanned {modelDiscovery.scanned_root_count}{" "}
                                        {modelDiscovery.scanned_root_count === 1
                                          ? "folder"
                                          : "folders"}
                                        . Choose a folder if the model is stored elsewhere.
                                      </p>
                                    ) : null}
                                  </div>
                                ) : (
                                  <p className="text-xs text-muted-foreground">
                                    Scan known folders or choose a model folder.
                                  </p>
                                )}
                              </div>
                            </div>
                            <Field label="GGUF model file">
                              <div className="flex flex-col gap-2 sm:flex-row">
                                <Input
                                  value={customModelPath}
                                  onChange={(event) =>
                                    setCustomModelPath(displayPath(event.target.value))
                                  }
                                  placeholder="D:/Models/Qwen3-4B-Q4_K_M.gguf"
                                />
                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => void chooseModelFolder()}
                                  disabled={!mounted || !desktop?.selectModelCheckpoint}
                                >
                                  <FolderOpen className="h-4 w-4" />
                                  Browse
                                </Button>
                              </div>
                            </Field>
                            <Field label="Name (optional)">
                              <Input
                                value={customModelName}
                                onChange={(event) => setCustomModelName(event.target.value)}
                                placeholder="My Qwen model"
                              />
                            </Field>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                variant="outline"
                                onClick={() => void validateCustomModel()}
                                disabled={!customModelPath.trim()}
                              >
                                Check model
                              </Button>
                              <Button
                                onClick={() => void importApprovedModel()}
                                disabled={!customModelReport?.accepted}
                              >
                                Add model
                              </Button>
                            </div>
                            {customModelReport && (
                              <div className="rounded-md border border-border bg-card p-4 text-sm">
                                <div className="font-medium">
                                  {customModelReport.accepted
                                    ? "Compatible model"
                                    : "This model cannot be used"}
                                </div>
                                <div className="mt-2 text-muted-foreground">
                                  {customModelReport.detail}
                                </div>
                                <div className="mt-2 text-xs text-muted-foreground">
                                  {customModelReport.selection_detail}
                                </div>
                                {!!customModelReport.reasons.length && (
                                  <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                                    {customModelReport.reasons.map((reason) => (
                                      <li key={reason}>{reason}</li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )}

                    <button
                      type="button"
                      className="w-fit text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                      onClick={() => setShowSkipModels(true)}
                    >
                      Skip for now
                    </button>
                  </SetupPanel>
                )}

                {step === 4 && (
                  <SetupPanel
                    icon={<Sparkles className="h-5 w-5" />}
                    title="Set up memory search"
                    sub="This small model helps Vault find the right parts of your library."
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ChoiceButton
                        selected={embeddingChoice === "recommended"}
                        title="Download the recommended model"
                        description="Best for most people."
                        onClick={() => setEmbeddingChoice("recommended")}
                      />
                      <ChoiceButton
                        selected={embeddingChoice === "existing"}
                        title="Use one I have"
                        description="Choose an existing model folder."
                        onClick={() => setEmbeddingChoice("existing")}
                      />
                    </div>

                    {embeddingChoice === "recommended" && (
                      <div className="rounded-md border border-border bg-card px-4 py-3">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <div className="text-sm font-medium">
                            {recommendedEmbeddingModel.name}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {recommendedEmbeddingModel.approximateSize}
                          </div>
                        </div>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">
                          A local search model that helps Vault find related ideas in your library.
                          It does not write chat answers.
                        </p>
                        <div className="mt-2 text-xs text-muted-foreground">
                          Public Apache 2.0 model. No Hugging Face account or token is required.
                        </div>
                      </div>
                    )}

                    <Field
                      label={
                        embeddingChoice === "recommended"
                          ? "Save model in"
                          : "Embedding cache folder"
                      }
                    >
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <Input
                          value={embeddingCacheDir}
                          onChange={(event) =>
                            setEmbeddingCacheDir(displayPath(event.target.value))
                          }
                          placeholder={
                            embeddingChoice === "recommended"
                              ? "Choose where to save the memory-search model"
                              : "Choose an existing embedding cache folder"
                          }
                        />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void chooseEmbeddingFolder()}
                          disabled={!mounted || !desktop?.selectEmbeddingFolder}
                        >
                          <FolderOpen className="h-4 w-4" />
                          Browse
                        </Button>
                        {embeddingChoice === "recommended" && (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => setShowEmbeddingConsent(true)}
                            disabled={
                              embeddingDownload?.status === "queued" ||
                              embeddingDownload?.status === "downloading" ||
                              !embeddingCacheDir.trim()
                            }
                          >
                            <Download className="h-4 w-4" />
                            Review download
                          </Button>
                        )}
                      </div>
                    </Field>

                    <div className="rounded-md border border-border bg-card p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className="text-sm font-medium">
                            {embeddingRuntime?.available ? "Ready" : "Not ready yet"}
                          </div>
                          <div className="mt-1 text-sm text-muted-foreground">
                            {embeddingRuntime?.detail ??
                              "Choose a folder, download the model, then test it."}
                          </div>
                        </div>
                        {embeddingRuntime?.available && (
                          <Check className="h-5 w-5 text-[var(--status-ready)]" />
                        )}
                      </div>
                      {embeddingDownload && embeddingDownload.status !== "idle" && (
                        <div className="mt-3 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                          <div className="flex items-center justify-between gap-3">
                            <span className="truncate">
                              {shortEmbeddingModelName(embeddingDownload.model_id)}
                            </span>
                            <span className="text-foreground">{embeddingDownload.status}</span>
                          </div>
                          {(embeddingDownload.status === "queued" ||
                            embeddingDownload.status === "downloading") && (
                            <div className="mt-2">
                              <Progress
                                value={embeddingDownload.progress_percent ?? 0}
                                className="download-progress-active h-1.5"
                              />
                              <div className="mt-1 flex items-center justify-between gap-3">
                                <span>
                                  {formatBytes(embeddingDownload.bytes_downloaded ?? 0)}
                                  {embeddingDownload.bytes_total
                                    ? ` / ${formatBytes(embeddingDownload.bytes_total)}`
                                    : " downloaded"}
                                </span>
                                <span>
                                  {embeddingDownload.progress_percent == null
                                    ? "Downloading"
                                    : formatProgressPercent(embeddingDownload.progress_percent)}
                                </span>
                              </div>
                            </div>
                          )}
                          {embeddingDownload.local_path && (
                            <div className="mt-1 truncate font-mono">
                              {displayPath(embeddingDownload.local_path)}
                            </div>
                          )}
                          {embeddingDownload.error && (
                            <div className="mt-1 text-destructive">{embeddingDownload.error}</div>
                          )}
                        </div>
                      )}
                      {(embeddingDownload?.status === "queued" ||
                        embeddingDownload?.status === "downloading") && (
                        <Button
                          variant="outline"
                          className="mt-3"
                          onClick={() => void cancelEmbeddingModelDownload()}
                        >
                          <X className="h-4 w-4" />
                          Cancel download
                        </Button>
                      )}
                      <Button
                        className="mt-4"
                        onClick={() => void saveEmbeddingRuntime()}
                        disabled={embeddingSaving}
                      >
                        {embeddingSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                        Test memory search
                      </Button>
                    </div>
                  </SetupPanel>
                )}

                {step === 5 && (
                  <SetupPanel
                    icon={<HardDrive className="h-5 w-5" />}
                    title="Protect your library"
                    sub="Add a passphrase so Vault starts locked after you close it. You can skip this and turn protection on later."
                  >
                    <div className="max-w-xl space-y-4">
                      <Field label="Passphrase">
                        <Input
                          type="password"
                          autoComplete="new-password"
                          value={securityPassphrase}
                          onChange={(event) => setSecurityPassphrase(event.target.value)}
                          placeholder="Create a passphrase"
                        />
                      </Field>
                      <p className="-mt-2 text-xs text-muted-foreground">
                        Use at least 12 characters. Vault cannot recover it for you.
                      </p>
                      <Field label="Confirm passphrase">
                        <Input
                          type="password"
                          autoComplete="new-password"
                          value={securityPassphraseConfirm}
                          onChange={(event) => setSecurityPassphraseConfirm(event.target.value)}
                          placeholder="Type it again"
                        />
                      </Field>
                      {securityPassphraseConfirm && securityPassphrase !== securityPassphraseConfirm ? (
                        <p className="text-xs text-destructive">The passphrases do not match.</p>
                      ) : null}
                      <button
                        type="button"
                        className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                        onClick={() => setShowSkipSecurity(true)}
                      >
                        Skip protection for now
                      </button>
                      <p className="text-xs leading-5 text-muted-foreground">
                        A 6-digit PIN is not offered yet because destructive actions currently
                        require the full passphrase.
                      </p>
                    </div>
                  </SetupPanel>
                )}

                {step === 6 && (
                  <SetupPanel
                    icon={<Check className="h-5 w-5" />}
                    title="Welcome to Vault"
                    sub={
                      models.some((model) => isModelRuntimeReady(model, modelRuntime))
                        ? "Your library is ready. Add sources, or start a chat when you want to ask across everything."
                        : "Your library is ready. Add sources now; you can set up chat later in Settings."
                    }
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <SummaryRow label="Profile" value={displayName.trim() || "Local user"} />
                      <SummaryRow label="Library" value={vault?.name ?? vaultName.trim()} />
                      <SummaryRow
                        label="Chat model"
                        value={
                          models.find(
                            (model) => isModelRuntimeReady(model, modelRuntime),
                          )?.name ?? "Skipped — set up later in Settings"
                        }
                      />
                      <SummaryRow
                        label="Storage"
                        value={displayPath(resolvedVaultPath) || "Selected library folder"}
                      />
                      <SummaryRow
                        label="Memory search"
                        value={embeddingRuntime?.available ? "Ready" : "Needs setup"}
                      />
                    </div>
                    {securityRecoveryKey ? (
                      <div className="mt-5 rounded-md border border-[var(--status-learning)]/35 bg-[var(--status-learning)]/10 p-4">
                        <div className="text-sm font-medium">Save your recovery key now</div>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          This is the only way to change a forgotten passphrase.
                        </p>
                        <code className="mt-3 block break-all text-xs">{securityRecoveryKey}</code>
                      </div>
                    ) : null}
                  </SetupPanel>
                )}
              </div>

              {(message || error) && (
                <div
                  className={cn(
                    "mb-6 rounded-md border px-4 py-3 text-sm",
                    error
                      ? "border-destructive/30 bg-destructive/5 text-destructive"
                      : "vault-notice-lifetime border-[var(--status-ready)]/25 bg-[var(--status-ready)]/10 text-foreground",
                  )}
                >
                  {error ?? message}
                </div>
              )}
            </div>

            <div className="shrink-0 border-t border-border px-6 pb-6 pt-5 sm:px-8">
              <div className="flex items-center justify-between gap-3">
                <Button variant="ghost" onClick={back}>
                  <ArrowLeft className="h-4 w-4" />
                  Back
                </Button>

                <div className="flex items-center gap-3">
                  <div className="hidden text-xs text-muted-foreground sm:block">
                    {step + 1} of {steps.length}
                  </div>
                  {step === 2 ? (
                    <Button
                      onClick={() => void createVaultAfterFolderSelection()}
                      disabled={!canContinue}
                    >
                      Create vault
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  ) : step === 6 ? (
                    <Button onClick={() => void finish()}>
                      Open Vault
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button onClick={() => void next()} disabled={!canContinue || securitySaving}>
                      {step === 5 ? "Protect and continue" : "Continue"}
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
      {activeModelDownload &&
        (isActiveModelDownloadStatus(activeModelDownload.status) ||
          modelDownload?.model_id === activeModelDownload.model_id) && (
        <ModelDownloadToast
          download={activeModelDownload}
          onCancel={() => void cancelDownload(activeModelDownload.model_id)}
        />
      )}
      {showSkipModels && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setShowSkipModels(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="skip-model-title"
            className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-xl"
          >
            <h2 id="skip-model-title" className="text-lg font-semibold">
              Continue without a chat model?
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              You can finish setup, but Vault cannot write chat answers until a local model is
              added. You can add one later in Settings under Models.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowSkipModels(false)}>
                Cancel
              </Button>
              <Button onClick={() => void confirmSkipModels()}>Confirm skip</Button>
            </div>
          </div>
        </div>
      )}
      {showSkipSecurity && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setShowSkipSecurity(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="skip-security-title"
            className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-xl"
          >
            <h2 id="skip-security-title" className="text-lg font-semibold">
              Continue without library protection?
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Vault will open without asking for a passphrase. You can add one later in Settings
              under Library &amp; security.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <Button variant="outline" onClick={() => setShowSkipSecurity(false)}>
                Go back
              </Button>
              <Button onClick={() => void confirmSkipSecurity()}>Confirm skip</Button>
            </div>
          </div>
        </div>
      )}
      {showEmbeddingConsent && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setShowEmbeddingConsent(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="embedding-consent-title"
            aria-describedby="embedding-consent-description"
            className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-xl"
          >
            <h2 id="embedding-consent-title" className="text-lg font-semibold">
              Download {recommendedEmbeddingModel.name}?
            </h2>
            <p
              id="embedding-consent-description"
              className="mt-3 text-sm leading-6 text-muted-foreground"
            >
              Vault will download this model from {recommendedEmbeddingModel.source} and save it
              on this device. It creates numeric representations of your library so memory search
              can find related text. It is not used to generate chat replies. This is a public
              download; no Hugging Face account token is sent or requested.
            </p>
            <dl className="mt-4 space-y-3 rounded-md border border-border bg-background p-4 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">Model</dt>
                <dd className="mt-1 break-all font-medium">{recommendedEmbeddingModel.id}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Download size</dt>
                <dd className="mt-1 font-medium">{recommendedEmbeddingModel.approximateSize}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Save location</dt>
                <dd className="mt-1 break-all font-mono text-xs">
                  {displayPath(embeddingCacheDir.trim())}
                </dd>
              </div>
            </dl>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowEmbeddingConsent(false)}>
                Cancel
              </Button>
              <Button onClick={() => void startEmbeddingModelDownload()}>
                Agree and download
              </Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function MobileHeader({ step }: { step: Step }) {
  return (
    <div className="mb-7 lg:hidden">
      <div className="flex items-center justify-between">
        <BrandLogo className="h-7 w-auto select-none" />
        <div className="text-xs text-muted-foreground">
          {step + 1} / {steps.length}
        </div>
      </div>
      <Progress className="mt-3 h-1.5" value={((step + 1) / steps.length) * 100} />
    </div>
  );
}

function StepRail({ step }: { step: Step }) {
  return (
    <div className="mt-16 space-y-3">
      {steps.map((label, index) => (
        <div key={label} className="flex items-center gap-3 text-sm">
          <span
            className={cn(
              "flex h-6 w-6 items-center justify-center rounded-md border text-xs transition-colors",
              index < step &&
                "border-[var(--status-ready)] bg-[var(--status-ready)]/12 text-foreground",
              index === step && "border-primary bg-primary text-primary-foreground",
              index > step && "border-border bg-card/60 text-muted-foreground",
            )}
          >
            {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
          </span>
          <span
            className={cn(index === step ? "font-medium text-foreground" : "text-muted-foreground")}
          >
            {label}
          </span>
        </div>
      ))}
    </div>
  );
}

function setupPhaseToStep(phase: DesktopSetupPhase): Step {
  if (phase === "profile_complete" || phase === "vault_prepared") return 2;
  if (phase === "vault_committed") return 3;
  if (phase === "models_complete") return 4;
  if (phase === "memory_complete") return 5;
  if (phase === "security_complete") return 6;
  return 0;
}

function SetupPanel({
  icon,
  title,
  sub,
  children,
}: {
  icon: ReactNode;
  title: string;
  sub: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="flex min-w-0 items-center gap-5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-accent text-accent-foreground">
          {icon}
        </div>
        <h1 className="min-w-0 text-[30px] font-semibold leading-tight text-foreground">{title}</h1>
      </div>
      {sub ? <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground">{sub}</p> : null}
      <div className={cn("grid gap-4", sub ? "mt-6" : "mt-14")}>{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium leading-[17px]">{label}</span>
      <div className="mt-2">{children}</div>
    </label>
  );
}

function ChoiceButton({
  selected,
  title,
  description,
  mark,
  onClick,
}: {
  selected: boolean;
  title: string;
  description: string;
  mark?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border bg-card p-4 text-left shadow-none transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        selected ? "border-primary bg-accent/55" : "border-border",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium">{title}</div>
        {mark ? (
          <span className="flex h-6 w-6 items-center justify-center rounded-md border border-border bg-background text-xs font-semibold">
            {mark}
          </span>
        ) : selected ? (
          <Check className="h-4 w-4 text-primary" />
        ) : null}
      </div>
      <div className="mt-2 text-sm leading-5 text-muted-foreground">{description}</div>
    </button>
  );
}

function ModelSetupProgress({ operation }: { operation: ModelOperation }) {
  const active = operation.state === "active";
  const failed = operation.state === "error";
  const Icon = active ? Loader2 : failed ? AlertTriangle : Check;

  return (
    <div
      className={cn(
        "border-y border-border bg-secondary/35 px-4 py-3",
        failed && "border-destructive/30 bg-destructive/5",
      )}
      role={failed ? "alert" : "status"}
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            active && "animate-spin text-muted-foreground",
            failed && "text-destructive",
            operation.state === "complete" && "text-[var(--status-ready)]",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium text-foreground">{operation.title}</span>
            <span className="tabular-nums text-muted-foreground">
              {formatProgressPercent(operation.progress)}
            </span>
          </div>
          <Progress
            value={operation.progress}
            className={cn("mt-2 h-1.5", active && "download-progress-active")}
            aria-label={`${operation.title}: ${formatProgressPercent(operation.progress)}`}
          />
          <p className={cn("mt-2 text-xs leading-5 text-muted-foreground", failed && "text-destructive")}>
            {operation.detail}
          </p>
        </div>
      </div>
    </div>
  );
}

function ModelRow({
  model,
  recommended,
  selected,
  busy,
  activating,
  roleActive,
  onSelect,
  onDownload,
  onCancel,
  onActivate,
}: {
  model: LocalModelRecord;
  recommended: boolean;
  selected: boolean;
  busy: boolean;
  activating: boolean;
  roleActive: boolean;
  onSelect: () => void;
  onDownload: () => void;
  onCancel: () => void;
  onActivate: () => void;
}) {
  const downloading =
    model.download?.status === "resolving" || model.download?.status === "downloading";
  const needsVerification =
    model.installed &&
    model.source_kind === "default_choice" &&
    model.integrity?.status !== "verified";
  const totalBytes = model.download?.total_bytes ?? model.download?.bytes_total ?? null;
  const progress =
    model.download?.progress_percent ??
    (model.download?.bytes_downloaded && totalBytes
      ? Math.round((model.download.bytes_downloaded / totalBytes) * 100)
      : 0);

  return (
    <div
      className={cn(
        "rounded-md border bg-card p-4 shadow-none transition-colors",
        selected ? "border-primary bg-accent/55" : "border-border",
      )}
    >
      <button type="button" className="block w-full text-left" onClick={onSelect}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium">
              {shortModelName(model.name)}
              {recommended && (
                <span className="rounded-sm bg-primary px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground">
                  Best fit
                </span>
              )}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {model.approximate_download_gb} GB download / {model.recommended_ram_gb} GB RAM
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {roleActive
                ? "Ready for chat"
                : downloading
                  ? "Downloading"
                  : needsVerification
                    ? "Needs verification"
                  : model.installed
                    ? "Installed"
                    : "Ready to download"}
            </div>
          </div>
          {(selected || roleActive) && <Check className="h-4 w-4 text-primary" />}
        </div>
        <p className="mt-2 text-sm leading-5 text-muted-foreground">{model.notes}</p>
        {model.local_path && (
          <p className="mt-2 truncate font-mono text-xs text-muted-foreground">
            {displayPath(model.local_path)}
          </p>
        )}
        {model.source_kind !== "default_choice" &&
          model.compatibility &&
          !model.compatibility.chat_role_accepted && (
            <p className="mt-2 text-xs text-destructive">{model.compatibility.detail}</p>
          )}
      </button>

      {downloading && (
        <div className="mt-3">
          <Progress value={progress} className="download-progress-active h-1.5" />
          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{model.download?.status}</span>
            <span>{formatProgressPercent(progress)}</span>
          </div>
        </div>
      )}
      {model.download?.error && (
        <p className="mt-3 text-xs text-destructive">{model.download.error}</p>
      )}

      <div className="mt-4 flex flex-wrap justify-end gap-3">
        {model.compatibility?.chat_role_accepted && !roleActive && !needsVerification ? (
          <Button variant="outline" size="sm" onClick={onActivate} disabled={activating}>
            {activating ? "Activating" : "Use for chat"}
          </Button>
        ) : null}
        {downloading ? (
          <Button variant="outline" size="sm" onClick={onCancel}>
            <X className="h-4 w-4" />
            Cancel
          </Button>
        ) : (
          <Button
            variant={model.installed ? "outline" : "secondary"}
            size="sm"
            onClick={onDownload}
            disabled={(model.installed && !needsVerification) || busy}
          >
            <Download className="h-4 w-4" />
            {roleActive
              ? "Active"
              : needsVerification
                ? "Download again"
                : model.installed
                  ? "Installed"
                  : busy
                    ? "Starting"
                    : "Download"}
          </Button>
        )}
      </div>
    </div>
  );
}

function selectVisibleModelDownload(
  models: LocalModelRecord[],
  fallback: LocalModelRecord["download"] | null,
) {
  const visible = models
    .map((model) => model.download)
    .filter((download): download is NonNullable<LocalModelRecord["download"]> =>
      Boolean(download?.status && download.status !== "idle"),
    );
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
  const progress =
    download.progress_percent ??
    (download.bytes_downloaded && totalBytes
      ? Math.round((download.bytes_downloaded / totalBytes) * 100)
      : null);
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
        <div className="min-w-0 truncate text-sm font-medium">
          {shortModelName(download.model_id)}
        </div>
        {active && (
          <button
            type="button"
            className="rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Cancel model download"
            onClick={onCancel}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mt-2">
        <Progress
          value={progress ?? fallbackProgress}
          className={cn("h-1.5", active && "download-progress-active")}
        />
        <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            {progress !== null && progress !== undefined
              ? formatProgressPercent(progress)
              : "Preparing download"}
          </span>
          <span className="capitalize">{download.status}</span>
        </div>
        {active ? (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Download active. The percentage may pause while Vault verifies a file.
          </div>
        ) : null}
      </div>
      {download.error && <div className="mt-2 text-xs text-destructive">{download.error}</div>}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="vault-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-sm font-medium">{value}</div>
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

function formatProgressPercent(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0%";
  if (value < 0.1) return "<0.1%";
  if (value < 1) return `${value.toFixed(1)}%`;
  return `${Math.round(value)}%`;
}

function numberFromJobDetail(value: unknown) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function shortModelName(value: string) {
  const cleaned = value
    .replace(/q4[_-]k[_-]m/gi, "")
    .replace(/instruct/gi, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const qwen = cleaned.match(/qwen\s?(\d+)\s+(\d+)b/i);
  if (qwen) return `Qwen${qwen[1]}-${qwen[2]}B`;
  const gemma = cleaned.match(/gemma\s+(\d+)\s+(\d+)b/i);
  if (gemma) return `Gemma-${gemma[1]}-${gemma[2]}B`;
  const phi = cleaned.match(/phi\s+(\d+)\s+mini/i);
  if (phi) return `Phi-${phi[1]} Mini`;
  return cleaned.replace(/\b(\w)/g, (letter) => letter.toUpperCase());
}

function shortEmbeddingModelName(value: string) {
  return value.split("/").pop() || value;
}
