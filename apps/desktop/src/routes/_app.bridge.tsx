import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Cable, Copy, ExternalLink, Plus, RefreshCw, Shield, Terminal, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  approveBridgeApprovalRequest,
  createBridgeClient,
  deleteBridgeClient,
  getBridgeStatus,
  listBridgeApprovalRequests,
  listBridgeAuditEvents,
  listBridgeClients,
  listBridgeTokenRotations,
  listClusters,
  listBridgeRequests,
  rejectBridgeApprovalRequest,
  listVaults,
  updateBridgeClient,
  updateBridgeSettings,
  useBackendHealth,
  type BridgeApprovalRequest,
  type BridgeAuditEvent,
  type BridgeClientRecord,
  type BridgeRequest,
  type BridgeStatus,
  type BridgeTokenRotation,
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
  const [approvalRequests, setApprovalRequests] = useState<BridgeApprovalRequest[]>([]);
  const [auditEvents, setAuditEvents] = useState<BridgeAuditEvent[]>([]);
  const [rotations, setRotations] = useState<BridgeTokenRotation[]>([]);
  const [clients, setClients] = useState<BridgeClientRecord[]>([]);
  const [clientName, setClientName] = useState("Local MCP client");
  const [clientToken, setClientToken] = useState<string | null>(null);
  const [vaults, setVaults] = useState<VaultRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [saving, setSaving] = useState(false);

  async function loadBridgeState(options: { clearOnError?: boolean } = {}) {
    if (backend.status !== "online") return;
    try {
      const [nextStatus, nextRequests, nextApprovals, nextAuditEvents, nextRotations, nextClients, nextVaults, nextClusters] = await Promise.all([
        getBridgeStatus(),
        listBridgeRequests(),
        listBridgeApprovalRequests(),
        listBridgeAuditEvents(),
        listBridgeTokenRotations(),
        listBridgeClients(),
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
      setApprovalRequests(nextApprovals);
      setAuditEvents(nextAuditEvents);
      setRotations(nextRotations);
      setClients(nextClients);
      setVaults(nextVaults);
      setClusters(nextClusters);
    } catch {
      if (options.clearOnError) {
        setStatus(null);
        setRequests([]);
        setApprovalRequests([]);
        setAuditEvents([]);
        setRotations([]);
        setClients([]);
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

  async function addBridgeClient() {
    const name = clientName.trim();
    if (!name) return;
    setSaving(true);
    try {
      const created = await createBridgeClient({
        name,
        allowed_vault_ids: status?.allowed_vault_ids ?? [],
        allowed_cluster_ids: status?.allowed_cluster_ids ?? [],
        allow_raw_snippets: Boolean(status?.allow_raw_snippets),
        allow_style_profile: Boolean(status?.allow_style_profile),
        allow_expert_calls: Boolean(status?.allow_expert_calls),
      });
      setClientToken(created.token);
      setClientName("Local MCP client");
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function patchClient(
    client: BridgeClientRecord,
    payload: Parameters<typeof updateBridgeClient>[1],
  ) {
    setSaving(true);
    try {
      const updated = await updateBridgeClient(client.id, payload);
      if ("token" in updated) setClientToken(updated.token);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function removeClient(client: BridgeClientRecord) {
    setSaving(true);
    try {
      await deleteBridgeClient(client.id);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function approveRequest(requestRow: BridgeApprovalRequest) {
    setSaving(true);
    try {
      const created = await approveBridgeApprovalRequest(requestRow.id);
      setClientToken(created.token);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function rejectRequest(requestRow: BridgeApprovalRequest) {
    setSaving(true);
    try {
      await rejectBridgeApprovalRequest(requestRow.id, { detail: "Rejected in CML Bridge settings." });
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  const exampleClientToken = clientToken ?? "<approved-client-token>";

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
              Let local AI tools request selected context from this vault. New clients now request
              approval first, and approved clients keep their own scope, token, and identity notes.
            </p>
            <div className="mt-2 text-xs text-muted-foreground">
              Permissions refresh every minute. Pending approvals {status?.approval_requests_pending ?? 0}. Last checked{" "}
              {status?.last_refreshed_at ?? "not yet"}.
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
          {status?.enabled && status.allowed_vault_ids.length === 0 && (
            <div className="mb-4 rounded-md border border-[var(--status-learning)]/40 bg-[var(--status-learning)]/10 px-3 py-2 text-sm">
              Bridge is on, but no vault is allowed. MCP clients will receive no_active_vault until you allow one.
            </div>
          )}
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
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Pending approvals
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Claimed client names are never treated as verified identity on their own. Review the observed path and
                signature signal before approving.
              </p>
            </div>
            <div className="text-xs text-muted-foreground">
              {approvalRequests.filter((item) => item.status === "pending").length} pending
            </div>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {approvalRequests.filter((item) => item.status === "pending").length > 0 ? (
              approvalRequests
                .filter((item) => item.status === "pending")
                .map((item) => (
                  <div key={item.id} className="grid gap-3 py-3 lg:grid-cols-[1fr_auto]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="truncate text-sm font-medium">{item.claimed_name}</div>
                        <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                          unverified claim
                        </span>
                        <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                          {item.signature_status.replace(/_/g, " ")}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {item.requested_vault_ids.length || 0} vaults / {item.requested_cluster_ids.length || 0} clusters / raw text{" "}
                        {item.allow_raw_snippets ? "requested" : "off"}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Path {item.observed_executable_path || item.executable_path_claim || "not provided"}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Publisher {item.publisher_name || "not available"} / expires {new Date(item.expires_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" disabled={saving} onClick={() => void approveRequest(item)}>
                        Approve
                      </Button>
                      <Button variant="outline" size="sm" disabled={saving} onClick={() => void rejectRequest(item)}>
                        Reject
                      </Button>
                    </div>
                  </div>
                ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">No pending Bridge approval requests.</div>
            )}
          </div>
        </section>

        <section className="mt-4 rounded-md border border-border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Client tokens
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Give each external tool its own token and permission set. Newly created tokens are shown once.
              </p>
            </div>
            <div className="flex min-w-0 gap-2">
              <Input
                value={clientName}
                onChange={(event) => setClientName(event.target.value)}
                className="h-8 w-52"
                aria-label="Bridge client name"
              />
              <Button size="sm" className="gap-1" disabled={saving || !status} onClick={() => void addBridgeClient()}>
                <Plus className="h-3.5 w-3.5" />
                Add
              </Button>
            </div>
          </div>
          {clientToken && (
            <div className="mt-4 rounded-md border border-[var(--status-ready)]/35 bg-[var(--status-ready)]/10 px-3 py-2 text-xs">
              <div className="font-medium">New token</div>
              <button
                type="button"
                className="mt-1 block max-w-full truncate font-mono text-left text-muted-foreground"
                onClick={() => void navigator.clipboard.writeText(clientToken)}
                title="Copy token"
              >
                {clientToken}
              </button>
            </div>
          )}
          <div className="mt-4 divide-y divide-border border-y border-border">
            {clients.length > 0 ? (
              clients.map((client) => (
                <div key={client.id} className="grid gap-3 py-3 lg:grid-cols-[1fr_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{client.name}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {client.enabled ? "enabled" : "disabled"}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {client.allowed_vault_ids.length || 0} vaults / {client.allowed_cluster_ids.length || 0} clusters / raw text {client.allow_raw_snippets ? "on" : "off"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Identity {client.verified_identity ? client.verified_identity_label : "unverified"} / signature{" "}
                      {client.signature_status.replace(/_/g, " ")}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Path {client.observed_executable_path || client.executable_path_claim || "not recorded"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Requests {client.request_count_total} / bytes {client.response_bytes_total.toLocaleString()}
                      {client.last_request_at ? ` / last ${new Date(client.last_request_at).toLocaleString()}` : ""}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Switch
                      checked={client.enabled}
                      disabled={saving}
                      onCheckedChange={(enabled) => void patchClient(client, { enabled })}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={saving}
                      onClick={() => void patchClient(client, { rotate_token: true })}
                    >
                      Rotate
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={saving}
                      aria-label={`Delete ${client.name}`}
                      onClick={() => void removeClient(client)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">No Bridge clients have dedicated tokens yet.</div>
            )}
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
                    `x-cml-bridge-token: ${exampleClientToken}`,
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
                  `$env:CML_BRIDGE_TOKEN="${exampleClientToken}"\n.\\scripts\\bridge\\cml-bridge.ps1 "summarize my relevant context" -BackendUrl ${backend.url}`,
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
                        CML_BRIDGE_TOKEN: exampleClientToken,
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
              disabled={!clientToken}
              onClick={() => clientToken && void navigator.clipboard.writeText(clientToken)}
            >
              Copy approved client token
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
          {rotations.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="text-xs font-medium text-muted-foreground">Token rotation history</div>
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                {rotations.slice(0, 3).map((rotation) => (
                  <div key={rotation.id} className="flex justify-between gap-3">
                    <span>{rotation.reason.replace(/_/g, " ")}</span>
                    <span>{new Date(rotation.rotated_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {auditEvents.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="text-xs font-medium text-muted-foreground">Recent Bridge security events</div>
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                {auditEvents.slice(0, 5).map((event) => (
                  <div key={event.id} className="flex justify-between gap-3">
                    <span className="truncate">{event.event_type.replace(/_/g, " ")}</span>
                    <span>{new Date(event.created_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
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
