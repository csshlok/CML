const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");

function loadMainModule() {
  const filePath = path.join(__dirname, "main.cjs");
  const source =
    fs.readFileSync(filePath, "utf8") +
    "\nmodule.exports = { repairActionForPhase, isAllowedExternalUrl, isCurrentBackend, rendererSecurityHeaders, sanitizeRendererBody, setActiveVaultPath, getActiveVaultPath, collectSupportedFiles, findOpenPort, loadStartupFailure, loadRendererFailure, tryServeStaticAsset, verifyRendererUp, resolvePackagedServerEntry, __setMainWindow: (value) => { mainWindow = value; } };";

  const appHandlers = {};
  const dialogCalls = [];
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "cml-electron-"));
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
    },
    ipcMain: {
      handle: () => {},
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

  assert.match(integrity.title, /health check/i);
  assert.match(lock.body, /corrupt|close other vault windows/i);
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
  const targetRoot = fs.mkdtempSync(path.join(os.tmpdir(), "cml-vault path-"));
  const vaultPath = path.join(targetRoot, "研究 Vault 😀", "nested folder");

  await exported.setActiveVaultPath(vaultPath);
  const stored = await exported.getActiveVaultPath();

  assert.equal(stored, vaultPath);
  assert.equal(fs.existsSync(path.join(vaultPath, ".vault")), true);
});

test("collectSupportedFiles skips symlinks and build folders", async () => {
  const { exported } = loadMainModule();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cml-collect-"));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "cml-outside-"));
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

test("startup failure page renders a real copy button instead of malformed inline HTML", async () => {
  const { exported } = loadMainModule();
  let loadedUrl = "";
  const window = {
    loadURL: async (url) => {
      loadedUrl = url;
    },
  };

  await exported.loadStartupFailure(window, new Error("backend boot failed"));

  const html = decodeURIComponent(String(loadedUrl).replace(/^data:text\/html;charset=utf-8,/, ""));
  assert.match(html, /id="copy-details-button"/);
  assert.match(html, /addEventListener\("click"/);
  assert.match(html, /window\.cmlDesktop\?\.copyText/);
  assert.match(html, /window\.cmlDesktop\?\.retryStartup/);
  assert.match(html, /backend-stderr\.log/);
  assert.doesNotMatch(html, /this\.textContent='Copied details'/);
});

test("packaged static asset server returns 400 for malformed encoded paths", async () => {
  const { exported } = loadMainModule();
  const clientDir = fs.mkdtempSync(path.join(os.tmpdir(), "cml-client-"));

  const response = await exported.tryServeStaticAsset(clientDir, "/assets/%E0%A4%A");

  assert.equal(response?.status, 400);
  assert.match(String(response?.body), /bad request/i);
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

test("renderer failure page offers retry and copy diagnostics", async () => {
  const { exported } = loadMainModule();
  let loadedUrl = "";
  const window = {
    loadURL: async (url) => {
      loadedUrl = url;
    },
  };

  await exported.loadRendererFailure(window, new Error("renderer not available"));

  const html = decodeURIComponent(String(loadedUrl).replace(/^data:text\/html;charset=utf-8,/, ""));
  assert.match(html, /window\.cmlDesktop\?\.retryStartup/);
  assert.match(html, /window\.cmlDesktop\?\.copyText/);
  assert.match(html, /desktop-runtime\.log/);
});

test("resolvePackagedServerEntry falls back to dist/server/server.js when index.js is absent", async () => {
  const { exported } = loadMainModule();
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "cml-renderer-entry-"));
  const electronDir = path.join(tempRoot, "electron");
  const serverDir = path.join(tempRoot, "dist", "server");
  fs.mkdirSync(electronDir, { recursive: true });
  fs.mkdirSync(serverDir, { recursive: true });
  fs.writeFileSync(path.join(serverDir, "server.js"), "export default {};\n", "utf8");

  const resolved = await exported.resolvePackagedServerEntry(electronDir);
  assert.equal(resolved, path.join(electronDir, "../dist/server/server.js"));
});
