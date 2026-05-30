const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const isDev = !app.isPackaged;
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";
let backendProcess = null;
let backendUrl = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL || null;
let backendApiToken = process.env.CML_API_TOKEN || null;
let rendererServer = null;
let rendererUrl = null;
const supportedSourceExtensions = new Set([".txt", ".md", ".markdown", ".docx", ".pdf"]);
const supportedOpenExtensions = new Set([...supportedSourceExtensions, ".png", ".jpg", ".jpeg", ".webp", ".gif"]);
const skippedFolderNames = new Set([".git", "node_modules", ".venv", "dist", "build"]);

let mainWindow = null;

async function createWindow() {
  backendUrl = await ensureBackend();
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
    const url = new URL(devUrl);
    if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
    window.loadURL(url.toString());
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    rendererUrl = rendererUrl || await startPackagedRendererServer();
    const url = new URL(rendererUrl);
    if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
    window.loadURL(url.toString());
  }
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
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
          { name: "Documents", extensions: ["txt", "md", "markdown", "docx", "pdf"] },
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

    void createWindow();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        void createWindow();
      }
    });
  });
}

async function ensureBackend() {
  const existing = await findExistingCurrentBackend();
  if (existing) return existing;

  const token = await getBackendApiToken();
  const port = await findOpenPort(7343, 7355);
  const rootDir = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const pythonPath = isDev
    ? path.join(rootDir, ".venv", "Scripts", "python.exe")
    : path.join(process.resourcesPath, "python-runtime", "Scripts", "python.exe");
  const pythonCommand = await pathExists(pythonPath) ? pythonPath : "python";
  backendProcess = spawn(
    pythonCommand,
    ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: rootDir,
      env: {
        ...process.env,
        CML_API_PREFIX: process.env.CML_API_PREFIX || "/api/v1",
        CML_API_TOKEN: token,
      },
      windowsHide: true,
      stdio: "ignore",
    },
  );
  backendProcess.unref();
  const startedUrl = `http://127.0.0.1:${port}`;
  await waitForBackend(startedUrl, 12000);
  return startedUrl;
}

async function getBackendApiToken() {
  if (backendApiToken) return backendApiToken;
  const tokenPath = getBackendTokenPath();
  try {
    const token = (await fs.readFile(tokenPath, "utf8")).trim();
    if (token.length >= 32) {
      backendApiToken = token;
      return token;
    }
  } catch {
    // Missing or unreadable token files are regenerated locally.
  }
  backendApiToken = crypto.randomBytes(32).toString("base64url");
  await fs.mkdir(path.dirname(tokenPath), { recursive: true });
  await fs.writeFile(tokenPath, backendApiToken, { encoding: "utf8", mode: 0o600 });
  return backendApiToken;
}

function getBackendTokenPath() {
  return path.join(app.getPath("userData"), "backend-token");
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

async function findExistingCurrentBackend() {
  const candidates = [
    process.env.VITE_CML_BACKEND_URL,
    process.env.CML_BACKEND_URL,
    "http://127.0.0.1:7343",
    "http://127.0.0.1:7342",
  ].filter(Boolean);
  for (const candidate of [...new Set(candidates)]) {
    if (await isCurrentBackend(candidate)) return candidate;
  }
  return null;
}

function isCurrentBackend(url) {
  return httpJson(`${url}/openapi.json`, 1200)
    .then((spec) => {
      const paths = spec && spec.paths ? spec.paths : {};
      return Boolean(
        paths["/api/v1/chat/context/stream"] &&
        paths["/api/v1/bridge/settings"] &&
        paths["/api/v1/models/embeddings/configure"],
      );
    })
    .catch(() => false);
}

async function waitForBackend(url, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isCurrentBackend(url)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Backend did not start at ${url}`);
}

function httpJson(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
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
