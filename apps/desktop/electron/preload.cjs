const { contextBridge, ipcRenderer, webUtils } = require("electron");

let rendererReadySent = false;

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
  // Startup/renderer repair screens are data URLs that also use this preload.
  // They must not satisfy the packaged-app smoke test or renderer-ready wait.
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    void notifyRendererReady(window.location.pathname || "/");
  }
});

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  openExternal: (url) => ipcRenderer.invoke("cml:open-external", url),
  selectSourceFiles: () => ipcRenderer.invoke("cml:select-source-files"),
  selectSourceFolders: () => ipcRenderer.invoke("cml:select-source-folders"),
  selectEmbeddingFolder: () => ipcRenderer.invoke("cml:select-embedding-folder"),
  selectModelFolder: () => ipcRenderer.invoke("cml:select-model-folder"),
  selectVaultFolder: () => ipcRenderer.invoke("cml:select-vault-folder"),
  prepareActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:prepare-active-vault-folder", targetPath),
  setActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:set-active-vault-folder", targetPath),
  clearActiveVaultFolder: () => ipcRenderer.invoke("cml:clear-active-vault-folder"),
  selectCoverImage: () => ipcRenderer.invoke("cml:select-cover-image"),
  getBackendUrl: () => ipcRenderer.invoke("cml:get-backend-url"),
  getBackendToken: () => ipcRenderer.invoke("cml:get-backend-token"),
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
  getDroppedFilePaths: (files) =>
    Array.from(files)
      .map((file) => webUtils.getPathForFile(file))
      .filter(Boolean),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
