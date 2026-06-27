# Retrieval-Grounded Cluster Bundle Expert Implementation Plan

Last updated: 2026-06-26

## Purpose

This document defines the implementation plan for changing CML's cluster expert architecture from "LoRA adapter as a standalone cluster memory expert" to "retrieval-grounded cluster bundle with optional LoRA compression."

The goal is to preserve the original product value:

- Reduce repeated context replay for large personal clusters.
- Give local and external models compact, reusable, source-grounded cluster context.
- Keep cluster-specific terminology, style, and reasoning patterns available without forcing every downstream model to reread hundreds of raw sources.

The architecture change is necessary because recent LoRA testing showed that a small cluster adapter is not safe as the factual source of truth. It can produce fluent but wrong source titles, names, places, and citations. Retrieval must remain the authority for facts and citations. LoRA can still be useful, but only as a grounded compression and interpretation layer over retrieved evidence.

## Product Contract

The product-facing phrase "cluster expert" remains valid only if it means the full cluster bundle:

```text
Cluster Expert Bundle =
  retrieval index
  source manifest
  source-trust metadata
  memory profile
  cluster glossary
  optional LoRA adapter
  quality and freshness metadata
  expansion handles
  token-savings telemetry
```

The adapter is not the expert by itself. The bundle is the expert.

The source-of-truth contract is:

```text
Retrieval owns facts, citations, source IDs, quotes, dates, names, numbers, and refusal when evidence is missing.
LoRA owns grounded compression, terminology normalization, local style, and reasoning-pattern hints.
The final chat model or external MCP model owns user-facing synthesis from the packet.
```

## Architecture Shift

Old unsafe flow:

```text
User query
-> router selects cluster
-> LoRA adapter receives prompt
-> adapter answers from learned cluster memory
-> final answer may cite retrieval after the fact
```

New target flow:

```text
User query
-> router selects cluster bundle
-> bundle retrieves source-grounded evidence
-> optional LoRA compresses/interprets retrieved evidence
-> bundle returns compact packet with citations and expansion handles
-> final model answers from packet
```

This preserves the token-saving idea without asking the adapter to memorize a 600-700 source cluster.

## Non-Goals

- Do not make LoRA a factual database.
- Do not remove retrieval from expert-mode answers.
- Do not use citation-generation from the adapter as an authority signal.
- Do not train adapters on factual recall, citation grounding, or out-of-scope refusal as memory tasks.
- Do not ship "trained expert" UI copy unless the bundle passes quality, grounding, and freshness gates.

## New Backend Abstraction

Add a new module:

```text
backend/app/core/cluster_bundle.py
```

Primary function:

```python
def build_cluster_bundle_context(
    *,
    vault_id: str,
    query: str,
    cluster_id: str | None = None,
    token_budget: int | None = None,
    allow_expert_compression: bool = True,
    mode: str = "context",
) -> dict:
    ...
```

Expected return shape:

```json
{
  "bundle_id": "cluster:<cluster_id>:<context_request_id>",
  "query": "...",
  "selected_clusters": [],
  "retrieval_authority": true,
  "evidence": [],
  "citations": [],
  "expansion_handles": [],
  "memory_items": [],
  "working_memory": {},
  "cluster_profile": {
    "summary": "",
    "local_terms": [],
    "style_profile": "",
    "reasoning_patterns": []
  },
  "expert_digest": {
    "used": false,
    "mode": "not_eligible",
    "text": "",
    "artifact_id": null,
    "warnings": []
  },
  "token_ledger": {
    "raw_scope_tokens_estimate": 0,
    "retrieved_tokens_estimate": 0,
    "packet_tokens_estimate": 0,
    "expert_digest_tokens_estimate": 0,
    "estimated_tokens_saved_vs_raw_scope": 0,
    "estimated_tokens_saved_vs_retrieval_only": 0
  },
  "warnings": []
}
```

The bundle builder should become the shared entry point for chat, Bridge, MCP, benchmark scripts, and future CLI/API context requests.

## Codebase Change Map

| Area | Current Code | Required Change |
| --- | --- | --- |
| Product context docs | `docs/PROJECT_CONTEXT.md`, `docs/OVERALL_CONTEXT.md` | Replace standalone "LoRA cluster expert" language with "retrieval-grounded cluster expert bundle." |
| LoRA policy | `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md` | Redefine graduation around grounded compression and token savings, not adapter beating retrieval on answers. |
| LoRA runbook | `docs/LORA_FINDINGS_AND_REPLICATION_RUNBOOK.md` | Add latest finding: prompt-only adapter is unsafe as factual memory; new runs must use bundle objective. |
| Chat route | `backend/app/api/routes/chat.py::_build_retrieval_context` | Replace direct expert assist call with cluster bundle result. |
| Expert assist | `backend/app/api/routes/chat.py::_maybe_run_cluster_expert_assist` | Stop sending prompt-only requests to the adapter. Pass retrieved evidence and cluster profile. |
| Expert runtime | `backend/app/core/expert_runtime.py::run_cluster_expert_prompt` | Keep for smoke only. Add `run_cluster_expert_compression`. |
| Context packets | `backend/app/core/context_packets.py` | Add expert digest, retrieval authority, token ledger, and bundle status fields to rendered packets. |
| Bridge API | `backend/app/api/routes/bridge.py::build_context` | Call the bundle builder instead of assembling packet fields independently. |
| MCP formatting | `backend/app/bridge_mcp.py` | Surface bundle packet text by default and keep raw JSON diagnostics explicit. |
| Schemas | `backend/app/schemas.py::BridgeContextResponse`, `ChatCoverageLedger` | Add bundle status, expert digest, expert mode, token ledger, and retrieval-authority fields. |
| Training exporter | `backend/app/core/training_dataset.py` | Replace per-source answer categories with evidence-packet-to-digest training records. |
| Evaluation | `backend/app/core/expert_evaluation.py` | Replace retrieval-vs-adapter answer benchmark with retrieval-only vs retrieval-plus-expert packet benchmark. |
| Legacy proxy scoring | `backend/app/core/training_evaluation.py` | Remove from activation paths or rename to structural readiness. Do not report as quality. |
| Training lifecycle | `backend/app/core/lora_training.py`, `backend/app/core/background_jobs.py` | Keep early stopping, eval loss, dataset hash, rollback, and quality gates; change quality gate input to bundle benchmark. |
| Model recommender | `backend/app/core/model_recommender/*` | Reword expert model as optional expert-compression runtime. Keep separate chat and expert hardware gates. |
| Desktop UI | `apps/desktop/src/routes/*` | Update status copy and progress UI to distinguish retrieval-ready from expert-compression-ready. |
| Scripts | `scripts/backend/*lora*.ps1`, `scripts/backend/export-lora-run-artifacts.py` | Generate bundle benchmark artifacts with raw packets, token ledgers, sample outputs, and per-case expert use. |

## Phase 1: Product And Docs Contract

Update the docs first so future code changes have a stable target.

Required edits:

- `docs/PROJECT_CONTEXT.md`
- `docs/OVERALL_CONTEXT.md`
- `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md`
- `docs/LORA_FINDINGS_AND_REPLICATION_RUNBOOK.md`
- `docs/BRIDGE_CONTEXT_PACKET_DESIGN.md`
- `docs/CONTEXT_LAYER_V1_WORKPATH.md`
- `docs/V1_RELEASE_CHECKLIST.md`
- `docs/PRODUCT_PRD.md`
- `docs/UI_ARCHITECTURE.md`

Specific wording changes:

- Replace "LoRA cluster expert" with "retrieval-grounded cluster expert bundle" where the claim is product-facing.
- Replace "adapter knows the cluster" with "adapter compresses retrieved cluster evidence."
- Replace "expert beats retrieval" with "expert bundle preserves answer quality while reducing context tokens."
- Keep "citations come only from retrieval" explicit.
- Mark standalone adapter factual recall as an invalid goal.

Acceptance checks:

- No public-facing doc should imply the adapter can be trusted as source memory.
- All release gates should describe bundle quality, not adapter memory quality.
- Hardware docs should treat expert compression as a higher-spec optional capability unless public V1 explicitly blocks on it.

## Phase 2: Cluster Bundle Core

Create `backend/app/core/cluster_bundle.py`.

Responsibilities:

- Run semantic retrieval for the selected cluster or vault scope.
- Load memory items and working memory.
- Build a source-grounded evidence packet.
- Decide whether expert compression is eligible.
- Call LoRA only with retrieved evidence.
- Produce token telemetry.
- Return a single bundle result consumed by chat and Bridge.

Suggested helper functions:

```python
def retrieve_bundle_evidence(...) -> dict:
    ...

def build_cluster_profile(...) -> dict:
    ...

def should_use_expert_compression(...) -> dict:
    ...

def build_expert_compression_prompt(...) -> str:
    ...

def estimate_bundle_token_savings(...) -> dict:
    ...
```

Invariants:

- If no retrieval evidence exists, expert compression is not eligible.
- If the query is factual/citation/refusal-sensitive, adapter output may be used only as a non-authoritative digest or disabled entirely.
- If LoRA output mentions a source title, name, number, or date not found in evidence, the digest must be discarded.
- A failed expert call must degrade to retrieval-only without failing the chat request.

Tests to add:

- `backend/tests/test_cluster_bundle.py`
- Test bundle returns retrieval evidence without expert when no adapter exists.
- Test bundle calls expert only when evidence exists.
- Test bundle rejects prompt-only expert calls in product path.
- Test bundle strips or rejects unsupported source/entity claims from expert digest.
- Test bundle reports token savings telemetry.
- Test bundle degrades cleanly when expert runtime fails.

## Phase 3: Chat Integration

Current chat route builds retrieval context in `backend/app/api/routes/chat.py::_build_retrieval_context`.

Change plan:

- Call `build_cluster_bundle_context(...)` after route classification.
- Use `bundle["citations"]` for final answer grounding.
- Use `bundle["expert_digest"]["text"]` as the `expert_assist` field only if `expert_digest.used == true`.
- Store bundle telemetry in `coverage_ledger`.
- Keep existing trust gate and synthesis guard, but make them operate on bundle evidence.

Current unsafe seam:

```python
run_cluster_expert_prompt(conn, cluster_id=payload.cluster_id, prompt=payload.prompt)
```

Target:

```python
run_cluster_expert_compression(
    conn,
    cluster_id=payload.cluster_id,
    prompt=payload.prompt,
    citations=citations,
    cluster_profile=cluster_profile,
)
```

Tests to add or update:

- Chat context includes `expert_route_mode`.
- Chat context includes `expert_digest_tokens_estimate`.
- Chat final answer still cites only retrieval citations.
- Chat does not call expert for no-citation queries.
- Chat does not call expert for route-away categories unless explicitly allowed as digest-only.
- Streaming and non-streaming paths return the same bundle metadata.

## Phase 4: Bridge And MCP Integration

Current Bridge context is assembled in `backend/app/api/routes/bridge.py::build_context`.

Change plan:

- Bridge should call the same bundle builder as chat.
- Bridge response should expose structured bundle metadata.
- MCP `get_cluster_context` should default to the rendered bundle packet.
- Raw JSON should remain diagnostics-only.
- Expansion handles must continue to expand to source/chunk text, not adapter text.

Schema additions:

```python
class BridgeContextResponse(BaseModel):
    ...
    expert_digest: dict = {}
    expert_used: bool = False
    expert_mode: str = "not_eligible"
    retrieval_authority: bool = True
    token_ledger: dict = {}
    bundle_status: dict = {}
```

Packet rendering additions:

```text
Cluster Expert Digest
- Used: yes/no
- Mode: retrieval_grounded_compression
- Digest: ...

Authority
- Facts and citations come from Retrieved Evidence.
- Expert digest is compression only.

Token Savings
- Raw scope estimate
- Retrieved packet estimate
- Expert digest estimate
- Savings estimate
```

Tests to add:

- MCP `get_cluster_context` returns expert digest when allowed and available.
- MCP `get_cluster_context` omits expert digest when client permissions disable expert calls.
- HTTP `/bridge/context` returns token ledger.
- Expansion handles still map to source/chunk text.
- Raw JSON mode still works and is not the default.
- Bridge writeback quality gates still prevent ungrounded outside answers from becoming training data.

## Phase 5: Expert Runtime Refactor

Current expert runtime supports prompt-only generation through `run_cluster_expert_prompt`.

Add:

```python
def run_cluster_expert_compression(
    conn,
    *,
    cluster_id: str,
    prompt: str,
    citations: list[dict],
    cluster_profile: dict | None = None,
    artifact_id: str | None = None,
    max_new_tokens: int | None = None,
) -> dict:
    ...
```

The generated adapter prompt must include:

```text
Task: Compress the retrieved evidence into a cluster-aware context digest.
Authority: Use only the evidence below.
Forbidden: Do not invent citations, source titles, names, dates, quantities, or facts.
Output: Short digest, local terms, reasoning hints, uncertainty notes.
```

Output should be parseable:

```json
{
  "digest": "...",
  "local_terms": [],
  "reasoning_hints": [],
  "uncertainties": [],
  "unsupported_claims": []
}
```

If the model returns plain text, wrap it as `digest` and run the same grounding validation.

Tests to add:

- Runtime builds prompt with evidence.
- Runtime rejects empty evidence.
- Runtime validates unsupported entities and source titles.
- Runtime returns fallback mode on adapter failure.
- Runtime includes artifact ID and load-plan detail.

## Phase 6: Training Dataset Redesign

Current exporter trains one answer per category per source. This must change because it teaches the adapter to answer from memory.

New training record types:

| Record Type | Input | Target |
| --- | --- | --- |
| `source_fact_extract` | Evidence packet | Source-bounded fact extract |
| `evidence_compression` | Query + 2-5 retrieved snippets | Short grounded digest |
| `citation_boundary` | Evidence + source title | Citation boundary grounded in retrieved source |
| `terminology_normalization` | Evidence + generic phrasing | Cluster-preferred phrasing |
| `style_rewrite` | Evidence + neutral answer | Cluster style version without adding facts |
| `reasoning_hint` | Evidence packet | Reasoning pattern supported by evidence |
| `conflict_summary` | Conflicting snippets | Neutral conflict note with source handles |
| `uncertainty_boundary` | Partial evidence | What can and cannot be said |

Do not train:

- Factual recall from title alone.
- Citation generation from memory.
- Refusal from memory.
- Entity-sensitive summarization without evidence.

Required metadata per record:

```json
{
  "record_type": "evidence_compression",
  "source_ids": [],
  "content_hashes": [],
  "evidence_handles": [],
  "input_token_estimate": 0,
  "target_token_estimate": 0,
  "grounding_required": true
}
```

Tests to add:

- Exporter never emits prompt-only factual-recall training records.
- Exporter train/validation split holds out source groups.
- Exporter includes evidence handles in every adapter training input.
- Exporter excludes `MANIFEST.json` and other metadata files from source selection.
- Exporter enforces source diversity and max-share caps.
- Exporter emits manifest with record-type distribution.

## Phase 7: Benchmark Redesign

The old benchmark question was:

```text
Does adapter beat retrieval?
```

The new benchmark question is:

```text
Does retrieval + expert compression preserve quality while reducing tokens?
```

Benchmark modes:

| Mode | Description |
| --- | --- |
| `retrieval_only_small` | Same token budget as expert digest packet, no LoRA. |
| `retrieval_only_full` | Larger retrieval packet baseline. |
| `bundle_with_expert` | Retrieval evidence plus LoRA-compressed digest. |
| `bundle_without_expert` | Same bundle path with expert disabled. |

Score dimensions:

- Citation correctness.
- Entity fidelity.
- Source-title fidelity.
- Unsupported-claim rate.
- Answer completeness.
- Useful compression.
- Local terminology/style fit.
- Reasoning usefulness.
- Token count.
- Runtime latency.
- Adapter load memory.

Graduation gates:

```text
quality_regression_vs_retrieval_full <= allowed cap
quality_gain_vs_retrieval_small >= required gain
token_savings_vs_retrieval_full >= required savings
unsupported_claim_rate == 0 for release gates
wrong_citation_rate == 0 for release gates
dataset_matches_adapter_training == true
```

Suggested initial thresholds:

- At least `40%` token savings versus retrieval-only full packet.
- No more than `5%` quality regression versus retrieval-only full packet.
- At least `10%` quality improvement versus retrieval-only small packet.
- `0` wrong source-title/citation errors in release-gate sample.
- `0` unsupported named-entity/date/number insertions in release-gate sample.
- At least `10-15` cases per scored category before treating the result as meaningful.

Artifacts every run must save:

- Full benchmark JSON.
- Per-case CSV.
- Raw packet text for every mode.
- Adapter prompt and adapter raw output for every expert-used case.
- Retrieval evidence used.
- Token ledger.
- Quality gate report.
- Training dataset hash and benchmark dataset hash.
- Model/runtime/load plan.

Tests to add:

- Benchmark fails closed on dataset mismatch.
- Benchmark includes raw per-case packet text.
- Benchmark counts token savings correctly.
- Benchmark applies grounding validation to both retrieval and expert modes.
- Benchmark cannot pass if expert digest contains unsupported source/entity claims.

## Phase 8: UI Changes

The UI should not imply that LoRA memorizes the cluster.

Cluster status labels:

| Backend State | UI Label |
| --- | --- |
| `retrieval_ready` | Searchable |
| `expert_training_pending` | Preparing expert compression |
| `expert_training_running` | Training cluster compressor |
| `expert_compression_ready` | Expert compression ready |
| `expert_stale` | Expert needs update |
| `hardware_unsupported` | Expert compression unavailable on this device |
| `retrieval_only` | Retrieval-only mode |

Cluster detail page should show:

- Indexed source count.
- Last retrieval index update.
- Expert compression status.
- Last expert training time.
- Dataset hash match/mismatch.
- Token savings from last benchmark.
- Quality status.
- Hardware status.
- Clear fallback message if expert is unavailable.

Chat UI should show:

- "Used retrieval" always when citations exist.
- "Used expert compression" only when bundle expert digest was used.
- "Retrieval-only fallback" when expert was skipped.
- Citations remain visually tied to retrieved sources, not expert digest.

Bridge/MCP Settings should show:

- Allow expert compression toggle.
- Raw snippets permission.
- Style/profile permission.
- Token budget per request.
- Last packet savings.
- Expansion handle availability.

Training monitor should show:

- Epoch/step progress.
- Eval-loss curve.
- Best checkpoint.
- Early stop reason.
- Quality gate stage.
- Token-savings benchmark stage.
- Failure code with next action.

Tests to add:

- UI renders retrieval-only and expert-compression-ready as separate states.
- UI never displays "trained expert" for stale or failed adapters.
- UI shows expert compression as unavailable on unsupported hardware.
- Chat metadata exposes expert-used state.
- Bridge settings toggle controls backend `allow_expert_calls`.

## Phase 9: Model Recommendation And Setup

Current recommendation language treats accepted expert checkpoints as part of completing setup. That should be reframed.

Required changes:

- Separate "chat model readiness" from "expert compression readiness."
- Keep retrieval-only as a valid degraded mode.
- Do not promise expert compression on 8 GB machines until profiled.
- Recommend expert-capable Transformers models only when the device can train and run them safely.
- Make the cost clear: chat runtime and expert runtime may be separate.

Tests to add:

- 8 GB hardware profile does not promise expert compression.
- Setup can clearly show retrieval-only mode.
- Expert recommendation requires compatible local Transformers checkpoint, not GGUF-only runtime.
- Model recommender copy says compression/runtime, not factual memory.

## Phase 10: Migration And Backward Compatibility

Existing adapter artifacts trained under the old prompt-only objective should not be silently promoted into the new bundle architecture.

Migration rules:

- Mark old artifacts as `legacy_prompt_only`.
- Do not use legacy artifacts for product expert compression unless they pass the new bundle benchmark.
- Require retraining under the new dataset format for `expert_compression_ready`.
- Keep rollback only within the same artifact objective version.
- Include objective version in artifact metadata.

Suggested artifact metadata:

```json
{
  "expert_objective_version": "retrieval_grounded_compression_v1",
  "training_record_types": [],
  "requires_retrieved_evidence": true,
  "dataset_hash": "...",
  "bundle_benchmark_hash": "...",
  "best_checkpoint_step": 0
}
```

Tests to add:

- Old prompt-only adapter cannot be marked `expert_compression_ready`.
- Rollback cannot activate an artifact with incompatible objective version.
- Dataset mismatch marks expert stale.
- Benchmark mismatch marks expert unverified.

## Bug Prevention Guidelines

These rules should be treated as engineering guardrails, not suggestions.

1. Adapter product calls must never be prompt-only.

2. Retrieval remains citation authority in every path.

3. Adapter output must be validated against retrieved evidence before use.

4. Unsupported source titles, names, dates, quantities, and citations must fail closed.

5. Quality scores must come from live outputs, not structural proxy formulas.

6. Every benchmark artifact must include raw text samples.

7. Token budgets must be category-aware and logged in artifacts.

8. Dataset hash and objective version must match before a result can promote an adapter.

9. Route-away categories must be enforced in both product routing and benchmark routing.

10. Scorers must not reward prompt-word echo or scaffold phrases.

11. Scorers must not penalize valid paraphrase just because retrieval echoed source text.

12. Training records must include evidence inputs if the target output uses source facts.

13. Synthetic vaults must avoid repeated entity/template cycling that creates artificial bleed-through.

14. `MANIFEST.json` and benchmark metadata files must never become training or benchmark sources.

15. Failed expert runtime must degrade to retrieval-only, not block the user answer.

16. UI must never claim a cluster expert is trained unless the current artifact passed the current objective gate.

17. Bridge/MCP must always provide expansion handles for source verification.

18. External writebacks must not enter memory/training unless grounded or explicitly user-approved.

## Success Metrics

Architecture success is not "adapter score beats retrieval score." Success is measured by bundle usefulness and safety.

Required release-quality metrics:

| Metric | Target |
| --- | --- |
| Wrong citation/source-title rate | `0` in release-gate sample |
| Unsupported entity/date/number insertion rate | `0` in release-gate sample |
| Dataset/objective mismatch handling | Always fails closed |
| Token savings vs retrieval-only full packet | `>= 40%` initial target |
| Quality regression vs retrieval-only full packet | `<= 5%` initial target |
| Quality improvement vs retrieval-only same-token packet | `>= 10%` initial target |
| Expert runtime failure behavior | Retrieval-only fallback succeeds |
| Raw artifact coverage | 100% of benchmark cases include raw packet/output |
| Bridge expansion success | 100% of emitted handles expand or return explicit permission error |
| UI state accuracy | No stale/failed artifact shown as trained |

Training success metrics:

- Eval loss is logged during training.
- Best checkpoint is selected automatically.
- Training stops before overfitting where possible.
- Train/validation split has no source overlap.
- Record-type distribution is visible in manifest.

Product success metrics:

- Large clusters can answer through compact packets without sending hundreds of raw sources.
- External MCP clients receive model-ready packets by default.
- Users can expand sources when they need verification.
- Retrieval-only mode remains usable on lower-spec hardware.
- Expert compression adds value without becoming a trust risk.

## Recommended Implementation Sequence

1. Update docs and status language.

2. Add `cluster_bundle.py` with retrieval-only bundle output.

3. Route Bridge through the bundle builder without enabling LoRA compression yet.

4. Route chat through the bundle builder without enabling LoRA compression yet.

5. Add bundle schemas and token ledger fields.

6. Add tests proving retrieval-only bundle parity with current behavior.

7. Add `run_cluster_expert_compression` and evidence-grounded adapter prompts.

8. Add expert digest validation and fail-closed fallback.

9. Enable expert compression behind a flag.

10. Redesign training exporter for evidence-packet-to-digest records.

11. Retrain a 1.5B adapter under the new objective.

12. Replace benchmark with bundle quality and token-savings benchmark.

13. Update UI states and Bridge settings.

14. Run full regression, benchmark, and artifact export.

15. Only then decide whether 2B or 3B bases are necessary.

## Release Checklist For This Architecture

- Docs describe retrieval-grounded cluster bundles.
- Chat and Bridge share the same bundle builder.
- Product paths do not call prompt-only adapter generation.
- LoRA input includes retrieved evidence.
- Bundle packet includes citations and expansion handles.
- Expert digest is explicitly non-authoritative.
- Token ledger is returned and rendered.
- Benchmark compares token savings and quality.
- Training data matches the new objective.
- Legacy prompt-only adapters cannot graduate.
- UI states distinguish retrieval readiness from expert compression readiness.
- Model setup separates chat runtime from expert compression runtime.
- Security and writeback gates continue to block ungrounded memory/training inclusion.

## Open Decisions

- Whether public V1 blocks on expert compression or allows retrieval-only public release with expert compression as preview.
- Minimum hardware tier for expert compression after profiling.
- Whether summarization is shared or retrieval-owned by default in product routing.
- Whether Bridge clients can request expert compression per call or only inherit client-level permission.
- Minimum benchmark sample size required for public release gating.
- Whether token-savings targets should differ for chat, Bridge, and MCP clients.

