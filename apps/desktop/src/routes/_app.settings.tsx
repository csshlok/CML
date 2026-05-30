import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/mockStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  cancelModelDownload,
  configureEmbeddingRuntime,
  createDiagnosticBundle,
  createVault,
  getEmbeddingRuntimeStatus,
  getModelRuntimeStatus,
  listLocalModels,
  listVaults,
  startModelDownload,
  updateVault,
  type EmbeddingRuntimeStatus,
  type LocalModelRecord,
  type ModelRuntimeStatus,
  type VaultRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/settings")({
  head: () => ({ meta: [{ title: "Settings" }] }),
  component: SettingsView,
});

function SettingsView() {
  const { vaultPath, setVault } = useStore();
  const [backendVault, setBackendVault] = useState<VaultRecord | null>(null);
  const [pathDraft, setPathDraft] = useState(vaultPath ?? "");
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<LocalModelRecord[]>([]);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [embeddingRuntime, setEmbeddingRuntime] = useState<EmbeddingRuntimeStatus | null>(null);
  const [embeddingCacheDraft, setEmbeddingCacheDraft] = useState("");
  const [embeddingSaving, setEmbeddingSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [diagnosticStatus, setDiagnosticStatus] = useState<string | null>(null);

  useEffect(() => {
    async function loadVault() {
      setStatus("loading");
      try {
        const vaults = await listVaults();
        const firstVault = vaults[0] ?? null;
        setBackendVault(firstVault);
        if (firstVault) {
          setPathDraft(firstVault.path);
          setVault(firstVault.path);
        }
        setStatus("idle");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load vault settings.");
        setStatus("error");
      }
    }

    void loadVault();
  }, [setVault]);

  useEffect(() => {
    let cancelled = false;

    async function loadModels() {
      try {
        const [modelRows, runtimeStatus, embeddingStatus] = await Promise.all([
          listLocalModels(),
          getModelRuntimeStatus(),
          getEmbeddingRuntimeStatus(),
        ]);
        if (cancelled) return;
        setModels(modelRows);
        setRuntime(runtimeStatus);
        setEmbeddingRuntime(embeddingStatus);
        setModelError(null);
      } catch (err) {
        if (!cancelled) {
          setModelError(
            err instanceof Error ? err.message : "Could not load local model settings.",
          );
        }
      }
    }

    void loadModels();
    const id = window.setInterval(loadModels, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  async function saveVaultPath() {
    const path = pathDraft.trim();
    if (!path) return;
    setStatus("saving");
    setError(null);
    try {
      const nextVault = backendVault
        ? await updateVault(backendVault.id, { path })
        : await createVault({ name: "Local memory", path });
      setBackendVault(nextVault);
      setVault(nextVault.path);
      setStatus("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save vault settings.");
      setStatus("error");
    }
  }

  async function downloadModel(modelId: string) {
    setDownloadingId(modelId);
    setModelError(null);
    try {
      await startModelDownload(modelId);
      setModels(await listLocalModels());
    } catch (err) {
      setModelError(err instanceof Error ? err.message : "Could not start model download.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function cancelDownload(modelId: string) {
    setModelError(null);
    try {
      await cancelModelDownload(modelId);
      setModels(await listLocalModels());
    } catch (err) {
      setModelError(err instanceof Error ? err.message : "Could not cancel model download.");
    }
  }

  async function saveEmbeddingRuntime() {
    setEmbeddingSaving(true);
    setModelError(null);
    try {
      const nextStatus = await configureEmbeddingRuntime({
        provider: "sentence-transformers",
        cache_dir: embeddingCacheDraft.trim() || null,
      });
      setEmbeddingRuntime(nextStatus);
    } catch (err) {
      setModelError(err instanceof Error ? err.message : "Could not update embedding settings.");
    } finally {
      setEmbeddingSaving(false);
    }
  }

  async function exportDiagnostics() {
    setDiagnosticStatus("Creating diagnostic bundle...");
    try {
      const bundle = await createDiagnosticBundle();
      setDiagnosticStatus(`Diagnostic bundle saved to ${bundle.bundle_path}`);
    } catch (err) {
      setDiagnosticStatus(err instanceof Error ? err.message : "Could not create diagnostic bundle.");
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-10 pb-16">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <section className="mt-8 rounded-md border border-border bg-card p-4">
          <div className="text-sm font-medium">Vault location</div>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <Input
              value={pathDraft}
              onChange={(e) => setPathDraft(e.target.value)}
              placeholder="Choose a local folder for your memory"
            />
            <Button
              variant="outline"
              onClick={() => void saveVaultPath()}
              disabled={status === "saving"}
            >
              {backendVault ? "Save" : "Create"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {status === "loading"
              ? "Loading vault settings..."
              : status === "saving"
                ? "Saving vault..."
                : status === "saved"
                  ? "Vault saved locally."
                  : "Your vault stays on this device. Move it any time."}
          </p>
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </section>

        <section className="mt-6 rounded-md border border-border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Embeddings</div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Search, clustering, Bridge, and chat retrieval use this local embedding backend.
              </p>
            </div>
            <div className="rounded-md border border-border px-3 py-2 text-xs">
              <div className="font-medium">
                {embeddingRuntime?.available ? "Embeddings ready" : "Embeddings unavailable"}
              </div>
              <div className="mt-1 max-w-72 truncate text-muted-foreground">
                {embeddingRuntime?.detail ?? "Checking embedding backend..."}
              </div>
            </div>
          </div>
          <dl className="mt-4 grid gap-y-1 text-sm md:grid-cols-[140px_1fr]">
            <dt className="text-muted-foreground">Provider</dt>
            <dd>{embeddingRuntime?.provider ?? "checking"}</dd>
            <dt className="text-muted-foreground">Model</dt>
            <dd className="truncate">{embeddingRuntime?.model ?? "checking"}</dd>
            <dt className="text-muted-foreground">Dimensions</dt>
            <dd>{embeddingRuntime?.dimensions ?? "-"}</dd>
          </dl>
          <div className="mt-5 border-t border-border pt-4">
            <div className="rounded-md border border-border p-3 text-sm">
              <div className="font-medium">MiniLM semantic search</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Vault uses sentence-transformers/all-MiniLM-L6-v2 for retrieval. Hash embeddings are
                reserved for explicit development and test runs.
              </p>
            </div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <Input
                value={embeddingCacheDraft}
                onChange={(event) => setEmbeddingCacheDraft(event.target.value)}
                placeholder="Optional model cache folder, for example T:\\LLM\\embeddings"
              />
              <Button onClick={() => void saveEmbeddingRuntime()} disabled={embeddingSaving}>
                {embeddingSaving ? "Saving" : "Use"}
              </Button>
            </div>
            {embeddingRuntime?.provider === "sentence-transformers" &&
              !embeddingRuntime.available && (
                <p className="mt-2 text-xs text-destructive">
                  MiniLM is selected but not available in this Python runtime yet. Install the
                  optional embedding runtime or rebuild the package with embedding dependencies.
                </p>
              )}
          </div>
        </section>

        <section className="mt-6 rounded-md border border-border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Local models</div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                These models are downloaded to your configured local model folder and used through a
                local OpenAI-compatible runtime.
              </p>
            </div>
            <div className="rounded-md border border-border px-3 py-2 text-xs">
              <div className="font-medium">
                {runtime?.available ? "Runtime online" : "Runtime offline"}
              </div>
              <div className="mt-1 max-w-72 truncate text-muted-foreground">
                {runtime?.detail ?? "Checking local runtime..."}
              </div>
            </div>
          </div>

          <div className="mt-4 divide-y divide-border rounded-md border border-border">
            {models.map((model) => {
              const progress =
                model.download?.total_bytes && model.download.bytes_downloaded
                  ? Math.min(
                      100,
                      Math.round(
                        (model.download.bytes_downloaded / model.download.total_bytes) * 100,
                      ),
                    )
                  : null;
              const busy =
                model.download?.status === "resolving" || model.download?.status === "downloading";
              const cancelling = model.download?.status === "cancelling";

              return (
                <div
                  key={model.id}
                  className="grid gap-3 p-4 md:grid-cols-[1fr_auto] md:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{model.name}</div>
                      <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
                        {model.role}
                      </span>
                      <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
                        {model.quantization}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      {model.notes} {model.approximate_download_gb} GB download,{" "}
                      {model.recommended_ram_gb} GB RAM.
                    </div>
                    <div className="mt-1 break-all text-xs text-muted-foreground">
                      {model.hf_repo}
                    </div>
                    {model.local_path && (
                      <div className="mt-1 break-all text-xs text-muted-foreground">
                        {model.local_path}
                      </div>
                    )}
                    {busy && (
                      <div className="mt-3 h-1.5 overflow-hidden rounded bg-muted">
                        <div
                          className="h-full bg-foreground"
                          style={{ width: `${progress ?? 8}%` }}
                        />
                      </div>
                    )}
                    {model.download?.error && (
                      <div className="mt-2 text-xs text-destructive">{model.download.error}</div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 md:justify-end">
                    {(busy || cancelling) && (
                      <Button
                        variant="outline"
                        onClick={() => void cancelDownload(model.id)}
                        disabled={cancelling}
                      >
                        {cancelling ? "Cancelling" : "Cancel"}
                      </Button>
                    )}
                    <Button
                      variant={model.installed ? "outline" : "default"}
                      onClick={() => void downloadModel(model.id)}
                      disabled={model.installed || busy || cancelling || downloadingId === model.id}
                    >
                      {model.installed
                        ? "Installed"
                        : busy
                          ? progress
                            ? `${progress}%`
                            : "Starting"
                          : model.download?.status === "cancelled"
                            ? "Download"
                            : "Download"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
          {modelError && <p className="mt-3 text-xs text-destructive">{modelError}</p>}
        </section>

        <section className="mt-6 rounded-md border border-border bg-card p-4">
          <div className="text-sm font-medium">Shortcuts</div>
          <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Command palette</dt>
            <dd>Ctrl/Cmd K</dd>
            <dt className="text-muted-foreground">New chat</dt>
            <dd>Ctrl/Cmd N</dd>
            <dt className="text-muted-foreground">New cluster</dt>
            <dd>Ctrl/Cmd Shift N</dd>
            <dt className="text-muted-foreground">Add link</dt>
            <dd>Ctrl/Cmd L</dd>
            <dt className="text-muted-foreground">Open vault</dt>
            <dd>Ctrl/Cmd O</dd>
            <dt className="text-muted-foreground">Send message</dt>
            <dd>Ctrl/Cmd Enter</dd>
          </dl>
        </section>

        <section className="mt-6 rounded-md border border-border bg-card p-4">
          <div className="text-sm font-medium">Advanced</div>
          <p className="mt-2 text-sm text-muted-foreground">
            Power-user details like training logs and expert versions appear here.
          </p>
          <div className="mt-4 border-t border-border pt-4">
            <div className="text-sm font-medium">Diagnostics</div>
            <p className="mt-1 text-sm text-muted-foreground">
              Export a local support bundle with version details, database counts, integrity check
              results, and redacted logs. Source text is not included.
            </p>
            <Button className="mt-3" variant="outline" onClick={() => void exportDiagnostics()}>
              Export diagnostic bundle
            </Button>
            {diagnosticStatus && (
              <p className="mt-2 break-all text-xs text-muted-foreground">{diagnosticStatus}</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
