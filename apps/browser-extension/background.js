import { createBackgroundController, createChromeBackgroundDeps } from "./background-core.js";

const controller = createBackgroundController(createChromeBackgroundDeps(chrome, fetch));

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "cml:capture") return false;
  void controller.handleCapture(message)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
  return true;
});

chrome.commands.onCommand.addListener((command) => {
  void controller.handleCommand(command).catch(() => {
    // The popup and backend surfaces report capture failures; the command path should not crash the worker.
  });
});
