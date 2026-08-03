const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const route = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.tasks.tsx"),
  "utf8",
);

test("Tasks uses three user-facing views without losing task states", () => {
  assert.match(route, /type TaskFilter = "active" \| "attention" \| "history"/);
  assert.match(route, /const taskFilters: TaskFilter\[\] = \["active", "attention", "history"\]/);
  assert.match(route, /"blocked_setup_required"/);
  assert.match(route, /"partial_success"/);
  assert.match(route, /"succeeded", "cancelled"/);
  assert.doesNotMatch(route, /type TaskFilter = .*"maintenance"/);
});

test("Tasks relies on automatic refresh and keeps one page-level action", () => {
  const headerStart = route.indexOf("<PageHeader>");
  const headerEnd = route.indexOf("</PageHeader>", headerStart);
  const header = route.slice(headerStart, headerEnd);
  assert.match(header, /Run due jobs/);
  assert.doesNotMatch(header, />Refresh</);
});
