import { createFileRoute, Link } from "@tanstack/react-router";
import { useStore } from "@/lib/mockStore";
import { MessageSquare, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/chat")({
  head: () => ({ meta: [{ title: "Chat" }] }),
  component: ChatIndex,
});

function ChatIndex() {
  const { chats, createChat } = useStore();
  return (
    <div className="flex h-full">
      <div className="w-64 border-r border-border bg-card/40 p-2">
        <Button
          variant="ghost"
          className="mb-2 w-full justify-start gap-2"
          onClick={() => createChat(null)}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
        <div className="space-y-0.5">
          {chats.map((c) => (
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
            onClick={() => createChat(null)}
          >
            New chat
          </Button>
        </div>
      </div>
    </div>
  );
}