import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Clock3,
  FolderOpen,
  RefreshCw,
  Send,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/WindowAware";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import {
  cancelProjectRun,
  createChatSession,
  getProject,
  getProjectChanges,
  getProjectRun,
  linkProjectCluster,
  listClusters,
  listProjectLinks,
  listProjectRuns,
  reindexProject,
  removeProject,
  synchronizeProjectChanges,
  unlinkProjectCluster,
  updateProject,
  type ProjectIndexRunRecord,
  type ProjectRecord,
  type ProjectChangesRecord,
  type ProjectLinkRecord,
  type ClusterRecord,
} from "@/lib/backend";
import { displayPath } from "@/lib/displayPath";
import { detectProjectVisualizationRequest } from "@/components/ProjectGraphArtifact";

export const Route = createFileRoute("/_app/projects/$projectId")({
  head: () => ({ meta: [{ title: "Project" }] }),
  component: ProjectWorkspace,
});

function ProjectWorkspace() {
  const { projectId } = Route.useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [runs, setRuns] = useState<ProjectIndexRunRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [detailsWarning, setDetailsWarning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [name, setName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [links, setLinks] = useState<ProjectLinkRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [linkTarget, setLinkTarget] = useState("");
  const [changes, setChanges] = useState<ProjectChangesRecord | null>(null);

  const load = useCallback(async () => {
    try {
      const nextProject = await getProject(projectId);
      const [runsResult, linksResult, clustersResult, changesResult] = await Promise.allSettled([
        listProjectRuns(projectId, 12),
        listProjectLinks(projectId),
        listClusters(nextProject.vault_id),
        getProjectChanges(projectId, 200),
      ]);
      setProject(nextProject);
      if (runsResult.status === "fulfilled") setRuns(runsResult.value);
      if (linksResult.status === "fulfilled") setLinks(linksResult.value);
      if (clustersResult.status === "fulfilled") setClusters(clustersResult.value);
      if (changesResult.status === "fulfilled") setChanges(changesResult.value);
      setName(nextProject.name);
      const unavailable = [
        runsResult.status === "rejected" ? "history" : "",
        linksResult.status === "rejected" ? "links" : "",
        clustersResult.status === "rejected" ? "clusters" : "",
        changesResult.status === "rejected" ? "changes" : "",
      ].filter(Boolean);
      setDetailsWarning(
        unavailable.length ? `Unavailable right now: ${unavailable.join(", ")}.` : null,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Vault could not load this project.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshActiveRun = useCallback(async () => {
    if (!project?.active_run_id) return;
    try {
      const run = await getProjectRun(projectId, project.active_run_id);
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      if (!["queued", "running"].includes(run.status)) await load();
    } catch {
      // A later aggregate refresh will reconcile transient backend restarts.
    }
  }, [load, project?.active_run_id, projectId]);

  useVisiblePolling(refreshActiveRun, 1500, Boolean(project?.active_run_id));

  const activeRun = project?.active_run_id
    ? (runs.find((run) => run.id === project.active_run_id) ?? null)
    : null;
  const languages = useMemo(
    () =>
      Object.entries(project?.languages ?? {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3),
    [project],
  );
  const questions = useMemo(() => (project ? projectQuestions(project) : []), [project]);

  async function ask(prompt = question) {
    if (!project || !prompt.trim() || busy) return;
    const normalized = prompt.trim();
    const visualization = detectProjectVisualizationRequest(normalized);
    if (visualization) {
      navigate({
        to: "/project-map",
        search: { project: project.id, mode: visualization.mode, q: visualization.query },
      });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const session = await createChatSession({
        vault_id: project.vault_id,
        title: `${project.name}: ${normalized.slice(0, 52)}`,
        scope_cluster_id: project.primary_cluster_id,
        scope_project_id: project.id,
      });
      window.sessionStorage.setItem(`cml.pendingPrompt.${session.id}`, normalized);
      await navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Odin could not start this question.");
    } finally {
      setBusy(false);
    }
  }

  async function runAction(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The project could not be updated.");
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-sm text-muted-foreground">
        {message ?? "Loading project…"}
      </div>
    );
  }

  const commit = project.indexed_commit?.slice(0, 8);
  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <div className="mx-auto min-h-full max-w-5xl">
        <main className="min-w-0 px-4 py-6 sm:px-7 sm:py-8 lg:px-10">
          <Link
            to="/projects"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Projects
          </Link>
          <PageHeader className="mt-6 flex flex-wrap items-start justify-between gap-5 pb-5">
            <div className="min-w-0">
              <h1 className="page-title break-words">{project.name}</h1>
              <p className="mt-2 flex flex-wrap gap-x-2 text-sm text-muted-foreground">
                {project.default_branch && <span>{project.default_branch}</span>}
                <span>{project.source_count.toLocaleString()} files</span>
                {Boolean(changes?.changed_path_count) && (
                  <span role="status" className="text-foreground">
                    {changes!.changed_path_count.toLocaleString()}{" "}
                    {changes!.changed_path_count === 1 ? "change" : "changes"} pending
                  </span>
                )}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setSettingsOpen((value) => !value)}>
                <Settings2 className="h-4 w-4" /> Settings
              </Button>
              <Button
                disabled={busy || Boolean(activeRun)}
                onClick={() =>
                  void runAction(
                    () => synchronizeProjectChanges(project.id),
                    "Synchronization queued. Your current index remains available until activation.",
                  )
                }
              >
                <RefreshCw
                  className={`h-4 w-4 ${busy ? "animate-spin motion-reduce:animate-none" : ""}`}
                />{" "}
                Synchronize
              </Button>
            </div>
          </PageHeader>

          {activeRun && (
            <RunStrip
              run={activeRun}
              onCancel={() =>
                void runAction(
                  () => cancelProjectRun(project.id),
                  "Cancellation requested. The previous active index remains available.",
                )
              }
            />
          )}
          {message && (
            <div
              role="status"
              className="mt-5 rounded border border-border bg-card px-3 py-2 text-sm text-muted-foreground"
            >
              {message}
            </div>
          )}
          {settingsOpen && (
            <>
              <ProjectScopeSettings
                project={project}
                busy={busy}
                onChange={(scope) =>
                  void runAction(
                    () => updateProject(project.id, { discovery_scope: scope }),
                    "Project scope updated. Synchronize to build the replacement index.",
                  )
                }
              />
              <ProjectSyncModeSettings
                project={project}
                busy={busy}
                onChange={(syncMode) =>
                  void runAction(
                    () => updateProject(project.id, { sync_mode: syncMode }),
                    "Project sync mode updated.",
                  )
                }
              />
            </>
          )}
          {settingsOpen && (
            <ProjectSettings
              project={project}
              name={name}
              setName={setName}
              confirmation={confirmation}
              setConfirmation={setConfirmation}
              busy={busy}
              links={links}
              clusters={clusters}
              linkTarget={linkTarget}
              setLinkTarget={setLinkTarget}
              onLink={() =>
                void runAction(
                  () => linkProjectCluster(project.id, linkTarget),
                  "Cluster linked to this project.",
                )
              }
              onUnlink={(clusterId) =>
                void runAction(
                  () => unlinkProjectCluster(project.id, clusterId),
                  "Cluster link removed.",
                )
              }
              onSave={() =>
                void runAction(() => updateProject(project.id, { name }), "Project name updated.")
              }
              onReconnect={() => void reconnect(project, runAction)}
              onReindex={(layer) =>
                void runAction(
                  () => reindexProject(project.id, layer),
                  `${layer === "structure" ? "Structure" : layer === "retrieval" ? "Search" : "Interpretation"} refresh queued.`,
                )
              }
              onRemove={() =>
                void runAction(async () => {
                  await removeProject(project.id, confirmation);
                  navigate({ to: "/projects" });
                }, "Project removed from Vault. Repository files were not changed.")
              }
            />
          )}

          <section className="mt-6 max-w-3xl" aria-label="Project overview">
            <p className="max-w-[68ch] text-base leading-7 text-foreground/90">
              {project.brief ||
                "Odin has registered this project. Synchronize it to build a local, searchable overview."}
            </p>
            <div className="mt-3 flex flex-wrap gap-x-2 text-sm text-muted-foreground">
              {languages.length > 0 && (
                <span>{languages.map(([language]) => language).join(", ")}</span>
              )}
              <span>Updated {formatDate(project.updated_at)}</span>
            </div>
          </section>

          <section className="mt-8 max-w-3xl">
            <h2 className="text-lg font-semibold">Ask Odin</h2>
            <div className="mt-3 rounded-md border border-border bg-card p-2 focus-within:border-primary/60">
              <Textarea
                aria-label="Ask about this project"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask how something works, where it is defined, or what depends on it…"
                className="min-h-20 resize-y border-0 bg-transparent p-2 shadow-none focus-visible:ring-0"
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void ask();
                }}
              />
              <div className="flex justify-end px-1 pb-1">
                <Button size="sm" disabled={busy || !question.trim()} onClick={() => void ask()}>
                  <Send className="h-4 w-4" /> Ask Odin
                </Button>
              </div>
            </div>
            <details className="mt-3 text-sm text-muted-foreground">
              <summary className="w-fit cursor-pointer rounded py-1 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Suggested questions
              </summary>
              <nav
                aria-label="Suggested project questions"
                className="mt-2 grid gap-1 sm:grid-cols-2"
              >
                {questions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    disabled={busy}
                    className="rounded px-2 py-2 text-left hover:bg-card hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => void ask(item)}
                  >
                    {item}
                  </button>
                ))}
              </nav>
            </details>
          </section>

          <details className="mt-8 max-w-3xl border-t border-border py-5 text-sm">
            <summary className="w-fit cursor-pointer rounded font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              Project details
            </summary>
            <div className="mt-5 grid gap-7 sm:grid-cols-2">
              <section aria-labelledby="index-status-title">
                <h2 id="index-status-title" className="text-sm font-semibold">
                  Index status
                </h2>
                <div className="mt-2 divide-y divide-border">
                  <Layer label="Structure" value={project.structure_status} />
                  <Layer label="Search" value={project.retrieval_status} />
                  <Layer
                    label="Interpretation"
                    value={
                      project.interpretation_status === "unavailable"
                        ? "Not enabled"
                        : project.interpretation_status
                    }
                  />
                </div>
                {commit && (
                  <p className="mt-2 text-xs text-muted-foreground">Indexed at {commit}</p>
                )}
              </section>
              <section aria-labelledby="project-activity-title">
                <h2 id="project-activity-title" className="text-sm font-semibold">
                  Activity
                </h2>
                {project.entrypoints.length > 0 && (
                  <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                    Entry: {project.entrypoints[0]}
                  </p>
                )}
                <div className="mt-3 space-y-2">
                  {runs.slice(0, 3).map((run) => (
                    <p key={run.id} className="text-xs text-muted-foreground">
                      <span className="capitalize text-foreground">
                        {run.status.replaceAll("_", " ")}
                      </span>{" "}
                      · {formatDate(run.updated_at)}
                    </p>
                  ))}
                </div>
                <Link to="/tasks" className="mt-3 inline-flex text-sm text-primary">
                  View tasks
                </Link>
              </section>
            </div>
            {detailsWarning && (
              <p role="status" className="mt-5 text-xs text-muted-foreground">
                {detailsWarning}
              </p>
            )}
            {project.structure_status === "stale" && !activeRun && (
              <div role="status" className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">The project map needs an update.</p>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void runAction(
                      () => reindexProject(project.id, "structure"),
                      "Project map update queued.",
                    )
                  }
                >
                  <RefreshCw className="h-4 w-4" /> Update map
                </Button>
              </div>
            )}
            <ProjectChangesInbox
              changes={changes}
              busy={busy || Boolean(activeRun)}
              onSync={() =>
                void runAction(
                  () => synchronizeProjectChanges(project.id),
                  "Changed files are queued for synchronization.",
                )
              }
            />
          </details>
        </main>
      </div>
    </div>
  );
}

function RunStrip({ run, onCancel }: { run: ProjectIndexRunRecord; onCancel: () => void }) {
  const total = run.phase_total_count || run.eligible_total;
  const complete = run.phase_completed_count || run.completed_count;
  const percent = total ? Math.min(100, Math.round((complete / total) * 100)) : 0;
  const phase = projectRunPhase(run.phase);
  return (
    <section
      aria-label="Project indexing progress"
      className="mt-3 rounded-md bg-muted/60 px-3 py-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <Clock3 className="h-4 w-4 text-primary" />
          <span className="font-medium">{phase.label}</span>
          <span className="text-xs text-muted-foreground">
            {total ? `${complete.toLocaleString()} / ${total.toLocaleString()}` : "Preparing"}
          </span>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            <Square className="h-3.5 w-3.5" /> Cancel
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to="/tasks">Task</Link>
          </Button>
        </div>
      </div>
      <div
        className="mt-2 h-1 overflow-hidden rounded-full bg-background"
        role="progressbar"
        aria-label={`${phase.label}: ${percent}%`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div
          className="h-full bg-primary transition-[width] motion-reduce:transition-none"
          style={{ width: `${percent}%` }}
        />
      </div>
    </section>
  );
}

export function projectQuestions(project: ProjectRecord): string[] {
  const primaryLanguage = Object.entries(project.languages).sort((a, b) => b[1] - a[1])[0]?.[0];
  const questions = ["Open the project map."];

  if (project.entrypoints[0]) {
    questions.push(`Explain the application flow starting at ${project.entrypoints[0]}.`);
  } else {
    questions.push(`Explain the main application flow in ${project.name}.`);
  }

  if (project.workspace_count > 0) {
    questions.push(
      project.workspace_count === 1
        ? `How is the detected package or workspace in ${project.name} organized?`
        : `How are the ${project.workspace_count} detected packages or workspaces in ${project.name} organized?`,
    );
  } else if (primaryLanguage) {
    questions.push(`How is the ${primaryLanguage} code in ${project.name} organized?`);
  } else {
    questions.push(`What are the major areas of ${project.name}?`);
  }

  if (project.entrypoints[1]) {
    questions.push(`How does ${project.entrypoints[1]} connect to the rest of ${project.name}?`);
  } else {
    questions.push(`Which configuration files control ${project.name}?`);
  }

  return questions;
}

function ProjectChangesInbox({
  changes,
  busy,
  onSync,
}: {
  changes: ProjectChangesRecord | null;
  busy: boolean;
  onSync: () => void;
}) {
  if (!changes) return null;
  const items = changes.change_items.slice(0, 20);
  return (
    <section className="mt-5 border-y border-border py-4" aria-labelledby="project-changes-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="project-changes-title" className="text-sm font-semibold">
            Odin freshness
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {changes.changed_path_count
              ? `${changes.changed_path_count.toLocaleString()} eligible paths differ from the active Odin snapshot.`
              : "The active Odin snapshot matches the current eligible files."}{" "}
            {changes.last_checked_at ? `Last verified ${formatDate(changes.last_checked_at)}.` : ""}
          </p>
        </div>
        {changes.changed && (
          <Button size="sm" variant="outline" disabled={busy} onClick={onSync}>
            <RefreshCw className="h-3.5 w-3.5" /> Sync changes
          </Button>
        )}
      </div>
      {items.length > 0 && (
        <ul className="mt-3 divide-y divide-border border-y border-border">
          {items.map((item) => (
            <li
              key={`${item.kind}:${item.previous_path ?? ""}:${item.path}`}
              className="grid min-w-0 grid-cols-[5.5rem_minmax(0,1fr)] gap-3 py-2 text-xs"
            >
              <span className="capitalize text-muted-foreground">{item.kind}</span>
              <span className="min-w-0 break-all font-mono">
                {item.previous_path ? `${item.previous_path} → ${item.path}` : item.path}
              </span>
            </li>
          ))}
        </ul>
      )}
      {changes.truncated && (
        <p className="mt-2 text-xs text-muted-foreground">
          This list is bounded. Synchronization will use the complete detected delta or explain why
          a full refresh is required.
        </p>
      )}
      <div className="mt-4 border-t border-border pt-4">
        <h3 className="text-xs font-medium">Git repository status</h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {changes.working_tree_dirty
            ? `Git reports ${changes.repository_changed_path_count.toLocaleString()} changed working-tree paths. Some or all may already be present in Odin's active snapshot.`
            : "Git reports a clean working tree."}
          {changes.repository_truncated ? " This repository list is bounded." : ""}
        </p>
      </div>
    </section>
  );
}

function projectRunPhase(value: string) {
  const phase = value.toLowerCase();
  if (phase.startsWith("discover") || phase === "candidate_build")
    return { label: "Discovering files" };
  if (phase.startsWith("structure")) return { label: "Building structure" };
  if (phase.startsWith("retrieval")) return { label: "Preparing search" };
  return { label: "Activating index" };
}

function ProjectScopeSettings({
  project,
  busy,
  onChange,
}: {
  project: ProjectRecord;
  busy: boolean;
  onChange: (scope: "context" | "code") => void;
}) {
  const activeScope = project.active_snapshot?.discovery_scope ?? null;
  const options = [
    {
      value: "context" as const,
      title: "Code and context",
      description: "Include source code, documentation, manifests, and configuration.",
    },
    {
      value: "code" as const,
      title: "Code only",
      description:
        "Include source-like files and skip prose documentation and general configuration.",
    },
  ];
  return (
    <section className="mt-5 rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Files to index</h2>
      <p className="mt-1 max-w-[70ch] text-xs leading-5 text-muted-foreground">
        This setting persists for every future synchronization. Changing it keeps the active index
        available until you synchronize and its replacement is ready.
      </p>
      <fieldset className="mt-3" disabled={busy || Boolean(project.active_run_id)}>
        <legend className="sr-only">Project indexing scope</legend>
        <div className="divide-y divide-border border-y border-border">
          {options.map((option) => (
            <label key={option.value} className="flex cursor-pointer items-start gap-3 py-3">
              <input
                type="radio"
                name="project-discovery-scope"
                value={option.value}
                checked={project.discovery_scope === option.value}
                onChange={() => onChange(option.value)}
                className="mt-1 h-4 w-4 accent-[var(--primary)]"
              />
              <span>
                <span className="block text-sm font-medium">{option.title}</span>
                <span className="mt-0.5 block max-w-[58ch] text-xs leading-5 text-muted-foreground">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      {activeScope && activeScope !== project.discovery_scope && (
        <p role="status" className="mt-3 text-xs leading-5 text-muted-foreground">
          The active index still uses {activeScope === "code" ? "code only" : "code and context"}.
          Select Synchronize when you are ready to replace it.
        </p>
      )}
    </section>
  );
}

function ProjectSyncModeSettings({
  project,
  busy,
  onChange,
}: {
  project: ProjectRecord;
  busy: boolean;
  onChange: (mode: "automatic" | "notify" | "manual") => void;
}) {
  const options = [
    {
      value: "automatic" as const,
      title: "Automatic",
      description: "Detect and queue bounded changes when Vault verifies this project.",
    },
    {
      value: "notify" as const,
      title: "Notify only",
      description: "Detect changes and show them here without starting synchronization.",
    },
    {
      value: "manual" as const,
      title: "Manual",
      description: "Synchronize only when you choose Sync changes.",
    },
  ];
  return (
    <section className="mt-5 rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Change synchronization</h2>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={busy}
            aria-pressed={project.sync_mode === option.value}
            className={`rounded-md border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              project.sync_mode === option.value ? "border-primary bg-primary/5" : "border-border"
            }`}
            onClick={() => onChange(option.value)}
          >
            <span className="block text-sm font-medium">{option.title}</span>
            <span className="mt-1 block text-xs leading-5 text-muted-foreground">
              {option.description}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ProjectSettings({
  project,
  name,
  setName,
  confirmation,
  setConfirmation,
  busy,
  links,
  clusters,
  linkTarget,
  setLinkTarget,
  onLink,
  onUnlink,
  onSave,
  onReconnect,
  onReindex,
  onRemove,
}: {
  project: ProjectRecord;
  name: string;
  setName: (value: string) => void;
  confirmation: string;
  setConfirmation: (value: string) => void;
  busy: boolean;
  links: ProjectLinkRecord[];
  clusters: ClusterRecord[];
  linkTarget: string;
  setLinkTarget: (value: string) => void;
  onLink: () => void;
  onUnlink: (clusterId: string) => void;
  onSave: () => void;
  onReconnect: () => void;
  onReindex: (layer: "structure" | "retrieval" | "interpretation") => void;
  onRemove: () => void;
}) {
  const available = clusters.filter(
    (cluster) => !links.some((link) => link.cluster_id === cluster.id),
  );
  return (
    <section className="mt-5 rounded-md border border-border bg-card p-4">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h2 className="text-sm font-semibold">Project settings</h2>
          <label className="mt-4 block text-xs text-muted-foreground" htmlFor="project-name">
            Display name
          </label>
          <div className="mt-1 flex gap-2">
            <Input
              id="project-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={busy || name.trim() === project.name}
              onClick={onSave}
            >
              Save
            </Button>
          </div>
          <div className="mt-4">
            <span className="text-xs text-muted-foreground">Registered folder</span>
            <p className="mt-1 break-all font-mono text-xs">{displayPath(project.root_path)}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void window.cmlDesktop?.openPath(project.root_path)}
              >
                <FolderOpen className="h-3.5 w-3.5" /> Open
              </Button>
              <Button variant="outline" size="sm" disabled={busy} onClick={onReconnect}>
                Reconnect moved folder
              </Button>
            </div>
          </div>
          <div className="mt-5">
            <h3 className="text-sm font-semibold">Connected clusters</h3>
            <div className="mt-2 space-y-2">
              {links.map((link) => (
                <div
                  key={link.cluster_id}
                  className="flex items-center justify-between gap-3 text-xs"
                >
                  <span className="truncate">
                    {link.cluster_name} <span className="text-muted-foreground">({link.role})</span>
                  </span>
                  {link.role !== "primary" && (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => onUnlink(link.cluster_id)}
                    >
                      Unlink
                    </button>
                  )}
                </div>
              ))}
            </div>
            {available.length > 0 && (
              <div className="mt-3 flex gap-2">
                <select
                  aria-label="Cluster to link"
                  className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm"
                  value={linkTarget}
                  onChange={(event) => setLinkTarget(event.target.value)}
                >
                  <option value="">Choose cluster</option>
                  {available.map((cluster) => (
                    <option key={cluster.id} value={cluster.id}>
                      {cluster.name}
                    </option>
                  ))}
                </select>
                <Button variant="outline" size="sm" disabled={!linkTarget || busy} onClick={onLink}>
                  Link
                </Button>
              </div>
            )}
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Use <code>.cmlignore</code> in the project root to exclude local paths. Git-ignored,
            generated, dependency, secret, and oversized files are excluded automatically.
          </p>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Reindex one layer</h3>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            Structure rebuilds symbols and relationships. Search rebuilds retrievable text.
            Interpretation refreshes the local-model project synopsis. The active layer remains
            usable until its replacement is ready.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onReindex("structure")}
            >
              Reindex structure
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onReindex("retrieval")}
            >
              Reindex search
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onReindex("interpretation")}
            >
              Refresh interpretation
            </Button>
          </div>
          <div className="mt-6 border-t border-border pt-5">
            <h3 className="text-sm font-semibold text-destructive">Remove from Vault</h3>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              This removes Vault's index and project record. Files in{" "}
              <span className="font-medium text-foreground">{displayPath(project.root_path)}</span>{" "}
              will not be changed.
            </p>
            <Input
              className="mt-3"
              aria-label={`Type ${project.name} to confirm removal`}
              placeholder={`Type ${project.name} to confirm`}
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
            <Button
              variant="outline"
              size="sm"
              className="mt-2 text-destructive"
              disabled={busy || confirmation !== project.name}
              onClick={onRemove}
            >
              <Trash2 className="h-3.5 w-3.5" /> Remove project
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

async function reconnect(
  project: ProjectRecord,
  runAction: (action: () => Promise<unknown>, success: string) => Promise<void>,
) {
  const folders = await window.cmlDesktop?.selectSourceFolders();
  const root = folders?.[0];
  if (!root) return;
  await runAction(
    () => updateProject(project.id, { root_path: root }),
    "Project folder reconnected. Synchronize when you are ready to index the new location.",
  );
}

function Layer({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span>{label}</span>
      <span className="text-right capitalize text-muted-foreground">
        {value.replaceAll("_", " ")}
      </span>
    </div>
  );
}
function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(date);
}
