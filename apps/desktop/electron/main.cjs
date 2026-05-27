const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const path = require("node:path");

const isDev = !app.isPackaged;
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "CML",
    backgroundColor: "#fbfaf6",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  window.once("ready-to-show", () => {
    window.show();
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    window.loadURL(devUrl);
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    window.loadFile(path.join(__dirname, "../dist/client/index.html"));
  }
}

app.whenReady().then(() => {
  ipcMain.handle("cml:open-path", async (_event, targetPath) => {
    if (typeof targetPath !== "string" || targetPath.length === 0) return false;
    const error = await shell.openPath(targetPath);
    return error.length === 0;
  });

  ipcMain.handle("cml:show-item-in-folder", async (_event, targetPath) => {
    if (typeof targetPath !== "string" || targetPath.length === 0) return false;
    shell.showItemInFolder(targetPath);
    return true;
  });

  ipcMain.handle("cml:select-source-files", async () => {
    const result = await dialog.showOpenDialog({
      title: "Add sources",
      properties: ["openFile", "multiSelections"],
      filters: [
        { name: "Text and Markdown", extensions: ["txt", "md", "markdown"] },
        { name: "All files", extensions: ["*"] },
      ],
    });
    if (result.canceled) return [];
    return result.filePaths;
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
