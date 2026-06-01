import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { type DragEvent, useEffect, useState } from "react";
import {
  listClusters,
  createChatSession,
  deleteChatSession,
  listChatSessions,
  listVaults,
  type ChatSessionRecord,
  type ClusterRecord,
  type VaultRecord,
} from "@/lib/backend";
import { ArrowRight, FileText, MessageSquare, MoreHorizontal, Paperclip, Plus, Send, SlidersHorizontal, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/_app/chat")({
  head: () => ({ meta: [{ title: "Chat" }] }),
  component: ChatIndex,
});

function ChatIndex() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const navigate = useNavigate();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendClusters, setBackendClusters] = useState<ClusterRecord[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [attachmentNotice, setAttachmentNotice] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [scopeClusterId, setScopeClusterId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setVault(activeVault);
      if (!activeVault) return;
      const [sessions, clusterRows] = await Promise.all([
        listChatSessions(activeVault.id),
        listClusters(activeVault.id),
      ]);
      setBackendChats(sessions);
      setBackendClusters(clusterRows);
      setBackendReady(true);
    } catch {
      setBackendReady(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadIfMounted() {
      try {
        const vaults = await listVaults();
        const activeVault = vaults[0] ?? null;
        if (cancelled) return;
        setVault(activeVault);
        if (!activeVault) return;
        const [sessions, clusterRows] = await Promise.all([
          listChatSessions(activeVault.id),
          listClusters(activeVault.id),
        ]);
        if (cancelled) return;
        setBackendChats(sessions);
        setBackendClusters(clusterRows);
        setBackendReady(true);
      } catch {
        if (!cancelled) setBackendReady(false);
      }
    }

    void loadIfMounted();

    return () => {
      cancelled = true;
    };
  }, []);

  async function newChat() {
    try {
      const activeVault = vault ?? (await listVaults())[0] ?? null;
      if (activeVault) {
        const session = await createChatSession({ vault_id: activeVault.id });
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      }
    } catch {}
    navigate({ to: "/settings" });
  }

  async function startPromptChat() {
    const text = prompt.trim() || (attachments.length > 0 ? "Read and store these attachments." : "");
    if ((!text && attachments.length === 0) || creating) return;
    setCreating(true);
    try {
      const activeVault = vault ?? (await listVaults())[0] ?? null;
      if (activeVault) {
        const session = await createChatSession({
          vault_id: activeVault.id,
          title: titleFromPrompt(text),
          scope_cluster_id: scopeClusterId,
        });
        window.sessionStorage.setItem(`cml.pendingPrompt.${session.id}`, text);
        if (attachments.length > 0) {
          window.sessionStorage.setItem(`cml.pendingAttachments.${session.id}`, JSON.stringify(attachments));
        }
        window.dispatchEvent(new Event("vault:chats-changed"));
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      }
    } catch {
      navigate({ to: "/settings" });
    } finally {
      setCreating(false);
    }
  }

  async function removeChat(id: string) {
    if (backendReady) {
      await deleteChatSession(id);
      window.dispatchEvent(new Event("vault:chats-changed"));
      await load();
    }
  }

  function addAttachmentPaths(paths: string[]) {
    const cleanPaths = paths.filter(Boolean);
    if (cleanPaths.length === 0) return;
    setAttachments((current) => Array.from(new Set([...current, ...cleanPaths])));
    setAttachmentNotice(
      `${cleanPaths.length} attachment${cleanPaths.length === 1 ? "" : "s"} ready to store with your first message.`,
    );
  }

  async function addAttachments() {
    if (!window.cmlDesktop?.selectSourceFiles) return;
    addAttachmentPaths(await window.cmlDesktop.selectSourceFiles());
  }

  function removeAttachment(path: string) {
    setAttachments((current) => current.filter((item) => item !== path));
  }

  async function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    if (!backendReady) return;
    const droppedPaths = window.cmlDesktop?.getDroppedFilePaths?.(event.dataTransfer.files) ?? [];
    const paths = window.cmlDesktop?.listSupportedFiles
      ? await window.cmlDesktop.listSupportedFiles(droppedPaths)
      : droppedPaths;
    addAttachmentPaths(paths);
  }

  const visibleChats = backendReady ? backendChats : [];

  if (pathname !== "/chat") {
    return <Outlet />;
  }

  return (
    <div
      className="vault-page-wash grid h-full grid-cols-[320px_minmax(0,1fr)_326px] overflow-hidden"
      onDragOver={(event) => {
        event.preventDefault();
        if (backendReady) setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(event) => void handleDrop(event)}
    >
      <aside className="overflow-y-auto border-r border-border bg-card/35 px-5 py-6">
        <Button variant="ghost" className="mb-5 w-full justify-start gap-2 text-base" onClick={newChat}>
          <Plus className="h-4 w-4" /> New chat
        </Button>
        <div className="space-y-1">
          {visibleChats.map((c) => (
            <div key={c.id} className="group flex items-center gap-1 rounded-md hover:bg-accent/60">
              <Link
                to="/chat/$chatId"
                params={{ chatId: c.id }}
                className="min-w-0 flex-1 truncate px-3 py-2 text-sm text-muted-foreground group-hover:text-foreground"
              >
                {c.title}
              </Link>
              {backendReady && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="mr-1 h-7 w-7 opacity-0 group-hover:opacity-100"
                  aria-label={`Delete ${c.title}`}
                  onClick={() => void removeChat(c.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border bg-card/35 px-10 py-7">
          <div className="flex items-center gap-3">
            <MessageSquare className="h-5 w-5 text-muted-foreground" />
            <div>
              <h1 className="text-base font-semibold">Ask Vault</h1>
              <p className="text-sm text-muted-foreground">
                Starts with all indexed context. Narrow to a cluster only when the question needs
                it.
              </p>
            </div>
          </div>
        </header>

        <main className="flex flex-1 items-center justify-center overflow-y-auto px-10">
          <section className="w-full max-w-[840px]">
            {dragActive && (
              <div className="mb-2 rounded-md border border-dashed border-primary/50 bg-primary/5 px-3 py-2 text-xs text-foreground">
                Drop files to attach them to the first message.
              </div>
            )}
            {attachmentNotice && (
              <div className="mb-2 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                {attachmentNotice}
              </div>
            )}
            <div className="rounded-md border border-border bg-card/95 p-4">
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Ask across your vault..."
                rows={5}
                className="min-h-[150px] resize-none border-0 bg-transparent p-0 text-base shadow-none focus-visible:ring-0"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    void startPromptChat();
                  }
                }}
              />
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  disabled={!backendReady || creating}
                  aria-label="Attach files"
                  title="Attach files"
                  onClick={() => void addAttachments()}
                >
                  <Paperclip className="h-4 w-4" />
                </Button>
                <Select
                  value={scopeClusterId ?? "global"}
                  onValueChange={(value) => setScopeClusterId(value === "global" ? null : value)}
                >
                  <SelectTrigger className="h-8 w-auto min-w-44 gap-2 px-2.5 text-xs">
                    <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="global">All vault context</SelectItem>
                    {backendClusters.map((cluster) => (
                      <SelectItem key={cluster.id} value={cluster.id}>
                        {cluster.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-xs text-muted-foreground">
                  {backendReady ? "Semantic retrieval ready" : "Create a vault to chat"}
                </span>
                <Button
                  className="ml-auto gap-2"
                  onClick={() => void startPromptChat()}
                  disabled={(!prompt.trim() && attachments.length === 0) || creating}
                >
                  <Send className="h-4 w-4" />
                  Send
                </Button>
              </div>
            </div>
            {attachments.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {attachments.map((path) => (
                  <button
                    key={path}
                    type="button"
                    className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent"
                    onClick={() => removeAttachment(path)}
                    title="Remove attachment"
                  >
                    {fileNameFromPath(path)} <span className="ml-1 text-foreground">Ready</span>
                  </button>
                ))}
              </div>
            )}
            <div className="mt-6 text-sm text-muted-foreground">
              Ctrl/Cmd Enter sends. Existing chats stay in the left list.
            </div>
          </section>
        </main>
      </div>
      <aside className="overflow-y-auto border-l border-border bg-card/35 px-7 py-8">
        <div className="flex items-center gap-3">
          <span className="h-2.5 w-2.5 rounded-full bg-primary" />
          <h2 className="text-lg font-semibold">Vault context</h2>
          <MoreHorizontal className="ml-auto h-4 w-4 text-muted-foreground" />
          <span className="h-6 w-px bg-border" />
          <X className="h-4 w-4 text-muted-foreground" />
        </div>
        <p className="mt-8 text-sm leading-6 text-muted-foreground">
          Start globally by default. Pick a cluster only when the question needs a narrower memory space.
        </p>
        <div className="my-8 h-px bg-border" />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Active memory</h3>
        <div className="mt-5 grid grid-cols-2 gap-5">
          <Metric value={backendReady ? String(backendChats.length) : "0"} label="Chats" />
          <Metric value={backendReady ? String(backendClusters.length) : "5"} label="Clusters" />
          <Metric value={attachments.length.toString()} label="Attachments" />
          <Metric value={backendReady ? "Ready" : "No vault"} label="Status" />
        </div>
        <div className="my-8 h-px bg-border" />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Suggested prompts</h3>
        <div className="mt-4 space-y-2">
          {[
            "Summarize my design research",
            "What needs review today?",
            "Compare strategy and meeting notes",
          ].map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setPrompt(item)}
              className="flex w-full items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-left text-sm hover:bg-accent/45"
            >
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <span className="flex-1">{item}</span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </button>
          ))}
        </div>
        <div className="my-8 h-px bg-border" />
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Recent sources</h3>
        <div className="mt-5 rounded-md border border-border bg-background px-3 py-3 text-sm text-muted-foreground">
          Recent indexed sources appear here after a vault is active.
        </div>
      </aside>
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-semibold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function titleFromPrompt(prompt: string) {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  if (!cleaned) return "New chat";
  return cleaned.length > 60 ? `${cleaned.slice(0, 57).trim()}...` : cleaned;
}
