(() => {
  // Theme reactor shared by every static Electron document (startup, repair).
  // preload.cjs already applies the resolved theme to <html> before this
  // deferred script runs (data-theme/.dark/color-scheme), so this only needs
  // to (a) react to live main-process broadcasts while the document stays
  // open, and (b) fall back to the OS media query if the pre-paint snapshot
  // never landed (theme IPC unavailable) so these documents stay themed
  // even when the rest of the app cannot start.
  const root = document.documentElement;
  const applyTheme = (resolved) => {
    if (resolved !== "light" && resolved !== "dark") return;
    root.setAttribute("data-theme", resolved);
    root.classList.toggle("dark", resolved === "dark");
    root.style.colorScheme = resolved;
  };

  const desktop = window.cmlDesktop;
  const hasThemeBridge = typeof desktop?.onThemeChanged === "function";
  if (hasThemeBridge) {
    desktop.onThemeChanged((snapshot) => {
      applyTheme(snapshot?.resolved);
    });
  }

  if (!root.hasAttribute("data-theme")) {
    let media = null;
    try {
      media = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      media = null;
    }
    applyTheme(media?.matches ? "dark" : "light");
    if (!hasThemeBridge) {
      media?.addEventListener?.("change", (event) => {
        applyTheme(event.matches ? "dark" : "light");
      });
    }
  }

  const bridge = window.cmlDesktop?.windowControls;
  const controls = document.querySelector(".vault-static-window-controls");
  if (!controls) return;

  const minimizeButton = controls.querySelector('[data-action="minimize"]');
  const maximizeButton = controls.querySelector('[data-action="maximize"]');
  const closeButton = controls.querySelector('[data-action="close"]');

  const setWindowState = (state = {}) => {
    const maximized = Boolean(state.maximized || state.fullScreen);
    maximizeButton?.setAttribute("data-maximized", String(maximized));
    maximizeButton?.setAttribute("aria-label", maximized ? "Restore" : "Maximize");
    maximizeButton?.setAttribute("title", maximized ? "Restore" : "Maximize");
  };

  if (!bridge) {
    controls.dataset.unavailable = "true";
    for (const button of controls.querySelectorAll("button")) {
      button.disabled = true;
    }
    return;
  }

  minimizeButton?.addEventListener("click", () => {
    void bridge.minimize();
  });
  maximizeButton?.addEventListener("click", async () => {
    setWindowState(await bridge.toggleMaximize());
  });
  closeButton?.addEventListener("click", () => {
    void bridge.close();
  });

  void bridge.getState().then(setWindowState);
  bridge.onStateChanged(setWindowState);
})();
