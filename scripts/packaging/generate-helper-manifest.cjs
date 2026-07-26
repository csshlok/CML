const fs = require("node:fs/promises");
const path = require("node:path");
const { sha256File } = require("../../apps/desktop/electron/helper-integrity.cjs");

const repoRoot = path.resolve(__dirname, "..", "..");
const desktopRoot = path.join(repoRoot, "apps", "desktop");
const stagingRoot = path.join(desktopRoot, "packaging");
const outputPath = path.join(stagingRoot, "helper-manifest.json");

const backendFiles = [
  "docs/model-integrity-manifest.json",
  "backend/app/main.py",
  "backend/app/core/browser_ingestion.py",
  "backend/app/core/browser_worker.py",
  "backend/app/core/encrypted_storage.py",
  "backend/app/core/quarantine.py",
  "backend/app/core/parser_worker.py",
  "backend/app/core/vault_crypto.py",
  "backend/bin/ocr/manifest.json",
];

async function main() {
  const manifest = await buildManifest();
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  process.stdout.write(`${outputPath}\n`);
}

async function buildManifest() {
  const entries = [];
  for (const relativePath of backendFiles) {
    await addEntry(entries, "backend-security", relativePath);
  }
  await collectRuntimeEntries(entries, "python-runtime", "python-runtime");
  await collectEntries(entries, "ocr-tools", path.join("backend", "bin", "ocr"), new Set([".exe", ".dll", ".traineddata", ".json"]));
  await collectEntries(entries, "browser-runtime", "ms-playwright", new Set([".exe", ".dll"]));
  await collectEntries(entries, "llm-runtime", "llm-runtime", new Set([".exe", ".dll", ".json"]));
  return {
    generated_at: new Date().toISOString(),
    entry_count: entries.length,
    entries: entries.sort((a, b) => a.relative_path.localeCompare(b.relative_path)),
  };
}

async function collectEntries(entries, group, relativeRoot, extensions) {
  const absoluteRoot = path.join(stagingRoot, relativeRoot);
  if (!(await exists(absoluteRoot))) {
    return;
  }
  await walkEntries(entries, group, absoluteRoot, extensions);
}

async function collectRuntimeEntries(entries, group, relativeRoot) {
  const absoluteRoot = path.join(stagingRoot, relativeRoot);
  if (!(await exists(absoluteRoot))) {
    return;
  }
  await walkRuntimeEntries(entries, group, relativeRoot, absoluteRoot);
}

async function walkRuntimeEntries(entries, group, relativeRoot, absoluteRoot) {
  const dirents = await fs.readdir(absoluteRoot, { withFileTypes: true });
  for (const entry of dirents) {
    const absolutePath = path.join(absoluteRoot, entry.name);
    if (entry.isDirectory()) {
      await walkRuntimeEntries(entries, group, relativeRoot, absolutePath);
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    const relativePath = path.relative(stagingRoot, absolutePath).replace(/\\/g, "/");
    if (!shouldIncludeRuntimeBinary(relativeRoot, relativePath)) {
      continue;
    }
    await addEntry(entries, group, relativePath);
  }
}

function shouldIncludeRuntimeBinary(relativeRoot, relativePath) {
  const normalizedRoot = relativeRoot.replace(/\\/g, "/");
  const normalizedPath = relativePath.replace(/\\/g, "/");
  const extension = path.extname(normalizedPath).toLowerCase();
  if (extension === ".dll" || extension === ".pyd") {
    return true;
  }
  if (extension !== ".exe") {
    return false;
  }
  return (
    normalizedPath === `${normalizedRoot}/python.exe` ||
    normalizedPath === `${normalizedRoot}/pythonw.exe`
  );
}

async function walkEntries(entries, group, absoluteRoot, extensions) {
  const dirents = await fs.readdir(absoluteRoot, { withFileTypes: true });
  for (const entry of dirents) {
    const absolutePath = path.join(absoluteRoot, entry.name);
    if (entry.isDirectory()) {
      await walkEntries(entries, group, absolutePath, extensions);
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    if (!extensions.has(path.extname(entry.name).toLowerCase())) {
      continue;
    }
    const relativePath = path.relative(stagingRoot, absolutePath).replace(/\\/g, "/");
    await addEntry(entries, group, relativePath);
  }
}

async function addEntry(entries, group, relativePath) {
  const absolutePath = path.join(stagingRoot, relativePath);
  if (!(await exists(absolutePath))) {
    return;
  }
  const stat = await fs.stat(absolutePath);
  entries.push({
    group,
    relative_path: relativePath.replace(/\\/g, "/"),
    sha256: await sha256File(absolutePath),
    size: stat.size,
  });
}

async function exists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  buildManifest,
  shouldIncludeRuntimeBinary,
};
