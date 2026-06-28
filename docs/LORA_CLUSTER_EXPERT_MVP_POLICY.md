# Behavior-Specialized Hybrid Cluster Expert Policy

Last updated: 2026-06-27

This document defines the minimum bar for public "cluster expert" claims after the architecture shift from standalone LoRA experts to behavior-specialized hybrid cluster experts.

## Core Rule

The bundle is the expert. A LoRA adapter alone is not a cluster expert.

```text
Cluster Expert Bundle =
  retrieval index
  source manifest
  source-trust metadata
  memory profile
  cluster glossary
  LoRA behavior adapter
  quality and freshness metadata
  expansion handles
  token-savings telemetry
```

Retrieval owns facts. Retrieval owns citations. Retrieval owns source identity. LoRA may assist with grounded behavior specialization only after retrieval evidence exists.

## Behavior-Specialization Rule

For a cluster adapter to count as a real expert component, it must produce measurable grounded behavior lift in at least these areas:

- cluster terminology consistency
- answer structure
- reasoning order
- local framing
- practical emphasis
- uncertainty and conflict phrasing

If an adapter only shortens evidence without creating measurable behavior lift over the base model, it is a compression helper, not a qualified expert artifact.

## Graduation Gates

- Dataset gate: source count, unique-source count, estimated token count, validation-record count, and duplicate-content ratio must pass the backend contract.
- Diversity gate: source and normalized-content hash diversity must be high enough for a meaningful benchmark.
- Trainer gate: training must run through a configured LLaMA-Factory-compatible command with explicit argv/env paths, captured stdout/stderr, and mapped failure codes.
- Adapter gate: the output directory must contain a valid LoRA adapter with `adapter_config.json` and non-empty `adapter_model.safetensors`.
- Runtime gate: the adapter must have a valid local Transformers/PEFT runtime load plan.
- Objective gate: the artifact must declare the retrieval-grounded compression objective version.
- Bundle gate: product paths must call the adapter only with retrieved evidence, never prompt-only.
- Quality gate: bundle evaluation must preserve answer quality while reducing context tokens.
- Behavior gate: bundle evaluation must show that the correct adapter changes answer behavior in the intended cluster-specific direction more than a wrong-adapter or no-adapter baseline.
- Grounding gate: wrong citation/source-title/entity/date/number insertion rate must be zero in the release-gate sample.
- Staleness gate: dataset or objective mismatch marks the artifact stale.
- Rollback gate: rollback can activate only a valid artifact with the same objective version.

## Evaluation Ownership

- Retrieval-owned: factual recall, citation grounding, source selection, exact quotes, contradiction against source text, out-of-scope refusal.
- Adapter-owned: grounded behavior specialization, including terminology normalization, local style, reasoning-pattern hints, answer structure, and framing.
- Shared: evidence summarization only when the source evidence is supplied in the adapter input.

The adapter must not be benchmarked as a source-memory system. The public benchmark must compare:

```text
retrieval-only full packet
retrieval-only small packet
retrieval + expert compressed packet
```

The success question is:

```text
Does the expert bundle preserve quality while reducing context tokens and add measurable cluster-specific behavior?
```

not:

```text
Does the adapter beat retrieval at facts?
```

## Required Benchmark Metrics

- Citation correctness.
- Source-title correctness.
- Entity/date/number fidelity.
- Unsupported-claim rate.
- Answer completeness.
- Useful compression.
- Cluster terminology/style fit.
- Reasoning usefulness.
- Behavior delta versus base model with the same evidence.
- Wrong-adapter versus right-adapter separation.
- Packet token count.
- Runtime latency.
- Adapter load memory.

Initial public-quality targets:

- Wrong citation/source-title rate: `0` in release-gate sample.
- Unsupported entity/date/number insertion rate: `0` in release-gate sample.
- Token savings versus retrieval-only full packet: at least `40%`.
- Quality regression versus retrieval-only full packet: at most `5%`.
- Quality improvement versus retrieval-only same-token packet: at least `10%`.
- Behavior specialization lift versus retrieval-only/base-model same-evidence packet: positive on every adapter-owned graduation category.
- Minimum meaningful eval sample: at least `10-15` cases per scored category.

## Minimum Data Floor

Small clusters should remain retrieval-only.

Internal benchmark runs are not meaningful unless the post-filter, post-split dataset meets all of these floors:

- at least `400` train records
- at least `80` validation records
- at least `10` validation records per benchmark category
- at least `60` distinct contributing source documents
- at least `60` distinct normalized-content hashes across records actually used

Diversity caps:

- no single source may exceed `10%` of total train records
- no single source may exceed `10%` of total validation records
- no single source may exceed `20%` of validation records inside any one category

If these floors fail, the run is `insufficient_benchmark_diversity`, not a meaningful LoRA quality failure.

## Base Model Reality Check

- `0.5B` bases are smoke-test tools only.
- Current 1.5B prompt-only adapter results are historical and not public release proof.
- `1.5B`, `2B`, and `3B` models should be compared only after the bundle objective and benchmark exist.
- Larger bases should not be used to hide architectural mistakes such as prompt-only factual generation.

## Training Objective Rules

Training records must include retrieved evidence when the target output uses source facts.

Allowed training record types:

- evidence compression
- terminology normalization
- style rewrite grounded in evidence
- reasoning-hint extraction
- conflict summary from supplied snippets
- uncertainty boundary from partial evidence
- glossary extraction from supplied evidence
- answer-shape transfer grounded in evidence
- framing transfer grounded in evidence
- practical-action emphasis grounded in evidence

Disallowed as adapter memory tasks:

- factual recall from title alone
- citation generation from memory
- out-of-scope refusal from memory
- entity-sensitive summarization without evidence

## Runtime Rules

- Product code must not call prompt-only adapter generation for cluster answers.
- Expert runtime failures must degrade to retrieval-only.
- Adapter output must be checked against retrieved evidence before inclusion.
- Expansion handles must point to retrieval/source chunks, not adapter text.
- Final answer citations must come from retrieved evidence.
- Final expert qualification must depend on behavior lift under grounded retrieval, not on adapter-only generations.

## Repeatable Smokes

Current smoke scripts remain useful for infrastructure validation:

```powershell
.\scripts\backend\smoke-lora-expert.ps1
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath <adapter-dir> -BaseModel <base-model>
```

These scripts are not the final public-quality benchmark until they are updated for the retrieval-grounded bundle objective.

## Expected Adapter Layout

LLaMA-Factory-compatible adapter directories must contain:

- `adapter_config.json`
- `adapter_model.safetensors`

The adapter config must declare:

- `peft_type=LORA`
- `base_model_name_or_path`

The base model directory must be a local Transformers model directory, typically containing `config.json` plus tokenizer files.

## Known Limitations

- The bundle architecture is planned but not fully implemented yet.
- Existing prompt-only adapter artifacts are legacy and must not be silently promoted under the new objective.
- Current adapter-vs-retrieval benchmark scripts are historical harnesses until the bundle benchmark replaces them.
- The current implementation still leans too heavily toward compression-only expert usage; behavior-specialization ownership must be made explicit in runtime, routing, and benchmark code before public expert claims are strong.
