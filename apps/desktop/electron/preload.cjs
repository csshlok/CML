const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  selectSourceFiles: () => ipcRenderer.invoke("cml:select-source-files"),
  selectSourceFolders: () => ipcRenderer.invoke("cml:select-source-folders"),
  selectVaultFolder: () => ipcRenderer.invoke("cml:select-vault-folder"),
  selectCoverImage: () => ipcRenderer.invoke("cml:select-cover-image"),
  getBackendUrl: () => ipcRenderer.invoke("cml:get-backend-url"),
  listSupportedFiles: (targetPaths) => ipcRenderer.invoke("cml:list-supported-files", targetPaths),
  getDroppedFilePaths: (files) =>
    Array.from(files)
      .map((file) => webUtils.getPathForFile(file))
      .filter(Boolean),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
