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
import { useStore } from "@/lib/mockStore";
import {
  cancelModelDownload,
  configureEmbeddingRuntime,
  createDiagnosticBundle,
  createVault,
  getEmbeddingRuntimeStatus,
  getHardwareStatus,
  getJobStatus,
  getModelRuntimeStatus,
  getOCRRuntimeStatus,
  listLocalModels,
  listVaults,
  startModelDownload,
  updateVault,
  type EmbeddingRuntimeStatus,
  type HardwareStatusRead,
  type JobQueueStatus,
  type LocalModelRecord,
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
  const { vaultPath, setVault } = useStore();
  const [activeSection, setActiveSection] = useState("models");
  const [backendVault, setBackendVault] = useState<VaultRecord | null>(null);
  const [pathDraft, setPathDraft] = useState(vaultPath ?? "");
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingCacheDraft, setEmbeddingCacheDraft] = useState("");
  const [ocrRuntime, setOcrRuntime] = useState<OCRRuntimeStatusRead | null>(null);
  const [hardware, setHardware] = useState<HardwareStatusRead | null>(null);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [vaultRows, modelRows, runtimeStatus, embeddingStatus, ocrStatus, hardwareStatus, jobStatus] =
          await Promise.all([
            listVaults(),
            listLocalModels(),
            getModelRuntimeStatus(),
            getEmbeddingRuntimeStatus(),
            getOCRRuntimeStatus(),
            getHardwareStatus(),
            getJobStatus(),
          ]);
        if (cancelled) return;
        const firstVault = vaultRows[0] ?? null;
        setBackendVault(firstVault);
        if (firstVault) {
          setPathDraft(firstVault.path);
          setVault(firstVault.path);
        }
        setModels(modelRows);
        setRuntime(runtimeStatus);
        setEmbeddingRuntime(embeddingStatus);
        setEmbeddingCacheDraft(embeddingStatus.cache_dir ?? "");
        setOcrRuntime(ocrStatus);
        setHardware(hardwareStatus);
        setJobs(jobStatus);
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
  }, [setVault]);

  async function saveVaultPath() {
    const path = pathDraft.trim();
    if (!path) return;
    setSaving(true);
    try {
      const nextVault = backendVault
        ? await updateVault(backendVault.id, { path })
        : await createVault({ name: "Local memory", path });
      setBackendVault(nextVault);
      setVault(nextVault.path);
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

  const suggestedModel = models[0];

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
          <h1 className="font-serif text-4xl font-medium tracking-tight">Settings</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Local models, storage, privacy, and maintenance.
          </p>
        </header>

        <div className="mt-7 space-y-4">
          {activeSection === "profile" ? (
            <ProfileSettings />
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
              <Input value={runtime?.endpoint ?? "http://localhost:11434"} readOnly />
              <Button variant="outline" className="gap-2">Test <Play className="h-4 w-4" /></Button>
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<MessageSquare className="h-4 w-4" />}
            title="Chat model"
            description="Model used to generate assistant responses."
            status={runtime?.available ? "Ready" : "Missing"}
            statusTone={runtime?.available ? "ready" : "issue"}
          >
            <label className="mt-5 block text-sm font-medium">Model</label>
            <div className="mt-2 flex gap-2">
              <Input value={suggestedModel?.name ?? "mistral-nemo-instruct-2407:q4_k_m"} readOnly />
              <Button
                variant="outline"
                className="gap-2"
                disabled={!suggestedModel || downloadingId === suggestedModel.id}
                onClick={() => suggestedModel && void downloadModel(suggestedModel.id)}
              >
                {downloadingId === suggestedModel?.id ? "Starting..." : "Download"}
              </Button>
              {suggestedModel?.download_status === "downloading" && (
                <Button variant="outline" onClick={() => void cancelDownload(suggestedModel.id)}>
                  Cancel
                </Button>
              )}
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<Layers className="h-4 w-4" />}
            title="Embedding model"
            description="Model used to create vector embeddings for semantic search."
            status={embeddingRuntime?.available ? "Ready" : "Required"}
            statusTone={embeddingRuntime?.available ? "ready" : "issue"}
          >
            <label className="mt-5 block text-sm font-medium">Model path (required)</label>
            <div className="mt-2 flex gap-2">
              <Input
                value={embeddingCacheDraft}
                onChange={(event) => setEmbeddingCacheDraft(event.target.value)}
                placeholder="C:\\AI_Models\\all-MiniLM-L6-v2"
              />
              <Button variant="outline" onClick={() => void saveEmbeddingRuntime()} disabled={saving}>
                Browse...
              </Button>
            </div>
          </SettingsCard>

          <SettingsCard
            icon={<Settings2 className="h-4 w-4" />}
            title="OCR"
            description="Local OCR for scanned documents and images."
            status={ocrRuntime?.available ? "Ready" : "Missing"}
            statusTone={ocrRuntime?.available ? "ready" : "issue"}
          >
            <RuntimeRow label="OCRmyPDF" value={ocrRuntime?.ocrmypdf_available ? "Installed" : "Missing"} meta={ocrRuntime?.ocrmypdf_version ?? ""} />
            <RuntimeRow label="Tesseract" value={ocrRuntime?.tesseract_available ? "Installed" : "Missing"} meta={ocrRuntime?.tesseract_version ?? ""} />
          </SettingsCard>

          <SettingsCard
            icon={<Database className="h-4 w-4" />}
            title="Disk usage"
            description="Manage local data and model storage."
          >
            <div className="mt-5 h-1.5 rounded-full bg-muted">
              <span className="block h-full w-[28%] rounded-full bg-primary" />
            </div>
            <div className="mt-3 grid grid-cols-3 text-sm text-muted-foreground">
              <span>Used 124.6 GB</span>
              <span>Free 375.4 GB</span>
              <span>Total 500 GB</span>
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
          <ReadinessRow label="CPU" value={hardware?.avx2 ? "AVX2" : "Unknown"} meta={hardware?.cpu_name ?? "Capability check"} />
          <ReadinessRow label="RAM" value={hardware?.ram_gb ? `${hardware.ram_gb} GB` : "Unknown"} meta="Available locally" />
          <ReadinessRow label="GPU" value={hardware?.gpu_name ?? "Not detected"} meta={hardware?.cuda_available ? "CUDA available" : "Optional"} />
          <ReadinessRow label="Backend" value="Online" meta={runtime?.endpoint ?? "http://localhost:7343"} />
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

function ProfileSettings() {
  return (
    <>
      <section className="vault-card p-5">
        <div className="flex flex-wrap items-center gap-5">
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-foreground text-background">
            <UserRound className="h-7 w-7" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold">Arjun Mehta</h2>
            <p className="mt-1 text-sm text-muted-foreground">arjun@vault.local</p>
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
          <Input defaultValue="Arjun Mehta" />
          <Button variant="outline">Save</Button>
        </div>
      </section>

      <section className="vault-card p-5">
        <h2 className="text-sm font-semibold">Sign-in methods</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Vault can remember your account identity without syncing private vault data.
        </p>
        <div className="mt-5 divide-y divide-border border-y border-border">
          <ProfileMethod label="Email" value="arjun@vault.local" status="Connected" />
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
