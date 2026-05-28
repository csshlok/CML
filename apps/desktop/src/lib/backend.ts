import { useEffect, useState } from "react";

const BACKEND_URL = "http://127.0.0.1:7342";

export type BackendHealthStatus = "checking" | "online" | "offline";

export function useBackendHealth() {
  const [status, setStatus] = useState<BackendHealthStatus>("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const response = await fetch(`${BACKEND_URL}/health`, {
          signal: AbortSignal.timeout(1000),
        });
        if (!cancelled) setStatus(response.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setStatus("offline");
      }
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
    url: BACKEND_URL,
  };
}

export type BridgeStatus = {
  enabled: boolean;
  mcp: string;
  http_api: string;
  cli: string;
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
  }>;
  warnings: string[];
};

export type ChatMessageRecord = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  clusters_used: ChatContextResponse["clusters_used"];
  citations: ChatContextResponse["citations"];
  warnings: string[];
  created_at: string;
};

export type ChatSessionRecord = {
  id: string;
  vault_id: string;
  title: string;
  scope_cluster_id: string | null;
  saved: boolean;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRecord[];
};

export async function getBridgeStatus() {
  return request<BridgeStatus>("/api/v1/bridge/status");
}

export async function listBridgeRequests() {
  return request<BridgeRequest[]>("/api/v1/bridge/requests");
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

export async function updateVault(id: string, payload: Partial<Pick<VaultRecord, "name" | "path">>) {
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
  payload: Partial<Pick<SourceRecord, "cluster_id" | "title" | "state" | "raw_text" | "extracted_text" | "summary" | "tags" | "cover_image_url">>,
) {
  return request<SourceRecord>(`/api/v1/sources/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
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

export async function deleteChatSession(id: string) {
  await request<void>(`/api/v1/chat/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
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
