const test = require("node:test");
const assert = require("node:assert/strict");

test("parseSetupJson accepts desktop-exported setup JSON", async () => {
  const mod = await import("../extension-core.js");

  const parsed = mod.parseSetupJson(
    JSON.stringify({
      backend_url: "http://127.0.0.1:7343",
      api_prefix: "/custom/v2",
      extension_token: "token-123",
      default_vault_id: "vault-1",
      default_cluster_id: "cluster-1",
      client_name: "Browser extension",
    }),
  );

  assert.equal(parsed.backendUrl, "http://127.0.0.1:7343");
  assert.equal(parsed.apiPrefix, "/custom/v2");
  assert.equal(parsed.token, "token-123");
  assert.equal(parsed.vaultId, "vault-1");
  assert.equal(parsed.clusterId, "cluster-1");
});

test("apiPath builds extension endpoints from imported setup prefix", async () => {
  const mod = await import("../extension-core.js");

  assert.equal(mod.apiPath({ apiPrefix: "/custom/v2" }, "/extension/status"), "/custom/v2/extension/status");
  assert.equal(mod.apiPath({ apiPrefix: "custom/v2/" }, "extension/capture"), "/custom/v2/extension/capture");
});

test("buildExtensionCaptureRequest rejects empty vault or content and preserves selected scope", async () => {
  const mod = await import("../extension-core.js");

  assert.throws(
    () =>
      mod.buildExtensionCaptureRequest({
        vaultId: "",
        captureType: "selection",
        title: "Selection",
        text: "text",
      }),
    /Choose a vault/,
  );

  const payload = mod.buildExtensionCaptureRequest({
    vaultId: "vault-1",
    clusterId: "cluster-1",
    captureType: "selection",
    title: "Selection",
    url: "https://example.com",
    text: "selected text",
  });

  assert.equal(payload.vault_id, "vault-1");
  assert.equal(payload.cluster_id, "cluster-1");
  assert.equal(payload.capture_type, "selection");
  assert.equal(payload.text, "selected text");
});

test("buildExtensionUploadRequest sanitizes file payloads and parseDataUrl keeps screenshot bytes usable", async () => {
  const mod = await import("../extension-core.js");

  const upload = mod.buildExtensionUploadRequest({
    vaultId: "vault-1",
    clusterId: "cluster-1",
    captureType: "file",
    title: "Quarterly report",
    fileName: "C:\\Users\\name\\Downloads\\report.pdf",
    mimeType: "application/pdf",
    contentBase64: "YWJjZA==",
  });

  assert.equal(upload.vault_id, "vault-1");
  assert.equal(upload.cluster_id, "cluster-1");
  assert.equal(upload.file_name, "report.pdf");
  assert.equal(upload.content_base64, "YWJjZA==");

  const screenshot = mod.parseDataUrl("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB");
  assert.equal(screenshot.mimeType, "image/png");
  assert.equal(screenshot.contentBase64, "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB");
});

test("trimPageText keeps readable content and marks truncation when needed", async () => {
  const mod = await import("../extension-core.js");

  const text = "a".repeat(30);
  assert.equal(mod.trimPageText(text, 40), text);

  const trimmed = mod.trimPageText("b".repeat(60), 20);
  assert.match(trimmed, /\[Truncated by extension before upload\]/);
  assert.ok(trimmed.length > 20);
});

test("backend URLs require HTTPS unless they resolve to loopback", async () => {
  const mod = await import("../extension-core.js");

  assert.equal(mod.normalizeBackendUrl("http://127.42.0.1:7343"), "http://127.42.0.1:7343");
  assert.equal(mod.normalizeBackendUrl("http://[::1]:7343"), "http://[::1]:7343");
  assert.equal(mod.normalizeBackendUrl("https://vault.example.com/api"), "https://vault.example.com");
  assert.throws(
    () => mod.normalizeBackendUrl("http://192.168.1.20:7343"),
    /Plain HTTP is allowed only/,
  );
  assert.throws(
    () => mod.normalizeBackendUrl("http://token@localhost:7343"),
    /must not include credentials/,
  );
});
