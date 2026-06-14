import {
  buildExtensionCaptureRequest,
  buildExtensionUploadRequest,
  derivePageCaptureTitle,
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
        const selection = await deps.readSelectionFromTab(tab.id);
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
        const imageDataUrl = await deps.captureVisibleTab(tab.windowId);
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
      const stored = await chromeApi.storage.local.get(["backendUrl", "token", "vaultId", "clusterId"]);
      return {
        backendUrl: normalizeBackendUrl(stored.backendUrl),
        token: String(stored.token || "").trim(),
        vaultId: String(stored.vaultId || "").trim(),
        clusterId: String(stored.clusterId || "").trim(),
      };
    },
    async getCaptureTab() {
      const tabs = await chromeApi.tabs.query({ lastFocusedWindow: true });
      const candidates = tabs
        .filter((tab) => isCaptureCandidateTab(tab))
        .sort((left, right) => Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0));
      return candidates[0] || null;
    },
    async focusTab(tabId) {
      await chromeApi.tabs.update(tabId, { active: true });
    },
    async cacheSelection(tabId, selection) {
      if (!tabId) return;
      await chromeApi.storage.session.set({
        [`selection:${tabId}`]: {
          title: String(selection?.title || "").trim(),
          text: String(selection?.text || "").trim(),
          url: String(selection?.url || "").trim(),
          updatedAt: Date.now(),
        },
      });
    },
    async getCachedSelection(tabId) {
      if (!tabId) return { title: "", text: "", url: "" };
      const stored = await chromeApi.storage.session.get([`selection:${tabId}`]);
      const cached = stored[`selection:${tabId}`] || {};
      return {
        title: String(cached.title || "").trim(),
        text: String(cached.text || "").trim(),
        url: String(cached.url || "").trim(),
      };
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
    async readSelectionFromTab(tabId) {
      try {
        const fromContent = await chromeApi.tabs.sendMessage(tabId, { type: "cml:get-selection" });
        if (String(fromContent?.text || "").trim()) {
          return {
            title: String(fromContent.title || "").trim(),
            text: String(fromContent.text || "").trim(),
            url: String(fromContent.url || "").trim(),
          };
        }
      } catch {
        // Fall back to direct script execution when the content script is unavailable.
      }
      const [{ result }] = await chromeApi.scripting.executeScript({
        target: { tabId },
        func: () => {
          const selection = window.getSelection()?.toString().trim() || "";
          const root = document.documentElement;
          const cachedText = root?.getAttribute("data-cml-last-selection-text") || "";
          const cachedTitle = root?.getAttribute("data-cml-last-selection-title") || "";
          const cachedUrl = root?.getAttribute("data-cml-last-selection-url") || location.href;
          const title = selection
            ? `Selection from ${document.title || location.hostname || "page"}`
            : "";
          return {
            title: title || cachedTitle,
            text: selection || cachedText,
            url: location.href || cachedUrl,
          };
        },
      });
      const live = result || { title: "", text: "", url: "" };
      if (String(live.text || "").trim()) {
        return live;
      }
      return this.getCachedSelection(tabId);
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

function postJsonCapture(config, payload, fetchImpl, endpoint) {
      if (!config.token) {
        throw new Error("Extension token is missing. Import setup JSON first.");
      }
      return fetchImpl(`${config.backendUrl}/api/v1/extension/${endpoint}`, {
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
