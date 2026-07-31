export const HOME_PREFERENCES_STORAGE_KEY = "cml.home-preferences.v1";

export function homePreferencesStorageKey(profileId?: string) {
  const normalizedProfileId = profileId?.trim();
  return normalizedProfileId
    ? `${HOME_PREFERENCES_STORAGE_KEY}.${encodeURIComponent(normalizedProfileId)}`
    : HOME_PREFERENCES_STORAGE_KEY;
}

export const HOME_SECTION_IDS = [
  "ask",
  "attention",
  "suggestedMoves",
  "continue",
  "clusters",
  "quick",
  "recentSources",
  "inbox",
  "sourceTypes",
  "timeline",
  "tasks",
  "recentChats",
] as const;

export type HomeSectionId = (typeof HOME_SECTION_IDS)[number];
export type HomePreset = "focused" | "library" | "activity";
export type HomeDensity = "comfortable" | "compact";
export type HomeView = "list" | "grid";
export type HomeTypeFilter = "all" | "documents" | "notes" | "links" | "media" | "code";
export type HomeSort = "updated" | "added" | "alphabetical" | "attention";

export type HomePreferences = {
  version: 1;
  preset: HomePreset;
  density: HomeDensity;
  view: HomeView;
  type: HomeTypeFilter;
  sort: HomeSort;
  sectionOrder: HomeSectionId[];
  hiddenSections: HomeSectionId[];
};

const PRESET_SECTIONS: Record<HomePreset, HomeSectionId[]> = {
  focused: ["ask", "quick", "attention", "suggestedMoves", "continue", "clusters"],
  library: ["recentSources", "inbox", "clusters", "sourceTypes", "quick"],
  activity: ["timeline", "tasks", "recentChats", "quick"],
};

export const DEFAULT_HOME_PREFERENCES: HomePreferences = {
  version: 1,
  preset: "focused",
  density: "comfortable",
  view: "list",
  type: "all",
  sort: "updated",
  sectionOrder: [...PRESET_SECTIONS.focused, ...HOME_SECTION_IDS.filter((id) => !PRESET_SECTIONS.focused.includes(id))],
  hiddenSections: HOME_SECTION_IDS.filter((id) => !PRESET_SECTIONS.focused.includes(id)),
};

const PRESETS = new Set<HomePreset>(["focused", "library", "activity"]);
const DENSITIES = new Set<HomeDensity>(["comfortable", "compact"]);
const VIEWS = new Set<HomeView>(["list", "grid"]);
const TYPES = new Set<HomeTypeFilter>(["all", "documents", "notes", "links", "media", "code"]);
const SORTS = new Set<HomeSort>(["updated", "added", "alphabetical", "attention"]);
const SECTION_IDS = new Set<HomeSectionId>(HOME_SECTION_IDS);

export function homePreferencesForPreset(
  current: HomePreferences,
  preset: HomePreset,
): HomePreferences {
  const visible = PRESET_SECTIONS[preset];
  return {
    ...current,
    preset,
    sectionOrder: [...visible, ...HOME_SECTION_IDS.filter((id) => !visible.includes(id))],
    hiddenSections: HOME_SECTION_IDS.filter((id) => !visible.includes(id)),
  };
}

export function moveHomeSection(
  preferences: HomePreferences,
  sectionId: HomeSectionId,
  direction: -1 | 1,
): HomePreferences {
  const currentIndex = preferences.sectionOrder.indexOf(sectionId);
  const nextIndex = currentIndex + direction;
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= preferences.sectionOrder.length) {
    return preferences;
  }
  const sectionOrder = [...preferences.sectionOrder];
  [sectionOrder[currentIndex], sectionOrder[nextIndex]] = [
    sectionOrder[nextIndex],
    sectionOrder[currentIndex],
  ];
  return { ...preferences, sectionOrder };
}

export function readHomePreferences(
  storage: Pick<Storage, "getItem"> | null = typeof window === "undefined" ? null : window.localStorage,
  profileId?: string,
): HomePreferences {
  if (!storage) return cloneDefaultPreferences();
  try {
    const raw = storage.getItem(homePreferencesStorageKey(profileId));
    return raw ? normalizeHomePreferences(JSON.parse(raw)) : cloneDefaultPreferences();
  } catch {
    return cloneDefaultPreferences();
  }
}

export function writeHomePreferences(
  preferences: HomePreferences,
  storage: Pick<Storage, "setItem"> | null = typeof window === "undefined" ? null : window.localStorage,
  profileId?: string,
) {
  if (!storage) return;
  try {
    storage.setItem(
      homePreferencesStorageKey(profileId),
      JSON.stringify(normalizeHomePreferences(preferences)),
    );
  } catch {
    // Home remains usable when profile storage is unavailable or full.
  }
}

export function normalizeHomePreferences(value: unknown): HomePreferences {
  if (!value || typeof value !== "object") return cloneDefaultPreferences();
  const candidate = value as Partial<HomePreferences>;
  const preset = PRESETS.has(candidate.preset as HomePreset)
    ? (candidate.preset as HomePreset)
    : DEFAULT_HOME_PREFERENCES.preset;
  const fallback = homePreferencesForPreset(DEFAULT_HOME_PREFERENCES, preset);
  const sectionOrder = normalizeSectionOrder(candidate.sectionOrder, fallback.sectionOrder);
  const hiddenSections = normalizeHiddenSections(candidate.hiddenSections, fallback.hiddenSections)
    .filter((id) => sectionOrder.includes(id));
  return {
    version: 1,
    preset,
    density: DENSITIES.has(candidate.density as HomeDensity)
      ? (candidate.density as HomeDensity)
      : DEFAULT_HOME_PREFERENCES.density,
    view: VIEWS.has(candidate.view as HomeView)
      ? (candidate.view as HomeView)
      : DEFAULT_HOME_PREFERENCES.view,
    type: TYPES.has(candidate.type as HomeTypeFilter)
      ? (candidate.type as HomeTypeFilter)
      : DEFAULT_HOME_PREFERENCES.type,
    sort: SORTS.has(candidate.sort as HomeSort)
      ? (candidate.sort as HomeSort)
      : DEFAULT_HOME_PREFERENCES.sort,
    sectionOrder,
    hiddenSections,
  };
}

function normalizeSectionOrder(
  value: unknown,
  fallback: readonly HomeSectionId[],
): HomeSectionId[] {
  if (!Array.isArray(value)) return [...fallback];
  const normalized: HomeSectionId[] = [];
  for (const item of value) {
    if (SECTION_IDS.has(item as HomeSectionId) && !normalized.includes(item as HomeSectionId)) {
      normalized.push(item as HomeSectionId);
    }
  }
  for (const sectionId of HOME_SECTION_IDS) {
    if (!normalized.includes(sectionId)) normalized.push(sectionId);
  }
  return normalized;
}

function normalizeHiddenSections(
  value: unknown,
  fallback: readonly HomeSectionId[],
): HomeSectionId[] {
  if (!Array.isArray(value)) return [...fallback];
  const normalized: HomeSectionId[] = [];
  for (const item of value) {
    if (SECTION_IDS.has(item as HomeSectionId) && !normalized.includes(item as HomeSectionId)) {
      normalized.push(item as HomeSectionId);
    }
  }
  return normalized;
}

function cloneDefaultPreferences(): HomePreferences {
  return {
    ...DEFAULT_HOME_PREFERENCES,
    sectionOrder: [...DEFAULT_HOME_PREFERENCES.sectionOrder],
    hiddenSections: [...DEFAULT_HOME_PREFERENCES.hiddenSections],
  };
}
