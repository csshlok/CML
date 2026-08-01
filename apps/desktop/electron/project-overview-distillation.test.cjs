const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const route = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.projects.$projectId.tsx"),
  "utf8",
);

test("project overview keeps secondary information behind explicit disclosure", () => {
  assert.match(route, /<summary[^>]*>\s*Suggested questions\s*<\/summary>/);
  assert.match(route, /<summary[^>]*>\s*Project details\s*<\/summary>/);
  assert.doesNotMatch(route, /What this project does/);
  assert.doesNotMatch(route, /Answers stay scoped to this project/);
  assert.doesNotMatch(route, /Scope: \{project\.name\}/);
  assert.doesNotMatch(route, /<aside/);
  assert.doesNotMatch(route, /Step \{phase\.step\} of 4/);
  assert.doesNotMatch(route, /files in this phase/);
});

test("project overview bounds visible metadata and detailed activity", () => {
  assert.match(route, /\.slice\(0, 3\)/);
  assert.match(route, /runs\.slice\(0, 3\)/);
  assert.doesNotMatch(route, /project\.entrypoints\.slice\(0, 6\)/);
});
