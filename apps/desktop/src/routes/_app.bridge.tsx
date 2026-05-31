import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Cable, Copy, ExternalLink, RefreshCw, Shield, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  getBridgeStatus,
  listClusters,
  listBridgeRequests,
  listVaults,
  updateBridgeSettings,
  useBackendHealth,
  type BridgeRequest,
  type BridgeStatus,
  type ClusterRecord,
  type VaultRecord,
} from "@/lib/backend";

export const Route = createFileRoute("/_app/bridge")({
  head: () => ({ meta: [{ title: "Bridge" }] }),
  component: BridgeView,
});

function BridgeView() {
  const backend = useBackendHealth();
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [requests, setRequests] = useState<BridgeRequest[]>([]);
  const [vaults, setVaults] = useState<VaultRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [saving, setSaving] = useState(false);

  async function loadBridgeState(options: { clearOnError?: boolean } = {}) {
    if (backend.status !== "online") return;
    try {
      const [nextStatus, nextRequests, nextVaults, nextClusters] = await Promise.all([
        getBridgeStatus(),
        listBridgeRequests(),
        listVaults(),
        listClusters(),
      ]);
      const vaultIds = new Set(nextVaults.map((vault) => vault.id));
      const clusterIds = new Set(nextClusters.map((cluster) => cluster.id));
      setStatus({
        ...nextStatus,
        allowed_vault_ids: nextStatus.allowed_vault_ids.filter((id) => vaultIds.has(id)),
        allowed_cluster_ids: nextStatus.allowed_cluster_ids.filter((id) => clusterIds.has(id)),
      });
      setRequests(nextRequests);
      setVaults(nextVaults);
      setClusters(nextClusters);
    } catch {
      if (options.clearOnError) {
        setStatus(null);
        setRequests([]);
        setVaults([]);
        setClusters([]);
      }
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function refreshIfMounted() {
      if (cancelled) return;
      await loadBridgeState({ clearOnError: true });
    }

    void refreshIfMounted();
    const id = window.setInterval(refreshIfMounted, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [backend.status]);

  async function patchSettings(payload: Parameters<typeof updateBridgeSettings>[0]) {
    setSaving(true);
    try {
      const updated = await updateBridgeSettings(payload);
      setStatus(updated);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  function toggleVault(id: string) {
    if (!status) return;
    const allowed = status.allowed_vault_ids.includes(id)
      ? status.allowed_vault_ids.filter((vaultId) => vaultId !== id)
      : [...status.allowed_vault_ids, id];
    void patchSettings({ allowed_vault_ids: allowed });
  }

  function toggleCluster(id: string) {
    if (!status) return;
    const allowed = status.allowed_cluster_ids.includes(id)
      ? status.allowed_cluster_ids.filter((clusterId) => clusterId !== id)
      : [...status.allowed_cluster_ids, id];
    void patchSettings({ allowed_cluster_ids: allowed });
  }

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Cable className="h-4 w-4" />
              Bridge
            </div>
            <h1 className="page-title mt-2">Bridge</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Let local AI tools request selected context from this vault. Keep it off until you
              have chosen exactly which vaults and clusters another client can read.
            </p>
            <div className="mt-2 text-xs text-muted-foreground">
              Permissions refresh every minute. Last checked {status?.last_refreshed_at ?? "not yet"}.
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-md border border-border bg-card p-3">
            <div className="flex items-center gap-3">
              <Switch
                checked={Boolean(status?.enabled)}
                disabled={!status || saving}
                onCheckedChange={(checked) => void patchSettings({ enabled: checked })}
              />
              <div>
                <div className="text-sm font-medium">
                  {status?.enabled ? "Bridge running" : "Bridge off"}
                </div>
                <div className="text-xs text-muted-foreground">
                  HTTP API {status?.http_api ?? "checking"}
                </div>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              disabled={saving || backend.status !== "online"}
              aria-label="Refresh Bridge permissions"
              title="Refresh Bridge permissions"
              onClick={() => void loadBridgeState({ clearOnError: true })}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
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
            <div className="font-medium">Permissions</div>
          </div>
          <div className="mt-4 grid gap-6 md:grid-cols-2">
            <div>
              <div className="text-sm font-medium">Allowed vaults</div>
              <div className="mt-2 space-y-1.5">
                {vaults.length > 0 ? (
                  vaults.map((vault) => (
                    <label key={vault.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={Boolean(status?.allowed_vault_ids.includes(vault.id))}
                        disabled={!status || saving}
                        onChange={() => toggleVault(vault.id)}
                      />
                      <span className="truncate">{vault.name}</span>
                    </label>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">No vaults found.</div>
                )}
              </div>
            </div>
            <div>
              <div className="text-sm font-medium">Allowed clusters</div>
              <div className="mt-2 max-h-36 space-y-1.5 overflow-y-auto pr-1">
                {clusters.length > 0 ? (
                  clusters.map((cluster) => (
                    <label key={cluster.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={Boolean(status?.allowed_cluster_ids.includes(cluster.id))}
                        disabled={!status || saving}
                        onChange={() => toggleCluster(cluster.id)}
                      />
                      <span className="truncate">{cluster.name}</span>
                    </label>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">No clusters found.</div>
                )}
              </div>
            </div>
          </div>
          <div className="mt-5 divide-y divide-border border-y border-border">
            <PermissionRow
              label="Raw source text"
              detail="Allow external clients to receive full extracted source text."
              checked={Boolean(status?.allow_raw_snippets)}
              disabled={!status || saving}
              onChange={(checked) => void patchSettings({ allow_raw_snippets: checked })}
            />
            <PermissionRow
              label="Style profiles"
              detail="Allow clients to request cluster style context when available."
              checked={Boolean(status?.allow_style_profile)}
              disabled={!status || saving}
              onChange={(checked) => void patchSettings({ allow_style_profile: checked })}
            />
            <PermissionRow
              label="Local experts"
              detail="Allow clients to call cluster experts after the expert lifecycle is implemented."
              checked={Boolean(status?.allow_expert_calls)}
              disabled={!status || saving}
              onChange={(checked) => void patchSettings({ allow_expert_calls: checked })}
            />
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
            <p className="mt-3 text-sm text-muted-foreground">No external context requests yet.</p>
          )}
          <div className="mt-4 flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(
                  [
                    `POST ${backend.url}/api/v1/bridge/context`,
                    `x-cml-bridge-token: ${status?.bridge_token ?? ""}`,
                    JSON.stringify({
                      query: "...",
                      vault_id: status?.allowed_vault_ids[0] ?? "",
                      client_name: "local-client",
                    }),
                  ].join("\n"),
                );
              }}
            >
              <Copy className="h-3.5 w-3.5" />
              Copy HTTP example
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(
                  `$env:CML_BRIDGE_TOKEN="${status?.bridge_token ?? ""}"\n.\\scripts\\bridge\\cml-bridge.ps1 "summarize my relevant context" -BackendUrl ${backend.url}`,
                );
              }}
            >
              <Terminal className="h-3.5 w-3.5" />
              Copy CLI example
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(
                  JSON.stringify(
                    {
                      command: ".venv\\Scripts\\python.exe",
                      args: ["-m", "backend.app.bridge_mcp"],
                      env: {
                        CML_BACKEND_URL: backend.url,
                        CML_BRIDGE_TOKEN: status?.bridge_token ?? "",
                      },
                    },
                    null,
                    2,
                  ),
                );
              }}
            >
              Copy MCP config
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!status}
              onClick={() => void navigator.clipboard.writeText(status?.bridge_token ?? "")}
            >
              Copy token
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!status || saving}
              onClick={() => void patchSettings({ rotate_token: true })}
            >
              Rotate token
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

function PermissionRow({
  label,
  detail,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{detail}</div>
      </div>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

function BridgeCard({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
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
