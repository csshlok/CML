import { Link, useNavigate, useRouterState, Outlet } from "@tanstack/react-router";
import {
  MessageSquare,
  Layers,
  Files,
  Globe2,
  Search,
  Cable,
  Settings as SettingsIcon,
  Plus,
  FolderOpen,
  Command,
} from "lucide-react";
import { useStore } from "@/lib/mockStore";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { Button } from "@/components/ui/button";
import { useEffect } from "react";
import { createChatSession, listVaults, useBackendHealth } from "@/lib/backend";

const nav = [
  { to: "/search", label: "Mind", icon: Search },
  { to: "/sources", label: "Sources", icon: Files },
  { to: "/map", label: "Map", icon: Globe2 },
  { to: "/clusters", label: "Clusters", icon: Layers },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/bridge", label: "Bridge", icon: Cable },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

export function AppShell() {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const { vaultPath, chats, isIndexing, indexingProgress } = useStore();
  const { open: openPalette, setOpen } = useCommandPalette();
  const backend = useBackendHealth();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (mod && e.key.toLowerCase() === "n") {
        e.preventDefault();
        if (e.shiftKey) {
          navigate({ to: "/clusters" });
        } else {
          navigate({ to: "/chat" });
        }
      }
      if (mod && e.key.toLowerCase() === "l") {
        e.preventDefault();
        navigate({ to: "/sources" });
      }
      if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        navigate({ to: "/settings" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, setOpen]);

  const savedChats = chats.filter((c) => c.saved).slice(0, 6);

  async function newChat() {
    try {
      const vault = (await listVaults())[0];
      if (vault) {
        const session = await createChatSession({ vault_id: vault.id, title: "New chat" });
        navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
        return;
      }
    } catch {
      // The Chat index still offers local fallback when the backend is not available.
    }
    navigate({ to: "/chat" });
  }

  return (
    <div className="flex h-screen w-full flex-col bg-background text-foreground">
      <div className="flex flex-1 min-h-0">
        <aside className="flex w-64 flex-col border-r border-border bg-sidebar">
          <div className="border-b border-sidebar-border px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Vault
            </div>
            <button className="mt-1 flex w-full items-center gap-2 truncate text-left text-sm font-medium">
              <FolderOpen className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="truncate">{vaultPath ?? "Local memory"}</span>
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-2 py-3">
            <div className="space-y-0.5">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = pathname.startsWith(item.to);
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={
                      "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors " +
                      (active
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground")
                    }
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                );
              })}
            </div>

            {savedChats.length > 0 && (
              <div className="mt-6">
                <div className="px-2.5 pb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                  Saved chats
                </div>
                <div className="space-y-0.5">
                  {savedChats.map((c) => (
                    <Link
                      key={c.id}
                      to="/chat/$chatId"
                      params={{ chatId: c.id }}
                      className="block truncate rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                    >
                      {c.title}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </nav>

          <div className="border-t border-sidebar-border p-2">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-2 text-muted-foreground"
              onClick={() => setOpen(true)}
            >
              <Command className="h-3.5 w-3.5" /> Command palette
              <span className="ml-auto text-[10px] opacity-60">Ctrl/Cmd K</span>
            </Button>
            <button
              type="button"
              onClick={() => void newChat()}
              className="mt-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm font-medium text-primary hover:bg-sidebar-accent/60"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
          </div>
        </aside>

        <main className="flex-1 min-w-0 overflow-hidden">
          <Outlet />
        </main>
      </div>

      <footer className="flex h-7 items-center gap-4 border-t border-border bg-card px-3 text-[11px] text-muted-foreground">
        <span>{vaultPath ?? "No vault"}</span>
        <span className="opacity-50">/</span>
        {isIndexing ? (
          <span>Indexing... {Math.round(indexingProgress * 100)}%</span>
        ) : (
          <span>Idle</span>
        )}
        <span className="ml-auto opacity-60">Ctrl/Cmd K commands / Ctrl/Cmd N new chat</span>
        <span
          className={
            "rounded-full px-2 py-0.5 " +
            (backend.status === "online"
              ? "bg-[var(--status-ready)]/15 text-foreground"
              : backend.status === "checking"
                ? "bg-muted text-muted-foreground"
                : "bg-[var(--status-issue)]/15 text-foreground")
          }
          title={backend.url}
        >
          Backend {backend.status}
        </span>
      </footer>

      <CommandPalette open={openPalette} onOpenChange={setOpen} />
    </div>
  );
}
