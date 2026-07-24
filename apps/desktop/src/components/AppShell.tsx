import { Link, useNavigate, useRouterState, Outlet } from "@tanstack/react-router";
import {
  Boxes,
  CalendarDays,
  CheckSquare,
  Code2,
  FolderOpen,
  Globe,
  Home,
  Layers,
  Link2,
  MessageSquare,
  Search,
  Settings,
  UserRound,
  LockKeyhole,
  Menu,
  X,
} from "lucide-react";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { BrandLogo } from "@/components/BrandLogo";
import { useCallback, useEffect, useState } from "react";
import {
  getJobStatus,
  listClusters,
  listVaults,
  getUnlockStatus,
  useBackendHealth,
  type ClusterRecord,
  type JobQueueStatus,
  type VaultRecord,
  type UnlockStatusRead,
} from "@/lib/backend";
import { AppStatusAnnouncer, LockedState, StatusLabel } from "@/components/product/Feedback";
import { useVisiblePolling } from "@/lib/useVisiblePolling";

type NavItem = {
  to:
    | "/home"
    | "/chat"
    | "/search"
    | "/sources"
    | "/projects"
    | "/clusters"
    | "/map"
    | "/timeline"
    | "/bridge"
    | "/tasks"
    | "/settings";
  label: string;
  icon: typeof Home;
  separated?: boolean;
};

const nav: NavItem[] = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/search", label: "Search", icon: Search },
  { to: "/sources", label: "Sources", icon: Layers },
  { to: "/projects", label: "Projects", icon: Code2 },
  { to: "/clusters", label: "Clusters", icon: Boxes },
  { to: "/map", label: "Map", icon: Globe },
  { to: "/timeline", label: "Timeline", icon: CalendarDays },
  { to: "/bridge", label: "Bridge", icon: Link2 },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, separated: true },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function AppShell() {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const { open: openPalette, setOpen } = useCommandPalette();
  const backend = useBackendHealth();
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [recentClusters, setRecentClusters] = useState<ClusterRecord[]>([]);
  const [unlockStatus, setUnlockStatus] = useState<UnlockStatusRead | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await getJobStatus());
    } catch {
      setJobs(null);
    }
  }, []);
  const refreshLibrary = useCallback(async () => {
    try {
      const activeVault = (await listVaults())[0] ?? null;
      setVault(activeVault);
      if (!activeVault) {
        setRecentClusters([]);
        setUnlockStatus(null);
        return;
      }
      const [rows, currentUnlock] = await Promise.all([
        listClusters(activeVault.id),
        getUnlockStatus(),
      ]);
      setRecentClusters(rows.slice(0, 5));
      setUnlockStatus(currentUnlock);
    } catch {
      setRecentClusters([]);
    }
  }, []);

  useVisiblePolling(refreshJobs, 10_000, backend.status === "online");
  useVisiblePolling(refreshLibrary, 30_000, backend.status === "online");

  useEffect(() => {
    const onLockState = (event: Event) => {
      const detail = (event as CustomEvent<UnlockStatusRead>).detail;
      if (detail) setUnlockStatus(detail);
      void refreshLibrary();
    };
    window.addEventListener("vault:lock-state", onLockState);
    return () => {
      window.removeEventListener("vault:lock-state", onLockState);
    };
  }, [refreshLibrary]);

  useEffect(() => setSidebarOpen(false), [pathname]);

  const vaultPath = vault?.path ?? null;
  const sidebarClusters =
    recentClusters.length > 0
      ? recentClusters.map((cluster) => ({ id: cluster.id, name: cluster.name }))
      : [];

  const taskCount = (jobs?.queued ?? 0) + (jobs?.running ?? 0) + (jobs?.failed ?? 0);

  return (
    <div className="vault-shell flex-col text-foreground">
      <div className="vault-mobile-bar">
        <button
          type="button"
          className="vault-icon-button"
          onClick={() => setSidebarOpen((current) => !current)}
          aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={sidebarOpen}
        >
          {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
        </button>
        <BrandLogo className="h-6 w-auto" />
        <StatusLabel tone={backend.status === "online" ? "ready" : backend.status === "degraded" ? "warning" : "neutral"}>
          {backend.status === "online" ? "Ready" : backend.status === "checking" ? "Checking" : "Offline"}
        </StatusLabel>
      </div>
      <div className="flex min-h-0 flex-1">
        {sidebarOpen ? <button type="button" className="vault-sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} /> : null}
        <aside className={`vault-sidebar flex flex-col ${sidebarOpen ? "is-open" : ""}`}>
          <div className="px-4 pb-2 pt-4">
            <div className="panel-section-title mb-2">Vault</div>
            <button
              type="button"
              onClick={() => navigate({ to: "/settings", search: { section: "storage" } })}
              className="flex min-h-9 w-full items-start gap-2 rounded-md px-1 py-1.5 text-left text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] hover:text-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={vaultPath ? "Change library location" : "Choose a library"}
            >
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

          </nav>

          <div className="border-t border-[var(--border-default)] p-4">
            <Link to="/settings" search={{ section: "profile" }} className="flex min-h-10 items-center gap-3 rounded-md p-1 hover:bg-[var(--bg-hover)]">
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
            </Link>
          </div>
        </aside>

        <main className="content-area">
          {unlockStatus && !unlockStatus.ready && pathname !== "/settings" ? (
            <LockedState onOpenSettings={() => navigate({ to: "/settings", search: { section: "privacy" } })} />
          ) : (
            <Outlet key={unlockStatus?.ready === false ? "locked" : "ready"} />
          )}
        </main>
      </div>

      <footer className="vault-footer flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--border-default)] px-4 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${backend.status === "online" ? "bg-[var(--status-ready)]" : "bg-[var(--status-muted)]"}`} />
          <span className="min-w-0 break-all">{vaultPath ?? "No active library"}</span>
          <span>/</span>
          <span>
            {backend.status === "online"
              ? "Library service available"
              : backend.status === "degraded"
                ? "Library service needs attention"
                : backend.status === "checking"
                  ? "Checking library service"
                  : "Library service unavailable"}
          </span>
          <span>/</span>
          <span>{jobs?.running ? `${jobs.running} task running` : jobs?.queued ? `${jobs.queued} queued` : "Tasks idle"}</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <span>Ctrl/Cmd K commands</span>
          <span>/</span>
          <span>Ctrl/Cmd N new chat</span>
          <span>/</span>
          <LockKeyhole className="h-3 w-3" strokeWidth={1.5} />
          <span>All data stays on your device</span>
        </div>
      </footer>

      <CommandPalette open={openPalette} onOpenChange={setOpen} />
      <AppStatusAnnouncer
        message={
          backend.status === "offline"
            ? "Vault local service is offline."
            : backend.status === "degraded"
              ? "Vault local service needs attention."
              : null
        }
      />
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
