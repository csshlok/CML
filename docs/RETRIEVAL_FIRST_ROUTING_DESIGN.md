# Retrieval-First Chat Routing Design

Last updated: 2026-06-13

## Problem

Current chat routing is too brittle for CML's product promise. The existing intent path is mostly keyword-based and defaults to `general_chat` when no marker is found. That means natural memory-seeking prompts can bypass vault retrieval entirely:

- "Give me an overview."
- "Where did we leave off?"
- "What are the main takeaways?"
- "Summarize what we discussed yesterday."

For a context-management product, a false `general_chat` route is more damaging than a false retrieval route. If the vault is bypassed, the model can hallucinate or answer generically with no clear signal that CML did not use the user's memory.

## Decision

CML V1 should use retrieval-first routing.

Default route: `vault_question`.

Narrow exceptions:

- explicit attachment ingestion
- explicit expanded analysis
- explicit cluster-scoped question
- obvious conversational/acknowledgment prompts
- explicit user request to just chat without vault context
- zero indexed sources, where retrieval cannot produce context

Do not add a semantic intent classifier for V1 unless telemetry proves the routing failure rate justifies it. An embedding-exemplar classifier would add latency to every chat turn, especially on low-spec machines where embeddings are already a bottleneck. A larger regex/pattern classifier would recreate the current keyword-list problem with more surface area.

## Routing Order

1. If the request includes supported attachments or an explicit attachment action, route to attachment ingestion.
2. If the request explicitly asks for expanded/complete-scope analysis, route to expanded analysis.
3. If the request has an explicit `cluster_id` or cluster-scoped mode, route to cluster question.
4. If the prompt is only conversational, acknowledgment, or an explicit "do not use my vault" style request, route to `general_chat`.
5. If the active vault has zero indexed sources and no distilled memory, skip retrieval and return a direct local LLM answer if available, clearly marked as ungrounded.
6. Otherwise, route to `vault_question`.

This intentionally lets many ordinary world-knowledge prompts run through retrieval first. The cost of an unnecessary semantic search is lower than the product cost of silently bypassing the vault on memory-seeking prompts.

## Retrieval Outcome Handling

Retrieval-first only works if empty retrieval degrades well.

When retrieval produces supported citations:

- synthesize from retrieved evidence
- cite the supporting sources
- preserve trust/conflict warnings from the evidence pipeline

When retrieval runs but finds no relevant citations:

- do not stop at a dead-end "no citations" response
- attempt a direct local LLM answer if the runtime is available
- clearly mark the answer as ungrounded: no relevant vault context was found
- expose the no-results state in response metadata

When embeddings are unavailable:

- treat this as separate from routing
- explain that vault retrieval is unavailable because embeddings are not configured or failed
- attempt a direct local LLM answer if the runtime is available
- clearly mark the answer as ungrounded
- return an actionable setup/degraded-mode message if no runtime is available

When the runtime is unavailable:

- return the compact retrieval/context result if useful
- otherwise return an explicit runtime-unavailable degraded state
- do not pretend synthesis happened

## Telemetry Required Before Classifier Work

Add routing telemetry before considering a real classifier:

- selected route
- route reason
- indexed source count
- whether retrieval was attempted
- candidate count
- citation count
- no-citations fallback usage
- embedding-unavailable fallback usage
- direct-general reason
- retrieval latency
- generation latency

This lets CML measure actual routing failures instead of guessing from examples. A classifier should only be added if real usage shows unacceptable retrieval-first latency or repeated wrong-route outcomes that simple explicit-mode rules cannot solve.

## Implementation Plan

1. Replace the default branch in chat intent routing with `vault_question`.
2. Keep explicit structural routes ahead of the default: attachments, expanded analysis, and cluster-scoped mode.
3. Tighten `general_chat` so it only fires for obvious conversational prompts or explicit no-vault/direct-chat requests.
4. Add an indexed-source and memory count check before retrieval to avoid useless vault searches on empty vaults.
5. Change the no-citations path to fall back to direct local LLM synthesis when available, with an ungrounded warning.
6. Change the embedding-unavailable path to the same ungrounded direct-answer fallback when runtime is ready.
7. Add route metadata and diagnostics fields for routing decisions and fallback reasons.
8. Add regression tests for natural prompts that currently miss retrieval:
   - "Give me an overview."
   - "Where did we leave off?"
   - "What are the key points from yesterday?"
   - "Summarize what we discussed."
   - "What should I focus on next?"
9. Add tests for explicit direct-chat prompts so normal conversation still works.
10. Defer semantic classifier work until routing telemetry shows a concrete need.

## V1 Acceptance Criteria

- Natural memory-seeking prompts route to vault retrieval by default.
- CML never silently bypasses vault context unless the user clearly asked for direct chat or the vault has no usable context.
- Empty retrieval produces a useful ungrounded fallback when the local runtime is available.
- Missing embeddings do not hard-stop chat if the local runtime can answer directly.
- Routing decisions are observable in diagnostics and testable in regression fixtures.
