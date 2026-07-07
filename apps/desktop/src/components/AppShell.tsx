import { Link, useNavigate, useRouterState, Outlet } from "@tanstack/react-router";
import {
  Activity,
  Boxes,
  CalendarDays,
  CheckSquare,
  ChevronDown,
  FolderOpen,
  Globe,
  Home,
  Layers,
  LayoutGrid,
  Link2,
  MessageSquare,
  Search,
  Settings,
  Plus,
  UserRound,
  LockKeyhole,
} from "lucide-react";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { QuickCaptureDialog } from "@/components/QuickCaptureDialog";
import { BrandLogo } from "@/components/BrandLogo";
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
  type VaultRecord,
} from "@/lib/backend";
import { useQuickCaptureDialog } from "@/lib/quick-capture-store";

type NavItem = {
  to:
    | "/home"
    | "/chat"
    | "/search"
    | "/sources"
    | "/clusters"
    | "/map"
    | "/timeline"
    | "/bridge"
    | "/tasks"
    | "/activity"
    | "/settings";
  label: string;
  icon: typeof Home;
  separated?: boolean;
};

const nav: NavItem[] = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/search", label: "Mind", icon: LayoutGrid },
  { to: "/sources", label: "Sources", icon: Layers },
  { to: "/clusters", label: "Clusters", icon: Boxes },
  { to: "/map", label: "Map", icon: Globe },
  { to: "/timeline", label: "Timeline", icon: CalendarDays },
  { to: "/bridge", label: "Bridge", icon: Link2 },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, separated: true },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function AppShell() {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const { open: openPalette, setOpen } = useCommandPalette();
  const { openDialog: openQuickCapture } = useQuickCaptureDialog();
  const backend = useBackendHealth();
  const [vault, setVault] = useState<VaultRecord | null>(null);
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
      if (mod && e.shiftKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        openQuickCapture({ mode: "artifact", seedFromClipboard: true });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, openQuickCapture, setOpen]);

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
          if (!cancelled) setVault(null);
          if (!cancelled) setRecentClusters([]);
          return;
        }
        if (!cancelled) setVault(vault);
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

  const vaultPath = vault?.path ?? null;
  const savedChats = backendSavedChats;
  const sidebarClusters =
    recentClusters.length > 0
      ? recentClusters.map((cluster) => ({ id: cluster.id, name: cluster.name }))
      : [];

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
    <div className="vault-shell flex-col text-foreground">
      <div className="flex min-h-0 flex-1">
        <aside className="vault-sidebar flex flex-col">
          <div className="px-4 pb-2 pt-4">
            <div className="panel-section-title mb-2">Vault</div>
            <button className="flex w-full items-start gap-2 text-left text-[12px] text-[var(--text-primary)] hover:text-[var(--primary)]">
              <FolderOpen className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} />
              <span className="min-w-0 flex-1 break-all">{vaultPath ?? "Choose library"}</span>
            </button>
            <div className="mt-4">
              <BrandLogo className="h-7 w-auto select-none" />
            </div>
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="mt-4 flex h-8 w-full items-center gap-2 rounded-md border border-[var(--border-input)] bg-[var(--bg-input)] px-3 text-left text-[13px] text-[var(--text-placeholder)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-body)]"
            >
              <Search className="h-3.5 w-3.5" strokeWidth={1.5} />
              <span className="min-w-0 flex-1">Search</span>
              <span className="text-[11px] text-[var(--text-subtle)]">⌘K</span>
            </button>
            <button
              type="button"
              onClick={() => openQuickCapture({ mode: "artifact", seedFromClipboard: true })}
              className="mt-2 flex h-8 w-full items-center gap-2 rounded-md border border-[var(--border-input)] bg-[var(--bg-card)] px-3 text-left text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
              <span className="min-w-0 flex-1">Quick save to Vault</span>
              <span className="text-[11px] text-[var(--text-subtle)]">Ctrl/Cmd Shift S</span>
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-4 pb-4 pt-2">
            <div className="space-y-1">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = pathname.startsWith(item.to);
                return (
                  <div key={item.to} className={item.separated ? "mt-4 border-t border-[var(--border-default)] pt-4" : ""}>
                    <Link
                      to={item.to}
                      data-active={active}
                      className="vault-nav-item flex items-center gap-3 px-2.5 transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                    >
                      <Icon className="h-4 w-4" strokeWidth={1.5} />
                      <span className="min-w-0 flex-1 break-words">{item.label}</span>
                      {item.to === "/tasks" && taskCount > 0 && (
                        <span className="rounded bg-[var(--bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)]">
                          {taskCount}
                        </span>
                      )}
                    </Link>
                  </div>
                );
              })}
            </div>

            {sidebarClusters.length > 0 && (
              <div className="mt-6 border-t border-[var(--border-default)] pt-5">
                <div className="panel-section-title px-2.5 pb-2">Recent</div>
                <div className="space-y-1">
                  {sidebarClusters.map((cluster, index) => (
                    <Link
                      key={cluster.id}
                      to="/clusters/$clusterId"
                      params={{ clusterId: cluster.id }}
                      className="flex min-h-7 items-start gap-2 rounded-md px-2.5 py-1 text-[13px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                    >
                      <span
                        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                        style={{ background: clusterDot(index) }}
                      />
                      <span className="min-w-0 flex-1 break-words">{cluster.name}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {savedChats.length > 0 && pathname.startsWith("/chat") && (
              <div className="mt-6 border-t border-[var(--border-default)] pt-5">
                <div className="panel-section-title flex items-center justify-between px-2.5 pb-2">
                  <span>Saved chats</span>
                  <button type="button" onClick={() => void newChat()} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                    <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
                  </button>
                </div>
                <div className="space-y-1">
                  {savedChats.map((c) => (
                    <Link
                      key={c.id}
                      to="/chat/$chatId"
                      params={{ chatId: c.id }}
                      className="block break-words rounded-md px-2.5 py-1.5 text-[13px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                    >
                      {c.title}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </nav>

          <div className="border-t border-[var(--border-default)] p-4">
            <div className="flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--text-primary)] text-[var(--bg-card)]">
                <UserRound className="h-4 w-4" strokeWidth={1.5} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="break-words text-[13px] font-medium text-[var(--text-primary)]">
                  {vaultPath ? vaultName(vaultPath) : "Local profile"}
                </div>
                <div className="break-all text-[12px] text-[var(--text-muted)]">
                  {vaultPath ?? "No library selected"}
                </div>
              </div>
              <ChevronDown className="h-3.5 w-3.5 text-[var(--text-muted)]" strokeWidth={1.5} />
            </div>
          </div>
        </aside>

        <main className="content-area">
          <Outlet />
        </main>
      </div>

      <footer className="vault-footer flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--border-default)] px-4 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${backend.status === "online" ? "bg-[var(--status-ready)]" : "bg-[var(--status-muted)]"}`} />
          <span className="min-w-0 break-all">{vaultPath ?? "No active library"}</span>
          <span>/</span>
          <span>
            {backend.status === "online"
              ? "Backend online"
              : backend.status === "degraded"
                ? "Backend reachable"
                : backend.status === "checking"
                  ? "Checking backend"
                  : "Backend offline"}
          </span>
          <span>/</span>
          <span>{jobs?.running ? `${jobs.running} job running` : jobs?.queued ? `${jobs.queued} queued` : "Jobs idle"}</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <span>Ctrl/Cmd K commands</span>
          <span>/</span>
          <span>Ctrl/Cmd N new chat</span>
          <span>/</span>
          <span>Ctrl/Cmd Shift S quick save</span>
          <span>/</span>
          <LockKeyhole className="h-3 w-3" strokeWidth={1.5} />
          <span>All data stays on your device</span>
        </div>
      </footer>

      <CommandPalette open={openPalette} onOpenChange={setOpen} />
      <QuickCaptureDialog />
    </div>
  );
}

function vaultName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function clusterDot(index: number) {
  const colors = [
    "var(--cluster-sage)",
    "var(--cluster-terracotta)",
    "var(--cluster-sky)",
    "var(--cluster-lavender)",
    "var(--cluster-sand)",
  ];
  return colors[index % colors.length];
}
