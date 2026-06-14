const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadPreload() {
  const filePath = path.join(__dirname, "preload.cjs");
  const source = fs.readFileSync(filePath, "utf8");
  const invocations = [];
  let exposedApi = null;
  const ipcRenderer = {
    invoke: async (channel, ...args) => {
      invocations.push({ channel, args });
      return channel === "cml:read-clipboard-text" ? "clipboard text from preload" : true;
    },
    on: () => {},
    removeListener: () => {},
  };
  const sandbox = {
    require: (id) => {
      if (id === "electron") {
        return {
          contextBridge: {
            exposeInMainWorld: (_name, api) => {
              exposedApi = api;
            },
          },
          ipcRenderer,
          webUtils: {
            getPathForFile: () => null,
          },
        };
      }
      return require(id);
    },
    window: {
      addEventListener: () => {},
      location: { pathname: "/" },
    },
    process,
    console,
    module: { exports: {} },
    exports: {},
  };
  vm.runInNewContext(source, sandbox, { filename: filePath });
  return { exposedApi, invocations };
}

test("preload exposes a readClipboardText bridge for quick capture", async () => {
  const { exposedApi, invocations } = loadPreload();

  const result = await exposedApi.readClipboardText();

  assert.equal(result, "clipboard text from preload");
  assert.deepEqual(invocations[0], { channel: "cml:read-clipboard-text", args: [] });
});
