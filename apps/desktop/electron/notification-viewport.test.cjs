const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const notificationsSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "product", "Notifications.tsx"),
  "utf8",
);
const settingsSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.settings.tsx"),
  "utf8",
);
const rootSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "__root.tsx"),
  "utf8",
);
const appShellSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "AppShell.tsx"),
  "utf8",
);
const homeSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.home.tsx"),
  "utf8",
);

test("Settings feedback uses the application notification viewport", () => {
  assert.match(settingsSource, /import \{ notify \} from "@\/components\/product\/Notifications"/);
  assert.match(settingsSource, /notify\(\{\s*title: normalized,/);
  assert.doesNotMatch(settingsSource, /statusMessage\s*&&/);
  assert.match(rootSource, /<NotificationViewport \/>/);
  assert.match(
    settingsSource,
    /lastPollingNoticeRef\.current === normalized/,
  );
  assert.match(settingsSource, /setPollingStatusMessage\(message\)/);
});

test("notifications stay fixed to the user frame and leave after a short fade", () => {
  assert.match(notificationsSource, /notificationFadeAfterMs = 5000/);
  assert.match(notificationsSource, /notificationRemoveAfterMs = 5500/);
  assert.match(
    notificationsSource,
    /fixed inset-x-4 bottom-5[\s\S]*items-center/,
  );
  assert.match(notificationsSource, /leavingIds\.has\(notification\.id\)/);
  assert.match(notificationsSource, /opacity-0/);
  assert.match(notificationsSource, /motion-reduce:transition-none/);
});

test("notifications remain accessible and manually dismissible", () => {
  assert.match(notificationsSource, /role=\{tone === "error" \? "alert" : "status"\}/);
  assert.match(notificationsSource, /aria-label="Dismiss notification"/);
  assert.match(notificationsSource, /onClick=\{\(\) => dismiss\(notification\.id\)\}/);
});

test("persistent notifications support approve and cancel actions", () => {
  assert.match(notificationsSource, /persistent\?: boolean/);
  assert.match(notificationsSource, /if \(notification\.persistent\) return/);
  assert.match(notificationsSource, /secondaryActionLabel\?: string/);
  assert.match(notificationsSource, /notification\.onSecondaryAction\?\.\(\)/);
  assert.match(appShellSource, /title: "Odin is requesting access"/);
  assert.match(appShellSource, /secondaryActionLabel: "Cancel request"/);
  assert.match(appShellSource, /actionLabel: "Approve"/);
  assert.match(appShellSource, /listCliPairingChallenges\(\)/);
  assert.match(appShellSource, /!onCodeConnectionsPage/);
});

test("model-dependent work reports outages once and confirms automatic recovery", () => {
  assert.match(appShellSource, /nextJobs\.blocked_local_model > 0/);
  assert.match(appShellSource, /title: "Local model unavailable"/);
  assert.match(
    appShellSource,
    /Document descriptions and clustering are paused while Vault restarts the model\./,
  );
  assert.match(appShellSource, /title: "Local model restored"/);
  assert.match(
    appShellSource,
    /Vault resumed document descriptions and clustering\./,
  );
  assert.match(appShellSource, /modelAvailabilityNoticeRef/);
  assert.match(homeSource, /title: "Local model unavailable"/);
  assert.match(homeSource, /Vault will resume them after the model restarts\./);
  assert.match(homeSource, /\{ label: "Waiting for model", value: jobs\.blocked_local_model \}/);
});
