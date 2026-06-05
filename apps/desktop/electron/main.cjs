const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require("electron");
const { spawn } = require("node:child_process");
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { createTokenStore, getOrCreateToken } = require("./token-store.cjs");

const isDev = !app.isPackaged;
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";
const apiPrefix = process.env.CML_API_PREFIX || "/api/v1";
let backendProcess = null;
let backendUrl = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL || null;
let backendApiToken = process.env.CML_API_TOKEN || null;
let backendTokenStore = null;
let rendererServer = null;
let rendererUrl = null;
let vaultLockOverrideOnce = false;
const supportedSourceExtensions = new Set([
  ".aac", ".asc", ".bat", ".bmp", ".c", ".cpp", ".cs", ".csv", ".css", ".docx",
  ".flac", ".gif", ".go", ".htm", ".html", ".java", ".jpeg", ".jpg", ".js",
  ".json", ".jsonl", ".jsx", ".kt", ".log", ".lua", ".m4a", ".markdown", ".md",
  ".mov", ".mp3", ".mp4", ".ogg", ".pdf", ".php", ".png", ".ps1", ".py", ".rb",
  ".rs", ".rtf", ".sh", ".sql", ".swift", ".text", ".tif", ".tiff", ".toml",
  ".ts", ".tsv", ".tsx", ".txt", ".wav", ".webm", ".webp", ".xml", ".yaml", ".yml",
]);
const supportedOpenExtensions = new Set([...supportedSourceExtensions, ".png", ".jpg", ".jpeg", ".webp", ".gif"]);
const skippedFolderNames = new Set([".git", "node_modules", ".venv", "dist", "build"]);

let mainWindow = null;

function writeDesktopRuntimeLog(message, error = null) {
  try {
    const logPath = path.join(app.getPath("userData"), "desktop-runtime.log");
    const detail = error && (error.stack || error.message) ? `\n${error.stack || error.message}` : "";
    fsSync.appendFileSync(logPath, `${new Date().toISOString()} ${message}${detail}\n`, "utf8");
  } catch {
    // Startup logging must never become the reason the app fails to open.
  }
}

process.on("uncaughtException", (error) => {
  writeDesktopRuntimeLog("uncaughtException", error);
});

process.on("unhandledRejection", (error) => {
  writeDesktopRuntimeLog("unhandledRejection", error instanceof Error ? error : new Error(String(error)));
});

async function createWindow() {
  let startupError = null;
  try {
    backendUrl = await ensureBackend();
  } catch (error) {
    startupError = error;
  }
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "Vault",
    backgroundColor: "#fbfaf6",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = window;

  window.once("ready-to-show", () => {
    window.setTitle("Vault");
    window.show();
  });

  window.on("page-title-updated", (event) => {
    event.preventDefault();
    window.setTitle("Vault");
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  if (isDev) {
    if (startupError) {
      await loadStartupFailure(window, startupError);
      return;
    }
    const url = new URL(devUrl);
    if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
    window.loadURL(url.toString());
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    if (startupError) {
      await loadStartupFailure(window, startupError);
      return;
    }
    rendererUrl = rendererUrl || await startPackagedRendererServer();
    const url = new URL(rendererUrl);
    if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
    window.loadURL(url.toString());
  }
}

async function loadStartupFailure(window, error) {
  const status = await readStartupStatus();
  const detail = status?.message || error?.message || "Vault could not start its local backend.";
  const phase = status?.phase || "startup_failed";
  const action = repairActionForPhase(phase);
  const diagnosticText = [
    `Phase: ${phase}`,
    `Message: ${detail}`,
    `Data directory: ${status?.data_dir || "Unknown"}`,
    `Database: ${status?.database_path || "Unknown"}`,
    `Startup status: ${getStartupStatusPath()}`,
  ].join("\n");
  const html = `
    <!doctype html>
    <meta charset="utf-8" />
    <title>Vault startup issue</title>
    <body style="margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#fbfaf6;color:#1f1a17;">
      <main style="max-width:760px;margin:10vh auto;padding:32px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:28px;">
          <div style="width:32px;height:32px;border:1px solid #ded6cc;border-radius:8px;display:grid;place-items:center;background:#fffdf9;">V</div>
          <div>
            <div style="font-weight:650;font-size:14px;">Vault</div>
            <div style="font-size:12px;color:#7c6f65;">Startup repair</div>
          </div>
        </div>
        <h1 style="font-size:30px;line-height:1.15;margin:0 0 12px;">Vault needs attention before it can open.</h1>
        <p style="line-height:1.65;color:#5f524b;margin:0;max-width:620px;">${escapeHtml(detail)}</p>
        <div style="margin-top:22px;padding:16px;border:1px solid #d7cfc5;border-radius:8px;background:#fffdf9;">
          <div style="font-weight:600;font-size:14px;">${escapeHtml(action.title)}</div>
          <div style="margin-top:6px;font-size:13px;line-height:1.55;color:#5f524b;">${escapeHtml(action.body)}</div>
        </div>
        <dl style="margin-top:18px;padding:16px;border:1px solid #ded6cc;border-radius:8px;background:#fff;">
          <dt style="font-size:12px;color:#8b7d72;">Phase</dt>
          <dd style="margin:4px 0 12px;">${escapeHtml(phase)}</dd>
          <dt style="font-size:12px;color:#8b7d72;">Data directory</dt>
          <dd style="margin:4px 0 12px;word-break:break-all;">${escapeHtml(status?.data_dir || "Unknown")}</dd>
          <dt style="font-size:12px;color:#8b7d72;">Database</dt>
          <dd style="margin:4px 0 0;word-break:break-all;">${escapeHtml(status?.database_path || "Unknown")}</dd>
        </dl>
        <div style="display:flex;gap:10px;margin-top:22px;flex-wrap:wrap;">
          <button onclick="location.reload()" style="height:36px;padding:0 14px;border:0;border-radius:8px;background:#765f4d;color:#fff;font-weight:600;">Try again</button>
          ${phase === "vault_lock_failed" ? '<button onclick="window.cmlDesktop?.openVaultAnyway?.()" style="height:36px;padding:0 14px;border:1px solid #9b6a4f;border-radius:8px;background:#fff7ed;color:#7c2d12;font-weight:600;">Open anyway</button>' : ""}
          <button onclick="navigator.clipboard?.writeText(${JSON.stringify(diagnosticText)}).then(()=>this.textContent='Copied details').catch(()=>this.textContent='Copy failed')" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Copy details</button>
          <button onclick="window.close()" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Close Vault</button>
        </div>
      </main>
    </body>`;
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

function repairActionForPhase(phase) {
  if (phase === "integrity_check_failed") {
    return {
      title: "The vault database did not pass its health check.",
      body: "Do not keep retrying if this repeats. The next repair pass should export diagnostics and offer backup or restore options before any write recovery.",
    };
  }
  if (phase === "schema_check_failed") {
    return {
      title: "The vault schema or migration state is incomplete.",
      body: "Vault stopped before accepting traffic so it does not mutate a half-migrated database.",
    };
  }
  if (phase === "vault_lock_failed") {
    return {
      title: "Another Vault process may own this vault.",
      body: "Close other Vault windows before retrying. Opening the same vault twice can corrupt local data.",
    };
  }
  return {
    title: "The local backend did not reach a ready state.",
    body: "Retry once. If it repeats, keep this screen open and use the shown path when collecting diagnostics.",
  };
}

async function readStartupStatus() {
  try {
    const raw = await fs.readFile(getStartupStatusPath(), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function getStartupStatusPath() {
  return path.join(app.getPath("userData"), "startup-status.json");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();
writeDesktopRuntimeLog(`main loaded; packaged=${app.isPackaged}; singleInstance=${gotSingleInstanceLock}`);

if (!gotSingleInstanceLock) {
  writeDesktopRuntimeLog("single-instance lock unavailable; quitting");
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
      const requestedVaultArg = argv.find((arg) => arg.startsWith("--vault="));
      if (requestedVaultArg) {
        dialog.showMessageBox(mainWindow, {
          type: "info",
          title: "Vault is already open",
          message: "Vault is already open.",
          detail: "Close the current vault before opening another.",
        });
      }
    }
  });
}

if (gotSingleInstanceLock) {
  app.whenReady().then(() => {
    ipcMain.handle("cml:open-path", async (_event, targetPath) => {
      if (!(await isSafeOpenPath(targetPath))) return false;
      const error = await shell.openPath(targetPath);
      return error.length === 0;
    });

    ipcMain.handle("cml:show-item-in-folder", async (_event, targetPath) => {
      if (!(await isExistingLocalPath(targetPath))) return false;
      shell.showItemInFolder(targetPath);
      return true;
    });

    ipcMain.handle("cml:select-source-files", async () => {
      const result = await dialog.showOpenDialog({
        title: "Add sources",
        properties: ["openFile", "multiSelections"],
        filters: [
        {
          name: "Vault sources",
          extensions: [
            "txt", "md", "markdown", "docx", "pdf", "csv", "json", "jsonl", "html", "htm",
            "xml", "yaml", "yml", "rtf", "log", "py", "js", "ts", "tsx", "jsx", "go", "rs",
            "java", "cs", "cpp", "c", "png", "jpg", "jpeg", "webp", "gif", "tif", "tiff",
            "mp3", "wav", "m4a", "flac", "mp4", "mov", "webm",
          ],
        },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (result.canceled) return [];
      return result.filePaths;
    });

    ipcMain.handle("cml:select-source-folders", async () => {
      const result = await dialog.showOpenDialog({
        title: "Add synced folder",
        properties: ["openDirectory", "multiSelections"],
      });
      if (result.canceled) return [];
      return result.filePaths;
    });

    ipcMain.handle("cml:select-embedding-folder", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose embedding model folder",
        properties: ["openDirectory"],
      });
      if (result.canceled) return null;
      return result.filePaths[0] ?? null;
    });

    ipcMain.handle("cml:select-model-folder", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose model checkpoint folder",
        properties: ["openDirectory"],
      });
      if (result.canceled) return null;
      return result.filePaths[0] ?? null;
    });

    ipcMain.handle("cml:select-vault-folder", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose vault location",
        properties: ["openDirectory", "createDirectory"],
      });
      if (result.canceled) return null;
      return result.filePaths[0] ?? null;
    });

    ipcMain.handle("cml:list-supported-files", async (_event, targetPaths) => {
      if (!Array.isArray(targetPaths)) return [];
      const files = [];
      for (const targetPath of targetPaths) {
        if (typeof targetPath !== "string" || targetPath.length === 0) continue;
        await collectSupportedFiles(targetPath, files);
        if (files.length >= 500) break;
      }
      return files.slice(0, 500);
    });

    ipcMain.handle("cml:select-cover-image", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose card image",
        properties: ["openFile"],
        filters: [
          { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (result.canceled) return null;
      return result.filePaths[0];
    });

    ipcMain.handle("cml:get-backend-url", async () => backendUrl);
    ipcMain.handle("cml:get-backend-token", async () => getBackendApiToken());
    ipcMain.handle("cml:open-vault-anyway", async () => {
      const confirmation = await dialog.showMessageBox(mainWindow, {
        type: "warning",
        buttons: ["Cancel", "Open once"],
        defaultId: 0,
        cancelId: 0,
        title: "Open locked vault?",
        message: "Open this vault only if every other Vault window or backend process is closed.",
        detail: "This bypasses the lock once. Opening the same vault from two processes can corrupt local data.",
      });
      if (confirmation.response !== 1) return null;
      vaultLockOverrideOnce = true;
      await restartBackend();
      if (mainWindow && backendUrl) {
        const url = isDev ? new URL(devUrl) : new URL(rendererUrl || await startPackagedRendererServer());
        url.searchParams.set("backendUrl", backendUrl);
        await mainWindow.loadURL(url.toString());
      }
      return backendUrl;
    });
    ipcMain.handle("cml:set-active-vault-folder", async (_event, targetPath) => {
      if (typeof targetPath !== "string" || targetPath.trim().length === 0) return null;
      await setActiveVaultPath(targetPath);
      await restartBackend();
      return backendUrl;
    });

    void createWindow().catch((error) => {
      writeDesktopRuntimeLog("createWindow failed", error);
      app.quit();
    });

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        void createWindow().catch((error) => {
          writeDesktopRuntimeLog("createWindow failed during activate", error);
          app.quit();
        });
      }
    });
  });
}

async function ensureBackend() {
  const explicitBackend = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL;
  const token = await getBackendApiToken();
  const existing = explicitBackend ? await findExistingCurrentBackend(token) : null;
  if (existing) return existing;

  const activeVaultPath = await getActiveVaultPath();
  const backendMode = activeVaultPath ? "full_vault" : "pre_vault";
  const dataDir = activeVaultPath
    ? path.join(activeVaultPath, ".vault")
    : path.join(app.getPath("userData"), "pre-vault");
  const databasePath = path.join(dataDir, "cml.sqlite3");
  const startupStatusPath = getStartupStatusPath();
  const port = await findOpenPort(7343, 7355);
  const rootDir = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const pythonPath = isDev
    ? path.join(rootDir, ".venv", "Scripts", "python.exe")
    : path.join(process.resourcesPath, "python-runtime", "Scripts", "python.exe");
  const expertPythonPath = isDev
    ? path.join(rootDir, ".venv-lora", "Scripts", "python.exe")
    : path.join(process.resourcesPath, "expert-python-runtime", "Scripts", "python.exe");
  const pythonCommand = await pathExists(pythonPath) ? pythonPath : "python";
  const expertPythonCommand = await pathExists(expertPythonPath) ? expertPythonPath : pythonCommand;
  backendProcess = spawn(
    pythonCommand,
    ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: rootDir,
      env: {
        ...process.env,
        CML_API_PREFIX: apiPrefix,
        CML_API_TOKEN: token,
        CML_BACKEND_MODE: backendMode,
        CML_DATA_DIR: dataDir,
        CML_DATABASE_PATH: databasePath,
        CML_STARTUP_STATUS_PATH: startupStatusPath,
        CML_VAULT_LOCK_OVERRIDE: vaultLockOverrideOnce ? "open_anyway" : "",
        CML_LORA_RUNTIME_PYTHON: expertPythonCommand,
        PLAYWRIGHT_BROWSERS_PATH: isDev
          ? process.env.PLAYWRIGHT_BROWSERS_PATH || ""
          : path.join(process.resourcesPath, "ms-playwright"),
      },
      windowsHide: true,
      stdio: "ignore",
    },
  );
  vaultLockOverrideOnce = false;
  backendProcess.unref();
  const startedUrl = `http://127.0.0.1:${port}`;
  await waitForBackend(startedUrl, token, 12000);
  return startedUrl;
}

async function restartBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
  backendUrl = null;
  backendUrl = await ensureBackend();
  if (mainWindow && backendUrl) {
    mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
  }
}

function getActiveVaultConfigPath() {
  return path.join(app.getPath("userData"), "active-vault.json");
}

async function getActiveVaultPath() {
  try {
    const raw = await fs.readFile(getActiveVaultConfigPath(), "utf8");
    const parsed = JSON.parse(raw);
    if (typeof parsed.path === "string" && parsed.path.trim()) return parsed.path;
  } catch {
    return null;
  }
  return null;
}

async function setActiveVaultPath(targetPath) {
  await fs.mkdir(path.dirname(getActiveVaultConfigPath()), { recursive: true });
  await fs.mkdir(path.join(targetPath, ".vault"), { recursive: true });
  await fs.writeFile(
    getActiveVaultConfigPath(),
    JSON.stringify({ path: targetPath, updated_at: new Date().toISOString() }, null, 2),
    "utf8",
  );
}

async function getBackendApiToken() {
  if (backendApiToken) return backendApiToken;
  backendTokenStore = backendTokenStore || createTokenStore(app.getPath("userData"), safeStorage);
  backendApiToken = await getOrCreateToken(backendTokenStore);
  return backendApiToken;
}

async function startPackagedRendererServer() {
  if (rendererServer && rendererUrl) return rendererUrl;
  const port = await findOpenPort(5174, 5190);
  const clientDir = path.join(__dirname, "../dist/client");
  const serverEntry = path.join(__dirname, "../dist/server/index.js");
  const workerModule = await import(pathToFileUrl(serverEntry));
  const worker = workerModule.default;

  rendererServer = http.createServer(async (request, response) => {
    try {
      const parsed = new URL(request.url || "/", `http://127.0.0.1:${port}`);
      const staticResponse = await tryServeStaticAsset(clientDir, parsed.pathname);
      if (staticResponse) {
        writeNodeResponse(response, staticResponse.status, staticResponse.headers, staticResponse.body);
        return;
      }

      const target = `http://127.0.0.1:${port}${request.url || "/"}`;
      const webRequest = new Request(target, {
        method: request.method,
        headers: request.headers,
      });
      const webResponse = await worker.fetch(webRequest, {}, {});
      const body = Buffer.from(await webResponse.arrayBuffer());
      writeNodeResponse(response, webResponse.status, Object.fromEntries(webResponse.headers), body);
    } catch (error) {
      response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end(error instanceof Error ? error.stack || error.message : String(error));
    }
  });

  await new Promise((resolve, reject) => {
    rendererServer.once("error", reject);
    rendererServer.listen(port, "127.0.0.1", resolve);
  });
  rendererUrl = `http://127.0.0.1:${port}/`;
  return rendererUrl;
}

async function tryServeStaticAsset(clientDir, pathname) {
  const safePathname = decodeURIComponent(pathname).replace(/^\/+/, "");
  if (!safePathname || safePathname.includes("..")) return null;
  if (!(safePathname.startsWith("assets/") || safePathname === "favicon.svg")) return null;
  const target = path.join(clientDir, safePathname);
  if (!target.startsWith(clientDir)) return null;
  try {
    const body = await fs.readFile(target);
    return {
      status: 200,
      headers: { "content-type": contentTypeForPath(target) },
      body,
    };
  } catch {
    return {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
      body: Buffer.from("Not found"),
    };
  }
}

function writeNodeResponse(response, status, headers, body) {
  response.writeHead(status, headers);
  response.end(body);
}

function contentTypeForPath(targetPath) {
  const ext = path.extname(targetPath).toLowerCase();
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".json") return "application/json; charset=utf-8";
  return "application/octet-stream";
}

function pathToFileUrl(targetPath) {
  return `file:///${targetPath.replace(/\\/g, "/").replace(/^([a-zA-Z]):/, "$1:")}`;
}

async function findExistingCurrentBackend(token) {
  const candidates = [
    process.env.VITE_CML_BACKEND_URL,
    process.env.CML_BACKEND_URL,
    "http://127.0.0.1:7343",
    "http://127.0.0.1:7342",
  ].filter(Boolean);
  for (const candidate of [...new Set(candidates)]) {
    if (await isCurrentBackend(candidate, token)) return candidate;
  }
  return null;
}

function isCurrentBackend(url, token) {
  if (!token) return Promise.resolve(false);
  return httpJson(`${url}${apiPrefix}/system/backend-identity`, 1200, token)
    .then((identity) => (
      identity &&
      identity.service === "cml-backend" &&
      identity.api_prefix === apiPrefix
    ))
    .catch(() => false);
}

async function waitForBackend(url, token, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isCurrentBackend(url, token)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Backend did not start at ${url}`);
}

function httpJson(url, timeoutMs, token = "") {
  return new Promise((resolve, reject) => {
    const headers = token ? { "x-cml-api-token": token } : {};
    const request = http.get(url, { timeout: timeoutMs, headers }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`HTTP ${response.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on("timeout", () => {
      request.destroy(new Error("Timed out"));
    });
    request.on("error", reject);
  });
}

async function findOpenPort(start, end) {
  for (let port = start; port <= end; port += 1) {
    if (await isPortOpen(port)) return port;
  }
  throw new Error(`No open backend port between ${start} and ${end}`);
}

function isPortOpen(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, "127.0.0.1");
  });
}

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function collectSupportedFiles(targetPath, files) {
  let stat;
  try {
    stat = await fs.lstat(targetPath);
  } catch {
    return;
  }
  if (stat.isSymbolicLink()) return;

  if (stat.isFile()) {
    if (supportedSourceExtensions.has(path.extname(targetPath).toLowerCase())) {
      files.push(targetPath);
    }
    return;
  }

  if (!stat.isDirectory()) return;
  const folderName = path.basename(targetPath);
  if (skippedFolderNames.has(folderName)) return;

  let entries;
  try {
    entries = await fs.readdir(targetPath, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    if (files.length >= 500) return;
    if (entry.name.startsWith(".") && entry.name !== ".obsidian") continue;
    await collectSupportedFiles(path.join(targetPath, entry.name), files);
  }
}

function isAllowedExternalUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" || parsed.protocol === "mailto:";
  } catch {
    return false;
  }
}

async function isExistingLocalPath(targetPath) {
  if (typeof targetPath !== "string" || targetPath.length === 0 || targetPath.length > 4096) {
    return false;
  }
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(targetPath) && !/^[a-zA-Z]:[\\/]/.test(targetPath)) {
    return false;
  }
  try {
    await fs.lstat(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function isSafeOpenPath(targetPath) {
  if (!(await isExistingLocalPath(targetPath))) return false;
  return supportedOpenExtensions.has(path.extname(targetPath).toLowerCase());
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (rendererServer) {
    rendererServer.close();
  }
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
});
