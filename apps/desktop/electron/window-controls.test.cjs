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
  const stylesSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "styles.css"),
    "utf8",
  );

  assert.match(mainSource, /frame:\s*false/);
  assert.match(mainSource, /attachWindowStateEvents\(window\)/);
  assert.match(mainSource, /registerWindowControlHandlers\(\{\s*ipcMain,\s*BrowserWindow\s*\}\)/);
  assert.match(mainSource, /repairWindowChromeMarkup\(\)/);
  assert.match(preloadSource, /windowControls:\s*\{/);
  assert.match(preloadSource, /cml:window-toggle-maximize/);
  assert.match(preloadSource, /cml:window-state-changed/);
  assert.match(
    stylesSource,
    /\.vault-window-chrome\s*\{[^}]*width:\s*150px;[^}]*height:\s*44px;/s,
  );
  assert.match(
    stylesSource,
    /\.vault-desktop-frame \.desktop-window-action\s*\{[^}]*margin-right:\s*150px;/s,
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
    /\.vault-desktop-frame \.vault-mobile-status\s*\{[^}]*margin-right:\s*150px;/s,
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
  ]) {
    const routeSource = fs.readFileSync(
      path.join(__dirname, "..", "src", "routes", routeName),
      "utf8",
    );
    assert.match(routeSource, /desktop-window-action/, `${routeName} must avoid window controls`);
  }
});
