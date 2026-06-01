import { useEffect, useState } from "react";

const CONFIGURED_BACKEND_URL =
  (import.meta.env.VITE_CML_BACKEND_URL as string | undefined) || "http://127.0.0.1:7343";
const BACKEND_CANDIDATES = Array.from(
  new Set([CONFIGURED_BACKEND_URL, "http://127.0.0.1:7343", "http://127.0.0.1:7342"]),
);
let resolvedBackendUrl: string | null = null;
let resolvedBackendToken: string | null = null;

if (typeof window !== "undefined") {
  const queryBackendUrl = new URLSearchParams(window.location.search).get("backendUrl");
  if (queryBackendUrl) {
    resolvedBackendUrl = queryBackendUrl;
  } else {
    void window.cmlDesktop?.getBackendUrl?.().then((url) => {
      if (url) resolvedBackendUrl = url;
    });
    void window.cmlDesktop?.getBackendToken?.().then((token) => {
      if (token) resolvedBackendToken = token;
    });
  }
}

export type BackendHealthStatus = "checking" | "online" | "degraded" | "offline";

export function useBackendHealth() {
  const [status, setStatus] = useState<BackendHealthStatus>("checking");
  const [url, setUrl] = useState(CONFIGURED_BACKEND_URL);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      let degradedCandidateSeen = false;
      for (const candidate of BACKEND_CANDIDATES) {
        const probe = await probeBackend(candidate);
        if (probe.status === "online") {
          resolvedBackendUrl = candidate;
          if (!cancelled) {
            setUrl(candidate);
            setStatus("online");
          }
          return;
        }
        if (probe.status === "degraded" && candidate === CONFIGURED_BACKEND_URL) {
          degradedCandidateSeen = true;
          if (!cancelled) {
            setUrl(candidate);
            setStatus("degraded");
          }
        }
      }
      if (!cancelled && !degradedCandidateSeen) setStatus("offline");
    }

    check();
    const id = window.setInterval(check, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return {
    status,
    url,
  };
}

async function probeBackend(url: string): Promise<{ status: BackendHealthStatus }> {
  try {
    const response = await fetch(`${url}/health`, {
      signal: AbortSignal.timeout(1000),
    });
    if (!response.ok) return { status: "offline" };
    const openapi = await fetch(`${url}/openapi.json`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!openapi.ok) return { status: "degraded" };
    const spec = await openapi.json();
    const paths = spec?.paths ?? {};
    const hasChatRoutes =
      Boolean(paths["/api/v1/chat/sessions"]) &&
      Boolean(paths["/api/v1/chat/messages/{message_id}"]) &&
      Boolean(paths["/api/v1/models/embeddings/configure"]);
    return { status: hasChatRoutes ? "online" : "degraded" };
  } catch {
    return { status: "offline" };
  }
}

async function getBackendUrl() {
  if (resolvedBackendUrl) return resolvedBackendUrl;
  for (const candidate of BACKEND_CANDIDATES) {
    const probe = await probeBackend(candidate);
    if (probe.status === "online") {
      resolvedBackendUrl = candidate;
      return candidate;
    }
  }
  return CONFIGURED_BACKEND_URL;
}

async function getBackendToken() {
  if (resolvedBackendToken) return resolvedBackendToken;
  const token = await window.cmlDesktop?.getBackendToken?.();
  if (token) resolvedBackendToken = token;
  return resolvedBackendToken;
}

export type BridgeStatus = {
  enabled: boolean;
  mcp: string;
  http_api: string;
  cli: string;
  allowed_vault_ids: string[];
  allowed_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_style_profile: boolean;
  allow_expert_calls: boolean;
  bridge_token: string;
  last_refreshed_at?: string | null;
};

export type BridgeRequest = {
  id: string;
  client_name: string;
  query: string;
  mode: string;
  created_at: string;
};

export type BridgeTokenRotation = {
  id: string;
  rotated_at: string;
  reason: string;
};

export type BridgeClientRecord = {
  id: string;
  name: string;
  enabled: boolean;
  allowed_vault_ids: string[];
  allowed_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_style_profile: boolean;
  allow_expert_calls: boolean;
  created_at: string;
  updated_at: string;
};

export type BridgeClientCreateResponse = BridgeClientRecord & {
  token: string;
};

export type VaultRecord = {
  id: string;
  name: string;
  path: string;
  created_at: string;
  updated_at: string;
};

export type ClusterRecord = {
  id: string;
  vault_id: string;
  name: string;
  description: string;
  color: string;
  expert_status: string;
  created_at: string;
  updated_at: string;
};

export type ClusterSuggestionRecord = {
  source_id: string;
  source_title: string;
  current_cluster_id: string | null;
  suggested_cluster_id: string;
  suggested_cluster_name: string;
  confidence: number;
  reason: string;
};

export type ClusterExpertJobRecord = {
  id: string;
  cluster_id: string;
  vault_id: string;
  action: string;
  status: string;
  detail: string;
  failure_code: string;
  artifact_path: string | null;
  hardware_tier: string;
  created_at: string;
  updated_at: string;
};

export type ExpertArtifactRecord = {
  id: string;
  cluster_id: string;
  vault_id: string;
  job_id: string | null;
  artifact_type: string;
  status: string;
  local_path: string | null;
  base_model: string;
  hardware_tier: string;
  quality_score: number | null;
  dataset_hash: string;
  training_config_hash: string;
  metrics_json: string;
  active: boolean;
  rolled_back_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ExpertGraduationContractRecord = {
  supported_statuses: string[];
  minimum_sources: number;
  minimum_quality_score: number;
  required_artifact_files: string[];
  failure_codes: string[];
  rollback_behavior: string;
};

export type AppJobRecord = {
  id: string;
  job_type: string;
  status: string;
  payload: string;
  dedupe_key: string | null;
  priority?: string | null;
  write_scope?: string | null;
  scope_id?: string | null;
  resource_cost?: string | null;
  cancellable?: number | null;
  timeout_seconds?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_seconds?: number | null;
  estimated_remaining_seconds?: number | null;
  status_detail?: string | null;
  attempts: number;
  max_attempts: number;
  last_error: string;
  created_at: string;
  updated_at: string;
};

export type JobQueueStatus = {
  queued: number;
  blocked_by_dependency: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  manual_review: number;
  running_jobs: AppJobRecord[];
  latest: AppJobRecord[];
};

export type SourceRecord = {
  id: string;
  vault_id: string;
  cluster_id: string | null;
  title: string;
  source_type: string;
  state: string;
  original_path: string | null;
  url: string | null;
  raw_text: string;
  extracted_text: string;
  summary: string;
  tags: string[];
  cover_image_url: string | null;
  created_at: string;
  updated_at: string;
};

export type SourcePageRecord = {
  id: string;
  source_id: string;
  vault_id: string;
  page_number: number;
  raw_text: string;
  extraction_version: string;
  content_hash: string;
  created_at: string;
  updated_at: string;
};

export type SemanticSearchResult = {
  source_id: string;
  source_title: string;
  source_type: string;
  cluster_id: string | null;
  chunk_id: string;
  chunk_index: number;
  snippet: string;
  score: number;
};

export type SemanticSearchResponse = {
  query: string;
  results: SemanticSearchResult[];
};

export type ChatContextResponse = {
  session_id: string | null;
  user_message_id: string | null;
  assistant_message_id: string | null;
  prompt: string;
  answer: string;
  clusters_used: Array<{
    cluster_id: string;
    cluster_name: string;
    reason: string;
  }>;
  citations: Array<{
    source_id: string;
    source_title: string;
    snippet: string;
    score: number;
    chunk_id?: string | null;
    page_id?: string | null;
    page_number?: number | null;
    state?: string;
  }>;
  coverage_ledger: {
    sources_considered: number;
    sources_analyzed: number;
    sources_low_relevance: number;
    relevance_threshold: number;
    scope: string;
  } | null;
  attachments_stored: Array<{
    source_id: string;
    title: string;
    cluster_id: string | null;
  }>;
  intent: string;
  runtime_state: string | null;
  warnings: string[];
  memory_status: string | null;
};

export type DiagnosticBundleResponse = {
  bundle_path: string;
  bundle_format_version: number;
  bundle_generated_at: string;
  app_version: string;
  backend_version: string;
  schema_version: number;
  included_files: string[];
};

export type ChatMessageRecord = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  clusters_used: ChatContextResponse["clusters_used"];
  citations: ChatContextResponse["citations"];
  warnings: string[];
  useful: boolean | null;
  saved: boolean;
  created_at: string;
};

export type ChatSessionRecord = {
  id: string;
  vault_id: string;
  title: string;
  scope_cluster_id: string | null;
  saved: boolean;
  memory_status: string;
  memory_updated_at: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRecord[];
};

export type ChatTimelineItem =
  | (ChatMessageRecord & { message_type: "user_message" | "assistant_message"; sort_key: string })
  | {
      message_type: "retriable_generation";
      id: string;
      session_id: string;
      prompt: string;
      cluster_id: string | null;
      state: string;
      error: string;
      created_at: string;
      updated_at: string;
      sort_key: string;
    };

export type ChatTimelineResponse = {
  session_id: string;
  items: ChatTimelineItem[];
};

export type ModelDownloadState = {
  model_id: string;
  status: string;
  bytes_downloaded: number | null;
  total_bytes: number | null;
  file_name: string | null;
  local_path: string | null;
  error: string | null;
};

export type LocalModelRecord = {
  id: string;
  name: string;
  role: string;
  hf_repo: string;
  quantization: string;
  approximate_download_gb: number;
  recommended_ram_gb: string;
  notes: string;
  llama_cpp_ref: string;
  installed: boolean;
  local_path: string | null;
  download: ModelDownloadState | null;
};

export type ModelRuntimeStatus = {
  provider: string;
  base_url: string;
  model: string;
  available: boolean;
  detail: string;
};

export type EmbeddingRuntimeStatus = {
  provider: string;
  model: string;
  dimensions: number;
  available: boolean;
  detail: string;
  setup_required: boolean;
  cache_dir: string | null;
};

export type EmbeddingModelDownloadState = ModelDownloadState;

export type DiskPreflightResponse = {
  path: string;
  probe_path: string;
  required_bytes: number;
  available_bytes: number;
  ok: boolean;
  message: string;
};

export type StartupStatusRead = {
  phase: string;
  raw_phase: string | null;
  status: string;
  message: string;
  error_code: string;
  backend_mode: string;
  data_dir: string;
  database_path: string;
  updated_at: string;
};

export type HardwareStatusRead = {
  os: string;
  machine: string;
  processor: string;
  cpu_count: number;
  total_memory_bytes: number | null;
  avx2: boolean | null;
  hardware_tier: string;
  training_supported: boolean;
  detail: string;
};

export type OCRRuntimeStatusRead = {
  available: boolean;
  pdf_ocr_available: boolean;
  image_ocr_available: boolean;
  tesseract_path: string | null;
  ocrmypdf_command: string | null;
  tessdata_path: string | null;
  ghostscript_path: string | null;
  qpdf_path: string | null;
  missing: string[];
  detail: string;
};

export type VaultSafetyRead = {
  database_path: string;
  integrity_ok: boolean;
  integrity_result: string[];
  wal_checkpoint: string;
  backup_path: string | null;
  created_at: string;
};

export type LocalFolderScanResponse = {
  import_id: string | null;
  path: string;
  integration_type: string;
  supported_files: string[];
  supported_count: number;
  skipped_count: number;
  truncated: boolean;
};

export type IntegrationImportRecord = {
  id: string;
  vault_id: string | null;
  integration_type: string;
  root_path: string;
  status: string;
  supported_count: number;
  skipped_count: number;
  truncated: boolean;
  last_scan_at: string;
  created_at: string;
  updated_at: string;
};

export type ExtensionClientRecord = {
  id: string;
  name: string;
  enabled: boolean;
  allowed_vault_ids: string[];
  created_at: string;
  updated_at: string;
};

export type ExtensionClientCreateResponse = ExtensionClientRecord & {
  token: string;
};

export type ExtensionCaptureRecord = {
  id: string;
  client_id: string | null;
  vault_id: string;
  source_id: string | null;
  capture_type: string;
  title: string;
  url: string;
  status: string;
  created_at: string;
};

export type VaultLockAuditRecord = {
  id: string;
  event_type: string;
  pid: number | null;
  owner_pid: number | null;
  lock_path: string;
  detail: string;
  user_choice: string;
  created_at: string;
};

export async function getBridgeStatus() {
  return request<BridgeStatus>("/api/v1/bridge/status");
}

export async function listBridgeRequests() {
  return request<BridgeRequest[]>("/api/v1/bridge/requests");
}

export async function listBridgeTokenRotations() {
  return request<BridgeTokenRotation[]>("/api/v1/bridge/token-rotations");
}

export async function listBridgeClients() {
  return request<BridgeClientRecord[]>("/api/v1/bridge/clients");
}

export async function createBridgeClient(payload: {
  name: string;
  allowed_vault_ids?: string[];
  allowed_cluster_ids?: string[];
  allow_raw_snippets?: boolean;
  allow_style_profile?: boolean;
  allow_expert_calls?: boolean;
}) {
  return request<BridgeClientCreateResponse>("/api/v1/bridge/clients", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateBridgeClient(
  clientId: string,
  payload: Partial<
    Pick<
      BridgeClientRecord,
      | "name"
      | "enabled"
      | "allowed_vault_ids"
      | "allowed_cluster_ids"
      | "allow_raw_snippets"
      | "allow_style_profile"
      | "allow_expert_calls"
    >
  > & { rotate_token?: boolean },
) {
  return request<BridgeClientCreateResponse | BridgeClientRecord>(
    `/api/v1/bridge/clients/${encodeURIComponent(clientId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteBridgeClient(clientId: string) {
  await request<void>(`/api/v1/bridge/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

export async function updateBridgeSettings(
  payload: Partial<
    Pick<
      BridgeStatus,
      | "enabled"
      | "allowed_vault_ids"
      | "allowed_cluster_ids"
      | "allow_raw_snippets"
      | "allow_style_profile"
      | "allow_expert_calls"
      | "bridge_token"
    >
  > & { rotate_token?: boolean },
) {
  return request<BridgeStatus>("/api/v1/bridge/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function createDiagnosticBundle() {
  return request<DiagnosticBundleResponse>("/api/v1/diagnostics/bundle", { method: "POST" });
}

export async function listVaults() {
  return request<VaultRecord[]>("/api/v1/vaults");
}

export async function createVault(payload: { name: string; path: string }) {
  return request<VaultRecord>("/api/v1/vaults", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateVault(
  id: string,
  payload: Partial<Pick<VaultRecord, "name" | "path">>,
) {
  return request<VaultRecord>(`/api/v1/vaults/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function listClusters(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<ClusterRecord[]>(`/api/v1/clusters${query}`);
}

export async function createCluster(payload: {
  vault_id: string;
  name: string;
  description?: string;
  color?: string;
}) {
  return request<ClusterRecord>("/api/v1/clusters", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getCluster(id: string) {
  return request<ClusterRecord>(`/api/v1/clusters/${encodeURIComponent(id)}`);
}

export async function updateCluster(
  id: string,
  payload: Partial<Pick<ClusterRecord, "name" | "description" | "color" | "expert_status">>,
) {
  return request<ClusterRecord>(`/api/v1/clusters/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function listClusterExpertJobs(clusterId: string) {
  return request<ClusterExpertJobRecord[]>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/jobs`,
  );
}

export async function listClusterExpertArtifacts(clusterId: string) {
  return request<ExpertArtifactRecord[]>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/artifacts`,
  );
}

export async function getClusterExpertContract(clusterId: string) {
  return request<ExpertGraduationContractRecord>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/contract`,
  );
}

export async function activateClusterExpertArtifact(clusterId: string, artifactId: string) {
  return request<ExpertArtifactRecord>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/artifacts/${encodeURIComponent(artifactId)}/activate`,
    { method: "POST" },
  );
}

export async function rollbackClusterExpert(clusterId: string) {
  return request<ExpertArtifactRecord>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/rollback`,
    { method: "POST" },
  );
}

export async function deleteClusterExpertArtifact(clusterId: string, artifactId: string) {
  return request<void>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/artifacts/${encodeURIComponent(artifactId)}`,
    { method: "DELETE" },
  );
}

export async function retrainClusterExpert(clusterId: string) {
  return request<ClusterExpertJobRecord>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/retrain`,
    { method: "POST" },
  );
}

export async function pauseClusterExpert(clusterId: string) {
  return request<ClusterRecord>(`/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/pause`, {
    method: "POST",
  });
}

export async function mergeClusterInto(sourceClusterId: string, targetClusterId: string) {
  return request<ClusterRecord>(`/api/v1/clusters/${encodeURIComponent(sourceClusterId)}/merge`, {
    method: "POST",
    body: JSON.stringify({ target_cluster_id: targetClusterId }),
  });
}

export async function listClusterSuggestions(vaultId: string, limit = 12) {
  return request<ClusterSuggestionRecord[]>(
    `/api/v1/clusters/suggestions?vault_id=${encodeURIComponent(vaultId)}&limit=${limit}`,
  );
}

export async function listSources(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<SourceRecord[]>(`/api/v1/sources${query}`);
}

export async function createSource(payload: {
  vault_id: string;
  cluster_id?: string | null;
  title: string;
  source_type: string;
  original_path?: string | null;
  url?: string | null;
  raw_text?: string;
  cover_image_url?: string | null;
}) {
  return request<SourceRecord>("/api/v1/sources", {
    method: "POST",
    body: JSON.stringify({ raw_text: "", ...payload }),
  });
}

export async function createSourceFromPath(payload: {
  vault_id: string;
  cluster_id?: string | null;
  path: string;
}) {
  return request<SourceRecord>("/api/v1/sources/from-path", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createSourceFromText(payload: {
  vault_id: string;
  cluster_id?: string | null;
  title: string;
  text: string;
}) {
  return request<SourceRecord>("/api/v1/sources/from-text", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createSourceFromUrl(payload: {
  vault_id: string;
  cluster_id?: string | null;
  url: string;
}) {
  return request<SourceRecord>("/api/v1/sources/from-url", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateSource(
  id: string,
  payload: Partial<
    Pick<
      SourceRecord,
      | "cluster_id"
      | "title"
      | "state"
      | "raw_text"
      | "extracted_text"
      | "summary"
      | "tags"
      | "cover_image_url"
    >
  >,
) {
  return request<SourceRecord>(`/api/v1/sources/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function listSourcePages(sourceId: string) {
  return request<SourcePageRecord[]>(`/api/v1/sources/${encodeURIComponent(sourceId)}/pages`);
}

export async function deleteSource(id: string) {
  await request<void>(`/api/v1/sources/${id}`, { method: "DELETE" });
}

export async function semanticSearch(payload: {
  vault_id: string;
  query: string;
  cluster_id?: string | null;
  limit?: number;
}) {
  return request<SemanticSearchResponse>("/api/v1/search/semantic", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function reindexVaultSearch(vaultId: string) {
  return request<{ vault_id: string; sources_indexed: number; chunks_indexed: number }>(
    `/api/v1/search/reindex/${encodeURIComponent(vaultId)}`,
    { method: "POST" },
  );
}

export async function buildChatContext(payload: {
  vault_id: string;
  prompt: string;
  cluster_id?: string | null;
  session_id?: string | null;
  persist?: boolean;
  limit?: number;
  attachments?: Array<{ path: string; cluster_id?: string | null }>;
  expanded_analysis?: boolean;
}) {
  return request<ChatContextResponse>("/api/v1/chat/context", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function streamChatContext(
  payload: {
    vault_id: string;
    prompt: string;
    cluster_id?: string | null;
    session_id?: string | null;
    persist?: boolean;
    limit?: number;
    attachments?: Array<{ path: string; cluster_id?: string | null }>;
    expanded_analysis?: boolean;
  },
  handlers: {
    onMeta?: (
      payload: Pick<
        ChatContextResponse,
        | "clusters_used"
        | "citations"
        | "coverage_ledger"
        | "attachments_stored"
        | "intent"
        | "runtime_state"
        | "warnings"
      >,
    ) => void;
    onToken: (text: string) => void;
    onDone?: (payload: Partial<ChatContextResponse>) => void;
  },
  signal?: AbortSignal,
) {
  const backendUrl = await getBackendUrl();
  const token = await getBackendToken();
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("x-cml-api-token", token);
  const response = await fetch(`${backendUrl}/api/v1/chat/context/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Backend stream failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const eventBlock of events) {
      const event = parseSseEvent(eventBlock);
      if (!event) continue;
      if (event.event === "meta") handlers.onMeta?.(event.data);
      if (event.event === "token" && typeof event.data.text === "string")
        handlers.onToken(event.data.text);
      if (event.event === "done") handlers.onDone?.(event.data);
    }
  }
}

function parseSseEvent(block: string): { event: string; data: Record<string, unknown> } | null {
  const eventLine = block.split("\n").find((line) => line.startsWith("event:"));
  const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) return null;
  try {
    return {
      event: eventLine.slice(6).trim(),
      data: JSON.parse(dataLine.slice(5).trim()),
    };
  } catch {
    return null;
  }
}

export async function listChatSessions(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<ChatSessionRecord[]>(`/api/v1/chat/sessions${query}`);
}

export async function createChatSession(payload: {
  vault_id: string;
  title?: string | null;
  scope_cluster_id?: string | null;
}) {
  return request<ChatSessionRecord>("/api/v1/chat/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getChatSession(id: string) {
  return request<ChatSessionRecord>(`/api/v1/chat/sessions/${encodeURIComponent(id)}`);
}

export async function getChatTimeline(id: string) {
  return request<ChatTimelineResponse>(`/api/v1/chat/sessions/${encodeURIComponent(id)}/timeline`);
}

export async function updateChatSession(
  id: string,
  payload: Partial<Pick<ChatSessionRecord, "title" | "scope_cluster_id" | "saved">>,
) {
  return request<ChatSessionRecord>(`/api/v1/chat/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateChatMessage(
  id: string,
  payload: Partial<Pick<ChatMessageRecord, "useful" | "saved">>,
) {
  return request<ChatSessionRecord>(`/api/v1/chat/messages/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteChatSession(id: string) {
  await request<void>(`/api/v1/chat/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getJobStatus() {
  return request<JobQueueStatus>("/api/v1/jobs/status");
}

export async function runJobsOnce() {
  return request<JobQueueStatus>("/api/v1/jobs/run-once", { method: "POST" });
}

export async function cancelJob(jobId: string) {
  return request<AppJobRecord>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export async function listLocalModels() {
  return request<LocalModelRecord[]>("/api/v1/models");
}

export async function getModelRuntimeStatus() {
  return request<ModelRuntimeStatus>("/api/v1/models/runtime");
}

export async function getEmbeddingRuntimeStatus() {
  return request<EmbeddingRuntimeStatus>("/api/v1/models/embeddings");
}

export async function configureEmbeddingRuntime(payload: {
  provider: "sentence-transformers";
  cache_dir?: string | null;
  model?: string | null;
}) {
  return request<EmbeddingRuntimeStatus>("/api/v1/models/embeddings/configure", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEmbeddingDownloadStatus() {
  return request<EmbeddingModelDownloadState>("/api/v1/models/embeddings/download");
}

export async function startEmbeddingDownload(payload: {
  cache_dir?: string | null;
  model?: string | null;
}) {
  return request<EmbeddingModelDownloadState>("/api/v1/models/embeddings/download", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function cancelEmbeddingDownload() {
  return request<EmbeddingModelDownloadState>("/api/v1/models/embeddings/download/cancel", {
    method: "POST",
  });
}

export async function checkDiskPreflight(payload: {
  path: string;
  required_bytes?: number | null;
}) {
  return request<DiskPreflightResponse>("/api/v1/system/preflight/disk", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getStartupStatus() {
  return request<StartupStatusRead>("/api/v1/system/startup-status");
}

export async function getHardwareStatus() {
  return request<HardwareStatusRead>("/api/v1/system/hardware");
}

export async function getOCRRuntimeStatus() {
  return request<OCRRuntimeStatusRead>("/api/v1/system/ocr");
}

export async function getVaultSafetyStatus() {
  return request<VaultSafetyRead>("/api/v1/system/vault-safety");
}

export async function createVaultBackup() {
  return request<VaultSafetyRead>("/api/v1/system/vault-safety/backup", { method: "POST" });
}

export async function listVaultLockAudit(limit = 20) {
  return request<VaultLockAuditRecord[]>(`/api/v1/system/vault-lock/audit?limit=${limit}`);
}

export async function listIntegrationImports(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<IntegrationImportRecord[]>(`/api/v1/integrations/imports${query}`);
}

export async function scanLocalFolderIntegration(payload: {
  path: string;
  vault_id?: string | null;
  max_files?: number;
}) {
  return request<LocalFolderScanResponse>("/api/v1/integrations/local-folder/scan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function refreshIntegrationImport(importId: string) {
  return request<LocalFolderScanResponse>(
    `/api/v1/integrations/imports/${encodeURIComponent(importId)}/refresh`,
    { method: "POST" },
  );
}

export async function listExtensionClients() {
  return request<ExtensionClientRecord[]>("/api/v1/extension/clients");
}

export async function createExtensionClient(payload: { name: string }) {
  return request<ExtensionClientCreateResponse>("/api/v1/extension/clients", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateExtensionClient(
  clientId: string,
  payload: { enabled?: boolean; allowed_vault_ids?: string[] },
) {
  return request<ExtensionClientRecord>(`/api/v1/extension/clients/${encodeURIComponent(clientId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function revokeExtensionClient(clientId: string) {
  await request<void>(`/api/v1/extension/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

export async function listExtensionCaptures(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<ExtensionCaptureRecord[]>(`/api/v1/extension/captures${query}`);
}

export async function startModelDownload(modelId: string) {
  return request<ModelDownloadState>(`/api/v1/models/${encodeURIComponent(modelId)}/download`, {
    method: "POST",
  });
}

export async function cancelModelDownload(modelId: string) {
  return request<ModelDownloadState>(
    `/api/v1/models/${encodeURIComponent(modelId)}/download/cancel`,
    { method: "POST" },
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const backendUrl = await getBackendUrl();
  const token = await getBackendToken();
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("x-cml-api-token", token);
  const response = await fetch(`${backendUrl}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      detail = await response.text().catch(() => "");
    }
    throw new Error(detail || `Backend request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
