const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");

const {
  WINDOW_STATE_CHANNEL,
  attachWindowStateEvents,
  registerWindowControlHandlers,
} = require("./window-controls.cjs");

function createHarness() {
  const handlers = {};
  const sent = [];
  const window = new EventEmitter();
  let maximized = false;
  let fullScreen = false;
  let minimized = false;
  let closed = false;
  window.isDestroyed = () => false;
  window.isMaximized = () => maximized;
  window.isFullScreen = () => fullScreen;
  window.maximize = () => {
    maximized = true;
    window.emit("maximize");
  };
  window.unmaximize = () => {
    maximized = false;
    window.emit("unmaximize");
  };
  window.setFullScreen = (value) => {
    fullScreen = value;
    window.emit(value ? "enter-full-screen" : "leave-full-screen");
  };
  window.minimize = () => {
    minimized = true;
  };
  window.close = () => {
    closed = true;
  };
  window.webContents = {
    isDestroyed: () => false,
    send: (...args) => sent.push(args),
  };
  const sender = {};
  const BrowserWindow = {
    fromWebContents: (candidate) => (candidate === sender ? window : null),
  };
  const ipcMain = {
    handle: (channel, handler) => {
      handlers[channel] = handler;
    },
  };
  registerWindowControlHandlers({ ipcMain, BrowserWindow });
  attachWindowStateEvents(window);
  return {
    handlers,
    event: { sender },
    sent,
    window,
    getState: () => ({ maximized, fullScreen, minimized, closed }),
  };
}

test("window controls minimize, maximize, restore, and close only the sender window", async () => {
  const harness = createHarness();

  assert.deepEqual(await harness.handlers["cml:window-get-state"](harness.event), {
    maximized: false,
    fullScreen: false,
  });
  assert.equal(await harness.handlers["cml:window-minimize"](harness.event), true);
  assert.deepEqual(await harness.handlers["cml:window-toggle-maximize"](harness.event), {
    maximized: true,
    fullScreen: false,
  });
  assert.deepEqual(await harness.handlers["cml:window-toggle-maximize"](harness.event), {
    maximized: false,
    fullScreen: false,
  });
  assert.equal(await harness.handlers["cml:window-close"](harness.event), true);

  assert.deepEqual(harness.getState(), {
    maximized: false,
    fullScreen: false,
    minimized: true,
    closed: true,
  });
});

test("maximize control exits true fullscreen before changing maximized state", async () => {
  const harness = createHarness();
  harness.window.setFullScreen(true);

  assert.deepEqual(await harness.handlers["cml:window-toggle-maximize"](harness.event), {
    maximized: false,
    fullScreen: false,
  });
});

test("window state changes are published to the renderer", () => {
  const harness = createHarness();
  harness.window.maximize();

  assert.deepEqual(harness.sent.at(-1), [
    WINDOW_STATE_CHANNEL,
    { maximized: true, fullScreen: false },
  ]);
});

test("window controls reject events without a BrowserWindow sender", async () => {
  const harness = createHarness();
  const invalidEvent = { sender: {} };

  assert.equal(await harness.handlers["cml:window-minimize"](invalidEvent), false);
  assert.equal(await harness.handlers["cml:window-close"](invalidEvent), false);
  assert.deepEqual(await harness.handlers["cml:window-toggle-maximize"](invalidEvent), {
    maximized: false,
    fullScreen: false,
  });
});

test("desktop window and preload are wired to the custom frameless chrome", () => {
  const mainSource = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");
  const preloadSource = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
  const startupSource = fs.readFileSync(path.join(__dirname, "startup.html"), "utf8");
  const repairSource = fs.readFileSync(path.join(__dirname, "repair.html"), "utf8");
  const staticChromeSource = fs.readFileSync(
    path.join(__dirname, "static-window-chrome.js"),
    "utf8",
  );
  const staticChromeStyles = fs.readFileSync(
    path.join(__dirname, "static-window-chrome.css"),
    "utf8",
  );
  const stylesSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "styles.css"),
    "utf8",
  );

  assert.match(mainSource, /frame:\s*false/);
  assert.match(mainSource, /attachWindowStateEvents\(window\)/);
  assert.match(mainSource, /registerWindowControlHandlers\(\{\s*ipcMain,\s*BrowserWindow\s*\}\)/);
  assert.match(mainSource, /loadRepairDocument\(window/);
  assert.match(mainSource, /window\.loadFile\(repairDocumentPath/);
  assert.match(startupSource, /vault-static-window-controls/);
  assert.match(repairSource, /vault-static-window-controls/);
  assert.match(staticChromeSource, /bridge\.minimize\(\)/);
  assert.match(staticChromeSource, /bridge\.toggleMaximize\(\)/);
  assert.match(staticChromeSource, /bridge\.close\(\)/);
  assert.match(preloadSource, /windowControls:\s*\{/);
  assert.match(preloadSource, /cml:window-toggle-maximize/);
  assert.match(preloadSource, /cml:window-state-changed/);
  assert.doesNotMatch(
    preloadSource,
    /require\(["']\.{1,2}\//,
    "sandboxed preload must not require local files",
  );
  assert.match(
    stylesSource,
    /--vault-window-controls-safe-width:\s*calc\(/,
  );
  for (const contract of [
    ["--vault-window-controls-width", "138px"],
    ["--vault-window-controls-height", "32px"],
    ["--vault-window-controls-gap", "12px"],
  ]) {
    const pattern = new RegExp(`${contract[0]}:\\s*${contract[1]}`);
    assert.match(stylesSource, pattern);
    assert.match(staticChromeStyles, pattern);
  }
  const baseLayerStart = stylesSource.indexOf("@layer base {");
  const baseLayerOpeningBrace = stylesSource.indexOf("{", baseLayerStart);
  let baseLayerDepth = 0;
  let baseLayerEnd = -1;
  for (let index = baseLayerOpeningBrace; index < stylesSource.length; index += 1) {
    if (stylesSource[index] === "{") baseLayerDepth += 1;
    if (stylesSource[index] === "}") {
      baseLayerDepth -= 1;
      if (baseLayerDepth === 0) {
        baseLayerEnd = index;
        break;
      }
    }
  }
  const safeZoneRuleStart = stylesSource.indexOf(
    ".vault-window-aware.vault-window-aware",
  );
  assert.ok(baseLayerEnd > 0, "the Tailwind base layer must be well formed");
  assert.ok(
    safeZoneRuleStart > baseLayerEnd,
    "the window safe-zone rule must stay outside Tailwind layers",
  );
  assert.match(
    stylesSource,
    /\.vault-window-aware\.vault-window-aware\s*\{[^}]*min-height:\s*var\(--vault-window-controls-safe-height\)/s,
  );
  assert.doesNotMatch(
    stylesSource,
    /\.vault-window-aware(?:\.vault-window-aware)?\s*\{[^}]*padding-(?:right|inline-end):/s,
    "the safe zone must not reserve a full-width strip",
  );
  assert.match(
    stylesSource,
    /\.vault-window-aware\s*>\s*\*\s*\{[^}]*margin-inline-end:\s*var\(--vault-window-collision-inset,\s*0\)/s,
  );
  const windowAwareSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "WindowAware.tsx"),
    "utf8",
  );
  assert.match(
    windowAwareSource,
    /querySelector<HTMLElement>\("\[data-window-control-safe-zone\]"\)/,
    "shared window-aware layouts must measure the actual control rectangle",
  );
  assert.match(
    windowAwareSource,
    /baseline\.right\s*-\s*safe\.left\s*\+\s*12/,
    "only colliding children should move outside the no-go rectangle",
  );
  assert.match(
    stylesSource,
    /\.vault-window-controls\s*\{[^}]*-webkit-app-region:\s*no-drag/s,
  );
  assert.doesNotMatch(
    stylesSource,
    /\.vault-desktop-content\s*\{[^}]*padding-top:/s,
  );
  assert.match(
    stylesSource,
    /\.vault-mobile-bar\s*\{[^}]*padding:\s*6px max\(var\(--vault-window-controls-safe-width\),\s*12px\) 6px 12px;/s,
  );

  for (const routeName of [
    "_app.search.tsx",
    "_app.home.tsx",
    "_app.sources.tsx",
    "_app.map.tsx",
    "_app.projects.tsx",
    "_app.tasks.tsx",
    "_app.bridge.tsx",
    "_app.clusters.tsx",
    "_app.chat.tsx",
    "_app.chat.$chatId.tsx",
    "_app.clusters.$clusterId.tsx",
    "_app.projects.$projectId.tsx",
    "_app.settings.tsx",
    "_app.timeline.tsx",
  ]) {
    const routeSource = fs.readFileSync(
      path.join(__dirname, "..", "src", "routes", routeName),
      "utf8",
    );
    assert.match(
      routeSource,
      /import\s+\{\s*PageHeader\s*\}\s+from\s+"@\/components\/layout\/WindowAware"/,
      `${routeName} must use the shared window-aware page header`,
    );
    assert.match(routeSource, /<PageHeader(?:\s|>)/, `${routeName} must render PageHeader`);
    assert.doesNotMatch(routeSource, /desktop-window-action|vault-window-control-clearance/);
  }
});
