const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
  openPath: (targetPath) => ipcRenderer.invoke("cml:open-path", targetPath),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("cml:show-item-in-folder", targetPath),
});
