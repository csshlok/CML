import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { useStore, ClusterTint } from "@/lib/mockStore";
import { FolderOpen, Upload, Link2, FileText, Check } from "lucide-react";

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Welcome — Context Workspace" }] }),
  component: Onboarding,
});

function Onboarding() {
  const [step, setStep] = useState(0);
  const [vault, setVault] = useState("~/Documents/Context");
  const [pasted, setPasted] = useState("");
  const [link, setLink] = useState("");
  const navigate = useNavigate();
  const store = useStore();

  const next = () => setStep((s) => s + 1);

  const finish = () => {
    store.setVault(vault);
    store.completeSetup();
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ctx.onboarded", "1");
    }
    navigate({ to: "/chat" });
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-xl px-6 py-16">
        <div className="mb-10 flex items-center gap-2 text-xs text-muted-foreground">
          {["Vault", "Add content", "Indexing", "Clusters"].map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <span
                className={
                  "flex h-5 w-5 items-center justify-center rounded-full border " +
                  (i <= step ? "border-primary text-primary" : "border-border")
                }
              >
                {i < step ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              <span className={i === step ? "text-foreground" : ""}>{label}</span>
              {i < 3 && <span className="mx-1 h-px w-6 bg-border" />}
            </div>
          ))}
        </div>

        {step === 0 && (
          <Section
            title="Choose a place for your local memory."
            sub="Your vault stays on this device. You can move it later."
          >
            <div className="rounded-md border border-border bg-card p-4">
              <label className="text-xs uppercase tracking-wider text-muted-foreground">
                Vault location
              </label>
              <div className="mt-2 flex gap-2">
                <Input value={vault} onChange={(e) => setVault(e.target.value)} />
                <Button variant="outline" type="button">
                  <FolderOpen className="mr-1.5 h-4 w-4" /> Browse
                </Button>
              </div>
            </div>
            <div className="mt-6 flex justify-end">
              <Button onClick={next}>Continue</Button>
            </div>
          </Section>
        )}

        {step === 1 && (
          <Section
            title="Drop files, links, screenshots, or notes to begin."
            sub="Anything you add here becomes part of your context."
          >
            <div className="grid gap-3">
              <div className="flex items-center justify-center rounded-md border border-dashed border-border bg-card p-10 text-sm text-muted-foreground">
                <Upload className="mr-2 h-4 w-4" /> Drop files or a folder here
              </div>
              <div className="rounded-md border border-border bg-card p-3">
                <label className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
                  <Link2 className="h-3.5 w-3.5" /> Add a link
                </label>
                <Input
                  className="mt-2"
                  placeholder="https://…"
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                />
              </div>
              <div className="rounded-md border border-border bg-card p-3">
                <label className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
                  <FileText className="h-3.5 w-3.5" /> Paste text
                </label>
                <Textarea
                  className="mt-2"
                  rows={4}
                  placeholder="A note, a quote, anything…"
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                />
              </div>
            </div>
            <div className="mt-6 flex justify-between">
              <Button variant="ghost" onClick={next}>
                Skip — use sample vault
              </Button>
              <Button
                onClick={() => {
                  if (link) store.addSource({ title: link, type: "link" });
                  if (pasted)
                    store.addSource({ title: pasted.slice(0, 40), type: "note", preview: pasted });
                  store.startIndexing();
                  next();
                }}
              >
                Continue
              </Button>
            </div>
          </Section>
        )}

        {step === 2 && <IndexingStep onDone={next} />}

        {step === 3 && (
          <Section
            title="We suggested a few clusters."
            sub="Rename, merge, or accept — you can always change these later."
          >
            <div className="space-y-2">
              {store.clusters.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-3 rounded-md border border-border bg-card p-3"
                >
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: `var(--cluster-${c.tint})` }}
                  />
                  <Input
                    defaultValue={c.name}
                    onBlur={(e) => store.renameCluster(c.id, e.target.value)}
                    className="h-8 max-w-xs"
                  />
                  <span className="text-xs text-muted-foreground">{c.description}</span>
                </div>
              ))}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => {
                const tints: ClusterTint[] = ["sand", "lavender", "terracotta"];
                const used = new Set(store.clusters.map((c) => c.tint));
                const tint = tints.find((t) => !used.has(t)) ?? "sand";
                store.addCluster({ name: "New cluster", tint, description: "" });
              }}>
                Add cluster
              </Button>
              <Button onClick={finish}>Open chat</Button>
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h1 className="font-serif text-3xl leading-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{sub}</p>
      <div className="mt-8">{children}</div>
    </div>
  );
}

function IndexingStep({ onDone }: { onDone: () => void }) {
  const { isIndexing, indexingProgress, sources } = useStore();
  return (
    <Section
      title="Reading your content…"
      sub="This happens locally. You can keep working — chat is available once anything is indexed."
    >
      <Progress value={indexingProgress * 100} className="h-1.5" />
      <div className="mt-6 max-h-64 space-y-1 overflow-y-auto rounded-md border border-border bg-card p-2 text-sm">
        {sources.slice(0, 8).map((s) => (
          <div key={s.id} className="flex items-center justify-between px-2 py-1">
            <span className="truncate">{s.title}</span>
            <span className="text-xs text-muted-foreground">
              {s.state === "indexed" ? "Indexed" : s.state === "extracting" ? "Extracting" : "Waiting"}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-6 flex justify-end">
        <Button onClick={onDone} disabled={isIndexing && indexingProgress < 1}>
          {isIndexing && indexingProgress < 1 ? "Indexing…" : "Continue"}
        </Button>
      </div>
    </Section>
  );
}