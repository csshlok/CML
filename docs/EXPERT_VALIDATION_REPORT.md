# Expert Validation Report

Date: 2026-06-15

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The audit treats verified real LoRA expert training and runtime loading as blocking public V1 release. The relevant standard is also defined in `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md`: CI scaffold validation is not enough for public release claims.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| CI scaffold smoke | Passed | `scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer -ReportPath .tmp\phase5-lora-expert-scaffold-report.json` produced one ready scaffold adapter artifact and `training_ready` expert status. This is not public release evidence. |
| Real trainer smoke | Passed for current dev CPU smoke | 2026-06-15 real run used `CML_LORA_TRAINER_COMMAND='llamafactory-cli train {config_path}'`, `Qwen/Qwen2.5-0.5B-Instruct`, actual project docs, `12` real source sections, dataset hash `d0f85a6bf90dd9f0ef0489aef3ebf2e705fd896a91ad5a7f357196ba40c1c4b0`, and produced a real adapter at `.tmp\lora-real-smoke-work\experts\cluster-smoke\adapter-5baaf88e-a9b5-4926-810e-9e3c53d0c778`. |
| Real adapter runtime smoke | Passed for current dev CPU smoke | Direct Transformers/PEFT runtime evidence at `.tmp\lora-real-qwen05b-runtime-evidence.json` returned `ok=true` and response `The V1 release is a major update`. |
| Live adapter quality benchmark | Failed | The short one-case live benchmark ran against the real adapter and scored adapter `24.0` vs retrieval `100.0`, delta `-76.0`; release-grade quality proof remains missing. |
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
- short live benchmark: failed, adapter `24.0` vs retrieval `100.0`

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

The repeatable scaffold path and one real CPU trainer/runtime path are now validated, but the public expert blocker remains open because the live adapter quality benchmark failed. The implementation must continue refusing public "trained expert" claims until a real adapter-backed benchmark beats retrieval.
