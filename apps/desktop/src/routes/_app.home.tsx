import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  File,
  FileCode2,
  FileText,
  FolderKanban,
  Grid2X2,
  Image as ImageIcon,
  LayoutList,
  Link2,
  ListFilter,
  MessageSquare,
  Mic,
  Plus,
  RotateCcw,
  Send,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/WindowAware";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  ProductSection,
  ProductSectionHeader,
  ProductSectionStack,
} from "@/components/product/Layout";
import {
  countSources,
  createChatSession,
  decideClusterSuggestion,
  getJobStatus,
  listClusterSuggestions,
  listActivity,
  listChatSessions,
  listClusters,
  listProjects,
  listSources,
  listVaults,
  sourceCountsByCluster,
  sourceCountsByType,
  useBackendGeneration,
  type ActivityRecord,
  type ChatSessionRecord,
  type JobQueueStatus,
  type ClusterSuggestionRecord,
  type ProjectRecord,
  type SourceTypeCountRecord,
  type VaultRecord,
} from "@/lib/backend";
import type { Cluster, Source, SourceType } from "@/lib/domain";
import {
  DEFAULT_HOME_PREFERENCES,
  homePreferencesForPreset,
  moveHomeSection,
  readHomePreferences,
  writeHomePreferences,
  type HomePreferences,
  type HomePreset,
  type HomeSectionId,
  type HomeSort,
  type HomeTypeFilter,
} from "@/lib/homePreferences";
import { cn } from "@/lib/utils";
import { clusterFromRecord, sourceFromRecord } from "@/lib/recordAdapters";
import { useVisiblePolling } from "@/lib/useVisiblePolling";

export const Route = createFileRoute("/_app/home")({
  head: () => ({ meta: [{ title: "Home" }] }),
  component: HomeView,
});

const typeOptions: Array<{ value: HomeTypeFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "documents", label: "Documents" },
  { value: "notes", label: "Notes" },
  { value: "links", label: "Links" },
  { value: "media", label: "Media" },
  { value: "code", label: "Code" },
];

const sortOptions: Array<{ value: HomeSort; label: string }> = [
  { value: "updated", label: "Recently updated" },
  { value: "added", label: "Recently added" },
  { value: "alphabetical", label: "A–Z" },
  { value: "attention", label: "Needs attention" },
];

const sectionLabels: Record<HomeSectionId, string> = {
  ask: "Ask Vault",
  attention: "Needs attention",
  suggestedMoves: "Suggested moves",
  continue: "Continue working",
  clusters: "Active clusters",
  quick: "Quick actions",
  recentSources: "Recent sources",
  inbox: "Inbox",
  sourceTypes: "Source types",
  timeline: "Timeline",
  tasks: "Current tasks",
  recentChats: "Recent conversations",
};

function HomeView() {
  const navigate = useNavigate();
  const backendGeneration = useBackendGeneration();
  const overviewSequence = useRef(0);
  const [preferences, setPreferences] = useState<HomePreferences>(() => readHomePreferences(null));
  const [preferencesProfileId, setPreferencesProfileId] = useState<string | null>(null);
  const [vault, setVault] = useState<VaultRecord | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [unsortedSources, setUnsortedSources] = useState<Source[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [activityItems, setActivityItems] = useState<ActivityRecord[]>([]);
  const [chatSessions, setChatSessions] = useState<ChatSessionRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [jobs, setJobs] = useState<JobQueueStatus | null>(null);
  const [totalSources, setTotalSources] = useState(0);
  const [unsortedCount, setUnsortedCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  const [sourceTypeCounts, setSourceTypeCounts] = useState<SourceTypeCountRecord[]>([]);
  const [clusterCounts, setClusterCounts] = useState<
    Map<string, { total: number; indexed: number }>
  >(new Map());
  const [suggestedMoves, setSuggestedMoves] = useState<ClusterSuggestionRecord[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");
  const [scopeClusterId, setScopeClusterId] = useState("all");

  useEffect(() => {
    if (vault && preferencesProfileId === vault.id) {
      writeHomePreferences(preferences, undefined, vault.id);
    }
  }, [preferences, preferencesProfileId, vault?.id]);

  useEffect(() => {
    if (!vault) {
      setPreferencesProfileId(null);
      return;
    }
    setPreferences(readHomePreferences(undefined, vault.id));
    setPreferencesProfileId(vault.id);
  }, [vault?.id]);

  const loadOverview = useCallback(async () => {
    const sequence = ++overviewSequence.current;
    try {
      const activeVault = (await listVaults())[0] ?? null;
      if (sequence !== overviewSequence.current) return;
      setVault(activeVault);
      if (!activeVault) {
        setSources([]);
        setUnsortedSources([]);
        setClusters([]);
        setActivityItems([]);
        setChatSessions([]);
        setProjects([]);
        setJobs(null);
        setTotalSources(0);
        return;
      }
      const results = await Promise.allSettled([
        listSources(activeVault.id, { limit: 4, order: "newest", unclustered: true }),
        listClusters(activeVault.id, { limit: 12 }),
        sourceCountsByCluster(activeVault.id),
        sourceCountsByType(activeVault.id),
        countSources(activeVault.id),
        countSources(activeVault.id, undefined, { unclustered: true }),
        countSources(activeVault.id, undefined, { states: ["failed"] }),
        listActivity(activeVault.id, { limit: 10 }),
        listChatSessions(activeVault.id, { limit: 5 }),
        listProjects(activeVault.id, { limit: 5 }),
        getJobStatus(),
        listClusterSuggestions(activeVault.id, 8),
      ]);
      const [
        unsortedResult,
        clusterResult,
        clusterCountResult,
        typeCountResult,
        totalResult,
        unsortedCountResult,
        failedCountResult,
        activityResult,
        chatResult,
        projectResult,
        jobsResult,
        suggestionsResult,
      ] = results;
      if (sequence !== overviewSequence.current) return;
      if (unsortedResult.status === "fulfilled") {
        setUnsortedSources(unsortedResult.value.map(sourceFromRecord));
      }
      if (clusterResult.status === "fulfilled") {
        setClusters(clusterResult.value.map(clusterFromRecord));
      }
      if (clusterCountResult.status === "fulfilled") {
        const next = new Map<string, { total: number; indexed: number }>();
        for (const item of clusterCountResult.value.items) {
          if (!item.cluster_id) continue;
          const current = next.get(item.cluster_id) ?? { total: 0, indexed: 0 };
          current.total += item.total;
          if (item.state === "indexed") current.indexed += item.total;
          next.set(item.cluster_id, current);
        }
        setClusterCounts(next);
      }
      if (typeCountResult.status === "fulfilled") setSourceTypeCounts(typeCountResult.value.items);
      if (totalResult.status === "fulfilled") setTotalSources(totalResult.value.total);
      if (unsortedCountResult.status === "fulfilled")
        setUnsortedCount(unsortedCountResult.value.total);
      if (failedCountResult.status === "fulfilled") setFailedCount(failedCountResult.value.total);
      if (activityResult.status === "fulfilled") setActivityItems(activityResult.value.items);
      if (chatResult.status === "fulfilled") setChatSessions(chatResult.value);
      if (projectResult.status === "fulfilled") setProjects(projectResult.value);
      if (jobsResult.status === "fulfilled") setJobs(jobsResult.value);
      if (suggestionsResult.status === "fulfilled") setSuggestedMoves(suggestionsResult.value);
      setLoadError(results.some((result) => result.status === "rejected"));
    } catch {
      setLoadError(true);
    }
  }, [backendGeneration]);

  const loadFilteredSources = useCallback(
    async (vaultId: string, nextPreferences: HomePreferences) => {
      try {
        const result = await listSources(vaultId, {
          limit: 12,
          order:
            nextPreferences.sort === "alphabetical"
              ? "alphabetical"
              : nextPreferences.sort === "added"
                ? "newest"
                : "newest",
          sourceTypes: sourceTypesForFilter(nextPreferences.type),
        });
        setSources(sortSources(result.map(sourceFromRecord), nextPreferences.sort));
      } catch {
        setLoadError(true);
      }
    },
    [],
  );

  useVisiblePolling(loadOverview, 30_000, true, undefined, backendGeneration);
  useVisiblePolling(
    () => (vault ? loadFilteredSources(vault.id, preferences) : undefined),
    30_000,
    Boolean(vault),
  );

  function updatePreferences(next: HomePreferences, reloadSources = false) {
    setPreferences(next);
    if (reloadSources && vault) void loadFilteredSources(vault.id, next);
  }

  const sortedClusters = useMemo(
    () => sortClusters(clusters, preferences.sort),
    [clusters, preferences.sort],
  );
  const visibleSections = preferences.sectionOrder.filter(
    (sectionId) => !preferences.hiddenSections.includes(sectionId),
  );
  const attentionItems = useMemo(
    () =>
      buildAttentionItems({
        failedCount,
        unsortedCount,
        jobs,
        loadError,
      }),
    [failedCount, unsortedCount, jobs, loadError],
  );
  const workItems = useMemo(
    () => buildWorkItems(activityItems, projects, sources, preferences),
    [activityItems, projects, sources, preferences],
  );
  const hasHomeContent = Boolean(
    totalSources ||
    clusters.length ||
    chatSessions.length ||
    projects.length ||
    activityItems.length,
  );
  const dense = preferences.density === "compact";

  async function startChat() {
    const text = query.trim();
    if (vault) {
      const session = await createChatSession({
        vault_id: vault.id,
        title: text || "New chat",
        scope_cluster_id: scopeClusterId === "all" ? null : scopeClusterId,
      });
      if (text) window.sessionStorage.setItem(`cml.pendingPrompt.${session.id}`, text);
      navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
      return;
    }
    navigate({ to: "/chat" });
  }

  function renderSection(sectionId: HomeSectionId) {
    switch (sectionId) {
      case "ask":
        return (
          <AskVaultSection
            key={sectionId}
            query={query}
            scopeClusterId={scopeClusterId}
            clusters={sortedClusters}
            recentChats={chatSessions.slice(0, 3)}
            dense={dense}
            onQueryChange={setQuery}
            onScopeChange={setScopeClusterId}
            onSend={() => void startChat()}
          />
        );
      case "attention":
        return attentionItems.length ? (
          <AttentionSection key={sectionId} items={attentionItems} dense={dense} />
        ) : null;
      case "suggestedMoves":
        return (
          <SuggestedMovesSection
            key={sectionId}
            suggestions={suggestedMoves}
            dense={dense}
            onChanged={() => void loadOverview()}
          />
        );
      case "continue":
        return (
          <ContinueSection
            key={sectionId}
            items={workItems.slice(0, 8)}
            view={preferences.view}
            dense={dense}
          />
        );
      case "clusters":
        return (
          <ActiveClustersSection
            key={sectionId}
            clusters={sortedClusters.slice(0, 8)}
            counts={clusterCounts}
            view={preferences.view}
            dense={dense}
          />
        );
      case "quick":
        return <QuickActionsSection key={sectionId} dense={dense} />;
      case "recentSources":
        return (
          <SourcesSection
            key={sectionId}
            title="Recent sources"
            description="The latest sources matching your Home filters."
            sources={sources.slice(0, 8)}
            view={preferences.view}
            dense={dense}
          />
        );
      case "inbox":
        return (
          <SourcesSection
            key={sectionId}
            title="Inbox"
            description={
              unsortedCount
                ? `${unsortedCount} sources still need a cluster.`
                : "Everything is organized."
            }
            sources={unsortedSources}
            view="list"
            dense={dense}
            inbox
          />
        );
      case "sourceTypes":
        return <SourceTypesSection key={sectionId} counts={sourceTypeCounts} dense={dense} />;
      case "timeline":
        return <TimelineSection key={sectionId} items={activityItems.slice(0, 8)} dense={dense} />;
      case "tasks":
        return <TasksSection key={sectionId} jobs={jobs} dense={dense} />;
      case "recentChats":
        return (
          <RecentChatsSection key={sectionId} chats={chatSessions.slice(0, 6)} dense={dense} />
        );
    }
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <main
        className={cn(
          "mx-auto w-full max-w-[1320px] min-w-0 px-4 pb-10 sm:px-8",
          dense ? "pt-5 sm:pt-7" : "pt-6 sm:pt-10",
        )}
      >
        <PageHeader className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <h1 className="page-title break-words">Home</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {vault
                ? `${vault.name} · ${totalSources.toLocaleString()} ${totalSources === 1 ? "source" : "sources"}`
                : "No library open"}
            </p>
          </div>

          <div className="flex max-w-full flex-wrap items-center gap-2">
            {hasHomeContent ? (
              <>
                <Select
                  value={preferences.type}
                  onValueChange={(value: HomeTypeFilter) =>
                    updatePreferences({ ...preferences, type: value }, true)
                  }
                >
                  <SelectTrigger
                    className="h-9 w-auto min-w-[132px] bg-card shadow-none"
                    aria-label="Filter Home by source type"
                  >
                    <ListFilter className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="mr-1 text-muted-foreground">Type:</span>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="end">
                    {typeOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select
                  value={preferences.sort}
                  onValueChange={(value: HomeSort) =>
                    updatePreferences({ ...preferences, sort: value }, true)
                  }
                >
                  <SelectTrigger
                    className="h-9 w-auto min-w-[166px] bg-card shadow-none"
                    aria-label="Sort Home"
                  >
                    <Clock3 className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="mr-1 text-muted-foreground">Sort:</span>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="end">
                    {sortOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            ) : null}

            <CustomizeHome
              preferences={preferences}
              onChange={(next) => updatePreferences(next, false)}
              onReset={() =>
                updatePreferences(
                  {
                    ...DEFAULT_HOME_PREFERENCES,
                    sectionOrder: [...DEFAULT_HOME_PREFERENCES.sectionOrder],
                    hiddenSections: [...DEFAULT_HOME_PREFERENCES.hiddenSections],
                  },
                  true,
                )
              }
            />
          </div>
        </PageHeader>

        <ProductSectionStack className={dense ? "mt-6 space-y-5" : "mt-8 space-y-7"}>
          {visibleSections.map(renderSection)}
        </ProductSectionStack>
      </main>
    </div>
  );
}

function CustomizeHome({
  preferences,
  onChange,
  onReset,
}: {
  preferences: HomePreferences;
  onChange: (preferences: HomePreferences) => void;
  onReset: () => void;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="gap-2 bg-card shadow-none" aria-label="Customize Home">
          <SlidersHorizontal className="h-4 w-4" />
          Customize
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="flex max-h-[min(720px,calc(100vh-5rem))] w-[min(340px,calc(100vw-2rem))] flex-col overflow-hidden p-0"
      >
        <div className="shrink-0 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Customize Home</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Choose what appears and in what order.
          </p>
        </div>

        <div className="min-h-0 space-y-4 overflow-y-auto p-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-foreground">Layout</span>
            <Select
              value={preferences.preset}
              onValueChange={(value: HomePreset) =>
                onChange(homePreferencesForPreset(preferences, value))
              }
            >
              <SelectTrigger className="shadow-none">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="focused">Focused</SelectItem>
                <SelectItem value="library">Library</SelectItem>
                <SelectItem value="activity">Activity</SelectItem>
              </SelectContent>
            </Select>
          </label>

          <ControlGroup label="Density">
            <SegmentButton
              selected={preferences.density === "comfortable"}
              onClick={() => onChange({ ...preferences, density: "comfortable" })}
            >
              Comfortable
            </SegmentButton>
            <SegmentButton
              selected={preferences.density === "compact"}
              onClick={() => onChange({ ...preferences, density: "compact" })}
            >
              Compact
            </SegmentButton>
          </ControlGroup>

          <ControlGroup label="View">
            <SegmentButton
              selected={preferences.view === "list"}
              onClick={() => onChange({ ...preferences, view: "list" })}
            >
              <LayoutList className="h-3.5 w-3.5" />
              List
            </SegmentButton>
            <SegmentButton
              selected={preferences.view === "grid"}
              onClick={() => onChange({ ...preferences, view: "grid" })}
            >
              <Grid2X2 className="h-3.5 w-3.5" />
              Grid
            </SegmentButton>
          </ControlGroup>

          <div>
            <div className="mb-2 text-xs font-medium text-foreground">Sections</div>
            <div className="divide-y divide-border rounded-md border border-border">
              {preferences.sectionOrder.map((sectionId, index) => {
                const visible = !preferences.hiddenSections.includes(sectionId);
                return (
                  <div key={sectionId} className="flex min-h-10 items-center gap-2 px-2.5 py-1.5">
                    <Switch
                      checked={visible}
                      aria-label={`${visible ? "Hide" : "Show"} ${sectionLabels[sectionId]}`}
                      onCheckedChange={(checked) =>
                        onChange({
                          ...preferences,
                          hiddenSections: checked
                            ? preferences.hiddenSections.filter((id) => id !== sectionId)
                            : [...preferences.hiddenSections, sectionId],
                        })
                      }
                    />
                    <span className="min-w-0 flex-1 truncate text-xs">
                      {sectionLabels[sectionId]}
                    </span>
                    <button
                      type="button"
                      className="rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-30"
                      aria-label={`Move ${sectionLabels[sectionId]} up`}
                      disabled={index === 0}
                      onClick={() => onChange(moveHomeSection(preferences, sectionId, -1))}
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      className="rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-30"
                      aria-label={`Move ${sectionLabels[sectionId]} down`}
                      disabled={index === preferences.sectionOrder.length - 1}
                      onClick={() => onChange(moveHomeSection(preferences, sectionId, 1))}
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="shrink-0 border-t border-border p-3">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-center gap-2"
            onClick={onReset}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset Home
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ControlGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-foreground">{label}</div>
      <div className="flex rounded-md border border-border p-0.5">{children}</div>
    </div>
  );
}

function SegmentButton({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "flex min-h-8 flex-1 items-center justify-center gap-1.5 rounded px-2 text-xs transition-colors",
        selected
          ? "bg-secondary font-medium text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function AskVaultSection({
  query,
  scopeClusterId,
  clusters,
  recentChats,
  dense,
  onQueryChange,
  onScopeChange,
  onSend,
}: {
  query: string;
  scopeClusterId: string;
  clusters: Cluster[];
  recentChats: ChatSessionRecord[];
  dense: boolean;
  onQueryChange: (value: string) => void;
  onScopeChange: (value: string) => void;
  onSend: () => void;
}) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Ask Vault"
        description="Ask across this library or narrow the answer to one cluster."
      />
      <div className={dense ? "p-3" : "p-4"}>
        <Textarea
          aria-label="Ask your library"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Ask your library…"
          className={cn(
            "resize-none border-0 bg-transparent p-1 text-base shadow-none focus-visible:ring-0",
            dense ? "min-h-[60px]" : "min-h-[78px]",
          )}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Select value={scopeClusterId} onValueChange={onScopeChange}>
            <SelectTrigger
              className="h-8 w-auto min-w-[150px] max-w-full border-0 bg-secondary text-xs shadow-none"
              aria-label="Chat scope"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Entire library</SelectItem>
              {clusters.map((cluster) => (
                <SelectItem key={cluster.id} value={cluster.id}>
                  {cluster.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">Ctrl Enter</span>
          <Button size="sm" className="gap-2" onClick={onSend}>
            <Send className="h-4 w-4" />
            Ask
          </Button>
        </div>
        {recentChats.length ? (
          <div className="mt-3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3">
            <span className="text-xs text-muted-foreground">Recent</span>
            {recentChats.map((chat) => (
              <Link
                key={chat.id}
                to="/chat/$chatId"
                params={{ chatId: chat.id }}
                className="max-w-[240px] truncate text-xs text-foreground hover:underline"
              >
                {chat.title}
              </Link>
            ))}
          </div>
        ) : null}
      </div>
    </ProductSection>
  );
}

type AttentionItem = {
  id: string;
  title: string;
  detail: string;
  href: "/sources" | "/tasks" | "/settings";
  search?: { filter: "unsorted" | "unclustered" } | { section: "health" };
};

function AttentionSection({ items, dense }: { items: AttentionItem[]; dense: boolean }) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Needs attention"
        description="Only items that need a decision or retry appear here."
      />
      <div className="divide-y divide-border">
        {items.map((item) => (
          <Link
            key={item.id}
            to={item.href}
            search={item.search}
            className={cn(
              "flex items-center gap-3 px-5 hover:bg-accent/35",
              dense ? "min-h-12 py-2" : "min-h-14 py-3",
            )}
          >
            <CircleAlert className="h-4 w-4 shrink-0 text-[var(--status-warn-ink)]" />
            <span className="min-w-0 flex-1">
              <span className="block break-words text-sm font-medium">{item.title}</span>
              <span className="block break-words text-xs text-muted-foreground">{item.detail}</span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </Link>
        ))}
      </div>
    </ProductSection>
  );
}

type WorkItem =
  | { id: string; kind: "source"; title: string; detail: string; time: string; sourceId: string }
  | { id: string; kind: "chat"; title: string; detail: string; time: string; chatId: string }
  | { id: string; kind: "cluster"; title: string; detail: string; time: string; clusterId: string }
  | { id: string; kind: "project"; title: string; detail: string; time: string; projectId: string };

function ContinueSection({
  items,
  view,
  dense,
}: {
  items: WorkItem[];
  view: HomePreferences["view"];
  dense: boolean;
}) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Continue working"
        description="Recent sources, conversations, clusters, and projects in one place."
      />
      {items.length ? (
        <div className={sectionItemsClass(view)}>
          {items.map((item) => (
            <WorkItemRow key={item.id} item={item} dense={dense} />
          ))}
        </div>
      ) : (
        <EmptyRow>Open a source, chat, cluster, or project to see it here.</EmptyRow>
      )}
    </ProductSection>
  );
}

function WorkItemRow({ item, dense }: { item: WorkItem; dense: boolean }) {
  const content = (
    <>
      <WorkIcon kind={item.kind} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{item.title}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">{item.detail}</span>
      </span>
      <time className="shrink-0 text-xs text-muted-foreground">{formatRelativeDay(item.time)}</time>
    </>
  );
  const className = cn(
    "flex items-center gap-3 bg-card px-5 hover:bg-accent/35",
    dense ? "min-h-12 py-2" : "min-h-16 py-3",
  );
  if (item.kind === "chat") {
    return (
      <Link to="/chat/$chatId" params={{ chatId: item.chatId }} className={className}>
        {content}
      </Link>
    );
  }
  if (item.kind === "cluster") {
    return (
      <Link to="/clusters/$clusterId" params={{ clusterId: item.clusterId }} className={className}>
        {content}
      </Link>
    );
  }
  if (item.kind === "project") {
    return (
      <Link to="/projects/$projectId" params={{ projectId: item.projectId }} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <Link to="/sources" search={{ source: item.sourceId }} className={className}>
      {content}
    </Link>
  );
}

function WorkIcon({ kind }: { kind: WorkItem["kind"] }) {
  const Icon =
    kind === "chat"
      ? MessageSquare
      : kind === "cluster"
        ? Sparkles
        : kind === "project"
          ? FolderKanban
          : FileText;
  return <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

function ActiveClustersSection({
  clusters,
  counts,
  view,
  dense,
}: {
  clusters: Cluster[];
  counts: Map<string, { total: number; indexed: number }>;
  view: HomePreferences["view"];
  dense: boolean;
}) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Active clusters"
        description="Recently used groups, ordered by your Home sort."
        action={
          <Link to="/clusters" className="text-sm text-primary hover:underline">
            View all
          </Link>
        }
      />
      {clusters.length ? (
        <div className={sectionItemsClass(view)}>
          {clusters.map((cluster) => {
            const metrics = counts.get(cluster.id) ?? { total: 0, indexed: 0 };
            return (
              <Link
                key={cluster.id}
                to="/clusters/$clusterId"
                params={{ clusterId: cluster.id }}
                className={cn(
                  "flex items-center gap-3 bg-card px-5 hover:bg-accent/35",
                  dense ? "min-h-12 py-2" : "min-h-16 py-3",
                )}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: `var(--cluster-${cluster.tint})` }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{cluster.name}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {metrics.total} {metrics.total === 1 ? "source" : "sources"} ·{" "}
                    {clusterStateText(cluster, metrics)}
                  </span>
                </span>
                <time className="shrink-0 text-xs text-muted-foreground">
                  {formatRelativeDay(cluster.lastActive)}
                </time>
              </Link>
            );
          })}
        </div>
      ) : (
        <EmptyRow>Create a cluster when several sources belong together.</EmptyRow>
      )}
    </ProductSection>
  );
}

function SuggestedMovesSection({
  suggestions,
  dense,
  onChanged,
}: {
  suggestions: ClusterSuggestionRecord[];
  dense: boolean;
  onChanged: () => void;
}) {
  if (suggestions.length === 0) return null;

  async function decide(suggestion: ClusterSuggestionRecord, action: "accepted" | "dismissed") {
    await decideClusterSuggestion({
      source_id: suggestion.source_id,
      suggested_cluster_id: suggestion.suggested_cluster_id,
      action,
    });
    onChanged();
  }

  return (
    <ProductSection>
      <ProductSectionHeader
        title="Suggested moves"
        description={`${suggestions.length} ${suggestions.length === 1 ? "source may fit" : "sources may fit"} better elsewhere.`}
        action={
          <Link to="/clusters" className="text-sm text-primary hover:underline">
            Review all
          </Link>
        }
      />
      <div className="divide-y divide-border">
        {suggestions.slice(0, 3).map((suggestion) => (
          <div
            key={`${suggestion.source_id}:${suggestion.suggested_cluster_id}`}
            className={cn(
              "flex flex-col gap-3 px-5 sm:flex-row sm:items-center",
              dense ? "py-2" : "py-3",
            )}
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{suggestion.source_title}</div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                Move to {suggestion.suggested_cluster_name}
              </div>
            </div>
            <div className="flex shrink-0 gap-1">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void decide(suggestion, "accepted")}
              >
                <Check className="h-4 w-4" /> Move
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Dismiss move for ${suggestion.source_title}`}
                onClick={() => void decide(suggestion, "dismissed")}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </ProductSection>
  );
}

function QuickActionsSection({ dense }: { dense: boolean }) {
  const actions = [
    { label: "Add source", href: "/sources" as const, icon: Plus },
    { label: "Start chat", href: "/chat" as const, icon: MessageSquare },
    { label: "New cluster", href: "/clusters" as const, icon: Sparkles },
    { label: "Add project", href: "/projects" as const, icon: FolderKanban },
  ];
  return (
    <ProductSection>
      <h2 className="sr-only">Quick actions</h2>
      <div className="flex flex-wrap divide-x divide-border">
        {actions.map(({ label, href, icon: Icon }) => (
          <Link
            key={label}
            to={href}
            className={cn(
              "flex min-w-[140px] flex-1 items-center justify-center gap-2 px-4 text-sm font-medium hover:bg-accent/35",
              dense ? "min-h-11" : "min-h-13",
            )}
          >
            <Icon className="h-4 w-4 text-muted-foreground" />
            {label}
          </Link>
        ))}
      </div>
    </ProductSection>
  );
}

function SourcesSection({
  title,
  description,
  sources,
  view,
  dense,
  inbox = false,
}: {
  title: string;
  description: string;
  sources: Source[];
  view: HomePreferences["view"];
  dense: boolean;
  inbox?: boolean;
}) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title={title}
        description={description}
        action={
          <Link
            to="/sources"
            search={inbox ? { filter: "unclustered" } : undefined}
            className="text-sm text-primary hover:underline"
          >
            {inbox ? "Review" : "View all"}
          </Link>
        }
      />
      {sources.length ? (
        <div className={sectionItemsClass(view)}>
          {sources.map((source) => (
            <SourceRow key={source.id} source={source} dense={dense} />
          ))}
        </div>
      ) : (
        <EmptyRow>
          {inbox ? "Nothing is waiting in your inbox." : "No sources match these filters."}
        </EmptyRow>
      )}
    </ProductSection>
  );
}

function SourceRow({ source, dense }: { source: Source; dense: boolean }) {
  const Icon = sourceTypeIcons[source.type];
  return (
    <Link
      to="/sources"
      search={{ source: source.id }}
      className={cn(
        "flex items-center gap-3 bg-card px-5 hover:bg-accent/35",
        dense ? "min-h-12 py-2" : "min-h-16 py-3",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{source.title}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
          {sourceSummaryText(source)}
        </span>
      </span>
      <span className="shrink-0 text-xs text-muted-foreground">{sourceStateText(source)}</span>
    </Link>
  );
}

function SourceTypesSection({
  counts,
  dense,
}: {
  counts: SourceTypeCountRecord[];
  dense: boolean;
}) {
  const grouped = typeOptions
    .filter((option) => option.value !== "all")
    .map((option) => ({
      ...option,
      total: counts
        .filter((item) =>
          sourceTypesForFilter(option.value)?.includes(item.source_type as SourceType),
        )
        .reduce((sum, item) => sum + item.total, 0),
    }));
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Source types"
        description="A compact breakdown of what is in this library."
      />
      <dl className="divide-y divide-border">
        {grouped.map((item) => (
          <div
            key={item.value}
            className={cn(
              "flex items-center justify-between gap-4 px-5",
              dense ? "min-h-10" : "min-h-12",
            )}
          >
            <dt className="text-sm">{item.label}</dt>
            <dd className="text-sm tabular-nums text-muted-foreground">
              {item.total.toLocaleString()}
            </dd>
          </div>
        ))}
      </dl>
    </ProductSection>
  );
}

function TimelineSection({ items, dense }: { items: ActivityRecord[]; dense: boolean }) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Timeline"
        description="Recent changes across the library."
        action={
          <Link to="/timeline" className="text-sm text-primary hover:underline">
            View all
          </Link>
        }
      />
      {items.length ? (
        <div className="divide-y divide-border">
          {items.map((item) => (
            <ActivityRow key={item.id} item={item} dense={dense} />
          ))}
        </div>
      ) : (
        <EmptyRow>No activity yet.</EmptyRow>
      )}
    </ProductSection>
  );
}

function ActivityRow({ item, dense }: { item: ActivityRecord; dense: boolean }) {
  const targetId = item.id.split(":", 2)[1] ?? "";
  const content = (
    <>
      <WorkIcon kind={item.kind} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{item.title}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">{item.detail}</span>
      </span>
      <time className="shrink-0 text-xs text-muted-foreground">{formatRelativeDay(item.time)}</time>
    </>
  );
  const className = cn(
    "flex items-center gap-3 px-5 hover:bg-accent/35",
    dense ? "min-h-12 py-2" : "min-h-15 py-3",
  );
  if (item.kind === "chat") {
    return (
      <Link to="/chat/$chatId" params={{ chatId: targetId }} className={className}>
        {content}
      </Link>
    );
  }
  if (item.kind === "cluster") {
    return (
      <Link to="/clusters/$clusterId" params={{ clusterId: targetId }} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <Link to="/sources" search={{ source: targetId }} className={className}>
      {content}
    </Link>
  );
}

function TasksSection({ jobs, dense }: { jobs: JobQueueStatus | null; dense: boolean }) {
  const rows = jobs
    ? [
        { label: "Running", value: jobs.running },
        { label: "Queued", value: jobs.queued },
        { label: "Waiting for model", value: jobs.blocked_local_model },
        {
          label: "Waiting for setup",
          value: Math.max(0, jobs.blocked_setup_required - jobs.blocked_local_model),
        },
        { label: "Waiting on another task", value: jobs.blocked_by_dependency },
        { label: "Needs review", value: jobs.manual_review },
        { label: "Paused", value: jobs.paused },
        { label: "Failed", value: jobs.failed },
      ].filter((item) => item.value > 0)
    : [];
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Current tasks"
        description="Imports and background work that are still active."
        action={
          <Link to="/tasks" className="text-sm text-primary hover:underline">
            Open Tasks
          </Link>
        }
      />
      {rows.length ? (
        <dl className="divide-y divide-border">
          {rows.map((row) => (
            <div
              key={row.label}
              className={cn(
                "flex items-center justify-between gap-4 px-5",
                dense ? "min-h-10" : "min-h-12",
              )}
            >
              <dt className="text-sm">{row.label}</dt>
              <dd className="text-sm tabular-nums text-muted-foreground">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <EmptyRow>No background work is waiting.</EmptyRow>
      )}
    </ProductSection>
  );
}

function RecentChatsSection({ chats, dense }: { chats: ChatSessionRecord[]; dense: boolean }) {
  return (
    <ProductSection>
      <ProductSectionHeader
        title="Recent conversations"
        description="Pick up where you left off."
        action={
          <Link to="/chat" className="text-sm text-primary hover:underline">
            View all
          </Link>
        }
      />
      {chats.length ? (
        <div className="divide-y divide-border">
          {chats.map((chat) => (
            <Link
              key={chat.id}
              to="/chat/$chatId"
              params={{ chatId: chat.id }}
              className={cn(
                "flex items-center gap-3 px-5 hover:bg-accent/35",
                dense ? "min-h-12 py-2" : "min-h-14 py-3",
              )}
            >
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{chat.title}</span>
              <time className="shrink-0 text-xs text-muted-foreground">
                {formatRelativeDay(chat.updated_at)}
              </time>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyRow>Start a chat to see it here.</EmptyRow>
      )}
    </ProductSection>
  );
}

function EmptyRow({ children }: { children: ReactNode }) {
  return <div className="px-5 py-6 text-sm text-muted-foreground">{children}</div>;
}

function buildAttentionItems({
  failedCount,
  unsortedCount,
  jobs,
  loadError,
}: {
  failedCount: number;
  unsortedCount: number;
  jobs: JobQueueStatus | null;
  loadError: boolean;
}): AttentionItem[] {
  const items: AttentionItem[] = [];
  if (failedCount > 0) {
    items.push({
      id: "failed-sources",
      title: `${failedCount} ${failedCount === 1 ? "source needs" : "sources need"} a retry`,
      detail: "Open Sources to review the indexing error.",
      href: "/sources",
    });
  }
  if (unsortedCount > 0) {
    items.push({
      id: "unsorted-sources",
      title: `${unsortedCount} ${unsortedCount === 1 ? "source is" : "sources are"} not organized`,
      detail: "Move them from the inbox into a cluster.",
      href: "/sources",
      search: { filter: "unclustered" },
    });
  }
  if ((jobs?.paused ?? 0) > 0) {
    items.push({
      id: "paused-jobs",
      title: `${jobs?.paused} paused ${jobs?.paused === 1 ? "task" : "tasks"}`,
      detail: "Resume or stop them from Tasks.",
      href: "/tasks",
    });
  }
  if ((jobs?.blocked_local_model ?? 0) > 0) {
    items.push({
      id: "local-model",
      title: "Local model unavailable",
      detail: `${jobs?.blocked_local_model} ${jobs?.blocked_local_model === 1 ? "task is" : "tasks are"} waiting. Vault will resume them after the model restarts.`,
      href: "/settings",
      search: { section: "health" },
    });
  }
  if ((jobs?.failed ?? 0) > 0) {
    items.push({
      id: "failed-jobs",
      title: `${jobs?.failed} failed background ${jobs?.failed === 1 ? "task" : "tasks"}`,
      detail: "Open Tasks for the failure details.",
      href: "/tasks",
    });
  }
  if (loadError) {
    items.push({
      id: "service",
      title: "Some library details are unavailable",
      detail: "Check the local service from Settings.",
      href: "/settings",
      search: { section: "health" },
    });
  }
  return items;
}

function buildWorkItems(
  activity: ActivityRecord[],
  projects: ProjectRecord[],
  sources: Source[],
  preferences: HomePreferences,
): WorkItem[] {
  const sourceIds = new Set(sources.map((source) => source.id));
  const items: WorkItem[] = [];
  for (const item of activity) {
    const targetId = item.id.split(":", 2)[1] ?? "";
    if (preferences.type !== "all" && item.kind === "source" && !sourceIds.has(targetId)) continue;
    if (item.kind === "chat") {
      items.push({
        id: item.id,
        kind: "chat",
        title: item.title,
        detail: item.detail,
        time: item.time,
        chatId: targetId,
      });
    } else if (item.kind === "cluster") {
      items.push({
        id: item.id,
        kind: "cluster",
        title: item.title,
        detail: item.detail,
        time: item.time,
        clusterId: targetId,
      });
    } else {
      items.push({
        id: item.id,
        kind: "source",
        title: item.title,
        detail: item.detail,
        time: item.time,
        sourceId: targetId,
      });
    }
  }
  for (const project of projects) {
    items.push({
      id: `project:${project.id}`,
      kind: "project",
      title: project.name,
      detail: project.status || "Project",
      time: project.updated_at,
      projectId: project.id,
    });
  }
  return sortWorkItems(items, preferences.sort);
}

function sortWorkItems(items: WorkItem[], sort: HomeSort) {
  return [...items].sort((left, right) => {
    if (sort === "alphabetical") return left.title.localeCompare(right.title);
    if (sort === "attention") {
      const leftAttention = /fail|pause|review|attention/i.test(left.detail) ? 1 : 0;
      const rightAttention = /fail|pause|review|attention/i.test(right.detail) ? 1 : 0;
      if (leftAttention !== rightAttention) return rightAttention - leftAttention;
    }
    return new Date(right.time).getTime() - new Date(left.time).getTime();
  });
}

function sortSources(sources: Source[], sort: HomeSort) {
  return [...sources].sort((left, right) => {
    if (sort === "alphabetical") return left.title.localeCompare(right.title);
    if (sort === "added") return dateValue(right.createdAt) - dateValue(left.createdAt);
    if (sort === "attention") {
      const rank = { failed: 0, processing: 1, waiting: 2, indexed: 3 } as const;
      const stateDifference = rank[left.state] - rank[right.state];
      if (stateDifference) return stateDifference;
      if (Boolean(left.clusterId) !== Boolean(right.clusterId)) return left.clusterId ? 1 : -1;
    }
    return dateValue(right.updatedAt) - dateValue(left.updatedAt);
  });
}

function sortClusters(clusters: Cluster[], sort: HomeSort) {
  return [...clusters].sort((left, right) => {
    if (sort === "alphabetical") return left.name.localeCompare(right.name);
    if (sort === "attention") {
      const attentionStates = new Set(["issue", "paused", "profile-stale", "retrieval-only"]);
      const leftAttention = attentionStates.has(left.lifecycle) ? 1 : 0;
      const rightAttention = attentionStates.has(right.lifecycle) ? 1 : 0;
      if (leftAttention !== rightAttention) return rightAttention - leftAttention;
    }
    return dateValue(right.lastActive) - dateValue(left.lastActive);
  });
}

function sourceTypesForFilter(filter: HomeTypeFilter): SourceType[] | undefined {
  if (filter === "documents") return ["file", "external_artifact"];
  if (filter === "notes") return ["note"];
  if (filter === "links") return ["link"];
  if (filter === "media") return ["image", "audio", "video", "external_transcript"];
  if (filter === "code") return ["code"];
  return undefined;
}

function sectionItemsClass(view: HomePreferences["view"]) {
  return view === "grid" ? "grid gap-px bg-border sm:grid-cols-2" : "divide-y divide-border";
}

function clusterStateText(cluster: Cluster, metrics: { total: number; indexed: number }) {
  if (cluster.lifecycle === "issue") return "Needs attention";
  if (cluster.lifecycle === "paused") return "Paused";
  if (metrics.total > 0 && metrics.indexed < metrics.total) return `${metrics.indexed} indexed`;
  return "Ready";
}

const sourceTypeIcons = {
  file: FileText,
  link: Link2,
  note: File,
  image: ImageIcon,
  audio: Mic,
  video: ImageIcon,
  code: FileCode2,
  external_transcript: Mic,
  external_artifact: FileText,
} satisfies Record<Source["type"], typeof FileText>;

function sourceSummaryText(source: Source) {
  if (source.state === "waiting") return "Waiting to be indexed";
  if (source.state === "processing") return "Indexing";
  if (source.state === "failed") return "Indexing failed";
  if (source.summary.trim()) return source.summary;
  const preview = source.preview.trim();
  if (!preview) return source.type;
  return preview.length > 90 ? `${preview.slice(0, 90).trimEnd()}…` : preview;
}

function sourceStateText(source: Source) {
  if (source.state === "indexed") return "Ready";
  if (source.state === "processing") return "Indexing";
  if (source.state === "failed") return "Needs review";
  return "Waiting";
}

function formatRelativeDay(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function dateValue(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}
