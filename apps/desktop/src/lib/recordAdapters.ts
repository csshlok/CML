import type { Cluster, ClusterTint, ExpertStatus, Source, SourceState, SourceType } from "@/lib/mockStore";
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
    expert: normalizeExpertStatus(record.expert_status),
    lastActive: record.updated_at,
    summary: record.description,
    styleProfile: "Style profile pending",
  };
}

export function sourceStateText(state: SourceState) {
  const labels: Record<SourceState, string> = {
    waiting: "Waiting",
    extracting: "Extracting",
    indexed: "Indexed",
    "needs-review": "Needs review",
    failed: "Failed",
  };
  return labels[state];
}

function normalizeSourceType(value: string): SourceType {
  return value === "file" || value === "link" || value === "note" || value === "image" ? value : "file";
}

function normalizeSourceState(value: string): SourceState {
  return value === "waiting" ||
    value === "extracting" ||
    value === "indexed" ||
    value === "needs-review" ||
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

function normalizeExpertStatus(value: string): ExpertStatus {
  return value === "setting-up" ||
    value === "learning" ||
    value === "ready" ||
    value === "needs-update" ||
    value === "paused" ||
    value === "issue"
    ? value
    : "setting-up";
}
