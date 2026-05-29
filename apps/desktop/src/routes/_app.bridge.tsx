import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Cable, Copy, ExternalLink, Shield, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  getBridgeStatus,
  listBridgeRequests,
  useBackendHealth,
  type BridgeRequest,
  type BridgeStatus,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/bridge")({
  head: () => ({ meta: [{ title: "Bridge" }] }),
  component: BridgeView,
});

function BridgeView() {
  const backend = useBackendHealth();
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [requests, setRequests] = useState<BridgeRequest[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadBridgeState() {
      if (backend.status !== "online") return;
      try {
        const [nextStatus, nextRequests] = await Promise.all([
          getBridgeStatus(),
          listBridgeRequests(),
        ]);
        if (!cancelled) {
          setStatus(nextStatus);
          setRequests(nextRequests);
        }
      } catch {
        if (!cancelled) {
          setStatus(null);
          setRequests([]);
        }
      }
    }

    loadBridgeState();
    const id = window.setInterval(loadBridgeState, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [backend.status]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Cable className="h-4 w-4" />
              Context Bridge
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">Context Bridge</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Bridge will expose selected clusters, style profiles, and expert context to local tools
              like Claude terminal, MCP clients, IDE agents, and scripts. The backend status is visible now;
              permissions and client setup are the next implementation step.
            </p>
          </div>

          <div className="rounded-md border border-border bg-card p-3">
            <div className="flex items-center gap-3">
              <Switch disabled />
              <div>
                <div className="text-sm font-medium">
                  {status?.enabled ? "Bridge running" : "Setup pending"}
                </div>
                <div className="text-xs text-muted-foreground">
                  HTTP API {status?.http_api ?? "checking"}
                </div>
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
            Recent context requests
          </div>
          {requests.length > 0 ? (
            <div className="mt-3 divide-y divide-border text-sm">
              {requests.slice(0, 5).map((request) => (
                <div key={request.id} className="grid grid-cols-[120px_1fr_90px] gap-3 py-2">
                  <span className="truncate text-muted-foreground">{request.client_name}</span>
                  <span className="truncate">{request.query}</span>
                  <span className="text-right text-xs text-muted-foreground">{request.mode}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              No external context requests yet.
            </p>
          )}
          <div className="mt-4 flex gap-2">
            <div className="rounded-md border border-dashed border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
              MCP config and CLI examples will appear here after bridge permissions are implemented.
            </div>
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
