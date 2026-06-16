import { useEffect, useMemo, useState } from "react";
import { ClipboardPaste, MessageSquare, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { describeBridgeCaptureResult } from "@/lib/bridge-presentation.js";
import {
  captureBridgeArtifact,
  captureBridgeExternalTurn,
  listClusters,
  listVaults,
  type ClusterRecord,
  type VaultRecord,
} from "@/lib/backend";
import { useQuickCaptureDialog } from "@/lib/quick-capture-store";
import {
  applyClipboardTextToDraft,
  buildQuickCaptureSubmission,
  canSubmitQuickCapture,
  createQuickCaptureDraft,
} from "@/lib/quick-capture.js";

type Draft = ReturnType<typeof createQuickCaptureDraft>;

export function QuickCaptureDialog() {
  const { open, mode, seedFromClipboard, closeDialog } = useQuickCaptureDialog();
  const [vaults, setVaults] = useState<VaultRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [draft, setDraft] = useState<Draft>(() => createQuickCaptureDraft(mode));
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    async function loadScope() {
      try {
        const nextVaults = await listVaults();
        const defaultVaultId = nextVaults[0]?.id ?? "";
        const nextClusters = defaultVaultId ? await listClusters(defaultVaultId) : [];
        if (cancelled) return;
        setVaults(nextVaults);
        setClusters(nextClusters);
        setDraft((current) => ({
          ...current,
          mode,
          vaultId: current.vaultId || defaultVaultId,
          clusterId: current.clusterId,
          clientName: current.clientName || "desktop-quick-capture",
        }));
      } catch {
        if (cancelled) return;
        setVaults([]);
        setClusters([]);
        setNotice("Open a vault before using quick capture.");
      }
    }
    void loadScope();
    return () => {
      cancelled = true;
    };
  }, [open, mode]);

  useEffect(() => {
    if (!open) return;
    setDraft((current) => ({ ...createQuickCaptureDraft(mode), vaultId: current.vaultId }));
    setNotice(null);
  }, [open, mode]);

  useEffect(() => {
    if (!open || !seedFromClipboard) return;
    void pasteClipboardIntoDraft();
  }, [open, seedFromClipboard]);

  const availableClusters = useMemo(
    () => clusters.filter((cluster) => !draft.vaultId || cluster.vault_id === draft.vaultId),
    [clusters, draft.vaultId],
  );

  async function refreshClusters(vaultId: string) {
    if (!vaultId) {
      setClusters([]);
      return;
    }
    try {
      setClusters(await listClusters(vaultId));
    } catch {
      setClusters([]);
    }
  }

  async function pasteClipboardIntoDraft() {
    try {
      const clipboardText = await readClipboardText();
      if (!clipboardText.trim()) {
        setNotice("Clipboard is empty.");
        return;
      }
      setDraft((current) => applyClipboardTextToDraft(current, clipboardText));
      setNotice("Clipboard text loaded into quick capture.");
    } catch {
      setNotice("Clipboard text could not be read.");
    }
  }

  async function submit() {
    setSaving(true);
    try {
      const submission = buildQuickCaptureSubmission(draft);
      const result =
        submission.kind === "turn"
          ? await captureBridgeExternalTurn(submission.payload)
          : await captureBridgeArtifact(submission.payload);
      setNotice(describeBridgeCaptureResult(result));
      setDraft((current) => ({
        ...createQuickCaptureDraft(current.mode),
        vaultId: current.vaultId,
      }));
      window.dispatchEvent(new Event("vault:bridge-captures-changed"));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Quick capture failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && closeDialog()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Quick Capture</DialogTitle>
          <DialogDescription>
            Save an outside artifact or prompt-response pair into Vault without going through the Bridge admin screen.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={draft.mode === "artifact" ? "default" : "outline"}
              onClick={() => setDraft((current) => ({ ...createQuickCaptureDraft("artifact"), vaultId: current.vaultId }))}
            >
              <Save className="h-4 w-4" />
              Save artifact
            </Button>
            <Button
              type="button"
              variant={draft.mode === "turn" ? "default" : "outline"}
              onClick={() => setDraft((current) => ({ ...createQuickCaptureDraft("turn"), vaultId: current.vaultId }))}
            >
              <MessageSquare className="h-4 w-4" />
              Save prompt + response
            </Button>
            <Button type="button" variant="outline" onClick={() => void pasteClipboardIntoDraft()}>
              <ClipboardPaste className="h-4 w-4" />
              Paste clipboard
            </Button>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Library</span>
              <select
                value={draft.vaultId}
                onChange={(event) => {
                  const nextVaultId = event.target.value;
                  setDraft((current) => ({ ...current, vaultId: nextVaultId, clusterId: "" }));
                  void refreshClusters(nextVaultId);
                }}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">Select a vault</option>
                {vaults.map((vault) => (
                  <option key={vault.id} value={vault.id}>
                    {vault.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Cluster</span>
              <select
                value={draft.clusterId}
                onChange={(event) => setDraft((current) => ({ ...current, clusterId: event.target.value }))}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">Optional cluster</option>
                {availableClusters.map((cluster) => (
                  <option key={cluster.id} value={cluster.id}>
                    {cluster.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Saved as</span>
            <Input
              value={draft.clientName}
              onChange={(event) => setDraft((current) => ({ ...current, clientName: event.target.value }))}
            />
          </label>

          {draft.mode === "artifact" ? (
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Title</span>
              <Input
                value={draft.title}
                onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                placeholder="Clipboard capture"
              />
            </label>
          ) : (
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Prompt</span>
              <Textarea
                value={draft.prompt}
                onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))}
                placeholder="What did you ask the model?"
                className="min-h-28 resize-none"
              />
            </label>
          )}

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">
              {draft.mode === "artifact" ? "Content" : "Model response"}
            </span>
            <Textarea
              value={draft.response}
              onChange={(event) => setDraft((current) => ({ ...current, response: event.target.value }))}
              placeholder={draft.mode === "artifact" ? "Paste the text you want to save." : "Paste the model response."}
              className="min-h-56 resize-none"
            />
          </label>
        </div>
        <DialogFooter className="gap-2">
          <div className="mr-auto text-xs text-muted-foreground">
            {notice ?? "Quick capture uses the same trust-aware Bridge writeback path as external MCP saves."}
          </div>
          <Button variant="outline" onClick={() => closeDialog()}>
            Close
          </Button>
          <Button onClick={() => void submit()} disabled={saving || !canSubmitQuickCapture(draft)}>
            Save to Vault
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

async function readClipboardText() {
  if (window.cmlDesktop?.readClipboardText) {
    return window.cmlDesktop.readClipboardText();
  }
  if (navigator.clipboard?.readText) {
    return navigator.clipboard.readText();
  }
  return "";
}
