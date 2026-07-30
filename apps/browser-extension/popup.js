import { createChromePopupDeps, createPopupController } from "./popup-core.js";

const setupJson = document.getElementById("setupJson");
const setupSummary = document.getElementById("setupSummary");
const statusNode = document.getElementById("status");
const capturePreview = document.getElementById("capturePreview");
const capturePdfLink = document.getElementById("capturePdfLink");
const captureFile = document.getElementById("captureFile");
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
  await dispatchCapture("page", "Saving page…");
});

document.getElementById("captureSelection").addEventListener("click", async () => {
  await dispatchCapture("selection", "Saving selection…");
});

capturePdfLink.addEventListener("click", async () => {
  await dispatchCapture("pdf_url", "Saving PDF link…");
});

document.getElementById("captureScreenshot").addEventListener("click", async () => {
  await dispatchCapture("screenshot", "Saving screenshot…");
});

captureFile.addEventListener("change", async () => {
  const file = captureFile.files?.[0];
  if (!file) return;
  try {
    setStatus("Saving file…");
    await controller.uploadLocalFile(file);
    setStatus("File saved.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    captureFile.value = "";
  }
});

void Promise.all([renderSummary(), renderCapturePreview()]);

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
    : `<div>Import setup from Vault to enable capture.</div>`;
}

async function renderCapturePreview() {
  try {
    const preview = await controller.getCapturePreview();
    capturePreview.innerHTML = `
      <strong>${escapeHtml(preview.title || "Untitled page")}</strong>
      <span>${escapeHtml(preview.origin || "Local page")}</span>
    `;
    capturePdfLink.hidden = !preview.pdf;
  } catch (error) {
    capturePreview.textContent = error.message;
    capturePdfLink.hidden = true;
  }
}

async function dispatchCapture(captureMode, message) {
  try {
    setStatus(message);
    await controller.dispatchCapture(captureMode);
    const messages = {
      page: "Page saved.",
      selection: "Selection saved.",
      pdf_url: "PDF link saved.",
      screenshot: "Screenshot saved.",
    };
    setStatus(messages[captureMode] || "Saved.", "success");
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
