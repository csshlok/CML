const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

test("browser extension package script includes module dependencies", () => {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const outputRoot = `.tmp/browser-extension-package-test-${process.pid}`;
  const outputPath = path.join(repoRoot, outputRoot);
  fs.rmSync(outputPath, { recursive: true, force: true });

  try {
    const result = spawnSync(
      "powershell",
      [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/extension/package-browser-extension.ps1",
        "-OutputRoot",
        outputRoot,
      ],
      { cwd: repoRoot, encoding: "utf8" },
    );

    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    const stagingPath = path.join(outputPath, "cml-browser-extension");
    for (const fileName of [
      "manifest.json",
      "background-core.js",
      "background.js",
      "content.js",
      "extension-core.js",
      "popup-core.js",
      "popup.js",
      "popup.html",
      "popup.css",
    ]) {
      assert.equal(fs.existsSync(path.join(stagingPath, fileName)), true, `${fileName} missing from package`);
    }
    assert.equal(fs.existsSync(path.join(outputPath, "cml-browser-extension.zip")), true);
  } finally {
    fs.rmSync(outputPath, { recursive: true, force: true });
  }
});
