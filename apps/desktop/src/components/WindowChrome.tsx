import { useEffect, useState } from "react";

const DEFAULT_WINDOW_STATE: DesktopWindowState = {
  maximized: false,
  fullScreen: false,
};

export function WindowChrome() {
  const controls = window.cmlDesktop?.windowControls;
  const [windowState, setWindowState] = useState(DEFAULT_WINDOW_STATE);

  useEffect(() => {
    if (!controls) return;

    let active = true;
    void controls.getState().then((state) => {
      if (active) setWindowState(state);
    });
    const unsubscribe = controls.onStateChanged((state) => {
      if (active) setWindowState(state);
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [controls]);

  const isExpanded = windowState.maximized || windowState.fullScreen;

  return (
    <header
      className="vault-window-chrome"
      data-testid="window-chrome"
      aria-hidden={controls ? undefined : true}
    >
      {controls ? <div
        className="vault-window-controls"
        data-window-control-safe-zone=""
        aria-label="Window controls"
      >
        <button
          type="button"
          className="vault-window-control"
          aria-label="Minimize"
          title="Minimize"
          onClick={() => void controls.minimize()}
        >
          <span className="vault-window-icon vault-window-icon-minimize" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="vault-window-control"
          aria-label={isExpanded ? "Restore" : "Maximize"}
          title={isExpanded ? "Restore" : "Maximize"}
          onClick={() => void controls.toggleMaximize().then(setWindowState)}
        >
          <span
            className={`vault-window-icon ${
              isExpanded ? "vault-window-icon-restore" : "vault-window-icon-maximize"
            }`}
            aria-hidden="true"
          />
        </button>
        <button
          type="button"
          className="vault-window-control vault-window-control-close"
          aria-label="Close"
          title="Close"
          onClick={() => void controls.close()}
        >
          <span className="vault-window-icon vault-window-icon-close" aria-hidden="true" />
        </button>
      </div> : null}
    </header>
  );
}
