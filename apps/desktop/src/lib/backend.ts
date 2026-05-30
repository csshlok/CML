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
};

export type BridgeRequest = {
  id: string;
  client_name: string;
  query: string;
  mode: string;
  created_at: string;
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
  created_at: string;
  updated_at: string;
};

export type AppJobRecord = {
  id: string;
  job_type: string;
  status: string;
  payload: string;
  dedupe_key: string | null;
  attempts: number;
  max_attempts: number;
  last_error: string;
  created_at: string;
  updated_at: string;
};

export type JobQueueStatus = {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
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
  warnings: string[];
  memory_status: string | null;
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
};

export async function getBridgeStatus() {
  return request<BridgeStatus>("/api/v1/bridge/status");
}

export async function listBridgeRequests() {
  return request<BridgeRequest[]>("/api/v1/bridge/requests");
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
  },
  handlers: {
    onMeta?: (
      payload: Pick<ChatContextResponse, "clusters_used" | "citations" | "warnings">,
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
}) {
  return request<EmbeddingRuntimeStatus>("/api/v1/models/embeddings/configure", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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
