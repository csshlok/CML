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


class SourceCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    source_type: str
    original_path: str | None = None
    url: str | None = None
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
    raw_text: str
    extracted_text: str
    summary: str
    tags: list[str]
    cover_image_url: str | None
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


class BridgeContextRequest(BaseModel):
    query: str = Field(min_length=1)
    cluster_id: str | None = None
    mode: str = "context"
    client_name: str = "unknown"


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
    created_at: str


class ChatSessionRead(BaseModel):
    id: str
    vault_id: str
    title: str
    scope_cluster_id: str | None
    saved: bool
    created_at: str
    updated_at: str
    messages: list[ChatMessageRead] = []
