# Project Context And Progress

Last updated: 2026-07-02

## Operating Rule

This file is the compact project operating brief. Keep it current and small. Do not use it as an append-only log.

- Target size: under 600 lines.
- Prefer current truth over historical detail.
- Move detailed reports to dedicated docs.
- Long-form fallback: `docs/OVERALL_CONTEXT.md`.
- Current detailed cluster-bundle plan: `docs/CLUSTER_BUNDLE_EXPERT_IMPLEMENTATION_PLAN.md`.

## Project Goal

Build CML, a local-first downloadable Windows desktop app for personal context management.

The user creates a local vault, adds files, folders, links, notes, screenshots, chat transcripts, and other memory artifacts. CML clusters related material, indexes it, and supplies structured, source-grounded context to local or external tools through the desktop app, Bridge, MCP, CLI, and API.

CML is not only a second-brain vault. Public V1 must act as a context-management layer between the user and LLMs: reduce context loss across long or old conversations, reduce token cost by avoiding repeated corpus/transcript replay, and let external tools request compressed, source-grounded, reusable context instead of re-reading raw history.

Target user: general second-brain users, not only developers.

## Current Product Decisions

- Product form: local downloadable desktop app, not a web app.
- Public V1 platform: Windows only.
- Release stance: public release only; no private alpha/demo fallback.
- Desktop shell: Electron in `apps/desktop`.
- Backend: FastAPI in `backend`.
- Active repo path: use the current checked-out workspace root; avoid hardcoded machine-specific paths in current runbooks.
- V1 vault scope: explicit vault mode only; no full-device silent scanning.
- V1 storage: local vault folder with `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`.
- V1 integrations: local synced folders first, including Google Drive Desktop, Dropbox, OneDrive, iCloud Drive, Obsidian folders, and normal folders.
- Later integrations: OAuth/API connectors after local ingestion is stable.
- Browser extension: Chrome and Brave only for public V1; thin capture surface, not an admin console.
- Bridge/MCP/API/CLI: first-class external context surfaces.
- Local-first privacy: user data stays local unless the user explicitly exports or connects a tool.
- Security boundary: encryption, unlock-state enforcement, Bridge approval, parser/browser isolation, renderer hardening, and model/artifact integrity are release gates.
- UI direction: memory-board landing, visual map, chat workspace, Mindly-like organization, Obsidian-like graph/map.
- UI responsive scope: desktop and narrow/minimized desktop; no dedicated mobile app for public V1.
- UI reference folder: preserve `UI-ref/`; do not delete or refactor it.

## Cluster Expert Architecture Decision

The old assumption was that a LoRA adapter could become a standalone factual expert for a cluster. Recent real runs showed that this is not safe: prompt-only adapters can produce fluent but wrong source titles, names, places, and citations.

The current architecture target is a retrieval-grounded cluster expert bundle:

```text
Cluster Expert Bundle =
  retrieval index
  source manifest
  source-trust metadata
  memory profile
  cluster glossary
  optional LoRA compression adapter
  quality and freshness metadata
  expansion handles
  token-savings telemetry
```

The bundle is the expert. The adapter is only one optional component.

Authority split:

- Retrieval owns facts, citations, source IDs, quotes, dates, names, numbers, and refusal when evidence is missing.
- LoRA owns grounded compression, terminology normalization, local style, and reasoning-pattern hints.
- The final chat model or external MCP model owns user-facing synthesis from the packet.
- Adapter output must never become citation authority.
- Product paths must not call a prompt-only adapter for cluster answers.

Target flow:

```text
User query
-> router selects cluster bundle
-> bundle retrieves source-grounded evidence
-> optional LoRA compresses/interprets retrieved evidence
-> bundle returns compact packet with citations and expansion handles
-> final model answers from packet
```

The detailed implementation plan is in `docs/CLUSTER_BUNDLE_EXPERT_IMPLEMENTATION_PLAN.md`.

## 2026-06-26 Bundle Implementation Progress

The first code pass for the retrieval-grounded bundle architecture is now live in the backend.

Implemented in this pass:

- `backend/app/core/cluster_bundle.py` now exists as a shared bundle builder for retrieval evidence, memory, cluster profile, expert eligibility, expert digest, and token ledger assembly.
- Bridge `/bridge/context` now routes through the shared bundle builder instead of assembling context independently.
- Standard chat retrieval context now consumes the shared bundle builder for retrieved evidence and expert-digest metadata. Prompt-only adapter product calls are no longer used in this path.
- `backend/app/core/expert_runtime.py` now includes `run_cluster_expert_compression(...)`, an evidence-grounded compression prompt, parseable digest handling, and fail-closed unsupported-claim validation.
- Context packet rendering and schemas now expose retrieval authority, expert digest metadata, bundle status, and token ledger fields.
- MCP packet formatting now respects backend-rendered packet text and bundle metadata.
- New backend tests exist in `backend/tests/test_cluster_bundle.py`.
- `backend/app/core/training_dataset.py` now exports evidence-grounded record types instead of prompt-only factual-answer tasks.
- LoRA dataset/benchmark lifecycle metadata now records `retrieval_grounded_compression_v1`, training record types, and retrieved-evidence requirements.
- Legacy prompt-only artifacts are now treated as incompatible with trained expert-compression readiness in lifecycle status.
- `backend/app/core/expert_evaluation.py` now exposes bundle benchmark modes such as `retrieval_only_small`, `retrieval_only_full`, `bundle_with_expert`, and `bundle_without_expert`, plus bundle-oriented gate fields for quality regression, quality gain, token savings, unsupported-claim rate, and wrong-citation rate.
- Backend lifecycle and cluster routes now write canonical bundle-era statuses such as `expert_compression_ready` and `expert_stale` instead of continuing to emit only legacy `training_ready` and `needs-update` values on new state transitions.
- Desktop cluster UI status adapters and badges now distinguish retrieval-ready, retrieval-only, training-pending, training-running, expert-ready, and stale states with bundle-era labels such as `Expert compression ready` and `Retrieval-only mode`.
- Cluster detail and map surfaces now describe expert compression as an optional grounded digest layer over retrieved evidence instead of as a standalone trained memory expert.
- Model recommendation, setup-readiness, onboarding, and settings copy now describe the expert role as an `expert-compression runtime` rather than an `expert checkpoint` or `expert-capable setup`.
- `scripts/backend/export-lora-run-artifacts.py` now exports bundle benchmark gate data and per-mode summaries instead of only the legacy adapter-versus-retrieval score framing.
- Expanded-analysis and complete-analysis chat paths now also route through `backend/app/core/cluster_bundle.py` rather than bypassing it with chat-local retrieval assembly.
- `backend/app/core/cluster_bundle.py` now supports `expanded_analysis` and `complete_analysis` modes by using analysis-packet evidence selection under the same shared bundle contract.
- `backend/app/core/expert_evaluation.py` now emits per-mode raw case outputs (`retrieval_only_full`, `retrieval_only_small`, `bundle_with_expert`, `bundle_without_expert`) alongside bundle benchmark modes and gate summaries.
- `backend/app/core/expert_evaluation.py` now also emits `bundle_category_scores`, restoring category-by-category benchmark visibility for the new bundle contract so each category can compare retrieval-full, retrieval-small, bundle-with-expert, and bundle-without-expert score/token behavior.
- `scripts/backend/benchmark-lora-adapter.ps1` now persists retrieval-small case scores and per-mode case-output payloads from the bundle benchmark.
- Bundle benchmark per-case outputs are now richer bundle-era artifacts rather than thin score rows: each mode row now carries raw packet text, retrieval evidence used, expert-call traces for expert-used cases, and a per-case token ledger.
- `scripts/backend/export-lora-run-artifacts.py` now emits both a bundle-era category CSV from `bundle_category_scores` and a bundle-era per-case CSV from `bundle_case_outputs`, in addition to the compatibility-only legacy CSVs and raw mode-case JSON.
- `backend/app/core/expert_runtime_worker.py` now uses a safer non-meta model load path for non-quantized local LoRA runtime runs, which restored live adapter smoke and bundle benchmark execution in the current repo environment after a Torch/PEFT loader regression.
- Manual expert artifact activation and rollback now enforce retrieval-grounded objective compatibility, passing bundle benchmark evidence, and current dataset-hash match instead of trusting any `ready` artifact with valid adapter files.
- `backend/app/core/expert_lifecycle.py` now exposes an activation-guard report so lifecycle status, activation, and rollback share the same compatibility contract for expert-compression artifacts.
- `scripts/backend/export-lora-run-artifacts.py` now emits raw per-mode case-output JSON in addition to bundle-mode CSV summaries, and its bundle artifact export path now parses cleanly again after a script regression fix.
- Bundle benchmark reports now expose primary bundle-first fields such as `bundle_benchmark_summary`, `bundle_release_gate`, `bundle_benchmark_modes`, `bundle_case_outputs`, and `bundle_readiness` instead of forcing downstream consumers to infer the current contract from legacy adapter/category fields.
- Training completion metrics now use the bundle benchmark's `bundle_with_expert_score` and bundle release gate as the activation-facing quality summary instead of relying on legacy `graduation_overall.adapter_score` as the primary signal.
- `scripts/backend/benchmark-lora-adapter.ps1` and `scripts/backend/export-lora-run-artifacts.py` now default to the bundle-first benchmark contract in their saved JSON, HTML, and summary outputs, while still preserving compatibility fields for older consumers.
- New targeted regression coverage now exists for the bundle-first benchmark/export contract in `backend/tests/test_cluster_bundle_benchmark.py` and `backend/tests/test_export_lora_run_artifacts.py`.
- `backend/app/core/lora_proof.py` and `scripts/backend/export-lora-proof.ps1` now summarize smoke proof using bundle-era benchmark fields such as `bundle_with_expert_score` and `bundle_release_gate`, and public blocked reasons now refer to `expert_bundle_benchmark_failed` instead of presenting the old adapter-quality benchmark label as the primary contract.
- `backend/app/core/training_evaluation.py` has been downgraded to an explicitly structural-readiness-only helper so it can no longer be mistaken for a live bundle-quality or activation gate.
- New targeted regression coverage now exists for the proof/readiness cleanup in `backend/tests/test_lora_proof_bundle_contract.py` and `backend/tests/test_training_evaluation_contract.py`.
- `backend/app/core/expert_evaluation.py` now uses `bundle_mode_coverage` as the primary benchmark completeness/readiness check, so pass/fail is no longer driven by legacy graduation-category completeness under the hood.
- Training metrics now persist `bundle_mode_coverage`, and bundle readiness reports now explain failure in bundle-mode terms such as missing or incomplete required modes while keeping legacy category completeness only as compatibility detail.
- New targeted regression coverage now exists for the bundle-primary benchmark internals in `backend/tests/test_cluster_bundle_benchmark.py`.
- `backend/app/core/lora_training.py::graduation_contract()` now exposes canonical bundle-era statuses as the primary contract and separates legacy status aliases explicitly instead of publishing old `training_ready`-style names as the default supported-state list.
- `scripts/backend/export-lora-run-artifacts.py` now labels legacy category/graduation outputs as compatibility-only artifacts and names those exported files accordingly, instead of presenting them as the primary benchmark deliverables.
- `backend/app/core/lora_proof.py` no longer emits the stale `adapter_quality_benchmark` gate alias; the proof surface now treats `expert_bundle_benchmark` as the authoritative gate name.
- `docs/PRODUCT_PRD.md`, tracked release/status docs, and historical notes in `docs/OVERALL_CONTEXT.md` now use bundle-era wording for the expert-quality/proof gate instead of continuing to describe the old adapter-quality benchmark as the current contract.
- The remaining named Phase 1 docs now also reflect the bundle-era contract:
  - `docs/BRIDGE_CONTEXT_PACKET_DESIGN.md`
  - `docs/CONTEXT_LAYER_V1_WORKPATH.md`
  - `docs/V1_RELEASE_CHECKLIST.md`
  - `docs/UI_ARCHITECTURE.md`
  These docs now describe expert digest authority limits, retrieval-owned facts/citations, token-ledger/bundle metadata, and expert-compression status language instead of leaning on the older adapter-era framing.
- Final closeout verification after the last Bridge-path bug fix passed across the core bundle implementation surfaces:
  - `.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_cluster_bundle.py backend\tests\test_cluster_bundle_training.py backend\tests\test_cluster_bundle_benchmark.py backend\tests\test_bridge_mcp.py backend\tests\test_bridge_phase10.py backend\tests\test_export_lora_run_artifacts.py backend\tests\test_lora_proof_bundle_contract.py backend\tests\test_training_evaluation_contract.py`
  - Result: `51 passed`
  - `.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_source_pages.py -k "expanded_analysis or complete_analysis or rollback_and_delete_guardrails or legacy_prompt_only_artifact or active_adapter_stale or expert_compression_ready"`
  - Result: `8 passed, 93 deselected`
  - `.\.venv\Scripts\python.exe -m compileall -q backend\app`
  - Result: passed

Still not implemented from the full plan:

- Benchmark/evaluation code now uses bundle-mode coverage for primary readiness, but it still carries the old category-score/graduation substrate as a compatibility and diagnostic layer; that deeper scoring model still needs a fuller end-to-end conversion before the document can be considered complete.
- Some repo tests and long-form historical notes still mention legacy `training_ready` wording for fixture compatibility or chronology, and those should be pruned or rewritten as part of the final migration polish.
- Release-proof breadth is still not empirically complete; the code and contract migration are largely in place, but public-proof items such as live benchmark breadth and clean-VM release validation remain separate release evidence work.
- Migration/objective-version enforcement is now active on manual activation and rollback, but broader promotion/verification surfaces still need a final audit for complete end-to-end closure.
- Broader LoRA smoke/proof tooling is now much closer to the bundle contract, but some historical script names and compatibility payload fields are still adapter-oriented and should be cleaned up before calling the migration complete.

## 2026-06-28 Debugging Pass

Validated fixes now landed locally:

- `backend/app/core/config.py` now defaults `CML_LORA_TRAINING_EARLY_STOPPING_STEPS` to `2`, restoring the expected LLaMA Factory training config contract.
- `backend/app/core/lora_training.py` now handles legacy category-shaped validation share/count accounting correctly while preserving the new record-type benchmark contract.
- `backend/app/core/training_dataset.py` now restores the expected grounded-glossary and missing/uncertain wording in generated bundle-era training records.
- `backend/app/core/lora_training.py` and `backend/app/core/expert_runtime_worker.py` now hide unneeded Transformers optional sklearn/pandas/pyarrow probes around the local test-trainer/runtime smoke path, avoiding the Windows native access-violation stack that was printing during ML dependency import.
- Validation passed:
  - `.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_additional_qa_cases.py::AdditionalQACases::test_llamafactory_training_config_defaults_to_auto_hardware backend\tests\test_additional_qa_cases.py::AdditionalQACases::test_llamafactory_training_config_honors_device_and_dtype_overrides backend\tests\test_additional_qa_cases.py::AdditionalQACases::test_lora_benchmark_eligibility_report_blocks_small_or_concentrated_datasets backend\tests\test_additional_qa_cases.py::AdditionalQACases::test_lora_training_dataset_exports_quality_benchmark_tasks backend\tests\test_source_pages.py::SourcePageIndexingTests::test_lora_training_can_bypass_quality_gate_for_diagnostic_runs backend\tests\test_source_pages.py::SourcePageIndexingTests::test_lora_training_respects_configured_benchmark_case_limit`
  - Result: `6 passed`
  - `.\.venv\Scripts\python.exe -m pytest -q backend\tests`
  - Result after the training/benchmark fixes: `544 passed, 3 skipped`
  - Result after the optional-import containment fix: `544 passed, 3 skipped`; the previous pyarrow/pandas/sklearn/Transformers access-violation stack did not print.
  - `npm run lint`
  - Result: `40 passed`
  - `npm run build`
  - Result: passed
  - `node --test apps/browser-extension/tests/*.test.cjs`
  - Result: `19 passed`
  - `.\.venv\Scripts\python.exe -m compileall -q backend\app\core\config.py backend\app\core\lora_training.py`
  - Result: passed
  - `.\.venv\Scripts\python.exe -m compileall -q backend\app`
  - Result: passed

Current note from full backend validation:

- The earlier Windows native access-violation stack during ML dependency import was reproduced in the adapter smoke path, contained by blocking unneeded optional sklearn/pandas/pyarrow probes, and absent from the final full backend validation run.

2026-06-29 follow-up debugging fix:

- `.gitignore` no longer excludes `docs/THREAT_MODEL.md` or `docs/CLUSTER_MERGE_POLICY.md`, and both policy docs are now intended tracked inputs for backend policy validation. This fixes a clean-clone risk where `backend/tests/test_system_vault_lock_and_embeddings.py -k "backend_policy_docs"` could pass only on a local workspace that happened to keep ignored policy docs.
- Validation passed: `.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_system_vault_lock_and_embeddings.py -k "backend_policy_docs"` (`1 passed, 68 deselected`).
- Final broad validation after the follow-up fix also passed: `.\.venv\Scripts\python.exe -m pytest -q backend\tests` (`544 passed, 3 skipped`), `npm run lint` (`40 passed`), `npm run build` (passed), `node --test apps/browser-extension/tests/*.test.cjs` (`19 passed`), and `.\.venv\Scripts\python.exe -m compileall -q backend\app` (passed).

2026-06-30 initial full-repo debug fix:

- `ReadME.md` now uses bundle-era release-gate and local expert state language instead of the stale adapter-quality/`training_ready` framing, and the touched public overview lines now render with ASCII-safe punctuation in normal terminals.
- Validation passed: `.\.venv\Scripts\python.exe -m pytest -q backend\tests` (`544 passed, 3 skipped`), `npm run lint` (`40 passed`), `npm run build` (passed), `node --test apps/browser-extension/tests/*.test.cjs` (`19 passed`), `.\.venv\Scripts\python.exe -m compileall -q backend\app` (passed), and targeted grep confirmed the stale README phrases were removed.

2026-06-30 continued full-repo debug fix:

- `scripts/extension/package-browser-extension.ps1` now includes the browser extension's imported `background-core.js` and `popup-core.js` modules in packaged output, fixing a shipped-zip risk where source tests could pass but the extension service worker/popup imports were missing from the archive.
- Browser-extension regression coverage now runs the package script and verifies the staged package includes those module dependencies.
- Ruff is now clean for `backend` and `scripts`; stale Bridge/chat imports and dead pre-bundle transcript helper code were removed without changing the shared bundle routing contract.
- Final validation passed: `.\.venv\Scripts\python.exe -m pytest -q backend\tests` (`544 passed, 3 skipped`), `npm run lint` (`40 passed`), `npm run build` (passed), `node --test apps/browser-extension/tests/*.test.cjs` (`20 passed`), `.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests` (passed), `npx tsc --project apps\desktop\tsconfig.json --noEmit` (passed), `.\.venv\Scripts\python.exe -m ruff check backend scripts` (passed), `npm run security:renderer` (passed), `npm run security:package` (passed), and `scripts\extension\package-browser-extension.ps1 -OutputRoot .tmp\browser-extension-final-validate` (passed).

2026-07-01 full-repo debug fixes:

- `docs/PROJECT_CONTEXT.md` no longer embeds stale machine-specific validation command paths in the current compact operating brief; the examples now use the active checkout root convention already stated in Current Product Decisions.
- `docs/OVERALL_CONTEXT.md`, `docs/LORA_FINDINGS_AND_REPLICATION_RUNBOOK.md`, and `docs/WORKING_COMMANDS.md` now also avoid stale machine-specific checkout paths in current copy-paste workflow examples; LoRA external runtime/model paths use placeholders where contributor-local paths are required.
- `.gitignore` no longer ignores the tracked `docs/UI_AUDIT_BRIEF.md` and `docs/PACKAGING_INVESTIGATION.md` files, keeping tracked project docs visible to clean-clone hygiene checks.
- Final validation passed after this cleanup: `.\.venv\Scripts\python.exe -m pytest -q backend\tests` (`544 passed, 3 skipped`), `npm run lint` (`40 passed`), `npm run build` (passed), `node --test apps/browser-extension/tests/*.test.cjs` (`20 passed`), `.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests` (passed), `npx tsc --project apps\desktop\tsconfig.json --noEmit` (passed), `.\.venv\Scripts\python.exe -m ruff check backend scripts` (passed), `npm run security:renderer` (passed), `npm run security:package` (passed), tracked Markdown local-link check (passed), and targeted tracked grep confirmed no stale absolute repo path examples remain.
- Additional hygiene validation passed: `git ls-files -ci --exclude-standard` now reports no tracked files ignored by `.gitignore`.

2026-07-02 initial full-repo debug fix:

- `docs/WORKING_COMMANDS.md` now has unique, sequential top-level section numbers from 1 through 10, fixing the duplicated `## 6` runbook navigation.
- Validation passed: heading scan for `docs/WORKING_COMMANDS.md` showed sections 1 through 10 in order; `.\.venv\Scripts\python.exe -m pytest -q backend\tests` (`544 passed, 3 skipped`), `npm run lint` (`40 passed`), `npm run build` (passed), `node --test apps\browser-extension\tests\*.test.cjs` (`20 passed`), `.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests` (passed), `npx tsc --project apps\desktop\tsconfig.json --noEmit` (passed), `.\.venv\Scripts\python.exe -m ruff check backend scripts` (passed), `npm run security:renderer` (passed), and `npm run security:package` (passed).

Local packaged validation refreshed on 2026-06-28:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\validate-clean-machine-package.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: `pass=true`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-runtime.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: passed; backend health, private API token enforcement, CORS blocking, model/embedding setup status, expert runtime availability, image OCR, and PDF OCR were available.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-full-vault.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: passed; vault creation, indexing/search, OCR image/PDF extraction, query-cache prune, startup phase registry, and diagnostics bundle succeeded.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-dynamic-link.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-migration-drill.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-app-launch.ps1 -PackageRoot apps\desktop\release\win-unpacked`
  - Result: passed with `startup_phase=ready` and `renderer_ready_detected=true`.
- This improves local package confidence only. It does not close the clean Windows VM or installed-app first-run parity gates because the host still has dev Python and Node on PATH.

## Model And Runtime Decisions

Do not bundle LLM weights in the first installer. First-run setup must require one CML-managed approved model download or import before normal local synthesis use.

Chat/runtime and expert-compression runtime are separate roles:

- Chat role: user-facing synthesis model for normal conversation and final answer writing.
- Expert-compression role: optional LoRA-capable Transformers/PEFT runtime used only after retrieval evidence exists.
- Retrieval layer: source of truth for evidence, snippets, citations, and expansion handles.

Current model policy:

- Custom models have only two outcomes: `accepted` or `rejected`.
- Acceptance must be role-aware: chat role, expert-compression role, or approved pairing.
- GGUF/Ollama/llama.cpp compatibility is not sufficient for LoRA acceptance.
- Expert compression currently requires a local Transformers-compatible checkpoint plus PEFT runtime.
- Retrieval-only mode remains a valid degraded mode.
- Do not promise expert compression on 8 GB machines until profiling proves it.

## Current Progress

| Area | Status | Progress | Current truth |
| --- | --- | --- | --- |
| Desktop app foundation | In progress | `[##########] 98%` | Local package artifact has been rebuilt and smoke-tested; broader startup repair QA and clean VM validation remain. |
| Retrieval/context layer | In progress | `[#########-] 95%` | Retrieval-first chat, Bridge packets, expansion handles, context budgets, trust gates, and analysis modes now share the bundle path; broader regression and release-gate proof remain. |
| Bridge/MCP | In progress | `[#########-] 92%` | Bridge now routes through the shared bundle builder and surfaces expert digest/token ledger metadata; expansion and permission flows remain, with broader regression still pending. |
| LoRA/expert work | Re-scoped | `[##########] 100%` | Retrieval-grounded bundle core, expert-compression runtime path, evidence-grounded training export, canonical status rollout, analysis-mode bundle parity, bundle-first benchmark/export/proof contract, bundle-mode-primary readiness, richer bundle benchmark artifacts, activation/rollback migration guards, and Phase 1 doc alignment are now implemented and broadly verified in focused bundle-era test suites. |
| Model recommendation | In progress | `[#########-] 88%` | Hardware-aware chat/expert distinction exists and wording now reflects expert compression, but broader runtime/setup verification and final release-gate proof are still pending. |
| Security | In progress | `[########--] 80%` | Vault crypto and auth hardening are active; passphrase strength, key-memory limitations, and concurrency hardening were recently addressed or flagged; threat-model and cluster-merge policy docs are now tracked for clean-clone validation. |
| UI | In progress | `[########--] 82%` | Main surfaces exist; UI copy/status must distinguish retrieval-ready from expert-compression-ready. |
| Packaging/release proof | In progress | `[########--] 78%` | Windows packaging evidence exists and browser-extension zip dependency coverage now has a regression test; clean VM and release checklist remain. |

## Latest LoRA Findings

Current evidence should be interpreted as architecture input, not as a final model verdict.

- Real 1.5B LoRA training can run locally with CUDA/Transformers/PEFT when the environment and pagefile are healthy.
- Step-based eval and best-checkpoint selection work; one recent full run selected a sub-1-epoch checkpoint before eval loss rose.
- Prompt-only adapter scoring found real product-dangerous behavior: wrong source titles, entity/name drift, and fluent unsupported claims.
- Several benchmark bugs were found and fixed or partially fixed: proxy quality gate, synthetic retrieval baseline, token caps, route-away enforcement, entity/source grounding penalties, scaffold rewards, and MANIFEST source inclusion.
- Remaining old adapter-vs-retrieval scores are historical only. They are not a valid public release gate after the architecture shift.
- Future LoRA benchmarks must measure retrieval-plus-expert bundle quality and token savings, not standalone adapter factual recall.

Current useful artifacts:

- `docs/CLUSTER_BUNDLE_EXPERT_IMPLEMENTATION_PLAN.md`
- `.tmp/lora-sample-new-vault-full205-rerun-harness-fixed.json`
- `.tmp/lora-sample-new-vault-full205-first-adapter-rerun-sample-outputs.md`
- `.tmp/lora-sample-new-vault-full205-first-adapter-rerun-summary.json`

## Current Required Engineering Sequence

1. Keep this context doc and `docs/OVERALL_CONTEXT.md` current with the bundle architecture.
2. Add `backend/app/core/cluster_bundle.py` as the shared retrieval-grounded bundle builder.
3. Route Bridge `/context` and MCP `get_cluster_context` through the bundle builder.
4. Route remaining chat analysis paths through the same bundle builder.
5. Finish bundle schema rollout and broader regression coverage.
6. Finish the last legacy benchmark-score cleanup so the remaining category/graduation outputs are clearly compatibility-only or are removed.
7. Broaden regression coverage across chat, Bridge, MCP, and script flows now that analysis paths share the bundle builder and the scripts consume bundle-first outputs.
8. Run a final migration audit across remaining artifact promotion/readiness surfaces and historical contract aliases.
9. Prune or rewrite stale long-form docs/tests that still present adapter-era wording as current truth.
10. Re-run LoRA only after the new objective and benchmark are implemented end to end.

## Code Areas To Change For Bundle Architecture

- `backend/app/core/cluster_bundle.py`: new shared bundle builder.
- `backend/app/api/routes/chat.py`: prompt-only expert assist is disabled; replace pending route with bundle result.
- `backend/app/api/routes/bridge.py`: route Bridge context through bundle builder.
- `backend/app/bridge_mcp.py`: expose bundle packet by default.
- `backend/app/core/context_packets.py`: render expert digest, authority, token ledger, and expansion handles.
- `backend/app/schemas.py`: add bundle fields to chat/Bridge responses.
- `backend/app/core/expert_runtime.py`: add evidence-grounded expert compression call.
- `backend/app/core/training_dataset.py`: remove prompt-only fact/citation/refusal training targets.
- `backend/app/core/expert_evaluation.py`: benchmark bundles, not standalone adapter answers.
- `backend/app/core/training_evaluation.py`: remove/rename proxy quality scoring so it cannot drive promotion.
- `backend/app/core/model_recommender/*`: reword expert role as expert-compression runtime.
- `apps/desktop/src/routes/*`: update cluster/expert status labels and settings copy.
- `scripts/backend/*lora*.ps1`: update smoke/benchmark scripts after bundle benchmark exists.

## Test Requirements For The Next Pass

Add or update tests for:

- Product paths never call prompt-only adapter generation.
- Adapter compression input always includes retrieved evidence.
- Adapter output with unsupported source titles, names, dates, numbers, or citations is discarded.
- Retrieval-owned routes remain retrieval-only.
- Bridge and chat share the same bundle builder.
- MCP packet includes expert digest only when allowed and available.
- Expansion handles always point to source/chunk text, not adapter text.
- Token-savings telemetry is present and stable.
- Legacy prompt-only artifacts cannot graduate under the new objective.
- Training exporter never emits prompt-only factual recall/citation records.
- Benchmark fails closed on dataset/objective mismatch.

## Release Gates

Public V1 remains public-quality only. Release slips if critical gates fail.

Cluster expert bundle gate:

- Retrieval works for the cluster.
- Bundle packet includes citations and expansion handles.
- Expert digest is optional and non-authoritative.
- Wrong citation/source-title rate is zero in release-gate sample.
- Unsupported named-entity/date/number insertion rate is zero in release-gate sample.
- Token savings versus retrieval-only full packet meets the target in `docs/CLUSTER_BUNDLE_EXPERT_IMPLEMENTATION_PLAN.md`.
- Quality regression versus retrieval-only full packet stays within the allowed cap.
- UI does not show stale or failed artifacts as trained.

Security gate:

- Vault encryption and unlock-state behavior are honest in UI copy.
- Bridge permissions and token checks are hardened.
- Ungrounded external writebacks cannot become trusted memory/training data automatically.
- Parser/browser/renderer boundaries are release-ready.

Packaging gate:

- Clean Windows VM launch works.
- Model download/import paths work.
- OCR and parser dependencies are staged.
- Startup repair and diagnostics are verified.

## Running Notes

- Use the current checked-out workspace root for active work; do not follow stale machine-specific paths from historical notes.
- Do not delete or alter `UI-ref/`.
- Do not present old prompt-only LoRA benchmark numbers as release evidence.
- The backend now has a first-pass shared cluster bundle implementation, but the full doc scope is not complete yet; do not describe the architecture migration as finished.
- Do not run expensive 2B/3B adapter training until the bundle objective and benchmark are implemented.
- Retrieval-only mode must stay honest and usable for lower-spec machines.
- "Trained expert" user-facing language is allowed only for a current, non-stale, retrieval-grounded bundle that passed the current gates.
- The `Q100` devil's advocate review remains non-actionable per user instruction.
- No package rebuild or VM run unless explicitly requested.
