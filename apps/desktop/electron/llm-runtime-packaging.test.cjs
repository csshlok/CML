const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const stagingScript = fs.readFileSync(
  path.join(repoRoot, "scripts", "packaging", "stage-llm-runtime.ps1"),
  "utf8",
);
const packageScript = fs.readFileSync(
  path.join(repoRoot, "scripts", "packaging", "package-windows.ps1"),
  "utf8",
);
const validationScript = fs.readFileSync(
  path.join(repoRoot, "scripts", "packaging", "validate-clean-machine-package.ps1"),
  "utf8",
);
const helperSource = fs.readFileSync(
  path.join(__dirname, "helper-integrity.cjs"),
  "utf8",
);
const installerInclude = fs.readFileSync(
  path.join(repoRoot, "apps", "desktop", "build", "installer.nsh"),
  "utf8",
);
const uninstallCleanupScript = fs.readFileSync(
  path.join(repoRoot, "apps", "desktop", "build", "stop-installed-runtimes.ps1"),
  "utf8",
);

test("Windows packages pin verified CPU and CUDA llama.cpp runtimes", () => {
  assert.match(stagingScript, /llama-b9374-bin-win-cpu-x64\.zip/);
  assert.match(stagingScript, /llama-b9374-bin-win-cuda-12\.4-x64\.zip/);
  assert.match(stagingScript, /cudart-llama-bin-win-cuda-12\.4-x64\.zip/);
  assert.match(
    stagingScript,
    /9843c5ec7db8939e66d0ce546e032cf515403093713b6c5229d04e21ecf8e5f8/,
  );
  assert.match(
    stagingScript,
    /8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6/,
  );
  assert.match(stagingScript, /schema_version = 2/);
  assert.match(stagingScript, /ggml-cuda\.dll/);
  assert.match(stagingScript, /cublas64_12\.dll/);
  assert.match(stagingScript, /cudart64_12\.dll/);
});

test("packaging and clean-machine checks require the CUDA fallback pair", () => {
  assert.match(packageScript, /llmCudaRuntimeServer/);
  assert.match(packageScript, /did not produce the CUDA llama-server\.exe/);
  assert.match(packageScript, /Stop-ProcessesInsidePackageOutput/);
  assert.match(packageScript, /StartsWith\(\s*\$normalizedRoot/);
  assert.match(packageScript, /\$removeAttempts -ge 5/);
  assert.match(validationScript, /llm_cuda_runtime_exists/);
  assert.match(validationScript, /llm_cuda_backend_exists/);
  assert.match(helperSource, /llmCudaRuntimeServer/);
  assert.match(helperSource, /CML_LLM_RUNTIME_CUDA_BINARY/);
});

test("Windows uninstall stops only runtime processes owned by the installation", () => {
  assert.match(packageScript, /"include": "build\/installer\.nsh"/);
  assert.match(packageScript, /uninstall\/stop-installed-runtimes\.ps1/);
  assert.match(installerInclude, /customUnInstall/);
  assert.match(installerInclude, /stop-installed-runtimes\.ps1/);
  assert.match(uninstallCleanupScript, /llama-server\.exe/);
  assert.match(uninstallCleanupScript, /ExecutablePath/);
  assert.match(uninstallCleanupScript, /GetPathRoot/);
  assert.match(uninstallCleanupScript, /StartsWith\(/);
  assert.match(uninstallCleanupScript, /OrdinalIgnoreCase/);
});
