const path = require("node:path");
const fs = require("node:fs/promises");
const { atomicWriteJson } = require("./setup-state.cjs");

// Appearance is device-level UI state, not encrypted vault content: it must
// resolve before vault selection, unlock, or any backend call, and it must
// never disclose vault paths or secrets in diagnostics.
const THEME_PREFERENCES = Object.freeze(["system", "light", "dark"]);
const THEME_SCHEMA_VERSION = 1;
const THEME_PREFERENCE_FILE_NAME = "theme-preference.json";
const THEME_CHANGED_CHANNEL = "cml:theme-changed";

// theme-literal-color-allowed: file -- this module is the centralized native
// Electron palette. BrowserWindow and last-resort data: documents cannot read
// renderer CSS custom properties, so their concrete colors live here only.
// Matches the existing BrowserWindow default so light mode is unaffected.
const LIGHT_BACKGROUND_COLOR = "#fbfaf6";
// Warm charcoal, not pure black, per the locked visual direction.
const DARK_BACKGROUND_COLOR = "#211d19";

const FALLBACK_PALETTES = Object.freeze({
  light: Object.freeze({
    background: LIGHT_BACKGROUND_COLOR,
    foreground: "#27211d",
    muted: "#766b64",
    track: "#e8e1d8",
    progress: "#27211d",
  }),
  dark: Object.freeze({
    background: DARK_BACKGROUND_COLOR,
    foreground: "#f2ece3",
    muted: "#b7a99a",
    track: "#423930",
    progress: "#c9a97d",
  }),
});

function isThemePreference(value) {
  return THEME_PREFERENCES.includes(value);
}

function resolveEffectiveTheme(preference, systemPrefersDark) {
  if (preference === "light") return "light";
  if (preference === "dark") return "dark";
  return systemPrefersDark ? "dark" : "light";
}

function themeBackgroundColor(resolved) {
  return resolved === "dark" ? DARK_BACKGROUND_COLOR : LIGHT_BACKGROUND_COLOR;
}

function themeFallbackPalette(resolved) {
  return resolved === "dark" ? FALLBACK_PALETTES.dark : FALLBACK_PALETTES.light;
}

function themePreferenceFilePath(userDataPath) {
  return path.join(userDataPath, THEME_PREFERENCE_FILE_NAME);
}

async function readThemePreferenceFile(userDataPath, onDiagnostic) {
  const target = themePreferenceFilePath(userDataPath);
  try {
    const raw = await fs.readFile(target, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && isThemePreference(parsed.preference)) {
      return parsed.preference;
    }
    onDiagnostic?.("theme_preference_invalid_shape");
    return "system";
  } catch (error) {
    if (error?.code !== "ENOENT") {
      onDiagnostic?.("theme_preference_read_failed");
    }
    return "system";
  }
}

async function writeThemePreferenceFile(userDataPath, preference) {
  if (!isThemePreference(preference)) {
    throw new Error("Theme preference must be system, light, or dark.");
  }
  await atomicWriteJson(themePreferenceFilePath(userDataPath), {
    schema_version: THEME_SCHEMA_VERSION,
    preference,
    updated_at: new Date().toISOString(),
  });
}

// Deliberately never mutates nativeTheme.themeSource: keeping it pinned to
// the OS value means nativeTheme.shouldUseDarkColors always reflects the
// real system state, so an explicit Light/Dark override can be resolved
// locally while still allowing "system" to observe live OS changes through
// the same signal.
function createThemeController({ userDataPath, nativeTheme, getWindows = () => [], onDiagnostic } = {}) {
  if (!userDataPath) throw new Error("createThemeController requires userDataPath.");
  if (!nativeTheme) throw new Error("createThemeController requires nativeTheme.");

  let preference = "system";
  let disposed = false;

  function systemPrefersDark() {
    return Boolean(nativeTheme.shouldUseDarkColors);
  }

  function effectiveTheme() {
    return resolveEffectiveTheme(preference, systemPrefersDark());
  }

  function getSnapshot() {
    return { preference, resolved: effectiveTheme() };
  }

  async function initialize() {
    preference = await readThemePreferenceFile(userDataPath, onDiagnostic);
    return getSnapshot();
  }

  function applyToWindow(window) {
    if (!window || window.isDestroyed()) return;
    try {
      window.setBackgroundColor(themeBackgroundColor(effectiveTheme()));
    } catch {
      onDiagnostic?.("theme_window_background_failed");
    }
  }

  function broadcast() {
    const snapshot = getSnapshot();
    for (const window of getWindows()) {
      if (!window || window.isDestroyed()) continue;
      applyToWindow(window);
      if (window.webContents && !window.webContents.isDestroyed()) {
        window.webContents.send(THEME_CHANGED_CHANNEL, snapshot);
      }
    }
    return snapshot;
  }

  async function setPreference(nextPreference) {
    if (!isThemePreference(nextPreference)) {
      throw new Error("Theme preference must be system, light, or dark.");
    }
    preference = nextPreference;
    try {
      await writeThemePreferenceFile(userDataPath, nextPreference);
    } catch {
      onDiagnostic?.("theme_preference_persist_failed");
    }
    return broadcast();
  }

  function handleNativeThemeUpdated() {
    if (disposed) return;
    // Explicit Light/Dark overrides intentionally ignore live OS changes;
    // only "system" re-resolves and broadcasts here.
    if (preference !== "system") return;
    broadcast();
  }

  nativeTheme.on("updated", handleNativeThemeUpdated);

  function dispose() {
    if (disposed) return;
    disposed = true;
    nativeTheme.removeListener("updated", handleNativeThemeUpdated);
  }

  return {
    initialize,
    getSnapshot,
    setPreference,
    applyToWindow,
    broadcast,
    dispose,
  };
}

module.exports = {
  THEME_PREFERENCES,
  THEME_SCHEMA_VERSION,
  THEME_PREFERENCE_FILE_NAME,
  THEME_CHANGED_CHANNEL,
  LIGHT_BACKGROUND_COLOR,
  DARK_BACKGROUND_COLOR,
  isThemePreference,
  resolveEffectiveTheme,
  themeBackgroundColor,
  themeFallbackPalette,
  themePreferenceFilePath,
  readThemePreferenceFile,
  writeThemePreferenceFile,
  createThemeController,
};
