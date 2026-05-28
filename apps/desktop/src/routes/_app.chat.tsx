import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/mockStore";
import {
  createChatSession,
  listChatSessions,
  listVaults,
  type ChatSessionRecord,
  type VaultRecord,
} from "@/lib/backend";
import { MessageSquare, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/chat")({
  head: () => ({ meta: [{ title: "Chat" }] }),
  component: ChatIndex,
});

function ChatIndex() {
  const { chats, createChat } = useStore();
  const navigate = useNavigate();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [backendChats, setBackendChats] = useState<ChatSessionRecord[]>([]);
  const [backendReady, setBackendReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const vaults = await listVaults();
        const activeVault = vaults[0] ?? null;
        if (cancelled) return;
        setVault(activeVault);
        if (!activeVault) return;
        const sessions = await listChatSessions(activeVault.id);
        if (cancelled) return;
        setBackendChats(sessions);
        setBackendReady(true);
      } catch {
        if (!cancelled) setBackendReady(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  async function newChat() {
    if (backendReady && vault) {
      try {
        const session = await createChatSession({ vault_id: vault.id });
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      } catch {
        // Fall back to local mock chat below.
      }
    }
    const chat = createChat(null);
    navigate({ to: "/chat/$chatId", params: { chatId: chat.id } });
  }

  const visibleChats = backendReady ? backendChats : chats;

  return (
    <div className="flex h-full">
      <div className="w-64 border-r border-border bg-card/40 p-2">
        <Button
          variant="ghost"
          className="mb-2 w-full justify-start gap-2"
          onClick={newChat}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
        <div className="space-y-0.5">
          {visibleChats.map((c) => (
            <Link
              key={c.id}
              to="/chat/$chatId"
              params={{ chatId: c.id }}
              className="block truncate rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {c.title}
            </Link>
          ))}
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <div className="text-center text-muted-foreground">
          <MessageSquare className="mx-auto h-8 w-8 opacity-40" />
          <p className="mt-3 text-sm">Start a new chat or open one from the list.</p>
          <Button
            className="mt-4"
            onClick={newChat}
          >
            New chat
          </Button>
        </div>
      </div>
    </div>
  );
}
