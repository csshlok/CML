import { normalizeBackendUrl, parseSetupJson } from "./extension-core.js";

export function createPopupController(deps) {
  return {
    async loadConfig() {
      return deps.getStoredConfig();
    },
    async importSetup(rawSetupJson) {
      const parsed = parseSetupJson(rawSetupJson);
      const config = {
        backendUrl: parsed.backendUrl,
        token: parsed.token,
        vaultId: parsed.vaultId,
        clusterId: parsed.clusterId,
      };
      await deps.saveConfig(config);
      return config;
    },
    async persistConfig(input) {
      const config = {
        backendUrl: normalizeBackendUrl(input.backendUrl),
        token: String(input.token || "").trim(),
        vaultId: String(input.vaultId || "").trim(),
        clusterId: String(input.clusterId || "").trim(),
      };
      if (!config.token) {
        throw new Error("Paste an extension token before saving.");
      }
      await deps.saveConfig(config);
      return config;
    },
    async checkStatus(input) {
      const config = await this.persistConfig(input);
      return deps.checkStatus(config);
    },
    async dispatchCapture(captureMode, input) {
      await this.persistConfig(input);
      return deps.sendCaptureMessage(captureMode);
    },
    async uploadLocalFile(file, input) {
      const config = await this.persistConfig(input);
      const upload = await deps.readLocalFile(file);
      return deps.uploadCapture(config, upload);
    },
  };
}

export function createChromePopupDeps(chromeApi, fetchImpl) {
  return {
    async getStoredConfig() {
      const stored = await chromeApi.storage.local.get(["backendUrl", "token", "vaultId", "clusterId"]);
      return {
        backendUrl: stored.backendUrl || "",
        token: stored.token || "",
        vaultId: stored.vaultId || "",
        clusterId: stored.clusterId || "",
      };
    },
    async saveConfig(config) {
      await chromeApi.storage.local.set(config);
    },
    async checkStatus(config) {
      const response = await fetchImpl(`${config.backendUrl}/api/v1/extension/status`, {
        headers: {
          "x-cml-extension-token": config.token,
        },
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.detail || `Status check failed with HTTP ${response.status}.`);
      }
      return payload;
    },
    async sendCaptureMessage(captureMode) {
      const response = await chromeApi.runtime.sendMessage({ type: "cml:capture", captureMode });
      if (!response?.ok) {
        throw new Error(response?.error || "Capture did not complete.");
      }
      return response.result;
    },
    async readLocalFile(file) {
      const payload = await readBrowserFile(file);
      return {
        captureType: "file",
        title: payload.fileName,
        fileName: payload.fileName,
        mimeType: payload.mimeType,
        contentBase64: payload.contentBase64,
      };
    },
    async uploadCapture(config, upload) {
      const response = await fetchImpl(`${config.backendUrl}/api/v1/extension/capture-upload`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-cml-extension-token": config.token,
        },
        body: JSON.stringify({
          vault_id: config.vaultId,
          cluster_id: config.clusterId || null,
          capture_type: upload.captureType || "file",
          title: upload.title,
          url: upload.url || "",
          file_name: upload.fileName,
          mime_type: upload.mimeType || "",
          content_base64: upload.contentBase64,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || `Upload failed with HTTP ${response.status}.`);
      }
      return payload;
    },
  };
}

async function readBrowserFile(file) {
  const name = String(file?.name || "").trim();
  if (!name) {
    throw new Error("Choose a file before saving.");
  }
  const buffer = await file.arrayBuffer();
  if (!buffer || buffer.byteLength === 0) {
    throw new Error("The selected file is empty.");
  }
  return {
    fileName: name,
    mimeType: String(file.type || "").trim(),
    contentBase64: bytesToBase64(new Uint8Array(buffer)),
  };
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}
