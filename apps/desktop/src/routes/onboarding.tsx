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
  ShieldCheck,
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
  type VaultRecord,
} from "@/lib/backend";
import { cn } from "@/lib/utils";

type Step = 0 | 1 | 2 | 3 | 4 | 5;
type ModelChoice = "recommended" | "custom";
type EmbeddingChoice = "recommended" | "existing";

const steps = [
  "Welcome",
  "Profile",
  "Library",
  "Chat model",
  "Memory search",
  "Finish",
] as const;

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Set up Vault" }] }),
  component: Onboarding,
});

function Onboarding() {
  const navigate = useNavigate();
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  const shellRef = useRef<HTMLElement | null>(null);
  const [mounted, setMounted] = useState(false);

  const [step, setStep] = useState<Step>(0);
  const [displayName, setDisplayName] = useState("");
  const [vaultName, setVaultName] = useState("My Library");
  const [vaultPath, setVaultPath] = useState("");
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
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
  const [embeddingChoice, setEmbeddingChoice] = useState<EmbeddingChoice>("recommended");
  const [embeddingCacheDir, setEmbeddingCacheDir] = useState("");
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingDownload, setEmbeddingDownload] = useState<EmbeddingModelDownloadState | null>(
    null,
  );
  const [diskPreflight, setDiskPreflight] = useState<DiskPreflightResponse | null>(null);
  const [embeddingSaving, setEmbeddingSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);


  const activeModelDownload = useMemo(() => {
    return selectVisibleModelDownload(models, modelDownload);
  }, [modelDownload, models]);

  const modelDownloadActive = isActiveModelDownloadStatus(activeModelDownload?.status);

  const resolvedVaultPath = useMemo(() => {
    const path = vaultPath.trim();
    return path ? `${path.replace(/[\\/]+$/, "")}\\.vault` : "";
  }, [vaultPath]);

  const canContinue = useMemo(() => {
    if (step === 0) return true;
    if (step === 1) return displayName.trim().length >= 2;
    if (step === 2) return vaultName.trim().length >= 2 && vaultPath.trim().length > 0;
    if (step === 3) return models.some(isChatSetupProgress);
    if (step === 4) return Boolean(embeddingRuntime?.available);
    return true;
  }, [
    displayName,
    embeddingRuntime?.available,
    models,
    step,
    vaultName,
    vaultPath,
  ]);


  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (step !== 3 && step !== 4) return;
    void refreshModels();
    void refreshEmbeddingStatus();
    if (step === 3) {
      void refreshDetectedModels();
    }
  }, [step]);

  useEffect(() => {
    if (step !== 3 || !modelDownloadActive) return;
    const id = window.setInterval(() => {
      void refreshModels();
    }, 1500);
    return () => window.clearInterval(id);
  }, [modelDownloadActive, step]);

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

  async function chooseModelFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (selected) {
      setCustomModelPath(selected);
      setCustomModelReport(null);
    }
  }

  async function chooseModelDownloadFolder() {
    const selected = await desktop?.selectModelFolder?.();
    if (selected) {
      setModelDownloadRoot(selected);
      setMessage("Model download location selected.");
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
      const status = await getEmbeddingRuntimeStatus();
      const downloadStatus = await getEmbeddingDownloadStatus();
      setEmbeddingRuntime(status);
      setEmbeddingDownload(downloadStatus);
      if (status.available) setMessage("Memory search is ready.");
    } catch (err) {
      setEmbeddingRuntime(null);
      setError(err instanceof Error ? err.message : "Could not check memory search.");
    }
  }

  async function chooseVaultFolder() {
    const selected = await desktop?.selectVaultFolder?.();
    if (selected) {
      setVaultPath(selected);
      await runVaultDiskPreflight(selected);
    }
  }

  async function runVaultDiskPreflight(path: string) {
    if (!path.trim()) return;
    setError(null);
    try {
      const result = await checkDiskPreflight({
        path: `${path.replace(/[\\/]+$/, "")}\\.vault`,
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
    setDownloadingId(modelId);
    try {
      const state = await startModelDownload(modelId, {
        target_dir: modelDownloadRoot.trim() || null,
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
      const state = await cancelModelDownload(modelId);
      setModelDownload(state);
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
    setMessage("Starting memory-search model download...");
    try {
      setEmbeddingDownload(
        await startEmbeddingDownload({
          cache_dir: embeddingCacheDir.trim() || null,
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

  return (
    <main
      ref={shellRef}
      className="vault-onboarding-shell h-screen overflow-x-hidden overflow-y-auto bg-background text-foreground"
    >
      <AnimatedBackground />

      <div className="relative z-10 grid min-h-full grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-background px-10 py-10 lg:flex lg:min-h-full lg:flex-col lg:pb-16">
          <div className="flex items-center gap-3">
            <BrandLogo className="h-12 w-auto select-none" />
          </div>

          <div className="mt-16">
            <div className="max-w-[280px] text-[30px] font-semibold leading-tight">
              Private memory starts here
            </div>
            <p className="mt-5 max-w-[280px] text-sm leading-6 text-muted-foreground">
              Choose a real vault folder, connect local models, and keep setup honest before the app
              opens.
            </p>
          </div>

          <StepRail step={step} />
        </aside>

        <section className="flex min-h-full min-w-0 items-start justify-center px-4 py-8 sm:px-8 lg:items-center lg:px-10">
          <div className="vault-onboarding-card flex w-full max-w-[860px] min-w-0 flex-col overflow-hidden lg:max-h-[calc(100vh-4rem)]">
            <div className="shrink-0 px-6 pb-6 pt-6 sm:px-8">
              <MobileHeader step={step} />

              <div className="flex items-start justify-between gap-4 border-b border-border pb-6">
                <div>
                  <div className="text-sm font-semibold">Vault setup</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Step {step + 1} of {steps.length} / {steps[step]}
                  </div>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 sm:px-8">
              <div key={step} className="vault-step-enter py-10">
                {step === 0 && (
                  <SetupPanel
                    icon={<ShieldCheck className="h-5 w-5" />}
                    title="Welcome to Vault"
                    sub="A private knowledge workspace that keeps your sources, search index, and conversations on this device."
                  >
                    <div className="mt-5 divide-y divide-border border-y border-border text-sm">
                      <div className="flex items-center justify-between gap-4 py-3"><span>Sources</span><span className="text-muted-foreground">Private and local</span></div>
                      <div className="flex items-center justify-between gap-4 py-3"><span>Search</span><span className="text-muted-foreground">Runs on this device</span></div>
                      <div className="flex items-center justify-between gap-4 py-3"><span>Storage</span><span className="text-muted-foreground">Folder you choose</span></div>
                    </div>
                  </SetupPanel>
                )}

                {step === 1 && (
                  <SetupPanel
                    icon={<UserRound className="h-5 w-5" />}
                    title="What should Vault call you?"
                    sub="This name stays in your local profile and appears in your workspace."
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
                            placeholder="C:\\Users\\You\\Documents\\Vault"
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
                    title="Choose the local chat model"
                    sub="A local chat model writes answers from the sources Vault finds. Citations always come from your library."
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ChoiceButton
                        selected={modelChoice === "recommended"}
                        title="Download model"
                        description="Download a local chat model that fits this device."
                        onClick={() => setModelChoice("recommended")}
                      />
                      <ChoiceButton
                        selected={modelChoice === "custom"}
                        title="Import checkpoint"
                        description="Validate a local checkpoint and accept or reject it for local chat use."
                        onClick={() => setModelChoice("custom")}
                      />
                    </div>

                    {modelChoice === "recommended" ? (
                      <div className="grid gap-3">
                        <div className="rounded-md border border-border bg-secondary/55 p-4 text-sm text-muted-foreground">
                          Downloaded runtime models power answer synthesis. Vault citations still
                          come from retrieval, not model memory.
                        </div>
                        <Field label="Local model download location">
                          <div className="flex flex-col gap-2 sm:flex-row">
                            <Input
                              value={modelDownloadRoot}
                              onChange={(event) => setModelDownloadRoot(event.target.value)}
                              placeholder="Choose where Vault should store downloaded GGUF models"
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
                          <p className="mt-2 text-xs text-muted-foreground">
                            Leave blank to use Vault's default model folder. Downloads continue in
                            the background while you finish setup.
                          </p>
                        </Field>
                        <div className="grid gap-3">
                          <div className="text-sm font-medium">Chat model</div>
                          {modelsLoading && (
                            <p className="text-sm text-muted-foreground">
                              Loading model options...
                            </p>
                          )}
                          {models
                            .filter(
                              (model) =>
                                model.compatibility?.chat_role_accepted ||
                                model.source_kind === "default_choice",
                            )
                            .map((model) => (
                              <ModelRow
                                key={`chat-${model.id}`}
                                model={model}
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
                        </div>
                      </div>
                    ) : (
                      <div className="grid gap-4">
                        <div className="rounded-md border border-border bg-secondary/35 p-4 text-sm">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="font-medium text-foreground">
                                Compatible models already on this device
                              </div>
                              <div className="mt-1 text-muted-foreground">
                                Vault can scan common local model folders and offer one-click import
                                for accepted local chat checkpoints.
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
                                Scanning configured and common model folders...
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
                                        {model.family_name || model.family || "Approved family"} /{" "}
                                        {model.local_path}
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
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                No accepted local Transformers checkpoints were found in the
                                configured or common model directories.
                              </p>
                            )}
                          </div>
                        </div>
                        <Field label="Checkpoint folder">
                          <div className="flex flex-col gap-2 sm:flex-row">
                            <Input
                              value={customModelPath}
                              onChange={(event) => setCustomModelPath(event.target.value)}
                              placeholder="D:\\Models\\Qwen3-4B"
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
                        <Field label="Display name">
                          <Input
                            value={customModelName}
                            onChange={(event) => setCustomModelName(event.target.value)}
                            placeholder="My local Qwen checkpoint"
                          />
                        </Field>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            onClick={() => void validateCustomModel()}
                            disabled={!customModelPath.trim()}
                          >
                            Test model
                          </Button>
                          <Button
                            onClick={() => void importApprovedModel()}
                            disabled={!customModelReport?.accepted}
                          >
                            Import approved model
                          </Button>
                        </div>
                        {customModelReport && (
                          <div className="rounded-md border border-border bg-card p-4 text-sm">
                            <div className="font-medium">
                              {customModelReport.accepted ? "Accepted" : "Rejected"}
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

                    <p className="text-xs text-muted-foreground">
                      You can continue after a chat model is installed, active, or downloading.
                      You can import more local chat models now or later from Settings.
                    </p>
                  </SetupPanel>
                )}

                {step === 4 && (
                  <SetupPanel
                    icon={<Sparkles className="h-5 w-5" />}
                    title="Choose the memory-search model"
                    sub="This step is required. Download the recommended model after install, or link a compatible model cache already on this device."
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ChoiceButton
                        selected={embeddingChoice === "recommended"}
                        title="Vault recommended"
                        description="Use all-MiniLM-L6-v2 after you download it locally."
                        onClick={() => setEmbeddingChoice("recommended")}
                      />
                      <ChoiceButton
                        selected={embeddingChoice === "existing"}
                        title="Existing cache"
                        description="Point Vault at a local model cache folder."
                        onClick={() => setEmbeddingChoice("existing")}
                      />
                    </div>

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
                          onChange={(event) => setEmbeddingCacheDir(event.target.value)}
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
                            onClick={() => void startEmbeddingModelDownload()}
                            disabled={
                              embeddingDownload?.status === "queued" ||
                              embeddingDownload?.status === "downloading"
                            }
                          >
                            <Download className="h-4 w-4" />
                            Download
                          </Button>
                        )}
                      </div>
                    </Field>

                    <div className="rounded-md border border-border bg-card p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className="text-sm font-medium">
                            {embeddingRuntime?.available
                              ? "Memory search ready"
                              : "Memory search needs setup"}
                          </div>
                          <div className="mt-1 text-sm text-muted-foreground">
                            {embeddingRuntime?.detail ??
                              "Run a local test before entering Vault. Setup cannot finish until this passes."}
                          </div>
                        </div>
                        {embeddingRuntime?.available && (
                          <Check className="h-5 w-5 text-[var(--status-ready)]" />
                        )}
                      </div>
                      {embeddingDownload && embeddingDownload.status !== "idle" && (
                        <div className="mt-3 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                          <div className="flex items-center justify-between gap-3">
                            <span className="truncate">{embeddingDownload.model_id}</span>
                            <span className="text-foreground">{embeddingDownload.status}</span>
                          </div>
                          {embeddingDownload.local_path && (
                            <div className="mt-1 truncate font-mono">
                              {embeddingDownload.local_path}
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
                        value={resolvedVaultPath || "Selected library folder"}
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
                      : "border-[var(--status-ready)]/25 bg-[var(--status-ready)]/10 text-foreground",
                  )}
                >
                  {error ?? message}
                </div>
              )}
            </div>

            <div className="shrink-0 border-t border-border px-6 pb-6 pt-5 sm:px-8">
              <div className="flex items-center justify-between gap-3">
                <Button variant="ghost" onClick={back} disabled={step === 0}>
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
      {activeModelDownload && activeModelDownload.status !== "idle" && (
        <ModelDownloadToast
          download={activeModelDownload}
          onCancel={() => void cancelDownload(activeModelDownload.model_id)}
        />
      )}
    </main>
  );
}

function AnimatedBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="vault-bg-wash" />
      <div className="vault-bg-lines" />
    </div>
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
    <div className="mt-auto space-y-3">
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
      <div className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-accent text-accent-foreground">
        {icon}
      </div>
      <h1 className="mt-6 text-[30px] font-semibold text-foreground">{title}</h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">{sub}</p>
      <div className="mt-8 grid gap-4">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
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
            <div className="text-sm font-medium">{model.name}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {model.role} / {model.quantization} / {model.approximate_download_gb} GB /{" "}
              {model.recommended_ram_gb} GB RAM
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {model.compatibility?.chat_role_accepted ? "Accepted for chat" : "Not accepted for chat"}
            </div>
          </div>
          {(selected || roleActive) && <Check className="h-4 w-4 text-primary" />}
        </div>
        <p className="mt-2 text-sm leading-5 text-muted-foreground">{model.notes}</p>
        {model.local_path && (
          <p className="mt-2 truncate font-mono text-xs text-muted-foreground">
            {model.local_path}
          </p>
        )}
        {model.compatibility && !model.compatibility.chat_role_accepted && (
          <p className="mt-2 text-xs text-destructive">{model.compatibility.detail}</p>
        )}
      </button>

      {downloading && (
        <div className="mt-3">
          <Progress value={progress || 12} className="h-1.5" />
          <div className="mt-1 text-xs text-muted-foreground">{model.download?.status}</div>
        </div>
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
  const fallbackProgress = active ? 10 : download.status === "installed" ? 100 : 0;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-border bg-card/95 p-4 shadow-2xl backdrop-blur">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">Model download</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{download.model_id}</div>
        </div>
        <span className="rounded-full border border-border bg-background px-2 py-0.5 text-xs capitalize text-muted-foreground">
          {download.status}
        </span>
      </div>
      <div className="mt-3">
        <Progress value={progress ?? fallbackProgress} className="h-1.5" />
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            {progress !== null && progress !== undefined
              ? `${Math.round(progress)}%`
              : "Preparing download"}
          </span>
          <span>
            {formatBytes(download.bytes_downloaded ?? 0)}
            {totalBytes ? ` / ${formatBytes(totalBytes)}` : ""}
          </span>
        </div>
      </div>
      {download.local_path && (
        <div className="mt-2 truncate font-mono text-[11px] text-muted-foreground">
          {download.local_path}
        </div>
      )}
      {download.error && <div className="mt-2 text-xs text-destructive">{download.error}</div>}
      {active && (
        <Button variant="outline" size="sm" className="mt-3 w-full" onClick={onCancel}>
          <X className="h-4 w-4" />
          Cancel download
        </Button>
      )}
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
