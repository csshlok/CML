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
  Menu,
  X,
} from "lucide-react";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { BrandLogo } from "@/components/BrandLogo";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  getJobStatus,
  listChatSessions,
  listClusters,
  listVaults,
  getUnlockStatus,
  type ChatSessionRecord,
  useBackendHealth,
  type ClusterRecord,
  type JobQueueStatus,
  type VaultRecord,
  type UnlockStatusRead,
} from "@/lib/backend";
import { AppStatusAnnouncer, LockedState, StatusLabel } from "@/components/product/Feedback";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import { normalizeTint } from "@/lib/recordAdapters";

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
};

const primaryNav: NavItem[] = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/sources", label: "Sources", icon: Layers },
  { to: "/clusters", label: "Clusters", icon: Boxes },
  { to: "/search", label: "Search", icon: Search },
  { to: "/projects", label: "Projects", icon: Code2 },
  { to: "/map", label: "Map", icon: Globe },
] as const;

const secondaryNav: NavItem[] = [
  { to: "/timeline", label: "Timeline", icon: CalendarDays },
  { to: "/bridge", label: "Bridge", icon: Link2 },
  { to: "/tasks", label: "Tasks", icon: CheckSquare },
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
  const [savedChats, setSavedChats] = useState<ChatSessionRecord[]>([]);
  const [unlockStatus, setUnlockStatus] = useState<UnlockStatusRead | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const contentRef = useRef<HTMLElement>(null);

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
        setSavedChats([]);
        setUnlockStatus(null);
        return;
      }
      const [rows, chats, currentUnlock] = await Promise.all([
        listClusters(activeVault.id),
        listChatSessions(activeVault.id, { limit: 50 }),
        getUnlockStatus(),
      ]);
      setRecentClusters(rows.slice(0, 5));
      setSavedChats(chats.filter((chat) => chat.saved).slice(0, 5));
      setUnlockStatus(currentUnlock);
    } catch {
      setRecentClusters([]);
      setSavedChats([]);
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
    window.addEventListener("vault:chats-changed", refreshLibrary);
    return () => {
      window.removeEventListener("vault:lock-state", onLockState);
      window.removeEventListener("vault:chats-changed", refreshLibrary);
    };
  }, [refreshLibrary]);

  useEffect(() => setSidebarOpen(false), [pathname]);

  const vaultPath = vault?.path ?? null;
  const sidebarClusters =
    recentClusters.length > 0
      ? recentClusters.map((cluster) => ({
          id: cluster.id,
          name: cluster.name,
          tint: normalizeTint(cluster.color),
        }))
      : [];

  const taskCount = (jobs?.queued ?? 0) + (jobs?.running ?? 0) + (jobs?.failed ?? 0);
  const activeTaskCount = (jobs?.queued ?? 0) + (jobs?.running ?? 0);
  const currentPage =
    [...primaryNav, ...secondaryNav].find((item) => pathname.startsWith(item.to))?.label ?? "Vault";
  const currentVaultName = vault?.name ?? (vaultPath ? vaultName(vaultPath) : "Vault");

  useEffect(() => {
    document.title = `${currentVaultName} — ${currentPage}`;
  }, [currentPage, currentVaultName]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => contentRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [pathname]);

  function handleNavKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const links = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-vault-nav]"));
    const currentIndex = links.indexOf(document.activeElement as HTMLElement);
    if (currentIndex < 0) return;
    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    links[(currentIndex + direction + links.length) % links.length]?.focus();
  }

  function renderNavItems(items: readonly NavItem[]) {
    return items.map((item) => {
      const Icon = item.icon;
      const active = pathname.startsWith(item.to);
      return (
        <Link
          key={item.to}
          to={item.to}
          data-vault-nav
          data-active={active}
          className="vault-nav-item flex items-center gap-3 px-2.5 transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
        >
          <Icon className="h-4 w-4" strokeWidth={1.5} />
          <span className="min-w-0 flex-1 break-words">{item.label}</span>
          {item.to === "/tasks" && taskCount > 0 ? (
            <span className="rounded bg-[var(--bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)]">
              {taskCount}
            </span>
          ) : null}
        </Link>
      );
    });
  }

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

          <nav
            className="flex-1 overflow-y-auto px-4 pb-4 pt-2"
            aria-label="Vault navigation"
            onKeyDown={handleNavKeyDown}
          >
            <div className="space-y-1">
              {renderNavItems(primaryNav)}
            </div>
            <div className="mt-5 border-t border-[var(--border-default)] pt-4">
              <div className="panel-section-title px-2.5 pb-2">More</div>
              <div className="space-y-1">{renderNavItems(secondaryNav)}</div>
            </div>

            {savedChats.length > 0 ? (
              <div className="mt-6 border-t border-[var(--border-default)] pt-5">
                <div className="panel-section-title px-2.5 pb-2">Saved chats</div>
                <div className="space-y-1">
                  {savedChats.map((chat) => (
                    <Link
                      key={chat.id}
                      to="/chat/$chatId"
                      params={{ chatId: chat.id }}
                      className="flex min-h-7 items-start gap-2 rounded-md px-2.5 py-1 text-[13px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                    >
                      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.5} />
                      <span className="min-w-0 flex-1 truncate">{chat.title}</span>
                    </Link>
                  ))}
                </div>
              </div>
            ) : null}

            {sidebarClusters.length > 0 && (
              <div className="mt-6 border-t border-[var(--border-default)] pt-5">
                <div className="panel-section-title px-2.5 pb-2">Recent</div>
                <div className="space-y-1">
                  {sidebarClusters.map((cluster) => (
                    <Link
                      key={cluster.id}
                      to="/clusters/$clusterId"
                      params={{ clusterId: cluster.id }}
                      className="flex min-h-7 items-start gap-2 rounded-md px-2.5 py-1 text-[13px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                    >
                      <span
                        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                        style={{ background: `var(--cluster-${cluster.tint})` }}
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

        <main ref={contentRef} className="content-area focus:outline-none" tabIndex={-1}>
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
          <span className="min-w-0 truncate">{vault?.name ?? (vaultPath ? vaultName(vaultPath) : "No active library")}</span>
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
          <span>{activeTaskCount > 0 ? `${activeTaskCount} active task${activeTaskCount === 1 ? "" : "s"}` : "No active tasks"}</span>
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
