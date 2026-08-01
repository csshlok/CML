const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const route = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.bridge.tsx"),
  "utf8",
);

test("Code Connections presents one setup step and groups secondary tools", () => {
  assert.match(route, /const nextConnectionStep =/);
  assert.match(route, /\["overview", "reviews", "history", "clients"\]/);
  assert.match(route, /Advanced connection tools/);
  assert.match(route, />\s*Connection access\s*<\/button>/);
  assert.match(route, />\s*Manual save\s*<\/button>/);
  assert.doesNotMatch(route, /Save useful answers without copying/);
  assert.doesNotMatch(route, /\["overview", "clients", "reviews", "history", "advanced"\]/);
});

test("permissions stay out of the default Connect view", () => {
  const permissionsIndex = route.indexOf(">Permissions<");
  const precedingSection = route.lastIndexOf("<section", permissionsIndex);
  const sectionSource = route.slice(precedingSection, permissionsIndex);
  assert.match(sectionSource, /hidden=\{bridgeView !== "clients"\}/);
});
