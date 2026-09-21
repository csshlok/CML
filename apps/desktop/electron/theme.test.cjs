const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const fsPromises = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");

const {
  THEME_PREFERENCES,
  THEME_CHANGED_CHANNEL,
  LIGHT_BACKGROUND_COLOR,
  DARK_BACKGROUND_COLOR,
  isThemePreference,
  resolveEffectiveTheme,
  themeBackgroundColor,
  themePreferenceFilePath,
  readThemePreferenceFile,
  writeThemePreferenceFile,
  createThemeController,
} = require("./theme.cjs");

const temporaryDirectories = new Set();

function makeTempDir() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "cml-theme-"));
  temporaryDirectories.add(directory);
  return directory;
}

test.after(() => {
  for (const directory of temporaryDirectories) {
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
});

class FakeNativeTheme extends EventEmitter {
  constructor(initialShouldUseDarkColors = false) {
    super();
    this.shouldUseDarkColors = initialShouldUseDarkColors;
  }

  setSystemPrefersDark(value) {
    this.shouldUseDarkColors = value;
    this.emit("updated");
  }
}

class FakeWindow {
  constructor() {
    this.destroyed = false;
    this.backgroundColor = null;
    this.sent = [];
    this.webContents = {
      isDestroyed: () => this.destroyed,
      send: (channel, payload) => {
        this.sent.push({ channel, payload });
      },
    };
  }

  isDestroyed() {
    return this.destroyed;
  }

  setBackgroundColor(color) {
    this.backgroundColor = color;
  }

  destroy() {
    this.destroyed = true;
  }
}

test("isThemePreference accepts only system, light, and dark", () => {
  for (const value of THEME_PREFERENCES) {
    assert.equal(isThemePreference(value), true);
  }
  assert.equal(isThemePreference("auto"), false);
  assert.equal(isThemePreference(""), false);
  assert.equal(isThemePreference(null), false);
  assert.equal(isThemePreference(undefined), false);
  assert.equal(isThemePreference(1), false);
});

test("resolveEffectiveTheme resolves explicit overrides regardless of system state", () => {
  assert.equal(resolveEffectiveTheme("light", true), "light");
  assert.equal(resolveEffectiveTheme("light", false), "light");
  assert.equal(resolveEffectiveTheme("dark", true), "dark");
  assert.equal(resolveEffectiveTheme("dark", false), "dark");
});

test("resolveEffectiveTheme follows system state when preference is system", () => {
  assert.equal(resolveEffectiveTheme("system", true), "dark");
  assert.equal(resolveEffectiveTheme("system", false), "light");
});

test("themeBackgroundColor maps resolved themes to their window background", () => {
  assert.equal(themeBackgroundColor("light"), LIGHT_BACKGROUND_COLOR);
  assert.equal(themeBackgroundColor("dark"), DARK_BACKGROUND_COLOR);
});

test("readThemePreferenceFile resolves to system when the file is missing", async () => {
  const userDataPath = makeTempDir();
  const preference = await readThemePreferenceFile(userDataPath);
  assert.equal(preference, "system");
});

test("readThemePreferenceFile resolves to system when the file is corrupt JSON", async () => {
  const userDataPath = makeTempDir();
  const diagnostics = [];
  await fsPromises.writeFile(themePreferenceFilePath(userDataPath), "{not json", "utf8");
  const preference = await readThemePreferenceFile(userDataPath, (category) => diagnostics.push(category));
  assert.equal(preference, "system");
  assert.deepEqual(diagnostics, ["theme_preference_read_failed"]);
});

test("readThemePreferenceFile resolves to system when the stored preference is invalid", async () => {
  const userDataPath = makeTempDir();
  const diagnostics = [];
  await fsPromises.writeFile(
    themePreferenceFilePath(userDataPath),
    JSON.stringify({ schema_version: 1, preference: "purple" }),
    "utf8",
  );
  const preference = await readThemePreferenceFile(userDataPath, (category) => diagnostics.push(category));
  assert.equal(preference, "system");
  assert.deepEqual(diagnostics, ["theme_preference_invalid_shape"]);
});

test("writeThemePreferenceFile persists a value readThemePreferenceFile can round-trip", async () => {
  const userDataPath = makeTempDir();
  await writeThemePreferenceFile(userDataPath, "dark");
  const preference = await readThemePreferenceFile(userDataPath);
  assert.equal(preference, "dark");
});

test("writeThemePreferenceFile rejects invalid preferences", async () => {
  const userDataPath = makeTempDir();
  await assert.rejects(() => writeThemePreferenceFile(userDataPath, "purple"));
});

test("createThemeController initializes from disk and defaults to system", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const controller = createThemeController({ userDataPath, nativeTheme });
  const snapshot = await controller.initialize();
  assert.deepEqual(snapshot, { preference: "system", resolved: "light" });
  controller.dispose();
});

test("createThemeController setPreference persists, validates, and broadcasts", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const windowA = new FakeWindow();
  const windowB = new FakeWindow();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [windowA, windowB],
  });
  await controller.initialize();

  await assert.rejects(() => controller.setPreference("purple"));

  const snapshot = await controller.setPreference("dark");
  assert.deepEqual(snapshot, { preference: "dark", resolved: "dark" });
  assert.equal(await readThemePreferenceFile(userDataPath), "dark");

  assert.equal(windowA.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.equal(windowB.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.equal(windowA.sent.length, 1);
  assert.equal(windowA.sent[0].channel, THEME_CHANGED_CHANNEL);
  assert.deepEqual(windowA.sent[0].payload, snapshot);
  assert.deepEqual(windowB.sent[0].payload, snapshot);

  controller.dispose();
});

test("system preference changes live when OS theme changes", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const window = new FakeWindow();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [window],
  });
  await controller.initialize();
  assert.equal(controller.getSnapshot().resolved, "light");

  nativeTheme.setSystemPrefersDark(true);
  assert.equal(controller.getSnapshot().resolved, "dark");
  assert.equal(window.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.equal(window.sent.at(-1).payload.resolved, "dark");

  controller.dispose();
});

test("an OS change while System is active updates every open window identically", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const windowA = new FakeWindow();
  const windowB = new FakeWindow();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [windowA, windowB],
  });
  await controller.initialize();

  nativeTheme.setSystemPrefersDark(true);

  const expectedSnapshot = { preference: "system", resolved: "dark" };
  assert.equal(windowA.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.equal(windowB.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.deepEqual(windowA.sent.at(-1).payload, expectedSnapshot);
  assert.deepEqual(windowB.sent.at(-1).payload, expectedSnapshot);

  controller.dispose();
});

test("explicit overrides ignore OS changes", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const window = new FakeWindow();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [window],
  });
  await controller.initialize();
  await controller.setPreference("light");
  const sentBeforeOsChange = window.sent.length;

  nativeTheme.setSystemPrefersDark(true);

  assert.equal(controller.getSnapshot().resolved, "light");
  assert.equal(window.sent.length, sentBeforeOsChange);

  controller.dispose();
});

test("destroyed windows are skipped during broadcast", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const liveWindow = new FakeWindow();
  const destroyedWindow = new FakeWindow();
  destroyedWindow.destroy();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [liveWindow, destroyedWindow],
  });
  await controller.initialize();

  await controller.setPreference("dark");

  assert.equal(liveWindow.backgroundColor, DARK_BACKGROUND_COLOR);
  assert.equal(destroyedWindow.backgroundColor, null);
  assert.equal(destroyedWindow.sent.length, 0);

  controller.dispose();
});

test("dispose removes the nativeTheme listener so teardown leaves nothing retained", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const window = new FakeWindow();
  const controller = createThemeController({
    userDataPath,
    nativeTheme,
    getWindows: () => [window],
  });
  await controller.initialize();
  assert.equal(nativeTheme.listenerCount("updated"), 1);

  controller.dispose();
  assert.equal(nativeTheme.listenerCount("updated"), 0);

  nativeTheme.setSystemPrefersDark(true);
  assert.equal(window.sent.length, 0);

  controller.dispose();
  assert.equal(nativeTheme.listenerCount("updated"), 0);
});

test("listener registration is idempotent across repeated initialize() calls", async () => {
  const userDataPath = makeTempDir();
  const nativeTheme = new FakeNativeTheme(false);
  const controller = createThemeController({ userDataPath, nativeTheme });

  await controller.initialize();
  await controller.initialize();
  await controller.initialize();

  assert.equal(nativeTheme.listenerCount("updated"), 1);
  controller.dispose();
});

test("createThemeController requires userDataPath and nativeTheme", () => {
  assert.throws(() => createThemeController({ nativeTheme: new FakeNativeTheme() }));
  assert.throws(() => createThemeController({ userDataPath: makeTempDir() }));
});
