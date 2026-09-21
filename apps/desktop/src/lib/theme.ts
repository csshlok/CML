// Renderer-safe theme runtime shared by every route, Settings, and the root
// shell. This module is the single source of truth for the theme vocabulary,
// resolution rules, DOM application, and cross-surface synchronization —
// no other module should invent a second theme store.
//
// Appearance is device-level UI state (THEME-01..03): it must resolve
// without an unlocked vault, a live backend, or a mounted React tree, and it
// must survive SSR, dev-web, packaged file loading, storage denial, and
// corrupted persisted state by falling back to System rather than throwing.

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export interface ThemeSnapshot {
  preference: ThemePreference;
  resolved: ResolvedTheme;
}

export const THEME_PREFERENCES: readonly ThemePreference[] = ["system", "light", "dark"];

const THEME_STORAGE_KEY = "cml.theme-preference.v1";

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "light") return "light";
  if (preference === "dark") return "dark";
  return systemPrefersDark ? "dark" : "light";
}

export function getSystemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

function safeLocalStorage(): Pick<Storage, "getItem" | "setItem"> | null {
  if (typeof window === "undefined") return null;
  try {
    // Accessing window.localStorage can throw under storage-denial policies
    // (private browsing, disabled storage, packaged file:// restrictions).
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Web/dev fallback only. In Electron, main-process state (via theme.cjs) is
 * authoritative; this is used when `window.cmlDesktop` is unavailable.
 */
export function readStoredThemePreference(
  storage: Pick<Storage, "getItem"> | null = safeLocalStorage(),
): ThemePreference {
  if (!storage) return "system";
  try {
    const raw = storage.getItem(THEME_STORAGE_KEY);
    if (!raw) return "system";
    const parsed = JSON.parse(raw) as { preference?: unknown } | null;
    return isThemePreference(parsed?.preference) ? parsed!.preference : "system";
  } catch {
    return "system";
  }
}

export function writeStoredThemePreference(
  preference: ThemePreference,
  storage: Pick<Storage, "setItem"> | null = safeLocalStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ version: 1, preference }));
  } catch {
    // Web/dev preference persistence is best-effort; theme still resolves via System.
  }
}

export function applyThemeAttributes(resolved: ResolvedTheme, target: Document | undefined = typeof document === "undefined" ? undefined : document): void {
  if (!target) return;
  const root = target.documentElement;
  root.setAttribute("data-theme", resolved);
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
}

/**
 * Self-contained, dependency-free bootstrap script embedded in the document
 * head for non-Electron (dev-web / SSR) rendering. Electron's preload already
 * applies the resolved theme synchronously before this would ever run; this
 * script checks for that and is a no-op when it already ran. Keep this
 * logic in sync with resolveTheme/readStoredThemePreference above — it
 * cannot import them because it must run as a standalone inline script.
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var d=document.documentElement;if(d.getAttribute('data-theme'))return;var pref='system';try{var raw=window.localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(raw){var parsed=JSON.parse(raw);if(parsed&&(parsed.preference==='light'||parsed.preference==='dark'||parsed.preference==='system')){pref=parsed.preference;}}}catch(e){}var systemDark=false;try{systemDark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;}catch(e){}var resolved=pref==='light'?'light':pref==='dark'?'dark':(systemDark?'dark':'light');d.setAttribute('data-theme',resolved);d.classList.toggle('dark',resolved==='dark');d.style.colorScheme=resolved;}catch(e){}})();`;

function isValidThemeSnapshot(value: unknown): value is ThemeSnapshot {
  const candidate = value as Partial<ThemeSnapshot> | null | undefined;
  return (
    isThemePreference(candidate?.preference) &&
    (candidate?.resolved === "light" || candidate?.resolved === "dark")
  );
}

/**
 * Synchronous best-known snapshot for initial render (e.g. a useState
 * initializer). In Electron this reads the value preload already resolved
 * via a synchronous IPC call before any script ran, so it reflects the real
 * main-process preference immediately rather than guessing from
 * localStorage/matchMedia and waiting for an async correction.
 */
export function getInitialThemeSnapshot(): ThemeSnapshot {
  const desktopInitial = typeof window !== "undefined" ? window.cmlDesktop?.initialTheme : undefined;
  if (isValidThemeSnapshot(desktopInitial)) return desktopInitial;
  const preference = readStoredThemePreference();
  return { preference, resolved: resolveTheme(preference, getSystemPrefersDark()) };
}

let currentSnapshot: ThemeSnapshot | null = null;
let initialized = false;
let systemMediaCleanup: (() => void) | null = null;
let desktopUnsubscribe: (() => void) | null = null;
const listeners = new Set<(snapshot: ThemeSnapshot) => void>();

function notify(snapshot: ThemeSnapshot): void {
  currentSnapshot = snapshot;
  applyThemeAttributes(snapshot.resolved);
  for (const listener of listeners) listener(snapshot);
}

/**
 * Idempotent: safe to call from every route/component that needs the theme
 * runtime live (e.g. the root shell and Settings). Resolves the Electron
 * bridge when present, otherwise falls back to localStorage + matchMedia.
 */
export async function initializeTheme(): Promise<ThemeSnapshot> {
  if (initialized) {
    return currentSnapshot ?? getInitialThemeSnapshot();
  }
  initialized = true;

  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  if (desktop?.getTheme) {
    // Apply the pre-paint snapshot immediately: it is already correct (same
    // authoritative source the async call below re-confirms), so the JS-side
    // store never has a window where it reflects a Light/localStorage guess
    // while waiting on the IPC round trip.
    notify(getInitialThemeSnapshot());
    try {
      const snapshot = await desktop.getTheme();
      if (isValidThemeSnapshot(snapshot)) notify(snapshot);
    } catch {
      // The pre-paint snapshot above is already applied; a rejected getTheme()
      // call leaves the last-known-good theme in place instead of resetting.
    }
    desktopUnsubscribe = desktop.onThemeChanged?.((snapshot) => {
      if (isValidThemeSnapshot(snapshot)) notify(snapshot);
    }) ?? null;
    return currentSnapshot!;
  }

  notify(getInitialThemeSnapshot());
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    try {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      const handleChange = () => {
        if (currentSnapshot?.preference !== "system") return;
        notify({ preference: "system", resolved: getSystemPrefersDark() ? "dark" : "light" });
      };
      media.addEventListener?.("change", handleChange);
      systemMediaCleanup = () => media.removeEventListener?.("change", handleChange);
    } catch {
      // Deterministic matchMedia mocks (tests) or restrictive embedders may
      // not support this; System still resolves once from the initial snapshot.
    }
  }
  return currentSnapshot!;
}

export function subscribeTheme(listener: (snapshot: ThemeSnapshot) => void): () => void {
  listeners.add(listener);
  if (currentSnapshot) listener(currentSnapshot);
  return () => {
    listeners.delete(listener);
  };
}

export function getThemeSnapshot(): ThemeSnapshot {
  return currentSnapshot ?? getInitialThemeSnapshot();
}

export async function setThemePreference(preference: ThemePreference): Promise<ThemeSnapshot> {
  if (!isThemePreference(preference)) {
    throw new Error("Theme preference must be system, light, or dark.");
  }
  const desktop = typeof window !== "undefined" ? window.cmlDesktop : undefined;
  if (desktop?.setTheme) {
    const snapshot = await desktop.setTheme(preference);
    notify(isValidThemeSnapshot(snapshot) ? snapshot : { preference, resolved: resolveTheme(preference, getSystemPrefersDark()) });
    return currentSnapshot!;
  }
  writeStoredThemePreference(preference);
  const snapshot: ThemeSnapshot = { preference, resolved: resolveTheme(preference, getSystemPrefersDark()) };
  notify(snapshot);
  return snapshot;
}

/** Test-only reset so suites can exercise initializeTheme() from a clean slate. */
export function __resetThemeRuntimeForTests(): void {
  initialized = false;
  currentSnapshot = null;
  listeners.clear();
  systemMediaCleanup?.();
  systemMediaCleanup = null;
  desktopUnsubscribe?.();
  desktopUnsubscribe = null;
}
