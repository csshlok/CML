# LoRA Cluster Expert MVP Policy

Last updated: 2026-06-21

This document defines the minimum bar for the compulsory cluster expert MVP. Retrieval can answer immediately, but the UI and release notes must not call a cluster "trained" until all gates below pass for that cluster.

## Graduation Gates

- Dataset gates: source count, unique-source count, estimated token count, validation-record count, and duplicate-content ratio must pass the backend LoRA contract.
- Trainer gate: training must run through a configured LLaMA-Factory-compatible command with `shell=False`, explicit argv/env paths, captured stdout/stderr, and a non-zero failure mapped to `trainer_failed`.
- Adapter gate: the output directory must contain a valid `adapter_config.json` declaring `peft_type=LORA`, a base model reference, and a non-empty `adapter_model.safetensors`.
- Runtime gate: the adapter must have a load plan for the selected local inference runtime, then pass the live runtime smoke before public trained-expert claims.
- Quality gate: adapter-backed evaluation must meet `CML_LORA_MIN_QUALITY_SCORE` and beat retrieval-only evaluation by at least `CML_LORA_MIN_QUALITY_DELTA` only on the adapter-owned and shared benchmark categories. Retrieval-owned factual/citation categories remain diagnostic and must not be used as the primary LoRA graduation test.
- Staleness gate: dataset-hash mismatch marks the active adapter stale and returns the cluster to `Needs update` until a new adapter graduates.
- Rollback gate: failed retraining must preserve the previous active adapter; rollback can only activate a valid, non-deleted prior adapter.

## Retrieval-Vs-Adapter Evaluation

The benchmark must compare retrieval-vs-adapter behavior on the same cluster prompts, but only for the parts of the answer contract that LoRA can plausibly improve.

- Retrieval owns facts, direct evidence selection, contradiction resolution against source text, and citations.
- The adapter owns cluster-specific style, terminology consistency, reasoning-pattern reuse, and higher-level synthesis behavior.
- Shared categories such as summarization and out-of-scope refusal still matter, but the graduation pass/fail rule must not depend on the adapter outperforming retrieval on raw factual recall or citation-grounding.
- Retrieval-only output remains the diagnostic baseline; adapter-backed output must exceed that baseline on adapter-owned and shared categories only.

## Required Evaluation Categories

- Diagnostic retrieval-owned categories:
  - `factual_recall`: answers must recover source-specific facts.
  - `citation_grounding`: answers must cite or name the local source.
  - `contradiction_handling`: answers must prefer stored local evidence over conflicting claims.
- Graduation categories:
  - `summarization`: answers must compress local source content without inventing claims.
  - `style_transfer`: answers should preserve the practical tone of the cluster notes.
  - `terminology_consistency`: answers should reuse cluster-specific vocabulary instead of flattening it.
  - `reasoning_pattern`: answers should apply the cluster's recurring reasoning structure.
  - `out_of_scope_refusal`: answers must state missing evidence instead of guessing.

## Minimum Data Floor

- Small clusters should remain retrieval-only.
- LoRA training attempts should start only once the cluster passes the higher backend data floor for source count, unique-source count, token count, and validation count.
- Synthetic multiplication of records from a tiny number of source documents does not count as real cluster diversity.

## Benchmark Eligibility Gate

- Internal LoRA benchmark runs are not meaningful unless the post-filter, post-split dataset meets all of these floors:
  - at least `400` train records
  - at least `80` validation records
  - at least `10` validation records per benchmark category
  - at least `60` distinct contributing source documents
  - at least `60` distinct normalized-content hashes across the records actually used
- Diversity caps also apply to the final record set:
  - no single source may exceed `10%` of total train records
  - no single source may exceed `10%` of total validation records
  - no single source may exceed `20%` of validation records inside any one category
- If the training gate passes but this benchmark gate fails, the run must be treated as `insufficient_benchmark_diversity`, not as a meaningful LoRA quality failure.

## Base Model Reality Check

- `0.5B` bases are useful only for trainer/runtime smoke and scaffolding checks.
- Real benchmark evidence should be gathered on at least `1.5B`, `2B`, and `3B` expert-capable base models.
- If adapter-owned categories still fail on those larger bases, treat that as an architecture warning rather than a tuning-only problem.

## Repeatable Smokes

```powershell
.\scripts\backend\smoke-lora-expert.ps1
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath <adapter-dir> -BaseModel <base-model>
```

`smoke-lora-expert.ps1 -AllowTestTrainer` is only for CI scaffold validation. Public V1 requires the same script without `-AllowTestTrainer`, using a real trainer command and real base model.

## Expected Adapter Layout

LLaMA-Factory-compatible adapter directories must contain:

- `adapter_config.json`
- `adapter_model.safetensors`

The adapter config must declare:

- `peft_type=LORA`
- `base_model_name_or_path`

The runtime smoke resolves the base model from:

- a direct filesystem path passed as `-BaseModel`
- `CML_LORA_MODEL_DIRS`
- `CML_MODELS_DIR`
- `CML_DATA_DIR\models`

The base model directory must be a local Transformers model directory, typically containing `config.json` plus tokenizer files.

## Runtime Notes

- The current live adapter smoke targets a local Transformers + PEFT runtime, which matches LLaMA-Factory adapter exports directly.
- The previous `llama.cpp`-style load-plan placeholder was not sufficient for real PEFT adapter validation. A PEFT adapter directory is not treated as a ready-to-attach `llama.cpp` LoRA artifact.
- Use `CML_LORA_RUNTIME_PYTHON` when the backend interpreter does not have `torch`, `transformers`, and `peft` importable.

## Known Limitations

- Public V1 still needs a machine-level proof run with a real local base model installed, not only scaffolded tests.
- Runtime smoke currently assumes a local Transformers-compatible base model directory, not a GGUF-only runtime.
- Retrieval-owned benchmark categories are diagnostic only and should not be mistaken for the LoRA graduation target.
