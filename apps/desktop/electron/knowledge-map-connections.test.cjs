const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mapSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "KnowledgeMap.tsx"),
  "utf8",
);
const routeSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.map.tsx"),
  "utf8",
);
const backendClientSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "backend.ts"),
  "utf8",
);

test("knowledge map offers current and semantic connection modes", () => {
  assert.match(mapSource, /aria-label="Cluster connection mode"/);
  assert.match(mapSource, />\s*Current\s*</);
  assert.match(mapSource, />\s*Connections\s*</);
  assert.match(mapSource, /onConnectionModeChange\("current"\)/);
  assert.match(mapSource, /onConnectionModeChange\("similar"\)/);
  assert.match(routeSource, /connections: connectionMode/);
  assert.match(backendClientSource, /params\.set\("connections", options\.connections\)/);
});

test("semantic lines are visibly distinct and explain their score", () => {
  assert.match(
    mapSource,
    /linkLineDash=\{\(edge: MapEdgeRecord\) => edge\.kind === "similarity" \? \[4, 3\] : null\}/,
  );
  assert.match(mapSource, /edge\.kind === "similarity" \? 1\.15 : 1\.5/);
  assert.match(mapSource, /Math\.round\(\(edge\.similarity_score \?\? 0\) \* 100\)/);
  assert.match(mapSource, /Shared topics:/);
  assert.match(mapSource, /<MapLineLegend dashed label="Similar" \/>/);
});
