# V1 Release Checklist

Date: 2026-06-10

Audit source: `docs/RELEASE_AUDIT.md`

## Blocking Release Gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Backend regression suite | Passed | `.venv\Scripts\python.exe -m pytest -q backend/tests` completed with `260 passed, 3 skipped`. |
| Desktop production build | Passed | `npm run build` passed after rerunning outside the filesystem sandbox. |
| Retrieval benchmark evidence | Partially passed | 100-source and 1k synthetic benchmark reports were generated under `.tmp\phase5-retrieval-100` and `.tmp\phase5-retrieval-1k`; larger user-owned/natural-corpus benchmark evidence is still required. |
| Real LoRA trainer smoke | Open | `docs/EXPERT_VALIDATION_REPORT.md` records that real smoke fails without `CML_LORA_TRAINER_COMMAND`. No real trainer run was available. |
| Real LoRA runtime smoke | Open | No verified adapter path and accepted local Transformers base model were available. |
| Live expert quality benchmark | Open | No live adapter-backed quality comparison was available. |
| Clean Windows VM validation | Open | `docs/WINDOWS_VM_VALIDATION.md` records missing packaged runtime resources and no clean-VM pass. |
| Packaged runtime completeness | Open | Current `apps\desktop\release\win-unpacked` lacks `resources\backend`, packaged Python runtimes, Playwright runtime, OCR manifest, and helper manifest. |
| Hardware-aware model/setup validation | Open | Existing implementation has role-aware model acceptance paths, but clean-machine validation with one imported approved checkpoint was not completed in this pass. |
| Bridge privacy/trusted-client wording | Partially documented | `docs/PROJECT_CONTEXT.md` records the trusted-client exfiltration boundary. `docs/THREAT_MODEL.md` is still minimal and should be expanded before public sign-off. |
| Cloud-synced vault path safety | Open | `docs/PROJECT_CONTEXT.md` marks robust warning/blocking for synced vault locations as a public V1 storage-integrity gap. |

## Validation Commands Run

```powershell
npm run build
```

Result: passed after sandbox approval.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\validate-clean-machine-package.ps1 -PackageRoot apps\desktop\release\win-unpacked -ReportPath .tmp\phase4-clean-machine-package-validation.json
```

Result: failed because required packaged resources are missing.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-retrieval.ps1 -Sources 100
```

Result: blocked by missing Python launcher target.
Phase 5 rerun: passed for 100-source and 1k-source synthetic benchmarks; see `docs/RETRIEVAL_BENCHMARKS.md`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\smoke-lora-expert.ps1 -ReportPath .tmp\phase4-lora-expert-real-report.json
```

Result: failed because `CML_LORA_TRAINER_COMMAND` is required for real LoRA smoke.

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

Result: `260 passed, 3 skipped`.

## Release Decision

Public V1 is not release-cleared.

Backend and synthetic retrieval validation have advanced since Phase 4, but the audit's substantive blockers remain open where this workspace lacks the required package resources, clean VM, real LoRA trainer command, accepted local expert base model, and live adapter benchmark evidence.
