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
