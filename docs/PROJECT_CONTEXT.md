# Project Context And Progress

Last updated: 2026-06-26

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
- Active repo path: `T:\CML`.
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
| Retrieval/context layer | In progress | `[#########-] 92%` | Retrieval-first chat, Bridge packets, expansion handles, context budgets, trust gates, and writeback review exist; bundle integration remains. |
| Bridge/MCP | In progress | `[#########-] 90%` | Packet text and expansion handles exist; next pass must add expert digest, token ledger, and bundle status. |
| LoRA/expert work | Re-scoped | `[#######---] 70%` | Training/runtime infrastructure works, but prompt-only adapter expert is not shippable. Next work is retrieval-grounded bundle compression. |
| Model recommendation | In progress | `[########--] 80%` | Hardware-aware chat/expert distinction exists, but copy and setup must reflect expert compression rather than factual expert memory. |
| Security | In progress | `[########--] 80%` | Vault crypto and auth hardening are active; passphrase strength, key-memory limitations, and concurrency hardening were recently addressed or flagged. |
| UI | In progress | `[########--] 82%` | Main surfaces exist; UI copy/status must distinguish retrieval-ready from expert-compression-ready. |
| Packaging/release proof | In progress | `[########--] 78%` | Windows packaging evidence exists; clean VM and release checklist remain. |

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
4. Route chat context through the same bundle builder.
5. Add bundle schemas: expert digest, retrieval authority, token ledger, expansion handles, bundle status.
6. Add `run_cluster_expert_compression`; chat product paths now fail closed instead of calling prompt-only adapters.
7. Redesign the LoRA training exporter around evidence-packet-to-digest records.
8. Replace the benchmark with bundle-quality and token-savings evaluation.
9. Update UI status/copy for retrieval-ready vs expert-compression-ready.
10. Re-run LoRA only after the new objective and benchmark are implemented.

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

- Do not use the old `C:\Users\csshl\Desktop\CML` copy for active work. Active repo is `T:\CML`.
- Do not delete or alter `UI-ref/`.
- Do not present old prompt-only LoRA benchmark numbers as release evidence.
- Do not run expensive 2B/3B adapter training until the bundle objective and benchmark are implemented.
- Retrieval-only mode must stay honest and usable for lower-spec machines.
- "Trained expert" user-facing language is allowed only for a current, non-stale, retrieval-grounded bundle that passed the current gates.
- The `Q100` devil's advocate review remains non-actionable per user instruction.
- No package rebuild or VM run unless explicitly requested.
