const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const clustersSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.clusters.tsx"),
  "utf8",
);
const backendSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "backend.ts"),
  "utf8",
);
const adaptersSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "recordAdapters.ts"),
  "utf8",
);
const clusterDetailSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.clusters.$clusterId.tsx"),
  "utf8",
);

test("cluster list has restrained search and filter controls", () => {
  assert.match(clustersSource, /aria-label="Search clusters"/);
  assert.match(clustersSource, /aria-label="Filter clusters"/);
  assert.match(clustersSource, /\["active", "With sources"\]/);
  assert.match(clustersSource, /\["attention", "Needs attention"\]/);
  assert.match(clustersSource, /\["projects", "Projects"\]/);
  assert.match(clustersSource, /No clusters match these filters\./);
});

test("suggestions refresh only through an explicit user action", () => {
  assert.match(clustersSource, /Check suggestions/);
  assert.match(clustersSource, /listClusterSuggestions\(vault\.id, 12, true\)/);
  assert.match(backendSource, /if \(refresh\) params\.set\("refresh", "true"\)/);
});

test("source previews are cleaned and kept distinct from descriptions", () => {
  assert.match(adaptersSource, /buildRepresentativePreview\(extracted, record\.summary\)/);
  assert.match(adaptersSource, /\.replace\(\/<\[\^>\]\+>\/g, " "\)/);
  assert.match(adaptersSource, /comparisonKey\(sentence\) !== summaryKey/);
});

test("cluster merges use an accessible reversible confirmation", () => {
  assert.match(clusterDetailSource, /confirmLabel="Merge cluster"/);
  assert.match(clusterDetailSource, /You can restore this merge later/);
  assert.doesNotMatch(clusterDetailSource, /window\.confirm/);
});
