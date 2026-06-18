export const DEFAULT_BACKEND_URL = "http://127.0.0.1:7343";
export const DEFAULT_API_PREFIX = "/api/v1";

export function normalizeBackendUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return DEFAULT_BACKEND_URL;
  const parsed = new URL(raw);
  if (!/^https?:$/.test(parsed.protocol)) {
    throw new Error("Backend URL must use http or https.");
  }
  parsed.pathname = "";
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

export function parseSetupJson(rawText) {
  let parsed;
  try {
    parsed = JSON.parse(String(rawText || ""));
  } catch {
    throw new Error("Setup JSON is not valid JSON.");
  }
  const backendUrl = normalizeBackendUrl(parsed.backend_url || parsed.backendUrl || DEFAULT_BACKEND_URL);
  const token = String(
    parsed.extension_token ||
      parsed.extensionToken ||
      parsed.token ||
      parsed?.headers?.["x-cml-extension-token"] ||
      "",
  ).trim();
  if (!token) {
    throw new Error("Setup JSON is missing an extension token.");
  }
  return {
    backendUrl,
    apiPrefix: normalizeApiPrefix(parsed.api_prefix || parsed.apiPrefix || DEFAULT_API_PREFIX),
    token,
    vaultId: String(parsed.default_vault_id || parsed.vault_id || "").trim(),
    clusterId: String(parsed.default_cluster_id || parsed.cluster_id || "").trim(),
    clientName: String(parsed.client_name || "Browser extension").trim() || "Browser extension",
    vaultPath: String(parsed.vault_path || parsed.save_root || "").trim(),
    browser: String(parsed.browser || "chrome").trim().toLowerCase() || "chrome",
    installTargets: Array.isArray(parsed.install_targets) ? parsed.install_targets.map((item) => String(item)) : [],
    primaryActions: Array.isArray(parsed.primary_actions) ? parsed.primary_actions.map((item) => String(item)) : [],
    optionalActions: Array.isArray(parsed.optional_actions) ? parsed.optional_actions.map((item) => String(item)) : [],
  };
}

export function normalizeApiPrefix(value) {
  const raw = String(value || DEFAULT_API_PREFIX).trim();
  const prefixed = raw.startsWith("/") ? raw : `/${raw}`;
  return prefixed.replace(/\/+$/, "") || DEFAULT_API_PREFIX;
}

export function apiPath(config, suffix) {
  const apiPrefix = normalizeApiPrefix(config?.apiPrefix || DEFAULT_API_PREFIX);
  return `${apiPrefix}/${String(suffix || "").replace(/^\/+/, "")}`;
}

export function buildExtensionCaptureRequest({
  vaultId,
  clusterId = "",
  captureType,
  title,
  url = "",
  text,
}) {
  const cleanVaultId = String(vaultId || "").trim();
  const cleanText = String(text || "").trim();
  const cleanTitle = String(title || "").trim();
  if (!cleanVaultId) {
    throw new Error("Choose a vault before saving.");
  }
  if (!cleanTitle) {
    throw new Error("A capture title is required.");
  }
  if (!cleanText) {
    throw new Error("There is no text to save.");
  }
  return {
    vault_id: cleanVaultId,
    cluster_id: String(clusterId || "").trim() || null,
    capture_type: String(captureType || "page").trim() || "page",
    title: cleanTitle,
    url: String(url || "").trim(),
    text: cleanText,
  };
}

export function buildExtensionUploadRequest({
  vaultId,
  clusterId = "",
  captureType,
  title,
  url = "",
  fileName,
  mimeType = "",
  contentBase64,
}) {
  const cleanVaultId = String(vaultId || "").trim();
  const cleanTitle = String(title || "").trim();
  const cleanFileName = sanitizeUploadFileName(fileName);
  const cleanContent = String(contentBase64 || "").trim();
  if (!cleanVaultId) {
    throw new Error("Choose a vault before saving.");
  }
  if (!cleanTitle) {
    throw new Error("A capture title is required.");
  }
  if (!cleanFileName) {
    throw new Error("A file name is required.");
  }
  if (!cleanContent) {
    throw new Error("There is no file content to save.");
  }
  return {
    vault_id: cleanVaultId,
    cluster_id: String(clusterId || "").trim() || null,
    capture_type: String(captureType || "file").trim() || "file",
    title: cleanTitle,
    url: String(url || "").trim(),
    file_name: cleanFileName,
    mime_type: String(mimeType || "").trim(),
    content_base64: cleanContent,
  };
}

export function derivePageCaptureTitle({ title, hostname }) {
  const cleanTitle = String(title || "").trim();
  if (cleanTitle) return cleanTitle;
  const cleanHost = String(hostname || "").trim();
  if (cleanHost) return `Saved page from ${cleanHost}`;
  return "Saved page";
}

export function trimPageText(text, maxChars = 12000) {
  const normalized = String(text || "").replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, maxChars).trimEnd()}\n\n[Truncated by extension before upload]`;
}

export function parseDataUrl(dataUrl) {
  const raw = String(dataUrl || "").trim();
  const match = /^data:([^;,]+)?;base64,([a-z0-9+/=\s]+)$/i.exec(raw);
  if (!match) {
    throw new Error("Screenshot capture did not return a valid image payload.");
  }
  return {
    mimeType: String(match[1] || "application/octet-stream").trim().toLowerCase(),
    contentBase64: match[2].replace(/\s+/g, ""),
  };
}

export function sanitizeUploadFileName(fileName) {
  const raw = String(fileName || "").trim().replace(/\\/g, "/");
  const leaf = raw.split("/").filter(Boolean).pop() || "";
  return leaf.replace(/[^\w.\-() ]+/g, "_").trim();
}
