from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

MIN_VAULT_PASSPHRASE_LENGTH = 12
SOURCE_STATE_VALUES = {"waiting", "processing", "indexed", "failed"}


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class HealthResponse(BaseModel):
    status: str
    service: str


class VaultCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1)


class VaultUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    path: str | None = Field(default=None, min_length=1)


class VaultDeleteRequest(BaseModel):
    confirmation_name: str = Field(min_length=1, max_length=120)
    passphrase: str | None = None


class VaultRead(BaseModel):
    id: str
    name: str
    path: str
    created_at: str
    updated_at: str


class ClusterCreate(BaseModel):
    vault_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    color: str = "sage"


class ClusterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    color: str | None = None
    index_status: str | None = None
    profile_status: str | None = None


class ClusterMergeRequest(BaseModel):
    target_cluster_id: str


class ClusterMembershipRepairRequest(BaseModel):
    vault_id: str
    batch_size: int = Field(default=100, ge=1, le=500)


class ClusterRead(BaseModel):
    id: str
    vault_id: str
    name: str
    description: str
    color: str
    index_status: str = "empty"
    profile_status: str = "missing"
    cluster_summary: str = ""
    cluster_glossary: str = "[]"
    profile_updated_at: str | None = None
    profile_source_hash: str = ""
    indexed_source_count: int = 0
    created_at: str
    updated_at: str


class ClusterSuggestionRead(BaseModel):
    source_id: str
    source_title: str
    current_cluster_id: str | None
    suggested_cluster_id: str
    suggested_cluster_name: str
    confidence: float
    reason: str


class ClusterSuggestionDecision(BaseModel):
    source_id: str
    suggested_cluster_id: str
    action: Literal["accepted", "dismissed"]


class ProjectCreate(BaseModel):
    vault_id: str
    root_path: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    discovery_scope: Literal["context", "code"] = "context"
    auto_sync_enabled: bool | None = None
    sync_mode: Literal["automatic", "notify", "manual"] | None = None
    sync: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    root_path: str | None = Field(default=None, min_length=1)
    discovery_scope: Literal["context", "code"] | None = None
    auto_sync_enabled: bool | None = None
    sync_mode: Literal["automatic", "notify", "manual"] | None = None


class ProjectSnapshotRead(BaseModel):
    id: str
    project_id: str
    discovery_scope: Literal["context", "code"] = "context"
    source_manifest_hash: str
    git_commit: str | None = None
    branch: str | None = None
    dirty_working_tree: bool = False
    extractor_version: str
    eligible_count: int = 0
    ignored_count: int = 0
    generated_count: int = 0
    parsed_count: int = 0
    failed_count: int = 0
    structure_status: str
    retrieval_status: str
    interpretation_status: str
    activated_at: str | None = None
    manifest_activated_at: str | None = None
    structure_activated_at: str | None = None
    retrieval_activated_at: str | None = None
    created_at: str


class ProjectIndexRunRead(BaseModel):
    id: str
    project_id: str
    snapshot_id: str | None = None
    job_id: str | None = None
    trigger_source: str
    status: str
    phase: str
    eligible_total: int = 0
    completed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    phase_completed_count: int = 0
    phase_total_count: int = 0
    cancellation_requested: bool = False
    cancellation_requested_at: str | None = None
    heartbeat_at: str | None = None
    queued_at: str | None = None
    activation_outcome: str = ""
    failure_category: str = ""
    detail_json: str = "{}"
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    updated_at: str


class ProjectRead(BaseModel):
    id: str
    vault_id: str
    name: str
    root_path: str
    root_fingerprint: str
    discovery_scope: Literal["context", "code"] = "context"
    primary_cluster_id: str
    repository_kind: str
    git_remote_fingerprint: str | None = None
    default_branch: str | None = None
    indexed_commit: str | None = None
    working_tree_dirty: bool = False
    changed_file_count: int = 0
    auto_sync_enabled: bool = True
    sync_mode: Literal["automatic", "notify", "manual"] = "automatic"
    change_fingerprint: str = ""
    last_change_checked_at: str | None = None
    status: str
    structure_status: str
    retrieval_status: str
    interpretation_status: str
    active_snapshot_id: str | None = None
    active_manifest_snapshot_id: str | None = None
    active_structure_snapshot_id: str | None = None
    active_retrieval_snapshot_id: str | None = None
    candidate_snapshot_id: str | None = None
    active_run_id: str | None = None
    active_snapshot: ProjectSnapshotRead | None = None
    brief: str
    languages: dict[str, int]
    workspace_count: int = 0
    entrypoints: list[str]
    source_count: int = 0
    created_at: str
    updated_at: str


class ProjectSyncResponse(BaseModel):
    project: ProjectRead
    run: ProjectIndexRunRead
    snapshot_id: str | None = None
    job_id: str | None = None
    queued: bool = False


class ProjectSyncRequest(BaseModel):
    discovery_scope: Literal["context", "code"] | None = None


class ProjectTargetedSyncRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class ProjectReindexRequest(BaseModel):
    layer: str = "full"


class ProjectLinkCreate(BaseModel):
    cluster_id: str


class ProjectLinkRead(BaseModel):
    project_id: str
    cluster_id: str
    cluster_name: str
    role: str
    created_at: str


class ProjectRemoveRequest(BaseModel):
    confirmation_name: str = Field(min_length=1, max_length=120)


class SourceCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    source_type: str
    original_path: str | None = None
    url: str | None = None
    checksum: str | None = None
    raw_text: str = ""
    summary: str | None = None
    tags: list[str] | None = None
    cover_image_url: str | None = None

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SourcePathCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    path: str = Field(min_length=1)

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SourceImportJobRequest(BaseModel):
    vault_id: str = Field(min_length=1)
    cluster_id: str | None = None
    paths: list[str] = Field(min_length=1, max_length=10_000)
    truncated_at: int | None = Field(default=None, ge=1, le=10_000)
    folder_roots: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("paths")
    @classmethod
    def normalize_paths(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("File paths cannot be blank")
        if any(len(value) > 32_767 for value in normalized):
            raise ValueError("A file path is too long")
        return normalized

    @field_validator("folder_roots")
    @classmethod
    def normalize_folder_roots(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


class SourceTextCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1)

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SourceUrlCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SourceUpdate(BaseModel):
    cluster_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    state: str | None = None
    raw_text: str | None = None
    extracted_text: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    cover_image_url: str | None = None

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized == "extracting":
            normalized = "processing"
        if normalized == "needs-review":
            normalized = "failed"
        if normalized not in SOURCE_STATE_VALUES:
            raise ValueError(f"Unsupported source state: {value}")
        return normalized


class SourceRead(BaseModel):
    id: str
    vault_id: str
    cluster_id: str | None
    title: str
    source_type: str
    state: str
    original_path: str | None
    import_root_path: str | None = None
    import_relative_path: str | None = None
    url: str | None
    checksum: str | None = None
    provenance: str = "local_import"
    trust_tier: str = "trusted_local"
    security_labels: str = "[]"
    parser_security_json: str = "{}"
    raw_text: str
    extracted_text: str
    summary: str
    tags: list[str]
    metadata_quality: str = "fallback"
    semantic_metadata_version: int = 0
    semantic_metadata_updated_at: str | None = None
    ingestion_stage: str = "ready"
    ingestion_generation: int = 1
    ingestion_error_code: str = ""
    ingestion_status_detail: str = ""
    ingestion_updated_at: str | None = None
    cover_image_url: str | None
    deleted_at: str | None = None
    created_at: str
    updated_at: str


class SourceBatchRequest(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("source_ids")
    @classmethod
    def normalize_source_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not normalized:
            raise ValueError("At least one source ID is required")
        return normalized


class SourcePageRead(BaseModel):
    id: str
    source_id: str
    vault_id: str
    page_number: int
    raw_text: str
    extraction_version: str
    content_hash: str
    created_at: str
    updated_at: str


class SemanticSearchRequest(BaseModel):
    vault_id: str
    query: str = Field(min_length=1)
    cluster_id: str | None = None
    unclustered_only: bool = False
    limit: int = Field(default=8, ge=1, le=30)


class SemanticSearchResult(BaseModel):
    source_id: str
    source_title: str
    source_type: str
    cluster_id: str | None
    chunk_id: str
    page_id: str | None = None
    page_number: int | None = None
    chunk_index: int
    snippet: str
    score: float
    raw_score: float | None = None
    provenance: str = "local_import"
    trust_tier: str = "trusted_local"
    security_labels: str = "[]"
    low_trust: bool = False


class SemanticSearchResponse(BaseModel):
    query: str
    backend: str | None = None
    eligible_count: int | None = None
    results: list[SemanticSearchResult]


class BridgeStatus(BaseModel):
    schema_version: int = 1
    enabled: bool
    mcp: str
    http_api: str
    cli: str
    allowed_vault_ids: list[str] = []
    allowed_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    bridge_token: str = ""
    approval_requests_pending: int = 0
    last_refreshed_at: str | None = None


class BridgeSettingsUpdate(BaseModel):
    enabled: bool | None = None
    allowed_vault_ids: list[str] | None = None
    allowed_cluster_ids: list[str] | None = None
    allow_raw_snippets: bool | None = None
    allow_cluster_profile: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    rotate_token: bool | None = None


class BridgeContextRequest(BaseModel):
    vault_id: str | None = None
    query: str = Field(min_length=1)
    cluster_id: str | None = None
    unclustered_only: bool = False
    project_id: str | None = None
    mode: str = "context"
    client_name: str = "unknown"
    limit: int = Field(default=5, ge=1, le=12)
    context_request_id: str | None = None
    include_graph: bool = False
    graph_mode: str = Field(default="graph", pattern="^(graph|tree)$")
    graph_max_nodes: int = Field(default=120, ge=10, le=300)


class BridgeContextResponse(BaseModel):
    context_request_id: str
    query: str
    selected_clusters: list[ClusterRead]
    source_snippets: list[SourceRead]
    citations: list[dict] = []
    warnings: list[str]
    packet_text: str | None = None
    expansion_handles: list[str] = []
    memory_items: list[dict] = []
    working_memory: dict = {}
    cluster_profile: dict = {}
    retrieval_authority: bool = True
    token_estimate: dict = {}
    bundle_status: dict = {}
    graph_context: dict | None = None


class BridgeContextExpandRequest(BaseModel):
    vault_id: str | None = None
    cluster_id: str | None = None
    handle: str = Field(min_length=1)
    mode: str = "full"
    client_name: str = "unknown"


class BridgeContextExpandResponse(BaseModel):
    handle: str
    source_id: str | None = None
    chunk_id: str | None = None
    page_id: str | None = None
    cluster_id: str | None = None
    title: str = ""
    source_type: str = ""
    trust_tier: str = ""
    text: str = ""
    warnings: list[str] = []


class BridgeExternalTurnCapture(BaseModel):
    vault_id: str | None = None
    cluster_id: str | None = None
    client_name: str = "unknown"
    user_prompt: str = Field(min_length=1)
    model_response: str = Field(min_length=1)
    context_request_id: str | None = None
    model_name: str | None = None
    metadata: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


class BridgeArtifactCapture(BaseModel):
    vault_id: str | None = None
    cluster_id: str | None = None
    client_name: str = "unknown"
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)
    artifact_type: str = "generated_text"
    metadata: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


class BridgeCaptureResponse(BaseModel):
    source_id: str
    vault_id: str
    cluster_id: str | None = None
    source_type: str
    indexed: bool
    quality_state: str = "unknown"
    approved: bool = False
    review_required: bool = False
    trust_tier: str = ""
    reasons: list[str] = []
    security_labels: list[str] = []
    warnings: list[str] = []


class BridgeWritebackReviewRead(BaseModel):
    source_id: str
    vault_id: str
    context_request_id: str | None = None
    quality_state: str
    approved: bool = False
    reasons: list[str] = []
    title: str = ""
    trust_tier: str = ""
    security_labels: list[str] = []
    updated_at: str


class BridgeWritebackReviewDecision(BaseModel):
    approved: bool
    expected_updated_at: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


class BridgeCaptureListItem(BaseModel):
    source_id: str
    vault_id: str
    cluster_id: str | None = None
    title: str
    source_type: str
    quality_state: str = "unknown"
    approved: bool = False
    trust_tier: str = ""
    security_labels: list[str] = []
    created_at: str


class BridgeRequestRead(BaseModel):
    id: str
    client_id: str | None = None
    client_name: str
    query: str
    mode: str
    decision: str = "allowed"
    source_count: int = 0
    response_bytes: int = 0
    created_at: str


class BridgeTokenRotationRead(BaseModel):
    id: str
    rotated_at: str
    reason: str


class BridgeClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    capability_profile: Literal["read_only", "read_write"] = "read_write"
    allowed_vault_ids: list[str] = []
    allowed_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )


class BridgeClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    capability_profile: Literal["read_only", "read_write"] | None = None
    allowed_vault_ids: list[str] | None = None
    allowed_cluster_ids: list[str] | None = None
    allow_raw_snippets: bool | None = None
    allow_cluster_profile: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    rotate_token: bool | None = None


class BridgeClientCreateResponse(BaseModel):
    id: str
    name: str
    token: str
    enabled: bool
    capability_profile: Literal["read_only", "read_write"] = "read_write"
    approval_vault_id: str | None = None
    allowed_vault_ids: list[str] = []
    allowed_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    approval_request_id: str | None = None
    approved_at: str | None = None
    revoked_at: str | None = None
    last_request_at: str | None = None
    request_count_total: int = 0
    response_bytes_total: int = 0
    executable_path_claim: str = ""
    observed_executable_path: str = ""
    publisher_name: str = ""
    signature_status: str = "not_provided"
    signature_detail: str = ""
    verified_identity: bool = False
    verified_identity_label: str = ""
    created_at: str
    updated_at: str


class BridgeClientRead(BaseModel):
    id: str
    name: str
    enabled: bool
    capability_profile: Literal["read_only", "read_write"] = "read_write"
    approval_vault_id: str | None = None
    allowed_vault_ids: list[str] = []
    allowed_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    approval_request_id: str | None = None
    approved_at: str | None = None
    revoked_at: str | None = None
    last_request_at: str | None = None
    request_count_total: int = 0
    response_bytes_total: int = 0
    executable_path_claim: str = ""
    observed_executable_path: str = ""
    publisher_name: str = ""
    signature_status: str = "not_provided"
    signature_detail: str = ""
    verified_identity: bool = False
    verified_identity_label: str = ""
    created_at: str
    updated_at: str


class BridgeApprovalRequestCreate(BaseModel):
    claimed_name: str = Field(min_length=1, max_length=120)
    capability_profile: Literal["read_only", "read_write"] = "read_only"
    requested_vault_ids: list[str] = []
    requested_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    executable_path: str | None = Field(default=None, max_length=2048)


class BridgeApprovalRequestCreateResponse(BaseModel):
    request_id: str
    status: str
    expires_at: str
    poll_code: str
    detail: str = ""


class BridgeApprovalRequestPollResponse(BaseModel):
    request_id: str
    status: str
    expires_at: str
    client_id: str | None = None
    token: str | None = None
    token_available: bool = False
    detail: str = ""


class BridgeApprovalRequestRead(BaseModel):
    id: str
    vault_id: str
    status: str
    claimed_name: str
    capability_profile: Literal["read_only", "read_write"] = "read_only"
    requested_vault_ids: list[str] = []
    requested_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_cluster_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    executable_path_claim: str = ""
    observed_executable_path: str = ""
    publisher_name: str = ""
    signature_status: str = "not_provided"
    signature_detail: str = ""
    verified_identity: bool = False
    verified_identity_label: str = ""
    client_id: str | None = None
    requested_at: str
    expires_at: str
    decided_at: str | None = None
    delivered_at: str | None = None
    updated_at: str
    detail: str = ""


class BridgeApprovalDecision(BaseModel):
    capability_profile: Literal["read_only", "read_write"] | None = None
    allowed_vault_ids: list[str] | None = None
    allowed_cluster_ids: list[str] | None = None
    allow_raw_snippets: bool | None = None
    allow_cluster_profile: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("allow_cluster_profile", "allow_style_profile"),
    )
    detail: str | None = Field(default=None, max_length=300)


class BridgeAuditEventRead(BaseModel):
    id: str
    vault_id: str | None = None
    client_id: str | None = None
    approval_request_id: str | None = None
    event_type: str
    detail: str = ""
    created_at: str
    updated_at: str


class DiagnosticBundleResponse(BaseModel):
    bundle_path: str
    bundle_format_version: int
    bundle_generated_at: str
    app_version: str
    backend_version: str
    schema_version: int
    included_files: list[str]


class ChatAttachmentInput(BaseModel):
    path: str = Field(min_length=1)
    cluster_id: str | None = None

    @field_validator("cluster_id", mode="before")
    @classmethod
    def normalize_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChatAttachmentStored(BaseModel):
    source_id: str
    title: str
    cluster_id: str | None = None


class ChatContextRequest(BaseModel):
    vault_id: str
    prompt: str = Field(min_length=1)
    cluster_id: str | None = None
    unclustered_only: bool = False
    project_id: str | None = None
    session_id: str | None = None
    persist: bool = True
    limit: int = Field(default=6, ge=1, le=12)
    expanded_analysis: bool = False
    complete_analysis: bool = False
    attachments: list[ChatAttachmentInput] = Field(default_factory=list)
    request_id: str | None = Field(default=None, min_length=8, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")
    retry_generation_id: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("cluster_id", "project_id", "session_id", "request_id", "retry_generation_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChatCitation(BaseModel):
    source_id: str
    source_title: str
    snippet: str
    score: float
    chunk_id: str | None = None
    page_id: str | None = None
    page_number: int | None = None
    state: str = "current"
    provenance: str = "local_import"
    trust_tier: str = "trusted_local"
    security_labels: str = "[]"
    low_trust: bool = False
    relative_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    project_snapshot_id: str | None = None
    indexed_commit: str | None = None


class ChatClusterUse(BaseModel):
    cluster_id: str
    cluster_name: str
    reason: str


class ChatCoverageLedger(BaseModel):
    sources_considered: int = 0
    sources_analyzed: int = 0
    sources_low_relevance: int = 0
    relevance_threshold: float = 0.0
    scope: str = "vault"
    trust_gate_mode: str = "normal"
    trusted_evidence_count: int = 0
    low_trust_evidence_count: int = 0
    trust_gate_latency_ms: float = 0.0
    token_budget: int = 0
    prompt_tokens_estimate: int = 0
    evidence_tokens_estimate: int = 0
    citations_selected: int = 0
    citations_trimmed: int = 0
    budget_diagnostics: dict = {}
    budget_applied: bool = False
    partial_failure_mode: str = "none"
    retrieval_authority: bool = True
    token_estimate: dict = {}
    bundle_status: dict = {}
    typed_evidence: dict = {}
    answer_mode: str = "direct"
    context_sources: list[str] = []


class ChatContextResponse(BaseModel):
    session_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    prompt: str
    answer: str
    clusters_used: list[ChatClusterUse]
    citations: list[ChatCitation]
    coverage_ledger: ChatCoverageLedger | None = None
    attachments_stored: list[ChatAttachmentStored] = []
    intent: str = "general_chat"
    runtime_state: str | None = None
    warnings: list[str]
    memory_status: str | None = None
    cluster_profile: dict = {}


class ChatSessionCreate(BaseModel):
    vault_id: str
    title: str | None = Field(default=None, min_length=1, max_length=160)
    scope_cluster_id: str | None = None
    scope_project_id: str | None = None
    scope_unclustered: bool = False

    @field_validator("scope_cluster_id", "scope_project_id", mode="before")
    @classmethod
    def normalize_scope_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    scope_cluster_id: str | None = None
    scope_project_id: str | None = None
    scope_unclustered: bool | None = None
    saved: bool | None = None

    @field_validator("scope_cluster_id", "scope_project_id", mode="before")
    @classmethod
    def normalize_scope_cluster_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChatMessageRead(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    clusters_used: list[ChatClusterUse]
    citations: list[ChatCitation]
    warnings: list[str]
    useful: bool | None = None
    saved: bool = False
    created_at: str
    generation_id: str | None = None
    reply_to_message_id: str | None = None
    generation_state: str | None = None
    attachments: list[str] = Field(default_factory=list)


class ChatMessageUpdate(BaseModel):
    useful: bool | None = None
    saved: bool | None = None


class ChatSessionRead(BaseModel):
    id: str
    vault_id: str
    title: str
    scope_cluster_id: str | None
    scope_project_id: str | None = None
    scope_unclustered: bool = False
    saved: bool
    memory_status: str = "idle"
    memory_updated_at: str | None = None
    active_generation: bool = False
    created_at: str
    updated_at: str
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ModelDownloadState(BaseModel):
    model_id: str
    status: str
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    total_bytes: int | None = None
    progress_percent: float | None = None
    download_speed_bps: int | None = None
    eta_seconds: int | None = None
    file_name: str | None = None
    local_path: str | None = None
    error: str | None = None
    sha256: str | None = None
    integrity_status: str | None = None
    started_at: str | None = None
    updated_at: str | None = None


class ModelIntegrityRead(BaseModel):
    status: str
    sha256: str | None = None
    expected_sha256: str | None = None
    detail: str | None = None


class ModelCompatibilityRead(BaseModel):
    status: str
    accepted: bool
    chat_role_accepted: bool = False
    accepted_roles: list[str] = []
    family: str
    family_name: str
    model_type: str
    architecture: str
    registered_family: str = ""
    local_path: str
    runtime_dependencies: dict
    hardware: dict
    reasons: list[str]
    selection_detail: str = ""
    replacement_recommendation: dict = {}
    detail: str


class ModelRead(BaseModel):
    id: str
    name: str
    role: str
    hf_repo: str
    family: str = ""
    quantization: str
    approximate_download_gb: float
    recommended_ram_gb: str
    notes: str
    llama_cpp_ref: str
    installed: bool = False
    local_path: str | None = None
    download: ModelDownloadState | None = None
    integrity: ModelIntegrityRead | None = None
    active: bool = False
    active_chat: bool = False
    compatibility: ModelCompatibilityRead | None = None
    source_kind: str = "default_choice"


class ModelCompatibilityRequest(BaseModel):
    path: str
    name: str | None = None


class ModelScanRootRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ModelDiscoveryJobRequest(BaseModel):
    max_results: int = Field(default=32, ge=1, le=200)
    include_rejected: bool = False
    scan_all_drives: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=240)


class DiagnosticBundleJobRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=240)


class ModelActivateRequest(BaseModel):
    role: str = "chat"


class ModelDownloadRequest(BaseModel):
    target_dir: str | None = None


class ModelRecommendationRead(BaseModel):
    hardware: dict
    recommended_model_id: str
    recommended_chat_model_id: str = ""
    chat_fit_type: str = ""
    chat_estimated_tok_per_sec: float | None = None
    evidence_level: str = "none"
    confidence: str = "low"
    warnings: list[str] = []
    reasons: list[str] = []
    fallback_low_spec: dict = {}
    fallback_fastest: dict = {}
    active_chat_setup: dict = {}
    chat_recommendation: dict = {}
    models: list[ModelRead]
    detected_compatible_models: list[dict] = []
    detected_compatible_model_count: int = 0
    rejected_candidates: list[dict] = []
    detail: str
    operator_summary: str = ""
    scoring_breakdown: dict = {}
    candidate_table: list[dict] = []
    benchmark_evidence_audit: list[dict] = []
    catalog_version: str = ""
    benchmark_bundle_version: str = ""
    catalog_models: list[dict] = []


class ModelRecommendationMeasurementWrite(BaseModel):
    model_id: str | None = None
    score: float | None = None
    estimated_tok_per_sec: float | None = None
    startup_seconds: float | None = None
    runtime_success: bool | None = None
    training_success: bool | None = None
    measured_at: str


class ModelRecommendationMeasurementRunRequest(BaseModel):
    model_id: str | None = None
    prompt: str = "Reply with a short sentence confirming the runtime is working."
    max_new_tokens: int | None = None


class ModelRecommendationHardwarePreviewRequest(BaseModel):
    hardware: dict = {}
    refresh: bool = False


class DiscoveredInstalledModelRead(BaseModel):
    id: str
    name: str
    family: str = ""
    family_name: str = ""
    local_path: str
    source_root: str
    source_kind: str = "discovered_checkpoint"
    already_imported: bool = False
    compatibility: ModelCompatibilityRead
    detail: str = ""


class InstalledModelDiscoveryRead(BaseModel):
    models: list[DiscoveredInstalledModelRead]
    compatible_model_count: int
    scanned_root_count: int
    scanned_roots: list[str]
    missing_roots: list[str]
    truncated: bool = False
    scan_duration_ms: float


class ModelDownloadStart(BaseModel):
    model_id: str
    status: str
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    total_bytes: int | None = None
    progress_percent: float | None = None
    download_speed_bps: int | None = None
    eta_seconds: int | None = None
    file_name: str | None = None
    local_path: str | None = None
    error: str | None = None
    sha256: str | None = None
    integrity_status: str | None = None
    started_at: str | None = None
    updated_at: str | None = None


class ModelRuntimeStatus(BaseModel):
    provider: str
    base_url: str
    model: str
    available: bool
    state: str = "missing"
    in_flight: int = 0
    detail: str
    pid: int | None = None
    error: str | None = None
    managed: bool = False


class EmbeddingRuntimeStatus(BaseModel):
    provider: str
    model: str
    dimensions: int
    available: bool
    detail: str
    setup_required: bool = False
    cache_dir: str | None = None


class EmbeddingRuntimeConfigure(BaseModel):
    provider: str
    cache_dir: str | None = None
    model: str | None = None


class EmbeddingModelDownloadRequest(BaseModel):
    cache_dir: str | None = None
    model: str | None = None


class EmbeddingModelDownloadState(BaseModel):
    model_id: str
    status: str
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    total_bytes: int | None = None
    progress_percent: float | None = None
    download_speed_bps: int | None = None
    eta_seconds: int | None = None
    file_name: str | None = None
    local_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    updated_at: str | None = None


class HardwareStatusRead(BaseModel):
    os: str
    machine: str
    processor: str
    cpu_count: int
    total_memory_bytes: int | None = None
    avx2: bool | None = None
    hardware_tier: str
    training_supported: bool
    detail: str


class AppProfileRead(BaseModel):
    display_name: str = ""
    updated_at: str | None = None


class AppProfileUpdate(BaseModel):
    display_name: str = Field(default="", max_length=120)


class LocalFolderScanRequest(BaseModel):
    path: str
    vault_id: str | None = None
    max_files: int = Field(default=500, ge=1, le=5000)


class LocalFolderScanResponse(BaseModel):
    import_id: str | None = None
    reconciliation_run_id: str | None = None
    path: str
    integration_type: str
    supported_files: list[str]
    supported_count: int
    skipped_count: int
    truncated: bool
    imported_count: int = 0
    updated_count: int = 0
    moved_count: int = 0
    unchanged_count: int = 0
    tombstoned_count: int = 0
    failed_count: int = 0
    failures: list[dict] = []


class IntegrationImportRead(BaseModel):
    id: str
    vault_id: str | None = None
    integration_type: str
    root_path: str
    status: str
    supported_count: int
    skipped_count: int
    truncated: bool
    imported_count: int = 0
    updated_count: int = 0
    moved_count: int = 0
    unchanged_count: int = 0
    tombstoned_count: int = 0
    failed_count: int = 0
    last_failures: list[dict] = []
    last_reconciliation_run_id: str | None = None
    last_reconciliation_status: str | None = None
    last_reconciliation_trigger_source: str | None = None
    last_reconciliation_finished_at: str | None = None
    last_reconciliation_detail_count: int = 0
    last_reconciliation_retryable_failed_count: int = 0
    last_scan_at: str
    last_import_at: str | None = None
    watch_enabled: bool = False
    watch_interval_seconds: int = 0
    next_watch_at: str | None = None
    created_at: str
    updated_at: str


class IntegrationImportUpdate(BaseModel):
    watch_enabled: bool | None = None
    watch_interval_seconds: int | None = Field(default=None, ge=60, le=86400)


class ReconciliationRunRead(BaseModel):
    id: str
    vault_id: str
    import_id: str
    trigger_source: str
    root_path: str
    status: str
    import_files: bool = True
    tombstone_missing: bool = False
    imported_count: int = 0
    updated_count: int = 0
    moved_count: int = 0
    unchanged_count: int = 0
    tombstoned_count: int = 0
    failed_count: int = 0
    retryable_failed_count: int = 0
    detail_count: int = 0
    started_at: str
    finished_at: str | None = None
    created_at: str
    updated_at: str


class ReconciliationItemRead(BaseModel):
    id: str
    run_id: str
    vault_id: str
    import_id: str
    item_reference: str
    action: str
    result: str
    error: str = ""
    retryable: bool = False
    detail: dict = {}
    created_at: str
    updated_at: str


class ReconciliationItemPageRead(BaseModel):
    run_id: str
    items: list[ReconciliationItemRead]
    total: int
    limit: int
    offset: int


class ReconciliationItemRetryResponse(BaseModel):
    retried_item_id: str
    new_run: ReconciliationRunRead
    new_item: ReconciliationItemRead | None = None


class ExtensionClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_vault_ids: list[str] = []


class ExtensionClientUpdate(BaseModel):
    enabled: bool | None = None
    allowed_vault_ids: list[str] | None = None


class ExtensionClientCreateResponse(BaseModel):
    id: str
    name: str
    token: str
    enabled: bool = True
    allowed_vault_ids: list[str] = []
    created_at: str


class ExtensionClientRead(BaseModel):
    id: str
    name: str
    enabled: bool
    allowed_vault_ids: list[str] = []
    created_at: str
    updated_at: str


class ExtensionDesktopSetupCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    name: str = Field(default="Chrome/Brave capture", min_length=1, max_length=120)
    backend_url: str = "http://127.0.0.1:7343"
    browser: str = "chrome"


class ExtensionDesktopSetupRead(BaseModel):
    backend_url: str
    api_prefix: str = "/api/v1"
    extension_token: str
    default_vault_id: str
    default_cluster_id: str = ""
    vault_path: str
    client_name: str
    browser: str
    install_targets: list[str] = []
    primary_actions: list[str] = []
    optional_actions: list[str] = []
    save_root: str = ""


class ExtensionStatusResponse(BaseModel):
    ok: bool
    client_id: str | None = None
    detail: str


class ExtensionCaptureRequest(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    capture_type: str = "page"
    title: str = Field(min_length=1, max_length=240)
    url: str = ""
    text: str = Field(min_length=1)


class ExtensionCaptureResponse(BaseModel):
    capture_id: str
    source_id: str
    status: str


class ExtensionUploadCaptureRequest(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    capture_type: str = "file"
    title: str = Field(min_length=1, max_length=240)
    url: str = ""
    file_name: str = Field(min_length=1, max_length=240)
    mime_type: str = ""
    content_base64: str = Field(min_length=1)


class ExtensionCaptureRead(BaseModel):
    id: str
    client_id: str | None = None
    vault_id: str
    source_id: str | None = None
    capture_type: str
    title: str
    url: str
    status: str
    created_at: str


class ExtensionPairingStartRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_vault_ids: list[str] = []
    ttl_seconds: int = Field(default=600, ge=60, le=1800)


class ExtensionPairingRead(BaseModel):
    id: str
    pairing_code: str
    status: str
    requested_name: str
    allowed_vault_ids: list[str] = []
    created_at: str
    expires_at: str
    completed_at: str | None = None


class ExtensionPermissionAuditRead(BaseModel):
    id: str
    client_id: str | None = None
    event_type: str
    vault_id: str | None = None
    detail: str
    created_at: str


class VaultLockAuditRead(BaseModel):
    id: str
    event_type: str
    pid: int | None = None
    owner_pid: int | None = None
    lock_path: str
    detail: str
    user_choice: str
    created_at: str


class UnlockStatusRead(BaseModel):
    state: str
    vault_id: str | None = None
    unlock_mode: str = "strict"
    pin_enabled: bool = False
    message: str = ""
    verification_error: str = ""
    updated_at: str = ""
    ready: bool = False
    secured_vault_count: int = 0
    secured_vault_ids: list[str] = []
    has_vendor_recovery: bool = False


class UnlockInitializeRequest(BaseModel):
    vault_id: str
    passphrase: str = Field(min_length=MIN_VAULT_PASSPHRASE_LENGTH)
    unlock_mode: str = "strict"


class UnlockInitializeResponse(UnlockStatusRead):
    recovery_key: str


class UnlockPassphraseRequest(BaseModel):
    vault_id: str
    passphrase: str = Field(min_length=1)


class UnlockRecoveryRequest(BaseModel):
    vault_id: str
    recovery_key: str = Field(min_length=1)


class UnlockRecoveryResetRequest(BaseModel):
    vault_id: str
    recovery_key: str = Field(min_length=1)
    new_passphrase: str = Field(min_length=MIN_VAULT_PASSPHRASE_LENGTH)


class UnlockSettingsUpdate(BaseModel):
    vault_id: str
    unlock_mode: str | None = None
    pin_enabled: bool | None = None


class SensitiveActionVerifyRequest(BaseModel):
    vault_id: str
    passphrase: str = Field(min_length=1)


class SensitiveActionVerifyRead(BaseModel):
    ok: bool
    vault_id: str
    verified_at: str


class DiskPreflightRequest(BaseModel):
    path: str
    required_bytes: int | None = None


class DiskPreflightResponse(BaseModel):
    path: str
    probe_path: str
    required_bytes: int
    available_bytes: int
    ok: bool
    message: str


class StartupStatusRead(BaseModel):
    phase: str
    raw_phase: str | None = None
    status: str
    message: str = ""
    error_code: str = ""
    backend_mode: str = ""
    data_dir: str = ""
    database_path: str = ""
    updated_at: str = ""


class OCRRuntimeStatusRead(BaseModel):
    available: bool
    pdf_ocr_available: bool
    image_ocr_available: bool
    pdf_ocr_engine: str | None = None
    full_pdf_ocr_available: bool = False
    fallback_pdf_ocr_available: bool = False
    tesseract_path: str | None = None
    ocrmypdf_command: str | None = None
    tessdata_path: str | None = None
    ghostscript_path: str | None = None
    qpdf_path: str | None = None
    missing: list[str]
    detail: str


class VaultSafetyRead(BaseModel):
    database_path: str
    integrity_ok: bool
    integrity_result: list[str]
    wal_checkpoint: str
    backup_path: str | None = None
    created_at: str


class AppJobRead(BaseModel):
    id: str
    job_type: str
    status: str
    payload: str
    result_json: str = "{}"
    dedupe_key: str | None = None
    priority: str | None = None
    idempotency_class: str | None = None
    restart_policy: str | None = None
    dependency_failure_policy: str | None = None
    write_scope: str | None = None
    scope_id: str | None = None
    concurrency_group: str | None = None
    resource_cost: str | None = None
    can_run_during_synthesis: int | None = None
    user_visible: int | None = None
    user_initiated: int | None = None
    cancellable: int | None = None
    preemptable: int | None = None
    timeout_seconds: int | None = None
    soft_timeout_seconds: int | None = None
    timeout_action: str | None = None
    depends_on_job_id: str | None = None
    attempts: int
    max_attempts: int
    last_error: str
    error_code: str = ""
    diagnostic_id: str = ""
    status_detail: str | None = None
    cancellation_requested: int = 0
    cancellation_requested_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    elapsed_seconds: int | None = None
    estimated_remaining_seconds: int | None = None
    created_at: str
    updated_at: str
    import_outcome: str | None = None


class TemporalFactBackfillRequest(BaseModel):
    vault_id: str = Field(min_length=1)
    batch_size: int = Field(default=50, ge=1, le=200)


class TemporalFactDiagnosticsRead(BaseModel):
    vault_id: str
    extractor_version: str = ""
    status_counts: dict[str, int] = Field(default_factory=dict)
    speaker_counts: dict[str, int] = Field(default_factory=dict)
    assertion_kind_counts: dict[str, int] = Field(default_factory=dict)
    session_count: int = 0
    indexed_session_count: int = 0
    latest_observed_at: str | None = None
    latest_processed_at: str | None = None


class TemporalFactRead(BaseModel):
    id: str
    vault_id: str
    cluster_id: str | None = None
    subject_key: str
    predicate_key: str
    object_text: str
    object_type: str
    assertion_kind: str
    modality: str
    speaker_role: str
    source_type: str
    source_id: str
    session_id: str | None = None
    citation_excerpt: str = ""
    observed_at: str
    valid_from: str
    valid_until: str | None = None
    supersession_key: str = ""
    supersedes_fact_id: str | None = None
    superseded_by_fact_id: str | None = None
    status: str
    confidence: float
    origin_fingerprint: str
    metadata: dict = Field(default_factory=dict)
    created_at: str


class TemporalFactCorrectionRequest(BaseModel):
    vault_id: str = Field(min_length=1)
    object_text: str = Field(min_length=1, max_length=1000)
    note: str = Field(default="", max_length=500)
    valid_from: str | None = None


class TemporalFactRetractionRequest(BaseModel):
    vault_id: str = Field(min_length=1)
    note: str = Field(default="", max_length=500)


class RetrievalPackingDiagnosticsRead(BaseModel):
    vault_id: str
    query_count: int = 0
    candidate_citation_count: int = 0
    selected_citation_count: int = 0
    raw_context_tokens: int = 0
    final_context_tokens: int = 0
    context_tokens_avoided: int = 0
    context_reduction_percent: float = 0.0
    raw_evidence_tokens: int = 0
    selected_evidence_tokens: int = 0
    average_final_context_tokens: int = 0
    latest_query_at: str | None = None


class JobQueueStatus(BaseModel):
    queued: int
    paused: int = 0
    blocked_by_dependency: int = 0
    blocked_setup_required: int = 0
    blocked_local_model: int = 0
    deferred: int = 0
    running: int
    succeeded: int
    partial_success: int = 0
    failed: int
    cancelled: int = 0
    manual_review: int = 0
    running_jobs: list[AppJobRead] = []
    latest: list[AppJobRead]
