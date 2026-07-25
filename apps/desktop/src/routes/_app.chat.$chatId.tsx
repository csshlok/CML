import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { type DragEvent, useEffect, useRef, useState } from "react";
import type { ChatMessage, Cluster, Source } from "@/lib/domain";
import {
  deleteChatSession,
  getModelRuntimeStatus,
  getChatSession,
  getChatTimeline,
  listChatSessions,
  listClusters,
  listSources,
  listVaults,
  streamChatContext,
  updateChatMessage,
  updateChatSession,
  type ChatContextResponse,
  type ChatMessageRecord,
  type ChatTimelineItem,
  type ChatSessionRecord,
  type ModelRuntimeStatus,
  type VaultRecord,
} from "@/lib/backend";
import {
  analysisModeLabel,
  describePartialFailure,
  statusToneForPartialFailure,
} from "@/lib/chat-presentation";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";
import { displayPath } from "@/lib/displayPath";
import { Button } from "@/components/ui/button";
import { ConfirmAction } from "@/components/product/Feedback";
import { notify } from "@/components/product/Notifications";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ClusterChip } from "@/components/ClusterChip";
import {
  detectProjectVisualizationRequest,
  ProjectGraphArtifact,
} from "@/components/ProjectGraphArtifact";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Bookmark,
  MoreHorizontal,
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
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [vault, setVaultRecord] = useState<VaultRecord | null>(null);
  const [backendClusters, setBackendClusters] = useState<Cluster[]>([]);
  const [backendSources, setBackendSources] = useState<Source[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [backendSessionId, setBackendSessionId] = useState<string | null>(null);
  const [backendSession, setBackendSession] = useState<ChatSessionRecord | null>(null);
  const [backendMessages, setBackendMessages] = useState<ChatMessage[]>([]);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [titleDraft, setTitleDraft] = useState("");
  const [memoryState, setMemoryState] = useState("idle");
  const [loadingSession, setLoadingSession] = useState(true);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [latestContextMeta, setLatestContextMeta] = useState<Pick<
    ChatContextResponse,
    "coverage_ledger" | "intent" | "runtime_state" | "warnings"
  > | null>(null);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [attachmentNotice, setAttachmentNotice] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<ModelRuntimeStatus | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [lastUserPrompt, setLastUserPrompt] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const consumedPendingPromptRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  async function loadBackendContext() {
    setLoadingSession(true);
    setBackendSession(null);
    setBackendSessionId(null);
    setBackendMessages([]);
    setLastError(null);
    setLatestContextMeta(null);
    try {
      const vaults = await listVaults();
      const activeVault = vaults[0] ?? null;
      setVaultRecord(activeVault);
      if (!activeVault) return;
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
        const timeline = await getChatTimeline(chatId).catch(() => null);
        setBackendSession(session);
        setBackendSessionId(session.id);
        setBackendMessages(timeline ? timeline.items.map(messageFromTimelineItem) : session.messages.map(messageFromRecord));
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
  }, [backendMessages.length, streamText]);

  useEffect(() => {
    if (!lastError) return;
    notify({ title: "Chat needs attention", description: lastError, tone: "error" });
  }, [lastError]);

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
    setTitleDraft(backendSession?.title ?? "New chat");
  }, [backendSession?.title]);

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

  if (loadingSession && !backendSession) {
    return <ChatLoadingSkeleton />;
  }

  if (!backendSession) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <p>Chat not found in the active vault.</p>
        <Button variant="outline" onClick={() => navigate({ to: "/chat" })}>
          Back to chats
        </Button>
      </div>
    );
  }

  const activeClusters = backendClusters;
  const activeSources = backendSources;
  const messages = backendMessages;
  const projectId = backendSession.scope_project_id ?? null;
  const scopeClusterId = backendSession.scope_cluster_id ?? null;
  const saved = backendSession.saved;
  const chatStatus = !backendReady
    ? { label: "Library unavailable", tone: "var(--status-error)", settings: false }
    : runtime && !runtime.available
      ? { label: "Chat model needs setup", tone: "var(--status-warn)", settings: true }
      : memoryState === "indexing"
        ? { label: "Saving conversation memory", tone: "var(--status-info)", settings: false }
        : { label: "Ready", tone: "var(--status-ready)", settings: false };

  const scope = scopeClusterId
    ? (activeClusters.find((c) => c.id === scopeClusterId) ?? null)
    : null;
  const suggestedPrompts = scope
    ? [
        `Summarize ${scope.name}.`,
        `What are the most important recent additions in ${scope.name}?`,
        `Which sources in ${scope.name} overlap or disagree?`,
      ]
    : [
        "What did I add recently?",
        activeClusters[0]
          ? `Summarize what I know about ${activeClusters[0].name}.`
          : "What are the main themes in my vault?",
        activeSources[0]
          ? `What are the key points in ${activeSources[0].title}?`
          : "Which sources in my vault are related?",
      ];
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const latestCoverage = latestContextMeta?.coverage_ledger ?? latestAssistant?.coverageLedger ?? null;
  const latestIntent = latestContextMeta?.intent ?? latestAssistant?.intent ?? "vault_question";
  const latestPartialFailure = String(latestCoverage?.partial_failure_mode ?? "none");
  const latestPartialFailureText = describePartialFailure(latestPartialFailure);
  const latestAnalysisLabel = analysisModeLabel(latestIntent, latestCoverage);
  const latestVisualizationRequest = projectId
    ? [...messages]
        .reverse()
        .filter((message) => message.role === "user")
        .map((message) => detectProjectVisualizationRequest(message.content))
        .find((request) => request !== null) ?? null
    : null;

  const setScope = async (val: string) => {
    const nextScope = val === "global" ? null : val;
    try {
      const updated = await updateChatSession(backendSession.id, {
        scope_cluster_id: nextScope,
      });
      setBackendSession(updated);
    } catch {
      setLastError("Could not update this chat's scope.");
    }
  };

  const toggleSaved = async () => {
    try {
      const updated = await updateChatSession(backendSession.id, {
        saved: !backendSession.saved,
      });
      setBackendSession(updated);
      window.dispatchEvent(new Event("vault:chats-changed"));
    } catch {
      setLastError("Could not update the saved state for this chat.");
    }
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

  const send = async (
    promptOverride?: string,
    attachmentOverride?: string[],
    analysisMode: "standard" | "expanded" | "complete" = "standard",
  ) => {
    const selectedAttachments = attachmentOverride ?? (promptOverride ? [] : attachments);
    const prompt = (promptOverride ?? input).trim() || (selectedAttachments.length > 0 ? "Read and store these attachments." : "");
    if ((!prompt && selectedAttachments.length === 0) || streaming) return;
    setLastUserPrompt(prompt);
    const attachmentNote =
      selectedAttachments.length > 0
        ? `\n\nAttachments:\n${selectedAttachments.map((path) => `- ${fileNameFromPath(path)}`).join("\n")}`
        : "";
    if (!backendReady || !vault || !backendSession) {
      setLastError("Open a library before sending a message.");
      return;
    }
    const userMsg = { id: crypto.randomUUID(), role: "user" as const, content: prompt + attachmentNote };
    setBackendMessages((current) => [...current, userMsg]);
    if (!promptOverride) {
      setInput("");
      setAttachments([]);
    }
    setStreaming(true);
    setStreamText("");
    setStreamStatus(
      analysisMode === "complete"
        ? "Scoring every indexed source in scope..."
        : analysisMode === "expanded"
          ? "Scoring sources in scope..."
          : "Routing message...",
    );
    setLatestContextMeta(null);
    setLastError(null);
    setAttachmentNotice(
      selectedAttachments.length > 0
        ? `Storing ${selectedAttachments.length} attachment${selectedAttachments.length === 1 ? "" : "s"} as vault source${selectedAttachments.length === 1 ? "" : "s"}...`
        : null,
    );
    setMemoryState("indexing");
    if (backendReady && vault) {
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      try {
        let streamedAnswer = "";
        let streamedMeta: Pick<ChatContextResponse, "clusters_used" | "citations" | "coverage_ledger" | "attachments_stored" | "intent" | "runtime_state" | "warnings"> = {
          clusters_used: [],
          citations: [],
          coverage_ledger: null,
          attachments_stored: [],
          intent: "general_chat",
          runtime_state: null,
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
            limit: analysisMode === "expanded" ? 12 : 6,
            expanded_analysis: analysisMode === "expanded",
            complete_analysis: analysisMode === "complete",
            attachments: selectedAttachments.map((path) => ({
              path,
              cluster_id: scope?.id ?? null,
            })),
          },
          {
            onMeta: (meta) => {
              streamedMeta = meta;
              setLatestContextMeta(meta);
              const coverage = meta.coverage_ledger;
              setStreamStatus(
                meta.intent === "general_chat"
                  ? "Using local LLM chat"
                  : analysisMode === "complete"
                    ? `Complete analysis: scored ${coverage?.sources_considered ?? 0} source${coverage?.sources_considered === 1 ? "" : "s"}; analyzing ${coverage?.sources_analyzed ?? 0}.`
                    : analysisMode === "expanded"
                    ? `Expanded analysis: considered ${coverage?.sources_considered ?? 0} source${coverage?.sources_considered === 1 ? "" : "s"}; analyzing ${coverage?.sources_analyzed ?? 0}.`
                    : coverage
                  ? `Considered ${coverage.sources_considered} source${coverage.sources_considered === 1 ? "" : "s"}; analyzing ${coverage.sources_analyzed}.`
                  : meta.citations.length > 0
                  ? `Using ${meta.citations.length} source${meta.citations.length === 1 ? "" : "s"}`
                  : "No matching source found yet",
              );
            },
            onToken: (text) => {
              streamedAnswer += text;
              setStreamStatus(
                analysisMode === "complete"
                  ? "Writing complete analysis..."
                  : analysisMode === "expanded"
                    ? "Writing expanded analysis..."
                    : "Writing answer...",
              );
              setStreamText(streamedAnswer);
            },
            onDone: (done) => {
              streamedDone = done;
              setLatestContextMeta({
                coverage_ledger: done.coverage_ledger ?? streamedMeta.coverage_ledger ?? null,
                intent: done.intent ?? streamedMeta.intent,
                runtime_state: done.runtime_state ?? streamedMeta.runtime_state,
                warnings: done.warnings ?? streamedMeta.warnings ?? [],
              });
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
          id: crypto.randomUUID(),
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
            relativePath: citation.relative_path,
            lineStart: citation.line_start,
            lineEnd: citation.line_end,
            symbol: citation.symbol,
            projectSnapshotId: citation.project_snapshot_id,
            indexedCommit: citation.indexed_commit,
          })),
          useful: null,
        } satisfies ChatMessage;
        if (response.session_id) {
          setBackendMessages((current) => [...current, assistantMessage]);
          try {
            const refreshed = await getChatSession(response.session_id);
            setBackendSession(refreshed);
            setBackendSessionId(refreshed.id);
            const timeline = await getChatTimeline(refreshed.id).catch(() => null);
            setBackendMessages(timeline ? timeline.items.map(messageFromTimelineItem) : refreshed.messages.map(messageFromRecord));
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
            const storedAttachments = streamedDone.attachments_stored ?? streamedMeta.attachments_stored ?? [];
            if (storedAttachments.length > 0) {
              setAttachmentNotice(
                `Stored ${storedAttachments.map((item) => item.title).join(", ")} in ${scope?.name ?? "the vault"}.`,
              );
            } else if (selectedAttachments.length > 0) {
              setAttachmentNotice(
                `Stored ${selectedAttachments.length} attachment${selectedAttachments.length === 1 ? "" : "s"} in ${scope?.name ?? "the vault"}.`,
              );
            }
          } catch {
            // Optimistic messages above remain usable until the next refresh.
          }
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
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            error instanceof Error
              ? `I could not retrieve local context: ${error.message}`
              : "I could not retrieve local context.",
          useful: null,
        } satisfies ChatMessage;
        setBackendMessages((current) => [...current, errorMessage]);
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
        }
        setStreaming(false);
        setStreamText("");
      }
      return;
    }
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
    const updated = await updateChatMessage(messageId, { useful: value });
    setBackendSession(updated);
    setBackendMessages(updated.messages.map(messageFromRecord));
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
      className="grid h-full grid-cols-1 overflow-y-auto lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[256px_minmax(0,1fr)] xl:overflow-hidden"
      onDragOver={(event) => {
        event.preventDefault();
        if (backendReady) setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(event) => void handleDrop(event)}
    >
      <aside className="border-b border-border bg-card/30 p-2 lg:border-b-0 lg:border-r lg:overflow-y-auto">
        <Button
          variant="ghost"
          className="mb-2 w-full justify-start gap-2"
          onClick={() => navigate({ to: "/chat" })}
        >
          <MessageSquare className="h-4 w-4" /> New chat
        </Button>
        <div className="max-h-48 space-y-0.5 overflow-y-auto lg:max-h-none">
          {backendChats.map((session) => (
            <Link
              key={session.id}
              to="/chat/$chatId"
              params={{ chatId: session.id }}
              className={
                "block break-words rounded-md px-2.5 py-1.5 text-sm transition-colors " +
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

      <div className="flex min-w-0 flex-col xl:min-h-0">
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
            <SelectTrigger className="h-8 w-full gap-2 text-xs sm:w-52">
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
          <div className="flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto">
            {lastError && (
              <Button variant="outline" size="sm" className="gap-1" onClick={retryLastUserMessage}>
                <RotateCcw className="h-4 w-4" />
                Retry
              </Button>
            )}
            {lastUserPrompt && !streaming && (
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="sm" className="gap-1" aria-label="More analysis options">
                    <MoreHorizontal className="h-4 w-4" />
                    Analyze again
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-72 p-2">
                  <button
                    type="button"
                    className="w-full rounded-md px-3 py-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => void send(lastUserPrompt, [], "expanded")}
                  >
                    <span className="block text-sm font-medium">Expanded analysis</span>
                    <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                      Search a wider set of likely relevant sources.
                    </span>
                  </button>
                  <button
                    type="button"
                    className="mt-1 w-full rounded-md px-3 py-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => void send(lastUserPrompt, [], "complete")}
                  >
                    <span className="block text-sm font-medium">Complete analysis</span>
                    <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                      Review every eligible source. This can take longer.
                    </span>
                  </button>
                </PopoverContent>
              </Popover>
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
            <ConfirmAction
              title={`Delete “${backendSession?.title ?? "this chat"}”?`}
              description="This removes the conversation and its saved messages from this Vault."
              confirmLabel="Delete chat"
              onConfirm={deleteCurrentChat}
            >
              <Button variant="ghost" size="sm" className="gap-1">
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
            </ConfirmAction>
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="h-2 w-2 rounded-full" style={{ background: chatStatus.tone }} />
              {chatStatus.settings ? (
                <Link to="/settings" search={{ section: "models" }} className="hover:text-foreground hover:underline">
                  {chatStatus.label}
                </Link>
              ) : chatStatus.label}
            </span>
          </div>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]">
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
                  <div className="mt-6 max-w-xl divide-y divide-border rounded-md border border-border bg-card">
                    {suggestedPrompts.map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        className="block w-full px-4 py-3 text-left text-sm leading-6 text-foreground transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                        onClick={() => setInput(prompt)}
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
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
                    onAskEvidence={(prompt) => setInput(prompt)}
                  />
                ))}
                {streaming && (
                  <div className="rounded-md bg-primary/5 p-4 ring-1 ring-primary/25" aria-live="polite">
                    {streamStatus && (
                      <div className="mb-2 flex items-center gap-2 break-words text-xs text-muted-foreground">
                        <span className="h-2 w-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
                        {streamStatus}
                      </div>
                    )}
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {streamText}
                      <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground/40 align-middle" />
                    </p>
                  </div>
                )}
                {projectId && latestVisualizationRequest && (
                  <ProjectGraphArtifact projectId={projectId} request={latestVisualizationRequest} />
                )}
              </div>
              <div ref={endRef} />
            </div>
          </div>
        </div>

        <div className="border-t border-border bg-card/40 p-4">
          {dragActive && (
            <div className="mx-auto mb-2 max-w-3xl break-words rounded-md border border-dashed border-primary/50 bg-primary/5 px-3 py-2 text-xs text-foreground">
              Drop files to attach them to this chat.
            </div>
          )}
          {lastError && (
            <div className="mx-auto mb-2 max-w-3xl break-words rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
              {lastError}
            </div>
          )}
          {backendReady && runtime && !runtime.available && (
            <div className="mx-auto mb-2 max-w-3xl break-words rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
              Vault can still find relevant sources, but it needs a local chat model to write a full answer. Set one up in Settings.
            </div>
          )}
          {latestPartialFailureText && !streaming && (
            <div
              className={
                "mx-auto mb-2 max-w-3xl rounded-md border px-3 py-2 text-xs " +
                (statusToneForPartialFailure(latestPartialFailure) === "critical"
                  ? "border-red-300 bg-red-50 text-red-950"
                  : statusToneForPartialFailure(latestPartialFailure) === "warning"
                    ? "border-amber-300 bg-amber-50 text-amber-950"
                    : "border-border bg-background text-muted-foreground")
              }
            >
              {latestPartialFailureText}
            </div>
          )}
          {attachmentNotice && (
            <div className="mx-auto mb-2 max-w-3xl break-words rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
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
              aria-label={scope ? `Ask ${scope.name}` : "Ask your vault"}
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
                  className="max-w-full break-all rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent"
                  onClick={() => removeAttachment(path)}
                  title="Remove attachment"
                >
                  {fileNameFromPath(path)} <span className="ml-1 text-foreground">Ready</span>
                </button>
              ))}
            </div>
          )}
          <p className="mx-auto mt-1.5 max-w-3xl break-words text-[11px] text-muted-foreground">
            Ctrl/Cmd Enter to send / {scope ? scope.name : "all vault context"} / {latestAnalysisLabel.toLowerCase()} / memory{" "}
            {memoryLabel(memoryState)}
          </p>
        </div>
      </div>
    </div>
  );
}

function ChatLoadingSkeleton() {
  return (
    <div className="grid h-full grid-cols-[240px_minmax(0,1fr)] overflow-hidden" aria-label="Loading chat">
      <aside className="border-r border-border bg-card/30 p-4">
        <div className="h-8 w-28 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
        <div className="mt-5 space-y-3">
          {[72, 88, 64, 80].map((width) => (
            <div
              key={width}
              className="h-5 animate-pulse rounded bg-muted motion-reduce:animate-none"
              style={{ width: `${width}%` }}
            />
          ))}
        </div>
      </aside>
      <div className="min-w-0">
        <div className="flex h-14 items-center border-b border-border px-6">
          <div className="h-5 w-48 animate-pulse rounded bg-muted motion-reduce:animate-none" />
        </div>
        <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
          <div className="ml-auto h-16 w-2/3 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
          <div className="h-32 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
          <div className="ml-auto h-12 w-1/2 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
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

function messageFromRecord(record: ChatMessageRecord): ChatMessage {
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
      relativePath: citation.relative_path,
      lineStart: citation.line_start,
      lineEnd: citation.line_end,
      symbol: citation.symbol,
      projectSnapshotId: citation.project_snapshot_id,
      indexedCommit: citation.indexed_commit,
    })),
    useful: record.useful,
    saved: record.saved,
    warnings: record.warnings,
  };
}

function messageFromTimelineItem(item: ChatTimelineItem): ChatMessage {
  if (item.message_type === "retriable_generation") {
    return {
      id: item.id,
      role: "retriable",
      prompt: item.prompt,
      content: "Vault was interrupted while answering this prompt. The partial answer was not saved.",
    };
  }
  return messageFromRecord(item);
}

function Message({
  msg,
  clusters,
  sources,
  onUseful,
  onSaved,
  onRegenerate,
  onOpenSources,
  onAskEvidence,
}: {
  msg: ChatMessage;
  clusters: Cluster[];
  sources: Source[];
  onUseful: (v: boolean) => void;
  onSaved: () => void;
  onRegenerate: () => void;
  onOpenSources: () => void;
  onAskEvidence: (prompt: string) => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] break-words rounded-md bg-accent px-3.5 py-2.5 text-sm">
        {msg.content}
      </div>
    );
  }
  if (msg.role === "retriable") {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
        <div className="font-medium">Interrupted answer</div>
        <p className="mt-1 break-words text-amber-900">{msg.content}</p>
        {msg.prompt ? (
          <p className="mt-2 break-words rounded border border-amber-200 bg-white/60 px-2 py-1 text-xs text-amber-900">
            {msg.prompt}
          </p>
        ) : null}
        <Button variant="outline" size="sm" className="mt-3 h-8" onClick={onRegenerate}>
          <RotateCcw className="mr-1 h-3.5 w-3.5" />
          Retry
        </Button>
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
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{msg.content}</p>
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
                  <button
                    type="button"
                    data-compound-trigger
                    className="inline-flex min-h-8 max-w-full items-center gap-1 rounded-full border border-border bg-background px-2 text-[11px] hover:bg-accent"
                  >
                    <Quote className="h-3 w-3" /> {title}
                    {cit.pageNumber ? <span className="text-muted-foreground">p.{cit.pageNumber}</span> : null}
                    {stateText ? <span className="text-muted-foreground">({stateText})</span> : null}
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-80 max-w-[calc(100vw-2rem)] text-xs">
                  <div className="mb-1 break-words font-medium">{title}</div>
                  {cit.relativePath && <div className="mb-2 break-all font-mono text-[11px] text-muted-foreground">{displayPath(cit.relativePath)}{cit.lineStart ? `:${cit.lineStart}${cit.lineEnd && cit.lineEnd !== cit.lineStart ? `-${cit.lineEnd}` : ""}` : ""}</div>}
                  {cit.symbol && <div className="mb-2 text-muted-foreground">Symbol: <span className="font-mono text-foreground">{cit.symbol}</span></div>}
                  {(cit.projectSnapshotId || cit.indexedCommit) && <div className="mb-2 text-muted-foreground">Indexed {cit.indexedCommit ? `at ${cit.indexedCommit.slice(0, 8)}` : "snapshot"}{cit.projectSnapshotId ? ` · ${cit.projectSnapshotId.slice(-8)}` : ""}</div>}
                  {cit.pageNumber ? (
                    <div className="mb-2 text-muted-foreground">Page {cit.pageNumber}</div>
                  ) : null}
                  {stateText ? (
                    <div className="mb-2 break-words rounded-md border border-border bg-card px-2 py-1 text-muted-foreground">
                      {stateText}. Showing the excerpt saved when this answer was generated.
                    </div>
                  ) : null}
                  <p className="break-words text-muted-foreground">{cit.snippet}</p>
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
                    {cit.relativePath && (
                      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => void window.cmlDesktop?.copyText(`${cit.relativePath}${cit.lineStart ? `:${cit.lineStart}` : ""}`)}>Copy path</Button>
                    )}
                    {cit.relativePath && (
                      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => onAskEvidence(`Explain ${cit.symbol ? `${cit.symbol} in ` : "the evidence in "}${cit.relativePath}${cit.lineStart ? ` around line ${cit.lineStart}` : ""}.`)}>Ask about this</Button>
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
      <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-border pt-2 text-xs text-muted-foreground">
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
