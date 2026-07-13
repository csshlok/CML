const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const desktopRoot = path.resolve(__dirname, "..");
const fixturePath = path.join(desktopRoot, "src", "lib", "mockStore.ts");

function sourceFilesUnder(relativeDirectory) {
  const root = path.join(desktopRoot, relativeDirectory);
  const files = [];
  const pending = [root];
  while (pending.length > 0) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) pending.push(target);
      else if (/\.(?:ts|tsx|js|jsx)$/.test(entry.name)) files.push(target);
    }
  }
  return files;
}

test("mock vault fixtures remain available for isolated feature development", () => {
  const source = fs.readFileSync(fixturePath, "utf8");

  assert.match(source, /Development and interaction-test fixtures only/);
  assert.match(source, /seedClusters/);
  assert.match(source, /seedSources/);
  assert.match(source, /streamMockReply/);
});

test("production routes and components do not import the mock store", () => {
  const offenders = ["src/routes", "src/components"]
    .flatMap(sourceFilesUnder)
    .filter((file) => /(?:@\/lib\/mockStore|\.\.\/lib\/mockStore)/.test(fs.readFileSync(file, "utf8")))
    .map((file) => path.relative(desktopRoot, file));

  assert.deepEqual(offenders, []);
});
