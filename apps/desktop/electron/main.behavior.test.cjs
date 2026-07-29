const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");
const vm = require("node:vm");

const temporaryDirectories = new Set();

function makeTempDir(prefix) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  temporaryDirectories.add(directory);
  return directory;
}

async function makeTempDirAsync(prefix) {
  const directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), prefix));
  temporaryDirectories.add(directory);
  return directory;
}

test.after(() => {
  for (const directory of temporaryDirectories) {
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
});

function loadMainModule() {
  const filePath = path.join(__dirname, "main.cjs");
  const source =
    fs.readFileSync(filePath, "utf8") +
    "\nmodule.exports = { repairActionForPhase, isAllowedExternalUrl, isCurrentBackend, backendIdentityMatches, rendererSecurityHeaders, sanitizeRendererBody, imageMimeType, imageDimensions, resolveApprovedMediaTarget, setActiveVaultPath, prepareActiveVaultPath, commitActiveVaultPath, getActiveVaultPath, getInitialRendererPath, resolveSetupLaunchState, collectSupportedFiles, findOpenPort, loadStartupProgress, loadStartupFailure, loadRendererFailure, truncateDesktopLogValue, tryServeStaticAsset, verifyRendererUp, waitForBackend, resolvePackagedServerEntry, assertSafeVaultMoveRoots, verifyCopiedVault, finalizeActiveVaultDeletion, reconcilePendingVaultDeletion, __setMainWindow: (value) => { mainWindow = value; }, __setTunnelManager: (value) => { tunnelManager = value; }, __getPendingActiveVaultPath: () => pendingActiveVaultPath, __setBackendUrl: (value) => { backendUrl = value; }, __setRestartBackend: (value) => { restartBackend = value; }, __setEnsureBackend: (value) => { ensureBackend = value; } };";

  const appHandlers = {};
  const dialogCalls = [];
  const ipcHandlers = {};
  const userDataDir = makeTempDir("cml-electron-");
  const electronStub = {
    app: {
      isPackaged: false,
      requestSingleInstanceLock: () => true,
      on: (event, handler) => {
        appHandlers[event] = handler;
      },
      whenReady: () => ({ then: () => {} }),
      quit: () => {},
      getPath: () => userDataDir,
    },
    BrowserWindow: class BrowserWindow {
      static getAllWindows() {
        return [];
      }
    },
    dialog: {
      showMessageBox: (...args) => {
        dialogCalls.push(args);
        return Promise.resolve({ response: 0 });
      },
    },
    clipboard: {
      writeText: () => {},
      readText: () => "clipboard text from electron",
    },
    ipcMain: {
      handle: (name, handler) => {
        ipcHandlers[name] = handler;
      },
    },
    shell: {
      openExternal: () => {},
      openPath: async () => "",
      showItemInFolder: () => {},
    },
  };

  const sandbox = {
    module: { exports: {} },
    exports: {},
    require: (id) => {
      if (id === "electron") return electronStub;
      if (id === "./token-store.cjs") {
        return {
          createTokenStore: () => ({}),
          getOrCreateToken: () => "test-token-value",
        };
      }
      return require(id);
    },
    __dirname,
    __filename: filePath,
    process: Object.assign(Object.create(process), {
      env: process.env,
      on: () => {},
    }),
    console,
    Buffer,
    setTimeout,
    clearTimeout,
    URL,
    URLSearchParams,
  };
  sandbox.exports = sandbox.module.exports;
  vm.runInNewContext(source, sandbox, { filename: filePath });

  return {
    exported: sandbox.module.exports,
    appHandlers,
    dialogCalls,
    ipcHandlers,
    userDataDir,
  };
}

test("second-instance with vault arg focuses window and shows already-open dialog", async () => {
  const { exported, appHandlers, dialogCalls } = loadMainModule();
  let focused = false;
  let restored = false;
  exported.__setMainWindow({
    isMinimized: () => true,
    restore: () => {
      restored = true;
    },
    focus: () => {
      focused = true;
    },
  });

  await appHandlers["second-instance"]({}, ["electron.exe", "--vault=C:\\OtherVault"]);

  assert.equal(restored, true);
  assert.equal(focused, true);
  assert.equal(dialogCalls.length, 1);
  assert.match(dialogCalls[0][1].message, /already open/i);
});

test("external URL allowlist permits http/https/mailto and blocks unsafe schemes", () => {
  const { exported } = loadMainModule();

  assert.equal(exported.isAllowedExternalUrl("https://example.com"), true);
  assert.equal(exported.isAllowedExternalUrl("http://example.com"), true);
  assert.equal(exported.isAllowedExternalUrl("mailto:test@example.com"), true);
  assert.equal(exported.isAllowedExternalUrl("file:///C:/secret.txt"), false);
  assert.equal(exported.isAllowedExternalUrl("ftp://example.com/file"), false);
  assert.equal(exported.isAllowedExternalUrl("javascript:alert(1)"), false);
});

test("packaged renderer security headers enforce CSP and nosniff", () => {
  const { exported } = loadMainModule();

  const headers = exported.rendererSecurityHeaders({ "content-type": "text/html; charset=utf-8" });

  assert.match(headers["content-security-policy"], /default-src 'self'/);
  assert.match(headers["content-security-policy"], /script-src 'self' 'unsafe-inline'/);
  assert.match(headers["content-security-policy"], /img-src 'self' data: blob: https:/);
  assert.match(headers["content-security-policy"], /object-src 'none'/);
  assert.match(headers["content-security-policy"], /frame-ancestors 'none'/);
  assert.match(headers["content-security-policy"], /connect-src 'self' http:\/\/127\.0\.0\.1:\*/);
  assert.equal(headers["x-content-type-options"], "nosniff");
  assert.equal(headers["referrer-policy"], "no-referrer");
});

test("packaged renderer strips external font links before serving HTML", async () => {
  const { exported } = loadMainModule();
  const response = new Response(
    '<!doctype html><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter"><link rel="preconnect" href="https://fonts.googleapis.com"><script type="module" src="/assets/index.js"></script>',
    { headers: { "content-type": "text/html; charset=utf-8" } },
  );

  const body = await exported.sanitizeRendererBody(response, { "content-type": "text/html; charset=utf-8" });
  const html = body.toString("utf8");

  assert.doesNotMatch(html, /fonts\.googleapis\.com/);
  assert.match(html, /\/assets\/index\.js/);
});

test("startup repair messages are phase-specific", () => {
  const { exported } = loadMainModule();

  const integrity = exported.repairActionForPhase("integrity_check_failed");
  const lock = exported.repairActionForPhase("vault_lock_failed");

  assert.match(integrity.title, /library needs to be checked/i);
  assert.match(lock.body, /close any other Vault window/i);
});

test("second-instance without vault arg focuses existing window without dialog", async () => {
  const { exported, appHandlers, dialogCalls } = loadMainModule();
  let focused = false;
  exported.__setMainWindow({
    isMinimized: () => false,
    restore: () => {
      throw new Error("restore should not be called");
    },
    focus: () => {
      focused = true;
    },
  });

  await appHandlers["second-instance"]({}, ["electron.exe"]);

  assert.equal(focused, true);
  assert.equal(dialogCalls.length, 0);
});

test("setActiveVaultPath persists unicode vault path and creates .vault directory", async () => {
  const { exported } = loadMainModule();
  const targetRoot = makeTempDir("cml-vault path-");
  const vaultPath = path.join(targetRoot, "研究 Vault 😀", "nested folder");

  await exported.setActiveVaultPath(vaultPath);
  const stored = await exported.getActiveVaultPath();

  assert.equal(stored, vaultPath);
  assert.equal(fs.existsSync(path.join(vaultPath, ".vault")), true);
});

test("local image sniffing accepts supported raster formats and rejects disguised text", () => {
  const { exported } = loadMainModule();

  assert.equal(
    exported.imageMimeType(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])),
    "image/png",
  );
  assert.equal(exported.imageMimeType(Buffer.from([255, 216, 255, 224, 0, 16])), "image/jpeg");
  assert.equal(exported.imageMimeType(Buffer.from("GIF89a", "ascii")), "image/gif");
  assert.equal(exported.imageMimeType(Buffer.from("<svg onload=alert(1)>", "utf8")), null);
});

test("profile media IDs are opaque, traversal-safe, and resolve only inside managed media", () => {
  const { exported, userDataDir } = loadMainModule();
  const digest = "a".repeat(64);
  assert.equal(
    exported.resolveApprovedMediaTarget(`media:profile:${digest}.png`),
    path.join(userDataDir, "media", "profiles", `${digest}.png`),
  );
  assert.equal(exported.resolveApprovedMediaTarget("media:profile:../../secret.png"), null);
  assert.equal(exported.resolveApprovedMediaTarget(`media:source:${digest}.png`), null);
  assert.equal(exported.resolveApprovedMediaTarget(`media:profile:${digest}.svg`), null);
});

test("image dimensions are read from headers without decoding untrusted pixels", () => {
  const { exported } = loadMainModule();
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(800, 16);
  png.writeUInt32BE(600, 20);
  assert.deepEqual(
    JSON.parse(JSON.stringify(exported.imageDimensions(png, "image/png"))),
    { width: 800, height: 600 },
  );

  const gif = Buffer.alloc(10);
  gif.write("GIF89a", 0, "ascii");
  gif.writeUInt16LE(320, 6);
  gif.writeUInt16LE(240, 8);
  assert.deepEqual(
    JSON.parse(JSON.stringify(exported.imageDimensions(gif, "image/gif"))),
    { width: 320, height: 240 },
  );
  assert.equal(exported.imageDimensions(Buffer.from("not an image"), "image/png"), null);
});

test("vault deletion tombstones data before clearing the active pointer", async () => {
  const { exported, userDataDir } = loadMainModule();
  const tunnelEvents = [];
  exported.__setTunnelManager({
    disconnect: async (options) => tunnelEvents.push(options),
  });
  const vaultRoot = await makeTempDirAsync("cml-delete-vault-");
  await exported.setActiveVaultPath(vaultRoot);
  await fs.promises.writeFile(path.join(vaultRoot, ".vault", "cml.sqlite3"), "fixture");
  await fs.promises.writeFile(
    path.join(userDataDir, "setup-state.json"),
    JSON.stringify({
      schema_version: 1,
      phase: "complete",
      profile: { display_name: "Ada" },
      vault: { id: "vault-1", name: "Personal", path: vaultRoot },
      chat_setup: { status: "skipped", model_id: "" },
      memory_setup: { status: "skipped", model_id: "" },
      updated_at: new Date().toISOString(),
    }),
  );
  exported.__setEnsureBackend(async () => "http://127.0.0.1:7343");

  const result = await exported.finalizeActiveVaultDeletion();

  assert.equal(result.deleted, true);
  assert.equal(await exported.getActiveVaultPath(), null);
  assert.equal(fs.existsSync(path.join(vaultRoot, ".vault")), false);
  assert.equal(fs.existsSync(path.join(userDataDir, "vault-deletion.json")), false);
  assert.equal(JSON.stringify(tunnelEvents), JSON.stringify([{ forget: true }]));
});

test("vault deletion restores data, pointer, and setup state when pre-vault restart fails", async () => {
  const { exported, userDataDir } = loadMainModule();
  const vaultRoot = await makeTempDirAsync("cml-delete-rollback-");
  await exported.setActiveVaultPath(vaultRoot);
  await fs.promises.writeFile(path.join(vaultRoot, ".vault", "cml.sqlite3"), "fixture");
  const setupState = {
    schema_version: 1,
    phase: "complete",
    profile: { display_name: "Ada" },
    vault: { id: "vault-1", name: "Personal", path: vaultRoot },
    chat_setup: { status: "ready", model_id: "model-1" },
    memory_setup: { status: "ready", model_id: "embedding-1" },
    updated_at: new Date().toISOString(),
  };
  await fs.promises.writeFile(
    path.join(userDataDir, "setup-state.json"),
    JSON.stringify(setupState),
  );
  let calls = 0;
  exported.__setEnsureBackend(async () => {
    calls += 1;
    if (calls === 1) throw new Error("pre-vault restart failed");
    return "http://127.0.0.1:7343";
  });

  await assert.rejects(
    exported.finalizeActiveVaultDeletion(),
    /pre-vault restart failed/,
  );

  assert.equal(await exported.getActiveVaultPath(), vaultRoot);
  assert.equal(fs.existsSync(path.join(vaultRoot, ".vault", "cml.sqlite3")), true);
  const restored = JSON.parse(
    await fs.promises.readFile(path.join(userDataDir, "setup-state.json"), "utf8"),
  );
  assert.equal(restored.phase, "complete");
  assert.equal(restored.vault.path, vaultRoot);
  assert.equal(fs.existsSync(path.join(userDataDir, "vault-deletion.json")), false);
});

test("prepared vault folder does not become active until committed", async () => {
  const { exported } = loadMainModule();
  const targetRoot = makeTempDir("cml-prepared-vault-");
  const vaultPath = path.join(targetRoot, "prepared-vault");
  let restarts = 0;
  exported.__setRestartBackend(async () => {
    restarts += 1;
    exported.__setBackendUrl(`http://127.0.0.1:${7400 + restarts}`);
  });

  await exported.prepareActiveVaultPath(vaultPath);

  assert.equal(fs.existsSync(path.join(vaultPath, ".vault")), true);
  assert.equal(exported.__getPendingActiveVaultPath(), vaultPath);
  assert.equal(await exported.getActiveVaultPath(), null);
  assert.equal(await exported.getInitialRendererPath(), "/onboarding");
  assert.equal(restarts, 1);

  await exported.commitActiveVaultPath(vaultPath);

  assert.equal(exported.__getPendingActiveVaultPath(), null);
  assert.equal(await exported.getActiveVaultPath(), vaultPath);
  assert.equal(await exported.getInitialRendererPath(), "/home");
  assert.equal(restarts, 1);
});

test("vault move rejects drive roots and overlapping folders", () => {
  const { exported } = loadMainModule();
  const root = path.parse(process.cwd()).root;
  assert.throws(
    () => exported.assertSafeVaultMoveRoots(root, path.join(root, "VaultDestination")),
    /below a drive root/,
  );
  assert.throws(
    () =>
      exported.assertSafeVaultMoveRoots(
        path.join(root, "VaultSource"),
        path.join(root, "VaultSource", "Nested"),
      ),
    /cannot be inside/,
  );
});

test("copied vault verification requires a SQLite database header", async () => {
  const { exported } = loadMainModule();
  const validRoot = makeTempDir("cml-vault-copy-valid-");
  fs.writeFileSync(
    path.join(validRoot, "cml.sqlite3"),
    Buffer.concat([Buffer.from("SQLite format 3\0"), Buffer.alloc(64)]),
  );
  await exported.verifyCopiedVault(validRoot);

  const invalidRoot = makeTempDir("cml-vault-copy-invalid-");
  fs.writeFileSync(path.join(invalidRoot, "cml.sqlite3"), "not sqlite");
  await assert.rejects(exported.verifyCopiedVault(invalidRoot), /SQLite header/);
});

test("stale active vault config falls back to onboarding instead of forcing home", async () => {
  const { exported, userDataDir } = loadMainModule();
  const targetRoot = makeTempDir("cml-stale-vault-");
  const vaultPath = path.join(targetRoot, "stale-vault");

  await exported.setActiveVaultPath(vaultPath);
  const { writeSetupState, defaultSetupState } = require("./setup-state.cjs");
  await writeSetupState(userDataDir, {
    ...defaultSetupState(),
    phase: "complete",
    vault: { id: "vault-stale", name: "Stale", path: vaultPath },
  });
  fs.rmSync(targetRoot, { recursive: true, force: true });

  assert.equal(await exported.getActiveVaultPath(), null);
  assert.equal(await exported.getInitialRendererPath(), "/onboarding");
  const resolved = await exported.resolveSetupLaunchState();
  assert.equal(resolved.state.phase, "recovery");
  assert.equal(resolved.state.recovery_reason, "missing_vault_data");
});

test("fresh install opens setup without showing missing-library recovery", async () => {
  const { exported } = loadMainModule();

  assert.equal(await exported.getInitialRendererPath(), "/onboarding");
  const resolved = await exported.resolveSetupLaunchState();
  assert.equal(resolved.state.phase, "fresh");
  assert.equal(resolved.state.recovery_reason, undefined);
});

test("completed setup restores a missing active pointer when saved vault data is valid", async () => {
  const { exported, userDataDir } = loadMainModule();
  const vaultPath = makeTempDir("cml-saved-vault-");
  fs.mkdirSync(path.join(vaultPath, ".vault"));
  const { writeSetupState, defaultSetupState } = require("./setup-state.cjs");
  await writeSetupState(userDataDir, {
    ...defaultSetupState(),
    phase: "complete",
    vault: { id: "vault-saved", name: "Saved", path: vaultPath },
  });

  assert.equal(await exported.getActiveVaultPath(), null);
  assert.equal(await exported.getInitialRendererPath(), "/home");
  assert.equal(await exported.getActiveVaultPath(), vaultPath);
  const resolved = await exported.resolveSetupLaunchState();
  assert.equal(resolved.state.phase, "complete");
  assert.equal(resolved.state.recovery_reason, undefined);
});

test("incomplete setup never becomes missing-library recovery", async () => {
  const { exported, userDataDir } = loadMainModule();
  const missingPath = path.join(userDataDir, "not-created");
  const { writeSetupState, defaultSetupState } = require("./setup-state.cjs");
  await writeSetupState(userDataDir, {
    ...defaultSetupState(),
    phase: "profile_complete",
    profile: { display_name: "Ada", avatar_path: "" },
    vault: { id: "", name: "My Library", path: missingPath },
  });

  const resolved = await exported.resolveSetupLaunchState();
  assert.equal(resolved.state.phase, "profile_complete");
  assert.equal(resolved.state.recovery_reason, undefined);
});

test("collectSupportedFiles skips symlinks and build folders", async () => {
  const { exported } = loadMainModule();
  const root = makeTempDir("cml-collect-");
  const outside = makeTempDir("cml-outside-");
  fs.writeFileSync(path.join(root, "note.md"), "# kept\n", "utf8");
  fs.mkdirSync(path.join(root, "node_modules"));
  fs.writeFileSync(path.join(root, "node_modules", "ignored.md"), "# ignored\n", "utf8");
  fs.writeFileSync(path.join(outside, "secret.md"), "# secret\n", "utf8");
  try {
    fs.symlinkSync(outside, path.join(root, "link-out"), "junction");
  } catch {
    return;
  }

  const files = [];
  await exported.collectSupportedFiles(root, files);

  assert.deepEqual(files.map((entry) => path.basename(entry)).sort(), ["note.md"]);
});

test("findOpenPort skips an occupied port and returns the next free loopback port", async () => {
  const { exported } = loadMainModule();
  const server = net.createServer();
  const start = 7450;
  await new Promise((resolve) => server.listen(start, "127.0.0.1", resolve));

  try {
    const port = await exported.findOpenPort(start, start + 2);
    assert.equal(port, start + 1);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("isCurrentBackend requires authenticated backend identity", async () => {
  const { exported } = loadMainModule();
  const server = http.createServer((request, response) => {
    const authorized = request.headers["x-cml-api-token"] === "expected-token";
    if (request.url !== "/api/v1/system/backend-identity" || !authorized) {
      response.writeHead(401);
      response.end();
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ service: "cml-backend", api_prefix: "/api/v1" }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    assert.equal(await exported.isCurrentBackend(`http://127.0.0.1:${port}`, "wrong-token"), false);
    assert.equal(await exported.isCurrentBackend(`http://127.0.0.1:${port}`, "expected-token"), true);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("backend identity must match the intended mode and exact vault paths", () => {
  const { exported } = loadMainModule();
  const intended = {
    backend_mode: "full_vault",
    data_dir: "C:\\Vaults\\Personal\\.vault",
    database_path: "C:\\Vaults\\Personal\\.vault\\cml.sqlite3",
  };
  const correct = {
    service: "cml-backend",
    api_prefix: "/api/v1",
    ...intended,
  };

  assert.equal(exported.backendIdentityMatches(correct, intended), true);
  assert.equal(
    exported.backendIdentityMatches(
      { ...correct, data_dir: "C:\\Users\\Ada\\AppData\\Roaming\\Vault\\pre-vault" },
      intended,
    ),
    false,
  );
  assert.equal(
    exported.backendIdentityMatches({ ...correct, backend_mode: "pre_vault" }, intended),
    false,
  );
});

test("isCurrentBackend accepts pre-vault 409 when health still reports cml-backend", async () => {
  const { exported } = loadMainModule();
  const server = http.createServer((request, response) => {
    if (request.url === "/api/v1/system/backend-identity") {
      response.writeHead(409, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: "Vault not initialized." }));
      return;
    }
    if (request.url === "/health") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ service: "cml-backend", status: "ok" }));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    assert.equal(await exported.isCurrentBackend(`http://127.0.0.1:${port}`, "expected-token"), true);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("startup failure uses the packaged repair document and passes safe structured state", async () => {
  const { exported } = loadMainModule();
  let loadedFile = "";
  let loadedOptions = null;
  const window = {
    loadFile: async (filePath, options) => {
      loadedFile = filePath;
      loadedOptions = options;
    },
  };

  await exported.loadStartupFailure(window, new Error("backend boot failed"));

  assert.equal(loadedFile, path.join(__dirname, "repair.html"));
  const state = JSON.parse(loadedOptions.query.state);
  assert.equal(state.heading, "Vault could not open.");
  assert.equal(state.detail, "The local service did not start.");
  assert.equal(state.showFields, true);
  assert.match(state.diagnosticText, /backend-stderr\.log/);
});

test("packaged static asset server returns 400 for malformed encoded paths", async () => {
  const { exported } = loadMainModule();
  const clientDir = makeTempDir("cml-client-");

  const response = await exported.tryServeStaticAsset(clientDir, "/assets/%E0%A4%A");

  assert.equal(response?.status, 400);
  assert.match(String(response?.body), /bad request/i);
});

test("packaged static asset server serves bundled brand assets", async () => {
  const { exported } = loadMainModule();
  const clientDir = makeTempDir("cml-client-");
  const brandDir = path.join(clientDir, "brand");
  fs.mkdirSync(brandDir, { recursive: true });
  fs.writeFileSync(path.join(brandDir, "Container.svg"), "<svg></svg>");

  const response = await exported.tryServeStaticAsset(clientDir, "/brand/Container.svg");

  assert.equal(response?.status, 200);
  assert.equal(response?.headers["content-type"], "image/svg+xml");
  assert.equal(String(response?.body), "<svg></svg>");
});

test("startup progress loads a small packaged document that references the onboarding wordmark", async () => {
  const { exported } = loadMainModule();
  const root = makeTempDir("cml-startup-brand-large-");
  const electronDir = path.join(root, "electron");
  fs.mkdirSync(electronDir, { recursive: true });
  const startupPath = path.join(electronDir, "startup.html");
  fs.copyFileSync(path.join(__dirname, "startup.html"), startupPath);
  let loadedFile = "";
  const window = {
    loadFile: async (filePath) => {
      loadedFile = filePath;
    },
  };

  await exported.loadStartupProgress(window, electronDir);

  assert.equal(loadedFile, startupPath);
  const html = fs.readFileSync(startupPath, "utf8");
  assert.ok(html.length < 20_000, `startup document was unexpectedly large: ${html.length}`);
  assert.match(html, /\.\.\/dist\/client\/brand\/Container\.svg/);
  assert.match(html, /vault-static-window-controls/);
  assert.match(html, /static-window-chrome\.js/);
  assert.doesNotMatch(html, /data:image\/svg\+xml;base64/);
  assert.doesNotMatch(html, /brand-fallback/);
  assert.equal((html.match(/alt="Vault"/g) || []).length, 1);
});

test("startup progress uses the branded repair page when its document is missing", async () => {
  const { exported } = loadMainModule();
  const emptyRoot = makeTempDir("cml-startup-brand-empty-");
  const electronDir = path.join(emptyRoot, "electron");
  fs.mkdirSync(electronDir, { recursive: true });
  fs.copyFileSync(path.join(__dirname, "repair.html"), path.join(electronDir, "repair.html"));
  let loadedFile = "";
  let loadedOptions = null;
  const window = {
    loadFile: async (filePath, options) => {
      loadedFile = filePath;
      loadedOptions = options;
    },
  };

  await exported.loadStartupProgress(window, electronDir);

  assert.equal(loadedFile, path.join(electronDir, "repair.html"));
  const state = JSON.parse(loadedOptions.query.state);
  assert.equal(state.heading, "Vault could not open.");
  assert.equal(state.guidanceTitle, "Reinstall Vault.");
});

test("startup progress keeps its last-resort page small and free of legacy artwork", async () => {
  const { exported } = loadMainModule();
  const emptyRoot = makeTempDir("cml-startup-all-missing-");
  let loadedUrl = "";
  const window = {
    loadURL: async (url) => {
      loadedUrl = url;
    },
  };

  await exported.loadStartupProgress(window, path.join(emptyRoot, "electron"));

  assert.match(loadedUrl, /^data:text\/html;charset=utf-8,/);
  assert.ok(loadedUrl.length < 20_000, `fallback startup URL was unexpectedly large: ${loadedUrl.length}`);
  const html = decodeURIComponent(loadedUrl.split(",", 2)[1]);
  assert.match(html, /<h1>Vault<\/h1>/);
  assert.doesNotMatch(html, /data:image|startup-brand-logo/);
});

test("desktop runtime logging bounds oversized URL and stack details", () => {
  const { exported } = loadMainModule();
  const oversized = `data:text/html,${"x".repeat(20_000)}`;

  const truncated = exported.truncateDesktopLogValue(oversized, 1000);

  assert.ok(truncated.length < 1100);
  assert.match(truncated, /^data:text\/html,/);
  assert.match(truncated, /\[truncated \d+ characters\]$/);
});

test("verifyRendererUp succeeds when the packaged renderer responds", async () => {
  const { exported } = loadMainModule();
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end("<!doctype html><title>ok</title>");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    await exported.verifyRendererUp(`http://127.0.0.1:${port}/`, 2000);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("verifyRendererUp accepts redirect responses from the packaged router", async () => {
  const { exported } = loadMainModule();
  const server = http.createServer((_request, response) => {
    response.writeHead(307, { location: "/onboarding" });
    response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    await exported.verifyRendererUp(`http://127.0.0.1:${port}/`, 2000);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("renderer failure uses the packaged repair document with retry diagnostics", async () => {
  const { exported } = loadMainModule();
  let loadedFile = "";
  let loadedOptions = null;
  const window = {
    loadFile: async (filePath, options) => {
      loadedFile = filePath;
      loadedOptions = options;
    },
  };

  await exported.loadRendererFailure(window, new Error("renderer not available"));

  assert.equal(loadedFile, path.join(__dirname, "repair.html"));
  const state = JSON.parse(loadedOptions.query.state);
  assert.equal(state.heading, "Vault could not open.");
  assert.equal(state.detail, "The app interface did not finish loading.");
  assert.doesNotMatch(state.detail, /renderer/i);
  assert.match(state.diagnosticText, /desktop-runtime\.log/);
});

test("waitForBackend fails fast when the backend child exits before readiness", async () => {
  const { exported } = loadMainModule();
  const child = new EventEmitter();
  child.exitCode = null;
  child.signalCode = null;

  setTimeout(() => {
    child.exitCode = 1;
    child.emit("close", 1, null);
  }, 20);

  const started = Date.now();
  await assert.rejects(
    exported.waitForBackend("http://127.0.0.1:65530", "expected-token", 2000, { stderr: "stderr.log" }, child),
    /exit_code=1/,
  );
  assert.ok(Date.now() - started < 1000);
});

test("resolvePackagedServerEntry falls back to dist/server/server.js when index.js is absent", async () => {
  const { exported } = loadMainModule();
  const tempRoot = makeTempDir("cml-renderer-entry-");
  const electronDir = path.join(tempRoot, "electron");
  const serverDir = path.join(tempRoot, "dist", "server");
  fs.mkdirSync(electronDir, { recursive: true });
  fs.mkdirSync(serverDir, { recursive: true });
  fs.writeFileSync(path.join(serverDir, "server.js"), "export default {};\n", "utf8");

  const resolved = await exported.resolvePackagedServerEntry(electronDir);
  assert.equal(resolved, path.join(electronDir, "../dist/server/server.js"));
});
