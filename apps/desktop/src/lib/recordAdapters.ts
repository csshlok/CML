import type { Cluster, ClusterLifecycleStatus, ClusterTint, Source, SourceState, SourceType } from "@/lib/mockStore";
import type { ClusterRecord, SourceRecord } from "@/lib/backend";

export function sourceFromRecord(record: SourceRecord): Source {
  return {
    id: record.id,
    title: record.title,
    type: normalizeSourceType(record.source_type),
    clusterId: record.cluster_id,
    state: normalizeSourceState(record.state),
    updatedAt: record.updated_at,
    preview: record.extracted_text || record.raw_text,
    summary: record.summary,
    tags: record.tags ?? [],
    coverImageUrl: record.cover_image_url ?? undefined,
    vaultPath: record.original_path ?? undefined,
    localPath: record.original_path ?? undefined,
    url: record.url ?? undefined,
  };
}

export function clusterFromRecord(record: ClusterRecord): Cluster {
  return {
    id: record.id,
    name: record.name,
    tint: normalizeTint(record.color),
    description: record.description,
    lifecycle: normalizeClusterLifecycle(record.index_status, record.profile_status),
    lastActive: record.updated_at,
    summary: record.cluster_summary || record.description,
    styleProfile: record.profile_status === "ready" ? "Profile cached" : "Profile refresh pending",
  };
}

export function sourceStateText(state: SourceState) {
  const labels: Record<SourceState, string> = {
    waiting: "Waiting",
    processing: "Processing",
    indexed: "Indexed",
    failed: "Failed",
  };
  return labels[state];
}

function normalizeSourceType(value: string): SourceType {
  return value === "file" ||
    value === "link" ||
    value === "note" ||
    value === "image" ||
    value === "audio" ||
    value === "video" ||
    value === "code" ||
    value === "external_transcript" ||
    value === "external_artifact"
    ? value
    : "file";
}

function normalizeSourceState(value: string): SourceState {
  return value === "waiting" ||
    value === "processing" ||
    value === "indexed" ||
    value === "failed"
    ? value
    : "waiting";
}

export function normalizeTint(value: string): ClusterTint {
  return value === "sage" ||
    value === "sand" ||
    value === "sky" ||
    value === "blush" ||
    value === "lavender" ||
    value === "terracotta"
    ? value
    : "sage";
}

function normalizeClusterLifecycle(indexStatus: string, profileStatus: string): ClusterLifecycleStatus {
  if (indexStatus === "error" || profileStatus === "error") return "issue";
  if (indexStatus === "indexing") return "indexing";
  if (indexStatus === "empty") return "empty";
  if (profileStatus === "stale" || profileStatus === "refreshing") return "profile-stale";
  if (indexStatus === "ready") return "searchable";
  return "retrieval-only";
}
