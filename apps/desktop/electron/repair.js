(() => {
  const params = new URLSearchParams(window.location.search);
  let repair;
  try {
    repair = JSON.parse(params.get("state") || "{}");
  } catch {
    repair = {};
  }

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value || "");
  };

  setText("repair-heading", repair.heading || "Vault could not open.");
  setText("repair-detail", repair.detail || "The app did not finish starting.");
  setText("guidance-title", repair.guidanceTitle || "Try opening Vault again.");
  setText("guidance-body", repair.guidanceBody || "If the same message returns, copy the details before closing Vault.");

  const fields = document.getElementById("repair-fields");
  if (repair.showFields && fields) {
    fields.hidden = false;
    setText("repair-phase", repair.phase || "startup_failed");
    setText("repair-data-directory", repair.dataDirectory || "Unknown");
    setText("repair-database", repair.database || "Unknown");
  }

  const bridge = window.cmlDesktop;
  const status = document.getElementById("repair-status");
  const retryButton = document.getElementById("retry-button");
  const openAnywayButton = document.getElementById("open-anyway-button");
  const copyButton = document.getElementById("copy-details-button");
  const closeButton = document.getElementById("close-button");

  if (repair.allowOpenAnyway && openAnywayButton) {
    openAnywayButton.hidden = false;
  }

  const showStatus = (message) => {
    if (status) status.textContent = message;
  };

  retryButton?.addEventListener("click", async () => {
    retryButton.disabled = true;
    showStatus("Restarting Vault...");
    try {
      await bridge?.retryStartup?.();
    } catch {
      retryButton.disabled = false;
      showStatus("Vault could not restart. Copy the details and close Vault.");
    }
  });

  openAnywayButton?.addEventListener("click", async () => {
    openAnywayButton.disabled = true;
    showStatus("Checking the library...");
    try {
      await bridge?.openVaultAnyway?.();
      openAnywayButton.disabled = false;
      showStatus("");
    } catch {
      openAnywayButton.disabled = false;
      showStatus("The library could not be opened.");
    }
  });

  copyButton?.addEventListener("click", async () => {
    try {
      if (!bridge?.copyText) throw new Error("Clipboard bridge unavailable");
      await bridge.copyText(repair.diagnosticText || repair.detail || "");
      copyButton.textContent = "Copied details";
      showStatus("");
    } catch {
      copyButton.textContent = "Copy failed";
      showStatus("The details could not be copied.");
    }
  });

  closeButton?.addEventListener("click", async () => {
    try {
      if (!bridge?.windowControls?.close) throw new Error("Window bridge unavailable");
      await bridge.windowControls.close();
    } catch {
      showStatus("Close Vault with Alt+F4.");
    }
  });

  if (!bridge) {
    retryButton.disabled = true;
    openAnywayButton.disabled = true;
    copyButton.disabled = true;
    showStatus("Desktop controls are unavailable. Close Vault with Alt+F4.");
  }
})();
