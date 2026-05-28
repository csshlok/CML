const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");

const isDev = !app.isPackaged;
const devUrl = process.env.CML_DESKTOP_DEV_URL || "http://127.0.0.1:5173";
const supportedSourceExtensions = new Set([".txt", ".md", ".markdown", ".docx", ".pdf"]);
const skippedFolderNames = new Set([".git", "node_modules", ".venv", "dist", "build"]);

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

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

async function collectSupportedFiles(targetPath, files) {
  let stat;
  try {
    stat = await fs.stat(targetPath);
  } catch {
    return;
  }

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

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
