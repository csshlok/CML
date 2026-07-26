const WINDOW_STATE_CHANNEL = "cml:window-state-changed";

function windowState(window) {
  return {
    maximized: Boolean(window && !window.isDestroyed() && window.isMaximized()),
    fullScreen: Boolean(window && !window.isDestroyed() && window.isFullScreen()),
  };
}

function resolveSenderWindow(BrowserWindow, event) {
  const sender = event?.sender;
  if (!sender) return null;
  const window = BrowserWindow.fromWebContents(sender);
  if (!window || window.isDestroyed()) return null;
  return window;
}

function sendWindowState(window) {
  if (!window || window.isDestroyed() || window.webContents.isDestroyed()) return;
  window.webContents.send(WINDOW_STATE_CHANNEL, windowState(window));
}

function attachWindowStateEvents(window) {
  const notify = () => sendWindowState(window);
  window.on("maximize", notify);
  window.on("unmaximize", notify);
  window.on("enter-full-screen", notify);
  window.on("leave-full-screen", notify);
}

function registerWindowControlHandlers({ ipcMain, BrowserWindow }) {
  ipcMain.handle("cml:window-get-state", (event) => {
    return windowState(resolveSenderWindow(BrowserWindow, event));
  });
  ipcMain.handle("cml:window-minimize", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return false;
    window.minimize();
    return true;
  });
  ipcMain.handle("cml:window-toggle-maximize", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return windowState(null);
    if (window.isFullScreen()) {
      window.setFullScreen(false);
    } else if (window.isMaximized()) {
      window.unmaximize();
    } else {
      window.maximize();
    }
    return windowState(window);
  });
  ipcMain.handle("cml:window-close", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return false;
    window.close();
    return true;
  });
}

module.exports = {
  WINDOW_STATE_CHANNEL,
  attachWindowStateEvents,
  registerWindowControlHandlers,
  resolveSenderWindow,
  sendWindowState,
  windowState,
};
