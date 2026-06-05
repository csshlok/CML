import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  FolderOpen,
  HardDrive,
  Loader2,
  Mail,
  PlugZap,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  activateLocalModel,
  cancelModelDownload,
  cancelEmbeddingDownload,
  checkDiskPreflight,
  configureEmbeddingRuntime,
  createVault,
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
  type LocalModelRecord,
  type ModelCompatibilityRecord,
  type VaultRecord,
} from "@/lib/backend";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/mockStore";

type Step = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;
type SignupMethod = "email" | "google";
type ModelChoice = "recommended" | "custom";
type EmbeddingChoice = "recommended" | "existing";

const steps = [
  "Sign up",
  "Name",
  "Vault",
  "Welcome",
  "Location",
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
  const store = useStore();
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;

  const [step, setStep] = useState<Step>(0);
  const [signupMethod, setSignupMethod] = useState<SignupMethod>("email");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [vaultName, setVaultName] = useState("My Vault");
  const [vaultPath, setVaultPath] = useState("");
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelChoice, setModelChoice] = useState<ModelChoice>("recommended");
  const [selectedModelId, setSelectedModelId] = useState("qwen3-4b-q4_k_m");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [customModelPath, setCustomModelPath] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelReport, setCustomModelReport] = useState<ModelCompatibilityRecord | null>(null);
  const [embeddingChoice, setEmbeddingChoice] = useState<EmbeddingChoice>("recommended");
  const [embeddingCacheDir, setEmbeddingCacheDir] = useState("");
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingDownload, setEmbeddingDownload] = useState<EmbeddingModelDownloadState | null>(null);
  const [diskPreflight, setDiskPreflight] = useState<DiskPreflightResponse | null>(null);
  const [embeddingSaving, setEmbeddingSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? models[0] ?? null,
    [models, selectedModelId],
  );

  const resolvedVaultPath = useMemo(() => {
    const path = vaultPath.trim();
    return path ? `${path.replace(/[\\/]+$/, "")}\\.vault` : "";
  }, [vaultPath]);

  const canContinue = useMemo(() => {
    if (step === 0) {
      if (signupMethod === "google") return true;
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
    }
    if (step === 1) return displayName.trim().length >= 2;
    if (step === 2) return vaultName.trim().length >= 2;
    if (step === 4) return vaultPath.trim().length > 0;
    if (step === 5) return Boolean(models.some((model) => model.active && model.compatibility?.accepted));
    if (step === 6) return Boolean(embeddingRuntime?.available);
    return true;
  }, [displayName, email, embeddingRuntime?.available, models, signupMethod, step, vaultName, vaultPath]);

  useEffect(() => {
    if (step !== 5 && step !== 6) return;
    void refreshModels();
    void refreshEmbeddingStatus();
  }, [step]);

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

  async function activateModel(modelId: string) {
    setError(null);
    setActivatingId(modelId);
    try {
      await activateLocalModel(modelId);
      await refreshModels();
      setMessage("Approved model activated.");
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
      await desktop?.setActiveVaultFolder?.(vaultPath.trim());
      const created = await createVaultWithRetry(vaultName.trim(), vaultPath.trim());
      setVault(created);
      store.setVault(created.path);
      setMessage("Vault folder is ready.");
      setStep(5);
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
    throw lastError instanceof Error ? lastError : new Error("The backend did not reopen the vault in time.");
  }

  async function startDownload(modelId: string) {
    setError(null);
    setDownloadingId(modelId);
    try {
      await startModelDownload(modelId);
      setMessage("Download started. You can continue setup while it resolves.");
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
      setMessage("Memory-search model download started. Keep this setup window open to watch status.");
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
    if (step === 0 && signupMethod === "google") {
      setMessage("Google OAuth is not connected in this local build; a local profile will be created.");
    }
    setStep(Math.min(step + 1, 7) as Step);
  }

  function back() {
    setError(null);
    setMessage(null);
    setStep(Math.max(step - 1, 0) as Step);
  }

  function finish() {
    store.completeSetup();
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ctx.onboarded", "1");
      window.localStorage.setItem("ctx.userName", displayName.trim());
      window.localStorage.setItem("ctx.userEmail", email.trim());
      window.localStorage.setItem("ctx.signupMethod", signupMethod);
      window.localStorage.setItem("ctx.vaultName", vaultName.trim());
      window.localStorage.setItem("ctx.chatModelChoice", modelChoice);
      window.localStorage.setItem("ctx.chatModelId", selectedModelId);
    }
    navigate({ to: "/search" });
  }

  return (
    <main className="vault-onboarding-shell min-h-screen overflow-hidden bg-background text-foreground">
      <AnimatedBackground />

      <div className="relative z-10 grid min-h-screen grid-cols-1 lg:grid-cols-[360px_1fr]">
        <aside className="hidden border-r border-border bg-background px-10 py-10 lg:flex lg:flex-col">
          <div className="flex items-center gap-3">
            <div className="vault-sidebar-mark flex h-8 w-8 items-center justify-center rounded-md">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">Vault</div>
              <div className="text-xs text-muted-foreground">Local memory setup</div>
            </div>
          </div>

          <div className="mt-16">
            <div className="max-w-[280px] text-[30px] font-semibold leading-tight">
              Private memory starts here
            </div>
            <p className="mt-5 max-w-[280px] text-sm leading-6 text-muted-foreground">
              Choose a real vault folder, connect local models, and keep setup honest before the app opens.
            </p>
          </div>

          <StepRail step={step} />
        </aside>

        <section className="flex min-h-screen items-center justify-center px-5 py-8 sm:px-10">
          <div className="vault-onboarding-card w-full max-w-[880px]">
            <MobileHeader step={step} />

            <div className="border-b border-border pb-6">
              <div className="text-sm font-semibold">Vault setup</div>
              <div className="mt-1 text-sm text-muted-foreground">
                Step {step + 1} of {steps.length} / {steps[step]}
              </div>
            </div>

            <div key={step} className="vault-step-enter py-10">
              {step === 0 && (
                <SetupPanel
                  icon={<Mail className="h-5 w-5" />}
                  title="Sign up to Vault"
                  sub="This creates a local profile for your device. Cloud accounts can be connected later."
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ChoiceButton
                      selected={signupMethod === "email"}
                      title="Email"
                      description="Use an email for your local profile."
                      onClick={() => setSignupMethod("email")}
                    />
                    <ChoiceButton
                      selected={signupMethod === "google"}
                      title="Google"
                      description="Reserved for OAuth; local profile now."
                      onClick={() => setSignupMethod("google")}
                      mark="G"
                    />
                  </div>
                  {signupMethod === "email" && (
                    <Field label="Email">
                      <Input
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        placeholder="you@example.com"
                        autoFocus
                      />
                    </Field>
                  )}
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
                  icon={<Sparkles className="h-5 w-5" />}
                  title="Name your vault"
                  sub="A vault is the local memory space where your files, links, notes, and chats live."
                >
                  <Field label="Vault name">
                    <Input
                      value={vaultName}
                      onChange={(event) => setVaultName(event.target.value)}
                      placeholder="My Vault"
                      autoFocus
                    />
                  </Field>
                </SetupPanel>
              )}

              {step === 3 && (
                <SetupPanel
                  icon={<ShieldCheck className="h-5 w-5" />}
                  title={`Welcome${displayName.trim() ? `, ${displayName.trim()}` : ""}`}
                  sub="Vault keeps the setup simple: choose a local folder, connect memory search, then start adding context."
                >
                  <div className="grid gap-3 sm:grid-cols-3">
                    <MiniFact title="Private" body="Stored on this device." />
                    <MiniFact title="Searchable" body="Powered by a local embedding model." />
                    <MiniFact title="Ready" body="Chat can use your context after indexing." />
                  </div>
                </SetupPanel>
              )}

              {step === 4 && (
                <SetupPanel
                  icon={<FolderOpen className="h-5 w-5" />}
                  title="Choose where Vault lives"
                  sub="This folder becomes your real storage location. Vault data is written inside a hidden .vault folder there."
                >
                  <Field label="Vault location">
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
                        disabled={!desktop?.selectVaultFolder}
                      >
                        <FolderOpen className="h-4 w-4" />
                        Browse
                      </Button>
                    </div>
                  </Field>
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
                          {diskPreflight.message} {formatBytes(diskPreflight.available_bytes)} available.
                        </div>
                      )}
                    </div>
                  )}
                </SetupPanel>
              )}

              {step === 5 && (
                <SetupPanel
                  icon={<PlugZap className="h-5 w-5" />}
                  title="Choose a local chat model"
                  sub="Vault can download a recommended model, or you can connect an existing OpenAI-compatible local runtime."
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ChoiceButton
                      selected={modelChoice === "recommended"}
                      title="Vault defaults"
                      description="Use the current default Qwen, Phi, or Gemma family choices."
                      onClick={() => setModelChoice("recommended")}
                    />
                    <ChoiceButton
                      selected={modelChoice === "custom"}
                      title="Import checkpoint"
                      description="Validate a local Transformers checkpoint and accept or reject it."
                      onClick={() => setModelChoice("custom")}
                    />
                  </div>

                  {modelChoice === "recommended" ? (
                    <div className="grid gap-3">
                      <div className="rounded-md border border-border bg-secondary/55 p-4 text-sm text-muted-foreground">
                        Expert setup only accepts app-managed Qwen, Phi, or Gemma checkpoints that pass validation. Runtime aliases and GGUF-only files do not satisfy this step by themselves.
                      </div>
                      {modelsLoading && <p className="text-sm text-muted-foreground">Loading model options...</p>}
                      {models.map((model) => (
                        <ModelRow
                          key={model.id}
                          model={model}
                          selected={selectedModelId === model.id}
                          busy={downloadingId === model.id}
                          activating={activatingId === model.id}
                          onSelect={() => setSelectedModelId(model.id)}
                          onDownload={() => void startDownload(model.id)}
                          onCancel={() => void cancelDownload(model.id)}
                          onActivate={() => void activateModel(model.id)}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="grid gap-4">
                      <Field label="Checkpoint folder">
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <Input
                            value={customModelPath}
                            onChange={(event) => setCustomModelPath(event.target.value)}
                            placeholder="D:\\Models\\Qwen3-4B"
                          />
                          <Button type="button" variant="outline" onClick={() => void chooseModelFolder()} disabled={!desktop?.selectModelFolder}>
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
                        <Button variant="outline" onClick={() => void validateCustomModel()} disabled={!customModelPath.trim()}>
                          Test model
                        </Button>
                        <Button onClick={() => void importApprovedModel()} disabled={!customModelReport?.accepted}>
                          Import approved model
                        </Button>
                      </div>
                      {customModelReport && (
                        <div className="rounded-md border border-border bg-card p-4 text-sm">
                          <div className="font-medium">
                            {customModelReport.accepted ? "Accepted" : "Rejected"}
                          </div>
                          <div className="mt-2 text-muted-foreground">{customModelReport.detail}</div>
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
                    Continue is enabled only after one approved model is active.
                  </p>
                </SetupPanel>
              )}

              {step === 6 && (
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

                  <Field label={embeddingChoice === "recommended" ? "Downloaded model folder" : "Embedding cache folder"}>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input
                        value={embeddingCacheDir}
                        onChange={(event) => setEmbeddingCacheDir(event.target.value)}
                        placeholder={
                          embeddingChoice === "recommended"
                            ? "T:\\Models\\all-MiniLM-L6-v2"
                            : "T:\\LLM\\embeddings"
                        }
                      />
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void chooseEmbeddingFolder()}
                        disabled={!desktop?.selectEmbeddingFolder}
                      >
                        <FolderOpen className="h-4 w-4" />
                        Browse
                      </Button>
                      {embeddingChoice === "recommended" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void startEmbeddingModelDownload()}
                          disabled={embeddingDownload?.status === "queued" || embeddingDownload?.status === "downloading"}
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
                          {embeddingRuntime?.available ? "Memory search ready" : "Memory search needs setup"}
                        </div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {embeddingRuntime?.detail ??
                            "Run a local test before entering Vault. Setup cannot finish until this passes."}
                        </div>
                      </div>
                      {embeddingRuntime?.available && <Check className="h-5 w-5 text-[var(--status-ready)]" />}
                    </div>
                    {embeddingDownload && embeddingDownload.status !== "idle" && (
                      <div className="mt-3 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                        <div className="flex items-center justify-between gap-3">
                          <span className="truncate">{embeddingDownload.model_id}</span>
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
                    {(embeddingDownload?.status === "queued" || embeddingDownload?.status === "downloading") && (
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

              {step === 7 && (
                <SetupPanel
                  icon={<Check className="h-5 w-5" />}
                  title="Welcome to Vault"
                  sub="Your vault is ready. Add sources from the Mind workspace, or start with chat when you want to ask across everything."
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <SummaryRow label="Profile" value={displayName.trim() || "Local user"} />
                    <SummaryRow label="Vault" value={vault?.name ?? vaultName.trim()} />
                    <SummaryRow label="Storage" value={resolvedVaultPath || "Selected vault folder"} />
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
                  "mt-5 rounded-md border px-4 py-3 text-sm",
                  error
                    ? "border-destructive/30 bg-destructive/5 text-destructive"
                    : "border-[var(--status-ready)]/25 bg-[var(--status-ready)]/10 text-foreground",
                )}
              >
                {error ?? message}
              </div>
            )}

            <div className="flex items-center justify-between gap-3 border-t border-border pt-5">
              <Button variant="ghost" onClick={back} disabled={step === 0}>
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>

              <div className="flex items-center gap-3">
                <div className="hidden text-xs text-muted-foreground sm:block">
                  {step + 1} of {steps.length}
                </div>
                {step === 4 ? (
                  <Button onClick={() => void createVaultAfterFolderSelection()} disabled={!canContinue}>
                    Create vault
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                ) : step === 7 ? (
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
        </section>
      </div>
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
        <div className="text-sm font-semibold">Vault</div>
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
              index < step && "border-[var(--status-ready)] bg-[var(--status-ready)]/12 text-foreground",
              index === step && "border-primary bg-primary text-primary-foreground",
              index > step && "border-border bg-card/60 text-muted-foreground",
            )}
          >
            {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
          </span>
          <span className={cn(index === step ? "font-medium text-foreground" : "text-muted-foreground")}>
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

function MiniFact({ title, body }: { title: string; body: string }) {
  return (
    <div className="vault-card p-4">
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-2 text-sm leading-5 text-muted-foreground">{body}</div>
    </div>
  );
}

function ModelRow({
  model,
  selected,
  busy,
  activating,
  onSelect,
  onDownload,
  onCancel,
  onActivate,
}: {
  model: LocalModelRecord;
  selected: boolean;
  busy: boolean;
  activating: boolean;
  onSelect: () => void;
  onDownload: () => void;
  onCancel: () => void;
  onActivate: () => void;
}) {
  const downloading = model.download?.status === "resolving" || model.download?.status === "downloading";
  const progress =
    model.download?.bytes_downloaded && model.download.total_bytes
      ? Math.round((model.download.bytes_downloaded / model.download.total_bytes) * 100)
      : 0;

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
              {model.role} / {model.quantization} / {model.approximate_download_gb} GB / {model.recommended_ram_gb} GB RAM
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {model.compatibility?.accepted ? "Expert compatible" : model.compatibility?.status === "rejected" ? "Rejected for expert runtime" : "Not validated"}
            </div>
          </div>
          {(selected || model.active) && <Check className="h-4 w-4 text-primary" />}
        </div>
        <p className="mt-2 text-sm leading-5 text-muted-foreground">{model.notes}</p>
        {model.local_path && <p className="mt-2 truncate font-mono text-xs text-muted-foreground">{model.local_path}</p>}
        {model.compatibility && !model.compatibility.accepted && (
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
        {model.compatibility?.accepted && !model.active ? (
          <Button variant="outline" size="sm" onClick={onActivate} disabled={activating}>
            {activating ? "Activating" : "Use model"}
          </Button>
        ) : null}
        {downloading ? (
          <Button variant="outline" size="sm" onClick={onCancel}>
            <X className="h-4 w-4" />
            Cancel
          </Button>
        ) : (
          <Button variant={model.installed ? "outline" : "secondary"} size="sm" onClick={onDownload} disabled={model.installed || busy}>
            <Download className="h-4 w-4" />
            {model.active ? "Active" : model.installed ? "Installed" : busy ? "Starting" : "Download"}
          </Button>
        )}
      </div>
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
