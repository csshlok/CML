import { Link, useNavigate, useRouterState, Outlet } from "@tanstack/react-router";
import {
  Activity,
  Briefcase,
  Home,
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
  UserRound,
  Asterisk,
  LockKeyhole,
} from "lucide-react";
import { useStore } from "@/lib/mockStore";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import {
  createChatSession,
  getJobStatus,
  listClusters,
  listChatSessions,
  listVaults,
  useBackendHealth,
  type ChatSessionRecord,
  type ClusterRecord,
  type JobQueueStatus,
} from "@/lib/backend";

const nav = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/search", label: "Mind", icon: Search },
  { to: "/sources", label: "Sources", icon: Files },
  { to: "/clusters", label: "Clusters", icon: Layers },
  { to: "/map", label: "Map", icon: Globe2 },
  { to: "/timeline", label: "Timeline", icon: Activity },
  { to: "/bridge", label: "Bridge", icon: Cable },
  { to: "/tasks", label: "Tasks", icon: Briefcase },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

export function AppShell() {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const { vaultPath, chats, clusters: mockClusters } = useStore();
  const { open: openPalette, setOpen } = useCommandPalette();
  const backend = useBackendHealth();
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [backendSavedChats, setBackendSavedChats] = useState<ChatSessionRecord[]>([]);
  const [recentClusters, setRecentClusters] = useState<ClusterRecord[]>([]);

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

  useEffect(() => {
    let cancelled = false;

    async function refreshJobs() {
      try {
        const status = await getJobStatus();
        if (!cancelled) setJobs(status);
      } catch {
        if (!cancelled) setJobs(null);
      }
    }

    void refreshJobs();
    const id = window.setInterval(refreshJobs, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function refreshClusters() {
      try {
        const vault = (await listVaults())[0] ?? null;
        if (!vault) {
          if (!cancelled) setRecentClusters([]);
          return;
        }
        const rows = await listClusters(vault.id);
        if (!cancelled) setRecentClusters(rows.slice(0, 5));
      } catch {
        if (!cancelled) setRecentClusters([]);
      }
    }

    void refreshClusters();
    const id = window.setInterval(refreshClusters, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function refreshSavedChats() {
      try {
        const vault = (await listVaults())[0] ?? null;
        if (!vault) {
          if (!cancelled) setBackendSavedChats([]);
          return;
        }
        const sessions = await listChatSessions(vault.id);
        if (!cancelled) setBackendSavedChats(sessions.filter((session) => session.saved).slice(0, 6));
      } catch {
        if (!cancelled) setBackendSavedChats([]);
      }
    }

    void refreshSavedChats();
    const id = window.setInterval(refreshSavedChats, 15000);
    window.addEventListener("vault:chats-changed", refreshSavedChats);

    return () => {
      cancelled = true;
      window.clearInterval(id);
      window.removeEventListener("vault:chats-changed", refreshSavedChats);
    };
  }, []);

  const savedChats =
    backend.status === "offline" || backendSavedChats.length === 0
      ? chats.filter((c) => c.saved).slice(0, 6)
      : backendSavedChats;
  const sidebarClusters =
    recentClusters.length > 0
      ? recentClusters.map((cluster) => ({ id: cluster.id, name: cluster.name }))
      : mockClusters.slice(0, 5).map((cluster) => ({ id: cluster.id, name: cluster.name }));

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

  const taskCount = (jobs?.queued ?? 0) + (jobs?.running ?? 0) + (jobs?.failed ?? 0);

  return (
    <div className="vault-shell flex h-screen w-full flex-col text-foreground">
      <div className="flex min-h-0 flex-1">
        <aside className="vault-sidebar flex w-[248px] flex-col border-r border-sidebar-border">
          <div className="px-5 py-5">
            <div className="flex items-center gap-3">
              <span className="vault-sidebar-mark flex h-7 w-7 items-center justify-center rounded-md">
                <Asterisk className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="text-lg font-semibold leading-5">Vault</div>
                <button className="flex w-full items-center gap-1.5 truncate text-left text-xs text-muted-foreground hover:text-foreground">
                  <FolderOpen className="h-3 w-3 shrink-0" />
                  <span className="truncate">{vaultPath ?? "Local memory"}</span>
                </button>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="mt-5 flex h-10 w-full items-center gap-2 rounded-md border border-sidebar-border bg-card px-3 text-left text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
            >
              <Search className="h-4 w-4" />
              <span className="min-w-0 flex-1">Search</span>
              <span className="text-[11px] opacity-60">Ctrl K</span>
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-4 pb-4">
            <div className="space-y-0.5">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = pathname.startsWith(item.to);
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    data-active={active}
                    className={
                      "vault-nav-item flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors " +
                      (active
                        ? ""
                        : "text-muted-foreground hover:bg-sidebar-accent/70 hover:text-foreground")
                    }
                    >
                      <Icon className="h-4 w-4" />
                      <span className="min-w-0 flex-1">{item.label}</span>
                      {item.to === "/tasks" && taskCount > 0 && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                          {taskCount}
                        </span>
                      )}
                    </Link>
                  );
                })}
            </div>

            {sidebarClusters.length > 0 && (
              <div className="mt-6 border-t border-sidebar-border pt-5">
                <div className="px-2.5 pb-2 text-xs font-medium text-muted-foreground">Recent</div>
                <div className="space-y-1">
                  {sidebarClusters.map((cluster) => (
                    <Link
                      key={cluster.id}
                      to="/clusters/$clusterId"
                      params={{ clusterId: cluster.id }}
                      className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-sidebar-accent/70 hover:text-foreground"
                    >
                      <span className="h-2.5 w-2.5 rounded-full bg-[var(--cluster-sage)]" />
                      <span className="truncate">{cluster.name}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {savedChats.length > 0 && (
              <div className="mt-6 border-t border-sidebar-border pt-5">
                <div className="px-2.5 pb-1.5 text-xs font-medium text-muted-foreground">
                  Saved chats
                </div>
                <div className="space-y-0.5">
                  {savedChats.map((c) => (
                    <Link
                      key={c.id}
                      to="/chat/$chatId"
                      params={{ chatId: c.id }}
                      className="block truncate rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-sidebar-accent/70 hover:text-foreground"
                    >
                      {c.title}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </nav>

          <div className="border-t border-sidebar-border p-4">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-2 text-muted-foreground"
              onClick={() => setOpen(true)}
            >
              <Command className="h-3.5 w-3.5" /> Command palette
              <span className="ml-auto text-[10px] opacity-60">Ctrl K</span>
            </Button>
            <button
              type="button"
              onClick={() => void newChat()}
              className="mt-1 flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm font-medium text-primary hover:bg-sidebar-accent/70"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
            <div className="mt-5 flex items-center gap-3 border-t border-sidebar-border pt-4">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-foreground text-background">
                <UserRound className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">Arjun Mehta</div>
                <div className="truncate text-xs text-muted-foreground">arjun@vault.local</div>
              </div>
            </div>
          </div>
        </aside>

        <main className="flex-1 min-w-0 overflow-hidden">
          <Outlet />
        </main>
      </div>

      <footer className="vault-footer flex h-7 shrink-0 items-center border-t border-border bg-background/80 px-4 text-[11px] text-muted-foreground">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="truncate">{vaultPath ?? "T:\\CML\\embedding-smoke"}</span>
          <span>/</span>
          <span>{backend.status === "online" ? "Ready" : backend.status === "checking" ? "Checking" : "Offline"}</span>
          <span>/</span>
          <span>{jobs?.running ? `${jobs.running} job running` : jobs?.queued ? `${jobs.queued} queued` : "Jobs idle"}</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <LockKeyhole className="h-3 w-3" />
          <span>All data stays on your device</span>
        </div>
      </footer>

      <CommandPalette open={openPalette} onOpenChange={setOpen} />
    </div>
  );
}
