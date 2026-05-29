import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import {
  useStore,
  streamMockReply,
  newId,
  type Cluster,
  type Source,
} from "@/lib/mockStore";
import {
  buildChatContext,
  deleteChatSession,
  getChatSession,
  listClusters,
  listSources,
  listVaults,
  reindexVaultSearch,
  updateChatMessage,
  updateChatSession,
  type ChatMessageRecord,
  type ChatSessionRecord,
  type VaultRecord,
} from "@/lib/backend";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ClusterChip, ClusterDot } from "@/components/ClusterChip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Send,
  Bookmark,
  ThumbsUp,
  ThumbsDown,
  Paperclip,
  Quote,
  Trash2,
} from "lucide-react";

export const Route = createFileRoute("/_app/chat/$chatId")({
  head: () => ({ meta: [{ title: "Chat" }] }),
  component: ChatView,
});

function ChatView() {
  const { chatId } = Route.useParams();
  const navigate = useNavigate();
  const {
    chats,
    clusters,
    sources,
    appendMessage,
    setMessageUseful,
    saveChat,
    createChat,
  } = useStore();
  const chat = chats.find((c) => c.id === chatId);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [vault, setVaultRecord] = useState<VaultRecord | null>(null);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [backendSessionId, setBackendSessionId] = useState<string | null>(null);
  const [backendSession, setBackendSession] = useState<ChatSessionRecord | null>(null);
  const [backendMessages, setBackendMessages] = useState<import("@/lib/mockStore").ChatMessage[]>([]);
  const [titleDraft, setTitleDraft] = useState("");
  const [memoryState, setMemoryState] = useState("idle");
  const [loadingSession, setLoadingSession] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  async function loadBackendContext() {
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setVaultRecord(activeVault);
      if (!activeVault) return;
      await reindexVaultSearch(activeVault.id).catch(() => undefined);
      const [clusterRows, sourceRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id),
      ]);
      setBackendClusters(clusterRows.map(clusterFromRecord));
      setBackendSources(sourceRows.map(sourceFromRecord));
      try {
        const session = await getChatSession(chatId);
        setBackendSession(session);
        setBackendSessionId(session.id);
        setBackendMessages(session.messages.map(messageFromRecord));
        setMemoryState(session.memory_status ?? "idle");
      } catch {
        setBackendSession(null);
        setBackendMessages([]);
        setMemoryState("idle");
      }
      setBackendReady(true);
    } catch {
      setBackendReady(false);
    } finally {
      setLoadingSession(false);
    }
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.length, backendMessages.length, streamText]);

  useEffect(() => {
    void loadBackendContext();
  }, []);

  useEffect(() => {
    setTitleDraft(backendSession?.title ?? chat?.title ?? "New chat");
  }, [backendSession?.title, chat?.title]);

  if (loadingSession && !chat && !backendSession) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading chat...
      </div>
    );
  }

  if (!chat && !backendSession) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Chat not found.
      </div>
    );
  }

  const activeClusters = backendReady ? backendClusters : clusters;
  const activeSources = backendReady ? backendSources : sources;
  const messages = backendSession ? backendMessages : chat?.messages ?? [];
  const scopeClusterId = backendSession?.scope_cluster_id ?? chat?.scopeClusterId ?? null;
  const saved = backendSession?.saved ?? chat?.saved ?? false;

  const scope = scopeClusterId
    ? activeClusters.find((c) => c.id === scopeClusterId) ?? null
    : null;

  const setScope = async (val: string) => {
    const nextScope = val === "global" ? null : val;
    if (backendSession) {
      try {
        const updated = await updateChatSession(backendSession.id, {
          scope_cluster_id: nextScope,
        });
        setBackendSession(updated);
      } catch {
        // Keep the current scope visible if the backend update fails.
      }
      return;
    }
    const c = createChat(val === "global" ? null : val);
    navigate({ to: "/chat/$chatId", params: { chatId: c.id } });
  };

  const toggleSaved = async () => {
    if (backendSession) {
      try {
        const updated = await updateChatSession(backendSession.id, { saved: !backendSession.saved });
        setBackendSession(updated);
      } catch {
        // Preserve the current saved state if the backend update fails.
      }
      return;
    }
    if (chat) saveChat(chat.id, !chat.saved);
  };

  const commitTitle = async () => {
    const nextTitle = titleDraft.trim();
    if (!backendSession || !nextTitle || nextTitle === backendSession.title) return;
    try {
      const updated = await updateChatSession(backendSession.id, { title: nextTitle });
      setBackendSession(updated);
    } catch {
      setTitleDraft(backendSession.title);
    }
  };

  const deleteCurrentChat = async () => {
    if (backendSession) {
      await deleteChatSession(backendSession.id);
    }
    navigate({ to: "/chat" });
  };

  const send = async (promptOverride?: string) => {
    const prompt = (promptOverride ?? input).trim();
    if (!prompt) return;
    const userMsg = { id: newId(), role: "user" as const, content: prompt };
    if (backendSession) {
      setBackendMessages((current) => [...current, userMsg]);
    } else if (chat) {
      appendMessage(chat.id, userMsg);
    }
    if (!promptOverride) setInput("");
    setStreaming(true);
    setStreamText("");
    if (backendSession) setMemoryState("indexing");
    if (backendReady && vault) {
      try {
        const response = await buildChatContext({
          vault_id: vault.id,
          prompt,
          cluster_id: scope?.id ?? null,
          session_id: backendSessionId,
          persist: true,
          limit: 6,
        });
        setBackendSessionId(response.session_id);
        setMemoryState(response.memory_status ?? "indexed");
        await revealAnswer(response.answer);
        const assistantMessage = {
          id: newId(),
          role: "assistant",
          content: response.answer,
          clustersUsed: response.clusters_used.map((cluster) => ({
            clusterId: cluster.cluster_id,
            reason: cluster.reason,
          })),
          citations: response.citations.map((citation) => ({
            sourceId: citation.source_id,
            snippet: citation.snippet,
          })),
          useful: null,
        } satisfies import("@/lib/mockStore").ChatMessage;
        if (backendSession) {
          if (response.session_id) {
            try {
              const refreshed = await getChatSession(response.session_id);
              setBackendSession(refreshed);
              setBackendMessages(refreshed.messages.map(messageFromRecord));
              setMemoryState(refreshed.memory_status ?? response.memory_status ?? "indexed");
              const [clusterRows, sourceRows] = await Promise.all([
                listClusters(vault.id),
                listSources(vault.id),
              ]);
              setBackendClusters(clusterRows.map(clusterFromRecord));
              setBackendSources(sourceRows.map(sourceFromRecord));
            } catch {
              // Optimistic messages above remain usable until the next refresh.
            }
          }
        } else if (chat) {
          appendMessage(chat.id, assistantMessage);
        }
      } catch (error) {
        setMemoryState("issue");
        const errorMessage = {
          id: newId(),
          role: "assistant",
          content:
            error instanceof Error
              ? `I could not retrieve local context: ${error.message}`
              : "I could not retrieve local context.",
          useful: null,
        } satisfies import("@/lib/mockStore").ChatMessage;
        if (backendSession) {
          setBackendMessages((current) => [...current, errorMessage]);
        } else if (chat) {
          appendMessage(chat.id, errorMessage);
        }
      } finally {
          setStreaming(false);
          setStreamText("");
        }
      return;
    }
    let full = "";
    for await (const chunk of streamMockReply(prompt, scope)) {
      full += chunk;
      setStreamText(full);
    }
    // pick clusters used
    const usedClusters = scope
      ? [{ clusterId: scope.id, reason: "selected scope" }]
      : activeClusters.slice(0, 2).map((c, i) => ({
          clusterId: c.id,
          reason: i === 0 ? "style" : "facts",
        }));
    const usedSources = activeSources
      .filter((s) =>
        usedClusters.some((u) => u.clusterId === s.clusterId) && s.state === "indexed",
      )
      .slice(0, 3)
      .map((s) => ({
        sourceId: s.id,
        snippet: s.preview.slice(0, 80) + "...",
      }));
    if (chat) appendMessage(chat.id, {
      id: newId(),
      role: "assistant",
      content: full.trim(),
      clustersUsed: usedClusters,
      citations: usedSources,
      useful: null,
    });
    setStreaming(false);
    setStreamText("");
  };

  const setBackendMessageUseful = async (messageId: string, value: boolean) => {
    if (backendSession) {
      const updated = await updateChatMessage(messageId, { useful: value });
      setBackendSession(updated);
      setBackendMessages(updated.messages.map(messageFromRecord));
      return;
    }
    if (chat) setMessageUseful(chat.id, messageId, value);
  };

  const toggleBackendMessageSaved = async (messageId: string, current: boolean) => {
    if (!backendSession) return;
    const updated = await updateChatMessage(messageId, { saved: !current });
    setBackendSession(updated);
    setBackendMessages(updated.messages.map(messageFromRecord));
  };

  const regenerateFromMessage = (messageId: string) => {
    const index = messages.findIndex((message) => message.id === messageId);
    const priorUser = messages
      .slice(0, Math.max(0, index))
      .reverse()
      .find((message) => message.role === "user");
    if (priorUser) void send(priorUser.content);
  };

  const revealAnswer = async (text: string) => {
    const words = text.split(/(\s+)/);
    let rendered = "";
    for (const word of words) {
      rendered += word;
      setStreamText(rendered);
      if (word.trim()) {
        await new Promise((resolve) => window.setTimeout(resolve, 12));
      }
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border bg-card/40 px-6 py-3">
        <Input
          value={titleDraft}
          onChange={(event) => setTitleDraft(event.target.value)}
          onBlur={commitTitle}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          disabled={!backendSession}
          aria-label="Chat title"
          className="h-8 w-56 border-transparent bg-transparent px-2 text-sm font-medium disabled:opacity-100"
        />
        <div className="text-xs text-muted-foreground">Scope</div>
        <Select
          value={scopeClusterId ?? "global"}
          onValueChange={setScope}
        >
          <SelectTrigger className="h-8 w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="global">Global - all clusters</SelectItem>
            {activeClusters.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleSaved}
          >
            <Bookmark className={"h-4 w-4 " + (saved ? "fill-current" : "")} />
            {saved ? "Saved" : "Save"}
          </Button>
          <Button variant="ghost" size="sm" className="gap-1" onClick={() => void deleteCurrentChat()}>
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
          <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
            {backendReady ? "Semantic context" : "Local fallback context"}
          </span>
          {backendSession && (
            <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
              Memory {memoryLabel(memoryState)}
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-8">
          {messages.length === 0 && !streaming && (
            <div className="text-center text-muted-foreground">
              <p className="text-lg font-medium text-foreground">
                Ask anything across your context.
              </p>
              <p className="mt-2 text-sm">
                {scope
                  ? `Scoped to ${scope.name}.`
                  : "Working across all clusters in your vault."}
              </p>
            </div>
          )}
          <div className="space-y-6">
            {messages.map((m) => (
              <Message
                key={m.id}
                msg={m}
                clusters={activeClusters}
                sources={activeSources}
                onUseful={(v) => {
                  void setBackendMessageUseful(m.id, v);
                }}
                onSaved={() => void toggleBackendMessageSaved(m.id, Boolean(m.saved))}
                onRegenerate={() => regenerateFromMessage(m.id)}
              />
            ))}
            {streaming && (
              <div className="rounded-md border border-border bg-card p-4">
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {streamText}
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground/40 align-middle" />
                </p>
              </div>
            )}
          </div>
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-border bg-card/40 p-4">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            disabled
            aria-label="Attachments are not available yet"
            title="Attachments are not available yet"
          >
            <Paperclip className="h-4 w-4" />
          </Button>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={scope ? `Ask ${scope.name}...` : "Ask your vault..."}
            rows={2}
            className="resize-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <Button onClick={() => void send()} disabled={streaming || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mx-auto mt-1.5 max-w-2xl text-[11px] text-muted-foreground">
          Ctrl/Cmd Enter to send / all processing local / memory {memoryLabel(memoryState)}
        </p>
      </div>
    </div>
  );
}

function memoryLabel(status: string) {
  if (status === "indexed") return "saved";
  if (status === "indexing") return "saving";
  if (status === "issue") return "issue";
  return "idle";
}

function messageFromRecord(record: ChatMessageRecord): import("@/lib/mockStore").ChatMessage {
  return {
    id: record.id,
    role: record.role,
    content: record.content,
    clustersUsed: record.clusters_used.map((cluster) => ({
      clusterId: cluster.cluster_id,
      reason: cluster.reason,
    })),
    citations: record.citations.map((citation) => ({
      sourceId: citation.source_id,
      snippet: citation.snippet,
    })),
    useful: record.useful,
    saved: record.saved,
  };
}

function Message({
  msg,
  clusters,
  sources,
  onUseful,
  onSaved,
  onRegenerate,
}: {
  msg: import("@/lib/mockStore").ChatMessage;
  clusters: Cluster[];
  sources: import("@/lib/mockStore").Source[];
  onUseful: (v: boolean) => void;
  onSaved: () => void;
  onRegenerate: () => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-md bg-accent px-3.5 py-2.5 text-sm">
        {msg.content}
      </div>
    );
  }
  return (
    <div className="rounded-md border border-border bg-card p-4">
      {msg.clustersUsed && msg.clustersUsed.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          Using
          {msg.clustersUsed.map((u, i) => {
            const c = clusters.find((x) => x.id === u.clusterId);
            if (!c) return null;
            return (
              <span key={u.clusterId} className="flex items-center gap-1.5">
                <ClusterChip cluster={c} />
                <span className="opacity-70">for {u.reason}</span>
                {i < msg.clustersUsed!.length - 1 && <span>/</span>}
              </span>
            );
          })}
        </div>
      )}
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
      {msg.citations && msg.citations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {msg.citations.map((cit, i) => {
            const s = sources.find((x) => x.id === cit.sourceId);
            return (
              <Popover key={i}>
                <PopoverTrigger asChild>
                  <button className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] hover:bg-accent">
                    <Quote className="h-3 w-3" /> {s?.title ?? "source"}
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-80 text-xs">
                  <div className="mb-1 font-medium">{s?.title}</div>
                  <p className="text-muted-foreground">{cit.snippet}</p>
                </PopoverContent>
              </Popover>
            );
          })}
        </div>
      )}
      <div className="mt-3 flex items-center gap-1 border-t border-border pt-2 text-xs text-muted-foreground">
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={onSaved}>
          <Bookmark className={"mr-1 h-3.5 w-3.5 " + (msg.saved ? "fill-current" : "")} />
          {msg.saved ? "Saved" : "Save answer"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className={"h-7 px-2 " + (msg.useful === true ? "text-foreground" : "")}
          onClick={() => onUseful(true)}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className={"h-7 px-2 " + (msg.useful === false ? "text-foreground" : "")}
          onClick={() => onUseful(false)}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={onRegenerate}>
          Regenerate
        </Button>
      </div>
    </div>
  );
}
