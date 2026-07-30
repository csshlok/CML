const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const settingsSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.settings.tsx"),
  "utf8",
);
const settingsControllerSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "settingsController.ts"),
  "utf8",
);

test("each Settings card belongs to one navigation section", () => {
  assert.doesNotMatch(settingsSource, /showSection\([^)]*,/);
});

test("Folder sync and Evidence retention have one clear home", () => {
  assert.match(
    settingsSource,
    /showSection\("advanced"\)[\s\S]{0,250}title="Evidence retention"/,
  );
  assert.match(
    settingsSource,
    /showSection\("library"\)[\s\S]{0,250}title="Folder sync"/,
  );
});

test("library moves use the product confirmation surface", () => {
  assert.match(settingsSource, /title="Move this library\?"/);
  assert.match(settingsSource, /confirmLabel="Move library"/);
  assert.doesNotMatch(settingsSource, /window\.confirm/);
});

test("the URL is the single owner of the active Settings section", () => {
  assert.match(settingsSource, /const activeSection = canonicalSettingsSection\(section\)/);
  assert.doesNotMatch(settingsSource, /\[activeSection, setActiveSection\]/);
  assert.match(settingsControllerSource, /export function canonicalSettingsSection/);
});

test("Odin launcher drift has one repair-and-pair action", () => {
  assert.match(settingsSource, /Repair and pair Odin/);
  assert.match(settingsSource, /repairAndPair = Boolean\(odinLauncher\?\.needs_repair\)/);
  assert.match(settingsSource, /if \(repairAndPair\)[\s\S]{0,120}startOdinPairing/);
});
