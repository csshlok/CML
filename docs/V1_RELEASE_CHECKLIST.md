# V1 Release Checklist

Last updated: 2026-06-28

Audit sources:

- `docs/PROJECT_CONTEXT.md`
- `docs/OVERALL_CONTEXT.md`
- `docs/RELEASE_AUDIT.md`

## Blocking Release Gates

| Gate | Status | Current evidence |
| --- | --- | --- |
| Backend regression suite | Passed | 2026-06-28 full backend run passed with `544 passed, 3 skipped` after fixing the LoRA training config, benchmark eligibility accounting, training dataset wording regressions, and optional ML import containment for the adapter smoke path. The final full run did not print the previous pyarrow/pandas/sklearn/Transformers access-violation stack. |
| Desktop production build | Passed | `npm run build` is passing in the current repo state. |
| Retrieval benchmark evidence | Partially passed | Synthetic 100/1k evidence, 1500-source evidence, and capped user-owned real-vault evidence now exist; broader natural-corpus confidence is still useful release proof. |
| Context-layer release proof | Partially passed | Broader hostile/context-layer benchmark runs exist with packet-savings telemetry and hostile degradation evidence; broader real-vault recall/expansion usefulness proof is still open. |
| Real LoRA trainer smoke | Passed for current dev CPU smoke | 2026-06-15 real one-step LLaMA Factory run used `Qwen/Qwen2.5-0.5B-Instruct`, actual project docs, dataset hash `d0f85a6bf90dd9f0ef0489aef3ebf2e705fd896a91ad5a7f357196ba40c1c4b0`, and produced a real adapter. |
| Real LoRA runtime smoke | Passed for current dev CPU smoke | Direct Transformers/PEFT adapter runtime evidence returned `ok=true` on CPU from `.tmp/lora-real-qwen05b-runtime-evidence.json`. |
| Live expert bundle benchmark | Open | Early live benchmark evidence still fails public proof. Release requires a retrieval-grounded expert-compression bundle benchmark that preserves quality while reducing tokens and passes the bundle safety gates. |
| Clean Windows VM validation | Open | Local package validation and smokes pass for `apps/desktop/release/test-0.1.6-Setup.exe`; the active blocker is a healthy clean-VM validation run of that current package. |
| Installed package first-run parity | Partially passed | Local installed-app startup smoke and clean installer lifecycle smoke pass for the current installer; a healthy clean-VM installed-app pass is still missing. |
| Hardware-aware model/setup validation | Open | Role-aware acceptance and recommendation code exists, but clean-machine QA with one imported approved checkpoint is still required. |
| Bridge privacy/trusted-client wording | Partially documented | Project docs now describe the trusted-client boundary more honestly, but release wording still needs to stay conservative. |
| Cloud-synced vault path safety | Open | Public-V1 storage-integrity warnings/blocking for synced vault locations remain an open release item. |

## Current Notes

- The package is no longer blocked on the older missing-runtime/missing-resource layout failure.
- Local installed-app parity now passes on the contributor machine; the remaining package gate is current clean-VM validation plus installed-app parity in that clean environment.
- The main open release gates are now:
- clean-VM package validation
- full live expert-compression bundle quality proof
- hardware-aware model/setup QA
- final public-proof breadth for larger real-vault/context-layer claims

## Release Decision

Status: not release-cleared.

The repo is substantially further along than the older phase-4/phase-5 state:

- backend/chat/Bridge validation is broader
- retrieval evidence is broader
- extension/browser evidence is broader
- turbovec Phase C runtime wiring exists

But public V1 still should not be treated as release-cleared until:

- a healthy clean Windows VM pass exists for the current packaged installer and installed app
- real expert-compression bundle quality proof exists beyond the current trainer/runtime smoke
- hardware-aware model/setup validation is completed on release-like machines
