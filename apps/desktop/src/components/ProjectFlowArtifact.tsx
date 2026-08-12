import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Braces,
  CheckCircle2,
  FileCode2,
  GitBranch,
  ListTree,
  Network,
  Search,
} from "lucide-react";
import {
  getProjectFlowView,
  type ProjectFlow,
  type ProjectFlowStep,
  type ProjectFlowView,
} from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layout/WindowAware";
import { displayPath } from "@/lib/displayPath";

const MAX_QUERY_LENGTH = 500;

export function ProjectFlowWorkspace({
  projectId,
  projectName,
  initialQuery,
}: {
  projectId: string;
  projectName: string;
  initialQuery: string;
}) {
  const [query, setQuery] = useState(initialQuery.slice(0, MAX_QUERY_LENGTH));
  const [submittedQuery, setSubmittedQuery] = useState(initialQuery.slice(0, MAX_QUERY_LENGTH));
  const [view, setView] = useState<ProjectFlowView | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null);
  const [selectedStepIndex, setSelectedStepIndex] = useState(0);
  const [loading, setLoading] = useState(Boolean(initialQuery.trim()));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const nextQuery = initialQuery.slice(0, MAX_QUERY_LENGTH);
    setQuery(nextQuery);
    setSubmittedQuery(nextQuery);
    setSelectedFlowId(null);
    setSelectedStepIndex(0);
  }, [initialQuery, projectId]);

  useEffect(() => {
    if (!submittedQuery.trim()) {
      setView(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getProjectFlowView(projectId, submittedQuery, { signal: controller.signal })
      .then((next) => {
        setView(next);
        setSelectedFlowId(next.primary_flow?.id ?? null);
        setSelectedStepIndex(0);
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Odin could not trace this project flow.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, submittedQuery]);

  const flows = useMemo(
    () => (view?.primary_flow ? [view.primary_flow, ...view.alternatives] : []),
    [view],
  );
  const selectedFlow = flows.find((flow) => flow.id === selectedFlowId) ?? flows[0] ?? null;
  const selectedStep = selectedFlow?.steps[selectedStepIndex] ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <PageHeader className="shrink-0 border-b border-border px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
              <Link to="/projects/$projectId" params={{ projectId }}>
                <ArrowLeft className="h-4 w-4" /> {projectName}
              </Link>
            </Button>
            <h1 className="text-xl font-semibold">Project map</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Trace one behavior through indexed code and inspect the evidence behind every step.
            </p>
          </div>
          <div className="flex items-center border border-border bg-card" aria-label="Project map mode">
            <Button asChild variant="ghost" className="h-9 rounded-none px-3 text-muted-foreground">
              <Link to="/project-map" search={{ project: projectId, mode: "graph", q: submittedQuery }}>
                <Network className="h-4 w-4" /> Graph
              </Link>
            </Button>
            <div className="flex h-9 items-center gap-1.5 border-l border-border bg-accent px-3 text-sm" aria-current="page">
              <GitBranch className="h-4 w-4" /> Flow
            </div>
            <Button asChild variant="ghost" className="h-9 rounded-none border-l border-border px-3 text-muted-foreground">
              <Link to="/project-map" search={{ project: projectId, mode: "tree", q: submittedQuery }}>
                <ListTree className="h-4 w-4" /> Tree
              </Link>
            </Button>
          </div>
        </div>
        <form
          className="mt-4 flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmittedQuery(query.trim());
          }}
        >
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={query}
              maxLength={MAX_QUERY_LENGTH}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-9"
              placeholder="Show how source enrichment reaches storage"
              aria-label="Flow question"
            />
          </div>
          <Button type="submit" disabled={!query.trim() || loading}>
            {loading ? "Tracing…" : "Trace flow"}
          </Button>
        </form>
      </PageHeader>

      {error ? (
        <div className="m-6 border border-destructive/40 px-4 py-3 text-sm text-destructive" role="alert">
          {error}
        </div>
      ) : !submittedQuery.trim() ? (
        <FlowPrompt projectName={projectName} onChoose={(value) => { setQuery(value); setSubmittedQuery(value); }} />
      ) : loading ? (
        <div className="grid min-h-[560px] flex-1 gap-5 p-6 lg:grid-cols-[minmax(0,1fr)_320px]" aria-label="Tracing project flow">
          <div className="animate-pulse bg-muted/35" />
          <div className="animate-pulse bg-muted/25" />
        </div>
      ) : view ? (
        <FlowResult
          view={view}
          flows={flows}
          selectedFlow={selectedFlow}
          selectedStep={selectedStep}
          selectedStepIndex={selectedStepIndex}
          onSelectFlow={(id) => { setSelectedFlowId(id); setSelectedStepIndex(0); }}
          onSelectStep={setSelectedStepIndex}
          onChooseCandidate={(value) => { setQuery(value); setSubmittedQuery(value); }}
        />
      ) : null}
    </div>
  );
}

function FlowPrompt({ projectName, onChoose }: { projectName: string; onChoose: (query: string) => void }) {
  const prompts = [
    "Show how a request enters and moves through the system",
    "Trace the main data-processing pipeline",
    "Show how stored data reaches the user interface",
  ];
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        <Braces className="h-8 w-8 text-muted-foreground" />
        <h2 className="mt-4 text-lg font-semibold">Choose one behavior to trace</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
          Odin will build a small evidence-backed path through {projectName}. It will not display the entire project graph.
        </p>
        <div className="mt-6 divide-y divide-border border-y border-border">
          {prompts.map((prompt) => (
            <button key={prompt} type="button" className="flex w-full items-center justify-between gap-4 py-3 text-left text-sm hover:text-primary" onClick={() => onChoose(prompt)}>
              {prompt}<ArrowRight className="h-4 w-4 shrink-0" />
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}

function FlowResult({
  view,
  flows,
  selectedFlow,
  selectedStep,
  selectedStepIndex,
  onSelectFlow,
  onSelectStep,
  onChooseCandidate,
}: {
  view: ProjectFlowView;
  flows: ProjectFlow[];
  selectedFlow: ProjectFlow | null;
  selectedStep: ProjectFlowStep | null;
  selectedStepIndex: number;
  onSelectFlow: (id: string) => void;
  onSelectStep: (index: number) => void;
  onChooseCandidate: (query: string) => void;
}) {
  if (!selectedFlow) {
    return <FlowNotFound view={view} onChooseCandidate={onChooseCandidate} />;
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0"><FlowStatus view={view} /></div>
      {flows.length > 1 ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-3 sm:px-6">
          <span className="mr-1 text-xs text-muted-foreground">Candidate paths</span>
          {flows.map((flow, index) => (
            <Button key={flow.id} type="button" size="sm" variant={flow.id === selectedFlow.id ? "secondary" : "ghost"} onClick={() => onSelectFlow(flow.id)}>
              {index === 0 ? "Best match" : `Alternative ${index}`}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 overflow-y-auto xl:grid-cols-[minmax(0,1fr)_360px] xl:overflow-hidden">
        <main className="min-w-0 p-4 sm:p-6 xl:overflow-y-auto">
          <div className="mx-auto max-w-3xl">
            <section aria-labelledby="flow-answer-title">
              <p className="text-xs font-medium text-muted-foreground">In plain English</p>
              <h2 id="flow-answer-title" className="mt-2 text-pretty text-2xl font-semibold leading-tight">
                {selectedFlow.overview.answer}
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                {selectedFlow.overview.meaning}
              </p>
            </section>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 className="mt-8 text-base font-semibold">What happens, step by step</h3>
              </div>
              <span className="text-xs text-muted-foreground">
                {selectedFlow.steps.length} verified {selectedFlow.steps.length === 1 ? "step" : "steps"}
              </span>
            </div>
            <ol className="mt-4 divide-y divide-border border-y border-border">
              {selectedFlow.steps.map((step, index) => (
                <li key={step.node.id}>
                  <button
                    type="button"
                    className={`grid w-full gap-3 px-2 py-5 text-left transition-colors motion-reduce:transition-none sm:grid-cols-[36px_minmax(0,1fr)] ${selectedStepIndex === index ? "bg-accent" : "hover:bg-muted/40"}`}
                    aria-current={selectedStepIndex === index ? "step" : undefined}
                    onClick={() => onSelectStep(index)}
                  >
                    <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border text-xs font-medium" aria-hidden="true">
                      {step.ordinal}
                    </span>
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="text-sm font-semibold">{step.plain_label}</span>
                        <span className="text-xs text-muted-foreground">{humanize(step.node.kind)}</span>
                      </span>
                      <span className="mt-2 block max-w-2xl text-sm leading-6">{step.what_happens}</span>
                      <span className="mt-1.5 block max-w-2xl text-xs leading-5 text-muted-foreground">
                        Why it matters: {step.why_it_matters}
                      </span>
                      <span className="mt-3 block truncate font-mono text-[11px] text-muted-foreground">
                        {step.node.label} · {displayPath(step.node.relative_path)}{step.node.start_line ? `:${step.node.start_line}` : ""}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-xs text-muted-foreground">
              Odin examined {view.diagnostics.examined_edges.toLocaleString()} indexed relationships in {Math.round(view.diagnostics.elapsed_ms).toLocaleString()} ms.
            </p>
            <FlowAnalysis view={view} />
          </div>
        </main>
        {selectedStep ? <FlowInspector step={selectedStep} /> : null}
      </div>
    </div>
  );
}

function FlowAnalysis({ view }: { view: ProjectFlowView }) {
  const observations = view.analysis?.observations ?? [];
  const exactTests = view.analysis?.test_impact?.exact_tests ?? [];
  if (!observations.length && !exactTests.length && !(view.analysis?.limitations ?? []).length) return null;
  return (
    <section className="mt-8 border-t border-border pt-5" aria-labelledby="flow-lens-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{humanize(view.lens)} lens</p>
          <h2 id="flow-lens-title" className="mt-1 text-sm font-medium">{view.analysis.title}</h2>
        </div>
        <p className="max-w-2xl text-xs leading-5 text-muted-foreground">{view.analysis.summary}</p>
      </div>
      {observations.length ? (
        <div className="mt-3 grid border-y border-border md:grid-cols-2">
          {observations.slice(0, 4).map((item, index) => (
            <div key={`${item.kind}:${item.label}:${index}`} className="min-w-0 border-b border-border px-3 py-3 last:border-b-0 md:[&:nth-child(odd)]:border-r md:[&:nth-last-child(-n+2)]:border-b-0">
              <div className="truncate text-xs font-medium">{item.label}</div>
              <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">{item.detail}</p>
            </div>
          ))}
        </div>
      ) : null}
      {observations.length > 4 ? (
        <details className="border-b border-border">
          <summary className="cursor-pointer py-3 text-xs font-medium text-muted-foreground hover:text-foreground">
            Show {observations.length - 4} more supporting {observations.length - 4 === 1 ? "signal" : "signals"}
          </summary>
          <div className="grid border-t border-border md:grid-cols-2">
            {observations.slice(4).map((item, index) => (
              <div key={`${item.kind}:${item.label}:${index + 4}`} className="min-w-0 border-b border-border px-3 py-3 last:border-b-0 md:[&:nth-child(odd)]:border-r">
                <div className="break-words text-xs font-medium">{item.label}</div>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{item.detail}</p>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {exactTests.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Coverage maps this path to {exactTests.length} exact {exactTests.length === 1 ? "test" : "tests"}.
        </p>
      ) : null}
      {(view.analysis.limitations ?? []).map((limitation) => (
        <p key={limitation} className="mt-2 text-[11px] leading-4 text-muted-foreground">{limitation}</p>
      ))}
    </section>
  );
}

function FlowStatus({ view }: { view: ProjectFlowView }) {
  const stale = view.freshness.changed_file_count > 0 || view.freshness.structure_status === "stale";
  return (
    <div className={stale || view.warnings.length ? "bg-amber-500/10" : "bg-card/40"}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2 text-xs sm:px-6">
        <span className="flex items-center gap-2">
          {stale || view.warnings.length ? <AlertTriangle className="h-4 w-4 text-amber-700" /> : <CheckCircle2 className="h-4 w-4 text-emerald-700" />}
          {stale ? `Last indexed snapshot · ${view.freshness.changed_file_count} changed files excluded` : "Current indexed snapshot"}
        </span>
        <span>{view.indexed_commit ? `Commit ${view.indexed_commit.slice(0, 8)}` : "Folder snapshot"}</span>
      </div>
      {view.warnings.length ? (
        <div className="border-b border-border px-4 py-2 text-xs leading-5 text-amber-900 dark:text-amber-200 sm:px-6" role="status">
          {view.warnings.join(" ")}
        </div>
      ) : null}
    </div>
  );
}

function FlowInspector({ step }: { step: ProjectFlowStep }) {
  return (
    <aside className="min-w-0 border-t border-border bg-card p-5 xl:overflow-y-auto xl:border-l xl:border-t-0" aria-label="Flow step evidence">
      <div className="flex items-start gap-3">
        <FileCode2 className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <h2 className="break-words font-medium">{step.plain_label}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{humanize(step.node.kind)}{step.node.language ? ` · ${step.node.language}` : ""}</p>
        </div>
      </div>
      <section className="mt-5">
        <h3 className="text-xs font-medium text-muted-foreground">What happens here</h3>
        <p className="mt-2 text-sm leading-6">{step.what_happens}</p>
        <h3 className="mt-4 text-xs font-medium text-muted-foreground">Why it matters</h3>
        <p className="mt-2 text-sm leading-6">{step.why_it_matters}</p>
      </section>
      <div className="mt-5 border-y border-border py-4 text-xs">
        <div className="text-muted-foreground">What Odin verified</div>
        <div className="mt-1">{step.technical_detail}</div>
        <div className="mt-3 text-muted-foreground">Language and location</div>
        <div className="mt-1">{humanize(step.node.kind)}{step.node.language ? ` · ${step.node.language}` : ""}</div>
      </div>
      {step.source_context ? (
        <section className="mt-5">
          <h3 className="text-xs font-medium text-muted-foreground">Source context</h3>
          <p className="mt-2 text-xs leading-5">{step.source_context}</p>
        </section>
      ) : null}
      {step.node.signature ? <pre className="mt-5 overflow-x-auto whitespace-pre-wrap break-words border-b border-border pb-5 font-mono text-xs leading-6">{step.node.signature}</pre> : null}
      <section className="mt-5">
        <h3 className="text-sm font-medium">Evidence</h3>
        <div className="mt-2 divide-y divide-border border-y border-border">
          {step.evidence.map((evidence, index) => (
            <div key={`${evidence.source_id}:${evidence.chunk_id ?? index}`} className="py-3">
              <div className="break-all font-mono text-[11px] text-muted-foreground">
                {displayPath(evidence.relative_path)}{evidence.line_start ? `:${evidence.line_start}` : ""}
              </div>
              {evidence.excerpt ? <p className="mt-2 line-clamp-6 text-xs leading-5">{evidence.excerpt}</p> : null}
              <Button asChild size="sm" variant="ghost" className="mt-2 -ml-2">
                <Link to="/sources" search={{ source: evidence.source_id }}>Open source</Link>
              </Button>
            </div>
          ))}
        </div>
      </section>
      {step.connection_to_next ? (
        <section className="mt-5 border-t border-border pt-4 text-xs leading-5 text-muted-foreground">
          Next relationship: {step.connection_to_next.label} · {humanize(step.connection_to_next.confidence)}
          {step.connection_to_next.source_line ? ` · line ${step.connection_to_next.source_line}` : ""}
        </section>
      ) : null}
    </aside>
  );
}

function FlowNotFound({
  view,
  onChooseCandidate,
}: {
  view: ProjectFlowView;
  onChooseCandidate: (query: string) => void;
}) {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        <GitBranch className="h-8 w-8 text-muted-foreground" />
        <h2 className="mt-4 text-lg font-semibold">No verified execution path found</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Odin found relevant project areas but could not connect them with verified execution relationships. Try a route, function, or entrypoint name.
        </p>
        {view.candidates.length ? (
          <div className="mt-6 divide-y divide-border border-y border-border">
            {view.candidates.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                className="flex w-full items-center justify-between gap-4 py-3 text-left hover:text-primary"
                onClick={() => onChooseCandidate(`Trace ${candidate.qualified_id}`)}
              >
                <span>
                  <span className="block text-sm font-medium">{candidate.label}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{displayPath(candidate.relative_path)} · {humanize(candidate.kind)}</span>
                </span>
                <ArrowRight className="h-4 w-4 shrink-0" />
              </button>
            ))}
          </div>
        ) : null}
        {view.warnings.map((warning) => <p key={warning} className="mt-3 text-xs text-muted-foreground">{warning}</p>)}
      </div>
    </main>
  );
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
