import { useEffect, useState } from "react";

const CONFIGURED_BACKEND_URL =
  (import.meta.env.VITE_CML_BACKEND_URL as string | undefined) || "http://127.0.0.1:7343";
const CONFIGURED_BACKEND_TOKEN = import.meta.env.VITE_CML_API_TOKEN as string | undefined;
const API_PREFIX = (import.meta.env.VITE_CML_API_PREFIX as string | undefined) || "/api/v1";
const DEFAULT_BACKEND_CANDIDATES = [
  "http://127.0.0.1:7342",
  ...Array.from({ length: 13 }, (_value, index) => `http://127.0.0.1:${7343 + index}`),
];
const BACKEND_CANDIDATES = Array.from(
  new Set([CONFIGURED_BACKEND_URL, ...DEFAULT_BACKEND_CANDIDATES]),
);
let resolvedBackendUrl: string | null = null;
let resolvedBackendToken: string | null = CONFIGURED_BACKEND_TOKEN || null;

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
    window.cmlDesktop?.onBackendUrlChanged?.((nextUrl) => {
      if (nextUrl) resolvedBackendUrl = nextUrl;
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
      const token = await getBackendToken();
      for (const candidate of BACKEND_CANDIDATES) {
        const probe = await probeBackend(candidate, token);
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

async function probeBackend(url: string, token?: string | null): Promise<{ status: BackendHealthStatus }> {
  try {
    const response = await fetch(`${url}/health`, {
      signal: AbortSignal.timeout(1000),
    });
    if (!response.ok) return { status: "offline" };
    if (!token) return { status: "degraded" };
    const identity = await fetch(`${url}${API_PREFIX}/system/backend-identity`, {
      headers: { "x-cml-api-token": token },
      signal: AbortSignal.timeout(1500),
    });
    if (!identity.ok) return { status: "degraded" };
    const payload = await identity.json();
    const authenticated = payload?.service === "cml-backend" && payload?.api_prefix === API_PREFIX;
    return { status: authenticated ? "online" : "degraded" };
  } catch {
    return { status: "offline" };
  }
}

async function getBackendUrl() {
  if (resolvedBackendUrl) return resolvedBackendUrl;
  const token = await getBackendToken();
  for (const candidate of BACKEND_CANDIDATES) {
    const probe = await probeBackend(candidate, token);
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
  approval_requests_pending: number;
  last_refreshed_at?: string | null;
};

export type BridgeRequest = {
  id: string;
  client_id?: string | null;
  client_name: string;
  query: string;
  mode: string;
  decision: string;
  source_count: number;
  response_bytes: number;
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
  approval_vault_id?: string | null;
  allowed_vault_ids: string[];
  allowed_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_style_profile: boolean;
  allow_expert_calls: boolean;
  approval_request_id?: string | null;
  approved_at?: string | null;
  revoked_at?: string | null;
  last_request_at?: string | null;
  request_count_total: number;
  response_bytes_total: number;
  executable_path_claim: string;
  observed_executable_path: string;
  publisher_name: string;
  signature_status: string;
  signature_detail: string;
  verified_identity: boolean;
  verified_identity_label: string;
  created_at: string;
  updated_at: string;
};

export type BridgeClientCreateResponse = BridgeClientRecord & {
  token: string;
};

export type BridgeApprovalRequest = {
  id: string;
  vault_id: string;
  status: string;
  claimed_name: string;
  requested_vault_ids: string[];
  requested_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_style_profile: boolean;
  allow_expert_calls: boolean;
  executable_path_claim: string;
  observed_executable_path: string;
  publisher_name: string;
  signature_status: string;
  signature_detail: string;
  verified_identity: boolean;
  verified_identity_label: string;
  client_id?: string | null;
  requested_at: string;
  expires_at: string;
  decided_at?: string | null;
  delivered_at?: string | null;
  updated_at: string;
  detail: string;
};

export type BridgeAuditEvent = {
  id: string;
  vault_id?: string | null;
  client_id?: string | null;
  approval_request_id?: string | null;
  event_type: string;
  detail: string;
  created_at: string;
  updated_at: string;
};

export type VaultRecord = {
  id: string;
  name: string;
  path: string;
  created_at: string;
  updated_at: string;
};

export type UnlockStatusRead = {
  state: "locked" | "unlocking" | "verifying" | "repair_required" | "ready";
  vault_id: string | null;
  unlock_mode: "convenience" | "strict" | string;
  pin_enabled: boolean;
  message: string;
  verification_error: string;
  updated_at: string;
  ready: boolean;
  secured_vault_count: number;
  secured_vault_ids: string[];
  has_vendor_recovery: boolean;
};

export type UnlockInitializeResponse = UnlockStatusRead & {
  recovery_key: string;
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
  minimum_unique_sources: number;
  minimum_estimated_tokens: number;
  minimum_validation_records: number;
  minimum_quality_score: number;
  minimum_quality_delta: number;
  maximum_duplicate_ratio: number;
  required_artifact_files: string[];
  failure_codes: string[];
  graduation_gate: string;
  rollback_behavior: string;
};

export type ClusterExpertStatusRecord = {
  cluster_id: string;
  expert_status: string;
  user_status: string;
  searchable: boolean;
  trained: boolean;
  stale: boolean;
  active_artifact_id: string | null;
  active_dataset_hash: string | null;
  current_dataset_hash: string | null;
  runtime_load: {
    available?: boolean;
    runtime?: string;
    base_model?: string;
    adapter_path?: string;
    detail?: string;
  };
  failure_code: string;
  detail: string;
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

export type ChatEvidenceRetentionPolicy = {
  default_keep_latest_snapshots_per_message: number;
  max_keep_latest_snapshots_per_message: number;
  default_excerpt_chars: number;
  deleted_source_state: string;
  compacted_state: string;
  query_cache_prune_endpoint: string;
};

export type ChatEvidenceRetentionResult = {
  message_id: string | null;
  keep_latest_per_message: number;
  excerpt_chars: number;
  compacted_snapshots: number;
  deleted_source_tombstones: number;
  trimmed_items: number;
  retained_at: string;
};

export type QueryCachePruneResult = {
  vault_id: string | null;
  max_age_days: number;
  max_items: number;
  max_payload_bytes: number;
  deleted_old_or_invalidated: number;
  deleted_oversized: number;
  deleted_over_limit: number;
};

export type ModelDownloadState = {
  model_id: string;
  status: string;
  bytes_downloaded: number | null;
  total_bytes: number | null;
  progress_percent?: number | null;
  download_speed_bps?: number | null;
  eta_seconds?: number | null;
  file_name: string | null;
  local_path: string | null;
  error: string | null;
  sha256?: string | null;
  integrity_status?: string | null;
};

export type ModelCompatibilityRecord = {
  status: "accepted" | "rejected";
  accepted: boolean;
  chat_role_accepted: boolean;
  expert_role_accepted: boolean;
  accepted_roles: string[];
  family: string;
  family_name: string;
  model_type: string;
  architecture: string;
  registered_family: string;
  local_path: string;
  runtime_dependencies: Record<string, unknown>;
  hardware: Record<string, unknown>;
  reasons: string[];
  pairing_detail: string;
  detail: string;
};

export type LocalModelRecord = {
  id: string;
  name: string;
  role: string;
  hf_repo: string;
  family: string;
  quantization: string;
  approximate_download_gb: number;
  recommended_ram_gb: string;
  notes: string;
  llama_cpp_ref: string;
  installed: boolean;
  local_path: string | null;
  download: ModelDownloadState | null;
  active: boolean;
  active_chat: boolean;
  active_expert: boolean;
  compatibility: ModelCompatibilityRecord | null;
  source_kind: string;
};

export type ModelRecommendationsRecord = {
  hardware: Record<string, unknown>;
  recommended_model_id: string;
  recommended_chat_model_id: string;
  recommended_expert_family: string;
  active_pair: Record<string, unknown>;
  models: LocalModelRecord[];
  detected_compatible_models: DiscoveredInstalledModelRecord[];
  detected_compatible_model_count: number;
  detail: string;
};

export type DiscoveredInstalledModelRecord = {
  id: string;
  name: string;
  family: string;
  family_name: string;
  local_path: string;
  source_root: string;
  source_kind: string;
  already_imported: boolean;
  compatibility: ModelCompatibilityRecord;
  detail: string;
};

export type InstalledModelDiscoveryRecord = {
  models: DiscoveredInstalledModelRecord[];
  compatible_model_count: number;
  scanned_root_count: number;
  scanned_roots: string[];
  missing_roots: string[];
  truncated: boolean;
  scan_duration_ms: number;
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
  pdf_ocr_engine: string | null;
  full_pdf_ocr_available: boolean;
  fallback_pdf_ocr_available: boolean;
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
  reconciliation_run_id: string | null;
  path: string;
  integration_type: string;
  supported_files: string[];
  supported_count: number;
  skipped_count: number;
  truncated: boolean;
  imported_count: number;
  updated_count: number;
  moved_count: number;
  unchanged_count: number;
  tombstoned_count: number;
  failed_count: number;
  failures: Array<{ path: string; error: string }>;
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
  imported_count: number;
  updated_count: number;
  moved_count: number;
  unchanged_count: number;
  tombstoned_count: number;
  failed_count: number;
  last_failures: Array<{ path: string; error: string }>;
  last_reconciliation_run_id: string | null;
  last_reconciliation_status: string | null;
  last_reconciliation_trigger_source: string | null;
  last_reconciliation_finished_at: string | null;
  last_reconciliation_detail_count: number;
  last_reconciliation_retryable_failed_count: number;
  last_scan_at: string;
  last_import_at: string | null;
  watch_enabled: boolean;
  watch_interval_seconds: number;
  next_watch_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ReconciliationRunRecord = {
  id: string;
  vault_id: string;
  import_id: string;
  trigger_source: string;
  root_path: string;
  status: string;
  import_files: boolean;
  tombstone_missing: boolean;
  imported_count: number;
  updated_count: number;
  moved_count: number;
  unchanged_count: number;
  tombstoned_count: number;
  failed_count: number;
  retryable_failed_count: number;
  detail_count: number;
  started_at: string;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ReconciliationItemRecord = {
  id: string;
  run_id: string;
  vault_id: string;
  import_id: string;
  item_reference: string;
  action: string;
  result: string;
  error: string;
  retryable: boolean;
  detail: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ReconciliationItemPage = {
  run_id: string;
  items: ReconciliationItemRecord[];
  total: number;
  limit: number;
  offset: number;
};

export type ReconciliationItemRetryResult = {
  retried_item_id: string;
  new_run: ReconciliationRunRecord;
  new_item: ReconciliationItemRecord | null;
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

export async function listBridgeApprovalRequests() {
  return request<BridgeApprovalRequest[]>("/api/v1/bridge/approval-requests");
}

export async function approveBridgeApprovalRequest(
  requestId: string,
  payload: {
    allowed_vault_ids?: string[];
    allowed_cluster_ids?: string[];
    allow_raw_snippets?: boolean;
    allow_style_profile?: boolean;
    allow_expert_calls?: boolean;
    detail?: string;
  } = {},
) {
  return request<BridgeClientCreateResponse>(
    `/api/v1/bridge/approval-requests/${encodeURIComponent(requestId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function rejectBridgeApprovalRequest(
  requestId: string,
  payload: { detail?: string } = {},
) {
  return request<BridgeApprovalRequest>(
    `/api/v1/bridge/approval-requests/${encodeURIComponent(requestId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function listBridgeAuditEvents() {
  return request<BridgeAuditEvent[]>("/api/v1/bridge/audit-events");
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

export async function getClusterExpertStatus(clusterId: string) {
  return request<ClusterExpertStatusRecord>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/expert/status`,
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

export async function pruneQueryCache(payload?: {
  vault_id?: string | null;
  max_age_days?: number;
  max_items?: number;
  max_payload_bytes?: number;
}) {
  const params = new URLSearchParams();
  if (payload?.vault_id) params.set("vault_id", payload.vault_id);
  if (payload?.max_age_days !== undefined) params.set("max_age_days", String(payload.max_age_days));
  if (payload?.max_items !== undefined) params.set("max_items", String(payload.max_items));
  if (payload?.max_payload_bytes !== undefined) {
    params.set("max_payload_bytes", String(payload.max_payload_bytes));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<QueryCachePruneResult>(`/api/v1/search/query-cache/prune${query}`, {
    method: "POST",
  });
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

export async function getChatEvidenceRetentionPolicy() {
  return request<ChatEvidenceRetentionPolicy>("/api/v1/chat/evidence-retention/policy");
}

export async function enforceChatEvidenceRetention(payload?: {
  message_id?: string | null;
  keep_latest_per_message?: number;
  excerpt_chars?: number;
}) {
  const params = new URLSearchParams();
  if (payload?.message_id) params.set("message_id", payload.message_id);
  if (payload?.keep_latest_per_message !== undefined) {
    params.set("keep_latest_per_message", String(payload.keep_latest_per_message));
  }
  if (payload?.excerpt_chars !== undefined) {
    params.set("excerpt_chars", String(payload.excerpt_chars));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<ChatEvidenceRetentionResult>(`/api/v1/chat/evidence-retention/enforce${query}`, {
    method: "POST",
  });
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

export async function getModelRecommendations() {
  return request<ModelRecommendationsRecord>("/api/v1/models/recommendations");
}

export async function discoverInstalledModels(payload?: {
  max_results?: number;
  include_rejected?: boolean;
}) {
  const query = new URLSearchParams();
  if (payload?.max_results) query.set("max_results", String(payload.max_results));
  if (payload?.include_rejected) query.set("include_rejected", "true");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<InstalledModelDiscoveryRecord>(`/api/v1/models/discover${suffix}`);
}

export async function getModelCompatibilityReport(payload: { path: string; name?: string | null }) {
  return request<ModelCompatibilityRecord>("/api/v1/models/compatibility/report", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importLocalModel(payload: { path: string; name?: string | null }) {
  return request<LocalModelRecord>("/api/v1/models/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function activateLocalModel(modelId: string, role: "chat" | "expert" | "pair" = "chat") {
  return request<LocalModelRecord>(`/api/v1/models/${encodeURIComponent(modelId)}/activate`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
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

export async function getUnlockStatus() {
  return request<UnlockStatusRead>("/api/v1/system/unlock/status");
}

export async function initializeVaultSecurity(payload: {
  vault_id: string;
  passphrase: string;
  unlock_mode?: "convenience" | "strict";
}) {
  return request<UnlockInitializeResponse>("/api/v1/system/unlock/initialize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function unlockVaultWithPassphrase(payload: { vault_id: string; passphrase: string }) {
  return request<UnlockStatusRead>("/api/v1/system/unlock/passphrase", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function lockVault(vaultId?: string | null) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<UnlockStatusRead>(`/api/v1/system/unlock/lock${query}`, { method: "POST" });
}

export async function updateUnlockSettings(payload: {
  vault_id: string;
  unlock_mode?: "convenience" | "strict" | null;
  pin_enabled?: boolean | null;
}) {
  return request<{
    vault_id: string;
    unlock_mode: string;
    pin_enabled: boolean;
    has_vendor_recovery: boolean;
  }>("/api/v1/system/unlock/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
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

export async function refreshIntegrationImport(
  importId: string,
  options?: { import_files?: boolean; tombstone_missing?: boolean },
) {
  const params = new URLSearchParams();
  if (options?.import_files) params.set("import_files", "true");
  if (options?.tombstone_missing) params.set("tombstone_missing", "true");
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<LocalFolderScanResponse>(
    `/api/v1/integrations/imports/${encodeURIComponent(importId)}/refresh${query}`,
    { method: "POST" },
  );
}

export async function updateIntegrationImport(
  importId: string,
  payload: { watch_enabled?: boolean; watch_interval_seconds?: number },
) {
  return request<IntegrationImportRecord>(`/api/v1/integrations/imports/${encodeURIComponent(importId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function listIntegrationReconciliationRuns(importId: string, limit = 10) {
  return request<ReconciliationRunRecord[]>(
    `/api/v1/integrations/imports/${encodeURIComponent(importId)}/reconciliation-runs?limit=${limit}`,
  );
}

export async function listIntegrationReconciliationItems(
  runId: string,
  options?: { limit?: number; offset?: number; result?: string },
) {
  const params = new URLSearchParams();
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.offset) params.set("offset", String(options.offset));
  if (options?.result) params.set("result", options.result);
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<ReconciliationItemPage>(
    `/api/v1/integrations/reconciliation-runs/${encodeURIComponent(runId)}/items${suffix}`,
  );
}

export async function retryIntegrationReconciliationItem(itemId: string) {
  return request<ReconciliationItemRetryResult>(
    `/api/v1/integrations/reconciliation-items/${encodeURIComponent(itemId)}/retry`,
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
