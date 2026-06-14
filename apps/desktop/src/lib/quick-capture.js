export function createQuickCaptureDraft(mode = "artifact") {
  return {
    mode,
    vaultId: "",
    clusterId: "",
    clientName: "desktop-quick-capture",
    title: mode === "artifact" ? "Clipboard capture" : "",
    prompt: "",
    response: "",
  };
}

export function applyClipboardTextToDraft(draft, clipboardText) {
  const normalized = String(clipboardText || "").trim();
  if (!normalized) return { ...draft };
  if (draft.mode === "turn") {
    return {
      ...draft,
      response: draft.response.trim() ? draft.response : normalized,
    };
  }
  const existingTitle = String(draft.title || "").trim();
  return {
    ...draft,
    title:
      existingTitle && existingTitle !== "Clipboard capture"
        ? draft.title
        : inferClipboardTitle(normalized),
    response: draft.response.trim() ? draft.response : normalized,
  };
}

export function canSubmitQuickCapture(draft) {
  if (!String(draft.vaultId || "").trim()) return false;
  if (draft.mode === "turn") {
    return Boolean(String(draft.prompt || "").trim() && String(draft.response || "").trim());
  }
  return Boolean(String(draft.title || "").trim() && String(draft.response || "").trim());
}

export function buildQuickCaptureSubmission(draft) {
  const vaultId = String(draft.vaultId || "").trim();
  if (!vaultId) {
    throw new Error("A vault must be selected before saving.");
  }
  const clusterId = String(draft.clusterId || "").trim() || null;
  const clientName = String(draft.clientName || "").trim() || "desktop-quick-capture";
  if (draft.mode === "turn") {
    const prompt = String(draft.prompt || "").trim();
    const response = String(draft.response || "").trim();
    if (!prompt || !response) {
      throw new Error("Both prompt and response are required for a saved turn.");
    }
    return {
      kind: "turn",
      payload: {
        vault_id: vaultId,
        cluster_id: clusterId,
        client_name: clientName,
        user_prompt: prompt,
        model_response: response,
        metadata: { capture_surface: "desktop_quick_capture" },
      },
    };
  }
  const title = String(draft.title || "").trim();
  const content = String(draft.response || "").trim();
  if (!title || !content) {
    throw new Error("A title and content are required for a saved artifact.");
  }
  return {
    kind: "artifact",
    payload: {
      vault_id: vaultId,
      cluster_id: clusterId,
      client_name: clientName,
      title,
      content,
      artifact_type: "quick_capture",
      metadata: { capture_surface: "desktop_quick_capture" },
    },
  };
}

function inferClipboardTitle(text) {
  const firstLine = text.split(/\r?\n/, 1)[0]?.trim() || "";
  if (!firstLine) return "Clipboard capture";
  if (firstLine.length <= 60) return firstLine;
  return `${firstLine.slice(0, 57).trimEnd()}...`;
}
