import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { type DragEvent, useEffect, useState } from "react";
import {
  listClustersPage,
  createChatSession,
  deleteChatSession,
  listChatSessionsPage,
  listVaults,
  type ChatSessionRecord,
  type ClusterRecord,
  type VaultRecord,
} from "@/lib/backend";
import { LoaderCircle, MessageSquare, Paperclip, Plus, Send, SlidersHorizontal, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmAction } from "@/components/product/Feedback";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useVisiblePolling } from "@/lib/useVisiblePolling";

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
  const [chatCursor, setChatCursor] = useState<string | null>(null);
  const [clusterCursor, setClusterCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
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
      const [sessionResult, clusterResult] = await Promise.allSettled([
        listChatSessionsPage(activeVault.id, { limit: 100 }),
        listClustersPage(activeVault.id, { limit: 200 }),
      ]);
      if (sessionResult.status === "fulfilled") {
        setBackendChats(sessionResult.value.items);
        setChatCursor(sessionResult.value.next_cursor);
        setBackendReady(true);
      } else {
        setBackendReady(false);
      }
      if (clusterResult.status === "fulfilled") {
        setBackendClusters(clusterResult.value.items);
        setClusterCursor(clusterResult.value.next_cursor);
      }
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
        const [sessionResult, clusterResult] = await Promise.allSettled([
          listChatSessionsPage(activeVault.id, { limit: 100 }),
          listClustersPage(activeVault.id, { limit: 200 }),
        ]);
        if (cancelled) return;
        if (sessionResult.status === "fulfilled") {
          setBackendChats(sessionResult.value.items);
          setChatCursor(sessionResult.value.next_cursor);
          setBackendReady(true);
        } else {
          setBackendReady(false);
        }
        if (clusterResult.status === "fulfilled") {
          setBackendClusters(clusterResult.value.items);
          setClusterCursor(clusterResult.value.next_cursor);
        }
      } catch {
        if (!cancelled) setBackendReady(false);
      }
    }

    void loadIfMounted();

    return () => {
      cancelled = true;
    };
  }, []);

  useVisiblePolling(load, 4_000, Boolean(vault));

  async function newChat() {
    try {
      const activeVault = vault ?? (await listVaults())[0] ?? null;
      if (activeVault) {
        const session = await createChatSession({ vault_id: activeVault.id });
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      }
    } catch {
      // Fall back to settings when the backend cannot create a chat yet.
    }
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

  async function loadMoreChats() {
    if (!vault || !chatCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await listChatSessionsPage(vault.id, { limit: 100, cursor: chatCursor });
      setBackendChats((current) => [...current, ...page.items]);
      setChatCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }

  async function loadMoreClusters() {
    if (!vault || !clusterCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await listClustersPage(vault.id, { limit: 200, cursor: clusterCursor });
      setBackendClusters((current) => [...current, ...page.items]);
      setClusterCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
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
    const droppedPaths = window.cmlDesktop?.getDroppedFilePaths?.() ?? [];
    const paths = window.cmlDesktop?.listSupportedFiles
      ? await window.cmlDesktop.listSupportedFiles(droppedPaths)
      : droppedPaths;
    if (paths.length === 0) {
      setAttachmentNotice("No supported documents found in that drop.");
      return;
    }
    addAttachmentPaths(paths);
  }

  const visibleChats = backendReady ? backendChats : [];

  if (pathname !== "/chat") {
    return (
      <div className="grid h-full min-w-0 grid-cols-[260px_minmax(0,1fr)] overflow-hidden xl:grid-cols-[300px_minmax(0,1fr)]">
        <ChatHistory
          chats={visibleChats}
          cursor={chatCursor}
          loadingMore={loadingMore}
          onNew={() => void newChat()}
          onDelete={(id) => void removeChat(id)}
          onLoadMore={() => void loadMoreChats()}
        />
        <div className="min-w-0 overflow-hidden">
          <Outlet />
        </div>
      </div>
    );
  }

  return (
    <div
      className={
        "vault-page-wash grid h-full grid-cols-1 overflow-y-auto xl:overflow-hidden " +
        (visibleChats.length > 0
          ? "lg:grid-cols-[260px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)]"
          : "")
      }
      onDragOver={(event) => {
        event.preventDefault();
        if (backendReady) setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(event) => void handleDrop(event)}
    >
      {visibleChats.length > 0 ? (
      <aside className="border-b border-border bg-card/35 px-4 py-4 sm:px-5 lg:overflow-y-auto lg:border-b-0 lg:border-r lg:py-6">
        <Button variant="ghost" className="mb-5 w-full justify-start gap-2 text-base" onClick={newChat}>
          <Plus className="h-4 w-4" /> New chat
        </Button>
        <div className="max-h-56 space-y-1 overflow-y-auto lg:max-h-none">
          {visibleChats.map((c) => (
            <div key={c.id} className="group flex items-center gap-1 rounded-md hover:bg-accent/60">
              <Link
                to="/chat/$chatId"
                params={{ chatId: c.id }}
                className="flex min-w-0 flex-1 items-center gap-2 break-words px-3 py-2 text-sm text-muted-foreground group-hover:text-foreground"
              >
                {c.active_generation ? (
                  <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" />
                ) : null}
                <span className="truncate">{c.title}</span>
              </Link>
              {backendReady && (
                <ConfirmAction
                  title={`Delete “${c.title}”?`}
                  description="This removes the conversation and its saved messages from this Vault."
                  confirmLabel="Delete chat"
                  onConfirm={() => removeChat(c.id)}
                >
                  <Button
                    variant="ghost"
                    size="icon"
                    className="mr-1 h-9 w-9 opacity-70 group-hover:opacity-100"
                    aria-label={`Delete ${c.title}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </ConfirmAction>
              )}
            </div>
          ))}
          {chatCursor ? (
            <Button variant="ghost" size="sm" className="w-full" disabled={loadingMore} onClick={() => void loadMoreChats()}>
              {loadingMore ? "Loading..." : "Load older chats"}
            </Button>
          ) : null}
        </div>
      </aside>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border bg-card/35 px-4 py-5 sm:px-6 lg:px-10 lg:py-7">
          <div className="flex min-w-0 items-start gap-3">
            <MessageSquare className="h-5 w-5 text-muted-foreground" />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold tracking-[-0.02em]">Ask your library</h1>
              <p className="break-words text-sm text-muted-foreground">
                Vault finds the relevant sources first, then your local model writes the answer.
              </p>
            </div>
          </div>
        </header>

        <main className="flex flex-1 items-center justify-center overflow-y-auto px-4 py-6 sm:px-6 lg:px-10">
          <section className="w-full max-w-[840px]">
            {visibleChats.length === 0 ? (
              <div className="mb-8 max-w-2xl">
                <div className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  First conversation
                </div>
                <h2 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-foreground">
                  Start with a real question.
                </h2>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                  Ask about a saved source, compare clusters, or attach a file to store it with
                  your first message.
                </p>
              </div>
            ) : null}
            {dragActive && (
              <div className="mb-2 break-words rounded-md border border-dashed border-primary/50 bg-primary/5 px-3 py-2 text-xs text-foreground">
                Drop files to attach them to the first message.
              </div>
            )}
            {attachmentNotice && (
              <div className="mb-2 break-words rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                {attachmentNotice}
              </div>
            )}
            <div className="rounded-md border border-border bg-card/95 p-4">
              <Textarea
                aria-label="Ask across your vault"
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
                  <SelectTrigger className="h-8 w-full min-w-0 gap-2 px-2.5 text-xs sm:w-auto sm:min-w-44">
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
                {clusterCursor ? (
                  <Button variant="ghost" size="sm" disabled={loadingMore} onClick={() => void loadMoreClusters()}>
                    More clusters
                  </Button>
                ) : null}
                <span className="text-xs text-muted-foreground">
                  {backendReady ? "Your library is ready" : "Create a library to start chatting"}
                </span>
                <Button
                  className="gap-2 sm:ml-auto"
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
                    className="max-w-full break-all rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent"
                    onClick={() => removeAttachment(path)}
                    title="Remove attachment"
                  >
                    {fileNameFromPath(path)} <span className="ml-1 text-foreground">Ready</span>
                  </button>
                ))}
              </div>
            )}
            <div className="mt-4 text-xs text-muted-foreground">Ctrl/Cmd Enter to send</div>
          </section>
        </main>
      </div>
    </div>
  );
}

function ChatHistory({
  chats,
  cursor,
  loadingMore,
  onNew,
  onDelete,
  onLoadMore,
}: {
  chats: ChatSessionRecord[];
  cursor: string | null;
  loadingMore: boolean;
  onNew: () => void;
  onDelete: (id: string) => void;
  onLoadMore: () => void;
}) {
  return (
    <aside className="min-w-0 border-r border-border bg-card/35 px-4 py-5">
      <Button variant="ghost" className="mb-4 w-full justify-start gap-2" onClick={onNew}>
        <Plus className="h-4 w-4" /> New chat
      </Button>
      <div className="h-[calc(100%-3rem)] space-y-1 overflow-y-auto">
        {chats.map((chat) => (
          <div key={chat.id} className="group flex items-center gap-1 rounded-md hover:bg-accent/60">
            <Link
              to="/chat/$chatId"
              params={{ chatId: chat.id }}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-sm text-muted-foreground group-hover:text-foreground"
            >
              {chat.active_generation ? (
                <LoaderCircle
                  className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none"
                  aria-label="Answer in progress"
                />
              ) : (
                <MessageSquare className="h-3.5 w-3.5 shrink-0" />
              )}
              <span className="truncate">{chat.title}</span>
            </Link>
            <ConfirmAction
              title={`Delete “${chat.title}”?`}
              description="This removes the conversation and its saved messages."
              confirmLabel="Delete chat"
              onConfirm={() => onDelete(chat.id)}
            >
              <Button
                variant="ghost"
                size="icon"
                className="mr-1 h-8 w-8 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                aria-label={`Delete ${chat.title}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </ConfirmAction>
          </div>
        ))}
        {cursor ? (
          <Button variant="ghost" size="sm" className="w-full" disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? "Loading..." : "Load older chats"}
          </Button>
        ) : null}
      </div>
    </aside>
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
