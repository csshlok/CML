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
import { PageHeader } from "@/components/layout/WindowAware";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useVisiblePolling } from "@/lib/useVisiblePolling";
import {
  cancelProjectRun,
  createChatSession,
  getProject,
  getProjectChanges,
  getProjectIntelligence,
  getJob,
  getProjectRun,
  linkProjectCluster,
  listClusters,
  listProjectLinks,
  listProjectRuns,
  reindexProject,
  refreshProjectIntelligence,
  removeProject,
  runProjectOperation,
  synchronizeProjectChanges,
  unlinkProjectCluster,
  updateProject,
  type ProjectIndexRunRecord,
  type ProjectRecord,
  type ProjectChangesRecord,
  type ProjectLinkRecord,
  type ProjectIntelligenceSnapshot,
  type ProjectOperationName,
  type ProjectOperationResult,
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
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [name, setName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [links, setLinks] = useState<ProjectLinkRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [linkTarget, setLinkTarget] = useState("");
  const [changes, setChanges] = useState<ProjectChangesRecord | null>(null);
  const [intelligence, setIntelligence] = useState<ProjectIntelligenceSnapshot | null>(null);
  const [overviewBusy, setOverviewBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const nextProject = await getProject(projectId);
      const [runsResult, linksResult, clustersResult, changesResult, intelligenceResult] = await Promise.allSettled([
        listProjectRuns(projectId, 12),
        listProjectLinks(projectId),
        listClusters(nextProject.vault_id),
        getProjectChanges(projectId, 200),
        getProjectIntelligence(projectId),
      ]);
      setProject(nextProject);
      if (runsResult.status === "fulfilled") setRuns(runsResult.value);
      if (linksResult.status === "fulfilled") setLinks(linksResult.value);
      if (clustersResult.status === "fulfilled") setClusters(clustersResult.value);
      if (changesResult.status === "fulfilled") setChanges(changesResult.value);
      if (intelligenceResult.status === "fulfilled") setIntelligence(intelligenceResult.value);
      setName(nextProject.name);
      const unavailable = [
        runsResult.status === "rejected" ? "history" : "",
        linksResult.status === "rejected" ? "links" : "",
        clustersResult.status === "rejected" ? "clusters" : "",
        changesResult.status === "rejected" ? "changes" : "",
        intelligenceResult.status === "rejected" ? "intelligence" : "",
      ].filter(Boolean);
      setMessage(unavailable.length ? `Some project details are unavailable: ${unavailable.join(", ")}.` : null);
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
        .slice(0, 5),
    [project],
  );
  const questions = useMemo(() => (project ? projectQuestions(project) : []), [project]);

  async function ask(prompt = question) {
    if (!project || !prompt.trim()) return;
    const normalized = prompt.trim();
    const visualization = detectProjectVisualizationRequest(normalized);
    if (visualization) {
      navigate({
        to: "/project-map",
        search: { project: project.id, mode: visualization.mode, q: visualization.query },
      });
      return;
    }
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

  async function improveOverview() {
    setOverviewBusy(true);
    setMessage(null);
    try {
      const queued = await refreshProjectIntelligence(projectId, "overview");
      const job = queued.jobs.find((item) => item.job_type === "project_intelligence_overview");
      if (!job) throw new Error("Odin could not queue the overview wording task.");
      const completed = await waitForProjectJob(job.id);
      if (completed.status !== "succeeded") {
        throw new Error(completed.status_detail || completed.last_error || "The local overview wording was not completed.");
      }
      setIntelligence(await getProjectIntelligence(projectId));
      setMessage("Overview wording updated from the active local model. Structured facts remain authoritative.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The overview wording could not be updated.");
    } finally {
      setOverviewBusy(false);
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
          <PageHeader className="mt-7 flex flex-wrap items-start justify-between gap-5 border-b border-border pb-7">
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
                {Boolean(changes?.changed_path_count) && (
                  <span
                    role="status"
                    className="inline-flex items-center rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] px-2 py-0.5 text-xs font-medium text-foreground"
                    title="Synchronize to include these pending file changes in Odin answers."
                  >
                    {changes!.changed_path_count.toLocaleString()}{" "}
                    {changes!.changed_path_count === 1 ? "change" : "changes"} pending for Odin
                  </span>
                )}
                {changes?.working_tree_dirty && (
                  <span
                    className="inline-flex items-center rounded border border-border px-2 py-0.5 text-xs text-muted-foreground"
                    title="Git repository state is reported separately from Odin index freshness."
                  >
                    Git working tree: {changes.repository_changed_path_count.toLocaleString()} changed
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
          {project.structure_status === "stale" && !activeRun && (
            <div
              role="status"
              className="mt-5 flex max-w-4xl flex-wrap items-center justify-between gap-3 border-y border-border py-3"
            >
              <p className="text-sm text-muted-foreground">
                Search includes the latest file changes. Update the map when you need current
                relationships.
              </p>
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
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">What this project does</h2>
              {intelligence?.id && intelligence.interpretation && (
                <Button size="sm" variant="ghost" disabled={overviewBusy} onClick={() => void improveOverview()}>
                  <RefreshCw className={`h-3.5 w-3.5 ${overviewBusy ? "animate-spin motion-reduce:animate-none" : ""}`} />
                  {intelligence.interpretation.generated_synopsis ? "Rewrite locally" : "Improve wording locally"}
                </Button>
              )}
            </div>
            <p className="mt-3 max-w-[72ch] text-sm leading-7 text-foreground/90">
              {intelligence?.interpretation?.generated_synopsis || intelligence?.identity?.purpose || project.brief ||
                "Odin has registered this project. Synchronize it to build a local, searchable overview."}
            </p>
            {intelligence?.interpretation?.generated_synopsis ? (
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Worded by {intelligence.interpretation.generation?.model_id || "your local model"} from {intelligence.interpretation.generated_fact_ids?.length || 0} structured facts. Open the explanation below to inspect provenance.
              </p>
            ) : intelligence?.identity.purpose ? (
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Based on {intelligence.evidence[0]?.label || "a supported root project file"}
                {intelligence.identity.purpose_candidates.length > 1
                  ? ` · ${intelligence.identity.purpose_candidates.length - 1} other supported source${intelligence.identity.purpose_candidates.length === 2 ? "" : "s"}`
                  : ""}
                . Odin keeps source descriptions separate instead of blending them into a generated claim.
              </p>
            ) : intelligence?.layers.identity.unknown_reason ? (
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Purpose is unknown: {intelligence.layers.identity.unknown_reason.detail}
              </p>
            ) : null}
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {languages.length > 0 && (
                <span>{languages.map(([language]) => language).join(", ")}</span>
              )}
              {project.workspace_count > 0 && (
                <span>
                  {project.workspace_count === 1
                    ? "1 package or workspace"
                    : `${project.workspace_count} packages or workspaces`}
                </span>
              )}
              <span>Updated {formatDate(project.updated_at)}</span>
            </div>
            {intelligence && (
              <details className="mt-5 border-t border-border pt-4">
                <summary className="cursor-pointer text-sm font-medium text-foreground">
                  How Odin formed this overview
                </summary>
                <div className="mt-3 space-y-3 text-xs leading-5 text-muted-foreground">
                  <p>
                    {Number(intelligence.architecture.indexed_file_count || project.source_count).toLocaleString()} indexed files
                    {Number(intelligence.architecture.relationship_count || 0) > 0
                      ? ` · ${Number(intelligence.architecture.relationship_count).toLocaleString()} observed relationships`
                      : ""}
                    {Number(intelligence.architecture.community_count || 0) > 0
                      ? ` · ${Number(intelligence.architecture.community_count).toLocaleString()} project areas`
                      : ""}.
                  </p>
                  <p>
                    Snapshot {intelligence.owning_snapshot_id || "not built"}. Each layer reports its own freshness;
                    unavailable Git history, decisions, or coverage do not make indexed code unavailable.
                  </p>
                  {intelligence.interpretation?.generated_synopsis && (
                    <p>
                      Optional wording by {intelligence.interpretation.generation?.model_id || "a local model"}; factual claims are limited to cited overview evidence.
                    </p>
                  )}
                </div>
              </details>
            )}
          </section>

          <ProjectUnderstanding projectId={project.id} changedPaths={changes?.changed_paths ?? []} />

          <section className="mt-10 max-w-4xl border-t border-border pt-8">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Ask about this project</h2>
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
                aria-label="Ask about this project"
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
            <nav
              aria-label="Suggested project questions"
              className="mt-4 grid gap-1 sm:grid-cols-2"
            >
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
            </nav>
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
              {changes
                ? changes.changed_path_count
                  ? `${changes.changed_path_count.toLocaleString()} file changes are pending for Odin.`
                  : "The active Odin snapshot matches the current eligible files."
                : project.changed_file_count
                  ? `${project.changed_file_count.toLocaleString()} file changes may be pending verification.`
                  : "Freshness is being verified."}
              {changes?.working_tree_dirty
                ? ` Git separately reports ${changes.repository_changed_path_count.toLocaleString()} working-tree paths.`
                : changes
                  ? " The Git working tree is clean."
                  : ""}
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

function ProjectUnderstanding({ projectId, changedPaths }: { projectId: string; changedPaths: string[] }) {
  const [selected, setSelected] = useState<ProjectOperationName | null>(null);
  const [result, setResult] = useState<ProjectOperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function inspect(operation: ProjectOperationName) {
    setSelected(operation);
    setLoading(true);
    setError(null);
    try {
      setResult(await runProjectOperation(projectId, {
        operation,
        changed_paths: operation === "coverage" ? changedPaths : undefined,
        compact: true,
      }));
    } catch (nextError) {
      setResult(null);
      setError(nextError instanceof Error ? nextError.message : "Odin could not inspect this project signal.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="mt-10 max-w-4xl border-t border-border pt-8" aria-labelledby="project-understanding-title">
      <h2 id="project-understanding-title" className="text-lg font-semibold">Understand what is happening</h2>
      <p className="mt-1 max-w-[68ch] text-sm leading-6 text-muted-foreground">
        Inspect live work, recorded decisions, or exact test evidence only when you need it.
      </p>
      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Project intelligence views">
        {([
          ["project_state", "Current work"],
          ["decisions", "Decisions"],
          ["coverage", "Test impact"],
        ] as const).map(([operation, label]) => (
          <Button
            key={operation}
            size="sm"
            variant={selected === operation ? "default" : "outline"}
            aria-pressed={selected === operation}
            disabled={loading && selected === operation}
            onClick={() => void inspect(operation)}
          >
            {label}
          </Button>
        ))}
      </div>
      <div className="mt-4 min-h-16 border-y border-border py-4" aria-live="polite">
        {loading ? (
          <p className="text-sm text-muted-foreground">Inspecting {operationLabel(selected)}…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : result ? (
          <ProjectOperationSummary result={result} changedPathCount={changedPaths.length} />
        ) : (
          <p className="text-sm text-muted-foreground">Choose one view. Odin will keep unknown evidence clearly marked instead of guessing.</p>
        )}
      </div>
    </section>
  );
}

function ProjectOperationSummary({ result, changedPathCount }: { result: ProjectOperationResult; changedPathCount: number }) {
  const data = asRecord(result.data);
  if (result.operation === "project_state") {
    if (data.status !== "ready") {
      return <p className="text-sm text-muted-foreground">{textValue(data.unknown_reason) || "Git state is unavailable for this folder."}</p>;
    }
    const live = asRecord(data.live_state);
    const files = asArray(live.files).map(asRecord);
    const counts = asRecord(live.counts);
    const changed = Object.values(counts).reduce<number>((total, value) => total + (Number(value) || 0), 0);
    return (
      <div className="text-sm">
        <p><span className="font-medium">{textValue(live.branch) || "Detached worktree"}</span> · {changed ? `${changed} changed path${changed === 1 ? "" : "s"}` : "working tree clean"}</p>
        <p className="mt-1 text-xs text-muted-foreground">Compared with Odin’s active index: {textValue(live.indexed_relation) || "unknown"}.</p>
        {files.length > 0 && (
          <ul className="mt-3 space-y-1 font-mono text-xs text-muted-foreground">
            {files.slice(0, 6).map((file) => <li key={textValue(file.relative_path)}>{textValue(file.status)} · {textValue(file.relative_path)}</li>)}
            {files.length > 6 && <li>+ {files.length - 6} more</li>}
          </ul>
        )}
      </div>
    );
  }
  if (result.operation === "decisions") {
    const items = asArray(data.items).map(asRecord);
    if (!items.length) return <p className="text-sm text-muted-foreground">No supported project decisions were found.</p>;
    return (
      <ol className="space-y-3">
        {items.slice(0, 5).map((item, index) => (
          <li key={textValue(item.id) || String(index)} className="text-sm">
            <p className="font-medium">{textValue(item.statement)}</p>
            <p className="mt-1 text-xs text-muted-foreground">{textValue(item.status)} · {textValue(item.confidence_class)}{asArray(item.evidence).length ? ` · ${asArray(item.evidence).length} source${asArray(item.evidence).length === 1 ? "" : "s"}` : ""}</p>
          </li>
        ))}
      </ol>
    );
  }
  const exactTests = asArray(data.exact_tests).map(asRecord);
  if (data.status === "unknown") {
    return <p className="text-sm text-muted-foreground">{textValue(data.unknown_reason) || "No coverage map is available."}</p>;
  }
  if (data.known_empty) {
    return <p className="text-sm">Coverage is available, but it maps no tests to the {changedPathCount} pending path{changedPathCount === 1 ? "" : "s"}.</p>;
  }
  if (!exactTests.length) {
    return <p className="text-sm text-muted-foreground">Coverage is available. Select this view after files change to calculate exact test impact.</p>;
  }
  return (
    <div>
      <p className="text-sm font-medium">{exactTests.length} exact test {exactTests.length === 1 ? "match" : "matches"}</p>
      <ul className="mt-3 space-y-1 font-mono text-xs text-muted-foreground">
        {exactTests.slice(0, 8).map((test, index) => <li key={`${textValue(test.test_path)}-${index}`}>{textValue(test.test_path)}{textValue(test.test_name) ? ` · ${textValue(test.test_name)}` : ""}</li>)}
      </ul>
      {data.status === "stale" && <p className="mt-3 text-xs text-muted-foreground">This coverage belongs to a different indexed commit.</p>}
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function operationLabel(operation: ProjectOperationName | null): string {
  return operation === "project_state" ? "current work" : operation === "decisions" ? "decisions" : "test evidence";
}

async function waitForProjectJob(jobId: string) {
  const terminal = new Set(["succeeded", "partial_success", "failed", "cancelled", "manual_review", "blocked_setup_required"]);
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await getJob(jobId);
    if (terminal.has(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("The local overview is still running. You can follow it from Tasks.");
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
          This list is bounded. Synchronization will use the complete detected delta or explain
          why a full refresh is required.
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
