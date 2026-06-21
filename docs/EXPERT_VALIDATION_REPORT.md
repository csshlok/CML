# Expert Validation Report

Date: 2026-06-21

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The audit treats verified real LoRA expert training and runtime loading as blocking public V1 release. The relevant standard is also defined in `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md`: CI scaffold validation is not enough for public release claims.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| CI scaffold smoke | Passed | `scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer -ReportPath .tmp\phase5-lora-expert-scaffold-report.json` produced one ready scaffold adapter artifact and `training_ready` expert status. This is not public release evidence. |
| Real trainer smoke | Passed for current dev CPU smoke | 2026-06-15 real run used `CML_LORA_TRAINER_COMMAND='llamafactory-cli train {config_path}'`, `Qwen/Qwen2.5-0.5B-Instruct`, actual project docs, `12` real source sections, dataset hash `d0f85a6bf90dd9f0ef0489aef3ebf2e705fd896a91ad5a7f357196ba40c1c4b0`, and produced a real adapter at `.tmp\lora-real-smoke-work\experts\cluster-smoke\adapter-5baaf88e-a9b5-4926-810e-9e3c53d0c778`. |
| Real adapter runtime smoke | Passed for current dev CPU smoke | Direct Transformers/PEFT runtime evidence at `.tmp\lora-real-qwen05b-runtime-evidence.json` returned `ok=true` and response `The V1 release is a major update`. |
| Real adapter runtime smoke | Passed on 2026-06-20 | `scripts\backend\smoke-lora-runtime.ps1` wrote `.tmp\lora-runtime-smoke-2026-06-20.json` with runtime `ok=true` for adapter `.tmp\lora-real-smoke-work\experts\cluster-smoke\adapter-e4713cdd-4278-401e-951a-dc7e45f81e7d` and base `.tmp\lora-models\qwen2.5-0.5b-instruct`. |
| CPU/AVX2 hardware proof | Passed on 2026-06-20 | `scripts\backend\export-hardware-proof.ps1` wrote `.tmp\hardware-proof-2026-06-20.json` with `avx2=true`, detection method `windows-kernel32`, 12 CPU threads, and `cpu_minimum_spec`. |
| Live adapter quality benchmark | Failed on 2026-06-20 | `scripts\backend\benchmark-lora-adapter.ps1` wrote `.tmp\lora-adapter-quality-benchmark-2026-06-20.json`; strict six-category benchmark scored retrieval `98.33`, adapter `30.0`, delta `-68.33`, so release-grade quality proof remains missing. |
| Live adapter quality benchmark, longer generation | Failed on 2026-06-20 | `scripts\backend\benchmark-lora-adapter.ps1 ... -BenchmarkMaxNewTokens 96` wrote `.tmp\lora-adapter-quality-benchmark-2026-06-20-retoken.json`; strict six-category benchmark scored retrieval `98.33`, adapter `38.67`, delta `-59.66`, so the failure is not just clipped output. |
| Quality-aligned dataset export | Passed on 2026-06-20 | `write_cluster_training_dataset` now emits records for all strict benchmark categories. The bounded real retrain attempt wrote `.tmp\lora-quality-aligned-real-smoke-work\experts\cluster-smoke\adapter-7474a5fa-6a24-49fe-ad89-2b029eb6ea2d\dataset\dataset-manifest.json` with dataset hash `26b3a8f2f491fed1f7bf0aaa5661c9347d79d56974e8008160a2b81e66c32231`, `57` train records, and `15` validation records. |
| Quality-aligned real retrain | Passed bounded CPU retrain on 2026-06-21 | `.tmp\lora-quality-aligned-cpu512-step1-2026-06-21.json` records a real LLaMA Factory CPU run that produced adapter `.tmp\lora-quality-aligned-cpu512-step1-work\experts\cluster-smoke\adapter-ce315f4e-1a28-497f-a65c-9acc014cd9cc` with `adapter_model.safetensors` size `17,640,136` bytes and training dataset hash `9a0f548aa9396dc8aea73ab2affed01c092828805c4ceb11fd51d1ca937b28a0`. |
| Live adapter quality benchmark, quality-aligned adapter | Failed on 2026-06-21 | `.tmp\lora-quality-aligned-cpu512-step1-dataset-match-benchmark-2026-06-21.json` fails closed with `status=dataset_mismatch` because the current docs-derived benchmark dataset hash differs from the adapter training dataset hash. Its raw strict benchmark still failed at retrieval `98.33`, adapter `61.0`, delta `-37.33`; the embedded same-dataset benchmark in `.tmp\lora-quality-aligned-cpu512-step1-2026-06-21.json` also failed at adapter `49.67`, delta `-48.66`. |
| Public LoRA proof export | Blocked only by quality benchmark | `.tmp\lora-proof-2026-06-20.json` verifies runtime, adapter/base pairing, expert-role compatibility, and AVX2 proof; public gate still fails with `adapter_quality_benchmark_failed`. |
| Backend expert regression coverage | Passed | Focused LoRA/runtime regressions passed on 2026-06-15; see `docs/PROJECT_CONTEXT.md` for the current command list. |

## Command Evidence

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer -ReportPath .tmp\phase4-lora-expert-scaffold-report.json
```

Result:

```text
LoRA expert smoke report written to C:\Users\KIIT0001\Desktop\Project-2\CML\.tmp\phase5-lora-expert-scaffold-report.json
```

Report highlights:

- `processed_jobs_total`: `4`
- `artifact_count`: `1`
- `expert_status.expert_status`: `training_ready`
- `expert_status.trained`: `true`
- `runtime_load.available`: `true`
- `runtime_dependencies`: `torch`, `transformers`, and `peft` importable in `.venv`
- `retrieval_vs_adapter.passes`: `true`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-expert.ps1 -ReportPath .tmp\phase4-lora-expert-real-report.json
```

Result:

```text
Superseded by the 2026-06-15 real smoke: trainer and runtime now pass on the current CPU dev machine, while the live quality gate fails.
```

Current real-smoke highlights:

- `adapter_model.safetensors`: `17,640,136` bytes
- training runtime: `753.997s` for one CPU step
- training loss: `5.6621`
- live runtime: `ok=true`
- 2026-06-20 strict live benchmark: failed, adapter `30.0` vs retrieval `98.33`, delta `-68.33`
- 2026-06-20 AVX2 proof: passed, `avx2=true` through `windows-kernel32`
- 2026-06-21 bounded quality-aligned CPU retrain: passed adapter production and live runtime smoke, but the public quality benchmark remains failed.
- 2026-06-21 standalone benchmark guard: now reports adapter training dataset metadata and fails closed on dataset mismatch instead of silently comparing a current-docs dataset against an adapter trained on an older export.

## Public Claim Rule

CML must not claim that a cluster has a trained expert until all of these are true for that cluster:

- A real trainer command ran without `-AllowTestTrainer`.
- The dataset manifest passed source, token, validation-record, and duplicate-ratio gates.
- The adapter directory contains valid LoRA artifacts.
- Runtime smoke loaded the adapter against an accepted local Transformers base model.
- A live adapter-backed benchmark beats the retrieval baseline by the configured release threshold.
- Rollback, staleness, and artifact integrity checks remain available after activation.

## Release Assessment

Status: not release-cleared.

The repeatable scaffold path, one real CPU trainer/runtime path, adapter/base pairing proof, and CPU AVX2 proof are now validated, but the public expert blocker remains open because the live adapter quality benchmark failed. The implementation must continue refusing public "trained expert" claims until a real adapter-backed benchmark beats retrieval.
