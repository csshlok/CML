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
    "\nmodule.exports = { repairActionForPhase, isAllowedExternalUrl, isCurrentBackend, setActiveVaultPath, getActiveVaultPath, collectSupportedFiles, findOpenPort, __setMainWindow: (value) => { mainWindow = value; } };";

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
    process,
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
