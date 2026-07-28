const { contextBridge, ipcRenderer, webUtils } = require("electron");

// Sandboxed Electron preloads can only require a small built-in module set.
// Keep this entry point self-contained so the packaged app does not lose its
// desktop bridge when app.asar is loaded.
function createDroppedFilePathStore(target, getPathForFile) {
  let pendingPaths = [];
  target.addEventListener(
    "drop",
    (event) => {
      const files = event?.dataTransfer?.files;
      pendingPaths = files
        ? Array.from(files)
            .map((file) => {
              try {
                return getPathForFile(file);
              } catch {
                return "";
              }
            })
            .filter(Boolean)
        : [];
    },
    true,
  );
  return {
    consume() {
      const paths = pendingPaths;
      pendingPaths = [];
      return paths;
    },
  };
}

function cleanIpcErrorMessage(error, fallback) {
  const raw = error instanceof Error ? error.message : String(error || "");
  const remotePrefix = /^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/i;
  return raw.replace(remotePrefix, "").trim() || fallback;
}

async function invokeWithCleanError(renderer, channel, fallback) {
  try {
    return await renderer.invoke(channel);
  } catch (error) {
    throw new Error(cleanIpcErrorMessage(error, fallback));
  }
}

let rendererReadySent = false;
const droppedFilePaths = createDroppedFilePathStore(window, (file) =>
  webUtils.getPathForFile(file),
);

async function notifyRendererReady(detail) {
  if (rendererReadySent) return true;
  rendererReadySent = true;
  try {
    return await ipcRenderer.invoke("cml:renderer-ready", detail);
  } catch {
    rendererReadySent = false;
    return false;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  // Static startup and repair documents use this preload too, but only the
  // packaged HTTP renderer can satisfy the renderer-ready wait.
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    void notifyRendererReady(window.location.pathname || "/");
  }
});

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  windowControls: {
    getState: () => ipcRenderer.invoke("cml:window-get-state"),
    minimize: () => ipcRenderer.invoke("cml:window-minimize"),
    toggleMaximize: () => ipcRenderer.invoke("cml:window-toggle-maximize"),
    close: () => ipcRenderer.invoke("cml:window-close"),
    onStateChanged: (listener) => {
      if (typeof listener !== "function") {
        return () => {};
      }
      const wrapped = (_event, state) => {
        listener(state);
      };
      ipcRenderer.on("cml:window-state-changed", wrapped);
      return () => {
        ipcRenderer.removeListener("cml:window-state-changed", wrapped);
      };
    },
  },
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  openExternal: (url) => ipcRenderer.invoke("cml:open-external", url),
  selectSourceFiles: () => ipcRenderer.invoke("cml:select-source-files"),
  selectSourceFolders: () => ipcRenderer.invoke("cml:select-source-folders"),
  selectEmbeddingFolder: () => ipcRenderer.invoke("cml:select-embedding-folder"),
  selectModelFolder: () => ipcRenderer.invoke("cml:select-model-folder"),
  selectModelCheckpoint: () => ipcRenderer.invoke("cml:select-model-checkpoint"),
  selectVaultFolder: () => ipcRenderer.invoke("cml:select-vault-folder"),
  prepareActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:prepare-active-vault-folder", targetPath),
  setActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:set-active-vault-folder", targetPath),
  moveActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:move-active-vault-folder", targetPath),
  clearActiveVaultFolder: () => ipcRenderer.invoke("cml:clear-active-vault-folder"),
  selectCoverImage: () => ipcRenderer.invoke("cml:select-cover-image"),
  readLocalImage: (targetPath) => ipcRenderer.invoke("cml:read-local-image", targetPath),
  deleteLocalMedia: (mediaId) => ipcRenderer.invoke("cml:delete-local-media", mediaId),
  getBackendUrl: () => ipcRenderer.invoke("cml:get-backend-url"),
  getBackendToken: () => ipcRenderer.invoke("cml:get-backend-token"),
  getMcpFeatureFlags: () => ipcRenderer.invoke("cml:get-mcp-feature-flags"),
  getMcpLauncher: (capabilityProfile) => ipcRenderer.invoke("cml:get-mcp-launcher", capabilityProfile),
  getOdinLauncherStatus: () => ipcRenderer.invoke("cml:get-odin-launcher-status"),
  installOdinLauncher: () =>
    invokeWithCleanError(
      ipcRenderer,
      "cml:install-odin-launcher",
      "Could not install Odin.",
    ),
  startOdinPairing: () =>
    invokeWithCleanError(
      ipcRenderer,
      "cml:start-odin-pairing",
      "Could not start Odin pairing.",
    ),
  getTunnelStatus: () => ipcRenderer.invoke("cml:get-tunnel-status"),
  connectTunnel: (configuration) => ipcRenderer.invoke("cml:connect-tunnel", configuration),
  reconnectTunnel: (bridgeToken) => ipcRenderer.invoke("cml:reconnect-tunnel", bridgeToken),
  disconnectTunnel: (forget) => ipcRenderer.invoke("cml:disconnect-tunnel", forget),
  openTunnelUi: () => ipcRenderer.invoke("cml:open-tunnel-ui"),
  onTunnelStatusChanged: (listener) => {
    if (typeof listener !== "function") return () => {};
    const wrapped = (_event, status) => listener(status);
    ipcRenderer.on("cml:tunnel-status-changed", wrapped);
    return () => ipcRenderer.removeListener("cml:tunnel-status-changed", wrapped);
  },
  getSetupState: () => ipcRenderer.invoke("cml:get-setup-state"),
  updateSetupState: (patch) => ipcRenderer.invoke("cml:update-setup-state", patch),
  resetAppSetup: () => ipcRenderer.invoke("cml:reset-app-setup"),
  finalizeActiveVaultDeletion: () => ipcRenderer.invoke("cml:finalize-active-vault-deletion"),
  notifyRendererReady: (detail) => notifyRendererReady(detail),
  onBackendUrlChanged: (listener) => {
    if (typeof listener !== "function") {
      return () => {};
    }
    const wrapped = (_event, nextUrl) => {
      listener(nextUrl ?? null);
    };
    ipcRenderer.on("cml:backend-url-changed", wrapped);
    return () => {
      ipcRenderer.removeListener("cml:backend-url-changed", wrapped);
    };
  },
  copyText: (value) => ipcRenderer.invoke("cml:copy-text", value),
  retryStartup: () => ipcRenderer.invoke("cml:retry-startup"),
  openVaultAnyway: () => ipcRenderer.invoke("cml:open-vault-anyway"),
  listSupportedFiles: (targetPaths) => ipcRenderer.invoke("cml:list-supported-files", targetPaths),
  scanSupportedFiles: (targetPaths, limit) =>
    ipcRenderer.invoke("cml:scan-supported-files", targetPaths, limit),
  getDroppedFilePaths: () => droppedFilePaths.consume(),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
