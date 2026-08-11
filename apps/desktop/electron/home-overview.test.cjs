const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const desktopRoot = path.join(__dirname, "..");
const homeSource = fs.readFileSync(
  path.join(desktopRoot, "src", "routes", "_app.home.tsx"),
  "utf8",
);
const preferencesPath = path.join(desktopRoot, "src", "lib", "homePreferences.ts");
const preferencesSource = fs.readFileSync(preferencesPath, "utf8");
const preferencesModule = { exports: {} };
const compiledPreferences = ts.transpileModule(preferencesSource, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
  fileName: preferencesPath,
}).outputText;
new Function("module", "exports", "require", compiledPreferences)(
  preferencesModule,
  preferencesModule.exports,
  require,
);
const {
  DEFAULT_HOME_PREFERENCES,
  homePreferencesForPreset,
  homePreferencesStorageKey,
  moveHomeSection,
  readHomePreferences,
  writeHomePreferences,
} = preferencesModule.exports;

test("Home presents a working overview instead of repeated dashboard actions", () => {
  assert.match(homeSource, /const hasHomeContent = Boolean\(/);
  assert.match(homeSource, /\{hasHomeContent \? \(/);
  assert.match(homeSource, />Type:<\/span>/);
  assert.match(homeSource, />Sort:<\/span>/);
  assert.match(homeSource, /\sCustomize\s*<\/Button>/);
  assert.match(homeSource, /Ask Vault/);
  assert.match(homeSource, /Needs attention/);
  assert.match(homeSource, /Suggested moves/);
  assert.match(homeSource, /Continue working/);
  assert.match(homeSource, /Active clusters/);
  assert.doesNotMatch(homeSource, /Search filters|Suggested clusters|Recent memories/);
});

test("Home preferences persist a fully visible custom layout", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  const custom = {
    ...DEFAULT_HOME_PREFERENCES,
    density: "compact",
    view: "grid",
    hiddenSections: [],
  };

  writeHomePreferences(custom, storage, "profile/one");
  const restored = readHomePreferences(storage, "profile/one");

  assert.equal(values.has(homePreferencesStorageKey("profile/one")), true);
  assert.equal(values.has(homePreferencesStorageKey("profile/two")), false);
  assert.equal(restored.density, "compact");
  assert.equal(restored.view, "grid");
  assert.deepEqual(restored.hiddenSections, []);
});

test("Focused Home puts Quick actions second without rewriting saved custom order", () => {
  assert.deepEqual(DEFAULT_HOME_PREFERENCES.sectionOrder.slice(0, 2), ["ask", "quick"]);

  const focused = homePreferencesForPreset(DEFAULT_HOME_PREFERENCES, "focused");
  assert.deepEqual(focused.sectionOrder.slice(0, 2), ["ask", "quick"]);

  const customOrder = [
    "clusters",
    "ask",
    ...DEFAULT_HOME_PREFERENCES.sectionOrder.filter(
      (sectionId) => sectionId !== "clusters" && sectionId !== "ask",
    ),
  ];
  const storage = {
    getItem: () =>
      JSON.stringify({
        ...DEFAULT_HOME_PREFERENCES,
        sectionOrder: customOrder,
      }),
  };

  const restored = readHomePreferences(storage);
  assert.deepEqual(restored.sectionOrder, customOrder);
});

test("invalid saved Home preferences fall back safely without losing valid visibility", () => {
  const storage = {
    getItem: () =>
      JSON.stringify({
        preset: "focused",
        density: "impossibly-dense",
        view: "list",
        type: "all",
        sort: "updated",
        sectionOrder: ["ask", "ask", "unknown", "clusters"],
        hiddenSections: ["attention", "attention", "unknown"],
      }),
  };

  const restored = readHomePreferences(storage);

  assert.equal(restored.density, "comfortable");
  assert.equal(new Set(restored.sectionOrder).size, restored.sectionOrder.length);
  assert.equal(restored.sectionOrder.length, DEFAULT_HOME_PREFERENCES.sectionOrder.length);
  assert.deepEqual(restored.hiddenSections, ["attention"]);
});

test("presets and keyboard reorder keep a complete, stable section list", () => {
  const library = homePreferencesForPreset(DEFAULT_HOME_PREFERENCES, "library");
  assert.deepEqual(library.sectionOrder.slice(0, 5), [
    "recentSources",
    "inbox",
    "clusters",
    "sourceTypes",
    "quick",
  ]);
  assert.equal(library.hiddenSections.includes("ask"), true);

  const moved = moveHomeSection(library, "inbox", -1);
  assert.deepEqual(moved.sectionOrder.slice(0, 2), ["inbox", "recentSources"]);
  assert.equal(new Set(moved.sectionOrder).size, moved.sectionOrder.length);
});

test("sidebar uses the requested artwork while startup keeps the opening wordmark", () => {
  const brandSource = fs.readFileSync(
    path.join(desktopRoot, "src", "components", "BrandLogo.tsx"),
    "utf8",
  );
  const shellSource = fs.readFileSync(
    path.join(desktopRoot, "src", "components", "AppShell.tsx"),
    "utf8",
  );
  const startupSource = fs.readFileSync(path.join(__dirname, "startup.html"), "utf8");

  assert.match(brandSource, /VAULT_OPENING_WORDMARK\s*=\s*"\/brand\/Container\.svg"/);
  assert.match(brandSource, /VAULT_SIDEBAR_WORDMARK\s*=\s*"\/brand\/Frame%208\.png"/);
  assert.doesNotMatch(brandSource, /brand\/logo\.svg|variant/);
  assert.match(shellSource, /<SidebarBrandLogo/);
  assert.match(startupSource, /brand\/Container\.svg/);
});

test("long-lived views invalidate data when the desktop backend generation changes", () => {
  const backendSource = fs.readFileSync(
    path.join(desktopRoot, "src", "lib", "backend.ts"),
    "utf8",
  );
  const timelineSource = fs.readFileSync(
    path.join(desktopRoot, "src", "routes", "_app.timeline.tsx"),
    "utf8",
  );
  const bridgeSource = fs.readFileSync(
    path.join(desktopRoot, "src", "routes", "_app.bridge.tsx"),
    "utf8",
  );

  assert.match(backendSource, /backendGenerationListeners\.forEach/);
  assert.match(homeSource, /useBackendGeneration\(\)/);
  assert.match(homeSource, /overviewSequence/);
  assert.match(timelineSource, /\[backendGeneration\]/);
  assert.match(bridgeSource, /loadSequence/);
  assert.match(bridgeSource, /backendGeneration/);
});
