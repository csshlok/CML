import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useStore, streamMockReply, newId, Cluster } from "@/lib/mockStore";
import { Button } from "@/components/ui/button";
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
  RefreshCw,
  Paperclip,
  Quote,
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
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.length, streamText]);

  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Chat not found.
      </div>
    );
  }

  const scope = chat.scopeClusterId
    ? clusters.find((c) => c.id === chat.scopeClusterId) ?? null
    : null;

  const setScope = (val: string) => {
    // recreate chat with new scope (simple mock)
    const c = createChat(val === "global" ? null : val);
    navigate({ to: "/chat/$chatId", params: { chatId: c.id } });
  };

  const send = async () => {
    if (!input.trim()) return;
    const userMsg = { id: newId(), role: "user" as const, content: input.trim() };
    appendMessage(chat.id, userMsg);
    const prompt = input.trim();
    setInput("");
    setStreaming(true);
    setStreamText("");
    let full = "";
    for await (const chunk of streamMockReply(prompt, scope)) {
      full += chunk;
      setStreamText(full);
    }
    // pick clusters used
    const usedClusters = scope
      ? [{ clusterId: scope.id, reason: "selected scope" }]
      : clusters.slice(0, 2).map((c, i) => ({
          clusterId: c.id,
          reason: i === 0 ? "style" : "facts",
        }));
    const usedSources = sources
      .filter((s) =>
        usedClusters.some((u) => u.clusterId === s.clusterId) && s.state === "indexed",
      )
      .slice(0, 3)
      .map((s) => ({
        sourceId: s.id,
        snippet: s.preview.slice(0, 80) + "…",
      }));
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

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border bg-card/40 px-6 py-3">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Scope</div>
        <Select
          value={chat.scopeClusterId ?? "global"}
          onValueChange={setScope}
        >
          <SelectTrigger className="h-8 w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="global">Global — all clusters</SelectItem>
            {clusters.map((c) => (
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
            onClick={() => saveChat(chat.id, !chat.saved)}
          >
            <Bookmark className={"h-4 w-4 " + (chat.saved ? "fill-current" : "")} />
            {chat.saved ? "Saved" : "Save"}
          </Button>
          <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
            Local only
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-8">
          {chat.messages.length === 0 && !streaming && (
            <div className="text-center text-muted-foreground">
              <p className="font-serif text-2xl text-foreground">
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
            {chat.messages.map((m) => (
              <Message
                key={m.id}
                msg={m}
                clusters={clusters}
                sources={sources}
                onUseful={(v) => setMessageUseful(chat.id, m.id, v)}
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
          <Button variant="ghost" size="icon" className="shrink-0">
            <Paperclip className="h-4 w-4" />
          </Button>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={scope ? `Ask ${scope.name}…` : "Ask your vault…"}
            rows={2}
            className="resize-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button onClick={send} disabled={streaming || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mx-auto mt-1.5 max-w-2xl text-[11px] text-muted-foreground">
          Ctrl/Cmd Enter to send · all processing local
        </p>
      </div>
    </div>
  );
}

function Message({
  msg,
  clusters,
  sources,
  onUseful,
}: {
  msg: import("@/lib/mockStore").ChatMessage;
  clusters: Cluster[];
  sources: import("@/lib/mockStore").Source[];
  onUseful: (v: boolean) => void;
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
                {i < msg.clustersUsed!.length - 1 && <span>·</span>}
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
        <Button variant="ghost" size="sm" className="h-7 px-2">
          <Bookmark className="mr-1 h-3.5 w-3.5" /> Save
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
        <Button variant="ghost" size="sm" className="h-7 px-2">
          <RefreshCw className="mr-1 h-3.5 w-3.5" /> Regenerate
        </Button>
      </div>
    </div>
  );
}
