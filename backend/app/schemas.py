from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class VaultCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1)


class VaultUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    path: str | None = Field(default=None, min_length=1)


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
    expert_status: str | None = None


class ClusterMergeRequest(BaseModel):
    target_cluster_id: str


class ClusterRead(BaseModel):
    id: str
    vault_id: str
    name: str
    description: str
    color: str
    expert_status: str
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


class ClusterExpertJobRead(BaseModel):
    id: str
    cluster_id: str
    vault_id: str
    action: str
    status: str
    detail: str
    created_at: str
    updated_at: str


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


class SourcePathCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    path: str = Field(min_length=1)


class SourceTextCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1)


class SourceUrlCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    url: str = Field(min_length=1, max_length=2048)


class SourceUpdate(BaseModel):
    cluster_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    state: str | None = None
    raw_text: str | None = None
    extracted_text: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    cover_image_url: str | None = None


class SourceRead(BaseModel):
    id: str
    vault_id: str
    cluster_id: str | None
    title: str
    source_type: str
    state: str
    original_path: str | None
    url: str | None
    checksum: str | None = None
    raw_text: str
    extracted_text: str
    summary: str
    tags: list[str]
    cover_image_url: str | None
    deleted_at: str | None = None
    created_at: str
    updated_at: str


class SemanticSearchRequest(BaseModel):
    vault_id: str
    query: str = Field(min_length=1)
    cluster_id: str | None = None
    limit: int = Field(default=8, ge=1, le=30)


class SemanticSearchResult(BaseModel):
    source_id: str
    source_title: str
    source_type: str
    cluster_id: str | None
    chunk_id: str
    chunk_index: int
    snippet: str
    score: float


class SemanticSearchResponse(BaseModel):
    query: str
    results: list[SemanticSearchResult]


class BridgeStatus(BaseModel):
    enabled: bool
    mcp: str
    http_api: str
    cli: str
    allowed_vault_ids: list[str] = []
    allowed_cluster_ids: list[str] = []
    allow_raw_snippets: bool = False
    allow_style_profile: bool = False
    allow_expert_calls: bool = False
    bridge_token: str = ""


class BridgeSettingsUpdate(BaseModel):
    enabled: bool | None = None
    allowed_vault_ids: list[str] | None = None
    allowed_cluster_ids: list[str] | None = None
    allow_raw_snippets: bool | None = None
    allow_style_profile: bool | None = None
    allow_expert_calls: bool | None = None
    rotate_token: bool | None = None


class BridgeContextRequest(BaseModel):
    vault_id: str | None = None
    query: str = Field(min_length=1)
    cluster_id: str | None = None
    mode: str = "context"
    client_name: str = "unknown"
    limit: int = Field(default=5, ge=1, le=12)


class BridgeContextResponse(BaseModel):
    query: str
    selected_clusters: list[ClusterRead]
    source_snippets: list[SourceRead]
    warnings: list[str]


class BridgeRequestRead(BaseModel):
    id: str
    client_name: str
    query: str
    mode: str
    created_at: str


class ChatContextRequest(BaseModel):
    vault_id: str
    prompt: str = Field(min_length=1)
    cluster_id: str | None = None
    session_id: str | None = None
    persist: bool = True
    limit: int = Field(default=6, ge=1, le=12)


class ChatCitation(BaseModel):
    source_id: str
    source_title: str
    snippet: str
    score: float


class ChatClusterUse(BaseModel):
    cluster_id: str
    cluster_name: str
    reason: str


class ChatContextResponse(BaseModel):
    session_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    prompt: str
    answer: str
    clusters_used: list[ChatClusterUse]
    citations: list[ChatCitation]
    warnings: list[str]
    memory_status: str | None = None


class ChatSessionCreate(BaseModel):
    vault_id: str
    title: str | None = Field(default=None, min_length=1, max_length=160)
    scope_cluster_id: str | None = None


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    scope_cluster_id: str | None = None
    saved: bool | None = None


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


class ChatMessageUpdate(BaseModel):
    useful: bool | None = None
    saved: bool | None = None


class ChatSessionRead(BaseModel):
    id: str
    vault_id: str
    title: str
    scope_cluster_id: str | None
    saved: bool
    memory_status: str = "idle"
    memory_updated_at: str | None = None
    created_at: str
    updated_at: str
    messages: list[ChatMessageRead] = []


class ModelDownloadState(BaseModel):
    model_id: str
    status: str
    bytes_downloaded: int | None = None
    total_bytes: int | None = None
    file_name: str | None = None
    local_path: str | None = None
    error: str | None = None


class ModelRead(BaseModel):
    id: str
    name: str
    role: str
    hf_repo: str
    quantization: str
    approximate_download_gb: float
    recommended_ram_gb: str
    notes: str
    llama_cpp_ref: str
    installed: bool = False
    local_path: str | None = None
    download: ModelDownloadState | None = None


class ModelDownloadStart(BaseModel):
    model_id: str
    status: str
    bytes_downloaded: int | None = None
    total_bytes: int | None = None
    file_name: str | None = None
    local_path: str | None = None
    error: str | None = None


class ModelRuntimeStatus(BaseModel):
    provider: str
    base_url: str
    model: str
    available: bool
    detail: str


class EmbeddingRuntimeStatus(BaseModel):
    provider: str
    model: str
    dimensions: int
    available: bool
    detail: str


class EmbeddingRuntimeConfigure(BaseModel):
    provider: str
    cache_dir: str | None = None


class AppJobRead(BaseModel):
    id: str
    job_type: str
    status: str
    payload: str
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
    status_detail: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str
    updated_at: str


class JobQueueStatus(BaseModel):
    queued: int
    blocked_by_dependency: int = 0
    running: int
    succeeded: int
    failed: int
    cancelled: int = 0
    manual_review: int = 0
    latest: list[AppJobRead]
