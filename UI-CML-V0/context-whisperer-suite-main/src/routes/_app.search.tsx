import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useStore } from "@/lib/mockStore";
import { Input } from "@/components/ui/input";
import { ClusterDot } from "@/components/ClusterChip";

export const Route = createFileRoute("/_app/search")({
  head: () => ({ meta: [{ title: "Search" }] }),
  component: SearchView,
});

function SearchView() {
  const { sources, clusters, chats } = useStore();
  const [q, setQ] = useState("");
  const ql = q.toLowerCase();
  const matchedSources = q ? sources.filter((s) => s.title.toLowerCase().includes(ql)) : [];
  const matchedClusters = q ? clusters.filter((c) => c.name.toLowerCase().includes(ql)) : [];
  const matchedChats = q ? chats.filter((c) => c.title.toLowerCase().includes(ql)) : [];

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="font-serif text-3xl">Search</h1>
      <Input
        autoFocus
        placeholder="Search across your vault…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="mt-6"
      />
      {q && (
        <div className="mt-8 space-y-6 text-sm">
          {matchedClusters.length > 0 && (
            <section>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Clusters</div>
              <div className="mt-2 space-y-1">
                {matchedClusters.map((c) => (
                  <Link
                    key={c.id}
                    to="/clusters/$clusterId"
                    params={{ clusterId: c.id }}
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent"
                  >
                    <ClusterDot tint={c.tint} /> {c.name}
                  </Link>
                ))}
              </div>
            </section>
          )}
          {matchedSources.length > 0 && (
            <section>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Sources</div>
              <div className="mt-2 space-y-1">
                {matchedSources.map((s) => (
                  <div key={s.id} className="rounded-md px-2 py-1.5 hover:bg-accent">{s.title}</div>
                ))}
              </div>
            </section>
          )}
          {matchedChats.length > 0 && (
            <section>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Chats</div>
              <div className="mt-2 space-y-1">
                {matchedChats.map((c) => (
                  <Link
                    key={c.id}
                    to="/chat/$chatId"
                    params={{ chatId: c.id }}
                    className="block rounded-md px-2 py-1.5 hover:bg-accent"
                  >
                    {c.title}
                  </Link>
                ))}
              </div>
            </section>
          )}
          {matchedClusters.length + matchedSources.length + matchedChats.length === 0 && (
            <p className="text-muted-foreground">No matches.</p>
          )}
        </div>
      )}
    </div>
  );
}