import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Clock3,
  Code2,
  FolderOpen,
  GitBranch,
  RefreshCw,
  Send,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  cancelProjectRun,
  createChatSession,
  getProject,
  getProjectRun,
  linkProjectCluster,
  listClusters,
  listProjectLinks,
  listProjectRuns,
  reindexProject,
  removeProject,
  synchronizeProject,
  unlinkProjectCluster,
  updateProject,
  type ProjectIndexRunRecord,
  type ProjectRecord,
  type ProjectLinkRecord,
  type ClusterRecord,
} from "@/lib/backend";
import { displayPath } from "@/lib/displayPath";

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
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [name, setName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [links, setLinks] = useState<ProjectLinkRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [linkTarget, setLinkTarget] = useState("");

  const load = useCallback(async () => {
    try {
      const nextProject = await getProject(projectId);
      const [nextRuns, nextLinks, nextClusters] = await Promise.all([
        listProjectRuns(projectId, 12),
        listProjectLinks(projectId),
        listClusters(nextProject.vault_id),
      ]);
      setProject(nextProject);
      setRuns(nextRuns);
      setLinks(nextLinks);
      setClusters(nextClusters);
      setName(nextProject.name);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Vault could not load this project.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(async () => {
      if (!project?.active_run_id) return;
      try {
        const run = await getProjectRun(projectId, project.active_run_id);
        setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
        if (!["queued", "running"].includes(run.status)) await load();
      } catch {
        // A later aggregate refresh will reconcile transient backend restarts.
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [load, project?.active_run_id, projectId]);

  const activeRun = project?.active_run_id
    ? (runs.find((run) => run.id === project.active_run_id) ?? null)
    : null;
  const languages = useMemo(
    () =>
      Object.entries(project?.languages ?? {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5),
    [project],
  );
  const questions = project?.entrypoints.length
    ? [
        `Explain what starts in ${project.entrypoints[0]}.`,
        "What are the major areas of this project?",
        "Where is request validation handled?",
        "Show the architecture graph for this project.",
      ]
    : [
        "What are the major areas of this project?",
        "Explain the main application flow.",
        "Which configuration controls the runtime?",
        "Show the architecture tree for this project.",
      ];

  async function ask(prompt = question) {
    if (!project || !prompt.trim()) return;
    const normalized = prompt.trim();
    const session = await createChatSession({
      vault_id: project.vault_id,
      title: `${project.name}: ${normalized.slice(0, 52)}`,
      scope_cluster_id: project.primary_cluster_id,
      scope_project_id: project.id,
    });
    window.sessionStorage.setItem(`cml.pendingPrompt.${session.id}`, normalized);
    navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
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
      <div className="mx-auto grid min-h-full max-w-[1500px] grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]">
        <main className="min-w-0 px-4 py-6 sm:px-7 sm:py-8 lg:px-10">
          <Link
            to="/projects"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Projects
          </Link>
          <header className="mt-7 flex flex-wrap items-start justify-between gap-5 border-b border-border pb-7">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="page-title break-words">{project.name}</h1>
                <span className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs text-muted-foreground">
                  <Code2 className="h-3.5 w-3.5" /> Project
                </span>
              </div>
              <p className="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-sm text-muted-foreground">
                {project.default_branch && (
                  <span className="inline-flex items-center gap-1">
                    <GitBranch className="h-3.5 w-3.5" /> {project.default_branch}
                  </span>
                )}
                {commit && <span>Indexed at {commit}</span>}
                {project.changed_file_count > 0 && (
                  <span
                    role="status"
                    className="inline-flex items-center rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] px-2 py-0.5 text-xs font-medium text-foreground"
                    title="Synchronize to include these working-tree changes in Odin answers."
                  >
                    {project.changed_file_count.toLocaleString()}{" "}
                    {project.changed_file_count === 1 ? "change" : "changes"} newer than index
                  </span>
                )}
                <span>{project.source_count.toLocaleString()} files</span>
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
                    () => synchronizeProject(project.id),
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
          </header>

          {activeRun && (
            <RunStrip
              run={activeRun}
              project={project}
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
                  `${layer === "structure" ? "Structure" : "Search"} reindex queued.`,
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

          <section className="mt-8 max-w-3xl">
            <h2 className="text-lg font-semibold">What this project does</h2>
            <p className="mt-3 max-w-[72ch] text-sm leading-7 text-foreground/90">
              {project.brief ||
                "Odin has registered this project. Synchronize it to build a local, searchable overview."}
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {languages.length > 0 && (
                <span>{languages.map(([language]) => language).join(", ")}</span>
              )}
              {project.workspace_count > 0 && (
                <span>{project.workspace_count} packages or workspaces</span>
              )}
              <span>Updated {formatDate(project.updated_at)}</span>
            </div>
          </section>

          <section className="mt-10 max-w-4xl border-t border-border pt-8">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Ask this project</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Answers stay scoped to this project and cite the indexed evidence they use.
                </p>
              </div>
              <span className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground">
                Scope: {project.name}
              </span>
            </div>
            <div className="mt-5 rounded-md border border-border bg-card p-3 focus-within:border-primary/60">
              <Textarea
                aria-label="Ask this project"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask how something works, where it is defined, or what depends on it…"
                className="min-h-28 resize-y border-0 bg-transparent p-2 shadow-none focus-visible:ring-0"
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void ask();
                }}
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
                <span className="text-xs text-muted-foreground">Ctrl + Enter to ask</span>
                <Button size="sm" disabled={!question.trim()} onClick={() => void ask()}>
                  <Send className="h-4 w-4" /> Ask Odin
                </Button>
              </div>
            </div>
            <div className="mt-4 grid gap-1 sm:grid-cols-2">
              {questions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="rounded px-2 py-2 text-left text-sm text-muted-foreground hover:bg-card hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => void ask(item)}
                >
                  {item} <ArrowRight className="ml-1 inline h-3.5 w-3.5" />
                </button>
              ))}
            </div>
          </section>
        </main>

        <aside className="min-w-0 border-t border-border px-5 py-7 xl:border-l xl:border-t-0">
          <h2 className="text-sm font-semibold">Index health</h2>
          <div className="mt-5 divide-y divide-border border-y border-border">
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
          <section className="mt-7">
            <h3 className="text-sm font-medium">Freshness</h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {commit ? `Indexed commit ${commit}.` : "Indexed from the registered local folder."}{" "}
              {project.changed_file_count
                ? `${project.changed_file_count} working-tree changes are newer than the index.`
                : "Synchronize after changing the repository."}
            </p>
          </section>
          {project.entrypoints.length > 0 && (
            <section className="mt-7">
              <h3 className="text-sm font-medium">Entry points</h3>
              <ul className="mt-2 space-y-2">
                {project.entrypoints.slice(0, 6).map((entry) => (
                  <li key={entry} className="break-all font-mono text-xs text-muted-foreground">
                    {entry}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className="mt-8">
            <h3 className="text-sm font-medium">Recent runs</h3>
            <div className="mt-2 space-y-3">
              {runs.slice(0, 5).map((run) => (
                <div key={run.id} className="border-l border-border pl-3 text-xs">
                  <div className="font-medium capitalize">{run.status.replaceAll("_", " ")}</div>
                  <div className="mt-1 text-muted-foreground">
                    {run.phase.replaceAll("_", " ")} · {formatDate(run.updated_at)}
                  </div>
                </div>
              ))}
            </div>
            <Link to="/tasks" className="mt-4 inline-flex text-sm text-primary">
              View tasks
            </Link>
          </section>
          <p className="mt-8 text-xs leading-5 text-muted-foreground">
            Odin reads eligible files locally. It does not execute or modify repository code.
          </p>
        </aside>
      </div>
    </div>
  );
}

function RunStrip({
  run,
  project,
  onCancel,
}: {
  run: ProjectIndexRunRecord;
  project: ProjectRecord;
  onCancel: () => void;
}) {
  const total = run.phase_total_count || run.eligible_total;
  const complete = run.phase_completed_count || run.completed_count;
  const percent = total ? Math.min(100, Math.round((complete / total) * 100)) : 0;
  const phase = projectRunPhase(run.phase);
  return (
    <section
      aria-label="Project indexing progress"
      className="mt-5 rounded-md border border-border bg-card px-4 py-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Clock3 className="h-4 w-4 text-primary" />
            <span>Step {phase.step} of 4</span>
            <span aria-hidden="true" className="text-muted-foreground">
              ·
            </span>
            <span>{phase.label}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {total
              ? `${complete.toLocaleString()} / ${total.toLocaleString()} files in this phase`
              : "Preparing this phase"}{" "}
            · the active{" "}
            {project.active_retrieval_snapshot_id
              ? "index remains available"
              : "index is being prepared"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            <Square className="h-3.5 w-3.5" /> Cancel
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to="/tasks">View task</Link>
          </Button>
        </div>
      </div>
      <div
        className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"
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

function projectRunPhase(value: string) {
  const phase = value.toLowerCase();
  if (phase.startsWith("discover") || phase === "candidate_build")
    return { step: 1, label: "Discovering files" };
  if (phase.startsWith("structure")) return { step: 2, label: "Building structure" };
  if (phase.startsWith("retrieval")) return { step: 3, label: "Preparing search" };
  return { step: 4, label: "Activating index" };
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
  onReindex: (layer: "structure" | "retrieval") => void;
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
            Structure rebuilds symbols and relationships. Search rebuilds retrievable text. The
            active layer remains usable until its replacement is ready.
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
          </div>
          <div className="mt-6 border-t border-border pt-5">
            <h3 className="text-sm font-semibold text-destructive">Remove from Vault</h3>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              This removes Vault's index and project record. Files in{" "}
              <span className="font-medium text-foreground">
                {displayPath(project.root_path)}
              </span>{" "}
              will not be
              changed.
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
