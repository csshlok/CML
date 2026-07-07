# Overall Context

Last updated: 2026-07-07

This file preserves the longer-form current state behind `docs/PROJECT_CONTEXT.md`. It should hold durable background, validation summaries, and high-signal historical notes, not stale architecture claims.

## Current Source Of Truth

- Compact operating brief: `docs/PROJECT_CONTEXT.md`
- Migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`

## Architecture State

The project has completed its migration away from the LoRA cluster-expert path.

The live architecture is now RAG-only:

- retrieval is the evidence authority
- clusters are retrieval scopes with cached profile metadata
- chat and Bridge share a retrieval-first packet contract
- token reduction comes from packet shaping and cache reuse, not adapter compression
- desktop setup and packaged runtime no longer expect a second expert runtime

The earlier bundle/expert-compression architecture is historical only and should not be treated as the current product contract.

## What Changed In The Migration

The migration replaced the old `retrieval + LoRA expert` direction with a single RAG stack:

- removed LoRA runtime, training, evaluation, proof, and artifact lifecycle code
- removed expert-oriented cluster statuses and replaced them with RAG-native lifecycle fields
- moved cluster refresh to indexing-driven summary/glossary refresh
- unified chat and Bridge on the same packet shape
- removed onboarding, settings, and packaging assumptions about an expert runtime
- converted the live model recommender path to chat-only compatibility logic

Current cluster metadata now centers on:

- `index_status`
- `profile_status`
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

## Validation That Passed

The migration has already been validated beyond static code changes.

Live isolated validation passed:

- `search/semantic` returned grounded hits from the seeded RAG vault
- `chat/context` returned grounded citations and retrieval fallback output
- `bridge/context` returned grounded citations and cluster profile data
- desktop screens validated against the isolated backend loaded without console errors on the checked paths

Broader regression validation passed:

- focused backend regression slice: `127 passed`

Scale and token-reduction validation passed:

- synthetic user corpus benchmark with `60` files passed
- retrieval benchmark with `500` sources passed

## Current Token Reduction Interpretation

The old token-reduction story depended on expert compression. That is no longer true.

The current RAG system still reduces tokens materially because it:

- selects only relevant evidence
- trims and deduplicates citations
- reuses working memory
- reuses cached cluster profile material
- benefits from warm-cache repeat-query behavior

Current benchmark evidence:

- average raw tokens: `1858.62`
- average current packet tokens: `1030.38`
- average reduction: `44.43%`
- warm-cache average reduction: `94.8%`

This is the right product story now: retrieval-driven reduction, not model-compression-driven reduction.

## Remaining Non-Migration Work

The migration is complete, but some release work remains:

- clean-machine packaged validation
- broader release hardening and security proof
- continued pruning of LoRA-era wording from secondary docs and release artifacts
- optional local synthesis runtime setup for richer final chat answers

Important distinction:

- missing local synthesis runtime is not a migration bug
- it only means chat falls back to retrieval-draft output instead of local grounded synthesis

## Historical Note

Older long-form notes in this repo may still mention:

- LoRA experts
- expert compression
- adapter graduation
- expert runtime packaging
- expert-only onboarding/setup

Those references are historical unless a document has been explicitly updated after the 2026-07-07 RAG migration completion pass.

When a historical note conflicts with `docs/PROJECT_CONTEXT.md`, the project context document is authoritative.
