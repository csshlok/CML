const fs = require("node:fs/promises");
const path = require("node:path");
const { sha256File } = require("../../apps/desktop/electron/helper-integrity.cjs");

const repoRoot = path.resolve(__dirname, "..", "..");
const desktopRoot = path.join(repoRoot, "apps", "desktop");
const stagingRoot = path.join(desktopRoot, "packaging");
const outputPath = path.join(stagingRoot, "helper-manifest.json");

const backendFiles = [
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
  const entries = [];
  for (const relativePath of backendFiles) {
    await addEntry(entries, "backend-security", relativePath);
  }
  await collectEntries(entries, "python-runtime", "python-runtime", new Set([".exe", ".dll", ".pyd"]));
  await collectEntries(entries, "expert-runtime", "expert-python-runtime", new Set([".exe", ".dll", ".pyd"]));
  await collectEntries(entries, "ocr-tools", path.join("backend", "bin", "ocr"), new Set([".exe", ".dll", ".traineddata", ".json"]));
  await collectEntries(entries, "browser-runtime", "ms-playwright", new Set([".exe", ".dll"]));
  const manifest = {
    generated_at: new Date().toISOString(),
    entry_count: entries.length,
    entries: entries.sort((a, b) => a.relative_path.localeCompare(b.relative_path)),
  };
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  process.stdout.write(`${outputPath}\n`);
}

async function collectEntries(entries, group, relativeRoot, extensions) {
  const absoluteRoot = path.join(stagingRoot, relativeRoot);
  if (!(await exists(absoluteRoot))) {
    return;
  }
  await walkEntries(entries, group, absoluteRoot, extensions);
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

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
