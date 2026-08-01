const { app, BrowserWindow, clipboard, dialog, ipcMain, safeStorage, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const {
  buildBackendChildEnv,
  buildMcpChildEnv,
  defaultWritableRoots,
  isPathWithinRoot,
  packageLayoutAudit,
  pathsOverlap,
  resolvePackagedHelperPaths,
  verifyHelperManifestCached,
} = require("./helper-integrity.cjs");
const { createTokenStore, getOrCreateToken } = require("./token-store.cjs");
const {
  createRuntimeDescriptor,
  removeRuntimeDescriptor,
  runtimeDescriptorPath,
  writeRuntimeDescriptor,
} = require("./runtime-descriptor.cjs");
const {
  atomicWriteJson,
  readSetupState,
  resetSetupState,
  updateSetupState,
  writeSetupState,
} = require("./setup-state.cjs");
const {
  attachWindowStateEvents,
  registerWindowControlHandlers,
} = require("./window-controls.cjs");
const { TunnelManager } = require("./tunnel-manager.cjs");
const { resolveMcpFeatureFlags } = require("./mcp-feature-flags.cjs");
const {
  getLauncherStatus: getOdinLauncherStatus,
  installLauncher: installOdinLauncher,
  installWithUv: installOdinWithUv,
  resolveOdinBinDir,
  runLauncher: runOdinLauncher,
} = require("./odin-launcher.cjs");

const isDev = !app.isPackaged;
const desktopProcessStartedAt = Date.now();
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";
const apiPrefix = normalizeApiPrefix(process.env.CML_API_PREFIX);
const mcpFeatureFlags = resolveMcpFeatureFlags(process.env);
let backendProcess = null;
let backendUrl = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL || null;
let backendApiToken = process.env.CML_API_TOKEN || null;
let backendTokenStore = null;
let rendererServer = null;
let rendererUrl = null;
let vaultLockOverrideOnce = false;
let packagedRuntimeVerification = null;
let backendStdoutStream = null;
let backendStderrStream = null;
let rendererReadyPath = null;
let pendingActiveVaultPath = null;
let odinRuntimeDescriptorPath = null;
let tunnelManager = null;
let stopBackendDependents = stopManagedRuntimeBeforeBackendStop;
let shutdownPromise = null;
let shutdownComplete = false;
const desktopRuntimeLogValueLimit = 8000;

function normalizeApiPrefix(value) {
  const raw = String(value || "/api/v1").trim();
  const prefixed = raw.startsWith("/") ? raw : `/${raw}`;
  return prefixed.replace(/\/+$/, "") || "/api/v1";
}
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

function truncateDesktopLogValue(value, limit = desktopRuntimeLogValueLimit) {
  const text = String(value || "");
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}\n[truncated ${text.length - limit} characters]`;
}

function writeDesktopRuntimeLog(message, error = null) {
  try {
    const logPath = getDesktopRuntimeLogPath();
    const safeMessage = truncateDesktopLogValue(message);
    const detailValue = error && (error.stack || error.message) ? error.stack || error.message : "";
    const detail = detailValue ? `\n${truncateDesktopLogValue(detailValue)}` : "";
    fsSync.appendFileSync(logPath, `${new Date().toISOString()} ${safeMessage}${detail}\n`, "utf8");
  } catch {
    // Startup logging must never become the reason the app fails to open.
  }
}

function getDesktopRuntimeLogPath() {
  return path.join(app.getPath("userData"), "desktop-runtime.log");
}

function getBackendLogPaths() {
  const userDataPath = app.getPath("userData");
  return {
    stdout: path.join(userDataPath, "backend-stdout.log"),
    stderr: path.join(userDataPath, "backend-stderr.log"),
  };
}

function closeBackendLogStreams() {
  const stdoutStream = backendStdoutStream;
  const stderrStream = backendStderrStream;
  backendStdoutStream = null;
  backendStderrStream = null;
  if (stdoutStream) {
    stdoutStream.end();
  }
  if (stderrStream) {
    stderrStream.end();
  }
}

function attachBackendLogging(childProcess, command, args) {
  const logPaths = getBackendLogPaths();
  closeBackendLogStreams();
  const stdoutStream = fsSync.createWriteStream(logPaths.stdout, { flags: "a" });
  const stderrStream = fsSync.createWriteStream(logPaths.stderr, { flags: "a" });
  backendStdoutStream = stdoutStream;
  backendStderrStream = stderrStream;
  const header = `[${new Date().toISOString()}] spawn ${command} ${args.join(" ")}\n`;
  stdoutStream.write(`\n${header}`);
  stderrStream.write(`\n${header}`);
  if (childProcess.stdout) {
    childProcess.stdout.on("data", (chunk) => {
      stdoutStream.write(chunk);
    });
  }
  if (childProcess.stderr) {
    childProcess.stderr.on("data", (chunk) => {
      stderrStream.write(chunk);
    });
  }
  childProcess.on("error", (error) => {
    writeDesktopRuntimeLog("backend process error", error);
  });
  childProcess.on("close", (code, signal) => {
    writeDesktopRuntimeLog(`backend exited; code=${code ?? "null"} signal=${signal ?? "null"}`);
    if (backendStdoutStream === stdoutStream) {
      backendStdoutStream = null;
    }
    if (backendStderrStream === stderrStream) {
      backendStderrStream = null;
    }
    stdoutStream.end();
    stderrStream.end();
  });
  return logPaths;
}

process.on("uncaughtException", (error) => {
  writeDesktopRuntimeLog("uncaughtException", error);
});

process.on("unhandledRejection", (error) => {
  writeDesktopRuntimeLog("unhandledRejection", error instanceof Error ? error : new Error(String(error)));
});

async function createWindow() {
  rendererReadyPath = null;
  const initialRendererPath = await getInitialRendererPath();
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "Vault",
    backgroundColor: "#fbfaf6",
    autoHideMenuBar: true,
    frame: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = window;
  attachWindowStateEvents(window);
  window.setMenuBarVisibility(false);

  window.once("ready-to-show", () => {
    window.setTitle("Vault");
    window.show();
    writeDesktopRuntimeLog(`startup window visible elapsed_ms=${Date.now() - desktopProcessStartedAt}`);
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
  window.webContents.on("did-finish-load", () => {
    writeDesktopRuntimeLog(`renderer did-finish-load ${window.webContents.getURL()}`);
  });
  window.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
    writeDesktopRuntimeLog(
      `renderer did-fail-load code=${errorCode} mainFrame=${isMainFrame} url=${validatedURL} description=${errorDescription}`,
    );
  });
  window.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    writeDesktopRuntimeLog(`renderer console level=${level} source=${sourceId || "unknown"} line=${line} message=${message}`);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    writeDesktopRuntimeLog(`renderer process gone reason=${details.reason} exitCode=${details.exitCode}`);
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (url.startsWith("data:text/html")) return;
    if (url === window.webContents.getURL()) return;
    event.preventDefault();
    if (isAllowedExternalUrl(url)) {
      shell.openExternal(url);
    }
  });

  await loadStartupProgress(window);
  let startupError = null;
  const packagedRendererPromise = isDev
    ? Promise.resolve({ ok: true, url: null })
    : startPackagedRendererServer().then(async (url) => {
        await verifyRendererUp(url, 10000);
        return { ok: true, url };
      }).catch((error) => ({ ok: false, error }));
  try {
    backendUrl = await ensureBackend();
  } catch (error) {
    startupError = error;
  }

  if (isDev) {
    if (startupError) {
      await loadStartupFailure(window, startupError);
      return;
    }
    const url = new URL(initialRendererPath, ensureTrailingSlash(devUrl));
    if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
    window.loadURL(url.toString());
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    if (startupError) {
      await loadStartupFailure(window, startupError);
      return;
    }
    try {
      const rendererResult = await packagedRendererPromise;
      if (!rendererResult.ok) throw rendererResult.error;
      rendererUrl = rendererUrl || rendererResult.url;
      const url = new URL(initialRendererPath, rendererUrl);
      if (backendUrl) url.searchParams.set("backendUrl", backendUrl);
      await window.loadURL(url.toString());
      await waitForRendererReady(10000);
    } catch (error) {
      writeDesktopRuntimeLog("packaged renderer failed", error);
      await loadRendererFailure(window, error);
    }
  }
}

async function loadStartupProgress(window, baseDir = __dirname) {
  const startupDocumentPath = path.join(baseDir, "startup.html");
  if (fsSync.existsSync(startupDocumentPath)) {
    await window.loadFile(startupDocumentPath);
    return;
  }
  const repairDocumentPath = path.join(baseDir, "repair.html");
  if (fsSync.existsSync(repairDocumentPath)) {
    await loadRepairDocument(window, {
      heading: "Vault could not open.",
      detail: "Some app files are missing.",
      guidanceTitle: "Reinstall Vault.",
      guidanceBody: "Your library files will stay in place.",
      diagnosticText: `Missing app file: ${displayPath(startupDocumentPath)}`,
      showFields: false,
      allowOpenAnyway: false,
    }, baseDir);
    return;
  }
  const html = `<!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="color-scheme" content="light">
        <title>Vault</title>
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #fbfaf6; color: #27211d; font-family: "Segoe UI", sans-serif; }
          main { width: min(420px, calc(100vw - 48px)); text-align: center; }
          h1 { margin: 0; font-size: 24px; letter-spacing: -.02em; }
          p { margin: 24px 0 0; color: #766b64; font-size: 14px; }
          .track { width: 100%; height: 3px; margin-top: 18px; overflow: hidden; border-radius: 999px; background: #e8e1d8; }
          .bar { width: 35%; height: 100%; border-radius: inherit; background: #27211d; animation: move 1.4s ease-in-out infinite; }
          @keyframes move { 0% { transform: translateX(-110%); } 100% { transform: translateX(390%); } }
          @media (prefers-reduced-motion: reduce) { .bar { width: 100%; animation: none; opacity: .55; } }
        </style>
      </head>
      <body>
        <main role="status" aria-live="polite">
          <h1>Vault</h1>
          <p>Opening your library…</p>
          <div class="track" aria-hidden="true"><div class="bar"></div></div>
        </main>
      </body>
    </html>`;
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

async function getInitialRendererPath() {
  const resolved = await resolveSetupLaunchState();
  return resolved.activeVaultPath && resolved.state.phase === "complete"
    ? "/home"
    : "/onboarding";
}

async function resolveSetupLaunchState() {
  const activeVaultPath = await getActiveVaultPath();
  const state = await readSetupState(app.getPath("userData"), { activeVaultPath });
  if (activeVaultPath || state.phase !== "complete") {
    return { activeVaultPath, state };
  }

  const savedVaultPath = String(state.vault?.path || "").trim();
  if (savedVaultPath && await isUsableActiveVaultPath(savedVaultPath)) {
    await setActiveVaultPath(savedVaultPath);
    return { activeVaultPath: savedVaultPath, state };
  }

  return {
    activeVaultPath: null,
    state: {
      ...state,
      phase: "recovery",
      recovery_reason: savedVaultPath ? "missing_vault_data" : "setup_state_invalid",
    },
  };
}

function ensureTrailingSlash(value) {
  return value.endsWith("/") ? value : `${value}/`;
}

function displayPath(value) {
  return String(value || "").replace(/\\/g, "/").replace(/\/{2,}/g, "/");
}

async function loadRepairDocument(window, state, baseDir = __dirname) {
  const repairDocumentPath = path.join(baseDir, "repair.html");
  if (!fsSync.existsSync(repairDocumentPath)) {
    throw new Error(`Vault repair document is missing: ${repairDocumentPath}`);
  }
  await window.loadFile(repairDocumentPath, {
    query: { state: JSON.stringify(state) },
  });
}

async function loadStartupFailure(window, error, baseDir = __dirname) {
  const status = await readStartupStatus();
  const backendLogs = getBackendLogPaths();
  const detail = status?.message || error?.message || "Vault could not start its local backend.";
  const phase = status?.phase || "startup_failed";
  const action = repairActionForPhase(phase);
  const diagnosticText = [
    `Phase: ${phase}`,
    `Message: ${detail}`,
    `Data directory: ${displayPath(status?.data_dir) || "Unknown"}`,
    `Database: ${displayPath(status?.database_path) || "Unknown"}`,
    `Startup status: ${displayPath(getStartupStatusPath())}`,
    `Backend stdout log: ${displayPath(backendLogs.stdout)}`,
    `Backend stderr log: ${displayPath(backendLogs.stderr)}`,
    `Desktop runtime log: ${displayPath(getDesktopRuntimeLogPath())}`,
  ].join("\n");
  await loadRepairDocument(window, {
    heading: "Vault could not open.",
    detail: "The local service did not start.",
    guidanceTitle: action.title,
    guidanceBody: action.body,
    phase,
    dataDirectory: displayPath(status?.data_dir) || "Unknown",
    database: displayPath(status?.database_path) || "Unknown",
    diagnosticText,
    showFields: true,
    allowOpenAnyway: phase === "vault_lock_failed",
  }, baseDir);
}

async function loadRendererFailure(window, error, baseDir = __dirname) {
  const diagnosticText = [
    "Phase: renderer_startup_failed",
    `Message: ${error?.message || "Packaged renderer did not become available."}`,
    `Renderer URL: ${rendererUrl || "Unknown"}`,
    `Startup status: ${displayPath(getStartupStatusPath())}`,
    `Backend stdout log: ${displayPath(getBackendLogPaths().stdout)}`,
    `Backend stderr log: ${displayPath(getBackendLogPaths().stderr)}`,
    `Desktop runtime log: ${displayPath(getDesktopRuntimeLogPath())}`,
  ].join("\n");
  await loadRepairDocument(window, {
    heading: "Vault could not open.",
    detail: "The app interface did not finish loading.",
    guidanceTitle: "Try opening Vault again.",
    guidanceBody: "If the same message returns, copy the details before closing Vault.",
    diagnosticText,
    showFields: false,
    allowOpenAnyway: false,
  }, baseDir);
}

function repairActionForPhase(phase) {
  if (phase === "integrity_check_failed") {
    return {
      title: "Your library needs to be checked.",
      body: "Vault stopped before making changes. Keep your current library files unchanged and copy the details.",
    };
  }
  if (phase === "schema_check_failed") {
    return {
      title: "Vault could not finish updating your library.",
      body: "Try again once. If the same message returns, copy the details.",
    };
  }
  if (phase === "vault_lock_failed") {
    return {
      title: "This library is already open.",
      body: "Close any other Vault window using this library, then try again.",
    };
  }
  return {
    title: "Vault's local service did not start.",
    body: "Try again. If the same message returns, copy the details before closing Vault.",
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
          detail: "Close the current library before opening another.",
        });
      }
    }
  });
}

if (gotSingleInstanceLock) {
  app.whenReady().then(async () => {
    registerWindowControlHandlers({ ipcMain, BrowserWindow });
    tunnelManager = new TunnelManager({
      appDataDir: app.getPath("userData"),
      safeStorage,
      launcherProvider: getMcpLauncherDescriptor,
      tunnelBinaryProvider: async () => {
        if (process.env.CML_TUNNEL_CLIENT_BINARY) {
          return path.resolve(process.env.CML_TUNNEL_CLIENT_BINARY);
        }
        return app.isPackaged
          ? resolvePackagedHelperPaths(process.resourcesPath).tunnelRuntimeClient
          : path.resolve(__dirname, "../packaging/tunnel-client/tunnel-client.exe");
      },
      environmentProvider: () => ({
        SystemRoot: process.env.SystemRoot || process.env.SYSTEMROOT || "C:\\Windows",
        ComSpec: process.env.ComSpec || process.env.COMSPEC || "C:\\Windows\\System32\\cmd.exe",
        PATHEXT: process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD",
        TEMP: process.env.TEMP || app.getPath("temp"),
        TMP: process.env.TMP || process.env.TEMP || app.getPath("temp"),
        USERPROFILE: process.env.USERPROFILE || "",
        LOCALAPPDATA: process.env.LOCALAPPDATA || "",
        APPDATA: process.env.APPDATA || "",
      }),
      onStatus: (status) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("cml:tunnel-status-changed", status);
        }
      },
    });
    await tunnelManager.initialize({
      allowAutoConnect:
        mcpFeatureFlags.chatgpt_mcp_setup && mcpFeatureFlags.secure_mcp_tunnel,
    });
    try {
      await reconcilePendingVaultDeletion();
    } catch (error) {
      writeDesktopRuntimeLog("pending vault deletion recovery failed", error);
    }
    ipcMain.handle("cml:open-external", async (_event, rawUrl) => {
      try {
        const url = new URL(String(rawUrl));
        if (url.protocol !== "https:" && url.protocol !== "http:") return false;
        await shell.openExternal(url.toString());
        return true;
      } catch {
        return false;
      }
    });

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

    ipcMain.handle("cml:select-model-checkpoint", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose a GGUF chat model",
        properties: ["openFile"],
        filters: [
          { name: "GGUF models", extensions: ["gguf"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (result.canceled) return null;
      return result.filePaths[0] ?? null;
    });

    ipcMain.handle("cml:select-vault-folder", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose library location",
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

    ipcMain.handle("cml:scan-supported-files", async (_event, targetPaths, requestedLimit = 5000) => {
      if (!Array.isArray(targetPaths)) return { files: [], truncated: false, limit: 0 };
      const limit = Math.max(1, Math.min(Number(requestedLimit) || 5000, 10000));
      const files = [];
      const state = { truncated: false };
      for (const targetPath of targetPaths) {
        if (typeof targetPath !== "string" || targetPath.length === 0) continue;
        await collectSupportedFiles(targetPath, files, limit, state);
        if (state.truncated) break;
      }
      return { files, truncated: state.truncated, limit };
    });

    ipcMain.handle("cml:select-cover-image", async () => {
      const result = await dialog.showOpenDialog({
        title: "Choose profile photo",
        properties: ["openFile"],
        filters: [
          { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (result.canceled) return null;
      return copyProfileImage(result.filePaths[0]);
    });

    ipcMain.handle("cml:read-local-image", async (_event, targetPath) => {
      return readApprovedLocalImage(targetPath);
    });
    ipcMain.handle("cml:delete-local-media", async (_event, mediaId) => {
      const target = resolveApprovedMediaTarget(mediaId);
      if (!target) return false;
      await fs.unlink(target).catch(() => {});
      return true;
    });

    ipcMain.handle("cml:get-backend-url", async () => backendUrl);
    ipcMain.handle("cml:get-backend-token", async () => getBackendApiToken());
    ipcMain.handle("cml:get-mcp-feature-flags", async () => ({ ...mcpFeatureFlags }));
    ipcMain.handle("cml:get-mcp-launcher", async (_event, requestedProfile) => {
      return getMcpLauncherDescriptor(requestedProfile);
    });
    ipcMain.handle("cml:get-odin-launcher-status", async () => {
      return getOdinLauncherStatus(getOdinLauncherConfiguration());
    });
    ipcMain.handle("cml:install-odin-launcher", async () => {
      const configuration = getOdinLauncherConfiguration();
      const installed = await installOdinLauncher(configuration);
      const help = runOdinLauncher(installed.launcher_path, ["--help"], {
        cwd: app.getPath("home"),
      });
      if (help.exit_code !== 0 || !help.stdout.toLowerCase().includes("odin")) {
        throw new Error("Odin was installed, but its help check failed. Repair Vault and try again.");
      }
      return { ...installed, help_ok: true };
    });
    ipcMain.handle("cml:install-odin-with-uv", async () => {
      const installed = await installOdinWithUv(getOdinLauncherConfiguration());
      const help = runOdinLauncher(installed.launcher_path, ["--help"], {
        cwd: app.getPath("home"),
      });
      if (help.exit_code !== 0 || !help.stdout.toLowerCase().includes("odin")) {
        throw new Error("uv installed Odin, but its help check failed.");
      }
      return { ...installed, help_ok: true };
    });
    ipcMain.handle("cml:start-odin-pairing", async () => {
      const configuration = getOdinLauncherConfiguration();
      const status = await getOdinLauncherStatus(configuration);
      if (!status.installed) throw new Error("Install Odin before pairing.");
      return runOdinLauncher(status.launcher_path, [], {
        cwd: app.getPath("home"),
        visible: true,
      });
    });
    ipcMain.handle("cml:get-tunnel-status", async () => tunnelManager?.getStatus() ?? null);
    ipcMain.handle("cml:connect-tunnel", async (_event, configuration) => {
      if (!mcpFeatureFlags.chatgpt_mcp_setup || !mcpFeatureFlags.secure_mcp_tunnel) {
        throw new Error("ChatGPT connection is unavailable in this Vault release.");
      }
      return tunnelManager.connect({
        ...configuration,
        capabilityProfile:
          configuration?.capabilityProfile === "read_write" &&
          mcpFeatureFlags.chatgpt_mcp_write_tools
            ? "read_write"
            : "read_only",
      });
    });
    ipcMain.handle("cml:reconnect-tunnel", async (_event, bridgeToken) => {
      if (!mcpFeatureFlags.chatgpt_mcp_setup || !mcpFeatureFlags.secure_mcp_tunnel) {
        throw new Error("ChatGPT connection is unavailable in this Vault release.");
      }
      return tunnelManager.reconnect(bridgeToken);
    });
    ipcMain.handle("cml:disconnect-tunnel", async (_event, forget = false) => {
      return tunnelManager.disconnect({ forget: Boolean(forget) });
    });
    ipcMain.handle("cml:open-tunnel-ui", async () => {
      const healthUrl = tunnelManager?.getStatus()?.health_url;
      if (!healthUrl) return false;
      const parsed = new URL(healthUrl);
      if (parsed.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) {
        return false;
      }
      await shell.openExternal(`${parsed.origin}/ui`);
      return true;
    });
    ipcMain.handle("cml:get-setup-state", async () => {
      return (await resolveSetupLaunchState()).state;
    });
    ipcMain.handle("cml:update-setup-state", async (_event, patch) => {
      const activeVaultPath = await getActiveVaultPath();
      return updateSetupState(app.getPath("userData"), patch, { activeVaultPath });
    });
    ipcMain.handle("cml:reset-app-setup", async () => {
      pendingActiveVaultPath = null;
      await tunnelManager?.disconnect({ forget: true });
      await clearActiveVaultPath();
      const state = await resetSetupState(app.getPath("userData"));
      await restartBackend();
      return state;
    });
    ipcMain.handle("cml:finalize-active-vault-deletion", async () => {
      return finalizeActiveVaultDeletion();
    });
    ipcMain.handle("cml:renderer-ready", async (_event, detail) => {
      rendererReadyPath = typeof detail === "string" ? detail : "";
      writeDesktopRuntimeLog(`renderer ready signal received path=${rendererReadyPath || "unknown"}`);
      return true;
    });
    ipcMain.handle("cml:copy-text", async (_event, value) => {
      clipboard.writeText(typeof value === "string" ? value : String(value ?? ""));
      return true;
    });
    ipcMain.handle("cml:retry-startup", async () => {
      writeDesktopRuntimeLog("manual startup retry requested");
      app.relaunch();
      app.exit(0);
      return true;
    });
    ipcMain.handle("cml:open-vault-anyway", async () => {
      const confirmation = await dialog.showMessageBox(mainWindow, {
        type: "warning",
        buttons: ["Cancel", "Open once"],
        defaultId: 0,
        cancelId: 0,
        title: "Open locked library?",
        message: "Open this vault only if every other Vault window or backend process is closed.",
        detail: "This bypasses the lock once. Opening the same library from two processes can corrupt local data.",
      });
      if (confirmation.response !== 1) return null;
      vaultLockOverrideOnce = true;
      await restartBackend();
      if (mainWindow && backendUrl) {
        const targetPath = await getInitialRendererPath();
        const url = isDev
          ? new URL(targetPath, ensureTrailingSlash(devUrl))
          : new URL(targetPath, rendererUrl || await startPackagedRendererServer());
        url.searchParams.set("backendUrl", backendUrl);
        await mainWindow.loadURL(url.toString());
      }
      return backendUrl;
    });
    ipcMain.handle("cml:set-active-vault-folder", async (_event, targetPath) => {
      if (typeof targetPath !== "string" || targetPath.trim().length === 0) return null;
      await commitActiveVaultPath(targetPath);
      return backendUrl;
    });
    ipcMain.handle("cml:move-active-vault-folder", async (_event, targetPath) => {
      if (typeof targetPath !== "string" || targetPath.trim().length === 0) return null;
      return moveActiveVaultPath(targetPath.trim());
    });
    ipcMain.handle("cml:clear-active-vault-folder", async () => {
      pendingActiveVaultPath = null;
      await clearActiveVaultPath();
      await restartBackend();
      return backendUrl;
    });
    ipcMain.handle("cml:prepare-active-vault-folder", async (_event, targetPath) => {
      if (typeof targetPath !== "string" || targetPath.trim().length === 0) return null;
      await prepareActiveVaultPath(targetPath);
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

async function copyProfileImage(sourcePath) {
  const source = path.resolve(String(sourcePath || ""));
  const sourceStat = await fs.stat(source);
  if (!sourceStat.isFile() || sourceStat.size > 10 * 1024 * 1024) {
    throw new Error("Choose a PNG, JPEG, WebP, or GIF image smaller than 10 MB.");
  }
  const bytes = await fs.readFile(source);
  const mimeType = imageMimeType(bytes);
  const dimensions = imageDimensions(bytes, mimeType);
  if (
    !mimeType ||
    !dimensions ||
    dimensions.width < 1 ||
    dimensions.height < 1 ||
    dimensions.width > 8192 ||
    dimensions.height > 8192 ||
    dimensions.width * dimensions.height > 40_000_000 ||
    bytes.length > 10 * 1024 * 1024
  ) {
    throw new Error("Choose a PNG, JPEG, WebP, or GIF image smaller than 10 MB.");
  }
  const extension = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
  }[mimeType];
  const digest = crypto.createHash("sha256").update(bytes).digest("hex");
  const mediaRoot = path.join(app.getPath("userData"), "media", "profiles");
  await fs.mkdir(mediaRoot, { recursive: true });
  const destination = path.join(mediaRoot, `${digest}${extension}`);
  try {
    await fs.writeFile(destination, bytes, { flag: "wx" });
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
  }
  return `media:profile:${digest}${extension}`;
}

async function getMcpLauncherDescriptor(requestedProfile) {
  if (!backendUrl) {
    throw new Error("Vault is still starting. Try again in a moment.");
  }
  const capabilityProfile =
    requestedProfile === "read_write" && mcpFeatureFlags.chatgpt_mcp_write_tools
      ? "read_write"
      : "read_only";
  const rootDir = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const helperPaths = isDev
    ? {
        resourcesRoot: rootDir,
        pythonRuntime: path.join(rootDir, ".venv"),
        backendPython: path.join(rootDir, ".venv", "Scripts", "python.exe"),
      }
    : resolvePackagedHelperPaths(process.resourcesPath);
  if (!isDev) {
    await verifyPackagedRuntime();
  }
  const pythonCommand = (await pathExists(helperPaths.backendPython))
    ? helperPaths.backendPython
    : (isDev ? "python" : helperPaths.backendPython);
  if (!isDev && !(await pathExists(pythonCommand))) {
    throw new Error("The packaged MCP runtime is missing. Repair Vault and try again.");
  }
  const env = isDev
    ? {
        CML_BACKEND_URL: backendUrl,
        CML_API_PREFIX: apiPrefix,
        CML_MCP_CAPABILITY_PROFILE: capabilityProfile,
      }
    : buildMcpChildEnv({
        inheritedEnv: process.env,
        helperPaths,
        backendUrl,
        apiPrefix,
        capabilityProfile,
        featureFlags: mcpFeatureFlags,
      });
  return {
    version: 1,
    app_version: app.getVersion(),
    command: pythonCommand,
    args: ["-s", "-m", "backend.app.bridge_mcp_stdio"],
    cwd: rootDir,
    env,
    capability_profile: capabilityProfile,
    packaged: app.isPackaged,
  };
}

function getOdinLauncherConfiguration() {
  const resourcesRoot = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const pythonPath = isDev
    ? path.join(resourcesRoot, ".venv", "Scripts", "python.exe")
    : resolvePackagedHelperPaths(resourcesRoot).backendPython;
  return {
    binDir: resolveOdinBinDir({
      localAppData: process.env.LOCALAPPDATA,
      appData: app.getPath("appData"),
      userData: app.getPath("userData"),
      homeDir: app.getPath("home"),
    }),
    pythonPath,
    resourcesRoot,
  };
}

async function readApprovedLocalImage(targetPath) {
  const resolvedMediaTarget = resolveApprovedMediaTarget(targetPath);
  const target = resolvedMediaTarget || path.resolve(String(targetPath || ""));
  const mediaRoot = path.resolve(path.join(app.getPath("userData"), "media"));
  try {
    const [realMediaRoot, realTarget] = await Promise.all([
      fs.realpath(mediaRoot),
      fs.realpath(target),
    ]);
    if (!isPathWithinRoot(realMediaRoot, realTarget)) return null;
    const stat = await fs.stat(target);
    if (!stat.isFile() || stat.size > 10 * 1024 * 1024) return null;
    const bytes = await fs.readFile(target);
    const mimeType = imageMimeType(bytes);
    return mimeType ? `data:${mimeType};base64,${bytes.toString("base64")}` : null;
  } catch {
    return null;
  }
}

function resolveApprovedMediaTarget(mediaId) {
  const match = /^media:profile:([a-f0-9]{64}\.(?:png|jpg|webp|gif))$/i.exec(String(mediaId || ""));
  if (!match) return null;
  return path.join(app.getPath("userData"), "media", "profiles", match[1].toLowerCase());
}

function imageMimeType(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 6) return null;
  if (bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return "image/png";
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return "image/jpeg";
  if (bytes.subarray(0, 6).toString("ascii") === "GIF87a" || bytes.subarray(0, 6).toString("ascii") === "GIF89a") {
    return "image/gif";
  }
  if (bytes.length >= 12 && bytes.subarray(0, 4).toString("ascii") === "RIFF" && bytes.subarray(8, 12).toString("ascii") === "WEBP") {
    return "image/webp";
  }
  return null;
}

function imageDimensions(bytes, mimeType) {
  try {
    if (mimeType === "image/png" && bytes.length >= 24) {
      return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
    }
    if (mimeType === "image/gif" && bytes.length >= 10) {
      return { width: bytes.readUInt16LE(6), height: bytes.readUInt16LE(8) };
    }
    if (mimeType === "image/webp" && bytes.length >= 30) {
      const kind = bytes.subarray(12, 16).toString("ascii");
      if (kind === "VP8X") {
        return {
          width: 1 + bytes.readUIntLE(24, 3),
          height: 1 + bytes.readUIntLE(27, 3),
        };
      }
      if (kind === "VP8 " && bytes.length >= 30 && bytes[23] === 0x9d && bytes[24] === 0x01 && bytes[25] === 0x2a) {
        return {
          width: bytes.readUInt16LE(26) & 0x3fff,
          height: bytes.readUInt16LE(28) & 0x3fff,
        };
      }
      if (kind === "VP8L" && bytes.length >= 25 && bytes[20] === 0x2f) {
        const bits = bytes.readUInt32LE(21);
        return {
          width: (bits & 0x3fff) + 1,
          height: ((bits >>> 14) & 0x3fff) + 1,
        };
      }
    }
    if (mimeType === "image/jpeg") {
      let offset = 2;
      while (offset + 8 < bytes.length) {
        if (bytes[offset] !== 0xff) {
          offset += 1;
          continue;
        }
        const marker = bytes[offset + 1];
        if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
          return { width: bytes.readUInt16BE(offset + 7), height: bytes.readUInt16BE(offset + 5) };
        }
        if (marker === 0xd8 || marker === 0xd9) {
          offset += 2;
          continue;
        }
        const segmentLength = bytes.readUInt16BE(offset + 2);
        if (segmentLength < 2) return null;
        offset += 2 + segmentLength;
      }
    }
  } catch {
    return null;
  }
  return null;
}

async function ensureBackend() {
  const explicitBackend = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL;
  const token = await getBackendApiToken();
  const activeVaultPath = pendingActiveVaultPath || await getActiveVaultPath();
  const backendMode = activeVaultPath ? "full_vault" : "pre_vault";
  const dataDir = activeVaultPath
    ? path.join(activeVaultPath, ".vault")
    : path.join(app.getPath("userData"), "pre-vault");
  const databasePath = path.join(dataDir, "cml.sqlite3");
  const expectedIdentity = {
    backend_mode: backendMode,
    data_dir: dataDir,
    database_path: databasePath,
  };
  const existing = explicitBackend
    ? await findExistingCurrentBackend(token, expectedIdentity)
    : null;
  if (existing) {
    await publishOdinRuntimeDescriptor(existing, token, expectedIdentity);
    return existing;
  }
  if (app.isPackaged) {
    await verifyPackagedRuntime();
  }

  const startupStatusPath = getStartupStatusPath();
  const port = await findOpenPort(7343, 7355);
  const rootDir = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const helperPaths = isDev
    ? {
        resourcesRoot: rootDir,
        pythonRuntime: path.join(rootDir, ".venv"),
        backendPython: path.join(rootDir, ".venv", "Scripts", "python.exe"),
        playwrightRoot: process.env.PLAYWRIGHT_BROWSERS_PATH || "",
        llmRuntimeRoot: path.join(rootDir, "apps", "desktop", "packaging", "llm-runtime"),
        llmRuntimeServer:
          process.env.CML_LLM_RUNTIME_BINARY ||
          path.join(rootDir, "apps", "desktop", "packaging", "llm-runtime", "llama-server.exe"),
        llmCudaRuntimeServer:
          process.env.CML_LLM_RUNTIME_CUDA_BINARY ||
          path.join(rootDir, "apps", "desktop", "packaging", "llm-runtime", "cuda", "llama-server.exe"),
      }
    : resolvePackagedHelperPaths(process.resourcesPath);
  const pythonCommand = isDev
    ? (await pathExists(helperPaths.backendPython) ? helperPaths.backendPython : "python")
    : helperPaths.backendPython;
  if (!isDev && !(await pathExists(pythonCommand))) {
    throw new Error("Packaged helper runtime is missing the backend Python executable.");
  }
  writeDesktopRuntimeLog(`starting backend; mode=${backendMode} dataDir=${dataDir}`);
  const backendArgs = ["-s", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", String(port)];
  // Packaged cold starts can spend tens of seconds loading the embedded Python
  // runtime, especially while Windows scans newly extracted binaries.
  const defaultBackendWaitTimeoutMs = isDev ? 30000 : 90000;
  const backendWaitTimeoutMs = Number(
    process.env.CML_BACKEND_WAIT_TIMEOUT_MS || defaultBackendWaitTimeoutMs,
  );
  const backendStartedAt = Date.now();
  backendProcess = spawn(
    pythonCommand,
    backendArgs,
    {
      cwd: rootDir,
      env: isDev
        ? {
            ...process.env,
            CML_API_PREFIX: apiPrefix,
            CML_API_TOKEN: token,
            CML_BACKEND_MODE: backendMode,
            CML_DATA_DIR: dataDir,
            CML_DATABASE_PATH: databasePath,
            CML_STARTUP_STATUS_PATH: startupStatusPath,
            CML_VAULT_LOCK_OVERRIDE: vaultLockOverrideOnce ? "open_anyway" : "",
            CML_LLM_RUNTIME_BINARY: helperPaths.llmRuntimeServer,
            CML_LLM_RUNTIME_CUDA_BINARY: helperPaths.llmCudaRuntimeServer,
            PLAYWRIGHT_BROWSERS_PATH: helperPaths.playwrightRoot,
            PYTHONNOUSERSITE: "1",
          }
        : buildBackendChildEnv({
            inheritedEnv: process.env,
            helperPaths,
            apiPrefix,
            apiToken: token,
            backendMode,
            dataDir,
            databasePath,
            startupStatusPath,
            vaultLockOverride: vaultLockOverrideOnce ? "open_anyway" : "",
          }),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const backendLogPaths = attachBackendLogging(
    backendProcess,
    pythonCommand,
    backendArgs,
  );
  vaultLockOverrideOnce = false;
  backendProcess.unref();
  const startedUrl = `http://127.0.0.1:${port}`;
  await waitForBackend(
    startedUrl,
    token,
    backendWaitTimeoutMs,
    backendLogPaths,
    backendProcess,
    expectedIdentity,
  );
  await publishOdinRuntimeDescriptor(startedUrl, token, expectedIdentity);
  writeDesktopRuntimeLog(`backend ready after ${Date.now() - backendStartedAt}ms at ${startedUrl}`);
  return startedUrl;
}

async function publishOdinRuntimeDescriptor(url, token, expectedIdentity = null) {
  const identity = await httpJson(`${url}${apiPrefix}/system/backend-identity`, 2000, token);
  if (
    !backendIdentityMatches(identity, expectedIdentity) ||
    !identity.instance_id
  ) {
    throw new Error("The backend identity could not be verified for Odin discovery.");
  }
  const descriptor = createRuntimeDescriptor({
    backendUrl: url,
    apiPrefix,
    backendInstanceId: identity.instance_id,
    backendPid: backendProcess?.pid ?? null,
    desktopPid: process.pid,
  });
  odinRuntimeDescriptorPath = runtimeDescriptorPath(path.join(app.getPath("appData"), "Vault"));
  await writeRuntimeDescriptor(odinRuntimeDescriptorPath, descriptor);
}

async function verifyPackagedRuntime() {
  if (packagedRuntimeVerification) {
    return packagedRuntimeVerification;
  }
  const helperPaths = resolvePackagedHelperPaths(process.resourcesPath);
  const activeVaultPath = pendingActiveVaultPath || await getActiveVaultPath();
  const manifestReport = await verifyHelperManifestCached(process.resourcesPath, {
    receiptPath: path.join(app.getPath("userData"), "helper-verification-v1.json"),
    packageVersion: app.getVersion(),
  });
  writeDesktopRuntimeLog(
    `helper verification ${manifestReport.cached ? "cache hit" : "full scan"}; entries=${manifestReport.entry_count}`,
  );
  if (!manifestReport.ok) {
    const failingEntry = manifestReport.entries.find((entry) => !entry.ok);
    const detail = failingEntry
      ? `${failingEntry.relative_path} failed helper verification`
      : "Helper manifest verification failed";
    throw new Error(detail);
  }
  const layoutReport = packageLayoutAudit({
    packageRoot: path.resolve(process.resourcesPath, ".."),
    resourcesRoot: process.resourcesPath,
    helperRoots: [
      helperPaths.backendRoot,
      helperPaths.pythonRuntime,
      helperPaths.playwrightRoot,
      helperPaths.llmRuntimeRoot,
      helperPaths.tunnelRuntimeRoot,
    ],
    writableRoots: defaultWritableRoots({
      userDataPath: app.getPath("userData"),
      activeVaultPath,
    }),
    helperManifestPath: helperPaths.helperManifest,
  });
  if (!layoutReport.ok) {
    throw new Error("Packaged helper layout overlaps runtime-writable paths.");
  }
  packagedRuntimeVerification = { manifestReport, layoutReport };
  return packagedRuntimeVerification;
}

async function restartBackend() {
  if (odinRuntimeDescriptorPath) await removeRuntimeDescriptor(odinRuntimeDescriptorPath);
  await stopBackendProcess();
  backendUrl = null;
  backendUrl = await ensureBackend();
  if (mainWindow && backendUrl) {
    mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
  }
}

async function prepareActiveVaultPath(targetPath) {
  const previousPendingPath = pendingActiveVaultPath;
  pendingActiveVaultPath = targetPath;
  await fs.mkdir(path.join(targetPath, ".vault"), { recursive: true });
  try {
    await restartBackend();
  } catch (error) {
    pendingActiveVaultPath = previousPendingPath;
    try {
      await restartBackend();
    } catch (rollbackError) {
      writeDesktopRuntimeLog("failed to restore previous backend after vault prepare failure", rollbackError);
    }
    throw error;
  }
}

async function commitActiveVaultPath(targetPath) {
  await setActiveVaultPath(targetPath);
  if (pendingActiveVaultPath === targetPath) {
    pendingActiveVaultPath = null;
    return;
  }
  await restartBackend();
}

function getActiveVaultConfigPath() {
  return path.join(app.getPath("userData"), "active-vault.json");
}

async function getActiveVaultPath() {
  try {
    const raw = await fs.readFile(getActiveVaultConfigPath(), "utf8");
    const parsed = JSON.parse(raw);
    if (typeof parsed.path === "string" && parsed.path.trim()) {
      const candidatePath = parsed.path.trim();
      if (await isUsableActiveVaultPath(candidatePath)) {
        return candidatePath;
      }
      await clearActiveVaultPath();
    }
  } catch {
    return null;
  }
  return null;
}

async function setActiveVaultPath(targetPath) {
  await fs.mkdir(path.dirname(getActiveVaultConfigPath()), { recursive: true });
  await fs.mkdir(path.join(targetPath, ".vault"), { recursive: true });
  await atomicWriteJson(getActiveVaultConfigPath(), {
    schema_version: 1,
    path: targetPath,
    updated_at: new Date().toISOString(),
  });
}

async function moveActiveVaultPath(targetPath) {
  const currentPath = await getActiveVaultPath();
  if (!currentPath) {
    throw new Error("No active library is available to move.");
  }
  const sourceRoot = path.resolve(currentPath);
  const destinationRoot = path.resolve(targetPath);
  if (sourceRoot === destinationRoot) {
    return { backend_url: backendUrl, path: destinationRoot, old_copy_removed: true };
  }
  assertSafeVaultMoveRoots(sourceRoot, destinationRoot);
  const sourceVault = path.join(sourceRoot, ".vault");
  const destinationVault = path.join(destinationRoot, ".vault");
  const stagingVault = path.join(
    destinationRoot,
    `.vault.move-staging-${process.pid}-${Date.now()}`,
  );
  let destinationPublished = false;
  await fs.mkdir(destinationRoot, { recursive: true });
  if (await pathExists(destinationVault)) {
    const entries = await fs.readdir(destinationVault);
    if (entries.length > 0) {
      throw new Error("The selected folder already contains Vault library data.");
    }
    await fs.rmdir(destinationVault);
  }
  try {
    await stopBackendProcess();
    await fs.cp(sourceVault, stagingVault, {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
    await verifyCopiedVault(stagingVault);
    await fs.rename(stagingVault, destinationVault);
    destinationPublished = true;
    pendingActiveVaultPath = null;
    await setActiveVaultPath(destinationRoot);
    backendUrl = await ensureBackend();
    if (mainWindow && backendUrl) {
      mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
    }
    let oldCopyRemoved = true;
    try {
      await fs.rm(sourceVault, { recursive: true, force: false });
    } catch (error) {
      oldCopyRemoved = false;
      writeDesktopRuntimeLog("new vault is active but old vault copy could not be removed", error);
    }
    const activeVaultPath = await getActiveVaultPath();
    await updateSetupState(
      app.getPath("userData"),
      { vault: { path: destinationRoot } },
      { activeVaultPath },
    );
    return {
      backend_url: backendUrl,
      path: destinationRoot,
      old_copy_removed: oldCopyRemoved,
    };
  } catch (error) {
    pendingActiveVaultPath = null;
    try {
      await setActiveVaultPath(sourceRoot);
      if (destinationPublished && await pathExists(destinationVault)) {
        await fs.rm(destinationVault, { recursive: true, force: false });
      }
      backendUrl = await ensureBackend();
      if (mainWindow && backendUrl) {
        mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
      }
    } catch (rollbackError) {
      writeDesktopRuntimeLog("vault move rollback failed", rollbackError);
    }
    throw error;
  } finally {
    if (await pathExists(stagingVault)) {
      await fs.rm(stagingVault, { recursive: true, force: true });
    }
  }
}

async function finalizeActiveVaultDeletion() {
  const activePath = await getActiveVaultPath();
  if (!activePath) {
    return { deleted: false, path: "" };
  }
  await tunnelManager?.disconnect({ forget: true });
  const activeRoot = path.resolve(activePath);
  assertSafeVaultDataRoot(activeRoot);
  const vaultData = path.join(activeRoot, ".vault");
  const tombstone = path.join(
    activeRoot,
    `.vault.deleted-${process.pid}-${Date.now()}`,
  );
  const userDataPath = app.getPath("userData");
  const previousSetupState = await readSetupState(userDataPath, {
    activeVaultPath: activeRoot,
  });
  await writeVaultDeletionJournal({
    phase: "prepared",
    active_root: activeRoot,
    vault_data: vaultData,
    tombstone,
    updated_at: new Date().toISOString(),
  });
  try {
    await stopBackendDependents();
    await stopBackendProcess(5000, false);
    if (await pathExists(vaultData)) {
      await fs.rename(vaultData, tombstone);
    }
    await writeVaultDeletionJournal({
      phase: "renamed",
      active_root: activeRoot,
      vault_data: vaultData,
      tombstone,
      updated_at: new Date().toISOString(),
    });
    pendingActiveVaultPath = null;
    await clearActiveVaultPath();
    await resetSetupState(userDataPath);
    await writeVaultDeletionJournal({
      phase: "pointer_cleared",
      active_root: activeRoot,
      vault_data: vaultData,
      tombstone,
      updated_at: new Date().toISOString(),
    });
    backendUrl = await ensureBackend();
    if (mainWindow && backendUrl) {
      mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
    }
    if (await pathExists(tombstone)) {
      await fs.rm(tombstone, { recursive: true, force: true });
    }
    await clearVaultDeletionJournal();
    return { deleted: true, path: activeRoot };
  } catch (error) {
    try {
      await stopBackendProcess(5000, false);
    } catch (stopError) {
      writeDesktopRuntimeLog("backend did not stop during vault deletion rollback", stopError);
    }
    backendUrl = null;
    if (await pathExists(tombstone) && !(await pathExists(vaultData))) {
      try {
        await fs.rename(tombstone, vaultData);
      } catch (rollbackError) {
        writeDesktopRuntimeLog("vault deletion rollback rename failed", rollbackError);
      }
    }
    await setActiveVaultPath(activeRoot);
    await writeSetupState(userDataPath, previousSetupState);
    try {
      backendUrl = await ensureBackend();
    } catch (restartError) {
      writeDesktopRuntimeLog("vault deletion rollback backend restart failed", restartError);
    }
    await clearVaultDeletionJournal();
    throw error;
  }
}

function getVaultDeletionJournalPath() {
  return path.join(app.getPath("userData"), "vault-deletion.json");
}

async function writeVaultDeletionJournal(value) {
  await atomicWriteJson(getVaultDeletionJournalPath(), {
    schema_version: 1,
    ...value,
  });
}

async function clearVaultDeletionJournal() {
  try {
    await fs.unlink(getVaultDeletionJournalPath());
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function reconcilePendingVaultDeletion() {
  let journal;
  try {
    journal = JSON.parse(await fs.readFile(getVaultDeletionJournalPath(), "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  const activeRoot = path.resolve(String(journal.active_root || ""));
  const vaultData = path.resolve(String(journal.vault_data || ""));
  const tombstone = path.resolve(String(journal.tombstone || ""));
  assertSafeVaultDataRoot(activeRoot);
  if (
    vaultData !== path.join(activeRoot, ".vault") ||
    path.dirname(tombstone) !== activeRoot ||
    !path.basename(tombstone).startsWith(".vault.deleted-")
  ) {
    throw new Error("Pending vault deletion journal contains unsafe paths.");
  }
  if (journal.phase === "prepared" && (await pathExists(vaultData))) {
    await clearVaultDeletionJournal();
    return;
  }
  pendingActiveVaultPath = null;
  await clearActiveVaultPath();
  await resetSetupState(app.getPath("userData"));
  if (await pathExists(tombstone)) {
    await fs.rm(tombstone, { recursive: true, force: true });
  }
  await clearVaultDeletionJournal();
}

function assertSafeVaultDataRoot(candidate) {
  const parsed = path.parse(candidate);
  if (!path.isAbsolute(candidate) || candidate === parsed.root) {
    throw new Error("Refusing to delete Vault data at a drive root.");
  }
}

function assertSafeVaultMoveRoots(sourceRoot, destinationRoot) {
  for (const candidate of [sourceRoot, destinationRoot]) {
    const parsed = path.parse(candidate);
    if (!path.isAbsolute(candidate) || candidate === parsed.root) {
      throw new Error("A library location must be an absolute folder below a drive root.");
    }
  }
  if (pathsOverlap(sourceRoot, destinationRoot)) {
    throw new Error("The new library folder cannot be inside the current library or contain it.");
  }
}

async function verifyCopiedVault(vaultDataPath) {
  const databasePath = path.join(vaultDataPath, "cml.sqlite3");
  const handle = await fs.open(databasePath, "r");
  try {
    const header = Buffer.alloc(16);
    const { bytesRead } = await handle.read(header, 0, header.length, 0);
    if (bytesRead !== 16 || header.toString("utf8") !== "SQLite format 3\u0000") {
      throw new Error("The copied library database did not pass its SQLite header check.");
    }
  } finally {
    await handle.close();
  }
}

async function stopBackendProcess(timeoutMs = 5000, stopDependents = true) {
  const child = backendProcess;
  backendProcess = null;
  if (!child || child.exitCode !== null || child.killed) {
    closeBackendLogStreams();
    return;
  }
  if (stopDependents) {
    try {
      await stopBackendDependents();
    } catch (error) {
      writeDesktopRuntimeLog("managed runtime did not stop before backend shutdown", error);
      backendProcess = child;
      throw error;
    }
  }
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error = null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      child.removeListener("exit", onExit);
      child.removeListener("error", onError);
      if (error) reject(error);
      else resolve();
    };
    const onExit = () => finish();
    const onError = (error) => finish(error);
    const timeout = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        // The process may have exited between the timeout and escalation.
      }
      finish(new Error(`Backend did not exit within ${timeoutMs}ms.`));
    }, timeoutMs);
    child.once("exit", onExit);
    child.once("error", onError);
    try {
      child.kill();
    } catch (error) {
      finish(error);
    }
  }).finally(() => {
    closeBackendLogStreams();
  });
}

async function clearActiveVaultPath() {
  try {
    await fs.unlink(getActiveVaultConfigPath());
  } catch {
    // Missing or locked config should not prevent the app from recovering.
  }
}

async function isUsableActiveVaultPath(targetPath) {
  if (!(await isExistingLocalPath(targetPath))) {
    return false;
  }
  try {
    const rootStat = await fs.lstat(targetPath);
    if (!rootStat.isDirectory()) {
      return false;
    }
    const vaultState = await fs.lstat(path.join(targetPath, ".vault"));
    return vaultState.isDirectory();
  } catch {
    return false;
  }
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
  const serverEntry = await resolvePackagedServerEntry();
  const workerModule = await import(pathToFileURL(serverEntry).href);
  const worker = workerModule.default;

  rendererServer = http.createServer(async (request, response) => {
    try {
      const parsed = new URL(request.url || "/", `http://127.0.0.1:${port}`);
      const staticResponse = await tryServeStaticAsset(clientDir, parsed.pathname);
      if (staticResponse) {
        writeNodeResponse(response, staticResponse.status, rendererSecurityHeaders(staticResponse.headers), staticResponse.body);
        return;
      }

      const target = `http://127.0.0.1:${port}${request.url || "/"}`;
      const webRequest = new Request(target, {
        method: request.method,
        headers: request.headers,
      });
      const webResponse = await worker.fetch(webRequest, {}, {});
      const responseHeaders = Object.fromEntries(webResponse.headers);
      const body = await sanitizeRendererBody(webResponse, responseHeaders);
      writeNodeResponse(response, webResponse.status, rendererSecurityHeaders(responseHeaders), body);
    } catch (error) {
      writeDesktopRuntimeLog("renderer request failed", error);
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

async function resolvePackagedServerEntry(baseDir = __dirname) {
  const candidates = [
    path.join(baseDir, "../dist/server/index.js"),
    path.join(baseDir, "../dist/server/server.js"),
  ];
  for (const candidate of candidates) {
    if (await pathExists(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    `Packaged renderer server entry is missing. Checked: ${candidates.join(", ")}`,
  );
}

async function sanitizeRendererBody(webResponse, headers) {
  const rawBody = Buffer.from(await webResponse.arrayBuffer());
  const contentType = String(headers["content-type"] || headers["Content-Type"] || "");
  if (!contentType.toLowerCase().includes("text/html")) {
    return rawBody;
  }
  const html = rawBody.toString("utf8")
    .replace(/<link\b[^>]*href=["']https:\/\/fonts\.googleapis\.com\/[^"']*["'][^>]*>/gi, "")
    .replace(/<link\b[^>]*rel=["']preconnect["'][^>]*href=["']https:\/\/fonts\.googleapis\.com["'][^>]*>/gi, "")
    .replace(/<link\b[^>]*href=["']https:\/\/fonts\.googleapis\.com["'][^>]*rel=["']preconnect["'][^>]*>/gi, "");
  return Buffer.from(html, "utf8");
}

async function tryServeStaticAsset(clientDir, pathname) {
  let safePathname = "";
  try {
    safePathname = decodeURIComponent(pathname).replace(/^\/+/, "");
  } catch {
    return {
      status: 400,
      headers: { "content-type": "text/plain; charset=utf-8" },
      body: Buffer.from("Bad request"),
    };
  }
  if (!safePathname || safePathname.includes("..")) return null;
  if (!(safePathname.startsWith("assets/") || safePathname.startsWith("brand/"))) return null;
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

function rendererSecurityHeaders(headers = {}) {
  return {
    ...headers,
    "content-security-policy": [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https:",
      "font-src 'self' data:",
      "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
      "media-src 'none'",
      "object-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'none'",
    ].join("; "),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
  };
}

function contentTypeForPath(targetPath) {
  const ext = path.extname(targetPath).toLowerCase();
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".json") return "application/json; charset=utf-8";
  return "application/octet-stream";
}

async function findExistingCurrentBackend(token, expectedIdentity = null) {
  const candidates = [
    process.env.VITE_CML_BACKEND_URL,
    process.env.CML_BACKEND_URL,
    "http://127.0.0.1:7342",
    ...Array.from({ length: 13 }, (_value, index) => `http://127.0.0.1:${7343 + index}`),
  ].filter(Boolean);
  for (const candidate of [...new Set(candidates)]) {
    if (await isCurrentBackend(candidate, token, expectedIdentity)) return candidate;
  }
  return null;
}

function isCurrentBackend(url, token, expectedIdentity = null) {
  if (!token) return Promise.resolve(false);
  return httpJson(`${url}${apiPrefix}/system/backend-identity`, 1200, token)
    .then((identity) => backendIdentityMatches(identity, expectedIdentity))
    .catch(async (error) => {
      // In pre-vault mode, private API routes intentionally return 409 until
      // setup completes. That still means the backend is alive and current.
      if (
        !expectedIdentity &&
        error instanceof HttpStatusError &&
        error.statusCode === 409
      ) {
        try {
          const health = await httpJson(`${url}/health`, 1200);
          return health && health.service === "cml-backend" && health.status === "ok";
        } catch {
          return false;
        }
      }
      return false;
    });
}

function backendIdentityMatches(identity, expectedIdentity = null) {
  if (
    !identity ||
    identity.service !== "cml-backend" ||
    identity.api_prefix !== apiPrefix
  ) {
    return false;
  }
  if (!expectedIdentity) return true;
  return (
    identity.backend_mode === expectedIdentity.backend_mode &&
    normalizedIdentityPath(identity.data_dir) === normalizedIdentityPath(expectedIdentity.data_dir) &&
    normalizedIdentityPath(identity.database_path) ===
      normalizedIdentityPath(expectedIdentity.database_path)
  );
}

function normalizedIdentityPath(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  const resolved = path.resolve(value.trim());
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function createBackendLaunchError(url, started, status, backendLogPaths = null, processState = null) {
  const messageParts = [`Backend did not start at ${url}`];
  if (status?.phase) {
    messageParts.push(`phase=${status.phase}`);
  }
  if (status?.message) {
    messageParts.push(`detail=${status.message}`);
  }
  messageParts.push(`elapsed_ms=${Date.now() - started}`);
  if (processState?.error?.message) {
    messageParts.push(`process_error=${processState.error.message}`);
  }
  if (processState?.exitCode !== null && processState?.exitCode !== undefined) {
    messageParts.push(`exit_code=${processState.exitCode}`);
  }
  if (processState?.signal) {
    messageParts.push(`signal=${processState.signal}`);
  }
  if (backendLogPaths?.stderr) {
    messageParts.push(`stderr=${backendLogPaths.stderr}`);
  }
  return new Error(messageParts.join(" | "));
}

async function waitForBackend(
  url,
  token,
  timeoutMs,
  backendLogPaths = null,
  childProcess = null,
  expectedIdentity = null,
) {
  const started = Date.now();
  const processState = { exitCode: null, signal: null, error: null };
  const onClose = (code, signal) => {
    processState.exitCode = code;
    processState.signal = signal;
  };
  const onError = (error) => {
    processState.error = error;
  };
  if (childProcess) {
    childProcess.once("close", onClose);
    childProcess.once("error", onError);
  }
  try {
    while (Date.now() - started < timeoutMs) {
      if (await isCurrentBackend(url, token, expectedIdentity)) return;
      if (processState.error || processState.exitCode !== null || processState.signal) {
        const status = await readStartupStatus();
        throw createBackendLaunchError(url, started, status, backendLogPaths, processState);
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const status = await readStartupStatus();
    throw createBackendLaunchError(url, started, status, backendLogPaths, processState);
  } finally {
    if (childProcess) {
      childProcess.removeListener("close", onClose);
      childProcess.removeListener("error", onError);
    }
  }
}

async function verifyRendererUp(url, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await httpStatus(url, 1500);
      if (response.statusCode >= 200 && response.statusCode < 400) {
        return;
      }
      const locationText = response.location ? ` location=${response.location}` : "";
      writeDesktopRuntimeLog(`renderer probe returned status ${response.statusCode} for ${url}${locationText}`);
    } catch (error) {
      writeDesktopRuntimeLog(`renderer probe failed for ${url}`, error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Renderer did not become available at ${url}. See ${getDesktopRuntimeLogPath()}`);
}

async function waitForRendererReady(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (rendererReadyPath !== null) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Renderer did not signal readiness. See ${getDesktopRuntimeLogPath()}`);
}

function httpStatus(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      response.resume();
      response.on("end", () => resolve({
        statusCode: response.statusCode || 0,
        location: response.headers.location || "",
      }));
    });
    request.on("timeout", () => {
      request.destroy(new Error("Timed out"));
    });
    request.on("error", reject);
  });
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
          reject(new HttpStatusError(response.statusCode, body));
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

function httpPostJson(url, timeoutMs, token = "") {
  return new Promise((resolve, reject) => {
    const headers = {
      ...(token ? { "x-cml-api-token": token } : {}),
      "content-length": "0",
    };
    const request = http.request(
      url,
      { method: "POST", timeout: timeoutMs, headers },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
        });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new HttpStatusError(response.statusCode, body));
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on("timeout", () => {
      request.destroy(new Error("Timed out"));
    });
    request.on("error", reject);
    request.end();
  });
}

async function stopManagedRuntimeBeforeBackendStop() {
  if (!backendUrl) return;
  const token = await getBackendApiToken();
  await httpPostJson(
    `${backendUrl}${apiPrefix}/models/runtime/stop`,
    12000,
    token,
  );
}

class HttpStatusError extends Error {
  constructor(statusCode, body = "") {
    super(`HTTP ${statusCode}`);
    this.name = "HttpStatusError";
    this.statusCode = statusCode;
    this.body = body;
  }
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

async function collectSupportedFiles(targetPath, files, maxFiles = 500, state = null) {
  let stat;
  try {
    stat = await fs.lstat(targetPath);
  } catch {
    return;
  }
  if (stat.isSymbolicLink()) return;

  if (stat.isFile()) {
    if (supportedSourceExtensions.has(path.extname(targetPath).toLowerCase())) {
      if (files.length < maxFiles) files.push(targetPath);
      else if (state) state.truncated = true;
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
    if (files.length >= maxFiles) {
      if (state) state.truncated = true;
      return;
    }
    if (entry.name.startsWith(".") && entry.name !== ".obsidian") continue;
    await collectSupportedFiles(path.join(targetPath, entry.name), files, maxFiles, state);
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

async function shutdownApplication() {
  tunnelManager?.shutdownSync();
  if (odinRuntimeDescriptorPath) {
    try {
      fsSync.rmSync(odinRuntimeDescriptorPath, { force: true });
    } catch {
      // Expiry and PID validation still reject a descriptor that cannot be removed during shutdown.
    }
  }
  if (rendererServer) {
    rendererServer.close();
    rendererServer = null;
  }
  try {
    await stopBackendProcess(12000);
  } catch (error) {
    writeDesktopRuntimeLog("graceful backend shutdown failed", error);
    try {
      await stopBackendProcess(5000, false);
    } catch (stopError) {
      writeDesktopRuntimeLog("forced backend shutdown failed", stopError);
    }
  }
  closeBackendLogStreams();
}

app.on("before-quit", (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownPromise) return;
  shutdownPromise = shutdownApplication()
    .catch((error) => {
      writeDesktopRuntimeLog("application shutdown failed", error);
    })
    .finally(() => {
      shutdownComplete = true;
      app.quit();
    });
});
