import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Cable,
  Check,
  ChevronDown,
  Clipboard,
  Copy,
  Cpu,
  FileCode2,
  FileText,
  FolderTree,
  GitBranch,
  HardDrive,
  HelpCircle,
  Layers,
  ListTodo,
  Map,
  MessageSquare,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { PageHeader } from "@/components/layout/WindowAware";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  helpArticleById,
  helpArticles,
  helpCategories,
  type HelpArticle,
  type HelpVisualKind,
} from "@/lib/helpContent";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/help")({
  validateSearch: (search: Record<string, unknown>): { article?: string } => ({
    article: typeof search.article === "string" ? search.article : undefined,
  }),
  head: () => ({ meta: [{ title: "Help & FAQ" }] }),
  component: HelpView,
});

const categoryIcons = {
  "getting-started": Sparkles,
  "sources-imports": FileText,
  clusters: Layers,
  "search-retrieval": Search,
  "chat-answers": MessageSquare,
  "odin-projects": FileCode2,
  "map-connections": Map,
  "tasks-automation": ListTodo,
  "models-ocr": Cpu,
  "storage-backups": HardDrive,
  "connections-sharing": Cable,
  "privacy-security": ShieldCheck,
  troubleshooting: Settings2,
} as const;

function HelpView() {
  const { article: requestedArticle } = Route.useSearch();
  const navigate = useNavigate();
  const article = helpArticleById(requestedArticle);
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const articleScrollRef = useRef<HTMLElement>(null);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matchingArticles = useMemo(
    () =>
      normalizedQuery
        ? helpArticles.filter((item) =>
            [item.title, item.summary, item.explanation.join(" "), item.path]
              .join(" ")
              .toLocaleLowerCase()
              .includes(normalizedQuery),
          )
        : helpArticles,
    [normalizedQuery],
  );

  const selectArticle = (id: string) => {
    void navigate({ to: "/help", search: { article: id }, replace: true });
    articleScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const copyText = async (key: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      return;
    }
    setCopied(key);
    window.setTimeout(() => setCopied((current) => (current === key ? null : current)), 1800);
  };

  const category = helpCategories.find((item) => item.id === article.category)!;

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <PageHeader className="border-b border-border bg-background px-5 py-4 lg:px-7">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
          <div className="flex min-w-0 items-center gap-3 lg:w-[250px]">
            <HelpCircle className="h-5 w-5 text-primary" />
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Help &amp; FAQ</h1>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {helpArticles.length} practical answers across {helpCategories.length} categories
              </p>
            </div>
          </div>
          <div className="relative min-w-0 flex-1 lg:max-w-2xl">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search help"
              value={query}
              onInput={(event) => setQuery(event.currentTarget.value)}
              placeholder="Search help"
              className="h-10 bg-card pl-9"
            />
          </div>
          <Button variant="ghost" size="sm" asChild className="w-fit gap-2">
            <Link to="/settings" search={{ section: "profile" }}>
              <ArrowLeft className="h-4 w-4" />
              Back to Settings
            </Link>
          </Button>
        </div>
      </PageHeader>

      <div className="grid min-h-0 min-w-0 flex-1 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[250px_minmax(0,1fr)_210px]">
        <aside className="hidden min-h-0 overflow-y-auto border-r border-border bg-card/30 px-4 py-5 lg:block">
          {normalizedQuery ? (
            <div>
              <div className="px-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {matchingArticles.length} result{matchingArticles.length === 1 ? "" : "s"}
              </div>
              <div className="mt-3 space-y-1">
                {matchingArticles.map((item) => (
                  <ArticleNavButton
                    key={item.id}
                    article={item}
                    active={item.id === article.id}
                    onSelect={selectArticle}
                    showCategory
                  />
                ))}
                {matchingArticles.length === 0 ? (
                  <p className="px-2 py-6 text-sm leading-6 text-muted-foreground">
                    No help article matches this search. Try a feature name, status, or error.
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <nav aria-label="Help categories" className="space-y-1">
              {helpCategories.map((item) => {
                const Icon = categoryIcons[item.id];
                const articles = helpArticles.filter((entry) => entry.category === item.id);
                const activeCategory = article.category === item.id;
                return (
                  <section key={item.id}>
                    <button
                      type="button"
                      onClick={() => selectArticle(articles[0].id)}
                      aria-expanded={activeCategory}
                      className={cn(
                        "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs font-medium uppercase tracking-[0.12em] hover:bg-card",
                        activeCategory ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="min-w-0 flex-1">{item.label}</span>
                      <span className="font-mono text-[10px] tracking-normal text-muted-foreground">
                        {articles.length}
                      </span>
                    </button>
                    {activeCategory ? (
                      <div className="mt-1 space-y-0.5">
                        {articles.map((itemArticle) => (
                          <ArticleNavButton
                            key={itemArticle.id}
                            article={itemArticle}
                            active={itemArticle.id === article.id}
                            onSelect={selectArticle}
                          />
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </nav>
          )}
        </aside>

        <main ref={articleScrollRef} className="min-w-0 overflow-y-auto scroll-smooth px-5 py-7 md:px-9 lg:px-10 xl:px-14">
          <article className="mx-auto max-w-3xl pb-20">
            <label className="mb-6 block lg:hidden">
              <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Help article
              </span>
              <select
                aria-label="Choose a help article"
                value={article.id}
                onChange={(event) => selectArticle(event.target.value)}
                className="mt-2 w-full rounded-md border border-border bg-card px-3 py-2.5 text-sm text-foreground"
              >
                {helpCategories.map((item) => (
                  <optgroup key={item.id} label={item.label}>
                    {helpArticles
                      .filter((entry) => entry.category === item.id)
                      .map((entry) => (
                        <option key={entry.id} value={entry.id}>{entry.title}</option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>Help &amp; FAQ</span>
              <span aria-hidden="true">/</span>
              <span>{category.label}</span>
            </div>
            <h2 className="mt-4 max-w-2xl text-3xl font-semibold leading-tight tracking-[-0.025em] text-foreground">
              {article.title}
            </h2>

            <section id="quick-answer" className="scroll-mt-6 border-b border-border py-7">
              <h3 className="text-lg font-semibold">Quick answer</h3>
              <p className="mt-3 text-[15px] leading-7 text-foreground/85">{article.summary}</p>
              <div className="mt-4 space-y-3 text-sm leading-7 text-muted-foreground">
                {article.explanation.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>
            </section>

            <section id="fix-it" className="scroll-mt-6 border-b border-border py-7">
              <h3 className="text-lg font-semibold">Fix it</h3>
              <ol className="mt-4 space-y-3 pl-6 text-sm leading-6 text-foreground/85 marker:font-medium marker:text-muted-foreground">
                {article.steps.map((step) => (
                  <li key={step} className="pl-2">
                    {step}
                  </li>
                ))}
              </ol>
              <HelpVisual article={article} />
            </section>

            <section id="command-path" className="scroll-mt-6 border-b border-border py-7">
              <h3 className="text-lg font-semibold">Command path</h3>
              <CopyBlock
                value={article.path}
                label="Vault path"
                copied={copied === "path"}
                onCopy={() => void copyText("path", article.path)}
              />
              {article.commands?.map((command, index) => (
                <div key={command.command} className="mt-3">
                  <CopyBlock
                    value={command.command}
                    label="Terminal command"
                    copied={copied === `command-${index}`}
                    onCopy={() => void copyText(`command-${index}`, command.command)}
                  />
                  <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{command.description}</p>
                </div>
              ))}
            </section>

            <section id="what-next" className="scroll-mt-6 border-b border-border py-7">
              <details className="group border-y border-border bg-card/30 px-4 py-1" open>
                <summary className="flex cursor-pointer list-none items-center gap-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                  What Vault does next
                </summary>
                <ol className="mb-4 ml-7 space-y-2 border-l border-border pl-5 text-sm leading-6 text-muted-foreground">
                  {article.plan.map((step, index) => (
                    <li key={step}>
                      <span className="mr-2 font-mono text-xs text-foreground/60">{index + 1}.</span>
                      {step}
                    </li>
                  ))}
                </ol>
              </details>
            </section>

            <section id="related" className="scroll-mt-6 py-7">
              <h3 className="text-lg font-semibold">Related questions</h3>
              <div className="mt-3 divide-y divide-border border-y border-border">
                {article.related.map((id) => {
                  const related = helpArticleById(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => selectArticle(id)}
                      className="flex w-full items-center justify-between gap-4 py-3 text-left text-sm text-primary hover:underline"
                    >
                      {related.title}
                      <span aria-hidden="true">→</span>
                    </button>
                  );
                })}
              </div>
            </section>
          </article>
        </main>

        <aside className="hidden min-h-0 overflow-y-auto border-l border-border px-6 py-8 xl:block">
          <div className="text-sm font-semibold">On this page</div>
          <nav className="mt-4 space-y-3 border-l border-border pl-4 text-sm text-muted-foreground" aria-label="On this page">
            <a className="block hover:text-foreground" href="#quick-answer">Quick answer</a>
            <a className="block hover:text-foreground" href="#fix-it">Fix it</a>
            <a className="block hover:text-foreground" href="#command-path">Command path</a>
            <a className="block hover:text-foreground" href="#what-next">What Vault does next</a>
            <a className="block hover:text-foreground" href="#related">Related questions</a>
          </nav>
          <div className="mt-8 border-t border-border pt-6">
            <p className="text-xs leading-5 text-muted-foreground">
              Still stuck? System health and Tasks usually contain the next concrete action.
            </p>
            <Button variant="outline" size="sm" className="mt-3" asChild>
              <Link to="/settings" search={{ section: "health" }}>Open System health</Link>
            </Button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ArticleNavButton({
  article,
  active,
  onSelect,
  showCategory = false,
}: {
  article: HelpArticle;
  active: boolean;
  onSelect: (id: string) => void;
  showCategory?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(article.id)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "w-full border-l-2 px-3 py-2 text-left text-[13px] leading-5 transition-colors",
        active
          ? "border-primary bg-primary/5 font-medium text-foreground"
          : "border-transparent text-muted-foreground hover:bg-card hover:text-foreground",
      )}
    >
      <span className="line-clamp-2">{article.title}</span>
      {showCategory ? (
        <span className="mt-0.5 block text-[11px] text-muted-foreground">
          {helpCategories.find((item) => item.id === article.category)?.label}
        </span>
      ) : null}
    </button>
  );
}

function CopyBlock({
  value,
  label,
  copied,
  onCopy,
}: {
  value: string;
  label: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="mt-4 overflow-hidden rounded-md border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
        <button
          type="button"
          onClick={onCopy}
          className="flex items-center gap-1.5 rounded px-2 py-1 normal-case tracking-normal hover:bg-muted hover:text-foreground"
          aria-label={`Copy ${label.toLocaleLowerCase()}`}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 font-mono text-[13px] leading-6 text-foreground">
        <code>{value}</code>
      </pre>
    </div>
  );
}

function HelpVisual({ article }: { article: HelpArticle }) {
  return (
    <figure className="mt-7">
      <div className="overflow-hidden rounded-md border border-border bg-background shadow-sm">
        <div className="flex items-center justify-between border-b border-border bg-card/60 px-4 py-2.5">
          <div className="flex items-center gap-2 text-xs font-medium">
            <span className="h-2 w-2 rounded-full bg-primary" />
            {article.visual.title}
          </div>
          <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Visual guide</span>
        </div>
        <VisualScreen kind={article.visual.kind} highlight={article.visual.highlight} />
      </div>
      <figcaption className="mt-2 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
        {article.visual.caption}
      </figcaption>
    </figure>
  );
}

function VisualScreen({ kind, highlight }: { kind: HelpVisualKind; highlight: string }) {
  const visual = visualCopy[kind];
  const Icon = visual.icon;
  return (
    <div className="relative min-h-56 bg-[linear-gradient(to_bottom,transparent_31px,var(--border)_32px)] bg-[length:100%_32px] px-5 py-5 md:px-7">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 text-primary" />
          {visual.heading}
        </div>
        <div className="rounded border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground">Ready</div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          {visual.rows.map((row) => (
            <div key={row} className="flex min-w-0 items-center gap-3 rounded border border-border bg-card px-3 py-2.5 text-xs">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{row}</span>
              <span className="text-muted-foreground">Ready</span>
            </div>
          ))}
        </div>
        <div className="flex min-w-36 flex-col justify-center gap-2">
          <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">Look here</div>
          <div className="relative rounded-md border-2 border-primary bg-primary/5 px-3 py-2 text-center text-xs font-semibold text-foreground shadow-[0_0_0_4px_hsl(var(--primary)/0.12)]">
            {highlight}
            <span className="absolute -left-3 top-1/2 h-px w-3 bg-primary" />
          </div>
          <p className="max-w-40 text-[10px] leading-4 text-muted-foreground">The highlighted control is the next action.</p>
        </div>
      </div>
    </div>
  );
}

const visualCopy: Record<
  HelpVisualKind,
  { heading: string; rows: string[]; icon: typeof Clipboard }
> = {
  sources: { heading: "Sources", rows: ["browser-start.log", "startup-notes.md"], icon: Clipboard },
  clusters: { heading: "Clusters", rows: ["Browser Start Issues · 2 sources", "Research notes · 18 sources"], icon: FolderTree },
  search: { heading: "Search", rows: ["3 matching source passages", "1 related project result"], icon: Search },
  chat: { heading: "Chat", rows: ["Question scoped to selected sources", "Answer with 3 citations"], icon: MessageSquare },
  project: { heading: "Odin project", rows: ["Structure · Ready", "Retrieval · Ready"], icon: FileCode2 },
  map: { heading: "Knowledge map", rows: ["42 relevant sources", "18 evidence-backed connections"], icon: GitBranch },
  tasks: { heading: "Tasks", rows: ["Import sources · Running", "Cluster refresh · Queued"], icon: ListTodo },
  models: { heading: "Models & OCR", rows: ["Chat model · Ready", "Embeddings · Ready"], icon: Cpu },
  storage: { heading: "Storage", rows: ["Library location · Available", "Latest backup · Verified"], icon: HardDrive },
  connections: { heading: "Code connections", rows: ["Connection scope · 1 vault", "Pending reviews · 0"], icon: Cable },
  settings: { heading: "Settings", rows: ["Local model · Ready", "Vault service · Ready"], icon: Settings2 },
};
