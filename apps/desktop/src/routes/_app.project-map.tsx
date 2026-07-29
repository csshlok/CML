import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProjectGraphWorkspace } from "@/components/ProjectGraphArtifact";
import { getProject, type ProjectRecord } from "@/lib/backend";

type ProjectMapSearch = {
  project: string;
  mode: "graph" | "tree";
  q: string;
};

export const Route = createFileRoute("/_app/project-map")({
  validateSearch: (search: Record<string, unknown>): ProjectMapSearch => ({
    project: typeof search.project === "string" ? search.project : "",
    mode: search.mode === "tree" ? "tree" : "graph",
    q: typeof search.q === "string" ? search.q.slice(0, 500) : "",
  }),
  head: () => ({ meta: [{ title: "Project map" }] }),
  component: ProjectMapPage,
});

function ProjectMapPage() {
  const search = Route.useSearch();
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!search.project) {
      setError("Choose a project before opening its map.");
      return;
    }
    setError(null);
    void getProject(search.project)
      .then((next) => {
        if (!cancelled) setProject(next);
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not open this project map.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [search.project]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md border border-border bg-card p-5">
          <h1 className="text-lg font-semibold">Project map unavailable</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          <Button asChild className="mt-4" size="sm">
            <Link to="/projects">Open projects</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading project map…
      </div>
    );
  }

  return (
    <ProjectGraphWorkspace
      projectId={project.id}
      projectName={project.name}
      initialMode={search.mode}
      initialQuery={search.q}
    />
  );
}
