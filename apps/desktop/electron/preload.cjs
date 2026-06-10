const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  selectSourceFiles: () => ipcRenderer.invoke("cml:select-source-files"),
  selectSourceFolders: () => ipcRenderer.invoke("cml:select-source-folders"),
  selectEmbeddingFolder: () => ipcRenderer.invoke("cml:select-embedding-folder"),
  selectModelFolder: () => ipcRenderer.invoke("cml:select-model-folder"),
  selectVaultFolder: () => ipcRenderer.invoke("cml:select-vault-folder"),
  setActiveVaultFolder: (targetPath) => ipcRenderer.invoke("cml:set-active-vault-folder", targetPath),
  selectCoverImage: () => ipcRenderer.invoke("cml:select-cover-image"),
  getBackendUrl: () => ipcRenderer.invoke("cml:get-backend-url"),
  getBackendToken: () => ipcRenderer.invoke("cml:get-backend-token"),
  notifyRendererReady: (detail) => ipcRenderer.invoke("cml:renderer-ready", detail),
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
  getDroppedFilePaths: (files) =>
    Array.from(files)
      .map((file) => webUtils.getPathForFile(file))
      .filter(Boolean),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
