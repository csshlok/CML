import { createChromePopupDeps, createPopupController } from "./popup-core.js";

const setupJson = document.getElementById("setupJson");
const backendUrlInput = document.getElementById("backendUrl");
const tokenInput = document.getElementById("token");
const vaultIdInput = document.getElementById("vaultId");
const clusterIdInput = document.getElementById("clusterId");
const uploadFileInput = document.getElementById("uploadFile");
const statusNode = document.getElementById("status");
const controller = createPopupController(createChromePopupDeps(chrome, fetch));

document.getElementById("importSetup").addEventListener("click", async () => {
  try {
    const parsed = await controller.importSetup(setupJson.value);
    backendUrlInput.value = parsed.backendUrl;
    tokenInput.value = parsed.token;
    vaultIdInput.value = parsed.vaultId;
    clusterIdInput.value = parsed.clusterId;
    setStatus("Setup imported and saved.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("saveConfig").addEventListener("click", async () => {
  try {
    await controller.persistConfig(readInputs());
    setStatus("Extension config saved.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("checkStatus").addEventListener("click", async () => {
  try {
    const payload = await controller.checkStatus(readInputs());
    setStatus(payload.detail || "Extension capture is available.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("capturePage").addEventListener("click", async () => {
  await dispatchCapture("page");
});

document.getElementById("captureSelection").addEventListener("click", async () => {
  await dispatchCapture("selection");
});

document.getElementById("capturePdfUrl").addEventListener("click", async () => {
  await dispatchCapture("pdf_url");
});

document.getElementById("captureScreenshot").addEventListener("click", async () => {
  await dispatchCapture("screenshot");
});

document.getElementById("uploadFileButton").addEventListener("click", async () => {
  await uploadSelectedFile();
});

void loadConfig();

async function loadConfig() {
  const stored = await controller.loadConfig();
  backendUrlInput.value = stored.backendUrl || "";
  tokenInput.value = stored.token || "";
  vaultIdInput.value = stored.vaultId || "";
  clusterIdInput.value = stored.clusterId || "";
}

async function dispatchCapture(captureMode) {
  try {
    await controller.persistConfig(readInputs());
    setStatus(statusMessageForCapture(captureMode));
    await controller.dispatchCapture(captureMode, readInputs());
    setStatus(`Saved to CML as ${captureMode}.`, "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function uploadSelectedFile() {
  try {
    const file = uploadFileInput.files?.[0];
    if (!file) {
      throw new Error("Choose a file before saving.");
    }
    await controller.persistConfig(readInputs());
    setStatus(`Uploading ${file.name}...`);
    await controller.uploadLocalFile(file, readInputs());
    uploadFileInput.value = "";
    setStatus(`Saved ${file.name} to CML.`, "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function readInputs() {
  return {
    backendUrl: backendUrlInput.value,
    token: tokenInput.value,
    vaultId: vaultIdInput.value,
    clusterId: clusterIdInput.value,
  };
}

function setStatus(message, state = "") {
  statusNode.textContent = message;
  if (state) {
    statusNode.dataset.state = state;
  } else {
    delete statusNode.dataset.state;
  }
}

function statusMessageForCapture(captureMode) {
  if (captureMode === "page") return "Saving current page...";
  if (captureMode === "selection") return "Saving selected text...";
  if (captureMode === "pdf_url") return "Saving PDF URL...";
  if (captureMode === "screenshot") return "Saving screenshot...";
  return "Saving to CML...";
}
