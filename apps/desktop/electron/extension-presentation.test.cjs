const test = require("node:test");
const assert = require("node:assert/strict");

test("buildExtensionSetupText produces a copyable setup contract for extension clients", async () => {
  const mod = await import("../src/lib/extension-presentation.js");

  const text = mod.buildExtensionSetupText({
    backendUrl: "http://127.0.0.1:7343",
    apiPrefix: "/custom/v2",
    token: "token-123",
    vaultId: "vault-1",
    clusterId: "cluster-1",
    vaultPath: "C:\\Vault",
    clientName: "Browser extension",
    browser: "brave",
  });
  const parsed = JSON.parse(text);

  assert.equal(parsed.backend_url, "http://127.0.0.1:7343");
  assert.equal(parsed.api_prefix, "/custom/v2");
  assert.equal(parsed.extension_token, "token-123");
  assert.equal(parsed.default_vault_id, "vault-1");
  assert.equal(parsed.default_cluster_id, "cluster-1");
  assert.equal(parsed.vault_path, "C:\\Vault");
  assert.equal(parsed.browser, "brave");
  assert.equal(parsed.headers["x-cml-extension-token"], "token-123");
  assert.equal(parsed.capture_example.payload.vault_id, "vault-1");
  assert.equal(parsed.capture_example.payload.cluster_id, "cluster-1");
  assert.equal(parsed.capture_example.endpoint, "http://127.0.0.1:7343/custom/v2/extension/capture");
  assert.equal(parsed.primary_actions[0], "save_link_to_vault");
});

test("describeExtensionScope resolves vault ids into readable labels", async () => {
  const mod = await import("../src/lib/extension-presentation.js");
  const names = new Map([
    ["vault-1", "Personal"],
    ["vault-2", "Research"],
  ]);

  assert.equal(mod.describeExtensionScope([], names), "All vaults allowed");
  assert.equal(mod.describeExtensionScope(["vault-1", "vault-2"], names), "Personal, Research");
});
