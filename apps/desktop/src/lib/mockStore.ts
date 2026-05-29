import { create } from "zustand";

export type ClusterTint =
  | "sage"
  | "sand"
  | "sky"
  | "blush"
  | "lavender"
  | "terracotta";

export type ExpertStatus =
  | "setting-up"
  | "learning"
  | "ready"
  | "needs-update"
  | "paused"
  | "issue";

export type SourceType = "file" | "link" | "note" | "image";
export type SourceState =
  | "waiting"
  | "extracting"
  | "indexed"
  | "needs-review"
  | "failed";

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
  expert: ExpertStatus;
  lastActive: string;
  summary: string;
  styleProfile: string;
}

export interface CitationRef {
  sourceId: string;
  snippet: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  clustersUsed?: { clusterId: string; reason: string }[];
  citations?: CitationRef[];
  useful?: boolean | null;
  saved?: boolean;
}

export interface Chat {
  id: string;
  title: string;
  scopeClusterId: string | null; // null = global
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
  indexingProgress: number; // 0-1
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

const seedClusters: Cluster[] = [
  {
    id: "c-design",
    name: "Design Notes",
    tint: "sage",
    description: "Visual notes, references, and design principles.",
    expert: "ready",
    lastActive: now(),
    summary:
      "A collection of design observations leaning toward calm, editorial, type-led interfaces.",
    styleProfile: "Measured, observational, references-heavy.",
  },
  {
    id: "c-research",
    name: "Research",
    tint: "sky",
    description: "Papers, articles, and saved findings.",
    expert: "learning",
    lastActive: now(),
    summary: "Mixed scientific and product research clippings.",
    styleProfile: "Concise, citation-first.",
  },
  {
    id: "c-writing",
    name: "Personal Writing",
    tint: "blush",
    description: "Drafts, essays, and journal entries.",
    expert: "ready",
    lastActive: now(),
    summary: "Long-form personal writing with a warm narrative voice.",
    styleProfile: "First-person, reflective, sentence-led.",
  },
];

const seedSources: Source[] = [
  ["Type as Voice.pdf", "file", "c-design", "indexed"],
  ["Editorial Grids — notes.md", "note", "c-design", "indexed"],
  ["nngroup.com/articles/chunking", "link", "c-design", "indexed"],
  ["Calm Tech principles.txt", "note", "c-design", "needs-review"],
  ["Attention is All You Need.pdf", "file", "c-research", "indexed"],
  ["arXiv 2310.05217.pdf", "file", "c-research", "extracting"],
  ["Anthropic — interpretability.html", "link", "c-research", "indexed"],
  ["Field notes — March.md", "note", "c-writing", "indexed"],
  ["Letter draft v3.docx", "file", "c-writing", "indexed"],
  ["Morning pages.txt", "note", "c-writing", "indexed"],
  ["screenshot-2026-05-12.png", "image", null, "waiting"],
  ["broken-link.html", "link", null, "failed"],
].map(([title, type, clusterId, state]) => ({
  id: uid(),
  title: title as string,
  type: type as SourceType,
  clusterId: clusterId as string | null,
  state: state as SourceState,
  updatedAt: now(),
  preview:
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus luctus urna sed urna ultricies ac tempor dui sagittis…",
  summary: "A short auto-generated summary of this source.",
  tags: [],
  coverImageUrl:
    type === "image"
      ? "https://images.unsplash.com/photo-1497032628192-86f99bcd76bc?auto=format&fit=crop&w=900&q=80"
      : undefined,
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
    updatedAt: now(),
    saved: true,
    messages: [
      {
        id: uid(),
        role: "user",
        content: "What style do my design notes lean toward?",
      },
      {
        id: uid(),
        role: "assistant",
        content:
          "Your design notes lean toward calm, editorial interfaces — restrained color, generous spacing, and type-led hierarchy. There's a recurring emphasis on chunking and reading rhythm.",
        clustersUsed: [
          { clusterId: "c-design", reason: "style" },
        ],
        citations: [
          { sourceId: seedSources[0].id, snippet: "Type carries voice before color does." },
          { sourceId: seedSources[1].id, snippet: "Editorial grids favor a primary column." },
        ],
        useful: true,
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
      expert: c.expert ?? "setting-up",
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
        s.id === id ? { ...s, state: "extracting", updatedAt: now() } : s,
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

export const expertLabel: Record<ExpertStatus, string> = {
  "setting-up": "Setting up",
  learning: "Learning",
  ready: "Ready",
  "needs-update": "Needs update",
  paused: "Paused",
  issue: "Issue",
};

export const sourceStateLabel: Record<SourceState, string> = {
  waiting: "Waiting",
  extracting: "Extracting",
  indexed: "Indexed",
  "needs-review": "Needs review",
  failed: "Failed",
};

export const newId = uid;

// canned streaming for chat
export async function* streamMockReply(
  prompt: string,
  cluster: Cluster | null,
): AsyncGenerator<string> {
  const opener = cluster
    ? `Drawing from ${cluster.name}: `
    : `Across your vault: `;
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
