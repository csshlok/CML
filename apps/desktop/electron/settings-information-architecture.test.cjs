const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const settingsSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.settings.tsx"),
  "utf8",
);

test("each Settings card belongs to one navigation section", () => {
  assert.doesNotMatch(settingsSource, /showSection\([^)]*,/);
});

test("Local imports and Evidence retention have one clear home", () => {
  assert.match(
    settingsSource,
    /showSection\("advanced"\)[\s\S]{0,250}title="Evidence retention"/,
  );
  assert.match(
    settingsSource,
    /showSection\("library"\)[\s\S]{0,250}title="Local imports"/,
  );
});
