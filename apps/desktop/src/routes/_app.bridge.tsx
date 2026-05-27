import { createFileRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Cable, Copy, ExternalLink, Shield, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useBackendHealth } from "@/lib/backend";

export const Route = createFileRoute("/_app/bridge")({
  head: () => ({ meta: [{ title: "Bridge" }] }),
  component: BridgeView,
});

function BridgeView() {
  const backend = useBackendHealth();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Cable className="h-4 w-4" />
              Context Bridge
            </div>
            <h1 className="mt-2 font-serif text-3xl">Let other AI apps ask your local memory.</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Bridge exposes selected clusters, style profiles, and expert context to local tools
              like Claude terminal, MCP clients, IDE agents, and scripts.
            </p>
          </div>

          <div className="rounded-md border border-border bg-card p-3">
            <div className="flex items-center gap-3">
              <Switch disabled />
              <div>
                <div className="text-sm font-medium">Bridge off</div>
                <div className="text-xs text-muted-foreground">Setup starts after backend wiring.</div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <BridgeCard
            icon={<ExternalLink className="h-4 w-4" />}
            title="MCP"
            body="Expose tools such as list_clusters, get_cluster_context, and ask_cluster_expert."
          />
          <BridgeCard
            icon={<Terminal className="h-4 w-4" />}
            title="CLI"
            body="Retrieve context from the terminal and pipe it into another local model."
          />
          <BridgeCard
            icon={<Copy className="h-4 w-4" />}
            title="Copy context"
            body="Build a source-grounded prompt packet for manual paste into another AI app."
          />
        </div>

        <section className="mt-8 rounded-md border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Local backend
              </div>
              <p className="mt-1 text-sm">
                {backend.status === "online"
                  ? "Backend is reachable."
                  : backend.status === "checking"
                    ? "Checking backend..."
                    : "Backend is not running."}
              </p>
            </div>
            <code className="rounded-md bg-muted px-2 py-1 text-xs">{backend.url}</code>
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-card p-4">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-muted-foreground" />
            <div className="font-medium">Default privacy boundary</div>
          </div>
          <div className="mt-3 grid gap-2 text-sm text-muted-foreground md:grid-cols-2">
            <div>Allowed vaults: none until enabled</div>
            <div>Allowed clusters: none until selected</div>
            <div>Raw source snippets: blocked by default</div>
            <div>Cluster expert calls: blocked by default</div>
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-card p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Next implementation steps
          </div>
          <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
            <li>Add backend bridge endpoints.</li>
            <li>Add MCP server command registration.</li>
            <li>Add per-cluster bridge permissions.</li>
            <li>Add recent external request log.</li>
          </ul>
          <div className="mt-4 flex gap-2">
            <Button variant="outline" disabled>
              Copy MCP config
            </Button>
            <Button variant="outline" disabled>
              Copy CLI example
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

function BridgeCard({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        {icon}
        {title}
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}
