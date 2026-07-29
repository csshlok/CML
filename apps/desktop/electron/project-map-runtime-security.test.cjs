const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src");
const read = (relativePath) => fs.readFileSync(path.join(rendererRoot, relativePath), "utf8");

test("requested project graphs open in an on-demand full-page workspace", () => {
  const chat = read("routes/_app.chat.$chatId.tsx");
  const project = read("routes/_app.projects.$projectId.tsx");
  const route = read("routes/_app.project-map.tsx");
  const graph = read("components/ProjectGraphArtifact.tsx");

  assert.doesNotMatch(chat, /<ProjectGraphArtifact/);
  assert.match(chat, /<ProjectGraphLink/);
  assert.match(project, /to:\s*"\/project-map"/);
  assert.match(route, /createFileRoute\("\/_app\/project-map"\)/);
  assert.match(graph, /Show more/);
  assert.match(graph, /Spread out/);
  assert.match(graph, /What this view shows/);
  assert.match(graph, /Observed flows/);
});

test("renderer accepts runtime backend URLs only from loopback origins", () => {
  const backend = read("lib/backend.ts");

  assert.match(backend, /safeRuntimeBackendUrl\(queryBackendUrl\)/);
  assert.match(backend, /\["127\.0\.0\.1", "localhost", "\[::1\]", "::1"\]/);
  assert.match(backend, /parsed\.protocol !== "http:"/);
  assert.match(backend, /parsed\.username/);
  assert.match(backend, /parsed\.password/);
  assert.match(backend, /return parsed\.origin/);
});

test("knowledge map expands dense views and hides details until selection", () => {
  const map = read("components/KnowledgeMap.tsx");

  assert.match(map, /onExpandOverview/);
  assert.match(map, /getMapNeighborhood\(vaultId, node\.id, limit\)/);
  assert.match(map, /selected \? \(\s*<MapInspector/);
  assert.match(map, /aria-label="Close map details"/);
});
