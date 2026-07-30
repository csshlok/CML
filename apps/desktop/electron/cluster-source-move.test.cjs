const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const clusterDetailSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.clusters.$clusterId.tsx"),
  "utf8",
);

test("cluster source rows expose a direct move action", () => {
  assert.match(clusterDetailSource, /aria-label=\{`Move \$\{source\.title\} to another cluster`\}/);
  assert.match(clusterDetailSource, /<DialogTitle>Move source<\/DialogTitle>/);
  assert.match(clusterDetailSource, /id="move-source-target"/);
  assert.match(
    clusterDetailSource,
    /\{moveSourceBusy \? "Moving…" : "Move source"\}/,
  );
});

test("a source move is confirmed by the backend before the row disappears", () => {
  const updateIndex = clusterDetailSource.indexOf(
    "const moved = await updateSource(sourceToMove.id",
  );
  const confirmationIndex = clusterDetailSource.indexOf(
    'if (moved.cluster_id !== target.id)',
  );
  const removalIndex = clusterDetailSource.indexOf(
    "current.filter((source) => source.id !== sourceToMove.id)",
  );

  assert.ok(updateIndex >= 0);
  assert.ok(confirmationIndex > updateIndex);
  assert.ok(removalIndex > confirmationIndex);
  assert.match(clusterDetailSource, /tone: "success"/);
  assert.match(clusterDetailSource, /role="alert"/);
});

test("move destinations are bounded, searchable, and exclude the current cluster", () => {
  assert.match(
    clusterDetailSource,
    /listClustersPage\(vaultId, \{ limit: 50, query \}\)/,
  );
  assert.match(clusterDetailSource, /aria-label="Search move destinations"/);
  assert.match(clusterDetailSource, /aria-label="Search merge destinations"/);
  assert.doesNotMatch(clusterDetailSource, /listAllVaultClusters/);
  assert.match(
    clusterDetailSource,
    /filter\(\(item\) => item\.id !== clusterId\)/,
  );
  assert.match(
    clusterDetailSource,
    /disabled=\{peerClusters\.length === 0\}/,
  );
});
