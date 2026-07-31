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
      return "Answered directly without library retrieval.";
    case "no_citations":
      return "No grounded library citations were found.";
    case "no_citations_direct_answer":
      return "No grounded vault citations were found, so Vault fell back to an ungrounded direct answer.";
    case "embedding_unavailable":
      return "Semantic retrieval is unavailable because embeddings are not configured.";
    case "embedding_unavailable_direct_answer":
      return "Semantic retrieval is unavailable, so Vault fell back to an ungrounded direct answer.";
    case "low_trust_extract_only":
      return "Only low-trust evidence was available, so Vault stayed extractive instead of synthesizing.";
    case "refuse_sensitive_low_trust":
      return "Sensitive request with only low-trust evidence. Vault refused to answer from it.";
    case "conflicting_evidence_extract_only":
      return "Retrieved evidence conflicted, so Vault stayed extractive instead of synthesizing.";
    case "weak_support_extract_only":
      return "Evidence support was weak, so Vault stayed extractive instead of synthesizing.";
    case "runtime_unavailable_extract_fallback":
      return "Grounded synthesis runtime was unavailable, so Vault returned a retrieval-only fallback.";
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

export function tokenizeChatInlineMarkdown(value) {
  const text = String(value ?? "");
  const tokens = [];
  let cursor = 0;

  while (cursor < text.length) {
    const marker = nextInlineMarker(text, cursor);
    if (!marker) {
      tokens.push({ type: "text", content: text.slice(cursor) });
      break;
    }
    const closing = text.indexOf(marker.marker, marker.index + marker.marker.length);
    if (closing < 0 || closing === marker.index + marker.marker.length) {
      tokens.push({ type: "text", content: text.slice(cursor) });
      break;
    }
    if (marker.index > cursor) {
      tokens.push({ type: "text", content: text.slice(cursor, marker.index) });
    }
    tokens.push({
      type:
        marker.marker === "**" || marker.marker === "__"
          ? "strong"
          : marker.marker === "`"
            ? "code"
            : "emphasis",
      content: text.slice(marker.index + marker.marker.length, closing),
    });
    cursor = closing + marker.marker.length;
  }

  if (tokens.length === 0) {
    tokens.push({ type: "text", content: text });
  }
  return tokens;
}

export function parseChatMarkdown(value) {
  const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let code = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push({ type: "paragraph", content: paragraph.join("\n") });
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    blocks.push(list);
    list = null;
  };

  for (const line of lines) {
    if (code) {
      if (/^\s*```/.test(line)) {
        blocks.push(code);
        code = null;
      } else {
        code.content.push(line);
      }
      continue;
    }
    const fence = line.match(/^\s*```([\w-]*)\s*$/);
    if (fence) {
      flushParagraph();
      flushList();
      code = { type: "code", language: fence[1] || "", content: [] };
      continue;
    }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        content: heading[2],
      });
      continue;
    }
    const unordered = line.match(/^(\s*)[-+*]\s+(.+)$/);
    const ordered = line.match(/^(\s*)\d+[.)]\s+(.+)$/);
    const item = unordered || ordered;
    if (item) {
      flushParagraph();
      const listType = ordered ? "ordered-list" : "unordered-list";
      if (list?.type !== listType) {
        flushList();
        list = { type: listType, items: [] };
      }
      list.items.push({
        content: item[2],
        depth: Math.max(0, Math.floor(item[1].replace(/\t/g, "  ").length / 2)),
      });
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push({ type: "blockquote", content: quote[1] });
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    paragraph.push(line);
  }

  if (code) {
    blocks.push(code);
  }
  flushParagraph();
  flushList();
  return blocks.length > 0 ? blocks : [{ type: "paragraph", content: "" }];
}

function nextInlineMarker(text, cursor) {
  const match = /(\*\*|__|`|\*)/g;
  match.lastIndex = cursor;
  const found = match.exec(text);
  return found ? { marker: found[0], index: found.index } : null;
}
