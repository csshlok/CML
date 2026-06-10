# Expert Validation Report

Date: 2026-06-10

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The audit treats verified real LoRA expert training and runtime loading as blocking public V1 release. The relevant standard is also defined in `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md`: CI scaffold validation is not enough for public release claims.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| CI scaffold smoke | Passed | `scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer -ReportPath .tmp\phase5-lora-expert-scaffold-report.json` produced one ready scaffold adapter artifact and `training_ready` expert status. This is not public release evidence. |
| Real trainer smoke | Failed as expected | `scripts\backend\smoke-lora-expert.ps1` fails without `CML_LORA_TRAINER_COMMAND`, which is the correct release gate behavior. |
| Real adapter runtime smoke | Not run | No verified real adapter path and accepted local Transformers base-model path were available in this workspace. |
| Live adapter quality benchmark | Not run | The scaffold smoke produced deterministic retrieval-vs-adapter metrics, but no real trained adapter was available, so release-grade quality proof remains missing. |
| Backend expert regression coverage | Passed | Full backend suite: `260 passed, 3 skipped` on 2026-06-10. |

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
CML_LORA_TRAINER_COMMAND is required for real LoRA smoke. Use -AllowTestTrainer only for CI scaffold validation.
```

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

The repeatable scaffold path is now validated, but the real expert blocker remains open. The implementation correctly refuses to treat the CI-only trainer as release evidence.
