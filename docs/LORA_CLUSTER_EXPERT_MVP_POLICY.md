# LoRA Cluster Expert MVP Policy

Last updated: 2026-06-04

This document defines the minimum bar for the compulsory cluster expert MVP. Retrieval can answer immediately, but the UI and release notes must not call a cluster "trained" until all gates below pass for that cluster.

## Graduation Gates

- Dataset gates: source count, unique-source count, estimated token count, validation-record count, and duplicate-content ratio must pass the backend LoRA contract.
- Trainer gate: training must run through a configured LLaMA-Factory-compatible command with `shell=False`, explicit argv/env paths, captured stdout/stderr, and a non-zero failure mapped to `trainer_failed`.
- Adapter gate: the output directory must contain a valid `adapter_config.json` declaring `peft_type=LORA`, a base model reference, and a non-empty `adapter_model.safetensors`.
- Runtime gate: the adapter must have a load plan for the selected local inference runtime, then pass the live runtime smoke before public trained-expert claims.
- Quality gate: adapter-backed evaluation must beat retrieval-only evaluation by at least `CML_LORA_MIN_QUALITY_DELTA` and meet `CML_LORA_MIN_QUALITY_SCORE`.
- Staleness gate: dataset-hash mismatch marks the active adapter stale and returns the cluster to `Needs update` until a new adapter graduates.
- Rollback gate: failed retraining must preserve the previous active adapter; rollback can only activate a valid, non-deleted prior adapter.

## Retrieval-Vs-Adapter Evaluation

The benchmark must compare retrieval-vs-adapter behavior on the same cluster prompts. Retrieval-only output is the baseline; adapter-backed output must exceed that baseline by the configured quality delta.

## Required Evaluation Categories

- `factual_recall`: answers must recover source-specific facts.
- `summarization`: answers must compress local source content without inventing claims.
- `citation_grounding`: answers must cite or name the local source.
- `contradiction_handling`: answers must prefer stored local evidence over conflicting claims.
- `style_transfer`: answers should preserve the practical tone of the cluster notes.
- `out_of_scope_refusal`: answers must state missing evidence instead of guessing.

## Repeatable Smokes

```powershell
.\scripts\backend\smoke-lora-expert.ps1
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath <adapter-dir> -BaseModel <base-model> -RuntimeUrl http://127.0.0.1:8080/v1
```

`smoke-lora-expert.ps1 -AllowTestTrainer` is only for CI scaffold validation. Public V1 requires the same script without `-AllowTestTrainer`, using a real trainer command and real base model.
