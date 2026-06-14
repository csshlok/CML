const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("browser extension manifest exposes MV3 popup, action shortcut, and loopback-only host permissions", () => {
  const manifestPath = path.join(__dirname, "..", "manifest.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.action.default_popup, "popup.html");
  assert.equal(manifest.background.service_worker, "background.js");
  assert.equal(manifest.commands._execute_action.suggested_key.default, "Ctrl+Shift+Y");
  assert.equal(manifest.commands.capture_screenshot.suggested_key.default, "Ctrl+Shift+U");
  assert.deepEqual(manifest.host_permissions.sort(), ["http://127.0.0.1/*", "http://localhost/*"].sort());
  assert.ok(manifest.permissions.includes("storage"));
  assert.ok(manifest.permissions.includes("scripting"));
});
