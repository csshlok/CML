let selectionTimer = null;
let lastSelection = { title: "", text: "", url: "" };

document.documentElement?.setAttribute("data-cml-capture-ready", "1");

function flushSelectionSnapshot() {
  const text = String(window.getSelection()?.toString() || "").trim();
  if (!text) return;
  const title = document.title || location.hostname || "page";
  lastSelection = {
    title: `Selection from ${title}`,
    text,
    url: location.href,
  };
  document.documentElement?.setAttribute("data-cml-last-selection-length", String(text.length));
  document.documentElement?.setAttribute("data-cml-last-selection-title", lastSelection.title);
  document.documentElement?.setAttribute("data-cml-last-selection-text", lastSelection.text);
  document.documentElement?.setAttribute("data-cml-last-selection-url", lastSelection.url);
  void chrome.runtime.sendMessage({
    type: "cml:selection-cache",
    selection: lastSelection,
  }).catch(() => {
    // Ignore cache update failures; live selection capture may still work.
  });
}

function scheduleSelectionSnapshot() {
  if (selectionTimer) {
    clearTimeout(selectionTimer);
  }
  selectionTimer = setTimeout(() => {
    flushSelectionSnapshot();
  }, 120);
}

document.addEventListener("selectionchange", () => {
  scheduleSelectionSnapshot();
});

document.addEventListener("mouseup", () => {
  scheduleSelectionSnapshot();
});

document.addEventListener("keyup", () => {
  scheduleSelectionSnapshot();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "cml:get-selection") {
    return false;
  }
  const currentText = String(window.getSelection()?.toString() || "").trim();
  if (currentText) {
    const title = document.title || location.hostname || "page";
    lastSelection = {
      title: `Selection from ${title}`,
      text: currentText,
      url: location.href,
    };
  }
  sendResponse(lastSelection);
  return false;
});
