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
const backendSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "backend.ts"),
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

test("successful library deletion stays inside the desktop router", () => {
  assert.match(
    settingsSource,
    /finalizeActiveVaultDeletion\?\.\(\)[\s\S]{0,250}await navigate\(\{ to: "\/onboarding" \}\)/,
  );
  assert.doesNotMatch(settingsSource, /window\.location\.assign\("\/onboarding"\)/);
});

test("library deletion authorization is not limited by the generic 12 second request timeout", () => {
  assert.match(
    backendSource,
    /authorizeVaultDeletion[\s\S]{0,900}timeoutMs:\s*120_000/,
  );
});

test("Library security exposes manual scans and a changeable 30-day full-check schedule", () => {
  assert.match(settingsSource, /title="Security scans"/);
  assert.match(settingsSource, /Run antivirus scan/);
  assert.match(settingsSource, /Run full security check/);
  assert.match(settingsSource, /The default is every 30 days/);
  assert.match(backendSource, /diagnostics\/security-scans/);
  assert.match(backendSource, /waitForAppJob\(queued\.id\)/);
});

test("the model connection test performs a real generation probe", () => {
  assert.match(
    backendSource,
    /testModelRuntimeConnection[\s\S]{0,300}models\/runtime\/probe[\s\S]{0,200}method:\s*"POST"/,
  );
  assert.match(
    settingsSource,
    /async function testRuntimeConnection\(\)[\s\S]{0,250}await testModelRuntimeConnection\(\)/,
  );
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

test("Code Connections leads with setup and exposes the complete Odin command surface", () => {
  const installIndex = settingsSource.indexOf('title="Install Odin"');
  const projectsIndex = settingsSource.indexOf('title="Odin code projects"');
  const accessIndex = settingsSource.indexOf('title="Odin command-line access"');
  const referenceIndex = settingsSource.indexOf('title="Odin command reference"');
  assert.ok(installIndex >= 0 && installIndex < projectsIndex);
  assert.ok(projectsIndex < accessIndex);
  assert.ok(accessIndex < referenceIndex);
  assert.match(settingsSource, /How to install and connect/);
  assert.match(settingsSource, /Install and connect Odin/);
  for (const command of [
    "odin doctor",
    "odin auth pair",
    "odin auth status",
    "odin auth logout",
    "odin auth forget",
    "odin project add",
    "odin project list",
    "odin project status",
    "odin project changes",
    "odin project sync",
    "odin project reindex",
    "odin project rename",
    "odin project link",
    "odin project unlink",
    "odin project links",
    "odin project explain",
    "odin project path",
    "odin project graph",
    "odin project tree",
    "odin project remove",
    "odin context",
  ]) {
    assert.match(settingsSource, new RegExp(command.replaceAll(" ", "\\s+")));
  }
});

test("Memory history keeps job state live and replaces indefinite loading with a retry", () => {
  assert.match(
    settingsSource,
    /firstVault && activeSection === "library"[\s\S]{0,600}add\("tasks", getJobStatus\(\)/,
  );
  assert.match(settingsSource, /const temporalRefreshPending = temporalBackfillBusy \|\| temporalBackfillActive/);
  assert.match(settingsSource, /memoryInsightsError[\s\S]{0,120}"Unavailable"/);
  assert.match(settingsSource, /<span role="alert">\{memoryInsightsError\}<\/span>/);
  assert.match(settingsSource, /onClick=\{\(\) => void refreshMemoryInsights\(\)\}[\s\S]{0,100}Try again/);
});

test("long Settings lists retain continuation controls", () => {
  assert.match(settingsSource, /Show more connected clients/);
  assert.match(settingsSource, /Show more projects/);
  assert.match(settingsSource, /Show more synced folders/);
  assert.match(settingsSource, /mergePolledCliClients/);
  assert.match(settingsSource, /mergePolledProjects/);
  assert.match(settingsSource, /mergePolledIntegrationImports/);
});
