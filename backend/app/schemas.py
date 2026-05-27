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


class SourceCreate(BaseModel):
    vault_id: str
    cluster_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    source_type: str
    original_path: str | None = None
    url: str | None = None
    raw_text: str = ""


class SourceUpdate(BaseModel):
    cluster_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    state: str | None = None
    raw_text: str | None = None
    extracted_text: str | None = None
    summary: str | None = None


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
    created_at: str
    updated_at: str


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
