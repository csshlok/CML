const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  selectSourceFiles: () => ipcRenderer.invoke("cml:select-source-files"),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
