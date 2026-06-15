const test = require("node:test");
const assert = require("node:assert/strict");

test("popup controller imports setup json and persists extension config", async () => {
  const mod = await import("../popup-core.js");
  let saved = null;
  const controller = mod.createPopupController({
    getStoredConfig: async () => ({ backendUrl: "", token: "", vaultId: "", clusterId: "" }),
    saveConfig: async (config) => {
      saved = config;
    },
    checkStatus: async () => ({ ok: true, detail: "Extension capture is available." }),
    sendCaptureMessage: async () => ({ capture_id: "cap-1" }),
  });

  const config = await controller.importSetup(
    JSON.stringify({
      backend_url: "http://127.0.0.1:7343",
      extension_token: "token-123",
      default_vault_id: "vault-1",
      default_cluster_id: "cluster-1",
      vault_path: "C:\\Vault",
      browser: "brave",
    }),
  );

  assert.equal(config.token, "token-123");
  assert.equal(config.vaultPath, "C:\\Vault");
  assert.equal(config.browser, "brave");
  assert.deepEqual(saved, {
    backendUrl: "http://127.0.0.1:7343",
    token: "token-123",
    vaultId: "vault-1",
    clusterId: "cluster-1",
    vaultPath: "C:\\Vault",
    browser: "brave",
    clientName: "Browser extension",
    installTargets: [],
    primaryActions: [],
    optionalActions: [],
  });
});

test("popup controller status and capture flows surface backend and runtime failures", async () => {
  const mod = await import("../popup-core.js");
  const controller = mod.createPopupController({
    getStoredConfig: async () => ({ backendUrl: "", token: "", vaultId: "", clusterId: "" }),
    saveConfig: async () => {},
    checkStatus: async () => {
      throw new Error("Missing or invalid extension token.");
    },
    sendCaptureMessage: async () => {
      throw new Error("The current tab does not look like a PDF URL.");
    },
  });

  await assert.rejects(
    () => controller.checkStatus({
      backendUrl: "http://127.0.0.1:7343",
      token: "bad-token",
      vaultId: "vault-1",
      clusterId: "",
    }),
    /invalid extension token/i,
  );

  await assert.rejects(
    () => controller.dispatchCapture("pdf_url", {
      backendUrl: "http://127.0.0.1:7343",
      token: "good-token",
      vaultId: "vault-1",
      clusterId: "",
    }),
    /does not look like a PDF URL/i,
  );
});

test("popup controller uploads a selected local file through the binary capture endpoint", async () => {
  const mod = await import("../popup-core.js");
  let uploaded = null;
  const controller = mod.createPopupController({
    getStoredConfig: async () => ({ backendUrl: "", token: "", vaultId: "", clusterId: "" }),
    saveConfig: async () => {},
    checkStatus: async () => ({ ok: true }),
    sendCaptureMessage: async () => ({ capture_id: "cap-4" }),
    readLocalFile: async (file) => {
      assert.equal(file.name, "notes.txt");
      return {
        captureType: "file",
        title: "notes.txt",
        fileName: "notes.txt",
        mimeType: "text/plain",
        contentBase64: "bm90ZXM=",
      };
    },
    uploadCapture: async (config, upload) => {
      uploaded = { config, upload };
      return { capture_id: "cap-upload" };
    },
  });

  await controller.uploadLocalFile(
    { name: "notes.txt", arrayBuffer: async () => new ArrayBuffer(0) },
    {
      backendUrl: "http://127.0.0.1:7343",
      token: "good-token",
      vaultId: "vault-1",
      clusterId: "cluster-7",
    },
  );

  assert.equal(uploaded.config.vaultId, "vault-1");
  assert.equal(uploaded.upload.fileName, "notes.txt");
  assert.equal(uploaded.upload.contentBase64, "bm90ZXM=");
});

test("popup controller can run from stored config without manual field re-entry", async () => {
  const mod = await import("../popup-core.js");
  let saved = null;
  const controller = mod.createPopupController({
    getStoredConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "good-token",
      vaultId: "vault-1",
      clusterId: "",
      vaultPath: "C:\\Vault",
      browser: "chrome",
    }),
    saveConfig: async (config) => {
      saved = config;
    },
    checkStatus: async () => ({ ok: true, detail: "ready" }),
    sendCaptureMessage: async () => ({ capture_id: "cap-6" }),
  });

  const status = await controller.checkStatus();
  const capture = await controller.dispatchCapture("page");

  assert.equal(status.detail, "ready");
  assert.equal(capture.capture_id, "cap-6");
  assert.equal(saved.vaultId, "vault-1");
});
