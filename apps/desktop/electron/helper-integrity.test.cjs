const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  buildBackendChildEnv,
  buildMcpChildEnv,
  defaultWritableRoots,
  isPathWithinRoot,
  packageLayoutAudit,
  pathsOverlap,
  sha256File,
  verifyHelperManifest,
  verifyHelperManifestCached,
} = require("./helper-integrity.cjs");

const temporaryDirectories = new Set();

function makeTempDir(prefix) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  temporaryDirectories.add(directory);
  return directory;
}

test.after(() => {
  for (const directory of temporaryDirectories) {
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
});

test("verifyHelperManifest detects modified helper payloads", async () => {
  const root = makeTempDir("cml-helper-manifest-");
  const helperPath = path.join(root, "python-runtime");
  fs.mkdirSync(helperPath, { recursive: true });
  const pythonExe = path.join(helperPath, "python.exe");
  fs.writeFileSync(pythonExe, "trusted-runtime", "utf8");
  const expected = await sha256File(pythonExe);
  fs.writeFileSync(
    path.join(root, "helper-manifest.json"),
    `${JSON.stringify({
      generated_at: new Date().toISOString(),
      entries: [{ group: "python-runtime", relative_path: "python-runtime/python.exe", sha256: expected }],
    })}\n`,
    "utf8",
  );

  let report = await verifyHelperManifest(root);
  assert.equal(report.ok, true);

  fs.writeFileSync(pythonExe, "tampered-runtime", "utf8");
  report = await verifyHelperManifest(root);
  assert.equal(report.ok, false);
  assert.equal(report.entries[0].ok, false);
});

test("verifyHelperManifest rejects a symlinked helper even when its target hash matches", async (t) => {
  const root = makeTempDir("cml-helper-symlink-");
  const helperPath = path.join(root, "python-runtime");
  fs.mkdirSync(helperPath, { recursive: true });
  const target = path.join(root, "trusted-target.exe");
  const pythonExe = path.join(helperPath, "python.exe");
  fs.writeFileSync(target, "trusted-runtime", "utf8");
  try {
    fs.symlinkSync(target, pythonExe, "file");
  } catch (error) {
    t.skip(`Symlink creation is unavailable: ${error.code || error.message}`);
    return;
  }
  const expected = await sha256File(target);
  fs.writeFileSync(
    path.join(root, "helper-manifest.json"),
    `${JSON.stringify({
      generated_at: new Date().toISOString(),
      entries: [{ group: "python-runtime", relative_path: "python-runtime/python.exe", sha256: expected }],
    })}\n`,
    "utf8",
  );

  const report = await verifyHelperManifest(root);

  assert.equal(report.ok, false);
  assert.equal(report.entries[0].ok, false);
  assert.equal(report.entries[0].actual_sha256, null);
});

test("verifyHelperManifestCached reuses a valid receipt and invalidates changed files", async () => {
  const root = makeTempDir("cml-helper-cache-");
  const helperPath = path.join(root, "python-runtime");
  const receiptPath = path.join(root, "user-data", "helper-verification-v1.json");
  fs.mkdirSync(helperPath, { recursive: true });
  const pythonExe = path.join(helperPath, "python.exe");
  fs.writeFileSync(pythonExe, "trusted-runtime", "utf8");
  const expected = await sha256File(pythonExe);
  const size = fs.statSync(pythonExe).size;
  fs.writeFileSync(
    path.join(root, "helper-manifest.json"),
    `${JSON.stringify({
      generated_at: new Date().toISOString(),
      entries: [{ group: "python-runtime", relative_path: "python-runtime/python.exe", sha256: expected, size }],
    })}\n`,
    "utf8",
  );

  const initial = await verifyHelperManifestCached(root, { receiptPath, packageVersion: "1.0.0" });
  const cached = await verifyHelperManifestCached(root, { receiptPath, packageVersion: "1.0.0" });
  fs.writeFileSync(pythonExe, "tampered-runtime-with-a-different-size", "utf8");
  const invalidated = await verifyHelperManifestCached(root, { receiptPath, packageVersion: "1.0.0" });

  assert.equal(initial.ok, true);
  assert.equal(initial.cached, false);
  assert.equal(cached.ok, true);
  assert.equal(cached.cached, true);
  assert.equal(invalidated.ok, false);
  assert.equal(invalidated.cached, false);
});

test("packageLayoutAudit rejects writable helper overlap", () => {
  const packageRoot = "C:\\Package";
  const resourcesRoot = "C:\\Package\\resources";
  const helperRoot = "C:\\Package\\resources\\python-runtime";
  const writableRoot = "C:\\Package\\resources\\python-runtime\\tmp";

  const report = packageLayoutAudit({
    packageRoot,
    resourcesRoot,
    helperRoots: [helperRoot],
    writableRoots: [writableRoot],
    helperManifestPath: "C:\\Package\\resources\\helper-manifest.json",
  });

  assert.equal(report.ok, false);
  assert.equal(report.overlaps.length, 1);
});

test("defaultWritableRoots keeps vault and userData paths separate", () => {
  const roots = defaultWritableRoots({
    userDataPath: "C:\\Users\\me\\AppData\\Roaming\\CML",
    activeVaultPath: "D:\\Knowledge\\VaultA",
  });

  assert.deepEqual(roots, [
    path.resolve("C:\\Users\\me\\AppData\\Roaming\\CML"),
    path.resolve("C:\\Users\\me\\AppData\\Roaming\\CML\\pre-vault"),
    path.resolve("D:\\Knowledge\\VaultA\\.vault"),
  ]);
});

test("buildBackendChildEnv pins PATH to helper and system roots", () => {
  const env = buildBackendChildEnv({
    inheritedEnv: {
      SystemRoot: "C:\\Windows",
      TEMP: "C:\\Temp",
      USERPROFILE: "C:\\Users\\me",
      APPDATA: "C:\\Users\\me\\AppData\\Roaming",
      LOCALAPPDATA: "C:\\Users\\me\\AppData\\Local",
      PROGRAMDATA: "C:\\ProgramData",
    },
    helperPaths: {
      resourcesRoot: "C:\\Package\\resources",
      pythonRuntime: "C:\\Package\\resources\\python-runtime",
      backendPython: "C:\\Package\\resources\\python-runtime\\python.exe",
      playwrightRoot: "C:\\Package\\resources\\ms-playwright",
      llmRuntimeServer: "C:\\Package\\resources\\llm-runtime\\llama-server.exe",
      llmCudaRuntimeServer: "C:\\Package\\resources\\llm-runtime\\cuda\\llama-server.exe",
    },
    apiPrefix: "/api/v1",
    apiToken: "token",
    backendMode: "full_vault",
    dataDir: "D:\\Vault\\.vault",
    databasePath: "D:\\Vault\\.vault\\cml.sqlite3",
    startupStatusPath: "C:\\Users\\me\\AppData\\Roaming\\CML\\startup-status.json",
    vaultLockOverride: "",
  });

  assert.match(env.PATH, /python-runtime/);
  assert.equal(env.PYTHONPATH, "C:\\Package\\resources");
  assert.equal(env.PYTHONNOUSERSITE, "1");
  assert.equal(env.CML_API_TOKEN, "token");
  assert.equal(
    env.CML_LLM_RUNTIME_CUDA_BINARY,
    "C:\\Package\\resources\\llm-runtime\\cuda\\llama-server.exe",
  );
});

test("pathsOverlap handles nested paths only", () => {
  assert.equal(pathsOverlap("C:\\A\\B", "C:\\A\\B\\C"), true);
  assert.equal(pathsOverlap("C:\\A\\B", "C:\\A\\C"), false);
});

test("buildMcpChildEnv contains only launcher essentials and no backend token", () => {
  const env = buildMcpChildEnv({
    inheritedEnv: {
      SystemRoot: "C:\\Windows",
      SECRET_SHOULD_NOT_LEAK: "hidden",
      TEMP: "C:\\Temp",
    },
    helperPaths: {
      resourcesRoot: "C:\\Package\\resources",
      pythonRuntime: "C:\\Package\\resources\\python-runtime",
    },
    backendUrl: "http://127.0.0.1:7343",
    apiPrefix: "/api/v1",
    capabilityProfile: "read_only",
    featureFlags: {
      chatgpt_mcp_write_tools: false,
      mcp_streaming: false,
      mcp_remote_http: false,
    },
  });

  assert.equal(env.CML_BACKEND_URL, "http://127.0.0.1:7343");
  assert.equal(env.CML_MCP_CAPABILITY_PROFILE, "read_only");
  assert.equal(env.CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS, "0");
  assert.equal(env.CML_FEATURE_MCP_STREAMING, "0");
  assert.equal(env.CML_FEATURE_MCP_REMOTE_HTTP, "0");
  assert.equal(env.PYTHONNOUSERSITE, "1");
  assert.equal(env.SECRET_SHOULD_NOT_LEAK, undefined);
  assert.equal(env.CML_API_TOKEN, undefined);
  assert.equal(env.CML_BRIDGE_TOKEN, undefined);
});

test("buildMcpChildEnv rejects non-loopback and credential-bearing backend URLs", () => {
  const options = {
    inheritedEnv: { SystemRoot: "C:\\Windows" },
    helperPaths: {
      resourcesRoot: "C:\\Package\\resources",
      pythonRuntime: "C:\\Package\\resources\\python-runtime",
    },
    apiPrefix: "/api/v1",
    capabilityProfile: "read_only",
  };
  for (const backendUrl of [
    "https://127.0.0.1:7343",
    "http://example.com:7343",
    "http://user:secret@127.0.0.1:7343",
    "http://127.0.0.1:7343/redirect",
  ]) {
    assert.throws(
      () => buildMcpChildEnv({ ...options, backendUrl }),
      /plain HTTP loopback origin/,
    );
  }
});

test("isPathWithinRoot is directional and rejects sibling traversal", () => {
  assert.equal(isPathWithinRoot("C:\\A\\B", "C:\\A\\B\\C\\image.png"), true);
  assert.equal(isPathWithinRoot("C:\\A\\B", "C:\\A\\B"), true);
  assert.equal(isPathWithinRoot("C:\\A\\B", "C:\\A"), false);
  assert.equal(isPathWithinRoot("C:\\A\\B", "C:\\A\\BC\\image.png"), false);
  assert.equal(isPathWithinRoot("C:\\A\\B", "C:\\A\\B\\..\\secret.png"), false);
});
