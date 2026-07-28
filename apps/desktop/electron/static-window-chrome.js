(() => {
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
