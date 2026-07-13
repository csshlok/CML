export type ClusterTint =
  | "sage"
  | "sand"
  | "sky"
  | "blush"
  | "lavender"
  | "terracotta";

export type ClusterLifecycleStatus =
  | "searchable"
  | "retrieval-only"
  | "empty"
  | "queued"
  | "indexing"
  | "profile-stale"
  | "paused"
  | "issue";

export type SourceType =
  | "file"
  | "link"
  | "note"
  | "image"
  | "audio"
  | "video"
  | "code"
  | "external_transcript"
  | "external_artifact";

export type SourceState = "waiting" | "processing" | "indexed" | "failed";

export interface Source {
  id: string;
  title: string;
  type: SourceType;
  clusterId: string | null;
  state: SourceState;
  updatedAt: string;
  preview: string;
  summary: string;
  tags: string[];
  coverImageUrl?: string;
  vaultPath?: string;
  localPath?: string;
  url?: string;
}

export interface Cluster {
  id: string;
  name: string;
  tint: ClusterTint;
  description: string;
  lifecycle: ClusterLifecycleStatus;
  lastActive: string;
  summary: string;
  styleProfile: string;
}

export interface CitationRef {
  sourceId: string;
  snippet: string;
  pageNumber?: number | null;
  state?: string;
  title?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "retriable";
  content: string;
  prompt?: string;
  clustersUsed?: { clusterId: string; reason: string }[];
  citations?: CitationRef[];
  useful?: boolean | null;
  saved?: boolean;
  warnings?: string[];
  intent?: string;
  runtimeState?: string | null;
  coverageLedger?: Record<string, unknown> | null;
}

export const clusterLifecycleLabel: Record<ClusterLifecycleStatus, string> = {
  searchable: "Searchable",
  "retrieval-only": "Retrieval-only",
  empty: "Empty cluster",
  queued: "Queued",
  indexing: "Indexing",
  "profile-stale": "Profile needs an update",
  paused: "Paused",
  issue: "Needs attention",
};

export const sourceStateLabel: Record<SourceState, string> = {
  waiting: "Waiting",
  processing: "Processing",
  indexed: "Indexed",
  failed: "Needs attention",
};
