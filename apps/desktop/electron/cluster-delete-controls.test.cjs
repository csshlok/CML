const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const clusterDetailSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.clusters.$clusterId.tsx"),
  "utf8",
);

test("manage cluster exposes a confirmed delete action", () => {
  assert.match(clusterDetailSource, /async function deleteCurrentCluster\(\)/);
  assert.match(clusterDetailSource, /await deleteCluster\(clusterIdForActions\)/);
  assert.match(clusterDetailSource, /title=\{`Delete \$\{clusterNameForActions\}\?`\}/);
  assert.match(clusterDetailSource, /confirmLabel="Delete cluster"/);
});

test("cluster deletion explains preservation and navigates after backend success", () => {
  const deleteIndex = clusterDetailSource.indexOf(
    "await deleteCluster(clusterIdForActions)",
  );
  const navigateIndex = clusterDetailSource.indexOf(
    'navigate({ to: "/clusters" });',
    deleteIndex,
  );

  assert.ok(deleteIndex >= 0);
  assert.ok(navigateIndex > deleteIndex);
  assert.match(clusterDetailSource, /Sources remain in Vault and move to Unclustered/);
  assert.match(clusterDetailSource, /Its sources are now unclustered/);
});
