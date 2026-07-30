const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("background controller posts selected text capture with chosen vault scope", async () => {
  const mod = await import("../background-core.js");
  let posted = null;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "cluster-1",
    }),
    getCaptureTab: async () => ({ id: 7, title: "Example title", url: "https://example.com" }),
    focusTab: async () => {},
    readSelectionFromTab: async () => ({ title: "Selection from Example", text: "selected text" }),
    readPageFromTab: async () => ({ title: "unused", text: "unused" }),
    postCapture: async (_config, payload) => {
      posted = payload;
      return { capture_id: "cap-1" };
    },
  });

  await controller.handleCapture({ captureMode: "selection" });

  assert.equal(posted.vault_id, "vault-1");
  assert.equal(posted.cluster_id, "cluster-1");
  assert.equal(posted.capture_type, "selection");
  assert.equal(posted.text, "selected text");
});

test("background controller saves pdf url captures without page text extraction", async () => {
  const mod = await import("../background-core.js");
  let pageReads = 0;
  let posted = null;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "",
    }),
    getCaptureTab: async () => ({ id: 3, title: "paper.pdf", url: "https://example.com/paper.pdf" }),
    focusTab: async () => {},
    readSelectionFromTab: async () => ({ title: "", text: "" }),
    readPageFromTab: async () => {
      pageReads += 1;
      return { title: "", text: "" };
    },
    postCapture: async (_config, payload) => {
      posted = payload;
      return { capture_id: "cap-2" };
    },
  });

  await controller.handleCapture({ captureMode: "pdf_url" });

  assert.equal(pageReads, 0);
  assert.equal(posted.capture_type, "file");
  assert.match(posted.text, /PDF URL captured/i);
  assert.equal(posted.url, "https://example.com/paper.pdf");
});

test("background controller uploads visible screenshots through the binary capture path", async () => {
  const mod = await import("../background-core.js");
  let postedUpload = null;
  let focusedTabId = null;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "cluster-2",
    }),
    getCaptureTab: async () => ({
      id: 4,
      windowId: 9,
      title: "System design",
      url: "https://example.com/design",
    }),
    focusTab: async (tabId) => {
      focusedTabId = tabId;
    },
    captureVisibleTab: async (windowId) => {
      assert.equal(windowId, 9);
      return "data:image/png;base64,c2NyZWVuc2hvdA==";
    },
    readSelectionFromTab: async () => ({ title: "", text: "" }),
    readPageFromTab: async () => ({ title: "", text: "" }),
    postCapture: async () => {
      throw new Error("text capture should not be used for screenshots");
    },
    postUploadCapture: async (_config, payload) => {
      postedUpload = payload;
      return { capture_id: "cap-3" };
    },
  });

  await controller.handleCapture({ captureMode: "screenshot" });

  assert.equal(postedUpload.capture_type, "screenshot");
  assert.equal(focusedTabId, 4);
  assert.equal(postedUpload.vault_id, "vault-1");
  assert.equal(postedUpload.cluster_id, "cluster-2");
  assert.equal(postedUpload.mime_type, "image/png");
  assert.equal(postedUpload.content_base64, "c2NyZWVuc2hvdA==");
  assert.match(postedUpload.file_name, /^cml-screenshot-/);
});

test("chrome background deps capture only the active tab in the current window", async () => {
  const mod = await import("../background-core.js");
  const deps = mod.createChromeBackgroundDeps(
    {
      storage: { local: { get: async () => ({}) } },
      tabs: {
        query: async (query) => {
          assert.deepEqual(query, { active: true, currentWindow: true });
          return [
          { id: 1, url: "chrome-extension://abc/popup.html", lastAccessed: 200 },
          { id: 2, url: "https://example.com/docs", lastAccessed: 300 },
          { id: 3, url: "file:///C:/notes.txt", lastAccessed: 100 },
          ];
        },
        sendMessage: async (_tabId, message) => ({
          title: "Selection from Docs",
          text: "tab message selection",
          url: "https://example.com/docs",
          nonce: message.nonce,
        }),
        update: async () => {},
        captureVisibleTab: async () => "data:image/png;base64,aaaa",
      },
      scripting: { executeScript: async () => [{ result: { title: "", text: "" } }] },
    },
    async () => ({ ok: true, json: async () => ({}) }),
  );

  const tab = await deps.getCaptureTab();
  assert.equal(tab.id, 2);
  const selection = await deps.readSelectionFromTab(2);
  assert.equal(selection.text, "tab message selection");
});

test("chrome background deps post captures through imported api prefix", async () => {
  const mod = await import("../background-core.js");
  let requestedUrl = "";
  const deps = mod.createChromeBackgroundDeps(
    {
      storage: {
        local: {
          get: async () => ({
            backendUrl: "http://127.0.0.1:7343",
            apiPrefix: "/custom/v2",
            token: "token-123",
            vaultId: "vault-1",
            clusterId: "",
          }),
        },
        session: { get: async () => ({}), set: async () => {} },
      },
      tabs: { query: async () => [], sendMessage: async () => ({}), update: async () => {} },
      scripting: { executeScript: async () => [{ result: { title: "", text: "" } }] },
    },
    async (url) => {
      requestedUrl = url;
      return { ok: true, json: async () => ({ capture_id: "cap-prefix" }) };
    },
  );

  const config = await deps.loadConfig();
  await deps.postCapture(config, {
    vault_id: "vault-1",
    cluster_id: null,
    capture_type: "page",
    title: "Docs",
    url: "https://example.com",
    text: "page text",
  });

  assert.equal(requestedUrl, "http://127.0.0.1:7343/custom/v2/extension/capture");
});

test("selection capture can use the content script's isolated previous selection", async () => {
  const mod = await import("../background-core.js");
  let posted = null;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "",
    }),
    getCaptureTab: async () => ({ id: 8, title: "Docs", url: "https://example.com/docs" }),
    focusTab: async () => {},
    readSelectionFromTab: async () => ({
      title: "Selection from Docs",
      text: "cached selected text from content script",
      url: "https://example.com/docs",
    }),
    readPageFromTab: async () => ({ title: "", text: "" }),
    postCapture: async (_config, payload) => {
      posted = payload;
      return { capture_id: "cap-4" };
    },
  });

  await controller.handleCapture({ captureMode: "selection" });

  assert.equal(posted.capture_type, "selection");
  assert.equal(posted.text, "cached selected text from content script");
});

test("background controller command shortcut can trigger screenshot capture", async () => {
  const mod = await import("../background-core.js");
  let postedUpload = null;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "",
    }),
    getCaptureTab: async () => ({
      id: 12,
      windowId: 4,
      title: "Docs",
      url: "https://example.com/docs",
    }),
    focusTab: async () => {},
    captureVisibleTab: async () => "data:image/png;base64,c2NyZWVuc2hvdA==",
    readSelectionFromTab: async () => ({ title: "", text: "" }),
    readPageFromTab: async () => ({ title: "", text: "" }),
    postCapture: async () => {
      throw new Error("command screenshot should use upload path");
    },
    postUploadCapture: async (_config, payload) => {
      postedUpload = payload;
      return { capture_id: "cap-shortcut" };
    },
  });

  const result = await controller.handleCommand("capture_screenshot");

  assert.equal(result.capture_id, "cap-shortcut");
  assert.equal(postedUpload.capture_type, "screenshot");
});

test("capture aborts when the active tab navigates before content is saved", async () => {
  const mod = await import("../background-core.js");
  let posted = false;
  const controller = mod.createBackgroundController({
    loadConfig: async () => ({
      backendUrl: "http://127.0.0.1:7343",
      token: "token-123",
      vaultId: "vault-1",
      clusterId: "",
    }),
    getCaptureTab: async () => ({
      id: 5,
      title: "Original",
      url: "https://example.com/original",
    }),
    readPageFromTab: async () => ({ title: "Original", text: "page contents" }),
    assertTabUnchanged: async () => {
      throw new Error("The page changed before capture finished. Try again.");
    },
    postCapture: async () => {
      posted = true;
    },
  });

  await assert.rejects(
    () => controller.handleCapture({ captureMode: "page" }),
    /page changed before capture finished/i,
  );
  assert.equal(posted, false);
});

test("selection content stays out of page-readable DOM attributes and uses a nonce", () => {
  const contentSource = fs.readFileSync(
    path.join(__dirname, "..", "content.js"),
    "utf8",
  );

  assert.doesNotMatch(contentSource, /setAttribute\([^)]*selection/i);
  assert.doesNotMatch(contentSource, /data-cml-last-selection/i);
  assert.match(contentSource, /message\.nonce/);
  assert.match(contentSource, /lastSelection = \{ title: "", text: "", url: "" \}/);
});
