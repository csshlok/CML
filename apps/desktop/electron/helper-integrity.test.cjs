const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  buildBackendChildEnv,
  defaultWritableRoots,
  packageLayoutAudit,
  pathsOverlap,
  sha256File,
  verifyHelperManifest,
} = require("./helper-integrity.cjs");

test("verifyHelperManifest detects modified helper payloads", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cml-helper-manifest-"));
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
});

test("pathsOverlap handles nested paths only", () => {
  assert.equal(pathsOverlap("C:\\A\\B", "C:\\A\\B\\C"), true);
  assert.equal(pathsOverlap("C:\\A\\B", "C:\\A\\C"), false);
});
