# LoRA Findings And Replication Runbook

Last updated: 2026-07-01

This document records the current LoRA findings that should guide future work. It intentionally replaces older append-only run notes that treated prompt-only adapter quality as the release target.

## Current Conclusion

LoRA remains useful for CML, but not as a standalone factual memory expert.

The shippable target is:

```text
retrieval-grounded cluster expert bundle
```

not:

```text
prompt-only LoRA cluster expert
```

Retrieval must own facts and citations. LoRA may compress retrieved evidence into cluster-specific terminology, style, and reasoning hints.

## Why The Old Target Changed

Real adapter runs found product-dangerous failure modes:

- wrong source titles
- wrong names or places substituted into plausible answers
- citation-like text generated from memory
- repetitive/template collapse
- prompt-word echo rewarded by early scorers
- valid paraphrase sometimes penalized versus retrieval's verbatim source echo

The important lesson is that raw sample inspection matters more than aggregate scores. Several clean-looking scores were later traced to benchmark or scorer bugs.

## Bugs And Measurement Issues Found

Fixed or partially fixed:

- Proxy quality formula measured training completion and dataset shape, not output quality.
- Retrieval baseline was synthetic in some paths instead of live/exact-source retrieval.
- Token caps were too low and clipped generated answers.
- Route-away categories were inconsistently enforced.
- `MANIFEST.json` could enter benchmark source selection.
- Scorers rewarded scaffold words like "first/then/therefore."
- Some marker scorers rewarded prompt-word echo.
- Entity/source grounding needed to compare against full source text.
- Repetition controls needed to reach runtime worker generation.
- Eval loss was configured but not actually logged in earlier training.
- Best-checkpoint selection was missing in older runs.

Still relevant:

- Current adapter-vs-retrieval scores are historical, not public release proof.
- Future benchmarks must evaluate bundle quality and token savings.
- Prompt-only adapter artifacts are legacy until retrained under the bundle objective.

## Current Trusted Training Infrastructure Facts

- Local Transformers/PEFT runtime can load valid LoRA adapters when the external runtime environment is healthy.
- CUDA training can run when configured with the correct venv and model path.
- Step-based eval loss and `load_best_model_at_end` work in the current trainer path.
- Early stopping/best checkpoint is required because useful training windows can be under one epoch.
- Dataset hash and objective version must be treated as promotion inputs.

## Known Environment Issues And Fixes

Hugging Face token:

```powershell
$env:HF_TOKEN = "<token>"
```

If using the CLI:

```powershell
T:\hf-cli-venv\Scripts\hf.exe auth login
```

Common issue:

```text
No module named huggingface_hub.cli.__main__
```

Fix: call the installed `hf.exe` command directly instead of `python -m huggingface_hub.cli`.

DNS/CDN issue:

```text
cdn-lfs.huggingface.co could not be resolved
```

Fixes tried:

- flush DNS
- switch network/DNS
- retry after network change
- verify `huggingface.co` and `cdn-lfs.huggingface.co` separately

Gated Gemma access:

```text
Access denied. This repository requires approval.
```

Fix: accept the model license/access request from the same Hugging Face account used by the token.

Windows memory issue:

```text
The paging file is too small for this operation to complete. (os error 1455)
```

Fixes:

- set Windows paging file to system managed or larger fixed size
- kill stray Python processes before rerun
- force GPU runtime settings when appropriate
- avoid concurrent adapter loads

Missing adapter path:

```text
adapter_invalid: LoRA adapter directory does not exist
```

Fix: find the real adapter under the active workdir before benchmarking. If deleted, retrain.

## Current External Runtime Environment

Typical environment variables used during current local runs:

```powershell
$env:CML_LORA_TRAINER_COMMAND = "<lora-venv>\Scripts\llamafactory-cli.exe train {config_path}"
$env:CML_LORA_RUNTIME_PYTHON = "<lora-venv>\Scripts\python.exe"
$env:CML_LORA_TRAINING_DEVICE = "cuda"
$env:CML_LORA_TRAINING_DTYPE = "fp16"
$env:CML_LORA_RUNTIME_DEVICE = "cuda"
$env:CML_LORA_RUNTIME_DTYPE = "float16"
$env:CML_LORA_RUNTIME_QUANTIZATION = "4bit"
$env:CML_LORA_RUNTIME_REPETITION_PENALTY = "1.1"
$env:CML_LORA_RUNTIME_NO_REPEAT_NGRAM_SIZE = "4"
```

Use the active repo checkout:

```powershell
Set-Location <your CML checkout>
```

## Historical Benchmark Artifacts

Keep these only as historical debugging references:

- `.tmp/lora-sample-new-vault-full205-rerun-harness-fixed.json`
- `.tmp/lora-sample-new-vault-full205-first-adapter-rerun-sample-outputs.md`
- `.tmp/lora-sample-new-vault-full205-first-adapter-rerun-summary.json`

Do not use old prompt-only adapter scores as release proof.

## What Not To Run Next

Do not spend GPU time on another 2B/3B prompt-only adapter run before the new bundle objective exists.

Do not run the old adapter-vs-retrieval benchmark and treat a pass/fail as product truth.

Do not train on synthetic source-title prompts that ask the adapter to answer from memory.

## What To Build Next

Follow `docs/CLUSTER_BUNDLE_EXPERT_IMPLEMENTATION_PLAN.md`.

Immediate sequence:

1. Add `backend/app/core/cluster_bundle.py`.
2. Route Bridge through the bundle builder in retrieval-only mode.
3. Route chat through the bundle builder in retrieval-only mode.
4. Add schema fields for expert digest, retrieval authority, token ledger, and bundle status.
5. Add `run_cluster_expert_compression`.
6. Validate expert digest against retrieved evidence.
7. Redesign the training exporter around evidence-packet-to-digest records.
8. Replace adapter-vs-retrieval benchmark with bundle benchmark.

## Future Bundle Benchmark Shape

Compare:

- retrieval-only full packet
- retrieval-only small packet
- retrieval plus expert compressed packet
- bundle path with expert disabled

Measure:

- answer quality
- citation correctness
- source-title correctness
- entity/date/number fidelity
- unsupported-claim rate
- token count
- latency
- runtime memory
- expansion handle correctness

Initial success target:

- at least `40%` token savings versus retrieval-only full packet
- at most `5%` quality regression versus retrieval-only full packet
- at least `10%` improvement versus retrieval-only same-token packet
- zero wrong citations/source titles/entities in release-gate sample

## Legacy Commands

These commands remain useful for infrastructure smoke only.

Runtime smoke:

```powershell
Set-Location <your CML checkout>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-runtime.ps1 `
  -AdapterPath <adapter-dir> `
  -BaseModel <base-model-dir>
```

Trainer/runtime smoke:

```powershell
Set-Location <your CML checkout>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-expert.ps1 `
  -BaseModelPath <base-model-dir> `
  -SourcePaths docs backend scripts `
  -MaxRealSources 50 `
  -BenchmarkCaseLimit 8 `
  -BenchmarkMaxNewTokens 0 `
  -AllowBenchmarkFailure `
  -WorkDir <lora-smoke-workdir>
```

Monitor training:

```powershell
Set-Location <your CML checkout>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\monitor-lora-training.ps1 `
  -WorkDir <workdir> `
  -RefreshSeconds 5
```

## Bug Prevention Rules

- Product paths must not call the adapter with prompt-only cluster questions.
- Every adapter training target that uses facts must include retrieved evidence in the input.
- Retrieval remains the only citation authority.
- Unsupported source/entity/date/number insertions must fail closed.
- Raw sample outputs must be saved for every benchmark run.
- Scorers must not reward prompt-word echo or empty scaffolds.
- Scorers must not penalize valid paraphrase simply because retrieval echoes source text.
- Dataset hash and objective version must match before promotion.
- Metadata files such as `MANIFEST.json` must never become training or benchmark sources.
