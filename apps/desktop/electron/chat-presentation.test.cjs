const test = require("node:test");
const assert = require("node:assert/strict");

test("analysisModeLabel distinguishes complete and expanded analysis", async () => {
  const mod = await import("../src/lib/chat-presentation.js");

  assert.equal(mod.analysisModeLabel("complete_analysis", null), "Complete analysis");
  assert.equal(
    mod.analysisModeLabel("vault_question", { analysis_mode: "expanded_analysis" }),
    "Expanded analysis",
  );
  assert.equal(mod.analysisModeLabel("general_chat", null), "Direct chat");
});

test("describePartialFailure explains degraded retrieval states", async () => {
  const mod = await import("../src/lib/chat-presentation.js");

  assert.match(
    mod.describePartialFailure("embedding_unavailable_direct_answer"),
    /fell back to an ungrounded direct answer/i,
  );
  assert.match(
    mod.describePartialFailure("conflicting_evidence_extract_only"),
    /conflicted/i,
  );
  assert.equal(mod.describePartialFailure("none"), null);
});

test("describeCoverage summarizes complete analysis counts", async () => {
  const mod = await import("../src/lib/chat-presentation.js");

  assert.equal(
    mod.describeCoverage({
      analysis_mode: "complete_analysis",
      sources_considered: 12,
      sources_analyzed: 12,
      sources_low_relevance: 4,
    }),
    "Scored 12 indexed sources and analyzed 12.",
  );
});
