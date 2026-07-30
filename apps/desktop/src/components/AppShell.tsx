import { Link, useNavigate, useRouterState, Outlet } from "@tanstack/react-router";
import {
  Boxes,
  CalendarDays,
  CheckSquare,
  Code2,
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
  ArrowLeft,
  ArrowRight,
} from "lucide-react";
import { CommandPalette, useCommandPalette } from "@/components/CommandPalette";
import { BrandLogo } from "@/components/BrandLogo";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  getJobStatus,
  getModelRuntimeStatus,
  listChatSessions,
  listRecentChatGenerations,
  listClusterSuggestions,
  listClusters,
  listVaults,
  getUnlockStatus,
  lockVault,
  updateAppProfile,
  unlockVaultWithPassphrase,
  type ChatSessionRecord,
  useBackendHealth,
  type ClusterRecord,
  type JobQueueStatus,
  type ModelRuntimeStatus,
  type ClusterSuggestionRecord,
  type VaultRecord,
  type UnlockStatusRead,
} from "@/lib/backend";
import { AppStatusAnnouncer, LockedState, StatusLabel } from "@/components/product/Feedback";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import { normalizeTint } from "@/lib/recordAdapters";
import { displayPath } from "@/lib/displayPath";
import { Button } from "@/components/ui/button";
import { flushSync } from "react-dom";
import { useLocalImage } from "@/lib/useLocalImage";
import {
  normalizeDesktopProfile,
  profileDisplayName,
  subscribeDesktopProfile,
  type DesktopProfile,
} from "@/lib/profileState";
import { notify } from "@/components/product/Notifications";

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
  const [suggestedMoves, setSuggestedMoves] = useState<ClusterSuggestionRecord[]>([]);
  const [unlockStatus, setUnlockStatus] = useState<UnlockStatusRead | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [tour, setTour] = useState<DesktopSetupState["tour"] | null>(null);
  const [profile, setProfile] = useState<DesktopProfile>(() => normalizeDesktopProfile(null));
  const avatarSource = useLocalImage(profile.avatar_path);
  const contentRef = useRef<HTMLElement>(null);
  const recentChatGenerationsRef = useRef<{ vaultId: string; ids: Set<string> } | null>(null);
  const modelAvailabilityNoticeRef = useRef<"unknown" | "ready" | "unavailable">("unknown");

  useEffect(() => {
    let cancelled = false;
    async function loadTour() {
      const state = await window.cmlDesktop?.getSetupState?.();
      if (!cancelled) {
        const nextProfile = normalizeDesktopProfile(state?.profile);
        setProfile(nextProfile);
        void updateAppProfile(nextProfile.display_name).catch(() => undefined);
      }
      if (!cancelled && state?.phase === "complete") {
        setTour(state.tour);
      }
    }
    void loadTour();
    const unsubscribeProfile = subscribeDesktopProfile(setProfile);
    const restart = () => {
      const next = { status: "pending", step: 0, version: 1 } as const;
      setTour(next);
      void window.cmlDesktop?.updateSetupState?.({ tour: next });
    };
    window.addEventListener("vault:start-tour", restart);
    return () => {
      cancelled = true;
      unsubscribeProfile();
      window.removeEventListener("vault:start-tour", restart);
    };
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const nextJobs = await getJobStatus();
      setJobs(nextJobs);
      let runtime: ModelRuntimeStatus | null = null;
      try {
        runtime = await getModelRuntimeStatus();
      } catch {
        // Job state still remains useful when the runtime status probe fails.
      }
      if (!runtime) return;
      const blocked = nextJobs.blocked_local_model > 0;
      const unavailable = blocked && !runtime.available;
      const previous = modelAvailabilityNoticeRef.current;
      if (unavailable && previous !== "unavailable") {
        const recoveryActive = nextJobs.latest.some(
          (job) =>
            job.job_type === "model_runtime_recovery" &&
            ["queued", "running", "blocked_by_dependency", "deferred"].includes(job.status),
        );
        notify({
          title: "Local model unavailable",
          description:
            runtime.state === "starting" || recoveryActive
              ? "Document descriptions and clustering are paused while Vault restarts the model."
              : "Document descriptions and clustering are paused. Open Models to choose or restart a model.",
          tone: "error",
          actionLabel: "Open settings",
          onAction: () => navigate({ to: "/settings" }),
        });
      } else if (runtime.available && previous === "unavailable") {
        notify({
          title: "Local model restored",
          description: "Vault resumed document descriptions and clustering.",
          tone: "success",
          actionLabel: "View tasks",
          onAction: () => navigate({ to: "/tasks" }),
        });
      }
      modelAvailabilityNoticeRef.current = unavailable
        ? "unavailable"
        : runtime.available
          ? "ready"
          : previous;
    } catch {
      setJobs(null);
    }
  }, [navigate]);
  const refreshLibrary = useCallback(async () => {
    try {
      const currentUnlock = await getUnlockStatus();
      setUnlockStatus(currentUnlock);
      if (currentUnlock.secured_vault_count > 0 && !currentUnlock.ready) {
        setVault(null);
        setRecentClusters([]);
        setSavedChats([]);
        return;
      }
      const activeVault = (await listVaults())[0] ?? null;
      setVault(activeVault);
      if (!activeVault) {
        setRecentClusters([]);
        setSavedChats([]);
        setSuggestedMoves([]);
        return;
      }
      const [rows, chats, suggestions] = await Promise.allSettled([
        listClusters(activeVault.id, { limit: 3 }),
        listChatSessions(activeVault.id, { saved: true, limit: 3 }),
        listClusterSuggestions(activeVault.id, 8),
      ]);
      if (rows.status === "fulfilled") setRecentClusters(rows.value);
      if (chats.status === "fulfilled") setSavedChats(chats.value);
      if (suggestions.status === "fulfilled") {
        setSuggestedMoves(suggestions.value);
        const storageKey = `vault.clusterSuggestions.notified.${activeVault.id}`;
        const prior = new Set(readStoredStrings(storageKey));
        const keys = suggestions.value.map(
          (item) => `${item.source_id}:${item.suggested_cluster_id}`,
        );
        const unseen = keys.filter((key) => !prior.has(key));
        if (unseen.length > 0) {
          notify({
            title: `${unseen.length} new suggested ${unseen.length === 1 ? "move" : "moves"}`,
            description: "Review where these sources fit.",
            actionLabel: "Review",
            onAction: () => navigate({ to: "/clusters" }),
          });
        }
        window.localStorage.setItem(storageKey, JSON.stringify(keys.slice(0, 100)));
      }
    } catch {
      // Keep the last successful sidebar data during a transient refresh failure.
    }
  }, [navigate]);

  useVisiblePolling(refreshJobs, 10_000, backend.status === "online");
  useVisiblePolling(refreshLibrary, 30_000, backend.status === "online");
  useVisiblePolling(
    async () => {
      if (!vault) {
        recentChatGenerationsRef.current = null;
        return;
      }
      try {
        const result = await listRecentChatGenerations(vault.id);
        const previous = recentChatGenerationsRef.current;
        const nextIds = new Set(result.items.map((item) => item.id));
        if (!previous || previous.vaultId !== vault.id) {
          recentChatGenerationsRef.current = { vaultId: vault.id, ids: nextIds };
          return;
        }
        for (const generation of result.items) {
          if (
            previous.ids.has(generation.id) ||
            generation.state !== "completed" ||
            pathname === `/chat/${generation.session_id}`
          ) {
            continue;
          }
          notify({
            title: "Answer ready",
            description: generation.title,
            tone: "success",
            actionLabel: "Open chat",
            onAction: () =>
              navigate({
                to: "/chat/$chatId",
                params: { chatId: generation.session_id },
              }),
          });
        }
        recentChatGenerationsRef.current = { vaultId: vault.id, ids: nextIds };
      } catch {
        // A transient status failure must not create a false completion notice.
      }
    },
    3_000,
    backend.status === "online" && Boolean(vault),
  );

  useEffect(() => {
    const onLockState = (event: Event) => {
      const detail = (event as CustomEvent<UnlockStatusRead>).detail;
      if (detail && !detail.ready) {
        flushSync(() => {
          setUnlockStatus(detail);
          setVault(null);
          setRecentClusters([]);
          setSavedChats([]);
        });
      } else if (detail) {
        setUnlockStatus(detail);
      }
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

  const taskCount =
    (jobs?.queued ?? 0) +
    (jobs?.paused ?? 0) +
    (jobs?.running ?? 0) +
    (jobs?.failed ?? 0) +
    (jobs?.blocked_by_dependency ?? 0) +
    (jobs?.blocked_setup_required ?? 0) +
    (jobs?.deferred ?? 0) +
    (jobs?.manual_review ?? 0);
  const securityLockActive =
    Boolean(unlockStatus) &&
    (unlockStatus?.secured_vault_count ?? 0) > 0 &&
    unlockStatus?.ready === false;
  const securedVaultId =
    vault?.id ?? unlockStatus?.vault_id ?? unlockStatus?.secured_vault_ids?.[0] ?? null;

  const lockCurrentVault = useCallback(async () => {
    if (!securedVaultId || securityLockActive) return;
    try {
      const next = await lockVault(securedVaultId);
      setOpen(false);
      window.dispatchEvent(new CustomEvent("vault:lock-state", { detail: next }));
      navigate({ to: "/home" });
    } catch (error) {
      notify({
        title: "Library was not locked",
        description: error instanceof Error ? error.message : "Try again.",
        tone: "error",
      });
    }
  }, [navigate, securedVaultId, securityLockActive, setOpen]);

  const unlockCurrentVault = useCallback(async (passphrase: string) => {
    if (!securedVaultId) throw new Error("Vault could not find the secured library.");
    const next = await unlockVaultWithPassphrase({ vault_id: securedVaultId, passphrase });
    window.dispatchEvent(new CustomEvent("vault:lock-state", { detail: next }));
  }, [securedVaultId]);

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
        void lockCurrentVault();
      }
      if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        navigate({ to: "/settings" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lockCurrentVault, navigate, setOpen]);
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
          data-tour-id={`nav-${item.label.toLowerCase()}`}
          data-active={active}
          className="vault-nav-item flex items-center gap-3 px-2.5 transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
        >
          <Icon className="h-4 w-4" strokeWidth={1.5} />
          <span className="min-w-0 flex-1 break-words">{item.label}</span>
          {item.to === "/tasks" && taskCount > 0 ? (
            <span className="rounded bg-[var(--bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)]">
              {taskCount}
            </span>
          ) : item.to === "/clusters" && suggestedMoves.length > 0 ? (
            <span className="rounded bg-[var(--bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)]">
              {suggestedMoves.length}
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
        <BrandLogo className="vault-mobile-logo h-6 w-auto" />
        <div className="vault-mobile-status">
          <StatusLabel tone={backend.status === "online" ? "ready" : backend.status === "degraded" ? "warning" : "neutral"}>
            {backend.status === "online" ? "Ready" : backend.status === "checking" ? "Checking" : "Offline"}
          </StatusLabel>
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        {sidebarOpen ? <button type="button" className="vault-sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} /> : null}
        <aside className={`vault-sidebar flex flex-col ${sidebarOpen ? "is-open" : ""}`}>
          <div className="px-4 pb-2 pt-5">
            <Link
              to="/home"
              aria-label="Vault home"
              className="inline-flex rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <BrandLogo
                className="h-auto w-[132px] select-none"
              />
            </Link>
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="mt-4 flex h-8 w-full items-center gap-2 rounded-md border border-[var(--border-input)] bg-[var(--bg-input)] px-3 text-left text-[13px] text-[var(--text-placeholder)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-body)]"
              data-tour-id="search"
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

            {savedChats.length > 0 || sidebarClusters.length > 0 ? (
              <div className="mt-6 border-t border-[var(--border-default)] pt-5">
                <div className="panel-section-title px-2.5 pb-2">Recent</div>
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
            ) : null}

          </nav>

          <div className="border-t border-[var(--border-default)] p-4">
            <Link to="/settings" search={{ section: "profile" }} className="flex min-h-10 items-center gap-3 rounded-md p-1 hover:bg-[var(--bg-hover)]">
              <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-[var(--text-primary)] text-[var(--bg-card)]">
                {avatarSource ? (
                  <img src={avatarSource} alt="" className="h-full w-full object-cover" />
                ) : (
                  <UserRound className="h-4 w-4" strokeWidth={1.5} />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="break-words text-[13px] font-medium text-[var(--text-primary)]">
                  {profileDisplayName(profile)}
                </div>
                <div className="break-all text-[12px] text-[var(--text-muted)]">
                  {displayPath(vaultPath) || "No library selected"}
                </div>
              </div>
            </Link>
          </div>
        </aside>

        <main ref={contentRef} className="content-area focus:outline-none" tabIndex={-1}>
          {securityLockActive && pathname !== "/settings" ? (
            <LockedState
              onUnlock={unlockCurrentVault}
              onOpenRecovery={() => navigate({ to: "/settings", search: { section: "privacy" } })}
            />
          ) : (
            <Outlet key={securityLockActive ? "locked" : "ready"} />
          )}
        </main>
      </div>

      <CommandPalette
        open={openPalette}
        onOpenChange={setOpen}
        onLock={lockCurrentVault}
        lockAvailable={Boolean(securedVaultId) && !securityLockActive}
      />
      <AppStatusAnnouncer
        message={
          backend.status === "offline"
            ? "Vault local service is offline."
            : backend.status === "degraded"
              ? "Vault local service needs attention."
              : null
        }
      />
      {tour?.status === "pending" && !securityLockActive ? (
        <FirstUseTour
          step={tour.step}
          onStep={async (step) => {
            const next = { status: "pending", step, version: 1 } as const;
            setTour(next);
            await window.cmlDesktop?.updateSetupState?.({ tour: next });
          }}
          onFinish={async (status) => {
            const next = { status, step: tourSteps.length - 1, version: 1 } as const;
            setTour(next);
            await window.cmlDesktop?.updateSetupState?.({ tour: next });
          }}
        />
      ) : null}
    </div>
  );
}

function readStoredStrings(key: string): string[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key) ?? "[]");
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

const tourSteps = [
  {
    title: "A quick look around",
    body: "Vault keeps your sources, chats, and connections together. This short tour points out the five places you will use most.",
    target: null,
  },
  {
    title: "Find anything",
    body: "Open Search from here, or press Ctrl/Command + K. Search looks across your local library.",
    target: "search",
  },
  {
    title: "Add your material",
    body: "Sources is where you add documents, folders, links, and pasted notes. Vault indexes them locally.",
    target: "nav-sources",
  },
  {
    title: "Ask your library",
    body: "Chat answers from your selected sources and keeps citations beside each answer.",
    target: "nav-chat",
  },
  {
    title: "Keep ideas organized",
    body: "Clusters group related sources. Vault suggests groups, but you stay in control of every move.",
    target: "nav-clusters",
  },
  {
    title: "You are ready",
    body: "Settings holds models, storage, privacy, and health checks. You can restart this tour there at any time.",
    target: "nav-settings",
  },
] as const;

function FirstUseTour({
  step,
  onStep,
  onFinish,
}: {
  step: number;
  onStep: (step: number) => Promise<void>;
  onFinish: (status: "completed" | "skipped") => Promise<void>;
}) {
  const safeStep = Math.max(0, Math.min(tourSteps.length - 1, step));
  const item = tourSteps[safeStep];
  const dialogRef = useRef<HTMLDivElement>(null);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    const target = item.target
      ? document.querySelector<HTMLElement>(`[data-tour-id="${item.target}"]`)
      : null;
    target?.scrollIntoView({ block: "nearest" });
    const update = () => setTargetRect(target?.getBoundingClientRect() ?? null);
    update();
    window.addEventListener("resize", update);
    const observer = target ? new ResizeObserver(update) : null;
    if (target) observer?.observe(target);
    const frame = window.requestAnimationFrame(() => dialogRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
      observer?.disconnect();
    };
  }, [item.target]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void onFinish("skipped");
      if (event.key === "ArrowRight" && safeStep < tourSteps.length - 1) {
        event.preventDefault();
        void onStep(safeStep + 1);
      }
      if (event.key === "ArrowLeft" && safeStep > 0) {
        event.preventDefault();
        void onStep(safeStep - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFinish, onStep, safeStep]);

  const viewportWidth = typeof window === "undefined" ? 1280 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 800 : window.innerHeight;
  const dialogWidth = Math.min(328, Math.max(0, viewportWidth - 32));
  const dialogStyle =
    targetRect && item.target
      ? {
          left: Math.max(
            16,
            Math.min(viewportWidth - dialogWidth - 16, targetRect.right + 16),
          ),
          top: Math.max(16, Math.min(viewportHeight - 260, targetRect.top - 8)),
        }
      : undefined;

  return (
    <div className="fixed inset-0 z-[80]" role="presentation">
      <div className="absolute inset-0 bg-black/35" />
      {targetRect ? (
        <div
          className="pointer-events-none fixed rounded-md border-2 border-white bg-white/10 shadow-[0_0_0_4px_rgba(255,255,255,0.2)]"
          style={{
            left: targetRect.left - 4,
            top: targetRect.top - 4,
            width: targetRect.width + 8,
            height: targetRect.height + 8,
          }}
        />
      ) : null}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="vault-tour-title"
        tabIndex={-1}
        className={
          dialogStyle
            ? "fixed max-h-[calc(100vh-2rem)] w-[min(328px,calc(100vw-2rem))] overflow-y-auto rounded-md border border-border bg-card p-5 shadow-xl outline-none"
            : "fixed left-1/2 top-1/2 w-[min(390px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-md border border-border bg-card p-6 shadow-xl outline-none"
        }
        style={dialogStyle}
      >
        <div className="text-xs text-muted-foreground">
          {safeStep + 1} of {tourSteps.length}
        </div>
        <h2 id="vault-tour-title" className="mt-2 text-xl font-semibold">
          {item.title}
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.body}</p>
        <div className="mt-6 flex items-center justify-between gap-3">
          <Button variant="ghost" size="sm" onClick={() => void onFinish("skipped")}>
            Skip tour
          </Button>
          <div className="flex gap-2">
            {safeStep > 0 ? (
              <Button variant="outline" size="sm" onClick={() => void onStep(safeStep - 1)}>
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
            ) : null}
            <Button
              size="sm"
              onClick={() =>
                void (safeStep === tourSteps.length - 1
                  ? onFinish("completed")
                  : onStep(safeStep + 1))
              }
            >
              {safeStep === tourSteps.length - 1 ? "Done" : "Next"}
              {safeStep < tourSteps.length - 1 ? <ArrowRight className="h-4 w-4" /> : null}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function vaultName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}
