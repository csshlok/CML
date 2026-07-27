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
  return {
    manifestPath,
    manifest: parsed,
    manifestSha256: crypto.createHash("sha256").update(raw).digest("hex"),
  };
}

async function verifyHelperManifest(resourcesRoot) {
  const { manifestPath, manifest, manifestSha256 } = await loadHelperManifest(resourcesRoot);
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
      const stat = await fsp.lstat(absolutePath);
      size = stat.size;
      if (stat.isFile() && !stat.isSymbolicLink()) {
        actualSha256 = (await sha256File(absolutePath)).toLowerCase();
        entryOk = actualSha256 === expectedSha256;
      }
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
    manifest_sha256: manifestSha256,
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
    tunnelRuntimeRoot: path.join(resourcesRoot, "tunnel-client"),
    tunnelRuntimeClient: path.join(resourcesRoot, "tunnel-client", "tunnel-client.exe"),
    helperManifest: path.join(resourcesRoot, HELPER_MANIFEST_NAME),
  };
}

async function verifyHelperManifestCached(resourcesRoot, { receiptPath, packageVersion }) {
  const { manifestPath, manifest, manifestSha256 } = await loadHelperManifest(resourcesRoot);
  const normalizedRoot = path.resolve(resourcesRoot);
  const expectedTotalSize = manifest.entries.reduce(
    (total, entry) => total + (Number.isFinite(Number(entry.size)) ? Number(entry.size) : 0),
    0,
  );
  let receipt = null;
  try {
    receipt = JSON.parse(await fsp.readFile(receiptPath, "utf8"));
  } catch {
    receipt = null;
  }
  const receiptMatches =
    receipt?.schema_version === 1 &&
    receipt?.package_version === String(packageVersion || "") &&
    receipt?.manifest_sha256 === manifestSha256 &&
    receipt?.resources_root === normalizedRoot &&
    receipt?.entry_count === manifest.entries.length &&
    receipt?.total_size === expectedTotalSize &&
    Number.isFinite(receipt?.verified_at_ms);
  if (receiptMatches) {
    let unchanged = true;
    for (const entry of manifest.entries) {
      const expectedSize = Number(entry.size);
      if (!Number.isFinite(expectedSize)) {
        unchanged = false;
        break;
      }
      try {
        const stat = await fsp.lstat(path.join(resourcesRoot, entry.relative_path));
        if (
          !stat.isFile() ||
          stat.isSymbolicLink() ||
          stat.size !== expectedSize ||
          stat.mtimeMs > receipt.verified_at_ms + 1000
        ) {
          unchanged = false;
          break;
        }
      } catch {
        unchanged = false;
        break;
      }
    }
    if (unchanged) {
      return {
        ok: true,
        cached: true,
        manifestPath,
        manifest_sha256: manifestSha256,
        generated_at: manifest.generated_at || null,
        resources_root: normalizedRoot,
        entry_count: manifest.entries.length,
        entries: [],
      };
    }
  }

  const report = await verifyHelperManifest(resourcesRoot);
  report.cached = false;
  if (report.ok) {
    const nextReceipt = {
      schema_version: 1,
      package_version: String(packageVersion || ""),
      manifest_sha256: manifestSha256,
      resources_root: normalizedRoot,
      entry_count: manifest.entries.length,
      total_size: expectedTotalSize,
      verified_at_ms: Date.now(),
    };
    await fsp.mkdir(path.dirname(receiptPath), { recursive: true });
    const temporaryPath = `${receiptPath}.${process.pid}.${Date.now()}.tmp`;
    await fsp.writeFile(temporaryPath, `${JSON.stringify(nextReceipt, null, 2)}\n`, "utf8");
    await fsp.rename(temporaryPath, receiptPath);
  }
  return report;
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

function buildMcpChildEnv({
  inheritedEnv,
  helperPaths,
  backendUrl,
  apiPrefix,
  capabilityProfile,
  featureFlags = {},
}) {
  const systemRoot = inheritedEnv.SystemRoot || inheritedEnv.SYSTEMROOT || "C:\\Windows";
  const parsedBackendUrl = new URL(backendUrl);
  if (
    parsedBackendUrl.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "::1", "[::1]"].includes(parsedBackendUrl.hostname) ||
    parsedBackendUrl.username ||
    parsedBackendUrl.password ||
    parsedBackendUrl.pathname !== "/" ||
    parsedBackendUrl.search ||
    parsedBackendUrl.hash
  ) {
    throw new Error("MCP backend URL must be a plain HTTP loopback origin.");
  }
  return {
    SystemRoot: systemRoot,
    ComSpec: inheritedEnv.ComSpec || inheritedEnv.COMSPEC || path.join(systemRoot, "System32", "cmd.exe"),
    PATHEXT: inheritedEnv.PATHEXT || ".COM;.EXE;.BAT;.CMD",
    TEMP: inheritedEnv.TEMP || os.tmpdir(),
    TMP: inheritedEnv.TMP || inheritedEnv.TEMP || os.tmpdir(),
    USERPROFILE: inheritedEnv.USERPROFILE || "",
    LOCALAPPDATA: inheritedEnv.LOCALAPPDATA || "",
    APPDATA: inheritedEnv.APPDATA || "",
    WINDIR: inheritedEnv.WINDIR || systemRoot,
    CML_BACKEND_URL: parsedBackendUrl.origin,
    CML_API_PREFIX: apiPrefix,
    CML_MCP_CAPABILITY_PROFILE: capabilityProfile === "read_write" ? "read_write" : "read_only",
    CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS:
      featureFlags.chatgpt_mcp_write_tools === false ? "0" : "1",
    CML_FEATURE_MCP_STREAMING: featureFlags.mcp_streaming === true ? "1" : "0",
    CML_FEATURE_MCP_REMOTE_HTTP: featureFlags.mcp_remote_http === true ? "1" : "0",
    PYTHONPATH: helperPaths.resourcesRoot,
    PYTHONHOME: helperPaths.pythonRuntime,
    PYTHONNOUSERSITE: "1",
    PATH: [
      helperPaths.pythonRuntime,
      path.join(helperPaths.pythonRuntime, "Scripts"),
      systemRoot,
      path.join(systemRoot, "System32"),
    ].join(path.delimiter),
  };
}

function pathsOverlap(firstPath, secondPath) {
  const a = path.resolve(firstPath);
  const b = path.resolve(secondPath);
  return a === b || a.startsWith(`${b}${path.sep}`) || b.startsWith(`${a}${path.sep}`);
}

function isPathWithinRoot(rootPath, targetPath) {
  const root = path.resolve(rootPath);
  const target = path.resolve(targetPath);
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
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
  buildMcpChildEnv,
  defaultWritableRoots,
  loadHelperManifest,
  packageLayoutAudit,
  pathExists,
  isPathWithinRoot,
  pathsOverlap,
  resolvePackagedHelperPaths,
  sha256File,
  verifyHelperManifest,
  verifyHelperManifestCached,
};
