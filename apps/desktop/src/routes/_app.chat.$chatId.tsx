import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { useStore, streamMockReply, newId, type Cluster, type Source } from "@/lib/mockStore";
import {
  deleteChatSession,
  getModelRuntimeStatus,
  getChatSession,
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  reindexVaultSearch,
  streamChatContext,
  updateChatMessage,
  updateChatSession,
  type ChatContextResponse,
  type ChatMessageRecord,
  type ChatSessionRecord,
  type ModelRuntimeStatus,
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Bookmark,
  MessageSquare,
  Paperclip,
  Quote,
  RotateCcw,
  Send,
  SlidersHorizontal,
  StopCircle,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";

export const Route = createFileRoute("/_app/chat/$chatId")({
  head: () => ({ meta: [{ title: "Chat" }] }),
  component: ChatView,
});

function ChatView() {
  const { chatId } = Route.useParams();
  const navigate = useNavigate();
  const { chats, clusters, sources, appendMessage, setMessageUseful, saveChat, createChat } =
    useStore();
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
  const [backendMessages, setBackendMessages] = useState<import("@/lib/mockStore").ChatMessage[]>(
    [],
  );
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [titleDraft, setTitleDraft] = useState("");
  const [memoryState, setMemoryState] = useState("idle");
  const [loadingSession, setLoadingSession] = useState(true);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [streamWarnings, setStreamWarnings] = useState<string[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [attachmentNotice, setAttachmentNotice] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const consumedPendingPromptRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  async function loadBackendContext() {
    setLoadingSession(true);
    setBackendSession(null);
    setBackendSessionId(null);
    setBackendMessages([]);
    setLastError(null);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setVaultRecord(activeVault);
      if (!activeVault) return;
      await reindexVaultSearch(activeVault.id).catch(() => undefined);
      const [clusterRows, sourceRows, chatRows] = await Promise.all([
        listClusters(activeVault.id),
        listSources(activeVault.id),
        listChatSessions(activeVault.id),
      ]);
      setBackendClusters(clusterRows.map(clusterFromRecord));
      setBackendSources(sourceRows.map(sourceFromRecord));
      setBackendChats(chatRows);
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
      void getModelRuntimeStatus().then(setRuntime).catch(() => setRuntime(null));
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
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [chatId]);

  useEffect(() => {
    if (!backendReady) return;
    let cancelled = false;
    async function refreshRuntime() {
      try {
        const status = await getModelRuntimeStatus();
        if (!cancelled) setRuntime(status);
      } catch {
        if (!cancelled) setRuntime(null);
      }
    }
    void refreshRuntime();
    const id = window.setInterval(refreshRuntime, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [backendReady]);

  useEffect(() => {
    setTitleDraft(backendSession?.title ?? chat?.title ?? "New chat");
  }, [backendSession?.title, chat?.title]);

  useEffect(() => {
    if (loadingSession || streaming || consumedPendingPromptRef.current === chatId) return;
    const pendingPrompt = window.sessionStorage.getItem(`cml.pendingPrompt.${chatId}`);
    const pendingAttachments = JSON.parse(
      window.sessionStorage.getItem(`cml.pendingAttachments.${chatId}`) ?? "[]",
    ) as string[];
    if (!pendingPrompt && pendingAttachments.length === 0) return;
    consumedPendingPromptRef.current = chatId;
    window.sessionStorage.removeItem(`cml.pendingPrompt.${chatId}`);
    window.sessionStorage.removeItem(`cml.pendingAttachments.${chatId}`);
    void send(pendingPrompt ?? undefined, pendingAttachments);
  }, [chatId, loadingSession, streaming]);

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
  const messages = backendSession ? backendMessages : (chat?.messages ?? []);
  const scopeClusterId = backendSession?.scope_cluster_id ?? chat?.scopeClusterId ?? null;
  const saved = backendSession?.saved ?? chat?.saved ?? false;

  const scope = scopeClusterId
    ? (activeClusters.find((c) => c.id === scopeClusterId) ?? null)
    : null;
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const latestCitations = latestAssistant?.citations ?? [];
  const latestWarnings = streamWarnings.length > 0 ? streamWarnings : [];

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
        const updated = await updateChatSession(backendSession.id, {
          saved: !backendSession.saved,
        });
        setBackendSession(updated);
        window.dispatchEvent(new Event("vault:chats-changed"));
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

  const send = async (promptOverride?: string, attachmentOverride?: string[]) => {
    const selectedAttachments = attachmentOverride ?? (promptOverride ? [] : attachments);
    const prompt = (promptOverride ?? input).trim() || (selectedAttachments.length > 0 ? "Read and store these attachments." : "");
    if ((!prompt && selectedAttachments.length === 0) || streaming) return;
    const attachmentNote =
      selectedAttachments.length > 0
        ? `\n\nAttachments:\n${selectedAttachments.map((path) => `- ${fileNameFromPath(path)}`).join("\n")}`
        : "";
    const userMsg = { id: newId(), role: "user" as const, content: prompt + attachmentNote };
    if (backendReady && vault) {
      setBackendMessages((current) => [...current, userMsg]);
    } else if (chat) {
      appendMessage(chat.id, userMsg);
    }
    if (!promptOverride) {
      setInput("");
      setAttachments([]);
    }
    setStreaming(true);
    setStreamText("");
    setStreamStatus("Finding relevant context...");
    setStreamWarnings([]);
    setLastError(null);
    setAttachmentNotice(
      selectedAttachments.length > 0
        ? `Storing ${selectedAttachments.length} attachment${selectedAttachments.length === 1 ? "" : "s"} as vault source${selectedAttachments.length === 1 ? "" : "s"}...`
        : null,
    );
    if (backendSession) setMemoryState("indexing");
    if (backendReady && vault) {
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      try {
        let streamedAnswer = "";
        let streamedMeta: Pick<ChatContextResponse, "clusters_used" | "citations" | "coverage_ledger" | "warnings"> = {
          clusters_used: [],
          citations: [],
          coverage_ledger: null,
          warnings: [],
        };
        let streamedDone: Partial<ChatContextResponse> = {};
        await streamChatContext(
          {
            vault_id: vault.id,
            prompt,
            cluster_id: scope?.id ?? null,
            session_id: backendSessionId ?? chatId,
            persist: true,
            limit: 6,
            attachments: selectedAttachments.map((path) => ({
              path,
              cluster_id: scope?.id ?? null,
            })),
          },
          {
            onMeta: (meta) => {
              streamedMeta = meta;
              const coverage = meta.coverage_ledger;
              setStreamStatus(
                coverage
                  ? `Considered ${coverage.sources_considered} source${coverage.sources_considered === 1 ? "" : "s"}; analyzing ${coverage.sources_analyzed}.`
                  : meta.citations.length > 0
                  ? `Using ${meta.citations.length} source${meta.citations.length === 1 ? "" : "s"}`
                  : "No matching source found yet",
              );
              setStreamWarnings(meta.warnings ?? []);
            },
            onToken: (text) => {
              streamedAnswer += text;
              setStreamStatus("Writing answer...");
              setStreamText(streamedAnswer);
            },
            onDone: (done) => {
              streamedDone = done;
              setStreamWarnings(done.warnings ?? streamedMeta.warnings ?? []);
            },
          },
          abortController.signal,
        );
        const response = {
          session_id: streamedDone.session_id ?? backendSessionId ?? chatId,
          answer: streamedDone.answer ?? streamedAnswer,
          clusters_used: streamedMeta.clusters_used,
          citations: streamedMeta.citations,
          memory_status: streamedDone.memory_status ?? "indexed",
        };
        setBackendSessionId(response.session_id);
        setMemoryState(response.memory_status ?? "indexed");
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
            pageNumber: citation.page_number,
            state: citation.state,
            title: citation.source_title,
          })),
          useful: null,
        } satisfies import("@/lib/mockStore").ChatMessage;
        if (response.session_id) {
          setBackendMessages((current) => [...current, assistantMessage]);
          try {
            const refreshed = await getChatSession(response.session_id);
            setBackendSession(refreshed);
            setBackendSessionId(refreshed.id);
            setBackendMessages(refreshed.messages.map(messageFromRecord));
            setMemoryState(refreshed.memory_status ?? response.memory_status ?? "indexed");
            const [clusterRows, sourceRows, chatRows] = await Promise.all([
              listClusters(vault.id),
              listSources(vault.id),
              listChatSessions(vault.id),
            ]);
            setBackendClusters(clusterRows.map(clusterFromRecord));
            setBackendSources(sourceRows.map(sourceFromRecord));
            setBackendChats(chatRows);
            window.dispatchEvent(new Event("vault:chats-changed"));
            if (selectedAttachments.length > 0) {
              setAttachmentNotice(
                `Stored ${selectedAttachments.length} attachment${selectedAttachments.length === 1 ? "" : "s"} in ${scope?.name ?? "the vault"}.`,
              );
            }
          } catch {
            // Optimistic messages above remain usable until the next refresh.
          }
        } else if (chat) {
          appendMessage(chat.id, assistantMessage);
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          setStreamStatus("Stopped before saving this answer.");
          return;
        }
        setMemoryState("issue");
        const message = error instanceof Error ? error.message : "Could not retrieve local context.";
        setLastError(
          selectedAttachments.length > 0
            ? `Could not store or read an attachment: ${message}`
            : message,
        );
        if (selectedAttachments.length > 0) {
          setAttachmentNotice("Attachment ingestion failed. The file was not saved as a source.");
        }
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
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
        }
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
      .filter((s) => usedClusters.some((u) => u.clusterId === s.clusterId) && s.state === "indexed")
      .slice(0, 3)
      .map((s) => ({
        sourceId: s.id,
        snippet: s.preview.slice(0, 80) + "...",
      }));
    if (chat)
      appendMessage(chat.id, {
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

  const stopStreaming = () => {
    abortControllerRef.current?.abort();
  };

  const addAttachments = async () => {
    if (!window.cmlDesktop?.selectSourceFiles) return;
    const paths = await window.cmlDesktop.selectSourceFiles();
    addAttachmentPaths(paths);
  };

  const addAttachmentPaths = (paths: string[]) => {
    const cleanPaths = paths.filter(Boolean);
    if (cleanPaths.length === 0) return;
    setAttachments((current) => Array.from(new Set([...current, ...cleanPaths])));
    setAttachmentNotice(
      `${cleanPaths.length} attachment${cleanPaths.length === 1 ? "" : "s"} ready to store with your next message.`,
    );
  };

  const removeAttachment = (path: string) => {
    setAttachments((current) => current.filter((item) => item !== path));
  };

  const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    if (!backendReady) return;
    const droppedPaths = window.cmlDesktop?.getDroppedFilePaths?.(event.dataTransfer.files) ?? [];
    const paths = window.cmlDesktop?.listSupportedFiles
      ? await window.cmlDesktop.listSupportedFiles(droppedPaths)
      : droppedPaths;
    addAttachmentPaths(paths);
  };

  const retryLastUserMessage = () => {
    const lastUser = [...messages].reverse().find((message) => message.role === "user");
    if (lastUser) void send(lastUser.content);
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
    window.dispatchEvent(new Event("vault:chats-changed"));
  };

  const regenerateFromMessage = (messageId: string) => {
    const index = messages.findIndex((message) => message.id === messageId);
    const priorUser = messages
      .slice(0, Math.max(0, index))
      .reverse()
      .find((message) => message.role === "user");
    if (priorUser) void send(priorUser.content);
  };

  return (
    <div
      className="flex h-full"
      onDragOver={(event) => {
        event.preventDefault();
        if (backendReady) setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(event) => void handleDrop(event)}
    >
      <aside className="hidden w-64 shrink-0 border-r border-border bg-card/30 p-2 lg:block">
        <Button
          variant="ghost"
          className="mb-2 w-full justify-start gap-2"
          onClick={() => navigate({ to: "/chat" })}
        >
          <MessageSquare className="h-4 w-4" /> New chat
        </Button>
        <div className="space-y-0.5">
          {backendChats.map((session) => (
            <Link
              key={session.id}
              to="/chat/$chatId"
              params={{ chatId: session.id }}
              className={
                "block truncate rounded-md px-2.5 py-1.5 text-sm transition-colors " +
                (session.id === backendSession?.id
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-accent/70 hover:text-foreground")
              }
            >
              {session.title}
            </Link>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card/40 px-6 py-3">
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
            className="h-8 min-w-0 flex-1 border-transparent bg-transparent px-2 text-sm font-medium disabled:opacity-100 md:max-w-sm"
          />
          <Select value={scopeClusterId ?? "global"} onValueChange={setScope}>
            <SelectTrigger className="h-8 w-52 gap-2 text-xs">
              <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="global">All vault context</SelectItem>
              {activeClusters.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="ml-auto flex items-center gap-2">
            {lastError && (
              <Button variant="outline" size="sm" className="gap-1" onClick={retryLastUserMessage}>
                <RotateCcw className="h-4 w-4" />
                Retry
              </Button>
            )}
            {streaming && (
              <Button variant="outline" size="sm" className="gap-1" onClick={stopStreaming}>
                <StopCircle className="h-4 w-4" />
                Stop
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={toggleSaved}>
              <Bookmark className={"h-4 w-4 " + (saved ? "fill-current" : "")} />
              {saved ? "Saved" : "Save"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1"
              onClick={() => void deleteCurrentChat()}
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </Button>
            <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
              {backendReady ? "Semantic context" : "Local fallback context"}
            </span>
            <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
              {runtime?.available ? `LLM ${runtime.provider}` : "LLM offline"}
            </span>
            {backendSession && (
              <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                Memory {memoryLabel(memoryState)}
              </span>
            )}
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl px-6 py-8">
              {messages.length === 0 && !streaming && (
                <div className="text-muted-foreground">
                  <p className="text-lg font-medium text-foreground">Ask across your vault.</p>
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
                    onOpenSources={() => navigate({ to: "/sources" })}
                  />
                ))}
                {streaming && (
                  <div className="rounded-md border border-border bg-card p-4">
                    {streamStatus && (
                      <div className="mb-2 text-xs text-muted-foreground">{streamStatus}</div>
                    )}
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
          <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-border bg-card/20 p-4 xl:block">
            <div className="text-sm font-medium">Context used</div>
            <div className="mt-3 space-y-3">
              {latestCitations.length === 0 ? (
                <div className="text-sm text-muted-foreground">
                  Citations from the next answer will appear here.
                </div>
              ) : (
                latestCitations.map((citation, index) => {
                  const source = activeSources.find((item) => item.id === citation.sourceId);
                  return (
                    <div
                      key={`${citation.sourceId}-${index}`}
                      className="rounded-md border border-border bg-card p-3"
                    >
                      <div className="truncate text-sm font-medium">
                        {source?.title ?? "Source"}
                      </div>
                      <p className="mt-2 line-clamp-4 text-xs leading-5 text-muted-foreground">
                        {citation.snippet}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
            {latestWarnings.length > 0 && (
              <div className="mt-5 border-t border-border pt-4">
                <div className="text-sm font-medium">Runtime notes</div>
                <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
                  {latestWarnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}
          </aside>
        </div>

        <div className="border-t border-border bg-card/40 p-4">
          {dragActive && (
            <div className="mx-auto mb-2 max-w-3xl rounded-md border border-dashed border-primary/50 bg-primary/5 px-3 py-2 text-xs text-foreground">
              Drop files to attach them to this chat.
            </div>
          )}
          {lastError && (
            <div className="mx-auto mb-2 max-w-3xl rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
              {lastError}
            </div>
          )}
          {attachmentNotice && (
            <div className="mx-auto mb-2 max-w-3xl rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
              {attachmentNotice}
            </div>
          )}
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0"
              disabled={streaming || !backendReady}
              aria-label="Attach files"
              title="Attach files"
              onClick={() => void addAttachments()}
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
            <Button
              onClick={() => void send()}
              disabled={streaming || (!input.trim() && attachments.length === 0)}
              className="shrink-0"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
          {attachments.length > 0 && (
            <div className="mx-auto mt-2 flex max-w-3xl flex-wrap gap-1.5">
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
          <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-muted-foreground">
            Ctrl/Cmd Enter to send / {scope ? scope.name : "all vault context"} / memory{" "}
            {memoryLabel(memoryState)}
          </p>
        </div>
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

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
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
      pageNumber: citation.page_number,
      state: citation.state,
      title: citation.source_title,
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
  onOpenSources,
}: {
  msg: import("@/lib/mockStore").ChatMessage;
  clusters: Cluster[];
  sources: import("@/lib/mockStore").Source[];
  onUseful: (v: boolean) => void;
  onSaved: () => void;
  onRegenerate: () => void;
  onOpenSources: () => void;
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
            const title = s?.title ?? cit.title ?? "source";
            const stateText =
              cit.state === "source_deleted"
                ? "Source deleted"
                : cit.state === "source_reindexed"
                  ? "Source changed"
                  : null;
            return (
              <Popover key={i}>
                <PopoverTrigger asChild>
                  <button className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] hover:bg-accent">
                    <Quote className="h-3 w-3" /> {title}
                    {cit.pageNumber ? <span className="text-muted-foreground">p.{cit.pageNumber}</span> : null}
                    {stateText ? <span className="text-muted-foreground">({stateText})</span> : null}
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-80 text-xs">
                  <div className="mb-1 font-medium">{title}</div>
                  {cit.pageNumber ? (
                    <div className="mb-2 text-muted-foreground">Page {cit.pageNumber}</div>
                  ) : null}
                  {stateText ? (
                    <div className="mb-2 rounded-md border border-border bg-card px-2 py-1 text-muted-foreground">
                      {stateText}. Showing the excerpt saved when this answer was generated.
                    </div>
                  ) : null}
                  <p className="text-muted-foreground">{cit.snippet}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {s?.localPath && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => s.localPath && void window.cmlDesktop?.openPath(s.localPath)}
                      >
                        Open file
                      </Button>
                    )}
                    {s?.localPath && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => s.localPath && void window.cmlDesktop?.showItemInFolder(s.localPath)}
                      >
                        Show in folder
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={onOpenSources}
                    >
                      View sources
                    </Button>
                  </div>
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
