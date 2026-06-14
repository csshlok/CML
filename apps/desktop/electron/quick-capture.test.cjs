const test = require("node:test");
const assert = require("node:assert/strict");

test("artifact quick capture trims clipboard text and derives a bridge artifact payload", async () => {
  const mod = await import("../src/lib/quick-capture.js");

  const draft = mod.applyClipboardTextToDraft(
    {
      ...mod.createQuickCaptureDraft("artifact"),
      vaultId: "vault-1",
    },
    "  Important retrospective note\nSecond line  ",
  );
  const submission = mod.buildQuickCaptureSubmission(draft);

  assert.equal(submission.kind, "artifact");
  assert.equal(submission.payload.vault_id, "vault-1");
  assert.equal(submission.payload.title, "Important retrospective note");
  assert.equal(submission.payload.content, "Important retrospective note\nSecond line");
  assert.equal(submission.payload.artifact_type, "quick_capture");
});

test("turn quick capture requires both prompt and response before it can submit", async () => {
  const mod = await import("../src/lib/quick-capture.js");

  const incomplete = {
    ...mod.createQuickCaptureDraft("turn"),
    vaultId: "vault-1",
    prompt: "What changed today?",
  };
  assert.equal(mod.canSubmitQuickCapture(incomplete), false);

  const complete = {
    ...incomplete,
    response: "We widened the quick-capture flow.",
  };
  const submission = mod.buildQuickCaptureSubmission(complete);

  assert.equal(mod.canSubmitQuickCapture(complete), true);
  assert.equal(submission.kind, "turn");
  assert.equal(submission.payload.user_prompt, "What changed today?");
  assert.equal(submission.payload.model_response, "We widened the quick-capture flow.");
});
