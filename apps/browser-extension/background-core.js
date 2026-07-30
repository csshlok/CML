import {
  buildExtensionCaptureRequest,
  buildExtensionUploadRequest,
  derivePageCaptureTitle,
  apiPath,
  normalizeApiPrefix,
  normalizeBackendUrl,
  parseDataUrl,
  sanitizeUploadFileName,
  trimPageText,
} from "./extension-core.js";

export function createBackgroundController(deps) {
  return {
    async handleCapture(message) {
      const config = await deps.loadConfig();
      const tab = await deps.getCaptureTab();
      if (!tab?.id) {
        throw new Error("No capture-ready browser tab is available.");
      }
      if (message.captureMode === "selection") {
        const selection = await deps.readSelectionFromTab(tab.id, tab.url || "");
        await verifyTab(deps, tab);
        const payload = buildExtensionCaptureRequest({
          vaultId: config.vaultId,
          clusterId: config.clusterId,
          captureType: "selection",
          title: selection.title || tab.title || "Saved selection",
          url: tab.url || "",
          text: selection.text,
        });
        return deps.postCapture(config, payload);
      }
      if (message.captureMode === "pdf_url") {
        if (!isPdfLikeUrl(tab.url || "")) {
          throw new Error("The current tab does not look like a PDF URL.");
        }
        await verifyTab(deps, tab);
        const payload = buildExtensionCaptureRequest({
          vaultId: config.vaultId,
          clusterId: config.clusterId,
          captureType: "file",
          title: derivePdfCaptureTitle(tab.title, tab.url),
          url: tab.url || "",
          text: buildPdfCaptureText(tab),
        });
        return deps.postCapture(config, payload);
      }
      if (message.captureMode === "screenshot") {
        await deps.focusTab(tab.id);
        await verifyTab(deps, tab);
        const imageDataUrl = await deps.captureVisibleTab(tab.windowId);
        await verifyTab(deps, tab);
        const imagePayload = parseDataUrl(imageDataUrl);
        const payload = buildExtensionUploadRequest({
          vaultId: config.vaultId,
          clusterId: config.clusterId,
          captureType: "screenshot",
          title: deriveScreenshotTitle(tab),
          url: tab.url || "",
          fileName: deriveScreenshotFileName(tab),
          mimeType: imagePayload.mimeType,
          contentBase64: imagePayload.contentBase64,
        });
        return deps.postUploadCapture(config, payload);
      }
      const page = await deps.readPageFromTab(tab.id);
      await verifyTab(deps, tab);
      const payload = buildExtensionCaptureRequest({
        vaultId: config.vaultId,
        clusterId: config.clusterId,
        captureType: "page",
        title: derivePageCaptureTitle({ title: page.title || tab.title, hostname: safeHostname(tab.url) }),
        url: tab.url || "",
        text: trimPageText(page.text),
      });
      return deps.postCapture(config, payload);
    },
    async handleCommand(command) {
      const normalized = String(command || "").trim().toLowerCase();
      if (normalized === "capture_screenshot") {
        return this.handleCapture({ captureMode: "screenshot" });
      }
      return null;
    },
  };
}

export function createChromeBackgroundDeps(chromeApi, fetchImpl) {
  return {
    async loadConfig() {
      const stored = await chromeApi.storage.local.get(["backendUrl", "apiPrefix", "token", "vaultId", "clusterId"]);
      return {
        backendUrl: normalizeBackendUrl(stored.backendUrl),
        apiPrefix: normalizeApiPrefix(stored.apiPrefix),
        token: String(stored.token || "").trim(),
        vaultId: String(stored.vaultId || "").trim(),
        clusterId: String(stored.clusterId || "").trim(),
      };
    },
    async getCaptureTab() {
      const tabs = await chromeApi.tabs.query({ active: true, currentWindow: true });
      return tabs.find((tab) => isCaptureCandidateTab(tab)) || null;
    },
    async focusTab(tabId) {
      await chromeApi.tabs.update(tabId, { active: true });
    },
    async assertTabUnchanged(tab) {
      const current = await chromeApi.tabs.get(tab.id);
      if (
        !current ||
        current.id !== tab.id ||
        String(current.url || "") !== String(tab.url || "")
      ) {
        throw new Error("The page changed before capture finished. Try again.");
      }
    },
    async postCapture(config, payload) {
      return postJsonCapture(config, payload, fetchImpl, "capture");
    },
    async postUploadCapture(config, payload) {
      return postJsonCapture(config, payload, fetchImpl, "capture-upload");
    },
    async captureVisibleTab(windowId) {
      return chromeApi.tabs.captureVisibleTab(typeof windowId === "number" ? windowId : undefined, {
        format: "png",
      });
    },
    async readSelectionFromTab(tabId, expectedUrl) {
      const nonce = createCaptureNonce();
      try {
        const fromContent = await chromeApi.tabs.sendMessage(tabId, {
          type: "cml:get-selection",
          nonce,
          consume: true,
        });
        if (
          fromContent?.nonce === nonce &&
          (!expectedUrl || String(fromContent?.url || "") === String(expectedUrl)) &&
          String(fromContent?.text || "").trim()
        ) {
          return {
            title: String(fromContent.title || "").trim(),
            text: String(fromContent.text || "").trim(),
            url: String(fromContent.url || "").trim(),
          };
        }
      } catch {
        // Fall back to a one-time isolated-world read when the content script is unavailable.
      }
      const [{ result }] = await chromeApi.scripting.executeScript({
        target: { tabId },
        func: () => {
          const selection = window.getSelection()?.toString().trim() || "";
          return {
            title: selection
              ? `Selection from ${document.title || location.hostname || "page"}`
              : "",
            text: selection,
            url: location.href,
          };
        },
      });
      const live = result || { title: "", text: "", url: "" };
      if (
        (!expectedUrl || String(live.url || "") === String(expectedUrl)) &&
        String(live.text || "").trim()
      ) {
        return live;
      }
      return { title: "", text: "", url: String(expectedUrl || "") };
    },
    async readPageFromTab(tabId) {
      const [{ result }] = await chromeApi.scripting.executeScript({
        target: { tabId },
        func: () => {
          const title = document.title || "";
          const article = document.querySelector("article");
          const root = article || document.body;
          const text = root?.innerText || "";
          return { title, text };
        },
      });
      return result || { title: "", text: "" };
    },
  };
}

function createCaptureNonce() {
  const values = new Uint32Array(4);
  globalThis.crypto.getRandomValues(values);
  return Array.from(values, (value) => value.toString(16).padStart(8, "0")).join("");
}

async function verifyTab(deps, tab) {
  if (typeof deps.assertTabUnchanged === "function") {
    await deps.assertTabUnchanged(tab);
  }
}

function postJsonCapture(config, payload, fetchImpl, endpoint) {
      if (!config.token) {
        throw new Error("Extension token is missing. Import setup JSON first.");
      }
      return fetchImpl(`${config.backendUrl}${apiPath(config, `/extension/${endpoint}`)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-cml-extension-token": config.token,
        },
        body: JSON.stringify(payload),
      }).then(async (response) => {
        if (!response.ok) {
          let detail = "";
          try {
            const body = await response.json();
            detail = typeof body.detail === "string" ? body.detail : "";
          } catch {
            detail = await response.text();
          }
          throw new Error(detail || `Capture failed with HTTP ${response.status}.`);
        }
        return response.json();
      });
}

export function isPdfLikeUrl(rawUrl) {
  try {
    const parsed = new URL(String(rawUrl || ""));
    return parsed.pathname.toLowerCase().endsWith(".pdf");
  } catch {
    return false;
  }
}

export function buildPdfCaptureText(tab) {
  return [
    "PDF URL captured by CML browser extension.",
    `Title: ${String(tab?.title || "").trim() || "Unknown PDF"}`,
    `URL: ${String(tab?.url || "").trim()}`,
  ].join("\n");
}

export function derivePdfCaptureTitle(title, rawUrl) {
  const cleanTitle = String(title || "").trim();
  if (cleanTitle) return cleanTitle;
  try {
    const parsed = new URL(String(rawUrl || ""));
    const last = parsed.pathname.split("/").filter(Boolean).pop();
    if (last) return decodeURIComponent(last);
  } catch {
    // Ignore parse errors and use fallback title.
  }
  return "Saved PDF URL";
}

export function deriveScreenshotTitle(tab) {
  const cleanTitle = String(tab?.title || "").trim();
  if (cleanTitle) {
    return `Screenshot of ${cleanTitle}`;
  }
  const host = safeHostname(tab?.url || "");
  return host ? `Screenshot of ${host}` : "Captured screenshot";
}

export function deriveScreenshotFileName(tab) {
  const host = safeHostname(tab?.url || "") || "page";
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  return sanitizeUploadFileName(`cml-screenshot-${host}-${timestamp}.png`);
}

function safeHostname(rawUrl) {
  try {
    return new URL(String(rawUrl || "")).hostname;
  } catch {
    return "";
  }
}

function isCaptureCandidateTab(tab) {
  if (!tab || !tab.id) return false;
  const rawUrl = String(tab.url || "").trim();
  if (!rawUrl) return false;
  if (rawUrl.startsWith("chrome-extension://")) return false;
  return /^https?:/i.test(rawUrl) || /^file:/i.test(rawUrl);
}
