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
  created_at: string;
  updated_at: string;
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
}) {
  return request<SourceRecord>("/api/v1/sources", {
    method: "POST",
    body: JSON.stringify({ raw_text: "", ...payload }),
  });
}

export async function updateSource(
  id: string,
  payload: Partial<Pick<SourceRecord, "cluster_id" | "title" | "state" | "raw_text" | "extracted_text" | "summary">>,
) {
  return request<SourceRecord>(`/api/v1/sources/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteSource(id: string) {
  await request<void>(`/api/v1/sources/${id}`, { method: "DELETE" });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (!response.ok) {
    throw new Error(`Backend request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
