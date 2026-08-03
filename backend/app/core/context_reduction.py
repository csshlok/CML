from __future__ import annotations

import re


def build_context_reduction_plan(
    *,
    prompt: str,
    citations: list[dict],
    recent_turns: list[dict[str, str]] | None,
    memory_items: list[dict] | None,
    working_memory: dict | None,
    token_budget: int,
    cluster_descriptions: list[str] | None = None,
) -> dict:
    raw_history_tokens = sum(
        estimate_tokens(turn.get("content", "")) for turn in (recent_turns or [])
    )
    raw_memory_tokens = sum(
        estimate_tokens(str(item.get("summary") or item.get("text") or ""))
        for item in (memory_items or [])
    )
    raw_working_memory_tokens = estimate_tokens(str((working_memory or {}).get("summary") or ""))
    trimmed_turns = trim_recent_turns_to_budget(recent_turns or [], token_budget=token_budget)
    history_tokens_estimate = sum(
        estimate_tokens(turn.get("content", "")) for turn in trimmed_turns
    )
    history_turns_trimmed = max(0, len(recent_turns or []) - len(trimmed_turns))
    memory_plan = reduce_memory_items(
        prompt=prompt,
        memory_items=memory_items or [],
        token_budget=max(120, int(token_budget * 0.18)),
    )
    working_memory_plan = reduce_working_memory(
        prompt=prompt,
        working_memory=working_memory or {},
        token_budget=max(80, int(token_budget * 0.1)),
    )
    base_tokens = (
        estimate_tokens(prompt)
        + estimate_tokens("\n".join(cluster_descriptions or []))
        + history_tokens_estimate
        + memory_plan["tokens"]
        + working_memory_plan["tokens"]
        + 120
    )
    remaining = max(token_budget - base_tokens, 80)
    citation_plan = reduce_citations(prompt=prompt, citations=citations, token_budget=remaining)
    citation_trimmed_count = citation_plan["trimmed_count"] + max(
        0, len(citations) - len(citation_plan["citations"])
    )
    if (
        citation_trimmed_count
        and citation_plan["citations"]
        and not any(
            str(item.get("snippet") or "").endswith("...") for item in citation_plan["citations"]
        )
    ):
        citations_with_marker = [dict(item) for item in citation_plan["citations"]]
        longest_index, longest = max(
            enumerate(citations_with_marker),
            key=lambda item: estimate_tokens(str(item[1].get("snippet") or "")),
        )
        snippet = str(longest.get("snippet") or "")
        citations_with_marker[longest_index]["snippet"] = snippet.rstrip(" .") + "..."
        citation_plan = {
            **citation_plan,
            "citations": citations_with_marker,
            "tokens": sum(
                estimate_tokens(item.get("snippet", "")) for item in citations_with_marker
            ),
        }
    total_tokens = base_tokens + citation_plan["tokens"]
    raw_context_tokens = (
        estimate_tokens(prompt)
        + estimate_tokens("\n".join(cluster_descriptions or []))
        + raw_history_tokens
        + raw_memory_tokens
        + raw_working_memory_tokens
        + citation_plan["raw_tokens"]
        + 120
    )
    dropped_citations = [item for item in citation_plan["dropped"]]
    diagnostics = {
        "strategy": "salient_dedupe_v1",
        "raw_candidate_citation_count": len(citations),
        "deduped_candidate_citation_count": citation_plan["deduped_count"],
        "kept_citation_count": len(citation_plan["citations"]),
        "dropped_citation_count": len(dropped_citations),
        "dropped_citations": dropped_citations[:12],
        "kept_citation_titles": [
            str(item.get("source_title") or item.get("title") or "")
            for item in citation_plan["citations"]
        ],
        "memory_items_kept": len(memory_plan["items"]),
        "memory_items_dropped": memory_plan["dropped_count"],
        "working_memory_trimmed": bool(working_memory_plan["trimmed"]),
        "raw_candidate_tokens": citation_plan["raw_tokens"],
        "raw_context_tokens": raw_context_tokens,
        "final_context_tokens": total_tokens,
        "memory_tokens": memory_plan["tokens"],
        "raw_memory_tokens": raw_memory_tokens,
        "tokens_avoided": max(0, raw_context_tokens - total_tokens),
    }
    return {
        "citations": citation_plan["citations"],
        "prompt_tokens_estimate": total_tokens,
        "evidence_tokens_estimate": citation_plan["tokens"],
        "history_tokens_estimate": history_tokens_estimate,
        "history_turns_trimmed": history_turns_trimmed,
        "recent_turns": trimmed_turns,
        "citations_trimmed": citation_trimmed_count,
        "budget_applied": bool(
            citation_plan["trimmed_count"]
            or history_turns_trimmed
            or citation_plan["dropped"]
            or memory_plan["dropped_count"]
            or working_memory_plan["trimmed"]
        ),
        "memory_items": memory_plan["items"],
        "working_memory": working_memory_plan["working_memory"],
        "diagnostics": diagnostics,
    }


def reduce_citations(*, prompt: str, citations: list[dict], token_budget: int) -> dict:
    deduped, dropped = dedupe_citations(citations)
    raw_tokens = sum(estimate_tokens(citation.get("snippet", "")) for citation in deduped)
    if token_budget >= 2400:
        max_citations = min(len(deduped), 10)
    elif token_budget >= 1400:
        max_citations = min(len(deduped), 7)
    elif token_budget >= 900:
        max_citations = min(len(deduped), 5)
    else:
        max_citations = min(len(deduped), 3)
    selected = rank_citations(prompt, deduped)[:max_citations]
    per_citation_budget = max(40, token_budget // max(len(selected), 1))
    kept: list[dict] = []
    trimmed_count = 0
    kept_tokens = 0
    for citation in selected:
        trimmed = dict(citation)
        snippet = str(citation.get("snippet") or "")
        compressed = salient_excerpt(
            snippet, prompt=prompt, token_budget=max(24, per_citation_budget - 16)
        )
        trimmed["snippet"] = compressed
        kept.append(trimmed)
        original_tokens = estimate_tokens(snippet)
        new_tokens = estimate_tokens(compressed)
        kept_tokens += new_tokens
        if new_tokens < original_tokens:
            trimmed_count += 1
    budget_dropped = rank_citations(prompt, deduped)[max_citations:]
    dropped.extend(
        {
            "title": str(
                citation.get("source_title") or citation.get("title") or "Untitled source"
            ),
            "reason": "budget_limit",
        }
        for citation in budget_dropped
    )
    if (
        budget_dropped
        and kept
        and not any(str(item.get("snippet") or "").endswith("...") for item in kept)
    ):
        longest_index, longest = max(
            enumerate(kept),
            key=lambda item: estimate_tokens(str(item[1].get("snippet") or "")),
        )
        snippet = str(longest.get("snippet") or "")
        compressed = trim_text_to_token_budget(snippet, max(1, estimate_tokens(snippet) - 1))
        if compressed == snippet:
            compressed = snippet.rstrip(" .") + "..."
        kept[longest_index] = {**longest, "snippet": compressed}
        kept_tokens = kept_tokens - estimate_tokens(snippet) + estimate_tokens(compressed)
        trimmed_count += 1
    return {
        "citations": kept,
        "tokens": kept_tokens,
        "trimmed_count": trimmed_count,
        "raw_tokens": raw_tokens,
        "deduped_count": len(deduped),
        "dropped": dropped,
    }


def reduce_memory_items(*, prompt: str, memory_items: list[dict], token_budget: int) -> dict:
    if not memory_items:
        return {"items": [], "tokens": 0, "dropped_count": 0}
    ranked = sorted(memory_items, key=lambda item: _memory_score(item, prompt), reverse=True)
    kept: list[dict] = []
    used = 0
    dropped = 0
    for item in ranked:
        summary = str(item.get("summary") or item.get("text") or "").strip()
        if not summary:
            dropped += 1
            continue
        compressed = salient_excerpt(summary, prompt=prompt, token_budget=64)
        tokens = estimate_tokens(compressed)
        if kept and used + tokens > token_budget:
            dropped += 1
            continue
        clone = dict(item)
        clone["summary"] = compressed
        kept.append(clone)
        used += tokens
    return {"items": kept, "tokens": used, "dropped_count": dropped}


def reduce_working_memory(*, prompt: str, working_memory: dict, token_budget: int) -> dict:
    summary = str((working_memory or {}).get("summary") or "").strip()
    if not summary:
        return {"working_memory": working_memory or {}, "tokens": 0, "trimmed": False}
    compressed = salient_excerpt(summary, prompt=prompt, token_budget=token_budget)
    clone = dict(working_memory or {})
    clone["summary"] = compressed
    return {
        "working_memory": clone,
        "tokens": estimate_tokens(compressed),
        "trimmed": compressed != summary,
    }


def trim_recent_turns_to_budget(
    recent_turns: list[dict[str, str]], *, token_budget: int
) -> list[dict[str, str]]:
    if not recent_turns:
        return []
    history_budget = min(max(int(token_budget * 0.25), 96), 384)
    selected: list[dict[str, str]] = []
    used = 0
    for turn in reversed(recent_turns):
        content = str(turn.get("content") or "").strip()
        role = str(turn.get("role") or "").strip().lower()
        if role not in {"user", "assistant"} or not content:
            continue
        trimmed_content = salient_excerpt(
            content, prompt=content, token_budget=min(96, max(history_budget // 2, 32))
        )
        turn_tokens = estimate_tokens(trimmed_content)
        if selected and used + turn_tokens > history_budget:
            break
        if not selected and turn_tokens > history_budget:
            trimmed_content = salient_excerpt(content, prompt=content, token_budget=history_budget)
            turn_tokens = estimate_tokens(trimmed_content)
        selected.append({"role": role, "content": trimmed_content})
        used += turn_tokens
        if used >= history_budget:
            break
    selected.reverse()
    return selected


def salient_excerpt(text: str, *, prompt: str, token_budget: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if estimate_tokens(cleaned) <= token_budget:
        return cleaned
    segments = [
        segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if segment.strip()
    ]
    if not segments:
        return trim_text_to_token_budget(cleaned, token_budget)
    query_terms = _query_terms(prompt)
    scored = sorted(
        (
            (segment, _segment_score(segment, query_terms), index)
            for index, segment in enumerate(segments)
        ),
        key=lambda item: (item[1], -item[2]),
        reverse=True,
    )
    selected: list[str] = []
    used = 0
    for segment, _score, _index in scored:
        tokens = estimate_tokens(segment)
        if selected and used + tokens > token_budget:
            continue
        selected.append(segment)
        used += tokens
        if used >= token_budget:
            break
    if not selected:
        return trim_text_to_token_budget(cleaned, token_budget)
    # DEAD EXPERIMENT (reader v4): re-sorting selected sentences into source
    # order was part of an accuracy bundle that missed its promotion gate.
    # joined = " ".join(segment for _index, segment in sorted(selected))
    joined = " ".join(selected)
    if estimate_tokens(joined) > token_budget:
        return trim_text_to_token_budget(joined, token_budget)
    if joined != cleaned and not joined.endswith("..."):
        return joined.rstrip(" .") + "..."
    return joined


def dedupe_citations(citations: list[dict]) -> tuple[list[dict], list[dict]]:
    seen: set[str] = set()
    kept: list[dict] = []
    dropped: list[dict] = []
    for citation in citations:
        key = _dedupe_key(citation)
        if key in seen:
            dropped.append(
                {
                    "title": str(
                        citation.get("source_title") or citation.get("title") or "Untitled source"
                    ),
                    "reason": "duplicate_evidence",
                }
            )
            continue
        seen.add(key)
        kept.append(citation)
    return kept, dropped


def rank_citations(prompt: str, citations: list[dict]) -> list[dict]:
    query_terms = _query_terms(prompt)
    return sorted(
        citations,
        key=lambda citation: (
            float(citation.get("score") or 0.0),
            _segment_score(str(citation.get("snippet") or ""), query_terms),
        ),
        reverse=True,
    )


def trim_text_to_token_budget(text: str, token_budget: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if estimate_tokens(cleaned) <= token_budget:
        return cleaned
    max_chars = max(32, token_budget * 4)
    return cleaned[: max_chars - 3].rstrip() + "..."


def estimate_tokens(text: str) -> int:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    return max(1, len(cleaned) // 4)


def _query_terms(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]{4,}", str(text or "").lower())}


def _segment_score(segment: str, query_terms: set[str]) -> int:
    lowered = str(segment or "").lower()
    overlap = sum(1 for term in query_terms if term in lowered)
    return overlap * 10 + min(len(lowered) // 40, 5)


def _dedupe_key(citation: dict) -> str:
    source_id = str(
        citation.get("source_id") or citation.get("chunk_id") or citation.get("page_id") or ""
    ).strip()
    snippet = re.sub(r"\s+", " ", str(citation.get("snippet") or "").strip().lower())
    if len(snippet) > 160:
        snippet = snippet[:160]
    title = str(citation.get("source_title") or citation.get("title") or "").strip().lower()
    return "|".join([source_id, title, snippet])


def _memory_score(item: dict, prompt: str) -> tuple[int, int, int]:
    summary = str(item.get("summary") or item.get("text") or "")
    typed_contract = int(item.get("kind") == "typed_evidence_contract")
    return (typed_contract, _segment_score(summary, _query_terms(prompt)), len(summary))
