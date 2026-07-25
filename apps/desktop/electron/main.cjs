const { app, BrowserWindow, clipboard, dialog, ipcMain, safeStorage, shell } = require("electron");
const { spawn } = require("node:child_process");
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const {
  buildBackendChildEnv,
  defaultWritableRoots,
  packageLayoutAudit,
  resolvePackagedHelperPaths,
  verifyHelperManifest,
} = require("./helper-integrity.cjs");
const { createTokenStore, getOrCreateToken } = require("./token-store.cjs");
const {
  createRuntimeDescriptor,
  removeRuntimeDescriptor,
  runtimeDescriptorPath,
  writeRuntimeDescriptor,
} = require("./runtime-descriptor.cjs");

const isDev = !app.isPackaged;
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";
const apiPrefix = normalizeApiPrefix(process.env.CML_API_PREFIX);
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
const startupRepairLogoMarkup = `
  <img
    src="data:image/png;base64,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"
    alt=""
    aria-hidden="true"
    style="display:block;width:100%;height:100%;object-fit:cover;"
  />
`;

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

function writeDesktopRuntimeLog(message, error = null) {
  try {
    const logPath = getDesktopRuntimeLogPath();
    const detail = error && (error.stack || error.message) ? `\n${error.stack || error.message}` : "";
    fsSync.appendFileSync(logPath, `${new Date().toISOString()} ${message}${detail}\n`, "utf8");
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
  let startupError = null;
  const initialRendererPath = await getInitialRendererPath();
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
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = window;
  window.setMenuBarVisibility(false);

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
      rendererUrl = rendererUrl || await startPackagedRendererServer();
      await verifyRendererUp(rendererUrl, 10000);
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

async function getInitialRendererPath() {
  const activeVaultPath = await getActiveVaultPath();
  return activeVaultPath ? "/home" : "/onboarding";
}

function ensureTrailingSlash(value) {
  return value.endsWith("/") ? value : `${value}/`;
}

async function loadStartupFailure(window, error) {
  const status = await readStartupStatus();
  const backendLogs = getBackendLogPaths();
  const detail = status?.message || error?.message || "Vault could not start its local backend.";
  const phase = status?.phase || "startup_failed";
  const action = repairActionForPhase(phase);
  const diagnosticText = [
    `Phase: ${phase}`,
    `Message: ${detail}`,
    `Data directory: ${status?.data_dir || "Unknown"}`,
    `Database: ${status?.database_path || "Unknown"}`,
    `Startup status: ${getStartupStatusPath()}`,
    `Backend stdout log: ${backendLogs.stdout}`,
    `Backend stderr log: ${backendLogs.stderr}`,
    `Desktop runtime log: ${getDesktopRuntimeLogPath()}`,
  ].join("\n");
  const html = `
    <!doctype html>
    <meta charset="utf-8" />
    <title>Vault startup issue</title>
    <body style="margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#fbfaf6;color:#1f1a17;">
      <main style="max-width:760px;margin:10vh auto;padding:32px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:28px;">
          <div style="width:32px;height:32px;border:1px solid #ded6cc;border-radius:8px;display:grid;place-items:center;background:#fffdf9;overflow:hidden;">${startupRepairLogoMarkup}</div>
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
          <button onclick="window.cmlDesktop?.retryStartup?.()" style="height:36px;padding:0 14px;border:0;border-radius:8px;background:#765f4d;color:#fff;font-weight:600;">Try again</button>
          ${phase === "vault_lock_failed" ? '<button onclick="window.cmlDesktop?.openVaultAnyway?.()" style="height:36px;padding:0 14px;border:1px solid #9b6a4f;border-radius:8px;background:#fff7ed;color:#7c2d12;font-weight:600;">Open anyway</button>' : ""}
          <button id="copy-details-button" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Copy details</button>
          <button onclick="window.close()" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Close Vault</button>
        </div>
      </main>
      <script>
        const copyButton = document.getElementById("copy-details-button");
        if (copyButton) {
          copyButton.addEventListener("click", async () => {
            try {
              if (window.cmlDesktop?.copyText) {
                await window.cmlDesktop.copyText(${JSON.stringify(diagnosticText)});
              } else if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(${JSON.stringify(diagnosticText)});
              } else {
                throw new Error("Clipboard bridge unavailable");
              }
              copyButton.textContent = "Copied details";
            } catch {
              copyButton.textContent = "Copy failed";
            }
          });
        }
      </script>
    </body>`;
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

async function loadRendererFailure(window, error) {
  const diagnosticText = [
    "Phase: renderer_startup_failed",
    `Message: ${error?.message || "Packaged renderer did not become available."}`,
    `Renderer URL: ${rendererUrl || "Unknown"}`,
    `Startup status: ${getStartupStatusPath()}`,
    `Backend stdout log: ${getBackendLogPaths().stdout}`,
    `Backend stderr log: ${getBackendLogPaths().stderr}`,
    `Desktop runtime log: ${getDesktopRuntimeLogPath()}`,
  ].join("\n");
  const html = `
    <!doctype html>
    <meta charset="utf-8" />
    <title>Vault renderer issue</title>
    <body style="margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#fbfaf6;color:#1f1a17;">
      <main style="max-width:760px;margin:10vh auto;padding:32px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:28px;">
          <div style="width:32px;height:32px;border:1px solid #ded6cc;border-radius:8px;display:grid;place-items:center;background:#fffdf9;overflow:hidden;">${startupRepairLogoMarkup}</div>
          <div>
            <div style="font-weight:650;font-size:14px;">Vault</div>
            <div style="font-size:12px;color:#7c6f65;">Renderer repair</div>
          </div>
        </div>
        <h1 style="font-size:30px;line-height:1.15;margin:0 0 12px;">Vault could not load its packaged UI.</h1>
        <p style="line-height:1.65;color:#5f524b;margin:0;max-width:620px;">${escapeHtml(error?.message || "The local renderer did not become ready.")}</p>
        <div style="margin-top:22px;padding:16px;border:1px solid #d7cfc5;border-radius:8px;background:#fffdf9;">
          <div style="font-weight:600;font-size:14px;">The backend may already be healthy.</div>
          <div style="margin-top:6px;font-size:13px;line-height:1.55;color:#5f524b;">Check the desktop runtime log path below for renderer startup details before rebuilding.</div>
        </div>
        <div style="display:flex;gap:10px;margin-top:22px;flex-wrap:wrap;">
          <button onclick="window.cmlDesktop?.retryStartup?.()" style="height:36px;padding:0 14px;border:0;border-radius:8px;background:#765f4d;color:#fff;font-weight:600;">Try again</button>
          <button id="copy-details-button" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Copy details</button>
          <button onclick="window.close()" style="height:36px;padding:0 14px;border:1px solid #ded6cc;border-radius:8px;background:#fffdf9;color:#1f1a17;">Close Vault</button>
        </div>
      </main>
      <script>
        const copyButton = document.getElementById("copy-details-button");
        if (copyButton) {
          copyButton.addEventListener("click", async () => {
            try {
              if (window.cmlDesktop?.copyText) {
                await window.cmlDesktop.copyText(${JSON.stringify(diagnosticText)});
              } else if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(${JSON.stringify(diagnosticText)});
              } else {
                throw new Error("Clipboard bridge unavailable");
              }
              copyButton.textContent = "Copied details";
            } catch {
              copyButton.textContent = "Copy failed";
            }
          });
        }
      </script>
    </body>`;
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

function repairActionForPhase(phase) {
  if (phase === "integrity_check_failed") {
    return {
      title: "The library database did not pass its health check.",
      body: "Do not keep retrying if this repeats. The next repair pass should export diagnostics and offer backup or restore options before any write recovery.",
    };
  }
  if (phase === "schema_check_failed") {
    return {
      title: "The library schema or migration state is incomplete.",
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
          detail: "Close the current library before opening another.",
        });
      }
    }
  });
}

if (gotSingleInstanceLock) {
  app.whenReady().then(() => {
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

async function ensureBackend() {
  const explicitBackend = process.env.VITE_CML_BACKEND_URL || process.env.CML_BACKEND_URL;
  const token = await getBackendApiToken();
  const existing = explicitBackend ? await findExistingCurrentBackend(token) : null;
  if (existing) {
    await publishOdinRuntimeDescriptor(existing, token);
    return existing;
  }
  if (app.isPackaged) {
    await verifyPackagedRuntime();
  }

  const activeVaultPath = pendingActiveVaultPath || await getActiveVaultPath();
  const backendMode = activeVaultPath ? "full_vault" : "pre_vault";
  const dataDir = activeVaultPath
    ? path.join(activeVaultPath, ".vault")
    : path.join(app.getPath("userData"), "pre-vault");
  const databasePath = path.join(dataDir, "cml.sqlite3");
  const startupStatusPath = getStartupStatusPath();
  const port = await findOpenPort(7343, 7355);
  const rootDir = isDev ? path.resolve(__dirname, "../../..") : process.resourcesPath;
  const helperPaths = isDev
    ? {
        resourcesRoot: rootDir,
        pythonRuntime: path.join(rootDir, ".venv"),
        backendPython: path.join(rootDir, ".venv", "Scripts", "python.exe"),
        playwrightRoot: process.env.PLAYWRIGHT_BROWSERS_PATH || "",
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
  await waitForBackend(startedUrl, token, backendWaitTimeoutMs, backendLogPaths, backendProcess);
  await publishOdinRuntimeDescriptor(startedUrl, token);
  writeDesktopRuntimeLog(`backend ready after ${Date.now() - backendStartedAt}ms at ${startedUrl}`);
  return startedUrl;
}

async function publishOdinRuntimeDescriptor(url, token) {
  const identity = await httpJson(`${url}${apiPrefix}/system/backend-identity`, 2000, token);
  if (!identity || identity.service !== "cml-backend" || identity.api_prefix !== apiPrefix || !identity.instance_id) {
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
  const manifestReport = await verifyHelperManifest(process.resourcesPath);
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
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
  closeBackendLogStreams();
  backendUrl = null;
  backendUrl = await ensureBackend();
  if (mainWindow && backendUrl) {
    mainWindow.webContents.send("cml:backend-url-changed", backendUrl);
  }
}

async function prepareActiveVaultPath(targetPath) {
  pendingActiveVaultPath = targetPath;
  await fs.mkdir(path.join(targetPath, ".vault"), { recursive: true });
  await restartBackend();
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
  await fs.writeFile(
    getActiveVaultConfigPath(),
    JSON.stringify({ path: targetPath, updated_at: new Date().toISOString() }, null, 2),
    "utf8",
  );
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

async function findExistingCurrentBackend(token) {
  const candidates = [
    process.env.VITE_CML_BACKEND_URL,
    process.env.CML_BACKEND_URL,
    "http://127.0.0.1:7342",
    ...Array.from({ length: 13 }, (_value, index) => `http://127.0.0.1:${7343 + index}`),
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
    .catch(async (error) => {
      // In pre-vault mode, private API routes intentionally return 409 until
      // setup completes. That still means the backend is alive and current.
      if (error instanceof HttpStatusError && error.statusCode === 409) {
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

async function waitForBackend(url, token, timeoutMs, backendLogPaths = null, childProcess = null) {
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
      if (await isCurrentBackend(url, token)) return;
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

app.on("before-quit", () => {
  if (odinRuntimeDescriptorPath) {
    try {
      fsSync.rmSync(odinRuntimeDescriptorPath, { force: true });
    } catch {
      // Expiry and PID validation still reject a descriptor that cannot be removed during shutdown.
    }
  }
  if (rendererServer) {
    rendererServer.close();
  }
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  closeBackendLogStreams();
});
