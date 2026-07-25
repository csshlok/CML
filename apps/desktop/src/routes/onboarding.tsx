import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
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
  cancelModelDownload,
  cancelEmbeddingDownload,
  checkDiskPreflight,
  configureEmbeddingRuntime,
  createVault,
  discoverInstalledModels,
  getEmbeddingDownloadStatus,
  getModelCompatibilityReport,
  getModelRecommendations,
  getEmbeddingRuntimeStatus,
  importLocalModel,
  listLocalModels,
  startEmbeddingDownload,
  startModelDownload,
  type EmbeddingModelDownloadState,
  type EmbeddingRuntimeStatus,
  type DiskPreflightResponse,
  type DiscoveredInstalledModelRecord,
  type LocalModelRecord,
  type ModelCompatibilityRecord,
  type ModelRecommendationsRecord,
  type VaultRecord,
} from "@/lib/backend";
import { cn } from "@/lib/utils";
import { displayPath } from "@/lib/displayPath";

type Step = 0 | 1 | 2 | 3 | 4 | 5;
type ModelChoice = "recommended" | "custom";
type EmbeddingChoice = "recommended" | "existing";

const steps = ["Welcome", "Name", "Library", "Models", "Memory search", "Finish"] as const;
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
  const [mounted, setMounted] = useState(false);

  const [step, setStep] = useState<Step>(0);
  const [displayName, setDisplayName] = useState("");
  const [vaultName, setVaultName] = useState("My Library");
  const [vaultPath, setVaultPath] = useState("");
  const [vault, setVault] = useState<VaultRecord | null>(null);
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
  const [customModelPath, setCustomModelPath] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelReport, setCustomModelReport] = useState<ModelCompatibilityRecord | null>(null);
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredInstalledModelRecord[]>([]);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [hasScannedModels, setHasScannedModels] = useState(false);
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

  const resolvedVaultPath = useMemo(() => {
    const path = vaultPath.trim();
    return path ? `${displayPath(path).replace(/\/+$/, "")}/.vault` : "";
  }, [vaultPath]);

  const canContinue = useMemo(() => {
    if (step === 0) return true;
    if (step === 1) return displayName.trim().length >= 2;
    if (step === 2) return vaultName.trim().length >= 2 && vaultPath.trim().length > 0;
    if (step === 3) return models.some(isChatSetupProgress);
    if (step === 4) return Boolean(embeddingRuntime?.available);
    return true;
  }, [displayName, embeddingRuntime?.available, models, step, vaultName, vaultPath]);

  useEffect(() => {
    setMounted(true);
  }, []);

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

  useEffect(() => {
    if (!modelDownloadActive) return;
    const id = window.setInterval(() => {
      void refreshModels();
    }, 1500);
    return () => window.clearInterval(id);
  }, [modelDownloadActive]);

  useEffect(() => {
    if (!embeddingDownloadActive) return;
    const id = window.setInterval(() => {
      void refreshEmbeddingStatus();
    }, 1500);
    return () => window.clearInterval(id);
  }, [embeddingDownloadActive]);

  async function refreshModels() {
    setModelsLoading(true);
    try {
      const rows = await listLocalModels();
      setModels(rows);
      if (!rows.some((row) => row.id === selectedModelId) && rows[0]) {
        setSelectedModelId(rows[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load local models.");
    } finally {
      setModelsLoading(false);
    }
  }

  async function refreshModelRecommendations() {
    try {
      const recommendations = await getModelRecommendations();
      setModelRecommendations(recommendations);
      if (recommendations.recommended_chat_model_id) {
        setSelectedModelId(recommendations.recommended_chat_model_id);
      }
    } catch {
      setModelRecommendations(null);
    }
  }

  async function chooseModelFolder() {
    const selected = await desktop?.selectModelFolder?.();
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

  async function refreshDetectedModels(refresh = false) {
    setDiscoveringModels(true);
    try {
      const discovered = await discoverInstalledModels({ max_results: 24, refresh });
      setDiscoveredModels(discovered.models);
    } catch (err) {
      setDiscoveredModels([]);
      setError(
        err instanceof Error ? err.message : "Could not scan for installed compatible models.",
      );
    } finally {
      setDiscoveringModels(false);
      setHasScannedModels(true);
    }
  }

  async function validateCustomModel() {
    setError(null);
    setMessage("Checking model compatibility...");
    try {
      const report = await getModelCompatibilityReport({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      setCustomModelReport(report);
      setMessage(report.accepted ? "Model accepted." : report.detail);
      if (!report.accepted) setError(report.detail);
    } catch (err) {
      setCustomModelReport(null);
      setError(err instanceof Error ? err.message : "Could not validate the model.");
      setMessage(null);
    }
  }

  async function importApprovedModel() {
    setError(null);
    setMessage("Importing approved model...");
    try {
      const imported = await importLocalModel({
        path: customModelPath.trim(),
        name: customModelName.trim() || null,
      });
      setMessage(`${imported.name} imported and ready.`);
      setCustomModelReport(imported.compatibility);
      await refreshModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import the model.");
      setMessage(null);
    }
  }

  async function importDiscoveredModel(model: DiscoveredInstalledModelRecord) {
    setError(null);
    setMessage(`Importing ${model.name}...`);
    try {
      const imported = await importLocalModel({
        path: model.local_path,
        name: model.name,
      });
      setMessage(`${imported.name} imported and ready.`);
      await refreshModels();
      await refreshDetectedModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import the detected model.");
      setMessage(null);
    }
  }

  async function activateModel(modelId: string) {
    setError(null);
    setActivatingId(modelId);
    try {
      await activateLocalModel(modelId, "chat");
      await refreshModels();
      setMessage("Chat model activated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not activate the model.");
    } finally {
      setActivatingId(null);
    }
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
      const created = await createVaultWithRetry(vaultName.trim(), vaultPath.trim());
      await desktop?.setActiveVaultFolder?.(vaultPath.trim());
      setVault(created);
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
    setDownloadingId(modelId);
    try {
      const state = await startModelDownload(modelId, {
        target_dir: modelDownloadRoot.trim(),
      });
      setModelDownload(state);
      if (state.status === "failed" || state.status === "blocked") {
        setError(state.error || "Could not start model download.");
        setMessage(null);
      } else {
        setMessage("Download started. You can continue setup while it resolves.");
      }
      await refreshModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start model download.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function cancelDownload(modelId: string) {
    setError(null);
    try {
      await cancelModelDownload(modelId);
      setModelDownload(null);
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

  function next() {
    setError(null);
    setMessage(null);
    setStep(Math.min(step + 1, 5) as Step);
  }

  function confirmSkipModels() {
    setShowSkipModels(false);
    setError(null);
    setMessage(null);
    setStep(4);
  }

  function back() {
    setError(null);
    setMessage(null);
    setStep(Math.max(step - 1, 0) as Step);
  }

  function finish() {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ctx.onboarded", "1");
      window.localStorage.setItem("ctx.userName", displayName.trim());
      window.localStorage.setItem("ctx.vaultName", vaultName.trim());
      window.localStorage.setItem("ctx.chatModelChoice", modelChoice);
      window.localStorage.setItem("ctx.chatModelId", selectedModelId);
    }
    navigate({ to: "/home" });
  }

  if (step === 0) {
    return (
      <main className="flex h-screen items-center justify-center bg-[#fbfbfb] text-[#171717]">
        <div className="flex -translate-y-28 flex-col items-center">
          <BrandLogo className="h-[132px] w-auto select-none" />
          <h1 className="mt-20 text-[46px] font-bold tracking-[-0.035em]">Welcome to Vault</h1>
          <Button
            className="mt-11 h-[53px] min-w-[194px] rounded-[3px] bg-[#8d806e] text-white hover:bg-[#786d5f]"
            onClick={next}
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
      className="vault-onboarding-shell h-screen overflow-x-hidden overflow-y-auto bg-background text-foreground"
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
          <div className="vault-onboarding-card flex w-full max-w-[860px] min-w-0 flex-col overflow-hidden lg:h-[520px]">
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
                                onSelect={() => setSelectedModelId(model.id)}
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
                            <div className="rounded-md border border-border bg-secondary/35 p-4 text-sm">
                              <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                  <div className="font-medium text-foreground">
                                    Models found on this computer
                                  </div>
                                  <div className="mt-1 text-muted-foreground">
                                    Vault checks every available drive. This may take a moment.
                                  </div>
                                </div>
                                <Button
                                  variant="outline"
                                  onClick={() => void refreshDetectedModels(true)}
                                  disabled={discoveringModels}
                                >
                                  {discoveringModels ? "Scanning..." : "Scan device"}
                                </Button>
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
                                  <p className="text-xs text-muted-foreground">
                                    No supported chat models were found.
                                  </p>
                                ) : (
                                  <p className="text-xs text-muted-foreground">
                                    Select Scan device to look for models.
                                  </p>
                                )}
                              </div>
                            </div>
                            <Field label="Model folder">
                              <div className="flex flex-col gap-2 sm:flex-row">
                                <Input
                                  value={customModelPath}
                                  onChange={(event) =>
                                    setCustomModelPath(displayPath(event.target.value))
                                  }
                                  placeholder="D:/Models/Qwen3-4B"
                                />
                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => void chooseModelFolder()}
                                  disabled={!mounted || !desktop?.selectModelFolder}
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
                                    ? "Ready to use"
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
                          ? "Downloaded model folder"
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
                              ? "Choose a local embedding model folder"
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
                                className="h-1.5"
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
                    icon={<Check className="h-5 w-5" />}
                    title="Welcome to Vault"
                    sub="Your library is ready. Add sources from the Sources workspace, or start with chat when you want to ask across everything."
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <SummaryRow label="Profile" value={displayName.trim() || "Local user"} />
                      <SummaryRow label="Library" value={vault?.name ?? vaultName.trim()} />
                      <SummaryRow
                        label="Chat model"
                        value={
                          models.find((model) => model.id === selectedModelId)?.name ??
                          selectedModelId
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
                  ) : step === 5 ? (
                    <Button onClick={finish}>
                      Open Vault
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button onClick={next} disabled={!canContinue}>
                      Continue
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
      {activeModelDownload && isActiveModelDownloadStatus(activeModelDownload.status) && (
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
              <Button onClick={confirmSkipModels}>Confirm skip</Button>
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
              can find related text. It is not used to generate chat replies. The download is
              anonymous; Vault does not send or request a Hugging Face account token.
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
          <Progress value={progress} className="h-1.5" />
          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{model.download?.status}</span>
            <span>{formatProgressPercent(progress)}</span>
          </div>
        </div>
      )}
      {model.download?.error && (
        <p className="mt-3 text-xs text-destructive">{model.download.error}</p>
      )}

      <div className="mt-3 flex justify-end gap-2">
        {model.compatibility?.chat_role_accepted && !roleActive ? (
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
            disabled={model.installed || busy}
          >
            <Download className="h-4 w-4" />
            {roleActive ? "Active" : model.installed ? "Installed" : busy ? "Starting" : "Download"}
          </Button>
        )}
      </div>
    </div>
  );
}

function isChatSetupProgress(model: LocalModelRecord) {
  const downloadStatus = model.download?.status;
  const managedChatDownloadInProgress =
    model.source_kind === "default_choice" &&
    (downloadStatus === "resolving" || downloadStatus === "downloading");
  return Boolean(
    managedChatDownloadInProgress ||
    (model.compatibility?.chat_role_accepted &&
      (model.active_chat || model.installed || downloadStatus === "installed")),
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
    (fallback && isActiveModelDownloadStatus(fallback.status) ? fallback : null) ??
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
  const totalBytes = download.total_bytes ?? download.bytes_total ?? null;
  const progress =
    download.progress_percent ??
    (download.bytes_downloaded && totalBytes
      ? Math.round((download.bytes_downloaded / totalBytes) * 100)
      : null);
  const active = isActiveModelDownloadStatus(download.status);
  const fallbackProgress = download.status === "installed" ? 100 : 0;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[min(18rem,calc(100vw-2rem))] rounded-md border border-border bg-card p-3 shadow-lg">
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
        <Progress value={progress ?? fallbackProgress} className="h-1.5" />
        <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            {progress !== null && progress !== undefined
              ? formatProgressPercent(progress)
              : "Preparing download"}
          </span>
          <span className="capitalize">{download.status}</span>
        </div>
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
