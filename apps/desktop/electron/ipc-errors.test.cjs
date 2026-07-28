const assert = require("node:assert/strict");
const test = require("node:test");

const {
  cleanIpcErrorMessage,
  invokeWithCleanError,
} = require("./ipc-errors.cjs");

test("remote IPC wrappers are removed from user-facing desktop errors", () => {
  assert.equal(
    cleanIpcErrorMessage(
      new Error(
        "Error invoking remote method 'cml:install-odin-launcher': Error: Windows could not update your user PATH.",
      ),
      "Could not install Odin.",
    ),
    "Windows could not update your user PATH.",
  );
  assert.equal(cleanIpcErrorMessage("", "Could not install Odin."), "Could not install Odin.");
});

test("clean IPC invocation preserves results and rejects with readable copy", async () => {
  const installed = await invokeWithCleanError(
    { invoke: async () => ({ installed: true }) },
    "cml:install-odin-launcher",
    "Could not install Odin.",
  );
  assert.deepEqual(installed, { installed: true });

  await assert.rejects(
    invokeWithCleanError(
      {
        invoke: async () => {
          throw new Error(
            "Error invoking remote method 'cml:install-odin-launcher': Error: Install failed.",
          );
        },
      },
      "cml:install-odin-launcher",
      "Could not install Odin.",
    ),
    { message: "Install failed." },
  );
});
