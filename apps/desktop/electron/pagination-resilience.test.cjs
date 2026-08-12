const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src");
const read = (relativePath) => fs.readFileSync(path.join(rendererRoot, relativePath), "utf8");

test("polling preserves user-loaded chat and cluster pages", () => {
  const route = read("routes/_app.chat.tsx");

  assert.match(route, /mergePolledPage\(current, sessionResult\.value\.items, 100\)/);
  assert.match(route, /mergePolledPage\(current, clusterResult\.value\.items, 200\)/);
  assert.match(route, /hasLoadedOlderClusters/);
});

test("numbered pages recover when filtering or deletion shrinks the result set", () => {
  for (const relativePath of ["routes/_app.search.tsx", "routes/_app.timeline.tsx"]) {
    const route = read(relativePath);
    assert.match(route, /if \(page > totalPages\) setPage\(totalPages\)/);
  }
});

test("semantic search labels bounded retrieval as top matches instead of a full total", () => {
  const route = read("routes/_app.search.tsx");
  assert.match(route, /top semantic match/);
});

test("Bridge histories expose continuation instead of silently slicing long-lived records", () => {
  const route = read("routes/_app.bridge.tsx");

  assert.match(route, /BRIDGE_HISTORY_PAGE_SIZE/);
  assert.match(route, /Show more saved captures/);
  assert.match(route, /Show more Bridge history/);
  assert.match(route, /Show more permission events/);
  assert.match(route, /fetchPage\(BRIDGE_HISTORY_PAGE_SIZE \+ 1, currentItems\.length\)/);
  assert.match(route, /appendHistoryPage/);
  assert.doesNotMatch(route, /BRIDGE_HISTORY_MAX_VISIBLE/);
  assert.doesNotMatch(route, /captures\.slice\(0, [568]\)/);
});

test("cluster member tabs traverse cursor pages while exact counts stay independent", () => {
  const route = read("routes/_app.clusters.$clusterId.tsx");

  assert.match(route, /listSourcesPage/);
  assert.match(route, /listChatSessionsPage/);
  assert.match(route, /Load more sources/);
  assert.match(route, /Load more chats/);
  assert.match(route, /getClusterCounts/);
  assert.doesNotMatch(route, /clusterId: clusterRow\.id, limit: 1000/);
});
