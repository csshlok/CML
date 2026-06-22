# LoRA Findings And Replication Runbook

Last updated: 2026-06-22

## Purpose

This document records the current trustworthy LoRA findings for CML, the code and process changes made to get there, the reasons for those changes, the exact problems encountered during setup and benchmarking, and a reproducible path for running the same work on another Windows machine.

Use this document as the long-form LoRA source of truth. Keep `docs/PROJECT_CONTEXT.md` compact and point back here for operational detail.

## Executive Summary

The current trustworthy result is the clean `1.5B` live rescore in `.tmp/rescore-1p5b-live-clean.json`.

- Adapter artifact: `.tmp/lora-smoke-1p5b-gpu5x/experts/cluster-smoke/adapter-b5641070-7f65-4103-9f73-dd9852489c6b`
- Base model: `T:\hf-models\Qwen2.5-1.5B-Instruct`
- Dataset alignment: `dataset_matches_adapter_training=true`
- Overall benchmark: retrieval `85.89`, adapter `79.74`, delta `-6.15`
- Graduation-only benchmark: retrieval `80.75`, adapter `76.45`, delta `-4.3`

Current trustworthy category pattern:

- Adapter wins: `terminology_consistency` `+6.87`, `contradiction_handling` `+5.67`
- Near-flat: `style_transfer` `-0.3`
- Adapter loses: `reasoning_pattern` `-9.58`, `summarization` `-11.69`, `out_of_scope_refusal` `-6.83`
- Large retrieval-owned loss: `citation_grounding` `-22.31`

Current conclusion:

- LoRA is not currently good enough to graduate as a cluster expert at `1.5B`.
- The result does support a narrower truth: LoRA can help local terminology consistency and some contradiction framing, but retrieval remains stronger for facts and citations.

## What Was Wrong Before

Two separate issues made earlier LoRA conclusions unreliable.

### 1. Proxy quality gate

The old activation path used `evaluate_adapter_quality(...)` in `backend/app/core/training_evaluation.py`.

That proxy score was based on:

- dataset score
- whether an adapter directory existed
- whether validation records existed

It did not score real adapter outputs.

That meant:

- a completed adapter could look "good" for the wrong reasons
- a failed quality comparison could be caused by the proxy formula, not by actual model behavior
- earlier activation-time adapter scores should be treated as unverified

### 2. Dataset mismatch during standalone benchmarking

The standalone benchmark originally rebuilt an evaluation dataset from a current docs crawl and compared its hash to the adapter's original training dataset hash.

That caused false `dataset_mismatch` states even when the benchmark was close enough to be useful diagnostically.

We fixed this by reconstructing the evaluation plan from the adapter's own exported validation set.

## What We Changed In Code

### Activation path

Files changed:

- `backend/app/core/background_jobs.py`
- `backend/app/core/expert_evaluation.py`

What changed:

- removed proxy-based activation decision from the expert activation path
- added `run_live_expert_benchmark(...)`
- made activation use live adapter inference plus scored benchmark outputs
- made activation optionally use the adapter's exported validation set as the benchmark source

Why:

- activation must be driven by actual model outputs
- the same scoring path should be used for activation and standalone verification

### Benchmark ownership-aware gate

Files changed:

- `backend/app/core/config.py`
- `backend/app/core/expert_evaluation.py`

What changed:

- added ownership-aware thresholds:
  - `lora_adapter_owned_min_quality_delta`
  - `lora_shared_max_quality_regression`
  - `lora_retrieval_owned_max_quality_regression`
- added ownership groups:
  - adapter-owned: `style_transfer`, `terminology_consistency`, `reasoning_pattern`
  - shared: `summarization`, `out_of_scope_refusal`
  - retrieval-owned: `factual_recall`, `citation_grounding`, `contradiction_handling`
- added `gate_report` to benchmark output

Why:

- the product design already says retrieval owns facts and citations
- a flat average hides the meaningful per-category split
- the gate should match the intended system design, not punish LoRA for not beating retrieval everywhere

### Benchmark dataset alignment

Files changed:

- `backend/app/core/expert_evaluation.py`
- `scripts/backend/benchmark-lora-adapter.ps1`

What changed:

- added `build_adapter_training_evaluation_plan(...)`
- rebuilt evaluation cases from the adapter's own `dataset/validation.jsonl`
- fixed benchmark wrapper path handling for absolute Windows paths
- fixed benchmark report dataset hash so it reflects the actual adapter-backed evaluation plan

Why:

- a clean benchmark must evaluate the same task surface the adapter was actually trained against
- false dataset-mismatch flags waste time and weaken trust in the result

### Earlier supporting fixes

Files changed earlier in the same line of work:

- `backend/app/core/training_dataset.py`
- `backend/app/core/lora_training.py`
- `backend/app/core/config.py`
- `backend/tests/test_additional_qa_cases.py`

What changed:

- fixed duplicate-content ratio accounting to work at source/hash level instead of raw record level
- added epoch configurability through config
- added stricter dataset and benchmark eligibility gates
- added regression coverage for benchmark dataset export, gate behavior, and live benchmark execution

Why:

- the earlier exporter/gate combination could mark healthy multi-category exports as over-duplicated
- the training and benchmark process needed a meaningful R&D floor before quality conclusions were useful

## Trustworthy Findings So Far

### CPU 0.5B era

Trust level: trainer/runtime proof only, not product-quality proof.

What we learned:

- real bounded CPU LoRA training can produce valid adapters
- runtime loading through Transformers/PEFT works
- these runs did not prove useful quality

Historical result direction:

- old factual/citation-heavy runs were very poor versus retrieval
- those numbers are now treated cautiously because some came from the proxy-era path

### GPU 1.5B clean result

Trust level: trustworthy.

What we learned:

- the adapter is real
- the runtime path is real
- the benchmark is now hash-aligned to the adapter training dataset
- `1.5B` is still not enough to pass the current ownership-aware gate

Most important interpretation:

- the adapter does not currently justify expert promotion
- the result is not "LoRA is useless"
- the result is "this `1.5B` setup helps in some local-language tasks but still loses too much elsewhere"

## Reproducible Windows Setup

The process below is the recommended replication path on another Windows machine.

### 1. Clone the repo and open a shell at repo root

All commands below assume the shell is started at the repository root.

If you run requirements commands from another directory, PowerShell will fail to find files like:

`requirements\contributors-lora-trainer.txt`

### 2. Create the backend virtual environment

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements\contributors-backend.txt
```

### 3. Create the LoRA trainer/runtime virtual environment

Example:

```powershell
python -m venv T:\cml-lora-venv
T:\cml-lora-venv\Scripts\python.exe -m pip install --upgrade pip
T:\cml-lora-venv\Scripts\python.exe -m pip install -r requirements\contributors-lora-trainer.txt
```

Notes:

- run the requirements command from the repo root
- this environment is used for trainer/runtime dependencies, not for the normal backend

### 4. Install CUDA PyTorch in the LoRA environment

The successful runtime/training path used CUDA-enabled PyTorch in `T:\cml-lora-venv`.

```powershell
T:\cml-lora-venv\Scripts\python.exe -m pip uninstall -y torch torchvision torchaudio
T:\cml-lora-venv\Scripts\python.exe -m pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Verify:

```powershell
T:\cml-lora-venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no-cuda')"
```

Expected shape:

- CUDA available should be `True`
- device should be the NVIDIA GPU

## Hugging Face Token And Model Download

### Recommended token setup

Temporary current-shell setup:

```powershell
$env:HF_TOKEN="hf_your_token_here"
```

Persistent setup for later shells:

```powershell
setx HF_TOKEN "hf_your_token_here"
```

Then open a new shell.

### CLI notes

We hit multiple Hugging Face CLI problems:

- `hf.exe` not found
- wrong module entrypoint for `huggingface_hub`
- network/DNS resolution failures

The simplest reproducible method is Python `snapshot_download(...)` from the LoRA venv instead of depending on whatever `hf.exe` happens to exist.

### Recommended download method

Create a model root:

```powershell
New-Item -ItemType Directory -Force -Path T:\hf-models | Out-Null
```

Download models with Python:

```powershell
@'
from huggingface_hub import snapshot_download

models = [
    ("Qwen/Qwen2.5-1.5B-Instruct", r"T:\hf-models\Qwen2.5-1.5B-Instruct"),
    ("google/gemma-2-2b-it", r"T:\hf-models\gemma-2-2b-it"),
    ("Qwen/Qwen2.5-3B-Instruct", r"T:\hf-models\Qwen2.5-3B-Instruct"),
]

for repo_id, local_dir in models:
    snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        token=True,
    )
'@ | T:\cml-lora-venv\Scripts\python.exe -
```

Notes:

- `gemma-2-2b-it` is gated; approval is required on Hugging Face before download will work
- the successful local base-model directories used in this project were:
  - `T:\hf-models\Qwen2.5-1.5B-Instruct`
  - `T:\hf-models\gemma-2-2b-it`
  - `T:\hf-models\Qwen2.5-3B-Instruct`

## Download Errors We Hit And Fixes

### `hf.exe` not recognized

Error shape:

```text
T:\cml-lora-venv\Scripts\hf.exe : The term ... is not recognized
```

Cause:

- the CLI script was not installed in that environment

Fix:

- do not rely on `hf.exe`
- use Python `snapshot_download(...)` from the environment that has `huggingface_hub` installed

### `No module named huggingface_hub.cli.__main__`

Cause:

- wrong module entrypoint

Fix:

- use `snapshot_download(...)` directly
- or use the correct CLI binary if present, but the Python path is more reliable

### DNS or CDN resolution failures

Observed symptom:

- `Invoke-WebRequest https://cdn-lfs.huggingface.co` failed with remote-name resolution errors

What did not reliably fix it:

- `ipconfig /flushdns` alone

What to do:

1. verify basic host resolution:

```powershell
nslookup huggingface.co
nslookup cdn-lfs.huggingface.co
```

2. verify HTTP access:

```powershell
Invoke-WebRequest https://huggingface.co -UseBasicParsing
Invoke-WebRequest https://cdn-lfs.huggingface.co -UseBasicParsing
```

3. if `cdn-lfs.huggingface.co` still cannot resolve:

- switch network
- try a mobile hotspot
- disable any broken VPN or filtering layer
- retry after network change

The real issue in that phase was network/DNS reachability, not the token itself.

### `Access denied. This repository requires approval.`

Cause:

- gated Hugging Face repo, especially Gemma

Fix:

- request/accept model access on Hugging Face first
- then rerun download with a valid token

## Runtime And Benchmark Environment Variables

These were the successful runtime settings used for GPU LoRA work:

```powershell
$env:CML_LORA_RUNTIME_PYTHON="T:\cml-lora-venv\Scripts\python.exe"
$env:CML_LORA_RUNTIME_DEVICE="cuda"
$env:CML_LORA_RUNTIME_DTYPE="float16"
```

Important:

- training used `fp16` naming successfully in some paths
- the runtime worker only accepts `auto`, `float16`, `bfloat16`, or `float32`
- using `fp16` in the runtime benchmark caused a real failure: `Unsupported runtime dtype: fp16`

## Training / Smoke Commands Used

### Real LoRA smoke with a base model

Example shape:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-expert.ps1 `
  -BaseModelPath T:\hf-models\Qwen2.5-1.5B-Instruct `
  -SourcePaths docs `
  -MaxRealSources 80 `
  -BenchmarkCaseLimit 80 `
  -RuntimeMaxNewTokens 32 `
  -BenchmarkMaxNewTokens 64 `
  -AllowBenchmarkFailure `
  -WorkDir .tmp\lora-smoke-1p5b-gpu5x
```

Important environment variables used for the GPU `1.5B` run:

```powershell
$env:CML_LORA_TRAINER_COMMAND="T:\cml-lora-venv\Scripts\llamafactory-cli.exe train {config_path}"
$env:CML_LORA_TRAINING_DEVICE="cuda"
$env:CML_LORA_TRAINING_DTYPE="fp16"
$env:CML_LORA_TRAINING_CUTOFF_LEN="512"
$env:CML_LORA_TRAINING_NUM_TRAIN_EPOCHS="5"
```

### Standalone live benchmark against an existing adapter

This is the clean rerun path for an already-trained adapter:

```powershell
$env:CML_LORA_RUNTIME_PYTHON="T:\cml-lora-venv\Scripts\python.exe"
$env:CML_LORA_RUNTIME_DEVICE="cuda"
$env:CML_LORA_RUNTIME_DTYPE="float16"

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-lora-adapter.ps1 `
  -AdapterPath .tmp\lora-smoke-1p5b-gpu5x\experts\cluster-smoke\adapter-b5641070-7f65-4103-9f73-dd9852489c6b `
  -BaseModel T:\hf-models\Qwen2.5-1.5B-Instruct `
  -SourcePaths docs `
  -MaxRealSources 80 `
  -BenchmarkCaseLimit 80 `
  -BenchmarkMaxNewTokens 64 `
  -ReportPath .tmp\rescore-1p5b-live-clean.json
```

## Problems Encountered During LoRA Work

### Permission error when a smoke workdir/path was wrong

Observed:

- `PermissionError: [Errno 13] Permission denied: '...\\backend'`

Meaning:

- the work/report path had collapsed onto a directory path instead of a file path

Fix:

- rerun with an explicit `.tmp\...json` report path and `.tmp\...` work directory

### Dataset mismatch in benchmark report

Meaning:

- the benchmark was not evaluating the adapter against the exact training-derived evaluation set

Fix made in code:

- reconstruct the evaluation plan from the adapter's exported `dataset/validation.jsonl`
- use the adapter plan dataset hash in the report

### Broken benchmark wrapper with absolute Windows paths

Cause:

- `benchmark-lora-adapter.ps1` was joining already-absolute paths to the repo root before calling `GetFullPath(...)`

Fix:

- detect rooted paths first
- only join repo-relative paths to the repo root

## How To Reproduce The Current Trustworthy 1.5B Result

1. Prepare the backend `.venv`
2. Prepare `T:\cml-lora-venv`
3. Install CUDA PyTorch in `T:\cml-lora-venv`
4. Download:
   - `Qwen/Qwen2.5-1.5B-Instruct`
5. Set:
   - `CML_LORA_TRAINER_COMMAND`
   - `CML_LORA_TRAINING_DEVICE=cuda`
   - `CML_LORA_TRAINING_DTYPE=fp16`
   - `CML_LORA_TRAINING_CUTOFF_LEN=512`
   - `CML_LORA_TRAINING_NUM_TRAIN_EPOCHS=5`
6. Run `scripts/backend/smoke-lora-expert.ps1` for the `1.5B` model
7. Note the produced adapter path under `.tmp/.../experts/cluster-smoke/...`
8. Set:
   - `CML_LORA_RUNTIME_PYTHON=T:\cml-lora-venv\Scripts\python.exe`
   - `CML_LORA_RUNTIME_DEVICE=cuda`
   - `CML_LORA_RUNTIME_DTYPE=float16`
9. Run `scripts/backend/benchmark-lora-adapter.ps1` against that adapter
10. Read:
   - `dataset_matches_adapter_training`
   - `overall`
   - `graduation_overall`
   - `gate_report`
   - `category_scores`

## What To Do Next

Current next step:

- run the same corrected process for `2B` and `3B`

Recommended interpretation rule before doing that:

- if `2B` and `3B` still lose badly on `citation_grounding`, treat that as architectural rather than tuning-related
- if a larger base improves `style_transfer`, `terminology_consistency`, and `reasoning_pattern` enough to clear the adapter-owned gate without catastrophic retrieval-owned regressions, then LoRA may still be viable for a narrower expert role

## Related Files

- `docs/PROJECT_CONTEXT.md`
- `docs/OVERALL_CONTEXT.md`
- `backend/app/core/background_jobs.py`
- `backend/app/core/expert_evaluation.py`
- `backend/app/core/training_dataset.py`
- `backend/app/core/lora_training.py`
- `scripts/backend/smoke-lora-expert.ps1`
- `scripts/backend/benchmark-lora-adapter.ps1`
- `scripts/backend/run-lora-size-matrix.ps1`
