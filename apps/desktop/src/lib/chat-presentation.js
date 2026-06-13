export function analysisModeLabel(intent, coverageLedger) {
  const mode = coverageLedger?.analysis_mode;
  if (mode === "complete_analysis" || intent === "complete_analysis") return "Complete analysis";
  if (mode === "expanded_analysis" || intent === "expanded_analysis") return "Expanded analysis";
  if (intent === "general_chat") return "Direct chat";
  return "Vault retrieval";
}

export function describeCoverage(coverageLedger) {
  if (!coverageLedger) return null;
  const considered = Number(coverageLedger.sources_considered ?? 0);
  const analyzed = Number(coverageLedger.sources_analyzed ?? 0);
  const lowRelevance = Number(coverageLedger.sources_low_relevance ?? 0);
  const mode = analysisModeLabel("vault_question", coverageLedger);
  if (mode === "Complete analysis") {
    return `Scored ${considered} indexed source${considered === 1 ? "" : "s"} and analyzed ${analyzed}.`;
  }
  if (mode === "Expanded analysis") {
    return `Considered ${considered} indexed source${considered === 1 ? "" : "s"} and analyzed ${analyzed}.`;
  }
  if (analyzed > 0 || lowRelevance > 0) {
    return `Analyzed ${analyzed} source${analyzed === 1 ? "" : "s"} with ${lowRelevance} low-relevance result${lowRelevance === 1 ? "" : "s"} left out.`;
  }
  return null;
}

export function describePartialFailure(mode) {
  switch (mode) {
    case "none":
    case "":
    case undefined:
    case null:
      return null;
    case "general_chat_direct":
      return "Answered directly without vault retrieval.";
    case "no_citations":
      return "No grounded vault citations were found.";
    case "no_citations_direct_answer":
      return "No grounded vault citations were found, so CML fell back to an ungrounded direct answer.";
    case "embedding_unavailable":
      return "Semantic retrieval is unavailable because embeddings are not configured.";
    case "embedding_unavailable_direct_answer":
      return "Semantic retrieval is unavailable, so CML fell back to an ungrounded direct answer.";
    case "low_trust_extract_only":
      return "Only low-trust evidence was available, so CML stayed extractive instead of synthesizing.";
    case "refuse_sensitive_low_trust":
      return "Sensitive request with only low-trust evidence. CML refused to answer from it.";
    case "conflicting_evidence_extract_only":
      return "Retrieved evidence conflicted, so CML stayed extractive instead of synthesizing.";
    case "weak_support_extract_only":
      return "Evidence support was weak, so CML stayed extractive instead of synthesizing.";
    case "runtime_unavailable_extract_fallback":
      return "Grounded synthesis runtime was unavailable, so CML returned a retrieval-only fallback.";
    case "runtime_unavailable_expert_extract_fallback":
      return "Grounded synthesis runtime was unavailable, so CML returned an expert-assisted retrieval fallback.";
    case "general_chat_runtime_unavailable":
      return "Direct chat runtime was unavailable.";
    default:
      return `Partial failure mode: ${String(mode).replaceAll("_", " ")}.`;
  }
}

export function statusToneForPartialFailure(mode) {
  if (!mode || mode === "none") return "neutral";
  if (mode === "refuse_sensitive_low_trust") return "critical";
  if (
    mode === "embedding_unavailable_direct_answer"
    || mode === "no_citations_direct_answer"
    || mode === "conflicting_evidence_extract_only"
    || mode === "low_trust_extract_only"
  ) {
    return "warning";
  }
  return "muted";
}
