import { apiPath, normalizeApiPrefix, normalizeBackendUrl, parseSetupJson } from "./extension-core.js";

export function createPopupController(deps) {
  return {
    async loadConfig() {
      return deps.getStoredConfig();
    },
    async importSetup(rawSetupJson) {
      const parsed = parseSetupJson(rawSetupJson);
      const config = {
        backendUrl: parsed.backendUrl,
        apiPrefix: parsed.apiPrefix,
        token: parsed.token,
        vaultId: parsed.vaultId,
        clusterId: parsed.clusterId,
        vaultPath: parsed.vaultPath,
        browser: parsed.browser,
        clientName: parsed.clientName,
        installTargets: parsed.installTargets,
        primaryActions: parsed.primaryActions,
        optionalActions: parsed.optionalActions,
      };
      await deps.saveConfig(config);
      return config;
    },
    async persistConfig(input = null) {
      const current = input || (await deps.getStoredConfig());
      const config = {
        backendUrl: normalizeBackendUrl(current.backendUrl),
        apiPrefix: normalizeApiPrefix(current.apiPrefix),
        token: String(current.token || "").trim(),
        vaultId: String(current.vaultId || "").trim(),
        clusterId: String(current.clusterId || "").trim(),
        vaultPath: String(current.vaultPath || "").trim(),
        browser: String(current.browser || "chrome").trim().toLowerCase() || "chrome",
        clientName: String(current.clientName || "Browser extension").trim() || "Browser extension",
        installTargets: Array.isArray(current.installTargets) ? current.installTargets : [],
        primaryActions: Array.isArray(current.primaryActions) ? current.primaryActions : [],
        optionalActions: Array.isArray(current.optionalActions) ? current.optionalActions : [],
      };
      if (!config.token) {
        throw new Error("Import setup from the CML desktop app before capturing.");
      }
      await deps.saveConfig(config);
      return config;
    },
    async checkStatus(input = null) {
      const config = await this.persistConfig(input);
      return deps.checkStatus(config);
    },
    async dispatchCapture(captureMode, input = null) {
      await this.persistConfig(input);
      return deps.sendCaptureMessage(captureMode);
    },
    async uploadLocalFile(file, input = null) {
      const config = await this.persistConfig(input);
      const upload = await deps.readLocalFile(file);
      return deps.uploadCapture(config, upload);
    },
  };
}

export function createChromePopupDeps(chromeApi, fetchImpl) {
  return {
    async getStoredConfig() {
      const stored = await chromeApi.storage.local.get([
        "backendUrl",
        "apiPrefix",
        "token",
        "vaultId",
        "clusterId",
        "vaultPath",
        "browser",
        "clientName",
        "installTargets",
        "primaryActions",
        "optionalActions",
      ]);
      return {
        backendUrl: stored.backendUrl || "",
        apiPrefix: stored.apiPrefix || "",
        token: stored.token || "",
        vaultId: stored.vaultId || "",
        clusterId: stored.clusterId || "",
        vaultPath: stored.vaultPath || "",
        browser: stored.browser || "chrome",
        clientName: stored.clientName || "Browser extension",
        installTargets: stored.installTargets || [],
        primaryActions: stored.primaryActions || [],
        optionalActions: stored.optionalActions || [],
      };
    },
    async saveConfig(config) {
      await chromeApi.storage.local.set(config);
    },
    async checkStatus(config) {
      const response = await fetchImpl(`${config.backendUrl}${apiPath(config, "/extension/status")}`, {
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
      const response = await fetchImpl(`${config.backendUrl}${apiPath(config, "/extension/capture-upload")}`, {
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
