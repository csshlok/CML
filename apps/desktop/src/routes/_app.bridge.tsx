import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  Cable,
  Copy,
  ExternalLink,
  HelpCircle,
  Plus,
  RefreshCw,
  Shield,
  Terminal,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmAction } from "@/components/product/Feedback";
import { PageHeader } from "@/components/layout/WindowAware";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  describeBridgeCaptureResult,
  describeBridgeReviewDecision,
} from "@/lib/bridge-presentation.js";
import { buildExtensionSetupText, describeExtensionScope } from "@/lib/extension-presentation.js";
import {
  approveBridgeApprovalRequest,
  captureBridgeArtifact,
  captureBridgeExternalTurn,
  approveExtensionPairing,
  createBridgeClient,
  createExtensionClient,
  decideBridgeWritebackReview,
  deleteBridgeClient,
  getExtensionStatus,
  listBridgeCaptures,
  getBridgeStatus,
  listBridgeApprovalRequests,
  listBridgeAuditEvents,
  listBridgeClients,
  listBridgeTokenRotations,
  listExtensionCaptures,
  listExtensionClients,
  listExtensionPermissionAudit,
  listExtensionPairings,
  listBridgeWritebackReviews,
  listClusters,
  listBridgeRequests,
  rejectBridgeApprovalRequest,
  revokeExtensionClient,
  rotateExtensionClient,
  startExtensionPairing,
  listVaults,
  updateBridgeClient,
  updateBridgeSettings,
  updateExtensionClient,
  useBackendHealth,
  BACKEND_API_PREFIX,
  type BridgeApprovalRequest,
  type BridgeAuditEvent,
  type BridgeCaptureRecord,
  type BridgeClientRecord,
  type BridgeRequest,
  type BridgeStatus,
  type BridgeTokenRotation,
  type BridgeWritebackReview,
  type ClusterRecord,
  type ExtensionCaptureRecord,
  type ExtensionClientRecord,
  type ExtensionPermissionAuditRecord,
  type ExtensionPairingRecord,
  type VaultRecord,
} from "@/lib/backend";
import { displayPath } from "@/lib/displayPath";
import { useVisiblePolling } from "@/lib/useVisiblePolling";

export const Route = createFileRoute("/_app/bridge")({
  head: () => ({ meta: [{ title: "Bridge" }] }),
  component: BridgeView,
});

function BridgeView() {
  const backend = useBackendHealth();
  const [bridgeView, setBridgeView] = useState<
    "overview" | "clients" | "reviews" | "history" | "advanced"
  >("overview");
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [requests, setRequests] = useState<BridgeRequest[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<BridgeApprovalRequest[]>([]);
  const [auditEvents, setAuditEvents] = useState<BridgeAuditEvent[]>([]);
  const [rotations, setRotations] = useState<BridgeTokenRotation[]>([]);
  const [clients, setClients] = useState<BridgeClientRecord[]>([]);
  const [captures, setCaptures] = useState<BridgeCaptureRecord[]>([]);
  const [reviews, setReviews] = useState<BridgeWritebackReview[]>([]);
  const [extensionClients, setExtensionClients] = useState<ExtensionClientRecord[]>([]);
  const [extensionCaptures, setExtensionCaptures] = useState<ExtensionCaptureRecord[]>([]);
  const [extensionAudit, setExtensionAudit] = useState<ExtensionPermissionAuditRecord[]>([]);
  const [extensionPairings, setExtensionPairings] = useState<ExtensionPairingRecord[]>([]);
  const [clientName, setClientName] = useState("Local MCP client");
  const [clientToken, setClientToken] = useState<string | null>(null);
  const [clientTokenClientId, setClientTokenClientId] = useState<string | null>(null);
  const [vaults, setVaults] = useState<VaultRecord[]>([]);
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [saving, setSaving] = useState(false);
  const [captureMode, setCaptureMode] = useState<"artifact" | "turn">("artifact");
  const [captureVaultId, setCaptureVaultId] = useState("");
  const [captureClusterId, setCaptureClusterId] = useState("");
  const [captureTitle, setCaptureTitle] = useState("");
  const [capturePrompt, setCapturePrompt] = useState("");
  const [captureResponse, setCaptureResponse] = useState("");
  const [captureClientName, setCaptureClientName] = useState("desktop-manual");
  const [captureNotice, setCaptureNotice] = useState<string | null>(null);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [extensionName, setExtensionName] = useState("Browser extension");
  const [extensionToken, setExtensionToken] = useState<string | null>(null);
  const [extensionNotice, setExtensionNotice] = useState<string | null>(null);
  const [extensionVaultId, setExtensionVaultId] = useState("");
  const [mcpSetupClient, setMcpSetupClient] = useState<"chatgpt" | "claude" | "cursor" | "other">(
    "chatgpt",
  );
  const [mcpCapabilityProfile, setMcpCapabilityProfile] = useState<"read_only" | "read_write">(
    "read_only",
  );
  const [mcpFeatureFlags, setMcpFeatureFlags] = useState<DesktopMcpFeatureFlags>({
    chatgpt_mcp_setup: true,
    secure_mcp_tunnel: true,
    chatgpt_mcp_write_tools: true,
    mcp_streaming: false,
    mcp_remote_http: false,
  });
  const [mcpLauncher, setMcpLauncher] = useState<DesktopMcpLauncher | null>(null);
  const [tunnelStatus, setTunnelStatus] = useState<DesktopTunnelStatus | null>(null);
  const [tunnelId, setTunnelId] = useState("");
  const [tunnelRuntimeKey, setTunnelRuntimeKey] = useState("");
  const [tunnelBusy, setTunnelBusy] = useState(false);
  const [tunnelError, setTunnelError] = useState<string | null>(null);
  const [tourStep, setTourStep] = useState<number | null>(null);

  async function loadBridgeState() {
    if (backend.status !== "online") return;
    const [
      statusResult,
      requestsResult,
      approvalsResult,
      auditResult,
      rotationsResult,
      clientsResult,
      vaultsResult,
      clustersResult,
      capturesResult,
      reviewsResult,
      extensionClientsResult,
      extensionCapturesResult,
      extensionPairingsResult,
      extensionAuditResult,
    ] = await Promise.allSettled([
      getBridgeStatus(),
      listBridgeRequests(),
      listBridgeApprovalRequests(),
      listBridgeAuditEvents(),
      listBridgeTokenRotations(),
      listBridgeClients(),
      listVaults(),
      listClusters(),
      listBridgeCaptures(),
      listBridgeWritebackReviews(undefined, true),
      listExtensionClients(),
      listExtensionCaptures(),
      listExtensionPairings(),
      listExtensionPermissionAudit(),
    ] as const);
    const nextVaults = vaultsResult.status === "fulfilled" ? vaultsResult.value : vaults;
    const nextClusters = clustersResult.status === "fulfilled" ? clustersResult.value : clusters;
    if (statusResult.status === "fulfilled") {
      const nextStatus = statusResult.value;
      const vaultIds = new Set(nextVaults.map((vault) => vault.id));
      const clusterIds = new Set(nextClusters.map((cluster) => cluster.id));
      setStatus({
        ...nextStatus,
        allowed_vault_ids: nextStatus.allowed_vault_ids.filter((id) => vaultIds.has(id)),
        allowed_cluster_ids: nextStatus.allowed_cluster_ids.filter((id) => clusterIds.has(id)),
      });
      if (!captureVaultId && nextStatus.allowed_vault_ids.length > 0) {
        setCaptureVaultId(nextStatus.allowed_vault_ids[0] ?? "");
      }
      if (!extensionVaultId && nextStatus.allowed_vault_ids.length > 0) {
        setExtensionVaultId(nextStatus.allowed_vault_ids[0] ?? "");
      }
    }
    if (requestsResult.status === "fulfilled") setRequests(requestsResult.value);
    if (approvalsResult.status === "fulfilled") setApprovalRequests(approvalsResult.value);
    if (auditResult.status === "fulfilled") setAuditEvents(auditResult.value);
    if (rotationsResult.status === "fulfilled") setRotations(rotationsResult.value);
    if (clientsResult.status === "fulfilled") setClients(clientsResult.value);
    if (vaultsResult.status === "fulfilled") setVaults(vaultsResult.value);
    if (clustersResult.status === "fulfilled") setClusters(clustersResult.value);
    if (capturesResult.status === "fulfilled") setCaptures(capturesResult.value);
    if (reviewsResult.status === "fulfilled") setReviews(reviewsResult.value);
    if (extensionClientsResult.status === "fulfilled") {
      setExtensionClients(extensionClientsResult.value);
    }
    if (extensionCapturesResult.status === "fulfilled") {
      setExtensionCaptures(extensionCapturesResult.value);
    }
    if (extensionPairingsResult.status === "fulfilled") {
      setExtensionPairings(extensionPairingsResult.value);
    }
    if (extensionAuditResult.status === "fulfilled") {
      setExtensionAudit(extensionAuditResult.value);
    }
  }

  useVisiblePolling(loadBridgeState, 60_000, backend.status === "online");

  useEffect(() => {
    void window.cmlDesktop?.getMcpFeatureFlags().then((next) => {
      setMcpFeatureFlags(next);
      if (!next.chatgpt_mcp_write_tools) setMcpCapabilityProfile("read_only");
      if (!next.chatgpt_mcp_setup) setMcpSetupClient("claude");
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void window.cmlDesktop
      ?.getMcpLauncher(mcpCapabilityProfile)
      .then((launcher) => {
        if (!cancelled) setMcpLauncher(launcher);
      })
      .catch(() => {
        if (!cancelled) setMcpLauncher(null);
      });
    return () => {
      cancelled = true;
    };
  }, [backend.url, mcpCapabilityProfile]);

  useEffect(() => {
    void window.cmlDesktop?.getTunnelStatus().then((next) => {
      if (!next) return;
      setTunnelStatus(next);
      setTunnelId(next.tunnel_id);
      setMcpCapabilityProfile(next.capability_profile);
    });
    return window.cmlDesktop?.onTunnelStatusChanged((next) => {
      setTunnelStatus(next);
      setTunnelId(next.tunnel_id);
      setMcpCapabilityProfile(next.capability_profile);
    });
  }, []);

  useEffect(() => {
    const refresh = () => void loadBridgeState();
    window.addEventListener("vault:bridge-captures-changed", refresh);
    return () => {
      window.removeEventListener("vault:bridge-captures-changed", refresh);
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
        capability_profile: mcpCapabilityProfile,
        allowed_vault_ids: status?.allowed_vault_ids ?? [],
        allowed_cluster_ids: status?.allowed_cluster_ids ?? [],
        allow_raw_snippets: Boolean(status?.allow_raw_snippets),
        allow_cluster_profile: Boolean(status?.allow_cluster_profile),
      });
      setClientToken(created.token);
      setClientTokenClientId(created.id);
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
      if ("token" in updated) {
        setClientToken(updated.token);
        setClientTokenClientId(updated.id);
        if (tunnelStatus?.bridge_client_id === updated.id) {
          const nextTunnelStatus = await window.cmlDesktop?.reconnectTunnel(updated.token);
          if (nextTunnelStatus) setTunnelStatus(nextTunnelStatus);
        }
      }
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function removeClient(client: BridgeClientRecord) {
    setSaving(true);
    try {
      if (tunnelStatus?.bridge_client_id === client.id) {
        const next = await window.cmlDesktop?.disconnectTunnel(true);
        if (next) setTunnelStatus(next);
      }
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
      setClientTokenClientId(created.id);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function rejectRequest(requestRow: BridgeApprovalRequest) {
    setSaving(true);
    try {
      await rejectBridgeApprovalRequest(requestRow.id, {
        detail: "Rejected in Vault Bridge settings.",
      });
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function reviewCapture(sourceId: string, approved: boolean) {
    setSaving(true);
    try {
      const result = await decideBridgeWritebackReview(sourceId, approved);
      setReviewNotice(describeBridgeReviewDecision(result, approved));
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function submitManualCapture() {
    const vaultId = captureVaultId || status?.allowed_vault_ids[0] || "";
    if (!vaultId) return;
    if (captureMode === "artifact") {
      const title = captureTitle.trim();
      const content = captureResponse.trim();
      if (!title || !content) return;
      setSaving(true);
      try {
        const result = await captureBridgeArtifact({
          vault_id: vaultId,
          cluster_id: captureClusterId || null,
          client_name: captureClientName.trim() || "desktop-manual",
          title,
          content,
          artifact_type: "manual_capture",
          metadata: { capture_surface: "desktop_bridge" },
        });
        setCaptureNotice(describeBridgeCaptureResult(result));
        setCaptureTitle("");
        setCaptureResponse("");
        await loadBridgeState();
      } finally {
        setSaving(false);
      }
      return;
    }
    const prompt = capturePrompt.trim();
    const response = captureResponse.trim();
    if (!prompt || !response) return;
    setSaving(true);
    try {
      const result = await captureBridgeExternalTurn({
        vault_id: vaultId,
        cluster_id: captureClusterId || null,
        client_name: captureClientName.trim() || "desktop-manual",
        user_prompt: prompt,
        model_response: response,
        metadata: { capture_surface: "desktop_bridge" },
      });
      setCaptureNotice(describeBridgeCaptureResult(result));
      setCapturePrompt("");
      setCaptureResponse("");
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function createManualExtensionClient() {
    const name = extensionName.trim();
    if (!name) return;
    setSaving(true);
    try {
      const result = await createExtensionClient({ name });
      if (extensionVaultId) {
        await updateExtensionClient(result.id, { allowed_vault_ids: [extensionVaultId] });
      }
      setExtensionToken(result.token);
      setExtensionNotice("Extension client created.");
      await loadBridgeState();
      try {
        const statusResult = await getExtensionStatus(result.token);
        setExtensionNotice(statusResult.detail);
      } catch {
        // Best-effort status probe.
      }
    } finally {
      setSaving(false);
    }
  }

  async function createPairingSession() {
    const name = extensionName.trim();
    if (!name) return;
    setSaving(true);
    try {
      await startExtensionPairing({
        name,
        allowed_vault_ids: extensionVaultId ? [extensionVaultId] : undefined,
      });
      setExtensionNotice("Pairing session started.");
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function approvePairing(pairingId: string) {
    setSaving(true);
    try {
      const result = await approveExtensionPairing(pairingId);
      setExtensionToken(result.token);
      setExtensionNotice("Pairing approved and token issued.");
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function toggleExtensionClient(client: ExtensionClientRecord, enabled: boolean) {
    setSaving(true);
    try {
      await updateExtensionClient(client.id, { enabled });
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function removeExtensionClient(client: ExtensionClientRecord) {
    setSaving(true);
    try {
      await revokeExtensionClient(client.id);
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function rotateExtensionClientToken(client: ExtensionClientRecord) {
    setSaving(true);
    try {
      const result = await rotateExtensionClient(client.id);
      setExtensionToken(result.token);
      setExtensionName(result.name);
      setExtensionVaultId(result.allowed_vault_ids[0] ?? "");
      setExtensionNotice("Extension token replaced. Import the new setup JSON in the extension.");
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function scopeExtensionClient(client: ExtensionClientRecord, vaultIds: string[]) {
    setSaving(true);
    try {
      await updateExtensionClient(client.id, { allowed_vault_ids: vaultIds });
      await loadBridgeState();
    } finally {
      setSaving(false);
    }
  }

  async function copyBridgeText(value: string) {
    if (window.cmlDesktop?.copyText) {
      await window.cmlDesktop.copyText(value);
      return;
    }
    await navigator.clipboard.writeText(value);
  }

  async function connectChatGptTunnel() {
    if (!clientToken) {
      setTunnelError("Create a connection token below first.");
      return;
    }
    setTunnelBusy(true);
    setTunnelError(null);
    try {
      const next = await window.cmlDesktop?.connectTunnel({
        tunnelId: tunnelId.trim(),
        runtimeApiKey: tunnelRuntimeKey.trim(),
        bridgeToken: clientToken,
        bridgeClientId: clientTokenClientId ?? undefined,
        capabilityProfile: mcpCapabilityProfile,
      });
      if (next) setTunnelStatus(next);
      setTunnelRuntimeKey("");
    } catch (error) {
      setTunnelError(error instanceof Error ? error.message : "Could not connect.");
    } finally {
      setTunnelBusy(false);
    }
  }

  async function disconnectChatGptTunnel(forget = false) {
    const connectedClientId = tunnelStatus?.bridge_client_id;
    setTunnelBusy(true);
    setTunnelError(null);
    try {
      const next = await window.cmlDesktop?.disconnectTunnel(forget);
      if (next) setTunnelStatus(next);
      if (forget) {
        if (connectedClientId) {
          await deleteBridgeClient(connectedClientId);
          if (clientTokenClientId === connectedClientId) {
            setClientToken(null);
            setClientTokenClientId(null);
          }
          await loadBridgeState();
        }
        setTunnelId("");
      }
    } catch (error) {
      setTunnelError(error instanceof Error ? error.message : "Could not disconnect.");
    } finally {
      setTunnelBusy(false);
    }
  }

  async function reconnectChatGptTunnel() {
    setTunnelBusy(true);
    setTunnelError(null);
    try {
      const next = await window.cmlDesktop?.reconnectTunnel();
      if (next) setTunnelStatus(next);
    } catch (error) {
      setTunnelError(error instanceof Error ? error.message : "Could not reconnect.");
    } finally {
      setTunnelBusy(false);
    }
  }

  const exampleClientToken = clientToken ?? "<approved-client-token>";
  const mcpServerDefinition = {
    command: mcpLauncher?.command ?? "<Vault MCP launcher unavailable>",
    args: mcpLauncher?.args ?? [],
    cwd: mcpLauncher?.cwd,
    env: {
      ...(mcpLauncher?.env ?? {}),
      CML_BRIDGE_TOKEN: exampleClientToken,
    },
  };
  const mcpSetupText =
    mcpSetupClient === "other"
      ? [
          ...Object.entries(mcpServerDefinition.env).map(([key, value]) => `${key}=${value}`),
          `${mcpServerDefinition.command} ${mcpServerDefinition.args.join(" ")}`,
        ].join("\n")
      : JSON.stringify(
          {
            mcpServers: {
              vault: mcpServerDefinition,
            },
          },
          null,
          2,
        );
  const extensionVaultNamesById = new Map(vaults.map((vault) => [vault.id, vault.name]));
  const chatGptClientId = tunnelStatus?.bridge_client_id ?? clientTokenClientId;
  const connectedBridgeClient = clients.find((client) => client.id === chatGptClientId);
  const chatGptScopeReady = Boolean(
    connectedBridgeClient &&
    (connectedBridgeClient.allowed_vault_ids.length > 0 ||
      connectedBridgeClient.allowed_cluster_ids.length > 0),
  );
  const chatGptReadVerified = requests.some(
    (request) =>
      request.client_id === chatGptClientId &&
      request.mode === "list_clusters" &&
      request.decision === "allowed",
  );
  const chatGptWriteVerified = requests.some(
    (request) =>
      request.client_id === chatGptClientId &&
      ["external_artifact", "external_turn"].includes(request.mode) &&
      request.decision === "captured",
  );
  const nextConnectionStep = !(
    status?.allowed_vault_ids.length || status?.allowed_cluster_ids.length
  )
    ? {
        title: "Choose what the assistant can access",
        detail: "Select a library or cluster, then continue with setup.",
      }
    : clients.length === 0
      ? {
          title: "Connect your AI app",
          detail: "Open setup below and choose the assistant you use.",
        }
      : !chatGptReadVerified
        ? {
            title: "Verify the connection",
            detail: "Ask the connected assistant to list your Vault clusters.",
          }
        : {
            title: "Connection ready",
            detail: "Your assistant can use the approved Vault context.",
          };
  const extensionSetupText = extensionToken
    ? buildExtensionSetupText({
        backendUrl: backend.url,
        apiPrefix: BACKEND_API_PREFIX,
        token: extensionToken,
        vaultId: extensionVaultId,
        clientName: extensionName.trim() || "Browser extension",
      })
    : null;

  return (
    <div className="vault-page-wash h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
        <PageHeader className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h1 className="page-title">Connect AI tools</h1>
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:shrink-0">
            <Button variant="outline" className="gap-2" onClick={() => setTourStep(0)}>
              <HelpCircle className="h-4 w-4" />
              How to connect
            </Button>
            <div className="flex items-center gap-2 rounded-md border border-border bg-card p-3">
              <div className="flex items-center gap-3">
                <Switch
                  aria-label="Enable Bridge"
                  checked={Boolean(status?.enabled)}
                  disabled={!status || saving}
                  onCheckedChange={(checked) => void patchSettings({ enabled: checked })}
                />
                <div>
                  <div className="text-sm font-medium">
                    {status?.enabled ? "Connections allowed" : "Connections paused"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {backend.status === "online"
                      ? "Local service ready"
                      : "Local service unavailable"}
                  </div>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                disabled={saving || backend.status !== "online"}
                aria-label="Refresh Bridge permissions"
                title="Refresh Bridge permissions"
                onClick={() => void loadBridgeState()}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </PageHeader>

        <nav
          className="mt-8 flex gap-1 overflow-x-auto border-b border-border pb-2"
          aria-label="Bridge sections"
        >
          {(["overview", "reviews", "history", "clients"] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setBridgeView(item)}
              aria-current={
                bridgeView === item || (item === "clients" && bridgeView === "advanced")
                  ? "page"
                  : undefined
              }
              className={`min-h-9 shrink-0 rounded-md px-3 text-sm font-medium ${
                bridgeView === item
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              }`}
            >
              {bridgeViewLabel(item)}
              {item === "reviews" && approvalRequests.length + reviews.length > 0
                ? ` (${approvalRequests.length + reviews.length})`
                : ""}
            </button>
          ))}
        </nav>

        {bridgeView === "clients" || bridgeView === "advanced" ? (
          <nav className="mt-5 flex gap-4 text-sm" aria-label="Advanced connection tools">
            <button
              type="button"
              className={
                bridgeView === "clients"
                  ? "font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }
              aria-current={bridgeView === "clients" ? "page" : undefined}
              onClick={() => setBridgeView("clients")}
            >
              Connection access
            </button>
            <button
              type="button"
              className={
                bridgeView === "advanced"
                  ? "font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }
              aria-current={bridgeView === "advanced" ? "page" : undefined}
              onClick={() => setBridgeView("advanced")}
            >
              Manual save
            </button>
          </nav>
        ) : null}

        <section
          hidden={bridgeView !== "overview"}
          style={{ display: bridgeView === "overview" ? undefined : "none" }}
          className={bridgeSectionClass("overview", bridgeView, "mt-6")}
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-secondary">
              <Cable className="h-4 w-4" />
            </span>
            <div>
              <h2 className="text-sm font-semibold">Connect an assistant</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Start with read-only access. You can add permission to save answers after the
                connection works.
              </p>
            </div>
          </div>
          <div className="mt-5 border-y border-border py-3">
            <div className="text-sm font-medium">{nextConnectionStep.title}</div>
            <p className="mt-1 text-xs text-muted-foreground">{nextConnectionStep.detail}</p>
          </div>
        </section>

        <details
          hidden={bridgeView !== "overview"}
          style={{ display: bridgeView === "overview" ? undefined : "none" }}
          className="mt-4 rounded-md border border-border bg-card"
          open={clients.length === 0 ? true : undefined}
        >
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
            Set up an AI connection
          </summary>
          <div className="border-t border-border px-4 py-4">
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              Choose the app you use. Vault will show only the setup fields and checks needed for
              that connection.
            </p>
            <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="MCP client">
              {[
                ...(mcpFeatureFlags.chatgpt_mcp_setup ? ([["chatgpt", "ChatGPT"]] as const) : []),
                ["claude", "Claude Desktop"] as const,
                ["cursor", "Cursor"] as const,
                ["other", "Other"] as const,
              ].map(([id, label]) => (
                <Button
                  key={id}
                  type="button"
                  size="sm"
                  variant={mcpSetupClient === id ? "default" : "outline"}
                  role="tab"
                  aria-selected={mcpSetupClient === id}
                  onClick={() => setMcpSetupClient(id)}
                >
                  {label}
                </Button>
              ))}
            </div>
            {mcpSetupClient === "chatgpt" ? (
              <div className="mt-4 grid gap-4">
                <div className="rounded-md border border-border bg-background px-4 py-3">
                  <div className="font-medium">ChatGPT setup</div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    Availability depends on your ChatGPT workspace and admin settings. Vault cannot
                    confirm account eligibility.
                  </p>
                  <ol className="mt-3 grid gap-3 text-sm">
                    <li>
                      <span className="font-medium">1. Choose access and scope.</span>{" "}
                      <span className="text-muted-foreground">
                        {chatGptScopeReady
                          ? "A connection token has an allowed library or cluster."
                          : "Choose libraries or clusters, then create a client token below."}
                      </span>
                    </li>
                    <li>
                      <span className="font-medium">2. Start the secure connection.</span>{" "}
                      <span className="text-muted-foreground">
                        {tunnelStatus?.state === "connected"
                          ? "The tunnel health check passed."
                          : "Enter the tunnel ID and one-time runtime key, then connect."}
                      </span>
                    </li>
                    <li>
                      <span className="font-medium">3. Add the app in ChatGPT web.</span>{" "}
                      <span className="text-muted-foreground">
                        In Settings, open Apps and enable Developer mode if your workspace allows
                        it. Create an app, enter the tunnel connection, and scan tools.
                      </span>
                    </li>
                    <li>
                      <span className="font-medium">4. Test reading.</span>{" "}
                      <span className="text-muted-foreground">
                        {chatGptReadVerified
                          ? "Vault received a successful list_clusters call."
                          : "Ask ChatGPT: “Use Vault to list my clusters.” Then refresh this page."}
                      </span>
                    </li>
                    {mcpCapabilityProfile === "read_write" ? (
                      <li>
                        <span className="font-medium">5. Test saving.</span>{" "}
                        <span className="text-muted-foreground">
                          {chatGptWriteVerified
                            ? "Vault received a test save. Review it, then remove it from Sources."
                            : "Ask ChatGPT to save an artifact named “Vault connection test.” Confirm the action, review it here, then remove it from Sources."}
                        </span>
                      </li>
                    ) : null}
                    <li>
                      <span className="font-medium">
                        {mcpCapabilityProfile === "read_write" ? "6" : "5"}. Finish or revoke.
                      </span>{" "}
                      <span className="text-muted-foreground">
                        The connection is ready after the read test. Use Disconnect and revoke below
                        to remove local access immediately.
                      </span>
                    </li>
                  </ol>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!tunnelId}
                      onClick={() => void copyBridgeText(tunnelId)}
                    >
                      <Copy className="h-3.5 w-3.5" />
                      Copy tunnel ID
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={saving}
                      onClick={() => void loadBridgeState()}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Refresh checks
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={mcpCapabilityProfile === "read_only" ? "default" : "outline"}
                    onClick={() => setMcpCapabilityProfile("read_only")}
                    disabled={tunnelBusy || tunnelStatus?.state === "connected"}
                  >
                    Read only
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={mcpCapabilityProfile === "read_write" ? "default" : "outline"}
                    onClick={() => setMcpCapabilityProfile("read_write")}
                    disabled={
                      tunnelBusy ||
                      tunnelStatus?.state === "connected" ||
                      !mcpFeatureFlags.chatgpt_mcp_write_tools
                    }
                  >
                    Read and save
                  </Button>
                </div>
                <p className="text-xs leading-5 text-muted-foreground">
                  {!mcpFeatureFlags.chatgpt_mcp_write_tools
                    ? "This Vault release allows read only."
                    : "Start with read only. Read and save requires a ChatGPT workspace that allows write actions."}
                </p>
                {!mcpFeatureFlags.secure_mcp_tunnel ? (
                  <div
                    role="status"
                    className="rounded-md border border-border bg-muted px-3 py-2 text-sm"
                  >
                    ChatGPT connection is unavailable in this Vault release.
                  </div>
                ) : null}
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-1.5 text-xs">
                    Tunnel ID
                    <Input
                      value={tunnelId}
                      onChange={(event) => setTunnelId(event.target.value)}
                      placeholder="tunnel_..."
                      disabled={tunnelBusy || tunnelStatus?.state === "connected"}
                    />
                  </label>
                  <label className="grid gap-1.5 text-xs">
                    Runtime key
                    <Input
                      type="password"
                      autoComplete="off"
                      value={tunnelRuntimeKey}
                      onChange={(event) => setTunnelRuntimeKey(event.target.value)}
                      placeholder="Shown once in OpenAI Platform"
                      disabled={tunnelBusy || tunnelStatus?.state === "connected"}
                    />
                  </label>
                </div>
                <div className="rounded-md border border-border bg-background px-3 py-2 text-sm">
                  <div className="font-medium">{tunnelStatus?.detail ?? "Not connected"}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {tunnelStatus?.state === "connected"
                      ? `Access: ${tunnelStatus.capability_profile === "read_write" ? "Read and save" : "Read only"}`
                      : "Vault uses an outbound-only Secure MCP Tunnel."}
                  </div>
                </div>
                {tunnelError && (
                  <div
                    role="alert"
                    className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                  >
                    {tunnelError}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {tunnelStatus?.state === "connected" ? (
                    <>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => void window.cmlDesktop?.openTunnelUi()}
                      >
                        Open connection status
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={tunnelBusy}
                        onClick={() => void disconnectChatGptTunnel(false)}
                      >
                        Disconnect
                      </Button>
                      <ConfirmAction
                        title="Disconnect and revoke?"
                        description="This stops ChatGPT and revokes its Vault access token."
                        confirmLabel="Disconnect and revoke"
                        disabled={tunnelBusy}
                        onConfirm={() => disconnectChatGptTunnel(true)}
                      >
                        <Button type="button" size="sm" variant="destructive" disabled={tunnelBusy}>
                          Disconnect and revoke
                        </Button>
                      </ConfirmAction>
                    </>
                  ) : (
                    <>
                      {tunnelStatus?.tunnel_id ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={tunnelBusy}
                          onClick={() => void reconnectChatGptTunnel()}
                        >
                          {tunnelBusy ? "Connecting..." : "Reconnect"}
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        disabled={
                          tunnelBusy ||
                          !mcpFeatureFlags.secure_mcp_tunnel ||
                          !tunnelId.trim() ||
                          !tunnelRuntimeKey.trim() ||
                          !clientToken
                        }
                        onClick={() => void connectChatGptTunnel()}
                      >
                        Connect with new details
                      </Button>
                    </>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void window.cmlDesktop?.openExternal(
                        "https://platform.openai.com/settings/organization/tunnels",
                      )
                    }
                  >
                    Open tunnel settings
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void window.cmlDesktop?.openExternal("https://chatgpt.com/")}
                  >
                    Open ChatGPT apps
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {!clientToken && (
                  <span className="text-xs text-muted-foreground">
                    Create or rotate a connection token below before connecting.
                  </span>
                )}
              </div>
            ) : (
              <>
                <p className="mt-4 text-xs text-muted-foreground">
                  {mcpSetupClient === "claude"
                    ? "Paste into claude_desktop_config.json, then restart Claude Desktop."
                    : mcpSetupClient === "cursor"
                      ? "Paste into your Cursor MCP configuration, then reload Cursor."
                      : "Launch Vault's packaged stdio MCP server with this configuration."}
                </p>
                <pre className="mt-3 max-h-72 overflow-auto rounded-md border border-border bg-background p-3 text-xs leading-5">
                  <code>{mcpSetupText}</code>
                </pre>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!mcpLauncher}
                    onClick={() => void copyBridgeText(mcpSetupText)}
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Copy configuration
                  </Button>
                  {!clientToken && (
                    <span className="text-xs text-muted-foreground">
                      The placeholder will be replaced after you create or rotate a client token.
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        </details>

        <section
          hidden={bridgeView !== "clients"}
          style={{ display: bridgeView === "clients" ? undefined : "none" }}
          className={bridgeSectionClass("clients", bridgeView, "mt-6")}
        >
          {status?.enabled && status.allowed_vault_ids.length === 0 && (
            <div className="mb-4 rounded-md border border-[var(--status-learning)]/40 bg-[var(--status-learning)]/10 px-3 py-2 text-sm">
              Bridge is on, but no library is allowed. MCP clients will receive no_active_vault
              until you allow one.
            </div>
          )}
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-muted-foreground" />
            <div className="font-medium">Permissions</div>
          </div>
          <div className="mt-4 grid gap-6 md:grid-cols-2">
            <div className="min-w-0">
              <div className="text-sm font-medium">Allowed libraries</div>
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
                  <div className="text-sm text-muted-foreground">No libraries found.</div>
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
              label="Cluster profiles"
              detail="Allow clients to request cluster summaries and related context when available."
              checked={Boolean(status?.allow_cluster_profile)}
              disabled={!status || saving}
              onChange={(checked) => void patchSettings({ allow_cluster_profile: checked })}
            />
          </div>
        </section>

        <section
          hidden={bridgeView !== "clients"}
          style={{ display: bridgeView === "clients" ? undefined : "none" }}
          className={bridgeSectionClass("clients", bridgeView, "mt-6")}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Extension pairing
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Set up a browser/extension capture client without dropping to raw API calls. Start a
                pairing, approve it here, and then monitor captures.
              </p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:flex-row sm:flex-wrap lg:w-auto lg:justify-end">
              <select
                value={extensionVaultId}
                onChange={(event) => setExtensionVaultId(event.target.value)}
                className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm sm:w-48"
                aria-label="Extension library scope"
              >
                <option value="">All allowed libraries</option>
                {vaults.map((vault) => (
                  <option key={vault.id} value={vault.id}>
                    {vault.name}
                  </option>
                ))}
              </select>
              <Input
                value={extensionName}
                onChange={(event) => setExtensionName(event.target.value)}
                className="h-8 w-full sm:w-52"
                aria-label="Extension client name"
              />
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() => void createPairingSession()}
              >
                Start pairing
              </Button>
              <Button
                size="sm"
                disabled={saving}
                onClick={() => void createManualExtensionClient()}
              >
                Create token
              </Button>
            </div>
          </div>
          {extensionToken && (
            <div className="mt-4 rounded-md border border-[var(--status-ready)]/35 bg-[var(--status-ready)]/10 px-3 py-2 text-xs">
              <div className="font-medium">New extension token</div>
              <button
                type="button"
                className="mt-1 block max-w-full truncate font-mono text-left text-muted-foreground"
                onClick={() => void copyBridgeText(extensionToken)}
                title="Copy extension token"
              >
                {extensionToken}
              </button>
              {extensionSetupText && (
                <button
                  type="button"
                  className="mt-2 block text-left text-muted-foreground underline-offset-4 hover:underline"
                  onClick={() => void copyBridgeText(extensionSetupText)}
                >
                  Copy extension setup JSON
                </button>
              )}
            </div>
          )}
          <div className="mt-2 text-xs text-muted-foreground">
            {extensionNotice ??
              "Use pairing for approve-in-app setup, or create a direct token if you are configuring it yourself."}
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {extensionPairings.length > 0 ? (
              extensionPairings.slice(0, 6).map((pairing) => (
                <div key={pairing.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{pairing.requested_name}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {pairing.status}
                      </span>
                    </div>
                    <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                      {pairing.pairing_code}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Expires {new Date(pairing.expires_at).toLocaleString()}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Scope:{" "}
                      {describeExtensionScope(pairing.allowed_vault_ids, extensionVaultNamesById)}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={saving}
                      onClick={() => void copyBridgeText(pairing.pairing_code)}
                    >
                      Copy code
                    </Button>
                    {pairing.status === "pending" && (
                      <Button
                        size="sm"
                        disabled={saving}
                        onClick={() => void approvePairing(pairing.id)}
                      >
                        Approve
                      </Button>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No extension pairing sessions yet.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "clients"}
          style={{ display: bridgeView === "clients" ? undefined : "none" }}
          className={bridgeSectionClass("clients", bridgeView)}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Extension clients and captures
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Review which extension clients are active and what they have saved recently.
              </p>
            </div>
            <div className="text-xs text-muted-foreground">
              {extensionClients.length} clients / {extensionCaptures.length} captures
            </div>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {extensionClients.length > 0 ? (
              extensionClients.map((client) => (
                <div key={client.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{client.name}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {client.enabled ? "enabled" : "disabled"}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Scope{" "}
                      {describeExtensionScope(client.allowed_vault_ids, extensionVaultNamesById)} /
                      updated {new Date(client.updated_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Switch
                      aria-label={`${client.enabled ? "Disable" : "Enable"} ${client.name}`}
                      checked={client.enabled}
                      disabled={saving}
                      onCheckedChange={(enabled) => void toggleExtensionClient(client, enabled)}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        saving ||
                        !extensionVaultId ||
                        (client.allowed_vault_ids.length === 1 &&
                          client.allowed_vault_ids[0] === extensionVaultId)
                      }
                      onClick={() =>
                        void scopeExtensionClient(
                          client,
                          extensionVaultId ? [extensionVaultId] : [],
                        )
                      }
                    >
                      Use selected library
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={saving || client.allowed_vault_ids.length === 0}
                      onClick={() => void scopeExtensionClient(client, [])}
                    >
                      Allow all
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={saving || !client.enabled}
                      onClick={() => void rotateExtensionClientToken(client)}
                    >
                      <RefreshCw className="h-4 w-4" /> Replace token
                    </Button>
                    <ConfirmAction
                      title={`Revoke “${client.name}”?`}
                      description="This browser extension will immediately lose access to Vault until it is paired again."
                      confirmLabel="Revoke access"
                      disabled={saving}
                      onConfirm={() => removeExtensionClient(client)}
                    >
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={saving}
                        aria-label={`Revoke ${client.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </ConfirmAction>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No extension clients configured yet.
              </div>
            )}
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {extensionCaptures.length > 0 ? (
              extensionCaptures.slice(0, 6).map((capture) => (
                <div key={capture.id} className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{capture.title}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {capture.capture_type} / {new Date(capture.created_at).toLocaleString()}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No extension captures stored yet.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "history"}
          style={{ display: bridgeView === "history" ? undefined : "none" }}
          className={bridgeSectionClass("history", bridgeView, "mt-6")}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Extension permission audit
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Recent extension setup and capture-permission events so users can verify what was
                approved, denied, or revoked.
              </p>
            </div>
            <div className="text-xs text-muted-foreground">{extensionAudit.length} recent</div>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {extensionAudit.length > 0 ? (
              extensionAudit.slice(0, 8).map((event) => (
                <div key={event.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">
                        {event.event_type.replace(/_/g, " ")}
                      </div>
                      {event.vault_id && (
                        <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                          {extensionVaultNamesById.get(event.vault_id) || event.vault_id}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 break-words text-xs text-muted-foreground">
                      {event.detail || "No extra detail recorded."}
                    </div>
                  </div>
                  <div className="text-xs text-muted-foreground lg:text-right">
                    {new Date(event.created_at).toLocaleString()}
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No extension permission events recorded yet.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "advanced"}
          style={{ display: bridgeView === "advanced" ? undefined : "none" }}
          className={bridgeSectionClass("advanced", bridgeView, "mt-6")}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold">Manual save</h2>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Fallback for tools that cannot call Vault directly. Connected assistants should use
                the automatic save tools instead.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 lg:justify-end">
              <Button
                variant={captureMode === "artifact" ? "default" : "outline"}
                size="sm"
                onClick={() => setCaptureMode("artifact")}
              >
                Artifact
              </Button>
              <Button
                variant={captureMode === "turn" ? "default" : "outline"}
                size="sm"
                onClick={() => setCaptureMode("turn")}
              >
                Prompt + answer
              </Button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">Library</span>
              <select
                value={captureVaultId}
                onChange={(event) => setCaptureVaultId(event.target.value)}
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
              >
                <option value="">Select library</option>
                {vaults.map((vault) => (
                  <option key={vault.id} value={vault.id}>
                    {vault.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">Cluster</span>
              <select
                value={captureClusterId}
                onChange={(event) => setCaptureClusterId(event.target.value)}
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
              >
                <option value="">No cluster</option>
                {clusters
                  .filter((cluster) => !captureVaultId || cluster.vault_id === captureVaultId)
                  .map((cluster) => (
                    <option key={cluster.id} value={cluster.id}>
                      {cluster.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="space-y-1 md:col-span-2">
              <span className="text-xs text-muted-foreground">Client label</span>
              <Input
                value={captureClientName}
                onChange={(event) => setCaptureClientName(event.target.value)}
              />
            </label>
            {captureMode === "artifact" ? (
              <label className="space-y-1 md:col-span-2">
                <span className="text-xs text-muted-foreground">Title</span>
                <Input
                  value={captureTitle}
                  onChange={(event) => setCaptureTitle(event.target.value)}
                />
              </label>
            ) : (
              <label className="space-y-1 md:col-span-2">
                <span className="text-xs text-muted-foreground">User prompt</span>
                <textarea
                  value={capturePrompt}
                  onChange={(event) => setCapturePrompt(event.target.value)}
                  className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                />
              </label>
            )}
            <label className="space-y-1 md:col-span-2">
              <span className="text-xs text-muted-foreground">
                {captureMode === "artifact" ? "Artifact content" : "Model response"}
              </span>
              <textarea
                value={captureResponse}
                onChange={(event) => setCaptureResponse(event.target.value)}
                className="min-h-36 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 break-words text-xs text-muted-foreground">
              {captureNotice ??
                "Stored captures inherit the same Bridge trust and review rules as external MCP writeback."}
            </div>
            <Button
              size="sm"
              disabled={saving || !captureVaultId || !captureResponse.trim()}
              onClick={() => void submitManualCapture()}
            >
              Save to Vault
            </Button>
          </div>
        </section>

        <section
          hidden={bridgeView !== "reviews"}
          style={{ display: bridgeView === "reviews" ? undefined : "none" }}
          className={bridgeSectionClass("reviews", bridgeView, "mt-6")}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Pending approvals
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Claimed client names are never treated as verified identity on their own. Review the
                observed path and signature signal before approving.
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
                  <div key={item.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
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
                        {item.requested_vault_ids.length || 0} libraries /{" "}
                        {item.requested_cluster_ids.length || 0} clusters / raw text{" "}
                        {item.allow_raw_snippets ? "requested" : "off"}
                      </div>
                      <div className="mt-1 break-all text-xs text-muted-foreground">
                        Path{" "}
                        {displayPath(item.observed_executable_path || item.executable_path_claim) ||
                          "not provided"}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Publisher {item.publisher_name || "not available"} / expires{" "}
                        {new Date(item.expires_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                      <Button size="sm" disabled={saving} onClick={() => void approveRequest(item)}>
                        Approve
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={saving}
                        onClick={() => void rejectRequest(item)}
                      >
                        Reject
                      </Button>
                    </div>
                  </div>
                ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No pending Bridge approval requests.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "clients"}
          style={{ display: bridgeView === "clients" ? undefined : "none" }}
          className={bridgeSectionClass("clients", bridgeView)}
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Client tokens
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Give each external tool its own token and permission set. Newly created tokens are
                shown once.
              </p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:justify-end">
              <Input
                value={clientName}
                onChange={(event) => setClientName(event.target.value)}
                className="h-8 w-full sm:w-52"
                aria-label="Bridge client name"
              />
              <Button
                size="sm"
                className="gap-1"
                disabled={saving || !status}
                onClick={() => void addBridgeClient()}
              >
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
                onClick={() => void copyBridgeText(clientToken)}
                title="Copy token"
              >
                {clientToken}
              </button>
            </div>
          )}
          <div className="mt-4 divide-y divide-border border-y border-border">
            {clients.length > 0 ? (
              clients.map((client) => (
                <div key={client.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{client.name}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {client.enabled ? "enabled" : "disabled"}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {client.allowed_vault_ids.length || 0} libraries /{" "}
                      {client.allowed_cluster_ids.length || 0} clusters / raw text{" "}
                      {client.allow_raw_snippets ? "on" : "off"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Identity{" "}
                      {client.verified_identity ? client.verified_identity_label : "unverified"} /
                      signature {client.signature_status.replace(/_/g, " ")}
                    </div>
                    <div className="mt-1 break-all text-xs text-muted-foreground">
                      Path{" "}
                      {displayPath(
                        client.observed_executable_path || client.executable_path_claim,
                      ) || "not recorded"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Requests {client.request_count_total} / bytes{" "}
                      {client.response_bytes_total.toLocaleString()}
                      {client.last_request_at
                        ? ` / last ${new Date(client.last_request_at).toLocaleString()}`
                        : ""}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Switch
                      aria-label={`${client.enabled ? "Disable" : "Enable"} ${client.name}`}
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
                    <ConfirmAction
                      title={`Delete “${client.name}”?`}
                      description="This client will immediately lose access to Vault. Existing copied tokens cannot be used again."
                      confirmLabel="Delete client"
                      disabled={saving}
                      onConfirm={() => removeClient(client)}
                    >
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={saving}
                        aria-label={`Delete ${client.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </ConfirmAction>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No Bridge clients have dedicated tokens yet.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "reviews"}
          style={{ display: bridgeView === "reviews" ? undefined : "none" }}
          className={bridgeSectionClass("reviews", bridgeView)}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Capture review queue
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                External answers that only partially used library context, contradicted it, or
                skipped it stay here until you approve them.
              </p>
            </div>
            <div className="text-xs text-muted-foreground">{reviews.length} pending</div>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {reviews.length > 0 ? (
              reviews.map((review) => (
                <div
                  key={review.source_id}
                  className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto]"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{review.title}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {review.quality_state.replace(/_/g, " ")}
                      </span>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {review.trust_tier}
                      </span>
                    </div>
                    <div className="mt-1 break-words text-xs text-muted-foreground">
                      Reasons: {review.reasons.join(", ") || "none recorded"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Updated {new Date(review.updated_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Button
                      size="sm"
                      disabled={saving}
                      onClick={() => void reviewCapture(review.source_id, true)}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={saving}
                      onClick={() => void reviewCapture(review.source_id, false)}
                    >
                      Keep gated
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No Bridge captures are waiting for review.
              </div>
            )}
          </div>
          {reviewNotice && (
            <div className="mt-4 rounded-md border border-[var(--status-ready)]/35 bg-[var(--status-ready)]/10 px-3 py-2 text-xs">
              <span className="break-words">{reviewNotice}</span>
            </div>
          )}
        </section>

        <section
          hidden={bridgeView !== "history"}
          style={{ display: bridgeView === "history" ? undefined : "none" }}
          className={bridgeSectionClass("history", bridgeView)}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Saved captures
              </div>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Recent external transcripts and artifacts stored through Bridge.
              </p>
            </div>
            <div className="text-xs text-muted-foreground">{captures.length} recent</div>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {captures.length > 0 ? (
              captures.slice(0, 8).map((capture) => (
                <div
                  key={capture.source_id}
                  className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto]"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-medium">{capture.title}</div>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {capture.source_type.replace(/_/g, " ")}
                      </span>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {capture.quality_state.replace(/_/g, " ")}
                      </span>
                      <span className="rounded-md border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {capture.trust_tier}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {capture.approved
                        ? "Approved for trusted reuse"
                        : "Stored with current trust gate"}{" "}
                      / {new Date(capture.created_at).toLocaleString()}
                    </div>
                    {capture.security_labels.length > 0 && (
                      <div className="mt-1 break-words text-xs text-muted-foreground">
                        Labels: {capture.security_labels.join(", ")}
                      </div>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                No Bridge captures stored yet.
              </div>
            )}
          </div>
        </section>

        <section
          hidden={bridgeView !== "history"}
          style={{ display: bridgeView === "history" ? undefined : "none" }}
          className={bridgeSectionClass("history", bridgeView)}
        >
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Recent context requests
          </div>
          {requests.length > 0 ? (
            <div className="mt-3 divide-y divide-border text-sm">
              {requests.slice(0, 5).map((request) => (
                <div
                  key={request.id}
                  className="grid gap-1 py-2 sm:grid-cols-[120px_minmax(0,1fr)_90px] sm:gap-3"
                >
                  <span className="truncate text-muted-foreground">{request.client_name}</span>
                  <span className="truncate">{request.query}</span>
                  <span className="text-right text-xs text-muted-foreground">{request.mode}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">No external context requests yet.</p>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void copyBridgeText(
                  [
                    `POST ${backend.url}${BACKEND_API_PREFIX}/bridge/context`,
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
                void copyBridgeText(
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
              disabled={!clientToken}
              onClick={() => clientToken && void copyBridgeText(clientToken)}
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
              <div className="text-xs font-medium text-muted-foreground">
                Token rotation history
              </div>
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                {rotations.slice(0, 3).map((rotation) => (
                  <div key={rotation.id} className="flex flex-wrap justify-between gap-3">
                    <span className="min-w-0 break-words">
                      {rotation.reason.replace(/_/g, " ")}
                    </span>
                    <span className="shrink-0">
                      {new Date(rotation.rotated_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {auditEvents.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="text-xs font-medium text-muted-foreground">
                Recent Bridge security events
              </div>
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                {auditEvents.slice(0, 5).map((event) => (
                  <div key={event.id} className="flex flex-wrap justify-between gap-3">
                    <span className="min-w-0 break-words">
                      {event.event_type.replace(/_/g, " ")}
                    </span>
                    <span className="shrink-0">{new Date(event.created_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
      {tourStep !== null ? (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/35 p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="bridge-tour-title"
            className="w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-2xl"
          >
            <div className="text-xs font-medium text-primary">Bridge setup {tourStep + 1} of 3</div>
            <h2 id="bridge-tour-title" className="mt-2 text-xl font-semibold">
              {
                [
                  "Choose what the AI app can read",
                  "Create a private connection",
                  "Paste the setup into your AI app",
                ][tourStep]
              }
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {
                [
                  "Turn Bridge on, then select at least one library. Cluster access is optional and narrows what the app can see.",
                  "Open Clients, name the outside app, and create it. Vault shows its token once, so copy it before leaving.",
                  "Return to Overview, choose Claude Desktop, Cursor, or Other, then copy the configuration. Paste it into that app's MCP settings and restart the app.",
                ][tourStep]
              }
            </p>
            <div className="mt-6 flex items-center justify-between gap-3">
              <Button variant="ghost" onClick={() => setTourStep(null)}>
                Close
              </Button>
              <div className="flex gap-2">
                {tourStep > 0 ? (
                  <Button variant="outline" onClick={() => setTourStep(tourStep - 1)}>
                    Back
                  </Button>
                ) : null}
                <Button
                  onClick={() => {
                    if (tourStep === 2) {
                      setBridgeView("overview");
                      setTourStep(null);
                    } else {
                      const next = tourStep + 1;
                      setBridgeView(next === 1 ? "clients" : "overview");
                      setTourStep(next);
                    }
                  }}
                >
                  {tourStep === 2 ? "Show configuration" : "Next"}
                </Button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
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
    <div className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-0.5 break-words text-xs text-muted-foreground">{detail}</div>
      </div>
      <Switch aria-label={label} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

function bridgeSectionClass(
  _section: "overview" | "clients" | "reviews" | "history" | "advanced",
  _active: "overview" | "clients" | "reviews" | "history" | "advanced",
  margin = "mt-4",
) {
  return `${margin} rounded-md border border-border bg-card p-4`;
}

function bridgeViewLabel(view: "overview" | "clients" | "reviews" | "history" | "advanced") {
  return {
    overview: "Connect",
    clients: "Advanced",
    reviews: "Review",
    history: "Activity",
    advanced: "Advanced",
  }[view];
}
