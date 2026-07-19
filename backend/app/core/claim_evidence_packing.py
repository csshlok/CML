from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from backend.app.core.context_reduction import estimate_tokens
from backend.app.core.multi_session_ledger import (
    LedgerEntry,
    build_evidence_ledger,
    ledger_anchor_keys,
    ledger_priority,
)


CLAIM_PACKER_VERSION = "claim-first-cited-v3-ledger"

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_AGGREGATION_RE = re.compile(
    r"\b(how many|how much|how often|how long|total|combined|sum|times did|"
    r"more|less|older|younger|before|after|changed|change|current|latest)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "about", "after", "again", "also", "been", "before", "could", "did", "does",
    "from", "have", "into", "many", "more", "much", "should", "that", "their",
    "them", "then", "there", "these", "they", "this", "those", "what", "when",
    "where", "which", "with", "would", "your", "you", "were", "was", "are", "the",
    "and", "for", "how", "who", "why",
}


def estimate_claim_tokens(text: str) -> int:
    """Conservatively estimate chat tokens without a provider tokenizer.

    Character-only estimates undercount citation-heavy and identifier-heavy text.
    The lexical-piece estimate covers that case while the character estimate remains
    the stronger bound for ordinary prose.
    """
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    lexical_pieces = len(re.findall(r"\w+|[^\w\s]", cleaned, re.UNICODE))
    return max(1, len(cleaned) // 4, math.ceil(lexical_pieces * 1.15))


@dataclass(frozen=True)
class SessionEnvelope:
    session_id: str
    date: str
    turns: list[dict]
    retrieval_rank: int


@dataclass(frozen=True)
class Claim:
    session_id: str
    date: str
    retrieval_rank: int
    turn_index: int
    sentence_index: int
    speaker: str
    text: str
    tokens: int

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.session_id, self.turn_index, self.sentence_index)


def pack_claim_evidence(
    *,
    question: str,
    sessions: list[SessionEnvelope],
    token_budget: int,
    question_type: str = "",
) -> tuple[str, dict]:
    if token_budget <= 0:
        raise ValueError("token_budget must be positive")
    claims = _claims(sessions)
    if not claims:
        return "", _metadata([], [], token_budget=token_budget, used_tokens=0)

    scores = _score_claims(question, question_type, claims)
    ledger_plan, ledger_entries = build_evidence_ledger(
        question, question_type, claims
    )
    for claim in claims:
        scores[claim.key] += ledger_priority(ledger_entries[claim.key], ledger_plan)
    by_session: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        by_session[claim.session_id].append(claim)

    selected: dict[tuple[str, int, int], Claim] = {}
    selection_reason: dict[tuple[str, int, int], str] = {}
    used = 0

    def add(claim: Claim, reason: str) -> bool:
        nonlocal used
        if claim.key in selected:
            return True
        rendered_tokens = claim.tokens + 12
        if selected and used + rendered_tokens > token_budget:
            return False
        selected[claim.key] = claim
        selection_reason[claim.key] = reason
        used += rendered_tokens
        return True

    # Preserve cross-session coverage before filling by score. This costs little because
    # each unit is a sentence, not a complete conversation.
    for session in sorted(sessions, key=lambda item: item.retrieval_rank):
        candidates = by_session.get(session.session_id) or []
        if candidates:
            add(max(candidates, key=lambda item: scores[item.key]), "session_coverage")

    # Preserve the typed values and start/end/update anchors needed by deterministic
    # multi-session operations before filling the remaining packet by relevance.
    by_position = {claim.key: claim for claim in claims}
    for key in ledger_anchor_keys(ledger_entries, ledger_plan):
        add(by_position[key], "ledger_anchor")

    ranked = sorted(
        claims,
        key=lambda item: (
            scores[item.key],
            -item.retrieval_rank,
            item.date,
            -item.turn_index,
        ),
        reverse=True,
    )
    for claim in ranked:
        if not add(claim, "ranked_claim"):
            continue

    # If a selected sentence has an adjacent sentence in the same turn, use remaining
    # space for local expansion. This recovers qualifiers without pulling the full session.
    for claim in list(selected.values()):
        for sentence_index in (claim.sentence_index - 1, claim.sentence_index + 1):
            neighbor = by_position.get((claim.session_id, claim.turn_index, sentence_index))
            if neighbor is not None:
                add(neighbor, "adjacent_expansion")

    ordered = sorted(
        selected.values(),
        key=lambda item: (item.date, item.session_id, item.turn_index, item.sentence_index),
    )
    context = _render(ordered, ledger_entries=ledger_entries, annotate=True)
    actual_estimate = estimate_claim_tokens(context)
    if actual_estimate > token_budget:
        # Rendering headers can push the estimate slightly over the selection allowance.
        # Remove the lowest-scored non-coverage claims until the complete packet fits.
        removable = sorted(
            (
                claim
                for claim in ordered
                if selection_reason.get(claim.key) != "session_coverage"
            ),
            key=lambda item: scores[item.key],
        )
        while actual_estimate > token_budget and removable:
            selected.pop(removable.pop(0).key, None)
            ordered = sorted(
                selected.values(),
                key=lambda item: (item.date, item.session_id, item.turn_index, item.sentence_index),
            )
            context = _render(ordered, ledger_entries=ledger_entries, annotate=True)
            actual_estimate = estimate_claim_tokens(context)

    meta = _metadata(
        claims,
        ordered,
        token_budget=token_budget,
        used_tokens=actual_estimate,
    )
    meta["selection_reasons"] = dict(Counter(selection_reason.get(item.key, "unknown") for item in ordered))
    selected_ledger = [ledger_entries[item.key] for item in ordered]
    meta["ledger"] = {
        "operation": ledger_plan.operation,
        "anchor_count": meta["selection_reasons"].get("ledger_anchor", 0),
        "assertion_modes": dict(Counter(item.assertion_mode for item in selected_ledger)),
        "numeric_roles": dict(Counter(item.numeric_role for item in selected_ledger)),
        "event_roles": dict(Counter(item.event_role for item in selected_ledger)),
    }
    return context, meta


def _claims(sessions: Iterable[SessionEnvelope]) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[tuple[str, str, str]] = set()
    for session in sessions:
        for turn_index, turn in enumerate(session.turns):
            speaker = str(turn.get("role") or "unknown").strip().lower()
            content = " ".join(str(turn.get("content") or "").split())
            for sentence_index, sentence in enumerate(_sentences(content)):
                normalized = " ".join(sentence.casefold().split())
                dedupe_key = (session.session_id, speaker, normalized)
                if not normalized or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                claims.append(
                    Claim(
                        session_id=session.session_id,
                        date=session.date,
                        retrieval_rank=session.retrieval_rank,
                        turn_index=turn_index,
                        sentence_index=sentence_index,
                        speaker=speaker,
                        text=sentence,
                        tokens=estimate_claim_tokens(sentence),
                    )
                )
    return claims


def _sentences(content: str) -> list[str]:
    if not content:
        return []
    initial = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+|\n+", content)
        if item.strip()
    ]
    output: list[str] = []
    for sentence in initial:
        if len(sentence) <= 700:
            output.append(sentence)
            continue
        clauses = [item.strip() for item in re.split(r"(?<=[;:])\s+|\s+[—–-]\s+", sentence) if item.strip()]
        if len(clauses) == 1:
            clauses = [sentence[index : index + 600].strip() for index in range(0, len(sentence), 600)]
        output.extend(clauses)
    return output


def _score_claims(question: str, question_type: str, claims: list[Claim]) -> dict[tuple[str, int, int], float]:
    query_tokens = _terms(question)
    document_frequency: Counter[str] = Counter()
    claim_terms: dict[tuple[str, int, int], set[str]] = {}
    for claim in claims:
        terms = _terms(claim.text)
        claim_terms[claim.key] = terms
        document_frequency.update(terms)
    count = max(len(claims), 1)
    aggregation = bool(_AGGREGATION_RE.search(question))
    asks_numeric = bool(re.search(r"\b(how many|how much|how long|percent|total|more|less|older|younger)\b", question, re.I))
    asks_temporal = "temporal" in question_type or bool(re.search(r"\b(when|before|after|latest|current|now|changed)\b", question, re.I))
    scores: dict[tuple[str, int, int], float] = {}
    for claim in claims:
        overlap = query_tokens & claim_terms[claim.key]
        lexical = sum(math.log((count + 1) / (document_frequency[term] + 1)) + 1 for term in overlap)
        phrase = sum(1.5 for pair in _bigrams(question) if pair in claim.text.casefold())
        numeric = 1.5 if asks_numeric and re.search(r"\b\d[\d,./:%-]*\b", claim.text) else 0.0
        temporal = 1.0 if asks_temporal and re.search(r"\b(today|yesterday|tomorrow|last|next|since|until|\d{4})\b", claim.text, re.I) else 0.0
        role = 0.75 if question_type == "single-session-assistant" and claim.speaker == "assistant" else 0.0
        if question_type != "single-session-assistant" and claim.speaker == "user":
            role += 0.25
        rank_prior = 1.0 / (1 + claim.retrieval_rank)
        breadth = 0.35 if aggregation and overlap else 0.0
        scores[claim.key] = lexical + phrase + numeric + temporal + role + rank_prior + breadth
    return scores


def _terms(text: str) -> set[str]:
    return {
        token
        for token in (item.casefold() for item in _TOKEN_RE.findall(text))
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _bigrams(text: str) -> set[str]:
    tokens = [token.casefold() for token in _TOKEN_RE.findall(text) if token.casefold() not in _STOPWORDS]
    return {f"{left} {right}" for left, right in zip(tokens, tokens[1:])}


def _render(
    claims: list[Claim],
    *,
    ledger_entries: dict[tuple[str, int, int], LedgerEntry] | None = None,
    annotate: bool = False,
) -> str:
    lines: list[str] = []
    current: tuple[str, str] | None = None
    for claim in claims:
        header = (claim.session_id, claim.date)
        if header != current:
            if lines:
                lines.append("")
            lines.append(f"Session {claim.session_id} — {claim.date}")
            current = header
        ledger = (ledger_entries or {}).get(claim.key)
        annotation = f" {{{ledger.annotation}}}" if annotate and ledger and ledger.annotation else ""
        lines.append(
            f"- [{claim.speaker} turn {claim.turn_index} sentence {claim.sentence_index}]{annotation} {claim.text}"
        )
    return "\n".join(lines)


def _metadata(
    all_claims: list[Claim],
    selected: list[Claim],
    *,
    token_budget: int,
    used_tokens: int,
) -> dict:
    selected_sessions = list(dict.fromkeys(item.session_id for item in selected))
    all_sessions = list(dict.fromkeys(item.session_id for item in all_claims))
    return {
        "packing": CLAIM_PACKER_VERSION,
        "token_budget": token_budget,
        "packed_tokens_estimate": used_tokens,
        "unbounded_claim_tokens_estimate": estimate_claim_tokens(_render(all_claims)),
        "candidate_claim_count": len(all_claims),
        "selected_claim_count": len(selected),
        "omitted_claim_count": max(0, len(all_claims) - len(selected)),
        "candidate_session_count": len(all_sessions),
        "included_session_count": len(selected_sessions),
        "included_session_ids": selected_sessions,
        "omitted_session_ids": [item for item in all_sessions if item not in selected_sessions],
        "context_truncated": len(selected) < len(all_claims),
    }
