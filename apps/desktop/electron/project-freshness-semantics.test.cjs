const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const route = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.projects.$projectId.tsx"),
  "utf8",
);
const backend = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "backend.ts"),
  "utf8",
);

test("project detail separates Odin snapshot freshness from Git working-tree state", () => {
  assert.match(route, /Odin freshness/);
  assert.match(route, /active Odin snapshot matches the current eligible files/);
  assert.match(route, /Git repository status/);
  assert.match(route, /Some or all may already be present in Odin's active snapshot/);
  assert.match(route, /changes\.changed_path_count/);
  assert.match(route, /changes\.repository_changed_path_count/);
});

test("project changes API contract exposes snapshot and repository deltas independently", () => {
  assert.match(backend, /repository_changed_paths: string\[\]/);
  assert.match(backend, /repository_change_items: ProjectChangeItem\[\]/);
  assert.match(backend, /repository_changed_path_count: number/);
  assert.match(backend, /working_tree_dirty: boolean/);
});
