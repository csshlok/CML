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
  cancelModelDownload,
  configureEmbeddingRuntime,
  createVault,
  getEmbeddingRuntimeStatus,
  listLocalModels,
  startModelDownload,
  type EmbeddingRuntimeStatus,
  type LocalModelRecord,
  type VaultRecord,
} from "@/lib/backend";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/mockStore";

type Step = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;
type SignupMethod = "email" | "google";
type ModelChoice = "recommended" | "existing";
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

const welcomeWords = ["local", "private", "searchable", "ready"];

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
  const [existingRuntime, setExistingRuntime] = useState("http://127.0.0.1:8084/v1");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [embeddingChoice, setEmbeddingChoice] = useState<EmbeddingChoice>("recommended");
  const [embeddingCacheDir, setEmbeddingCacheDir] = useState("");
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
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
    if (step === 6) return Boolean(embeddingRuntime?.available);
    return true;
  }, [displayName, email, embeddingRuntime?.available, signupMethod, step, vaultName, vaultPath]);

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

  async function refreshEmbeddingStatus() {
    try {
      const status = await getEmbeddingRuntimeStatus();
      setEmbeddingRuntime(status);
      if (status.available) setMessage("Memory search is ready.");
    } catch (err) {
      setEmbeddingRuntime(null);
      setError(err instanceof Error ? err.message : "Could not check memory search.");
    }
  }

  async function chooseVaultFolder() {
    const selected = await desktop?.selectVaultFolder?.();
    if (selected) setVaultPath(selected);
  }

  async function createVaultAfterFolderSelection() {
    setError(null);
    setMessage("Opening your vault folder...");
    try {
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
      const status = await configureEmbeddingRuntime({
        provider: "sentence-transformers",
        cache_dir: embeddingChoice === "existing" ? embeddingCacheDir.trim() || null : null,
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
      window.localStorage.setItem("ctx.localRuntimeUrl", existingRuntime.trim());
      window.localStorage.setItem("ctx.chatModelChoice", modelChoice);
      window.localStorage.setItem("ctx.chatModelId", selectedModelId);
    }
    navigate({ to: "/search" });
  }

  return (
    <main className="vault-onboarding-shell min-h-screen overflow-hidden bg-background text-foreground">
      <AnimatedBackground />

      <div className="relative z-10 grid min-h-screen grid-cols-1 lg:grid-cols-[360px_1fr]">
        <aside className="hidden border-r border-border/70 bg-background/45 px-10 py-10 backdrop-blur-sm lg:flex lg:flex-col">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">Vault</div>
              <div className="text-xs text-muted-foreground">Local memory setup</div>
            </div>
          </div>

          <div className="mt-16">
            <div className="text-4xl font-semibold leading-tight">
              Make your work
              <span className="vault-word-rotator ml-2 inline-grid align-baseline">
                {welcomeWords.map((word, index) => (
                  <span key={word} style={{ animationDelay: `${index * 1.8}s` }}>
                    {word}
                  </span>
                ))}
              </span>
            </div>
            <p className="mt-5 max-w-[280px] text-sm leading-6 text-muted-foreground">
              A private vault, a real memory-search model, and a calm place to start asking.
            </p>
          </div>

          <StepRail step={step} />
        </aside>

        <section className="flex min-h-screen items-center justify-center px-5 py-8 sm:px-8">
          <div className="vault-onboarding-card w-full max-w-[760px]">
            <MobileHeader step={step} />

            <div key={step} className="vault-step-enter">
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
                        onChange={(event) => setVaultPath(event.target.value)}
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
                      title="Recommended model"
                      description="Download one of Vault's local GGUF choices."
                      onClick={() => setModelChoice("recommended")}
                    />
                    <ChoiceButton
                      selected={modelChoice === "existing"}
                      title="Existing runtime"
                      description="Use llama-server, Ollama, or another local endpoint."
                      onClick={() => setModelChoice("existing")}
                    />
                  </div>

                  {modelChoice === "recommended" ? (
                    <div className="grid gap-3">
                      {modelsLoading && <p className="text-sm text-muted-foreground">Loading model options...</p>}
                      {models.map((model) => (
                        <ModelRow
                          key={model.id}
                          model={model}
                          selected={selectedModelId === model.id}
                          busy={downloadingId === model.id}
                          onSelect={() => setSelectedModelId(model.id)}
                          onDownload={() => void startDownload(model.id)}
                          onCancel={() => void cancelDownload(model.id)}
                        />
                      ))}
                    </div>
                  ) : (
                    <Field label="OpenAI-compatible endpoint">
                      <Input
                        value={existingRuntime}
                        onChange={(event) => setExistingRuntime(event.target.value)}
                        placeholder="http://127.0.0.1:8084/v1"
                      />
                    </Field>
                  )}

                  {selectedModel && modelChoice === "recommended" && (
                    <p className="text-xs text-muted-foreground">
                      Selected: {selectedModel.name}. You can finish setup while downloads continue.
                    </p>
                  )}
                </SetupPanel>
              )}

              {step === 6 && (
                <SetupPanel
                  icon={<Sparkles className="h-5 w-5" />}
                  title="Choose the memory-search model"
                  sub="This step is required. Search, clusters, Bridge, and vault-grounded chat need a real local embedding model."
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ChoiceButton
                      selected={embeddingChoice === "recommended"}
                      title="Vault recommended"
                      description="Use sentence-transformers/all-MiniLM-L6-v2."
                      onClick={() => setEmbeddingChoice("recommended")}
                    />
                    <ChoiceButton
                      selected={embeddingChoice === "existing"}
                      title="Existing cache"
                      description="Point Vault at a local model cache folder."
                      onClick={() => setEmbeddingChoice("existing")}
                    />
                  </div>

                  {embeddingChoice === "existing" && (
                    <Field label="Embedding cache folder">
                      <Input
                        value={embeddingCacheDir}
                        onChange={(event) => setEmbeddingCacheDir(event.target.value)}
                        placeholder="T:\\LLM\\embeddings"
                      />
                    </Field>
                  )}

                  <div className="rounded-md border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-medium">
                          {embeddingRuntime?.available ? "Memory search ready" : "Memory search needs setup"}
                        </div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {embeddingRuntime?.detail ?? "Run a local test before entering Vault."}
                        </div>
                      </div>
                      {embeddingRuntime?.available && <Check className="h-5 w-5 text-[var(--status-ready)]" />}
                    </div>
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

            <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-5">
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
      <div className="flex h-10 w-10 items-center justify-center rounded-md border border-border bg-card text-primary">
        {icon}
      </div>
      <h1 className="mt-6 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">{title}</h1>
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
        "rounded-md border bg-card p-4 text-left transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        selected ? "border-primary bg-primary/7" : "border-border",
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
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-2 text-sm leading-5 text-muted-foreground">{body}</div>
    </div>
  );
}

function ModelRow({
  model,
  selected,
  busy,
  onSelect,
  onDownload,
  onCancel,
}: {
  model: LocalModelRecord;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onDownload: () => void;
  onCancel: () => void;
}) {
  const downloading = model.download?.status === "resolving" || model.download?.status === "downloading";
  const progress =
    model.download?.bytes_downloaded && model.download.total_bytes
      ? Math.round((model.download.bytes_downloaded / model.download.total_bytes) * 100)
      : 0;

  return (
    <div
      className={cn(
        "rounded-md border bg-card p-4 transition-colors",
        selected ? "border-primary bg-primary/7" : "border-border",
      )}
    >
      <button type="button" className="block w-full text-left" onClick={onSelect}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium">{model.name}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {model.role} / {model.quantization} / {model.approximate_download_gb} GB / {model.recommended_ram_gb} GB RAM
            </div>
          </div>
          {selected && <Check className="h-4 w-4 text-primary" />}
        </div>
        <p className="mt-2 text-sm leading-5 text-muted-foreground">{model.notes}</p>
        {model.local_path && <p className="mt-2 truncate font-mono text-xs text-muted-foreground">{model.local_path}</p>}
      </button>

      {downloading && (
        <div className="mt-3">
          <Progress value={progress || 12} className="h-1.5" />
          <div className="mt-1 text-xs text-muted-foreground">{model.download?.status}</div>
        </div>
      )}

      <div className="mt-3 flex justify-end gap-2">
        {downloading ? (
          <Button variant="outline" size="sm" onClick={onCancel}>
            <X className="h-4 w-4" />
            Cancel
          </Button>
        ) : (
          <Button variant={model.installed ? "outline" : "secondary"} size="sm" onClick={onDownload} disabled={model.installed || busy}>
            <Download className="h-4 w-4" />
            {model.installed ? "Installed" : busy ? "Starting" : "Download"}
          </Button>
        )}
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-sm font-medium">{value}</div>
    </div>
  );
}
