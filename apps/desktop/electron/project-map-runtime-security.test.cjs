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
  assert.doesNotMatch(graph, /mode === "graph" \? \(\s*<Button type="button" variant="outline" disabled=\{!canExpand/);
  assert.match(graph, /Spread out/);
  assert.match(graph, /What this view shows/);
  assert.match(graph, /Observed flows/);
});

test("semantic project flows use a dedicated bounded workspace and cancel stale requests", () => {
  const route = read("routes/_app.project-map.tsx");
  const graph = read("components/ProjectGraphArtifact.tsx");
  const flow = read("components/ProjectFlowArtifact.tsx");
  const backend = read("lib/backend.ts");

  assert.match(route, /search\.mode === "flow"/);
  assert.match(route, /<ProjectFlowWorkspace/);
  assert.match(graph, /mode: "graph" \| "flow" \| "tree"/);
  assert.match(graph, /call flow\|execution flow\|data flow\|request flow\|pipeline\|trace/);
  assert.match(flow, /new AbortController\(\)/);
  assert.match(flow, /controller\.abort\(\)/);
  assert.match(flow, /In plain English/);
  assert.match(flow, /step\.what_happens/);
  assert.match(flow, /Why it matters/);
  assert.match(flow, /step\.technical_detail/);
  assert.match(flow, /No verified execution path found/);
  assert.match(flow, /view\.warnings\.join/);
  assert.match(flow, /Trace \$\{candidate\.qualified_id\}/);
  assert.match(flow, /xl:border-l xl:border-t-0/);
  assert.match(backend, /\/graph\/flow\?/);
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

test("long chat and graph surfaces virtualize rows and dispose graph simulations", () => {
  const chat = read("routes/_app.chat.$chatId.tsx");
  const graph = read("components/ProjectGraphArtifact.tsx");
  const map = read("components/KnowledgeMap.tsx");

  assert.match(chat, /useVirtualizer/);
  assert.match(chat, /data-message-virtualizer/);
  assert.match(chat, /measureElement/);
  assert.match(graph, /rowVirtualizer\.getVirtualItems\(\)/);
  assert.match(graph, /pauseAnimation/);
  assert.match(graph, /_destructor/);
  assert.match(map, /rowVirtualizer\.getVirtualItems\(\)/);
  assert.match(map, /neighborhoodLimit < 200/);
  assert.match(map, /map limit reached/);
});
