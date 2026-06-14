const test = require("node:test");
const assert = require("node:assert/strict");

test("describeBridgeCaptureResult explains review-required downgraded captures", async () => {
  const mod = await import("../src/lib/bridge-presentation.js");

  assert.match(
    mod.describeBridgeCaptureResult({
      source_type: "external_transcript",
      quality_state: "partially_grounded",
      trust_tier: "external_capture",
      review_required: true,
    }),
    /waiting in the review queue/i,
  );
});

test("describeBridgeCaptureResult distinguishes user artifacts from trusted reuse", async () => {
  const mod = await import("../src/lib/bridge-presentation.js");

  assert.match(
    mod.describeBridgeCaptureResult({
      source_type: "external_artifact",
      quality_state: "user_artifact",
      trust_tier: "external_capture",
      review_required: false,
    }),
    /outside trusted memory by default/i,
  );
});

test("describeBridgeReviewDecision explains approve vs keep gated", async () => {
  const mod = await import("../src/lib/bridge-presentation.js");

  assert.match(
    mod.describeBridgeReviewDecision({ title: "External model turn", trust_tier: "trusted_reviewed" }, true),
    /can participate in trusted reuse/i,
  );
  assert.match(
    mod.describeBridgeReviewDecision({ title: "External model turn", trust_tier: "external_capture" }, false),
    /remains outside trusted reuse/i,
  );
});
