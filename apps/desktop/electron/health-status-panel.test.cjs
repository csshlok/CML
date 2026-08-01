const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const panelSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "HealthStatusPanel.tsx"),
  "utf8",
);

test("health panel close control is excluded from pointer-drag capture", () => {
  assert.match(panelSource, /event\.target instanceof Element/);
  assert.match(panelSource, /event\.target\.closest\("\[data-health-panel-control\]"\)/);
  assert.match(
    panelSource,
    /<Button[\s\S]*data-health-panel-control[\s\S]*aria-label="Close health status"[\s\S]*onClick=\{onClose\}/,
  );
});
