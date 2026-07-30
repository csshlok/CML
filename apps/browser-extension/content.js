let selectionTimer = null;
let lastSelection = { title: "", text: "", url: "" };

function flushSelectionSnapshot() {
  const text = String(window.getSelection()?.toString() || "").trim();
  if (!text) return;
  const title = document.title || location.hostname || "page";
  lastSelection = {
    title: `Selection from ${title}`,
    text,
    url: location.href,
  };
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
  if (
    !message ||
    message.type !== "cml:get-selection" ||
    typeof message.nonce !== "string" ||
    message.nonce.length < 16
  ) {
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
  sendResponse({ ...lastSelection, nonce: message.nonce });
  if (message.consume) {
    lastSelection = { title: "", text: "", url: "" };
  }
  return false;
});
