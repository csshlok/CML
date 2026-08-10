const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(root, "src", relativePath), "utf8");

test("Projects can add folders without requiring Odin", () => {
  const source = read("routes/_app.projects.tsx");

  assert.match(source, /selectSourceFolders/);
  assert.match(source, /createProject\(\{/);
  assert.match(source, /Add project folder/);
  assert.match(source, /Odin is an optional terminal workflow|use Odin from your terminal/i);
});

test("the locked screen unlocks inline and Ctrl+L uses the backend lock", () => {
  const shell = read("components/AppShell.tsx");
  const feedback = read("components/product/Feedback.tsx");
  const palette = read("components/CommandPalette.tsx");

  assert.match(shell, /unlockVaultWithPassphrase/);
  assert.match(shell, /lockVault\(securedVaultId\)/);
  assert.match(shell, /e\.key\.toLowerCase\(\) === "l"/);
  assert.doesNotMatch(shell, /e\.key\.toLowerCase\(\) === "l"[\s\S]{0,120}navigate\(\{ to: "\/sources"/);
  assert.match(feedback, /Enter your passphrase to continue/);
  assert.match(feedback, /role="alert"/);
  assert.match(feedback, /Reset or recover/);
  assert.match(palette, /Lock library/);
});

test("large projects are represented as folders in Sources", () => {
  const route = read("routes/_app.sources.tsx");
  const backend = read("lib/backend.ts");

  assert.match(route, /project\.source_count >= 20/);
  assert.match(route, /listSourceFolders/);
  assert.match(route, /folderRoots/);
  assert.match(route, /search: \{ folder: folder\.root_path \}/);
  assert.match(
    route,
    /excludeGroupedProjects: !clusterId && !projectId && !folderPath && !unclusteredOnly/,
  );
  assert.match(route, /search: \{ project: project\.id \}/);
  assert.match(backend, /exclude_grouped_projects/);
  assert.match(backend, /project_id/);
});

test("command palette uses bounded cancellable server search", () => {
  const palette = read("components/CommandPalette.tsx");
  const backend = read("lib/backend.ts");

  assert.match(palette, /listClustersPage\(vault\.id, \{ limit: 20, query, signal:/);
  assert.match(palette, /listSourcesPage\(vault\.id, \{ limit: 20, query, signal:/);
  assert.match(palette, /controller\.abort\(\)/);
  assert.doesNotMatch(palette, /listClusters\(vault\.id\)/);
  assert.doesNotMatch(palette, /listSources\(vault\.id\)/);
  assert.match(backend, /query\?: string; signal\?: AbortSignal/);
});
