import { createChromePopupDeps, createPopupController } from "./popup-core.js";

const setupJson = document.getElementById("setupJson");
const setupSummary = document.getElementById("setupSummary");
const statusNode = document.getElementById("status");
const controller = createPopupController(createChromePopupDeps(chrome, fetch));

document.getElementById("importSetup").addEventListener("click", async () => {
  try {
    await controller.importSetup(setupJson.value);
    await renderSummary();
    setStatus("Extension setup imported.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("checkStatus").addEventListener("click", async () => {
  try {
    const payload = await controller.checkStatus();
    setStatus(payload.detail || "Extension capture is available.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("capturePage").addEventListener("click", async () => {
  await dispatchCapture("page", "Saving current page...");
});

document.getElementById("captureScreenshot").addEventListener("click", async () => {
  await dispatchCapture("screenshot", "Taking screenshot...");
});

void renderSummary();

async function renderSummary() {
  const stored = await controller.loadConfig();
  const ready = Boolean(stored.token && stored.vaultId);
  setupSummary.innerHTML = ready
    ? `
      <div><strong>Vault:</strong> ${escapeHtml(stored.vaultId)}</div>
      <div><strong>Cluster:</strong> ${escapeHtml(stored.clusterId || "None")}</div>
      <div><strong>Backend:</strong> ${escapeHtml(stored.backendUrl || "")}</div>
      <div><strong>Save root:</strong> ${escapeHtml(stored.vaultPath || "Managed by desktop")}</div>
    `
    : `<div>Import setup from the CML desktop app to enable capture.</div>`;
}

async function dispatchCapture(captureMode, message) {
  try {
    setStatus(message);
    await controller.dispatchCapture(captureMode);
    setStatus(captureMode === "page" ? "Saved link to vault." : "Screenshot saved to vault.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function setStatus(message, state = "") {
  statusNode.textContent = message;
  if (state) {
    statusNode.dataset.state = state;
  } else {
    delete statusNode.dataset.state;
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
