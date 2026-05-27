import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/mockStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  createVault,
  listVaults,
  updateVault,
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
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="font-serif text-3xl">Settings</h1>
      <section className="mt-8 rounded-md border border-border bg-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Vault location
        </div>
        <div className="mt-2 flex gap-2">
          <Input
            value={pathDraft}
            onChange={(e) => setPathDraft(e.target.value)}
            onBlur={() => void saveVaultPath()}
            placeholder="Choose a local folder for your memory"
          />
          <Button variant="outline" onClick={() => void saveVaultPath()} disabled={status === "saving"}>
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
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Shortcuts</div>
        <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Command palette</dt><dd>Ctrl/Cmd K</dd>
          <dt className="text-muted-foreground">New chat</dt><dd>Ctrl/Cmd N</dd>
          <dt className="text-muted-foreground">New cluster</dt><dd>Ctrl/Cmd Shift N</dd>
          <dt className="text-muted-foreground">Add link</dt><dd>Ctrl/Cmd L</dd>
          <dt className="text-muted-foreground">Open vault</dt><dd>Ctrl/Cmd O</dd>
          <dt className="text-muted-foreground">Send message</dt><dd>Ctrl/Cmd Enter</dd>
        </dl>
      </section>

      <section className="mt-6 rounded-md border border-border bg-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Advanced</div>
        <p className="mt-2 text-sm text-muted-foreground">
          Power-user details like training logs and expert versions appear here.
        </p>
      </section>
    </div>
  );
}
