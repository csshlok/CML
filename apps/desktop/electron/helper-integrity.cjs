const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const HELPER_MANIFEST_NAME = "helper-manifest.json";

async function sha256File(targetPath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(targetPath);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

async function loadHelperManifest(resourcesRoot) {
  const manifestPath = path.join(resourcesRoot, HELPER_MANIFEST_NAME);
  const raw = await fsp.readFile(manifestPath, "utf8");
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.entries)) {
    throw new Error("Helper manifest is malformed.");
  }
  return { manifestPath, manifest: parsed };
}

async function verifyHelperManifest(resourcesRoot) {
  const { manifestPath, manifest } = await loadHelperManifest(resourcesRoot);
  const entries = [];
  let ok = true;
  for (const entry of manifest.entries) {
    const relativePath = typeof entry.relative_path === "string" ? entry.relative_path : "";
    const expectedSha256 = typeof entry.sha256 === "string" ? entry.sha256.toLowerCase() : "";
    const absolutePath = path.join(resourcesRoot, relativePath);
    const exists = await pathExists(absolutePath);
    let actualSha256 = null;
    let size = null;
    let entryOk = false;
    if (exists) {
      const stat = await fsp.stat(absolutePath);
      size = stat.size;
      actualSha256 = (await sha256File(absolutePath)).toLowerCase();
      entryOk = actualSha256 === expectedSha256;
    }
    ok = ok && exists && entryOk;
    entries.push({
      group: typeof entry.group === "string" ? entry.group : "unknown",
      relative_path: relativePath,
      absolute_path: absolutePath,
      expected_sha256: expectedSha256,
      actual_sha256: actualSha256,
      size,
      exists,
      ok: exists && entryOk,
    });
  }
  return {
    ok,
    manifestPath,
    generated_at: manifest.generated_at || null,
    resources_root: resourcesRoot,
    entry_count: entries.length,
    entries,
  };
}

function resolvePackagedHelperPaths(resourcesRoot) {
  return {
    resourcesRoot,
    backendRoot: path.join(resourcesRoot, "backend"),
    pythonRuntime: path.join(resourcesRoot, "python-runtime"),
    backendPython: path.join(resourcesRoot, "python-runtime", "python.exe"),
    playwrightRoot: path.join(resourcesRoot, "ms-playwright"),
    llmRuntimeRoot: path.join(resourcesRoot, "llm-runtime"),
    llmRuntimeServer: path.join(resourcesRoot, "llm-runtime", "llama-server.exe"),
    helperManifest: path.join(resourcesRoot, HELPER_MANIFEST_NAME),
  };
}

function defaultWritableRoots({ userDataPath, activeVaultPath }) {
  const roots = [];
  if (userDataPath) {
    roots.push(path.resolve(userDataPath));
    roots.push(path.resolve(path.join(userDataPath, "pre-vault")));
  }
  if (activeVaultPath) {
    roots.push(path.resolve(path.join(activeVaultPath, ".vault")));
  }
  return Array.from(new Set(roots));
}

function packageLayoutAudit({
  packageRoot,
  resourcesRoot,
  helperRoots,
  writableRoots,
  helperManifestPath,
}) {
  const normalizedPackageRoot = path.resolve(packageRoot);
  const normalizedResourcesRoot = path.resolve(resourcesRoot);
  const helperEntries = helperRoots.map((root) => path.resolve(root));
  const writableEntries = writableRoots.map((root) => path.resolve(root));
  const overlaps = [];
  for (const helperRoot of helperEntries) {
    for (const writableRoot of writableEntries) {
      if (pathsOverlap(helperRoot, writableRoot)) {
        overlaps.push({ helper_root: helperRoot, writable_root: writableRoot });
      }
    }
  }
  return {
    ok: overlaps.length === 0,
    package_root: normalizedPackageRoot,
    resources_root: normalizedResourcesRoot,
    helper_manifest: path.resolve(helperManifestPath),
    helper_roots: helperEntries,
    writable_roots: writableEntries,
    overlaps,
  };
}

function buildBackendChildEnv({
  inheritedEnv,
  helperPaths,
  apiPrefix,
  apiToken,
  backendMode,
  dataDir,
  databasePath,
  startupStatusPath,
  vaultLockOverride,
}) {
  const env = {
    SystemRoot: inheritedEnv.SystemRoot || inheritedEnv.SYSTEMROOT || "C:\\Windows",
    ComSpec: inheritedEnv.ComSpec || inheritedEnv.COMSPEC || "C:\\Windows\\System32\\cmd.exe",
    PATHEXT: inheritedEnv.PATHEXT || ".COM;.EXE;.BAT;.CMD",
    TEMP: inheritedEnv.TEMP || os.tmpdir(),
    TMP: inheritedEnv.TMP || inheritedEnv.TEMP || os.tmpdir(),
    USERPROFILE: inheritedEnv.USERPROFILE || "",
    LOCALAPPDATA: inheritedEnv.LOCALAPPDATA || "",
    APPDATA: inheritedEnv.APPDATA || "",
    PROGRAMDATA: inheritedEnv.PROGRAMDATA || "",
    WINDIR: inheritedEnv.WINDIR || inheritedEnv.SystemRoot || inheritedEnv.SYSTEMROOT || "C:\\Windows",
    CML_API_PREFIX: apiPrefix,
    CML_API_TOKEN: apiToken,
    CML_BACKEND_MODE: backendMode,
    CML_DATA_DIR: dataDir,
    CML_DATABASE_PATH: databasePath,
    CML_STARTUP_STATUS_PATH: startupStatusPath,
    CML_VAULT_LOCK_OVERRIDE: vaultLockOverride || "",
    CML_LLM_RUNTIME_BINARY: helperPaths.llmRuntimeServer,
    PLAYWRIGHT_BROWSERS_PATH: helperPaths.playwrightRoot,
    PYTHONPATH: helperPaths.resourcesRoot,
    PYTHONHOME: helperPaths.pythonRuntime,
    PYTHONNOUSERSITE: "1",
  };
  env.PATH = [
    helperPaths.pythonRuntime,
    path.join(helperPaths.pythonRuntime, "Scripts"),
    env.SystemRoot,
    path.join(env.SystemRoot, "System32"),
    path.join(env.SystemRoot, "System32", "WindowsPowerShell", "v1.0"),
  ].join(path.delimiter);
  return env;
}

function pathsOverlap(firstPath, secondPath) {
  const a = path.resolve(firstPath);
  const b = path.resolve(secondPath);
  return a === b || a.startsWith(`${b}${path.sep}`) || b.startsWith(`${a}${path.sep}`);
}

async function pathExists(targetPath) {
  try {
    await fsp.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

module.exports = {
  HELPER_MANIFEST_NAME,
  buildBackendChildEnv,
  defaultWritableRoots,
  loadHelperManifest,
  packageLayoutAudit,
  pathExists,
  pathsOverlap,
  resolvePackagedHelperPaths,
  sha256File,
  verifyHelperManifest,
};
