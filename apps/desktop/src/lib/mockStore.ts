import { create } from "zustand";

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

export interface Chat {
  id: string;
  title: string;
  scopeClusterId: string | null;
  messages: ChatMessage[];
  updatedAt: string;
  saved?: boolean;
}

interface State {
  vaultPath: string | null;
  setupComplete: boolean;
  clusters: Cluster[];
  sources: Source[];
  chats: Chat[];
  indexingProgress: number;
  isIndexing: boolean;

  setVault: (path: string) => void;
  completeSetup: () => void;
  addCluster: (c: Partial<Cluster> & { name: string }) => Cluster;
  renameCluster: (id: string, name: string) => void;
  mergeClusters: (sourceId: string, targetId: string) => void;
  addSource: (s: Partial<Source> & { title: string; type: SourceType }) => Source;
  reindexSource: (id: string) => void;
  removeSource: (id: string) => void;
  moveSource: (id: string, clusterId: string | null) => void;
  createChat: (scopeClusterId: string | null) => Chat;
  appendMessage: (chatId: string, msg: ChatMessage) => void;
  setMessageUseful: (chatId: string, msgId: string, val: boolean) => void;
  saveChat: (chatId: string, saved: boolean) => void;
  startIndexing: () => Promise<void>;
}

const now = () => new Date().toISOString();
const uid = () => Math.random().toString(36).slice(2, 10);
const SEED_NOW = "2026-01-01T00:00:00.000Z";
const seedTime = (offsetMinutes = 0) =>
  new Date(Date.parse(SEED_NOW) + offsetMinutes * 60_000).toISOString();
const seedId = (prefix: string, index: number) => `${prefix}-${String(index).padStart(2, "0")}`;

const seedClusters: Cluster[] = [
  {
    id: "c-design",
    name: "Design Research",
    tint: "sage",
    description: "Notes, case studies, and inspiration on product design.",
    lifecycle: "searchable",
    lastActive: seedTime(1),
    summary: "A calm research space for interface principles, case studies, and visual systems.",
    styleProfile: "Measured, observational, reference-heavy.",
  },
  {
    id: "c-strategy",
    name: "Product Strategy",
    tint: "terracotta",
    description: "Roadmaps, positioning, GTM, and market insights.",
    lifecycle: "searchable",
    lastActive: seedTime(2),
    summary: "Positioning notes, decision frameworks, and product-market signals.",
    styleProfile: "Direct, decision-oriented, concise.",
  },
  {
    id: "c-health",
    name: "Health & Longevity",
    tint: "sky",
    description: "Books, papers, and personal notes on health.",
    lifecycle: "searchable",
    lastActive: seedTime(3),
    summary: "Health research, sleep notes, supplements, and longevity reading.",
    styleProfile: "Careful, evidence-first, practical.",
  },
  {
    id: "c-travel",
    name: "Travel Japan 2025",
    tint: "lavender",
    description: "Plans, places, learnings from our Japan trip.",
    lifecycle: "profile-stale",
    lastActive: seedTime(4),
    summary: "Kyoto cafes, Tokyo logistics, shrine notes, and travel planning.",
    styleProfile: "Personal, compact, itinerary-aware.",
  },
  {
    id: "c-meetings",
    name: "Meeting Notes",
    tint: "sand",
    description: "Internal syncs, decisions, and action items.",
    lifecycle: "indexing",
    lastActive: seedTime(5),
    summary: "Weekly planning, product decisions, and follow-up tasks.",
    styleProfile: "Action-oriented, crisp, chronological.",
  },
];

const seedSources: Source[] = [
  ["Aarron Walter - Designing for Emotion.pdf", "file", "c-design", "indexed"],
  ["One Thing at a Time - Productivity.pdf", "file", "c-design", "indexed"],
  ["IDEO - Field Guide to Human Centered Design.pdf", "file", "c-design", "indexed"],
  ["Editorial Grids - notes.md", "note", "c-design", "indexed"],
  ["nngroup.com/articles/chunking", "link", "c-design", "indexed"],
  ["Calm Tech principles.txt", "note", "c-design", "failed"],
  ["North Star Metric framework.md", "note", "c-strategy", "indexed"],
  ["Amplitude - Product Analytics Guide.pdf", "file", "c-strategy", "indexed"],
  ["Market positioning teardown.html", "link", "c-strategy", "indexed"],
  ["Roadmap review Q2.docx", "file", "c-strategy", "indexed"],
  ["Why We Sleep - Matthew Walker.pdf", "file", "c-health", "indexed"],
  ["Sleep is the multiplier.md", "note", "c-health", "indexed"],
  ["Longevity protocols.csv", "file", "c-health", "indexed"],
  ["Kyoto cafes list.md", "note", "c-travel", "indexed"],
  ["Japan rail planning.pdf", "file", "c-travel", "indexed"],
  ["Tokyo neighborhoods.png", "image", "c-travel", "indexed"],
  ["Q2 Planning Decisions.md", "note", "c-meetings", "indexed"],
  ["Weekly sync transcript.txt", "file", "c-meetings", "indexed"],
  ["Action items - May 27.md", "note", "c-meetings", "failed"],
  ["screenshot-2026-05-12.png", "image", null, "waiting"],
  ["voice-note-product-idea.m4a", "file", null, "waiting"],
  ["broken-link.html", "link", null, "failed"],
].map(([title, type, clusterId, state], index) => ({
  id: seedId("source", index + 1),
  title: title as string,
  type: type as SourceType,
  clusterId: clusterId as string | null,
  state: state as SourceState,
  updatedAt: seedTime(20 + index),
  preview: "A short extracted preview from this source appears here with enough context for quick triage.",
  summary: "A short auto-generated summary of this source.",
  tags: [],
  coverImageUrl: undefined,
  vaultPath: `/Sources/${title as string}`,
  localPath:
    type === "link"
      ? undefined
      : `C:\\Users\\csshl\\Documents\\CML Vault\\Sources\\${title as string}`,
  url: type === "link" ? `https://${title as string}` : undefined,
}));

const seedChats: Chat[] = [
  {
    id: "chat-welcome",
    title: "Getting started",
    scopeClusterId: null,
    updatedAt: seedTime(60),
    saved: true,
    messages: [
      {
        id: seedId("message", 1),
        role: "user",
        content: "What style do my design notes lean toward?",
      },
      {
        id: seedId("message", 2),
        role: "assistant",
        content:
          "Your design notes lean toward calm, editorial interfaces - restrained color, generous spacing, and type-led hierarchy. There's a recurring emphasis on chunking and reading rhythm.",
        clustersUsed: [{ clusterId: "c-design", reason: "style" }],
        citations: [
          { sourceId: seedSources[0].id, snippet: "Type carries voice before color does." },
          { sourceId: seedSources[3].id, snippet: "Editorial grids favor a primary column." },
        ],
        useful: true,
      },
    ],
  },
  {
    id: "chat-strategy",
    title: "North Star Metric",
    scopeClusterId: "c-strategy",
    updatedAt: seedTime(61),
    saved: true,
    messages: [
      {
        id: seedId("message", 3),
        role: "user",
        content: "Summarize the strongest product strategy notes.",
      },
    ],
  },
  {
    id: "chat-health",
    title: "Sleep protocol",
    scopeClusterId: "c-health",
    updatedAt: seedTime(62),
    saved: true,
    messages: [
      {
        id: seedId("message", 4),
        role: "user",
        content: "What are the practical sleep takeaways?",
      },
    ],
  },
];

export const useStore = create<State>((set, get) => ({
  vaultPath: null,
  setupComplete: false,
  clusters: seedClusters,
  sources: seedSources,
  chats: seedChats,
  indexingProgress: 0,
  isIndexing: false,

  setVault: (path) => set({ vaultPath: path }),
  completeSetup: () => set({ setupComplete: true }),

  addCluster: (c) => {
    const tints: ClusterTint[] = ["sage", "sand", "sky", "blush", "lavender", "terracotta"];
    const used = new Set(get().clusters.map((x) => x.tint));
    const tint = c.tint ?? tints.find((t) => !used.has(t)) ?? "sand";
    const cluster: Cluster = {
      id: "c-" + uid(),
      name: c.name,
      tint,
      description: c.description ?? "",
      lifecycle: c.lifecycle ?? "empty",
      lastActive: now(),
      summary: c.summary ?? "",
      styleProfile: c.styleProfile ?? "",
    };
    set({ clusters: [...get().clusters, cluster] });
    return cluster;
  },

  renameCluster: (id, name) =>
    set({
      clusters: get().clusters.map((c) => (c.id === id ? { ...c, name } : c)),
    }),

  mergeClusters: (sourceId, targetId) => {
    set({
      sources: get().sources.map((s) =>
        s.clusterId === sourceId ? { ...s, clusterId: targetId } : s,
      ),
      clusters: get().clusters.filter((c) => c.id !== sourceId),
    });
  },

  addSource: (s) => {
    const source: Source = {
      id: uid(),
      title: s.title,
      type: s.type,
      clusterId: s.clusterId ?? null,
      state: s.state ?? "waiting",
      updatedAt: now(),
      preview: s.preview ?? "",
      summary: s.summary ?? "",
      tags: s.tags ?? [],
    };
    set({ sources: [source, ...get().sources] });
    return source;
  },

  reindexSource: (id) =>
    set({
      sources: get().sources.map((s) =>
        s.id === id ? { ...s, state: "processing", updatedAt: now() } : s,
      ),
    }),

  removeSource: (id) =>
    set({ sources: get().sources.filter((s) => s.id !== id) }),

  moveSource: (id, clusterId) =>
    set({
      sources: get().sources.map((s) =>
        s.id === id ? { ...s, clusterId } : s,
      ),
    }),

  createChat: (scopeClusterId) => {
    const chat: Chat = {
      id: "chat-" + uid(),
      title: "New chat",
      scopeClusterId,
      messages: [],
      updatedAt: now(),
    };
    set({ chats: [chat, ...get().chats] });
    return chat;
  },

  appendMessage: (chatId, msg) =>
    set({
      chats: get().chats.map((c) =>
        c.id === chatId
          ? {
              ...c,
              messages: [...c.messages, msg],
              updatedAt: now(),
              title:
                c.messages.length === 0 && msg.role === "user"
                  ? msg.content.slice(0, 40)
                  : c.title,
            }
          : c,
      ),
    }),

  setMessageUseful: (chatId, msgId, val) =>
    set({
      chats: get().chats.map((c) =>
        c.id === chatId
          ? {
              ...c,
              messages: c.messages.map((m) =>
                m.id === msgId ? { ...m, useful: val } : m,
              ),
            }
          : c,
      ),
    }),

  saveChat: (chatId, saved) =>
    set({
      chats: get().chats.map((c) =>
        c.id === chatId ? { ...c, saved } : c,
      ),
    }),

  startIndexing: async () => {
    set({ isIndexing: true, indexingProgress: 0 });
    for (let i = 1; i <= 10; i++) {
      await new Promise((r) => setTimeout(r, 200));
      set({ indexingProgress: i / 10 });
    }
    set({ isIndexing: false });
  },
}));

export const tintVar = (t: ClusterTint) => `var(--cluster-${t})`;

export const clusterLifecycleLabel: Record<ClusterLifecycleStatus, string> = {
  searchable: "Searchable",
  "retrieval-only": "Retrieval-only",
  empty: "Empty cluster",
  queued: "Queued",
  indexing: "Indexing",
  "profile-stale": "Profile stale",
  paused: "Paused",
  issue: "Issue",
};

export const sourceStateLabel: Record<SourceState, string> = {
  waiting: "Waiting",
  processing: "Processing",
  indexed: "Indexed",
  failed: "Failed",
};

export const newId = uid;

export async function* streamMockReply(
  prompt: string,
  cluster: Cluster | null,
): AsyncGenerator<string> {
  const opener = cluster
    ? `Drawing from ${cluster.name}: `
    : "Across your vault: ";
  const body =
    prompt.length < 30
      ? "here's a short answer based on what I've indexed so far. The most relevant notes are surfaced as citations below."
      : "this prompt pulls from a few notes in your vault. I've tried to stay close to your voice and keep the answer grounded in cited material.";
  const text = opener + body;
  const words = text.split(" ");
  for (const w of words) {
    await new Promise((r) => setTimeout(r, 30));
    yield w + " ";
  }
}
