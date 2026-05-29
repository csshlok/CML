import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Check, FileText, FolderOpen, Link2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import {
  createSourceFromPath,
  createSourceFromText,
  createSourceFromUrl,
  createVault,
  type VaultRecord,
} from "@/lib/backend";
import { useStore } from "@/lib/mockStore";

type Step = 0 | 1 | 2 | 3;

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Set up CML" }] }),
  component: Onboarding,
});

function Onboarding() {
  const navigate = useNavigate();
  const store = useStore();
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;

  const [step, setStep] = useState<Step>(0);
  const [userName, setUserName] = useState("");
  const [vaultName, setVaultName] = useState("Local memory");
  const [vaultPath, setVaultPath] = useState("");
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [link, setLink] = useState("");
  const [textTitle, setTextTitle] = useState("First note");
  const [pastedText, setPastedText] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [importMessage, setImportMessage] = useState("No content imported yet.");
  const [importedCount, setImportedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const canContinue = useMemo(() => {
    if (step === 0) return userName.trim().length > 0;
    if (step === 1) return vaultName.trim().length > 0;
    if (step === 2) return vaultPath.trim().length > 0;
    return true;
  }, [step, userName, vaultName, vaultPath]);

  async function chooseVaultFolder() {
    const selected = await desktop?.selectVaultFolder?.();
    if (selected) setVaultPath(selected);
  }

  async function ensureVault() {
    if (vault) return vault;
    const path = vaultPath.trim();
    const name = vaultName.trim();
    if (!path || !name) throw new Error("Choose a vault name and location first.");

    const created = await createVault({ name, path });
    setVault(created);
    store.setVault(created.path);
    return created;
  }

  async function continueFromVaultLocation() {
    setError(null);
    try {
      await ensureVault();
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the vault.");
    }
  }

  async function importFiles(paths: string[]) {
    const currentVault = await ensureVault();
    setIsImporting(true);
    setError(null);
    let imported = 0;
    let failed = 0;
    let firstFailure = "";

    for (const path of paths) {
      try {
        await createSourceFromPath({ vault_id: currentVault.id, path });
        imported += 1;
      } catch (err) {
        failed += 1;
        if (!firstFailure) firstFailure = err instanceof Error ? err.message : path;
      }
    }

    setImportedCount((count) => count + imported);
    setImportMessage(
      failed
        ? `Imported ${imported}. ${failed} failed. First issue: ${firstFailure}`
        : imported
          ? `Imported ${imported} item${imported === 1 ? "" : "s"}.`
          : "No supported files were found.",
    );
    setIsImporting(false);
  }

  async function addFiles() {
    const paths = await desktop?.selectSourceFiles?.();
    if (!paths?.length) return;
    await importFiles(paths);
  }

  async function addFolder() {
    const folders = await desktop?.selectSourceFolders?.();
    if (!folders?.length) return;
    const paths = desktop?.listSupportedFiles ? await desktop.listSupportedFiles(folders) : folders;
    await importFiles(paths);
  }

  async function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const droppedPaths = desktop?.getDroppedFilePaths?.(event.dataTransfer.files) ?? [];
    if (!droppedPaths.length) {
      setImportMessage("Drop import is available in the desktop app.");
      return;
    }
    const paths = desktop?.listSupportedFiles ? await desktop.listSupportedFiles(droppedPaths) : droppedPaths;
    await importFiles(paths);
  }

  async function addLink() {
    if (!link.trim()) return;
    setIsImporting(true);
    setError(null);
    try {
      const currentVault = await ensureVault();
      await createSourceFromUrl({ vault_id: currentVault.id, url: link.trim() });
      setImportedCount((count) => count + 1);
      setImportMessage("Imported 1 link.");
      setLink("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import the link.");
    } finally {
      setIsImporting(false);
    }
  }

  async function addText() {
    if (!pastedText.trim()) return;
    setIsImporting(true);
    setError(null);
    try {
      const currentVault = await ensureVault();
      await createSourceFromText({
        vault_id: currentVault.id,
        title: textTitle.trim() || "First note",
        text: pastedText.trim(),
      });
      setImportedCount((count) => count + 1);
      setImportMessage("Imported 1 note.");
      setPastedText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import the note.");
    } finally {
      setIsImporting(false);
    }
  }

  function finish() {
    store.completeSetup();
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ctx.onboarded", "1");
      window.localStorage.setItem("ctx.userName", userName.trim());
      window.localStorage.setItem("ctx.vaultName", vaultName.trim());
    }
    navigate({ to: "/search" });
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <SetupSteps step={step} />

        {step === 0 && (
          <SetupSection title="What should CML call you?" sub="This is only used inside your local workspace.">
            <Field label="Your name">
              <Input value={userName} onChange={(event) => setUserName(event.target.value)} autoFocus />
            </Field>
            <Actions>
              <Button onClick={() => setStep(1)} disabled={!canContinue}>Continue</Button>
            </Actions>
          </SetupSection>
        )}

        {step === 1 && (
          <SetupSection title="Name your vault." sub="A vault is the local memory space where your sources, clusters, and chats live.">
            <Field label="Vault name">
              <Input value={vaultName} onChange={(event) => setVaultName(event.target.value)} autoFocus />
            </Field>
            <Actions>
              <Button variant="outline" onClick={() => setStep(0)}>Back</Button>
              <Button onClick={() => setStep(2)} disabled={!canContinue}>Continue</Button>
            </Actions>
          </SetupSection>
        )}

        {step === 2 && (
          <SetupSection title="Choose where the vault is stored." sub="CML keeps the vault on this device. You can use a normal folder or a synced folder.">
            <Field label="Vault location">
              <div className="flex gap-2">
                <Input
                  value={vaultPath}
                  onChange={(event) => setVaultPath(event.target.value)}
                  placeholder="C:\\Users\\You\\Documents\\CML Vault"
                />
                <Button variant="outline" onClick={chooseVaultFolder} disabled={!desktop?.selectVaultFolder}>
                  <FolderOpen className="mr-1.5 h-4 w-4" />
                  Browse
                </Button>
              </div>
            </Field>
            {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
            <Actions>
              <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
              <Button onClick={() => void continueFromVaultLocation()} disabled={!canContinue}>Create vault</Button>
            </Actions>
          </SetupSection>
        )}

        {step === 3 && (
          <SetupSection
            title="Add your first context."
            sub="Drop files, choose a folder, add a link, or paste text. CML can start searching immediately while local experts learn later."
          >
            <div
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => void handleDrop(event)}
              className="flex min-h-40 items-center justify-center rounded-md border border-dashed border-border bg-card p-6 text-center"
            >
              <div>
                <Upload className="mx-auto h-5 w-5 text-muted-foreground" />
                <div className="mt-3 text-sm font-medium">Drop files or folders here</div>
                <div className="mt-1 text-sm text-muted-foreground">TXT, Markdown, DOCX, and PDF are supported now.</div>
                <div className="mt-4 flex justify-center gap-2">
                  <Button variant="outline" onClick={() => void addFiles()} disabled={!desktop?.selectSourceFiles || isImporting}>Add files</Button>
                  <Button variant="outline" onClick={() => void addFolder()} disabled={!desktop?.selectSourceFolders || isImporting}>Add folder</Button>
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-md border border-border bg-card p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Link2 className="h-4 w-4" />
                  Add a link
                </div>
                <Input className="mt-3" value={link} onChange={(event) => setLink(event.target.value)} placeholder="https://..." />
                <Button className="mt-3" variant="outline" onClick={() => void addLink()} disabled={!link.trim() || isImporting}>Import link</Button>
              </div>

              <div className="rounded-md border border-border bg-card p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <FileText className="h-4 w-4" />
                  Paste text
                </div>
                <Input className="mt-3" value={textTitle} onChange={(event) => setTextTitle(event.target.value)} placeholder="Note title" />
                <Textarea className="mt-2" rows={4} value={pastedText} onChange={(event) => setPastedText(event.target.value)} placeholder="Paste a note, brief, chat transcript, or assignment..." />
                <Button className="mt-3" variant="outline" onClick={() => void addText()} disabled={!pastedText.trim() || isImporting}>Import text</Button>
              </div>
            </div>

            <div className="mt-5 rounded-md border border-border bg-card p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium">Learning starts with indexing</div>
                  <div className="mt-1 text-sm text-muted-foreground">{importMessage}</div>
                </div>
                <div className="text-sm text-muted-foreground">{importedCount} imported</div>
              </div>
              {isImporting && <Progress value={70} className="mt-3 h-1.5" />}
              {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
            </div>

            <Actions>
              <Button variant="outline" onClick={finish}>Skip for now</Button>
              <Button onClick={finish}>{importedCount > 0 ? "Open CML" : "Open empty vault"}</Button>
            </Actions>
          </SetupSection>
        )}
      </div>
    </div>
  );
}

function SetupSteps({ step }: { step: Step }) {
  const labels = ["Name", "Vault", "Location", "Content"];
  return (
    <div className="mb-10 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      {labels.map((label, index) => (
        <div key={label} className="flex items-center gap-2">
          <span
            className={
              "flex h-6 w-6 items-center justify-center rounded-full border text-xs " +
              (index <= step ? "border-foreground text-foreground" : "border-border")
            }
          >
            {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
          </span>
          <span className={index === step ? "text-foreground" : ""}>{label}</span>
          {index < labels.length - 1 && <span className="mx-1 h-px w-6 bg-border" />}
        </div>
      ))}
    </div>
  );
}

function SetupSection({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{sub}</p>
      <div className="mt-8">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block rounded-md border border-border bg-card p-4">
      <span className="text-sm font-medium">{label}</span>
      <div className="mt-2">{children}</div>
    </label>
  );
}

function Actions({ children }: { children: React.ReactNode }) {
  return <div className="mt-6 flex justify-end gap-2">{children}</div>;
}
