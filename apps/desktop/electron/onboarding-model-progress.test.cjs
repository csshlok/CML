const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const onboardingSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "onboarding.tsx"),
  "utf8",
);
const backendClientSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "backend.ts"),
  "utf8",
);

test("model setup keeps one persistent progress surface through activation", () => {
  assert.match(onboardingSource, /function ModelSetupProgress/);
  assert.match(onboardingSource, /modelSetupProgress/);
  assert.match(onboardingSource, /title: "Starting chat model"/);
  assert.match(onboardingSource, /title: "Checking chat model"/);
  assert.match(onboardingSource, /title: "Chat model ready"/);
  assert.match(onboardingSource, /aria-label=\{`\$\{operation\.title\}:/);
  assert.doesNotMatch(onboardingSource, /Chat model is ready\."\)/);
});

test("model import and discovery expose durable job progress to onboarding", () => {
  assert.match(backendClientSource, /type ModelJobProgressCallback/);
  assert.match(backendClientSource, /waitForAppJob\(queued\.id, onProgress\)/);
  assert.match(backendClientSource, /onProgress\?\.\(job, parseJobDetail\(job\.status_detail\)\)/);
  assert.match(onboardingSource, /updateModelImportProgress/);
  assert.match(onboardingSource, /detail\.progress_percent/);
  assert.match(onboardingSource, /detail\.candidates_checked/);
});

test("model scanning states its real scope and supports a chosen folder", () => {
  assert.match(onboardingSource, /Scan this computer/);
  assert.match(onboardingSource, /Checking available drives/);
  assert.match(onboardingSource, /Choose folder/);
  assert.match(onboardingSource, /approveModelDiscoveryRoot\(normalized\)/);
  assert.match(onboardingSource, /refreshDetectedModels\(true, normalized\)/);
  assert.doesNotMatch(onboardingSource, /Scan device/);
});

test("continue and completion use the selected chat model readiness", () => {
  assert.match(
    onboardingSource,
    /const selected = models\.find\(\(model\) => model\.id === selectedModelId\);[\s\S]{0,120}Boolean\(selected && isModelRuntimeReady\(selected, modelRuntime\)\)/,
  );
  assert.match(
    onboardingSource,
    /const selectedChatModel = models\.find\(\(model\) => model\.id === selectedModelId\)/,
  );
});
