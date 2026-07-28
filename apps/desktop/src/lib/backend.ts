import { useEffect, useSyncExternalStore } from "react";

const CONFIGURED_BACKEND_URL =
  (import.meta.env.VITE_CML_BACKEND_URL as string | undefined) || "http://127.0.0.1:7343";
const CONFIGURED_BACKEND_TOKEN = import.meta.env.VITE_CML_API_TOKEN as string | undefined;
const DEFAULT_API_PREFIX = "/api/v1";
const API_PREFIX = normalizeApiPrefix(import.meta.env.VITE_CML_API_PREFIX as string | undefined);
export const BACKEND_API_PREFIX = API_PREFIX;
const DEFAULT_BACKEND_CANDIDATES = [
  "http://127.0.0.1:7342",
  ...Array.from({ length: 13 }, (_value, index) => `http://127.0.0.1:${7343 + index}`),
];
const BACKEND_CANDIDATES = Array.from(
  new Set([CONFIGURED_BACKEND_URL, ...DEFAULT_BACKEND_CANDIDATES]),
);
let resolvedBackendUrl: string | null = null;
let resolvedBackendToken: string | null = CONFIGURED_BACKEND_TOKEN || null;
let backendGeneration = 0;
let healthCheckPromise: Promise<void> | null = null;
const desktopManagedBackend = typeof window !== "undefined" && Boolean(window.cmlDesktop);

if (typeof window !== "undefined") {
  const queryBackendUrl = new URLSearchParams(window.location.search).get("backendUrl");
  if (queryBackendUrl) {
    resolvedBackendUrl = queryBackendUrl;
  }
  const initialGeneration = backendGeneration;
  void window.cmlDesktop?.getBackendUrl?.().then((url) => {
    if (backendGeneration !== initialGeneration) return;
    if (url) {
      resolvedBackendUrl = url;
      publishHealth({ status: "checking", url });
    }
  });
  void window.cmlDesktop?.getBackendToken?.().then((token) => {
    if (token) resolvedBackendToken = token;
  });
  window.cmlDesktop?.onBackendUrlChanged?.((nextUrl) => {
    backendGeneration += 1;
    resolvedBackendUrl = nextUrl || null;
    discoveryPromise = null;
    lastDiscoveryAttempt = 0;
    publishHealth({
      status: "checking",
      url: nextUrl || CONFIGURED_BACKEND_URL,
    });
    if (nextUrl) void coordinateHealthCheck();
  });
}

export type BackendHealthStatus = "checking" | "online" | "degraded" | "offline";

export type CursorPage<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
};

type BackendHealthSnapshot = { status: BackendHealthStatus; url: string };
let healthSnapshot: BackendHealthSnapshot = {
  status: "checking",
  url: CONFIGURED_BACKEND_URL,
};
const serverHealthSnapshot: BackendHealthSnapshot = {
  status: "checking",
  url: CONFIGURED_BACKEND_URL,
};
const healthListeners = new Set<() => void>();
let healthCoordinatorStarted = false;
let discoveryPromise: Promise<string> | null = null;
let lastDiscoveryAttempt = 0;

function publishHealth(next: BackendHealthSnapshot) {
  if (healthSnapshot.status === next.status && healthSnapshot.url === next.url) return;
  healthSnapshot = next;
  healthListeners.forEach((listener) => listener());
}

function subscribeHealth(listener: () => void) {
  healthListeners.add(listener);
  return () => healthListeners.delete(listener);
}

async function runHealthCheck() {
  const generation = backendGeneration;
  const token = await getBackendToken();
  const candidates = desktopManagedBackend
    ? (resolvedBackendUrl ? [resolvedBackendUrl] : [])
    : resolvedBackendUrl
      ? [resolvedBackendUrl, ...BACKEND_CANDIDATES.filter((item) => item !== resolvedBackendUrl)]
      : BACKEND_CANDIDATES;
  for (const candidate of candidates) {
    const probe = await probeBackend(candidate, token);
    if (generation !== backendGeneration) return;
    if (probe.status === "online" || (probe.status === "degraded" && candidate === CONFIGURED_BACKEND_URL)) {
      resolvedBackendUrl = candidate;
      publishHealth({ status: probe.status, url: candidate });
      return;
    }
  }
  if (generation !== backendGeneration) return;
  resolvedBackendUrl = null;
  publishHealth({ status: "offline", url: CONFIGURED_BACKEND_URL });
}

function coordinateHealthCheck() {
  if (!healthCheckPromise) {
    healthCheckPromise = runHealthCheck().finally(() => {
      healthCheckPromise = null;
    });
  }
  return healthCheckPromise;
}

function startHealthCoordinator() {
  if (healthCoordinatorStarted || typeof window === "undefined") return;
  healthCoordinatorStarted = true;
  const schedule = async () => {
    if (!document.hidden) await coordinateHealthCheck();
    const delay = healthSnapshot.status === "offline" ? 15_000 : 8_000;
    window.setTimeout(schedule, document.hidden ? delay * 4 : delay);
  };
  const onVisibility = () => {
    if (!document.hidden) void coordinateHealthCheck();
  };
  document.addEventListener("visibilitychange", onVisibility);
  void schedule();
}

export function useBackendHealth() {
  useEffect(() => startHealthCoordinator(), []);
  return useSyncExternalStore(subscribeHealth, () => healthSnapshot, () => serverHealthSnapshot);
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
  const now = Date.now();
  if (!discoveryPromise && now - lastDiscoveryAttempt < 5_000) return CONFIGURED_BACKEND_URL;
  if (!discoveryPromise) {
    const generation = backendGeneration;
    lastDiscoveryAttempt = now;
    discoveryPromise = (async () => {
      const token = await getBackendToken();
      for (const candidate of BACKEND_CANDIDATES) {
        const probe = await probeBackend(candidate, token);
        if (generation !== backendGeneration) {
          return resolvedBackendUrl || CONFIGURED_BACKEND_URL;
        }
        if (probe.status === "online" || (probe.status === "degraded" && candidate === CONFIGURED_BACKEND_URL)) {
          resolvedBackendUrl = candidate;
          publishHealth({ status: probe.status, url: candidate });
          return candidate;
        }
      }
      publishHealth({ status: "offline", url: CONFIGURED_BACKEND_URL });
      return CONFIGURED_BACKEND_URL;
    })().finally(() => {
      discoveryPromise = null;
    });
  }
  return discoveryPromise;
}

async function getBackendToken() {
  if (resolvedBackendToken) return resolvedBackendToken;
  const token = await window.cmlDesktop?.getBackendToken?.();
  if (token) resolvedBackendToken = token;
  return resolvedBackendToken;
}

export type BridgeStatus = {
  schema_version: number;
  enabled: boolean;
  mcp: string;
  http_api: string;
  cli: string;
  allowed_vault_ids: string[];
  allowed_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_cluster_profile: boolean;
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
  capability_profile: "read_only" | "read_write";
  approval_vault_id?: string | null;
  allowed_vault_ids: string[];
  allowed_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_cluster_profile: boolean;
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
  capability_profile: "read_only" | "read_write";
  requested_vault_ids: string[];
  requested_cluster_ids: string[];
  allow_raw_snippets: boolean;
  allow_cluster_profile: boolean;
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

export type BridgeWritebackReview = {
  source_id: string;
  vault_id: string;
  context_request_id?: string | null;
  quality_state: string;
  approved: boolean;
  reasons: string[];
  title: string;
  trust_tier: string;
  security_labels: string[];
  updated_at: string;
};

export type BridgeCaptureRecord = {
  source_id: string;
  vault_id: string;
  cluster_id?: string | null;
  title: string;
  source_type: string;
  quality_state: string;
  approved: boolean;
  trust_tier: string;
  security_labels: string[];
  created_at: string;
};

export type BridgeCaptureResponse = {
  source_id: string;
  vault_id: string;
  cluster_id?: string | null;
  source_type: string;
  indexed: boolean;
  quality_state: string;
  approved: boolean;
  review_required: boolean;
  trust_tier: string;
  reasons: string[];
  security_labels: string[];
  warnings: string[];
};

export type BridgeArtifactCapturePayload = {
  vault_id?: string | null;
  cluster_id?: string | null;
  client_name: string;
  title: string;
  content: string;
  artifact_type?: string;
  metadata?: Record<string, unknown>;
};

export type BridgeExternalTurnPayload = {
  vault_id?: string | null;
  cluster_id?: string | null;
  client_name: string;
  user_prompt: string;
  model_response: string;
  context_request_id?: string | null;
  model_name?: string | null;
  metadata?: Record<string, unknown>;
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
  index_status: string;
  profile_status: string;
  cluster_summary: string;
  cluster_glossary: string;
  profile_updated_at?: string | null;
  profile_source_hash?: string;
  indexed_source_count?: number;
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

export type ProjectSnapshotRecord = {
  id: string;
  project_id: string;
  discovery_scope: "context" | "code";
  source_manifest_hash: string;
  git_commit: string | null;
  branch: string | null;
  dirty_working_tree: boolean;
  extractor_version: string;
  eligible_count: number;
  ignored_count: number;
  generated_count: number;
  parsed_count: number;
  failed_count: number;
  structure_status: string;
  retrieval_status: string;
  interpretation_status: string;
  activated_at: string | null;
  manifest_activated_at: string | null;
  structure_activated_at: string | null;
  retrieval_activated_at: string | null;
  created_at: string;
};

export type ProjectIndexRunRecord = {
  id: string;
  project_id: string;
  snapshot_id: string | null;
  job_id: string | null;
  trigger_source: string;
  status: "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled" | string;
  phase: string;
  eligible_total: number;
  completed_count: number;
  skipped_count: number;
  failed_count: number;
  phase_completed_count: number;
  phase_total_count: number;
  cancellation_requested: boolean;
  cancellation_requested_at: string | null;
  heartbeat_at: string | null;
  queued_at: string | null;
  activation_outcome: string;
  failure_category: string;
  detail_json: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectRecord = {
  id: string;
  vault_id: string;
  name: string;
  root_path: string;
  root_fingerprint: string;
  discovery_scope: "context" | "code";
  primary_cluster_id: string;
  repository_kind: "git" | "folder" | string;
  git_remote_fingerprint: string | null;
  default_branch: string | null;
  indexed_commit: string | null;
  working_tree_dirty: boolean;
  changed_file_count: number;
  status: string;
  structure_status: string;
  retrieval_status: string;
  interpretation_status: string;
  active_snapshot_id: string | null;
  active_manifest_snapshot_id: string | null;
  active_structure_snapshot_id: string | null;
  active_retrieval_snapshot_id: string | null;
  candidate_snapshot_id: string | null;
  active_run_id: string | null;
  active_snapshot: ProjectSnapshotRecord | null;
  brief: string;
  languages: Record<string, number>;
  workspace_count: number;
  entrypoints: string[];
  source_count: number;
  created_at: string;
  updated_at: string;
};

export type CliPairingChallenge = {
  id: string;
  status: string;
  requester_name: string;
  executable_fingerprint: string;
  requested_scopes: string[];
  client_id: string | null;
  created_at: string;
  expires_at: string;
  approved_at: string | null;
  denied_at: string | null;
  consumed_at: string | null;
};

export type CliClientRecord = {
  id: string;
  display_name: string;
  executable_fingerprint: string;
  credential_version: number;
  scopes: string[];
  allowed_vault_ids: string[];
  created_at: string;
  last_used_at: string | null;
  rotated_at: string | null;
  revoked_at: string | null;
  requires_pairing?: boolean;
};

export type ProjectGraphNode = {
  id: string;
  qualified_id: string;
  kind: string;
  language: string;
  label: string;
  relative_path: string;
  start_line: number | null;
  end_line: number | null;
  signature: string;
  source_id: string | null;
};

export type ProjectGraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: string;
  evidence_source_id: string | null;
  source_line: number | null;
};

export type ProjectGraphView = {
  version: number;
  project_id: string;
  snapshot_id: string;
  indexed_commit: string | null;
  mode: "graph" | "tree";
  direction: "outbound" | "inbound" | "balanced";
  query: string;
  root: string;
  nodes: ProjectGraphNode[];
  edges: ProjectGraphEdge[];
  truncated: boolean;
  limits: { max_nodes: number; max_depth: number };
  warnings: string[];
};

export type AppJobRecord = {
  id: string;
  job_type: string;
  status: string;
  payload: string;
  result_json?: string;
  dedupe_key: string | null;
  priority?: string | null;
  write_scope?: string | null;
  scope_id?: string | null;
  resource_cost?: string | null;
  user_visible?: number | null;
  cancellable?: number | null;
  timeout_seconds?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_seconds?: number | null;
  estimated_remaining_seconds?: number | null;
  status_detail?: string | null;
  cancellation_requested?: number | null;
  cancellation_requested_at?: string | null;
  attempts: number;
  max_attempts: number;
  last_error: string;
  created_at: string;
  updated_at: string;
};

export type JobQueueStatus = {
  queued: number;
  paused: number;
  blocked_by_dependency: number;
  blocked_setup_required: number;
  deferred: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  manual_review: number;
  running_jobs: AppJobRecord[];
  latest: AppJobRecord[];
};

export type SourceImportFailure = {
  file_name: string;
  reason: string;
};

export type SourceImportProgress = {
  kind: "source_import";
  total_files: number;
  completed_files: number;
  imported_files: number;
  updated_files: number;
  failed_files: number;
  failures: SourceImportFailure[];
  current_file: string;
  truncated_at: number | null;
};

export type TemporalFactDiagnostics = {
  vault_id: string;
  extractor_version: string;
  status_counts: Record<string, number>;
  speaker_counts: Record<string, number>;
  assertion_kind_counts: Record<string, number>;
  session_count: number;
  indexed_session_count: number;
  latest_observed_at: string | null;
  latest_processed_at: string | null;
};

export type TemporalFactRecord = {
  id: string;
  vault_id: string;
  cluster_id: string | null;
  subject_key: string;
  predicate_key: string;
  object_text: string;
  assertion_kind: string;
  modality: string;
  source_type: string;
  citation_excerpt: string;
  observed_at: string;
  valid_from: string;
  status: string;
  confidence: number;
};

export type RetrievalPackingDiagnostics = {
  vault_id: string;
  query_count: number;
  candidate_citation_count: number;
  selected_citation_count: number;
  raw_context_tokens: number;
  final_context_tokens: number;
  context_tokens_avoided: number;
  context_reduction_percent: number;
  raw_evidence_tokens: number;
  selected_evidence_tokens: number;
  average_final_context_tokens: number;
  latest_query_at: string | null;
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
  import_outcome?: "created" | "updated" | null;
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
    relative_path?: string | null;
    line_start?: number | null;
    line_end?: number | null;
    symbol?: string | null;
    project_snapshot_id?: string | null;
    indexed_commit?: string | null;
  }>;
  coverage_ledger: {
    sources_considered: number;
    sources_analyzed: number;
    sources_low_relevance: number;
    relevance_threshold: number;
    scope: string;
    trust_gate_mode?: string;
    trusted_evidence_count?: number;
    low_trust_evidence_count?: number;
    trust_gate_latency_ms?: number;
    route_policy?: string;
    route_reason?: string;
    analysis_mode?: string;
    retrieval_attempted?: boolean;
    token_budget?: number;
    budget_hardware_tier?: string;
    budget_model_tier?: string;
    budget_query_type?: string;
    budget_trust_mode?: string;
    budget_widening_applied?: boolean;
    budget_narrowing_applied?: boolean;
    budget_widening_reason?: string;
    budget_narrowing_reason?: string;
    prompt_tokens_estimate?: number;
    evidence_tokens_estimate?: number;
    history_tokens_estimate?: number;
    history_turns_selected?: number;
    history_turns_trimmed?: number;
    memory_items_selected?: number;
    citations_selected?: number;
    citations_trimmed?: number;
    candidate_citations?: number;
    supported_claims_count?: number;
    unsupported_claims_count?: number;
    contradiction_detected?: boolean;
    synthesis_guard_mode?: string;
    budget_applied?: boolean;
    partial_failure_mode?: string;
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
  generation_id: string | null;
  reply_to_message_id: string | null;
  generation_state: string | null;
};

export type ChatSessionRecord = {
  id: string;
  vault_id: string;
  title: string;
  scope_cluster_id: string | null;
  scope_project_id: string | null;
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
  bytes_total?: number | null;
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
  selection_detail: string;
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
  integrity?: {
    status: "missing" | "unverified" | "recorded" | "verified" | "mismatch";
    sha256?: string | null;
    expected_sha256?: string | null;
    detail?: string;
  } | null;
  active: boolean;
  active_chat: boolean;
  compatibility: ModelCompatibilityRecord | null;
  source_kind: string;
};

export type ClusterMergeArtifact = {
  id: string;
  vault_id: string;
  source_cluster_id: string;
  target_cluster_id: string;
  moved_source_ids: string[];
  moved_chat_session_ids: string[];
  reversible: boolean;
  rolled_back_at: string | null;
  created_at: string;
};

export type SourceStatsRecord = {
  source_id: string;
  page_count: number;
  chunk_count: number;
  size_bytes: number | null;
  last_error: string | null;
};

export type ReindexQueueResult = {
  status: string;
  job_id?: string;
  source_id?: string;
  vault_id?: string;
  sources_matched?: number;
  jobs_queued?: number;
};

export type ModelRecommendationsRecord = {
  hardware: Record<string, unknown>;
  recommended_model_id: string;
  recommended_chat_model_id: string;
  chat_fit_type: string;
  chat_estimated_tok_per_sec?: number | null;
  evidence_level: string;
  confidence: string;
  warnings: string[];
  reasons: string[];
  fallback_low_spec: {
    id?: string;
    name?: string;
    detail?: string;
  };
  fallback_fastest: {
    id?: string;
    name?: string;
    detail?: string;
  };
  active_chat_setup: Record<string, unknown>;
  chat_recommendation: {
    id?: string;
    name?: string;
    family?: string;
    summary?: string;
    score?: number;
    reasons?: string[];
    fit?: {
      fit_type?: string;
      feasible?: boolean;
      warnings?: string[];
    };
    speed?: {
      estimated_tok_per_sec?: number;
      confidence?: string;
      range_tok_per_sec?: [number, number] | null;
    };
    evidence?: {
      source?: string;
      confidence?: number;
      updated_at?: string;
    };
  };
  models: LocalModelRecord[];
  detected_compatible_models: DiscoveredInstalledModelRecord[];
  detected_compatible_model_count: number;
  rejected_candidates?: Array<{
    candidate_id: string;
    rejection_type: string;
    detail: string;
  }>;
  detail: string;
  operator_summary?: string;
  scoring_breakdown?: Record<string, unknown>;
  candidate_table?: Array<Record<string, unknown>>;
  benchmark_evidence_audit?: Array<Record<string, unknown>>;
  catalog_version?: string;
  benchmark_bundle_version?: string;
  catalog_models?: Array<Record<string, unknown>>;
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
  state?: string;
  detail: string;
  in_flight?: number;
  pid?: number | null;
  error?: string | null;
  managed?: boolean;
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

export type ExtensionPairingRecord = {
  id: string;
  pairing_code: string;
  status: string;
  requested_name: string;
  allowed_vault_ids: string[];
  created_at: string;
  expires_at: string;
  completed_at?: string | null;
};

export type ExtensionStatusResponse = {
  ok: boolean;
  client_id?: string | null;
  detail: string;
};

export type ExtensionPermissionAuditRecord = {
  id: string;
  client_id: string | null;
  event_type: string;
  vault_id: string | null;
  detail: string;
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

function paginationQuery(options: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  return params;
}

export async function listBridgeRequests(options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeRequest[]>(`/api/v1/bridge/requests${suffix}`);
}

export async function listBridgeTokenRotations(options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeTokenRotation[]>(`/api/v1/bridge/token-rotations${suffix}`);
}

export async function listBridgeClients(options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeClientRecord[]>(`/api/v1/bridge/clients${suffix}`);
}

export async function listBridgeApprovalRequests(options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeApprovalRequest[]>(`/api/v1/bridge/approval-requests${suffix}`);
}

export async function approveBridgeApprovalRequest(
  requestId: string,
  payload: {
    capability_profile?: "read_only" | "read_write";
    allowed_vault_ids?: string[];
    allowed_cluster_ids?: string[];
    allow_raw_snippets?: boolean;
    allow_cluster_profile?: boolean;
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

export async function listBridgeAuditEvents(options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeAuditEvent[]>(`/api/v1/bridge/audit-events${suffix}`);
}

export async function listBridgeWritebackReviews(
  vaultId?: string,
  pendingOnly = false,
  options: { limit?: number; offset?: number } = {},
) {
  const params = paginationQuery(options);
  if (vaultId) params.set("vault_id", vaultId);
  if (pendingOnly) params.set("pending_only", "true");
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeWritebackReview[]>(`/api/v1/bridge/reviews${suffix}`);
}

export async function listBridgeWritebackReviewsPage(
  vaultId?: string,
  pendingOnly = false,
  options: { limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (pendingOnly) params.set("pending_only", "true");
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<CursorPage<BridgeWritebackReview>>(`/api/v1/bridge/reviews/page${suffix}`);
}

export async function decideBridgeWritebackReview(
  sourceId: string,
  approved: boolean,
  expectedUpdatedAt?: string,
) {
  return request<BridgeWritebackReview>(`/api/v1/bridge/reviews/${encodeURIComponent(sourceId)}`, {
    method: "POST",
    body: JSON.stringify({
      approved,
      expected_updated_at: expectedUpdatedAt,
      idempotency_key: crypto.randomUUID(),
    }),
  });
}

export async function listBridgeCaptures(vaultId?: string, options: { limit?: number; offset?: number } = {}) {
  const params = paginationQuery(options);
  if (vaultId) params.set("vault_id", vaultId);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<BridgeCaptureRecord[]>(`/api/v1/bridge/captures${suffix}`);
}

export async function listBridgeCapturesPage(
  vaultId?: string,
  options: { limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request<CursorPage<BridgeCaptureRecord>>(`/api/v1/bridge/captures/page${suffix}`);
}

export async function captureBridgeArtifact(payload: BridgeArtifactCapturePayload) {
  return request<BridgeCaptureResponse>("/api/v1/bridge/artifacts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function captureBridgeExternalTurn(payload: BridgeExternalTurnPayload) {
  return request<BridgeCaptureResponse>("/api/v1/bridge/external-turn", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createBridgeClient(payload: {
  name: string;
  capability_profile?: "read_only" | "read_write";
  allowed_vault_ids?: string[];
  allowed_cluster_ids?: string[];
  allow_raw_snippets?: boolean;
  allow_cluster_profile?: boolean;
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
      | "capability_profile"
      | "allowed_vault_ids"
      | "allowed_cluster_ids"
      | "allow_raw_snippets"
      | "allow_cluster_profile"
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
      | "allow_cluster_profile"
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
  const queued = await request<AppJobRecord>("/api/v1/diagnostics/bundle", {
    method: "POST",
    body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
  });
  const completed = await waitForAppJob(queued.id);
  if (completed.status !== "succeeded") {
    throw new Error(completed.last_error || "The diagnostic bundle did not finish.");
  }
  return parseJobResult<DiagnosticBundleResponse>(completed.result_json);
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

export async function listClusters(vaultId?: string, options: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const query = params.size ? `?${params.toString()}` : "";
  return request<ClusterRecord[]>(`/api/v1/clusters${query}`);
}

export async function listClustersPage(
  vaultId?: string,
  options: { limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const query = params.size ? `?${params.toString()}` : "";
  return request<CursorPage<ClusterRecord>>(`/api/v1/clusters/page${query}`);
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
  payload: Partial<Pick<ClusterRecord, "name" | "description" | "color" | "index_status" | "profile_status">>,
) {
  return request<ClusterRecord>(`/api/v1/clusters/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export type ActivityRecord = {
  id: string;
  kind: "source" | "chat" | "cluster";
  time: string;
  title: string;
  detail: string;
  href: string;
};

export async function listActivity(
  vaultId: string,
  options: {
    kind?: ActivityRecord["kind"];
    query?: string;
    limit?: number;
    offset?: number;
    cursor?: string | null;
  } = {},
) {
  const params = new URLSearchParams({ vault_id: vaultId });
  if (options.kind) params.set("kind", options.kind);
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  if (options.cursor) params.set("cursor", options.cursor);
  return request<{
    items: ActivityRecord[];
    next_cursor: string | null;
    has_more: boolean;
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/activity?${params.toString()}`);
}

export async function getMapOverview(
  vaultId: string,
  options: { limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({ vault_id: vaultId });
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  return request<MapGraphResponse>(`/api/v1/map/overview?${params.toString()}`);
}

export async function getMapNeighborhood(vaultId: string, rootId: string, limit = 80) {
  const params = new URLSearchParams({
    vault_id: vaultId,
    root_id: rootId,
    limit: String(limit),
  });
  return request<MapGraphResponse>(`/api/v1/map/neighborhood?${params.toString()}`);
}

export async function getMapItem(vaultId: string, itemId: string) {
  const params = new URLSearchParams({ vault_id: vaultId });
  return request<MapItemRecord>(
    `/api/v1/map/items/${encodeURIComponent(itemId)}?${params.toString()}`,
  );
}

export async function refreshClusterProfile(id: string) {
  return request<ClusterRecord>(
    `/api/v1/clusters/${encodeURIComponent(id)}/refresh-profile`,
    { method: "POST" },
  );
}

export async function listProjects(
  vaultId?: string,
  options: { clusterId?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.clusterId) params.set("cluster_id", options.clusterId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  const query = params.size ? `?${params.toString()}` : "";
  return request<ProjectRecord[]>(`/api/v1/projects${query}`);
}

export async function listProjectsPage(
  vaultId?: string,
  options: { clusterId?: string; limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.clusterId) params.set("cluster_id", options.clusterId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const query = params.size ? `?${params.toString()}` : "";
  return request<CursorPage<ProjectRecord>>(`/api/v1/projects/page${query}`);
}

export async function getProjectClusterMembershipSummary(vaultId: string) {
  return request<{ cluster_ids: string[] }>(
    `/api/v1/projects/cluster-membership-summary?vault_id=${encodeURIComponent(vaultId)}`,
  );
}

export async function getProject(id: string) {
  return request<ProjectRecord>(`/api/v1/projects/${encodeURIComponent(id)}`);
}

export async function getProjectGraphView(
  id: string,
  options: {
    mode: "graph" | "tree";
    query?: string;
    root?: string;
    maxDepth?: number;
    maxNodes?: number;
    direction?: "outbound" | "inbound" | "balanced";
  },
) {
  const params = new URLSearchParams({ mode: options.mode });
  if (options.query) params.set("q", options.query);
  if (options.root) params.set("root", options.root);
  if (options.maxDepth) params.set("max_depth", String(options.maxDepth));
  if (options.maxNodes) params.set("max_nodes", String(options.maxNodes));
  if (options.direction) params.set("direction", options.direction);
  return request<ProjectGraphView>(
    `/api/v1/projects/${encodeURIComponent(id)}/graph/view?${params.toString()}`,
  );
}

export async function synchronizeProject(id: string, discoveryScope?: "context" | "code") {
  return request<{
    project: ProjectRecord;
    run: ProjectIndexRunRecord;
    snapshot_id: string | null;
    job_id: string | null;
    queued: boolean;
  }>(
    `/api/v1/projects/${encodeURIComponent(id)}/sync`,
    {
      method: "POST",
      body: JSON.stringify(discoveryScope ? { discovery_scope: discoveryScope } : {}),
    },
  );
}

export async function listCliPairingChallenges() {
  return request<CliPairingChallenge[]>("/api/v1/cli-auth/pairing-challenges?status=pending&limit=20");
}

export async function approveCliPairingChallenge(id: string, scopes: string[], allowedVaultIds: string[]) {
  return request<CliClientRecord>(`/api/v1/cli-auth/pairing-challenges/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    body: JSON.stringify({ scopes, allowed_vault_ids: allowedVaultIds }),
  });
}

export async function denyCliPairingChallenge(id: string) {
  return request<{ id: string; status: string }>(
    `/api/v1/cli-auth/pairing-challenges/${encodeURIComponent(id)}/deny`,
    { method: "POST" },
  );
}

export async function listCliClients() {
  return request<CliClientRecord[]>("/api/v1/cli-auth/clients");
}

export async function revokeCliClient(id: string) {
  return request<CliClientRecord>(`/api/v1/cli-auth/clients/${encodeURIComponent(id)}/revoke`, { method: "POST" });
}

export async function rotateCliClient(id: string) {
  return request<CliClientRecord>(`/api/v1/cli-auth/clients/${encodeURIComponent(id)}/rotate`, { method: "POST" });
}

export async function listProjectRuns(id: string, limit = 50, offset = 0) {
  return request<ProjectIndexRunRecord[]>(
    `/api/v1/projects/${encodeURIComponent(id)}/runs?limit=${limit}&offset=${offset}`,
  );
}

export async function listProjectRunSummary(limit = 200, activeOnly = false) {
  const params = new URLSearchParams({
    limit: String(limit),
    active_only: String(activeOnly),
  });
  return request<{
    items: Array<{
      project: Pick<ProjectRecord, "id" | "name" | "vault_id">;
      run: ProjectIndexRunRecord;
    }>;
    limit: number;
  }>(`/api/v1/projects/project-run-summary?${params.toString()}`);
}

export async function getProjectRun(id: string, runId: string) {
  return request<ProjectIndexRunRecord>(
    `/api/v1/projects/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`,
  );
}

export async function reindexProject(id: string, layer: "structure" | "retrieval" | "interpretation" | "full") {
  return request<{ project: ProjectRecord; run?: ProjectIndexRunRecord; queued_jobs?: number; layer?: string }>(
    `/api/v1/projects/${encodeURIComponent(id)}/reindex`,
    { method: "POST", body: JSON.stringify({ layer }) },
  );
}

export async function cancelProjectRun(id: string) {
  return request<ProjectIndexRunRecord>(`/api/v1/projects/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function updateProject(
  id: string,
  payload: { name?: string; root_path?: string; discovery_scope?: "context" | "code" },
) {
  return request<ProjectRecord>(`/api/v1/projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function removeProject(id: string, confirmationName: string) {
  await request<void>(`/api/v1/projects/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmation_name: confirmationName }),
  });
}

export type ProjectLinkRecord = {
  project_id: string;
  cluster_id: string;
  role: "primary" | "linked" | string;
  cluster_name: string;
  created_at: string;
};

export type MapNodeRecord = {
  id: string;
  kind: "cluster" | "collection" | "source" | "fact";
  label: string;
  summary: string;
  color?: string;
  state?: string;
  source_type?: string;
  cluster_id?: string | null;
  source_id?: string;
  source_count?: number;
  fact_count?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  updated_at: string;
};

export type MapEdgeRecord = {
  id: string;
  source: string;
  target: string;
  kind: "contains" | "establishes" | string;
  label: string;
  direction: "outbound" | "inbound" | string;
  temporal_state: "current" | "historical" | string;
  provenance_ids: string[];
  evidence_labels?: string[];
  updated_at: string;
};

export type MapGraphResponse = {
  vault_id: string;
  root_id?: string;
  nodes: MapNodeRecord[];
  edges: MapEdgeRecord[];
  total?: number;
  cluster_total?: number;
  unclustered_count?: number;
  limit: number;
  offset?: number;
  depth?: number;
  truncated: boolean;
  relationship_policy: "authoritative_only";
};

export type MapItemRecord = MapNodeRecord & {
  path?: string | null;
  url?: string | null;
  citation_excerpt?: string;
  provenance: Array<Record<string, unknown>>;
};

export async function listProjectLinks(id: string) {
  return request<ProjectLinkRecord[]>(`/api/v1/projects/${encodeURIComponent(id)}/links`);
}

export async function linkProjectCluster(id: string, clusterId: string) {
  return request<ProjectLinkRecord>(`/api/v1/projects/${encodeURIComponent(id)}/links`, {
    method: "POST",
    body: JSON.stringify({ cluster_id: clusterId }),
  });
}

export async function unlinkProjectCluster(id: string, clusterId: string) {
  await request<void>(`/api/v1/projects/${encodeURIComponent(id)}/links/${encodeURIComponent(clusterId)}`, { method: "DELETE" });
}

export async function deleteVault(
  id: string,
  payload: { confirmation_name: string; passphrase?: string | null },
) {
  await request<void>(`/api/v1/vaults/${encodeURIComponent(id)}/delete`, {
    method: "POST",
    body: JSON.stringify(payload),
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

export async function listSources(
  vaultId?: string,
  options: {
    limit?: number;
    offset?: number;
    clusterId?: string;
    unclustered?: boolean;
    states?: Array<SourceRecord["state"]>;
    query?: string;
    sourceTypes?: string[];
    order?: "newest" | "oldest" | "alphabetical";
  } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  if (options.clusterId) params.set("cluster_id", options.clusterId);
  if (options.unclustered) params.set("unclustered", "true");
  if (options.states?.length) params.set("states", options.states.join(","));
  if (options.sourceTypes?.length) params.set("source_types", options.sourceTypes.join(","));
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.order) params.set("order", options.order);
  const query = params.size ? `?${params.toString()}` : "";
  return request<SourceRecord[]>(`/api/v1/sources${query}`);
}

export async function listSourcesPage(
  vaultId?: string,
  options: {
    limit?: number;
    cursor?: string | null;
    clusterId?: string;
    unclustered?: boolean;
    states?: Array<SourceRecord["state"]>;
    query?: string;
    sourceTypes?: string[];
  } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.clusterId) params.set("cluster_id", options.clusterId);
  if (options.unclustered) params.set("unclustered", "true");
  if (options.states?.length) params.set("states", options.states.join(","));
  if (options.sourceTypes?.length) params.set("source_types", options.sourceTypes.join(","));
  if (options.query?.trim()) params.set("q", options.query.trim());
  const query = params.size ? `?${params.toString()}` : "";
  return request<CursorPage<SourceRecord>>(`/api/v1/sources/page${query}`);
}

export async function getLatestSourcesByCluster(vaultId: string) {
  return request<{
    items: Array<{ cluster_id: string; state: SourceRecord["state"]; updated_at: string }>;
  }>(`/api/v1/sources/latest-by-cluster?vault_id=${encodeURIComponent(vaultId)}`);
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

export async function startSourceImportJob(payload: {
  vault_id: string;
  cluster_id?: string | null;
  paths: string[];
  truncated_at?: number | null;
}) {
  return request<AppJobRecord>("/api/v1/sources/import-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getActiveSourceImportJob(vaultId?: string) {
  const query = vaultId ? `?vault_id=${encodeURIComponent(vaultId)}` : "";
  return request<AppJobRecord | null>(`/api/v1/sources/import-jobs/active${query}`);
}

export async function pauseSourceImportJob(jobId: string) {
  return request<AppJobRecord>(
    `/api/v1/sources/import-jobs/${encodeURIComponent(jobId)}/pause`,
    { method: "POST" },
  );
}

export async function resumeSourceImportJob(jobId: string) {
  return request<AppJobRecord>(
    `/api/v1/sources/import-jobs/${encodeURIComponent(jobId)}/resume`,
    { method: "POST" },
  );
}

export async function stopSourceImportJob(jobId: string) {
  return request<AppJobRecord>(
    `/api/v1/sources/import-jobs/${encodeURIComponent(jobId)}/stop`,
    { method: "POST" },
  );
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

export async function listSourcePages(sourceId: string, options: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<SourcePageRecord[]>(
    `/api/v1/sources/${encodeURIComponent(sourceId)}/pages${suffix}`,
  );
}

export async function listClusterMergeArtifacts(clusterId: string) {
  return request<{ cluster_id: string; items: ClusterMergeArtifact[] }>(
    `/api/v1/clusters/${encodeURIComponent(clusterId)}/merge-artifacts`,
  );
}

export async function rollbackClusterMerge(artifactId: string) {
  return request<ClusterRecord>(
    `/api/v1/clusters/merge-artifacts/${encodeURIComponent(artifactId)}/rollback`,
    { method: "POST" },
  );
}

export async function deleteCluster(clusterId: string) {
  await request<void>(`/api/v1/clusters/${encodeURIComponent(clusterId)}`, { method: "DELETE" });
}

export async function countSources(
  vaultId?: string,
  clusterId?: string,
  options: {
    unclustered?: boolean;
    states?: Array<SourceRecord["state"]>;
    query?: string;
    sourceTypes?: string[];
  } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (clusterId) params.set("cluster_id", clusterId);
  if (options.unclustered) params.set("unclustered", "true");
  if (options.states?.length) params.set("states", options.states.join(","));
  if (options.sourceTypes?.length) params.set("source_types", options.sourceTypes.join(","));
  if (options.query?.trim()) params.set("q", options.query.trim());
  const query = params.size ? `?${params.toString()}` : "";
  return request<{ total: number }>(`/api/v1/sources/count${query}`);
}

export type SourceClusterCountRecord = {
  cluster_id: string | null;
  state: SourceRecord["state"];
  total: number;
};

export async function sourceCountsByCluster(vaultId: string) {
  return request<{ items: SourceClusterCountRecord[] }>(
    `/api/v1/sources/counts-by-cluster?vault_id=${encodeURIComponent(vaultId)}`,
  );
}

export async function getSourceStats(sourceId: string) {
  return request<SourceStatsRecord>(`/api/v1/sources/${encodeURIComponent(sourceId)}/stats`);
}

export async function reindexSource(sourceId: string) {
  return request<ReindexQueueResult>(`/api/v1/sources/${encodeURIComponent(sourceId)}/reindex`, {
    method: "POST",
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
  return request<ReindexQueueResult>(
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
  complete_analysis?: boolean;
}) {
  return request<ChatContextResponse>("/api/v1/chat/context", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export class ChatStreamInterruptedError extends Error {
  constructor() {
    super("The local service closed the answer before confirming it was saved.");
    this.name = "ChatStreamInterruptedError";
  }
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
    complete_analysis?: boolean;
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
  const response = await fetch(`${backendUrl}${apiPath("/api/v1/chat/context/stream")}`, {
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
  let sawDone = false;
  while (true) {
    const { value, done } = await readStreamChunk(reader, 90_000);
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const eventBlock of events) {
      const event = parseSseEvent(eventBlock);
      if (!event) continue;
      if (event.event === "meta")
        handlers.onMeta?.(
          event.data as Pick<
            ChatContextResponse,
            | "clusters_used"
            | "citations"
            | "coverage_ledger"
            | "attachments_stored"
            | "intent"
            | "runtime_state"
            | "warnings"
          >,
        );
      if (event.event === "token" && typeof event.data.text === "string")
        handlers.onToken(event.data.text);
      if (event.event === "error") {
        const message =
          typeof event.data.message === "string"
            ? event.data.message
            : "Vault could not finish this answer.";
        const detail = typeof event.data.detail === "string" ? ` ${event.data.detail}` : "";
        throw new Error(`${message}${detail}`.trim());
      }
      if (event.event === "done") {
        sawDone = true;
        handlers.onDone?.(event.data);
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const event = parseSseEvent(buffer.trim());
    if (event?.event === "done") {
      sawDone = true;
      handlers.onDone?.(event.data);
    }
  }
  if (!sawDone) {
    throw new ChatStreamInterruptedError();
  }
}

async function readStreamChunk(
  reader: ReadableStreamDefaultReader<Uint8Array<ArrayBufferLike>>,
  timeoutMs: number,
) {
  let timeoutId: number | undefined;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        timeoutId = window.setTimeout(
          () => {
            void reader.cancel("Chat routing timed out");
            reject(
              new Error(
                "Vault received no routing update for 90 seconds. The request was stopped; retry it or test the chat model in Settings.",
              ),
            );
          },
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

function parseSseEvent(block: string): { event: string; data: Record<string, unknown> } | null {
  const lines = block.replace(/^\uFEFF/, "").split(/\r?\n/);
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));
  const dataLine = dataLines.map((line) => line.slice(5).trimStart()).join("\n");
  if (!eventLine || !dataLine) return null;
  try {
    return {
      event: eventLine.slice(6).trim(),
      data: JSON.parse(dataLine),
    };
  } catch {
    return null;
  }
}

export async function listChatSessions(
  vaultId?: string,
  options: { saved?: boolean; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.saved !== undefined) params.set("saved", String(options.saved));
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const query = params.size ? `?${params.toString()}` : "";
  return request<ChatSessionRecord[]>(`/api/v1/chat/sessions${query}`);
}

export async function listChatSessionsPage(
  vaultId?: string,
  options: { saved?: boolean; limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.saved !== undefined) params.set("saved", String(options.saved));
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const query = params.size ? `?${params.toString()}` : "";
  return request<CursorPage<ChatSessionRecord>>(`/api/v1/chat/sessions/page${query}`);
}

export async function createChatSession(payload: {
  vault_id: string;
  title?: string | null;
  scope_cluster_id?: string | null;
  scope_project_id?: string | null;
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
  payload: Partial<Pick<ChatSessionRecord, "title" | "scope_cluster_id" | "scope_project_id" | "saved">>,
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

export async function listJobsPage(
  options: { status?: string[]; limit?: number; cursor?: string | null } = {},
) {
  const params = new URLSearchParams();
  if (options.status?.length) params.set("status", options.status.join(","));
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<CursorPage<AppJobRecord>>(`/api/v1/jobs${suffix}`);
}

export async function runJobsOnce() {
  return request<JobQueueStatus>("/api/v1/jobs/run-once", { method: "POST" });
}

export async function authorizeVaultDeletion(
  id: string,
  payload: { confirmation_name: string; passphrase?: string | null },
) {
  return request<{ authorized: boolean; vault_id: string }>(
    `/api/v1/vaults/${encodeURIComponent(id)}/delete/authorize`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getSource(sourceId: string) {
  return request<SourceRecord>(`/api/v1/sources/${encodeURIComponent(sourceId)}`);
}

export async function getSources(sourceIds: string[]) {
  if (sourceIds.length === 0) return [];
  return request<SourceRecord[]>("/api/v1/sources/batch", {
    method: "POST",
    body: JSON.stringify({ source_ids: sourceIds.slice(0, 100) }),
  });
}

export async function getTemporalFactStatus(vaultId: string) {
  const params = new URLSearchParams({ vault_id: vaultId });
  return request<TemporalFactDiagnostics>(`/api/v1/jobs/temporal-facts/status?${params.toString()}`);
}

export async function backfillTemporalFacts(vaultId: string, batchSize = 50) {
  return request<AppJobRecord>("/api/v1/jobs/temporal-facts/backfill", {
    method: "POST",
    body: JSON.stringify({ vault_id: vaultId, batch_size: batchSize }),
  });
}

export async function listTemporalFacts(vaultId: string, limit = 12) {
  const params = new URLSearchParams({ vault_id: vaultId, limit: String(limit) });
  return request<TemporalFactRecord[]>(`/api/v1/memory/facts?${params.toString()}`);
}

export async function correctTemporalFact(factId: string, vaultId: string, objectText: string, note = "") {
  return request<TemporalFactRecord>(`/api/v1/memory/facts/${encodeURIComponent(factId)}/correct`, {
    method: "POST",
    body: JSON.stringify({ vault_id: vaultId, object_text: objectText, note }),
  });
}

export async function retractTemporalFact(factId: string, vaultId: string, note = "") {
  return request<TemporalFactRecord>(`/api/v1/memory/facts/${encodeURIComponent(factId)}/retract`, {
    method: "POST",
    body: JSON.stringify({ vault_id: vaultId, note }),
  });
}

export async function getRetrievalPackingDiagnostics(vaultId: string) {
  const params = new URLSearchParams({ vault_id: vaultId });
  return request<RetrievalPackingDiagnostics>(`/api/v1/memory/retrieval-efficiency?${params.toString()}`);
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
  refresh?: boolean;
}) {
  if (payload?.refresh) {
    const queued = await request<AppJobRecord>("/api/v1/models/discover/jobs", {
      method: "POST",
      body: JSON.stringify({
        max_results: payload.max_results ?? 32,
        include_rejected: Boolean(payload.include_rejected),
        idempotency_key: crypto.randomUUID(),
      }),
    });
    const completed = await waitForAppJob(queued.id);
    if (completed.status !== "succeeded") {
      throw new Error(completed.last_error || "The model scan did not finish.");
    }
    return parseJobResult<InstalledModelDiscoveryRecord>(completed.result_json);
  }
  const query = new URLSearchParams();
  if (payload?.max_results) query.set("max_results", String(payload.max_results));
  if (payload?.include_rejected) query.set("include_rejected", "true");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<InstalledModelDiscoveryRecord>(`/api/v1/models/discover${suffix}`);
}

export async function getJob(jobId: string) {
  return request<AppJobRecord>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
}

export async function approveModelDiscoveryRoot(path: string) {
  return request<{ path: string; approved: boolean }>("/api/v1/models/discovery-roots", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function getModelCompatibilityReport(payload: { path: string; name?: string | null }) {
  return request<ModelCompatibilityRecord>("/api/v1/models/compatibility/report", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importLocalModel(payload: { path: string; name?: string | null }) {
  const queued = await request<AppJobRecord>("/api/v1/models/import/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const completed = await waitForAppJob(queued.id);
  if (completed.status !== "succeeded") {
    throw new Error(completed.last_error || "The model import did not finish.");
  }
  const detail = parseJobDetail(completed.status_detail);
  const models = await listLocalModels();
  const imported = models.find((model) => model.id === detail.model_id);
  if (!imported) {
    throw new Error("The model was copied but Vault could not refresh it. Restart Vault and scan again.");
  }
  return imported;
}

async function waitForAppJob(jobId: string): Promise<AppJobRecord> {
  const terminal = new Set(["succeeded", "failed", "cancelled", "manual_review"]);
  while (true) {
    const job = await getJob(jobId);
    if (terminal.has(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
}

function parseJobDetail(value?: string | null): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function parseJobResult<T>(value?: string | null): T {
  if (!value) throw new Error("Vault finished the job without a result.");
  try {
    return JSON.parse(value) as T;
  } catch {
    throw new Error("Vault returned an unreadable job result.");
  }
}

export async function activateLocalModel(modelId: string, role: "chat" = "chat") {
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
    signal: AbortSignal.timeout(120_000),
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

export async function listIntegrationImports(
  vaultId?: string,
  options: { limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const query = params.size ? `?${params.toString()}` : "";
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
  const queued = await request<AppJobRecord>(
    `/api/v1/integrations/imports/${encodeURIComponent(importId)}/refresh/jobs${query}`,
    { method: "POST" },
  );
  const completed = await waitForAppJob(queued.id);
  if (completed.status !== "succeeded") {
    throw new Error(completed.last_error || "The folder refresh did not finish.");
  }
  return parseJobResult<LocalFolderScanResponse>(completed.result_json);
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

export async function listExtensionClients(options: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams();
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<ExtensionClientRecord[]>(`/api/v1/extension/clients${suffix}`);
}

export async function createExtensionClient(payload: { name: string }) {
  return request<ExtensionClientCreateResponse>("/api/v1/extension/clients", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startExtensionPairing(payload: {
  name: string;
  allowed_vault_ids?: string[];
  ttl_seconds?: number;
}) {
  return request<ExtensionPairingRecord>("/api/v1/extension/pairing/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function approveExtensionPairing(pairingId: string) {
  return request<ExtensionClientCreateResponse>(`/api/v1/extension/pairing/${encodeURIComponent(pairingId)}/approve`, {
    method: "POST",
  });
}

export async function listExtensionPairings(options: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams();
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<ExtensionPairingRecord[]>(`/api/v1/extension/pairing${suffix}`);
}

export async function getExtensionStatus(token?: string) {
  return request<ExtensionStatusResponse>("/api/v1/extension/status", {
    headers: token ? { "x-cml-extension-token": token } : undefined,
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

export async function listExtensionCaptures(
  vaultId?: string,
  options: { limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (vaultId) params.set("vault_id", vaultId);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<ExtensionCaptureRecord[]>(`/api/v1/extension/captures${suffix}`);
}

export async function listExtensionPermissionAudit(limit = 20, offset = 0) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  return request<ExtensionPermissionAuditRecord[]>(`/api/v1/extension/permission-audit?${params.toString()}`);
}

export async function startModelDownload(modelId: string, payload?: { target_dir?: string | null }) {
  return request<ModelDownloadState>(`/api/v1/models/${encodeURIComponent(modelId)}/download`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export async function cancelModelDownload(modelId: string) {
  return request<ModelDownloadState>(
    `/api/v1/models/${encodeURIComponent(modelId)}/download/cancel`,
    { method: "POST" },
  );
}

type BackendRequestInit = RequestInit & {
  timeoutMs?: number;
};

async function request<T>(path: string, init?: BackendRequestInit): Promise<T> {
  const backendUrl = await getBackendUrl();
  const token = await getBackendToken();
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("x-cml-api-token", token);
  let response: Response;
  const { timeoutMs = 12_000, ...fetchInit } = init ?? {};
  const retrySafe = !fetchInit.method || fetchInit.method.toUpperCase() === "GET";
  try {
    response = await fetch(`${backendUrl}${apiPath(path)}`, {
      ...fetchInit,
      headers,
      signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (
      error instanceof DOMException &&
      (error.name === "AbortError" || error.name === "TimeoutError")
    ) {
      throw new Error(
        retrySafe
          ? `Vault did not finish this request within ${formatTimeout(timeoutMs)}. Try again.`
          : `Vault did not confirm this action within ${formatTimeout(timeoutMs)}. Check its status before retrying.`,
      );
    }
    throw new Error("Vault's local service is unavailable. Open Health to reconnect.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      detail = await response.text().catch(() => "");
    }
    throw new Error(userFacingError(detail, response.status));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function formatTimeout(timeoutMs: number) {
  if (timeoutMs >= 60_000 && timeoutMs % 60_000 === 0) {
    return `${timeoutMs / 60_000} minutes`;
  }
  return `${Math.max(1, Math.round(timeoutMs / 1000))} seconds`;
}

export async function resetVaultPassphrase(payload: {
  vault_id: string;
  recovery_key: string;
  new_passphrase: string;
}) {
  return request<UnlockStatusRead>("/api/v1/system/unlock/recovery/reset", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function userFacingError(detail: string, status?: number) {
  const text = String(detail || "").trim();
  if (text === "invalid_vault_secret") {
    return "Incorrect passphrase. Try again.";
  }
  if (!text) {
    if (status === 401 || status === 403) return "Vault needs permission before it can do that.";
    if (status === 404) return "That item is no longer available.";
    if (status && status >= 500) return "Vault could not complete that action. Try again.";
    return "Vault could not complete that action.";
  }
  if (/failed to fetch|networkerror|load failed/i.test(text)) {
    return "Vault's local service is unavailable. Open Health to reconnect.";
  }
  return text
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\.$/, "") + ".";
}

function apiPath(path: string) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (normalized === API_PREFIX || normalized.startsWith(`${API_PREFIX}/`)) {
    return normalized;
  }
  if (normalized === DEFAULT_API_PREFIX || normalized.startsWith(`${DEFAULT_API_PREFIX}/`)) {
    return `${API_PREFIX}${normalized.slice(DEFAULT_API_PREFIX.length)}`;
  }
  return `${API_PREFIX}${normalized}`;
}

function normalizeApiPrefix(value?: string) {
  const raw = String(value || DEFAULT_API_PREFIX).trim();
  const prefixed = raw.startsWith("/") ? raw : `/${raw}`;
  return prefixed.replace(/\/+$/, "") || DEFAULT_API_PREFIX;
}
