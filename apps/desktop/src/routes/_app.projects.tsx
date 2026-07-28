import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Code2, FolderOpen, GitBranch, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  listProjectsPage,
  listVaults,
  synchronizeProject,
  type ProjectRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/projects")({
  head: () => ({ meta: [{ title: "Projects" }] }),
  component: ProjectsIndex,
});

function ProjectsIndex() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const vault = (await listVaults())[0] ?? null;
      const page = vault ? await listProjectsPage(vault.id, { limit: 100 }) : null;
      setProjects(page?.items ?? []);
      setNextCursor(page?.next_cursor ?? null);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Vault could not load your projects.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (pathname !== "/projects") return <Outlet />;

  async function synchronize(project: ProjectRecord) {
    setSyncingId(project.id);
    setMessage(null);
    try {
      await synchronizeProject(project.id);
      setMessage(`${project.name} synchronization was queued. Its current index stays available.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The project could not be synchronized.");
    } finally {
      setSyncingId(null);
    }
  }

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const vault = (await listVaults())[0] ?? null;
      if (!vault) return;
      const page = await listProjectsPage(vault.id, { limit: 100, cursor: nextCursor });
      setProjects((current) => [...current, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Vault could not load more projects.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <main className="mx-auto min-h-full max-w-[1200px] px-4 py-6 sm:px-7 sm:py-8 lg:px-10">
        <header className="flex flex-col gap-5 border-b border-border pb-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="page-title">Projects</h1>
            <p className="mt-2 max-w-[68ch] text-sm leading-6 text-muted-foreground">
              Ask questions across code you have indexed with Odin. Repository files stay local and are never executed or modified.
            </p>
          </div>
          <Button variant="outline" className="desktop-window-action" asChild>
            <Link to="/settings" search={{ section: "odin" }}>
              <Code2 className="h-4 w-4" /> Set up Odin
            </Link>
          </Button>
        </header>

        {message && <div role="status" className="mt-5 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground">{message}</div>}

        {loading ? (
          <div className="py-16 text-center text-sm text-muted-foreground">Loading projects…</div>
        ) : projects.length === 0 ? (
          <section className="py-16 text-center">
            <FolderOpen className="mx-auto h-8 w-8 text-muted-foreground" strokeWidth={1.5} />
            <h2 className="mt-4 text-base font-semibold">No projects indexed yet</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              From a project folder in your IDE, run <code className="font-mono text-foreground">odin project add . --name &quot;My Project&quot;</code>. It will appear here after registration.
            </p>
          </section>
        ) : (
          <div className="mt-7 divide-y divide-border border-y border-border">
            {projects.map((project) => {
              const language = Object.entries(project.languages).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "Code";
              const active = Boolean(project.active_run_id);
              return (
                <article key={project.id} className="flex flex-col gap-5 py-5 md:flex-row md:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to="/projects/$projectId" params={{ projectId: project.id }} className="break-words text-base font-semibold hover:text-primary">
                        {project.name}
                      </Link>
                      <Status project={project} />
                    </div>
                    <p className="mt-2 line-clamp-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                      {project.brief || "Synchronize this project to build a local, searchable overview."}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>{language}</span>
                      <span>{project.source_count.toLocaleString()} files</span>
                      <span>{project.discovery_scope === "code" ? "Code only" : "Code and context"}</span>
                      {project.default_branch && <span className="inline-flex items-center gap-1"><GitBranch className="h-3 w-3" /> {project.default_branch}</span>}
                      <span>{freshness(project)}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button variant="outline" size="sm" disabled={active || syncingId === project.id} onClick={() => void synchronize(project)}>
                      <RefreshCw className={`h-3.5 w-3.5 ${syncingId === project.id ? "animate-spin motion-reduce:animate-none" : ""}`} />
                      {active ? "Indexing" : "Synchronize"}
                    </Button>
                    <Button size="sm" asChild>
                      <Link to="/projects/$projectId" params={{ projectId: project.id }}>Open <ArrowRight className="h-3.5 w-3.5" /></Link>
                    </Button>
                  </div>
                </article>
              );
            })}
            {nextCursor ? (
              <div className="py-5 text-center">
                <Button variant="outline" disabled={loadingMore} onClick={() => void loadMore()}>
                  {loadingMore ? "Loading..." : "Load more projects"}
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </main>
    </div>
  );
}

function Status({ project }: { project: ProjectRecord }) {
  const issue = project.status === "issue" || project.structure_status === "issue" || project.retrieval_status === "issue";
  const label = project.active_run_id ? "Indexing" : issue ? "Needs attention" : project.status === "ready" ? "Ready" : project.status.replaceAll("_", " ");
  return <span className={`rounded-full border px-2 py-0.5 text-xs capitalize ${issue ? "border-destructive/40 text-destructive" : "border-border text-muted-foreground"}`}>{label}</span>;
}

function freshness(project: ProjectRecord) {
  if (project.changed_file_count > 0) return `${project.changed_file_count} newer changes`;
  if (project.indexed_commit) return `Indexed at ${project.indexed_commit.slice(0, 8)}`;
  return `Updated ${formatDate(project.updated_at)}`;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}
