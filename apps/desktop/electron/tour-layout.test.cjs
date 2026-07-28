const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appShellSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "AppShell.tsx"),
  "utf8",
);

test("first-use tour stays inside narrow and short viewports", () => {
  assert.match(
    appShellSource,
    /const dialogWidth = Math\.min\(328, Math\.max\(0, viewportWidth - 32\)\)/,
  );
  assert.match(
    appShellSource,
    /left: Math\.max\([\s\S]*viewportWidth - dialogWidth - 16/,
  );
  assert.match(
    appShellSource,
    /top: Math\.max\(16, Math\.min\(viewportHeight - 260, targetRect\.top - 8\)\)/,
  );
  assert.match(appShellSource, /max-h-\[calc\(100vh-2rem\)\]/);
  assert.match(appShellSource, /w-\[min\(328px,calc\(100vw-2rem\)\)\]/);
});
