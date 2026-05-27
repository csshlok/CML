import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useStore, sourceStateLabel, Source } from "@/lib/mockStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ClusterDot } from "@/components/ClusterChip";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { File, Link2, FileText, Image, Plus, RefreshCw, Trash2 } from "lucide-react";

export const Route = createFileRoute("/_app/sources")({
  head: () => ({ meta: [{ title: "Sources" }] }),
  component: SourcesView,
});

const typeIcon = {
  file: File,
  link: Link2,
  note: FileText,
  image: Image,
};

function SourcesView() {
  const { sources, clusters, addSource, reindexSource, removeSource } = useStore();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Source | null>(null);

  const filtered = sources.filter((s) =>
    s.title.toLowerCase().includes(q.toLowerCase()),
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-6 py-4">
        <h1 className="font-serif text-2xl">Sources</h1>
        <Input
          placeholder="Search sources…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="ml-4 h-8 max-w-xs"
        />
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() =>
            addSource({ title: "Untitled note", type: "note", state: "waiting" })
          }
        >
          <Plus className="mr-1.5 h-4 w-4" /> Add source
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Drop files, links, screenshots, or notes to begin.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-6 py-2 font-normal">Title</th>
                <th className="px-3 py-2 font-normal">Type</th>
                <th className="px-3 py-2 font-normal">Cluster</th>
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-6 py-2 font-normal" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => {
                const Icon = typeIcon[s.type];
                const cluster = clusters.find((c) => c.id === s.clusterId);
                return (
                  <tr
                    key={s.id}
                    className="cursor-pointer border-b border-border hover:bg-accent/50"
                    onClick={() => setSelected(s)}
                  >
                    <td className="flex items-center gap-2 px-6 py-2.5">
                      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="truncate">{s.title}</span>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">{s.type}</td>
                    <td className="px-3 py-2.5">
                      {cluster ? (
                        <span className="inline-flex items-center gap-1.5">
                          <ClusterDot tint={cluster.tint} />
                          <span className="text-muted-foreground">{cluster.name}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <StateChip state={s.state} />
                    </td>
                    <td className="px-6 py-2.5 text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          reindexSource(s.id);
                        }}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeSource(s.id);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent className="w-[420px] sm:max-w-[420px]">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="font-serif">{selected.title}</SheetTitle>
              </SheetHeader>
              <div className="mt-4 space-y-4 text-sm">
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span>{selected.type}</span>
                  <span>·</span>
                  <StateChip state={selected.state} />
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Summary
                  </div>
                  <p className="mt-1">{selected.summary || "—"}</p>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Extracted text
                  </div>
                  <p className="mt-1 max-h-48 overflow-y-auto rounded-md border border-border bg-card p-3 text-xs leading-relaxed">
                    {selected.preview || "No preview available."}
                  </p>
                </div>
                {selected.state === "failed" && (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                    <div className="font-medium text-destructive">Extraction failed</div>
                    <p className="mt-1 text-muted-foreground">
                      We couldn't read this source. Try reindexing or open the file to check it.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => reindexSource(selected.id)}>
                        Retry
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => { removeSource(selected.id); setSelected(null); }}>
                        Remove
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function StateChip({ state }: { state: Source["state"] }) {
  const color =
    state === "indexed"
      ? "var(--status-ready)"
      : state === "failed"
      ? "var(--status-issue)"
      : "var(--status-learning)";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {sourceStateLabel[state]}
    </span>
  );
}