const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const sourcesRoute = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.sources.tsx"),
  "utf8",
);

test("source inspector exposes an immediate cluster destination selector", () => {
  assert.match(sourcesRoute, /htmlFor="source-cluster-target"/);
  assert.match(sourcesRoute, /aria-label="Move source to cluster"/);
  assert.match(sourcesRoute, /value=\{source\.clusterId \?\? "__unclustered__"\}/);
  assert.match(sourcesRoute, /onValueChange=\{\(targetId\) => void moveToCluster\(targetId\)\}/);
  assert.match(sourcesRoute, /listClustersPage\(activeVault\.id, \{ limit: 200 \}\)/);
  assert.match(sourcesRoute, /Load more clusters/);
  assert.match(sourcesRoute, /Load more folders/);
});

test("source moves are confirmed before local source state changes", () => {
  const updateIndex = sourcesRoute.indexOf(
    "const moved = await updateSource(source.id, { cluster_id: target.id });",
  );
  const confirmationIndex = sourcesRoute.indexOf(
    "if (moved.cluster_id !== target.id)",
  );
  const localUpdateIndex = sourcesRoute.indexOf(
    "setBackendSources((current) =>",
    updateIndex,
  );

  assert.ok(updateIndex >= 0);
  assert.ok(confirmationIndex > updateIndex);
  assert.ok(localUpdateIndex > confirmationIndex);
  assert.match(sourcesRoute, /title: "Source moved"/);
  assert.match(sourcesRoute, /title: "Source move failed"/);
});
