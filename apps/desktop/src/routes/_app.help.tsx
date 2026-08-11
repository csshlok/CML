import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Cable,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Cpu,
  FileCode2,
  FileText,
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

            <section id="quick-answer" className="scroll-mt-6 py-7">
              <h3 className="text-lg font-semibold">Quick answer</h3>
              <p className="mt-3 text-[15px] leading-7 text-foreground/85">{article.summary}</p>
              <div className="mt-4 space-y-3 text-sm leading-7 text-muted-foreground">
                {article.explanation.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>
            </section>

            <section id="fix-it" className="scroll-mt-6 py-7">
              <h3 className="text-lg font-semibold">Fix it</h3>
              <ol className="mt-4 space-y-3 pl-6 text-sm leading-6 text-foreground/85 marker:font-medium marker:text-muted-foreground">
                {article.steps.map((step) => (
                  <li key={step} className="pl-2">
                    {step}
                  </li>
                ))}
              </ol>
              <HelpVisual key={article.id} article={article} />
            </section>

            <section id="command-path" className="scroll-mt-6 py-7">
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

            <section id="what-next" className="scroll-mt-6 py-7">
              <details className="group rounded-md bg-card/50 px-4 py-1" open>
                <summary className="flex cursor-pointer list-none items-center gap-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                  What Vault does next
                </summary>
                <ol className="mb-4 ml-7 space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
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
              <div className="mt-3 space-y-1">
                {article.related.map((id) => {
                  const related = helpArticleById(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => selectArticle(id)}
                      className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2.5 text-left text-sm text-primary hover:bg-card hover:underline"
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
  const slides = helpGallerySlides(article);
  const [activeSlide, setActiveSlide] = useState(0);
  const swipeStartRef = useRef<number | null>(null);
  const currentSlide = slides[activeSlide];

  const showSlide = (index: number) => {
    const nextIndex = Math.max(0, Math.min(index, slides.length - 1));
    setActiveSlide(nextIndex);
  };

  const finishSwipe = (clientX: number) => {
    const startX = swipeStartRef.current;
    swipeStartRef.current = null;
    if (startX === null || Math.abs(clientX - startX) < 48) return;
    showSlide(activeSlide + (clientX < startX ? 1 : -1));
  };

  return (
    <figure className="mt-8" aria-label={`${article.visual.title} walkthrough`}>
      <div className="mb-3 flex items-center justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold text-foreground">See it in Vault</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">Real screens with the next control outlined.</p>
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">{activeSlide + 1} of {slides.length}</span>
      </div>
      <div
        className="touch-pan-y overflow-hidden rounded-md border border-border bg-card"
        onPointerDown={(event) => { swipeStartRef.current = event.clientX; }}
        onPointerUp={(event) => finishSwipe(event.clientX)}
        onPointerCancel={() => { swipeStartRef.current = null; }}
      >
        <img key={currentSlide.src} src={currentSlide.src} alt={currentSlide.alt} className="block aspect-[8/5] w-full select-none object-cover object-top" loading="eager" draggable={false} />
      </div>
      <figcaption className="mt-3 flex items-start gap-3">
        <div className="flex shrink-0 gap-1">
          <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Previous walkthrough image" disabled={activeSlide === 0} onClick={() => showSlide(activeSlide - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Next walkthrough image" disabled={activeSlide === slides.length - 1} onClick={() => showSlide(activeSlide + 1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <div className="min-w-0 text-xs leading-5" aria-live="polite">
          <div className="font-medium text-foreground">{currentSlide.title}</div>
          <p className="text-muted-foreground">{currentSlide.caption}</p>
        </div>
      </figcaption>
    </figure>
  );
}

type HelpGallerySlide = { src: string; title: string; caption: string; alt: string };

const gallerySlides: Record<string, HelpGallerySlide> = {
  "sources-add-files": { src: "/help/sources-add-files.png", title: "Add the first files", caption: "In Sources, use the outlined Add files button for a small, familiar set.", alt: "Vault Sources page with mock documents and the Add files button outlined" },
  "sources-ready": { src: "/help/sources-ready.png", title: "Confirm indexing", caption: "Wait for imported rows to show Ready before relying on them in search or chat.", alt: "Vault Sources page with populated mock documents and a Ready source row outlined" },
  "clusters-refresh": { src: "/help/clusters-refresh.png", title: "Refresh unclustered organization", caption: "Refresh organization rebuilds cluster profiles, then assigns eligible unclustered sources.", alt: "Vault Clusters page with mock clusters and Refresh organization outlined" },
  "clusters-moves": { src: "/help/clusters-moves.png", title: "Look for moves between clusters", caption: "Check suggestions separately to compare already-clustered sources with other cluster profiles.", alt: "Vault Clusters page with populated mock clusters and Check suggestions outlined" },
  "search-query": { src: "/help/search-query.png", title: "Search saved evidence", caption: "Enter a phrase, title, tag, or summary in the outlined search field.", alt: "Vault Search page with mock source results and the search field outlined" },
  "chat-scope": { src: "/help/chat-scope.png", title: "Choose the evidence scope", caption: "Use the outlined scope control to search the whole vault or one cluster.", alt: "Vault Chat page with the scope selector outlined" },
  "chat-send": { src: "/help/chat-send.png", title: "Ask the question", caption: "Write a question you can verify, then use Send and inspect the resulting citations.", alt: "Vault Chat page with the Send button outlined" },
  "project-add": { src: "/help/project-add.png", title: "Add a code project", caption: "Choose Add project folder to let Odin index a repository without modifying it.", alt: "Vault Projects page with Add project folder outlined" },
  "map-connections": { src: "/help/map-connections.png", title: "Reveal related clusters", caption: "Connections adds evidence-backed similarity links to the populated knowledge map.", alt: "Vault knowledge map with mock clusters and Connections outlined" },
  "tasks-active": { src: "/help/tasks-active.png", title: "Track active work", caption: "The Active view shows running and queued work with durable status details.", alt: "Vault Tasks page with mock running jobs and Active outlined" },
  "models-manage": { src: "/help/models-manage.png", title: "Manage local models", caption: "Open Manage models to install or select the model Vault uses locally.", alt: "Vault model settings with Manage models outlined" },
  "storage-library": { src: "/help/storage-library.png", title: "Open library security", caption: "Library & security contains the vault location, protection, backup, and deletion controls.", alt: "Vault settings with Library and security outlined" },
  "connections-install": { src: "/help/connections-install.png", title: "Set up Odin", caption: "Install Odin before pairing command-line access or adding code projects.", alt: "Vault code connection settings with Install Odin outlined" },
  "settings-health": { src: "/help/settings-health.png", title: "Check system health", caption: "System health shows whether the vault, models, queue, and OCR are available.", alt: "Vault system health settings with System health outlined" },
};

const defaultSlideForKind: Record<HelpVisualKind, string> = {
  sources: "sources-add-files", clusters: "clusters-moves", search: "search-query",
  chat: "chat-scope", project: "project-add", map: "map-connections", tasks: "tasks-active",
  models: "models-manage", storage: "storage-library", connections: "connections-install",
  settings: "settings-health",
};

const slideForHighlight: Record<string, string> = {
  "Add files": "sources-add-files", Ready: "sources-ready", Unclustered: "sources-ready",
  "Unclustered sources": "sources-ready", "Refresh clustering": "clusters-refresh",
  "Needs attention": "clusters-moves", "Browser Start Issues": "clusters-moves",
  "Connection access": "connections-install", "Delete library": "storage-library",
  "Restart local services": "settings-health",
};

const stepKinds: Array<[RegExp, HelpVisualKind]> = [
  [/\bsource|file|folder|document|citation\b/i, "sources"],
  [/\bcluster|organization|move\b/i, "clusters"],
  [/\bchat|question|answer|scope\b/i, "chat"],
  [/\bsearch|retriev/i, "search"],
  [/\bproject|odin|repository|code\b/i, "project"],
  [/\bmap|connection|relationship\b/i, "map"],
  [/\btask|job|queue|progress\b/i, "tasks"],
  [/\bmodel|ocr|embedding\b/i, "models"],
  [/\bstorage|library|backup|passphrase|delete\b/i, "storage"],
  [/\bpair|bridge|client|share|tunnel\b/i, "connections"],
  [/\bhealth|setting|restart\b/i, "settings"],
];

function helpGallerySlides(article: HelpArticle): HelpGallerySlide[] {
  const slideIds = [slideForHighlight[article.visual.highlight] ?? defaultSlideForKind[article.visual.kind]];
  for (const step of article.steps) {
    const match = stepKinds.find(([pattern]) => pattern.test(step));
    if (match) slideIds.push(defaultSlideForKind[match[1]]);
  }
  if (article.id === "first-ten-minutes") {
    slideIds.splice(0, slideIds.length, "sources-add-files", "sources-ready", "clusters-moves", "chat-scope", "chat-send");
  }
  return [...new Set(slideIds)].slice(0, 5).map((id) => gallerySlides[id]);
}
