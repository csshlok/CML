import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/mockStore";
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
import { MessageSquare, Plus, Send, SlidersHorizontal, Trash2 } from "lucide-react";
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
  const { chats, createChat } = useStore();
  const navigate = useNavigate();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendClusters, setBackendClusters] = useState<ClusterRecord[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [prompt, setPrompt] = useState("");
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
    } catch {
      // Fall back to local mock chat below.
    }
    const chat = createChat(null);
    navigate({ to: "/chat/$chatId", params: { chatId: chat.id } });
  }

  async function startPromptChat() {
    const text = prompt.trim();
    if (!text || creating) return;
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
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      }
    } catch {
      // Fall back to local mock chat below.
    } finally {
      setCreating(false);
    }
    const chat = createChat(scopeClusterId);
    window.sessionStorage.setItem(`cml.pendingPrompt.${chat.id}`, text);
    navigate({ to: "/chat/$chatId", params: { chatId: chat.id } });
  }

  async function removeChat(id: string) {
    if (backendReady) {
      await deleteChatSession(id);
      await load();
    }
  }

  const visibleChats = backendReady ? backendChats : chats;

  if (pathname !== "/chat") {
    return <Outlet />;
  }

  return (
    <div className="flex h-full">
      <div className="w-64 border-r border-border bg-card/40 p-2">
        <Button variant="ghost" className="mb-2 w-full justify-start gap-2" onClick={newChat}>
          <Plus className="h-4 w-4" /> New chat
        </Button>
        <div className="space-y-0.5">
          {visibleChats.map((c) => (
            <div key={c.id} className="group flex items-center gap-1 rounded-md hover:bg-accent">
              <Link
                to="/chat/$chatId"
                params={{ chatId: c.id }}
                className="min-w-0 flex-1 truncate px-2.5 py-1.5 text-sm text-muted-foreground group-hover:text-foreground"
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
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border px-8 py-5">
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

        <main className="flex flex-1 items-center justify-center px-8">
          <section className="w-full max-w-2xl">
            <div className="rounded-md border border-border bg-card p-3">
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Ask across your vault..."
                rows={5}
                className="min-h-32 resize-none border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    void startPromptChat();
                  }
                }}
              />
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
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
                  {backendReady ? "Semantic retrieval ready" : "Local fallback"}
                </span>
                <Button
                  className="ml-auto gap-2"
                  onClick={() => void startPromptChat()}
                  disabled={!prompt.trim() || creating}
                >
                  <Send className="h-4 w-4" />
                  Send
                </Button>
              </div>
            </div>
            {visibleChats.length > 0 && (
              <div className="mt-5 text-sm text-muted-foreground">
                Ctrl/Cmd Enter sends. Existing chats stay in the left list.
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}

function titleFromPrompt(prompt: string) {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  if (!cleaned) return "New chat";
  return cleaned.length > 60 ? `${cleaned.slice(0, 57).trim()}...` : cleaned;
}
