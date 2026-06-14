import { createBackgroundController, createChromeBackgroundDeps } from "./background-core.js";

const controller = createBackgroundController(createChromeBackgroundDeps(chrome, fetch));

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "cml:selection-cache") {
    const tabId = _sender?.tab?.id;
    void controller.cacheSelection(tabId, message.selection || {})
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    return true;
  }
  if (!message || message.type !== "cml:capture") return false;
  void controller.handleCapture(message)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
  return true;
});
