# Behavior-Specialized Hybrid Cluster Expert Implementation Plan

Last updated: 2026-06-27

## Purpose

This document defines the implementation plan for changing CML's cluster expert architecture from "LoRA adapter as a standalone cluster memory expert" to a behavior-specialized hybrid expert:

- retrieval for facts
- LoRA for cluster-specific behavior
- final synthesis from a retrieval-grounded packet

The goal is to preserve the original product value:

- Reduce repeated context replay for large personal clusters.
- Give local and external models compact, reusable, source-grounded cluster context.
- Keep cluster-specific terminology, style, and reasoning patterns available without forcing every downstream model to reread hundreds of raw sources.

The architecture change is necessary because recent LoRA testing showed that a small cluster adapter is not safe as the factual source of truth. It can produce fluent but wrong source titles, names, places, and citations. Retrieval must remain the authority for facts and citations.

The correction in this version is important: LoRA should not be reduced to a cosmetic compression helper only. It should own the cluster's behavior where behavior is separable from factual authority:

- terminology preference
- local framing
- answer shape
- reasoning order
- practical emphasis
- conflict-handling tone
- uncertainty language

## Product Contract

The product-facing phrase "cluster expert" remains valid only if it means the full hybrid cluster bundle:

```text
Cluster Expert Bundle =
  retrieval index
  source manifest
  source-trust metadata
  memory profile
  cluster glossary
  LoRA behavior adapter
  quality and freshness metadata
  expansion handles
  token-savings telemetry
```

The adapter is not the expert by itself. The bundle is the expert.

The source-of-truth contract is:

```text
Retrieval owns facts, citations, source IDs, quotes, dates, names, numbers, and refusal when evidence is missing.
LoRA owns grounded behavior specialization: terminology normalization, local style, reasoning-pattern hints, answer structure, and domain-specific framing.
The final chat model or external MCP model owns user-facing synthesis from the packet.
```

## Hybrid Expert Definition

A real behavior-specialized hybrid expert is not just clustered retrieval plus a short digest. It must satisfy all of the following:

- When retrieval is present, the answer still reflects cluster-specific behavior that the base model would not naturally produce.
- When the wrong cluster adapter is paired with the same evidence, style, terminology, framing, and reasoning order degrade measurably.
- When the correct adapter is used on weak evidence, the system still behaves like the right expert while refusing unsupported facts.
- Final factual authority always remains in the retrieved evidence.

This means the adapter is not evaluated as memory. It is evaluated as behavioral control under grounded conditions.

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
-> LoRA applies cluster-specific behavior over retrieved evidence
-> bundle returns compact packet with citations, expansion handles, and behavior cues
-> final model answers from packet
```

This preserves the token-saving idea without asking the adapter to memorize a 600-700 source cluster, while still giving LoRA a real product role.

## Non-Goals

- Do not make LoRA a factual database.
- Do not remove retrieval from expert-mode answers.
- Do not use citation-generation from the adapter as an authority signal.
- Do not train adapters on factual recall, citation grounding, or out-of-scope refusal as memory tasks.
- Do not collapse the adapter back into a pure compression-only role and still call it an expert.
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
    allow_expert_behavior: bool = True,
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
    "reasoning_patterns": [],
    "answer_contract": {
      "voice": "",
      "structure": [],
      "emphasis": [],
      "refusal_style": ""
    }
  },
  "expert_digest": {
    "used": false,
    "mode": "not_eligible",
    "text": "",
    "artifact_id": null,
    "warnings": [],
    "behavior_profile": {
      "terminology_shift": [],
      "style_markers": [],
      "reasoning_order": [],
      "framing_rules": []
    }
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
| Product context docs | `docs/PROJECT_CONTEXT.md`, `docs/OVERALL_CONTEXT.md` | Replace standalone "LoRA cluster expert" language with "behavior-specialized hybrid cluster expert." |
| LoRA policy | `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md` | Redefine graduation around grounded behavior specialization plus token savings, not adapter beating retrieval on facts. |
| LoRA runbook | `docs/LORA_FINDINGS_AND_REPLICATION_RUNBOOK.md` | Add latest finding: prompt-only adapter is unsafe as factual memory; new runs must use bundle objective. |
| Chat route | `backend/app/api/routes/chat.py::_build_retrieval_context` | Replace direct expert assist call with cluster bundle result. |
| Expert assist | `backend/app/api/routes/chat.py::_maybe_run_cluster_expert_assist` | Stop sending prompt-only requests to the adapter. Pass retrieved evidence and cluster profile plus behavior contract. |
| Expert runtime | `backend/app/core/expert_runtime.py::run_cluster_expert_prompt` | Keep for smoke only. Replace compression-only runtime with grounded behavior runtime. |
| Context packets | `backend/app/core/context_packets.py` | Add expert digest, retrieval authority, token ledger, behavior profile, and bundle status fields to rendered packets. |
| Bridge API | `backend/app/api/routes/bridge.py::build_context` | Call the bundle builder instead of assembling packet fields independently. |
| MCP formatting | `backend/app/bridge_mcp.py` | Surface bundle packet text by default and keep raw JSON diagnostics explicit. |
| Schemas | `backend/app/schemas.py::BridgeContextResponse`, `ChatCoverageLedger` | Add bundle status, expert digest, expert mode, token ledger, and retrieval-authority fields. |
| Training exporter | `backend/app/core/training_dataset.py` | Replace per-source answer categories with evidence-to-behavior records and packet-to-answer-shape records. |
| Evaluation | `backend/app/core/expert_evaluation.py` | Replace compression-only grading with behavior-specialization grading under grounded retrieval. |
| Legacy proxy scoring | `backend/app/core/training_evaluation.py` | Remove from activation paths or rename to structural readiness. Do not report as quality. |
| Training lifecycle | `backend/app/core/lora_training.py`, `backend/app/core/background_jobs.py` | Keep early stopping, eval loss, dataset hash, rollback, and quality gates; change quality gate input to bundle benchmark. |
| Model recommender | `backend/app/core/model_recommender/*` | Reword expert model as optional expert-compression runtime. Keep separate chat and expert hardware gates. |
| Desktop UI | `apps/desktop/src/routes/*` | Update status copy and progress UI to distinguish retrieval-ready from expert-compression-ready. |
| Scripts | `scripts/backend/*lora*.ps1`, `scripts/backend/export-lora-run-artifacts.py` | Generate bundle benchmark artifacts with raw packets, token ledgers, behavior deltas, sample outputs, and per-case expert use. |

## Behavior Ownership

The adapter should own these behaviors only when grounded evidence is present:

- preferred local terminology
- answer structure such as bulleting, sequencing, and conclusion style
- reasoning order such as evidence -> interpretation -> action
- practical or diagnostic emphasis
- conflict and uncertainty phrasing
- local domain framing

The adapter must not own:

- exact factual recall
- citation identity
- source-title generation from memory
- dates, names, quantities, or quotes unless directly supported by retrieval

## Router Upgrade

The current router decides mainly whether expert compression is eligible. The hybrid expert router must decide:

- whether retrieval evidence is sufficient
- whether a cluster adapter is behavior-eligible
- whether the query is behavior-sensitive or purely factual
- whether the final answer should use:
  - retrieval only
  - retrieval + behavior adapter
  - retrieval + behavior adapter + packet compression

Initial route-away categories should remain fact-heavy:

- factual recall
- citation grounding
- strict numeric/date/entity extraction

Initial route-toward categories should expand:

- terminology consistency
- style transfer
- reasoning pattern
- practical summarization
- conflict framing
- uncertainty boundaries

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

- Replace "LoRA cluster expert" with "behavior-specialized hybrid cluster expert" where the claim is product-facing.
- Replace "adapter knows the cluster" with "adapter applies cluster-specific behavior to retrieved evidence."
- Replace "expert beats retrieval" with "expert bundle improves behavior quality while preserving factual grounding."
- Keep "citations come only from retrieval" explicit.
- Mark standalone adapter factual recall as an invalid goal.

Acceptance checks:

- No public-facing doc should imply the adapter can be trusted as source memory.
- All release gates should describe grounded bundle quality and measurable behavior lift, not adapter memory quality.
- Hardware docs should treat expert compression as a higher-spec optional capability unless public V1 explicitly blocks on it.

## Phase 2: Cluster Bundle Core

Create `backend/app/core/cluster_bundle.py`.

Responsibilities:

- Run semantic retrieval for the selected cluster or vault scope.
- Load memory items and working memory.
- Build a source-grounded evidence packet.
- Decide whether expert behavior is eligible.
- Call LoRA only with retrieved evidence.
- Extract and persist behavior profile signals that can be reused downstream.
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

def build_expert_behavior_prompt(...) -> str:
    ...

def extract_behavior_profile(...) -> dict:
    ...

def estimate_bundle_token_savings(...) -> dict:
    ...
```

Invariants:

- If no retrieval evidence exists, expert compression is not eligible.
- If the query is factual/citation/refusal-sensitive, adapter output may be used only as a non-authoritative digest or disabled entirely.
- If LoRA output mentions a source title, name, number, or date not found in evidence, the digest must be discarded.
- A failed expert call must degrade to retrieval-only without failing the chat request.
- If the adapter does not produce measurable cluster-specific behavior beyond the base model, it must not be treated as a qualified expert artifact.

Tests to add:

- `backend/tests/test_cluster_bundle.py`
- Test bundle returns retrieval evidence without expert when no adapter exists.
- Test bundle calls expert only when evidence exists.
- Test bundle rejects prompt-only expert calls in product path.
- Test bundle strips or rejects unsupported source/entity claims from expert digest.
- Test bundle reports token savings telemetry.
- Test bundle degrades cleanly when expert runtime fails.
- Test bundle emits behavior profile fields only when supported by grounded evidence.
- Test wrong-adapter-vs-right-adapter produces measurable behavior deltas with the same evidence.

## Phase 2A: Behavior Profile Layer

Add a behavior profile abstraction derived from the cluster corpus and reinforced by training:

```json
{
  "terminology_shift": [],
  "style_markers": [],
  "reasoning_order": [],
  "framing_rules": [],
  "refusal_style": "",
  "practicality_bias": ""
}
```

This profile must be built from local evidence and attached to:

- bundle construction
- training record generation
- runtime prompting
- evaluation reports

The behavior profile is the contract the adapter is trying to learn.

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

## External Dataset Choice And Import Plan

The exact external dataset pair for the next rebuild is:

- source corpus: `wikimedia/wikipedia`
- QA and benchmark prompts: `rajpurkar/squad_v2`

Use the current English Wikipedia config:

```text
dataset = wikimedia/wikipedia
config = 20231101.en
split = train
```

Use the default SQuAD v2 config:

```text
dataset = rajpurkar/squad_v2
config = squad_v2
splits = train, validation
```

This pairing is intentional:

- `wikimedia/wikipedia` gives us a large clean text reservoir for the exact `700` train-source and `300` validation-source corpus split.
- `rajpurkar/squad_v2` gives us a separate prompt-and-answer bank with explicit answerable and unanswerable cases.
- SQuAD must not become the adapter's factual memory target. It is a prompt/answer and benchmark asset, not the factual authority for the expert runtime.

### Import Contract

The import must produce three distinct artifacts, not one blended dataset:

- `train-sources.jsonl` and `validation-sources.jsonl`
  - raw source documents from `wikimedia/wikipedia`
- `train-corpus.txt` and `validation-corpus.txt`
  - pure text concatenation of the source split for inspection and trainer sanity checks
- `train-qa.jsonl` and `validation-qa.jsonl`
  - prompt/answer records from `rajpurkar/squad_v2`

Target counts:

- source corpus: exactly `1000` Wikipedia articles
  - `700` train
  - `300` validation
- QA prompts:
  - import the full `squad_v2` `validation` split as the first benchmark/eval bank
  - optionally import a bounded subset of `squad_v2` `train` as a separate development prompt bank

### Wikipedia Selection Rules

Do not ingest Wikipedia blindly. Apply source-quality gates before the `700/300` split:

- language must be English via config `20231101.en`
- keep only articles with substantive body text
- exclude pages dominated by lists, tables, redirects, or disambiguation-style patterns
- exclude ultra-short stubs
- exclude duplicate normalized text
- strip empty sections and excessive markup residue if present

Initial concrete thresholds:

- minimum normalized text length: `1500` characters
- preferred article size band: `1500-20000` characters
- maximum title duplication: `1`
- duplicate normalized-content tolerance: `0`

Selection procedure:

1. Stream or batch-load `wikimedia/wikipedia`, config `20231101.en`, split `train`.
2. Normalize article text into the exact trainer-ready plain-text form.
3. Filter by the quality rules above.
4. Deterministically sample `1000` accepted articles with a fixed seed.
5. Sort the accepted sample deterministically by synthetic `source_id`.
6. Assign the first `700` to train and the next `300` to validation.

Required stored fields per imported Wikipedia source:

```json
{
  "source_id": "wiki:<config>:<row_id>",
  "title": "Article title",
  "text": "Normalized article text",
  "summary": "Short derived summary",
  "content_hash": "hash",
  "origin_dataset": "wikimedia/wikipedia",
  "origin_config": "20231101.en",
  "origin_split": "train"
}
```

### SQuAD v2 Selection Rules

SQuAD import is separate and must preserve answerability metadata.

Keep fields:

- `id`
- `title`
- `context`
- `question`
- `answers.text`
- `answers.answer_start`
- impossible or no-answer status

Required stored fields per QA item:

```json
{
  "qa_id": "squad_v2:<split>:<id>",
  "title": "Article title",
  "question": "User-style prompt",
  "context": "Evidence passage",
  "answers": ["canonical answer"],
  "is_impossible": false,
  "origin_dataset": "rajpurkar/squad_v2",
  "origin_config": "squad_v2",
  "origin_split": "validation"
}
```

Import rules:

- keep answerable and unanswerable records
- preserve multiple gold answers when they exist
- dedupe exact duplicate question/context pairs
- do not rewrite answers into unsupported paraphrases
- keep `validation` pristine as the benchmark bank

### How This Fits The Hybrid-Expert Objective

The role split must stay strict:

- Wikipedia articles provide the raw textual source bed for behavior-specialization exports.
- SQuAD provides independent question/answer probes so we can test whether the retrieval-grounded system answers cleanly and refuses unsupported cases correctly.
- The LoRA objective remains behavior specialization under evidence, not memorization of Wikipedia facts or SQuAD answers.

That means:

- do not train the adapter to answer a SQuAD question from memory without evidence
- do not treat SQuAD gold answers as the runtime citation authority
- do use SQuAD prompts to benchmark retrieval grounding, refusal behavior, answer structure, and evidence use

### Import Implementation Plan

Implement one dedicated importer script for the external rebuild:

```text
scripts/backend/import-hf-wikipedia-squad.py
```

The script should:

1. Download or stream `wikimedia/wikipedia` `20231101.en`.
2. Build the filtered `1000`-article source pool.
3. Export exact `700/300` source splits through `write_cluster_training_dataset(...)`.
4. Download `rajpurkar/squad_v2`.
5. Export separate QA banks:
   - `train-qa.jsonl`
   - `validation-qa.jsonl`
   - optional raw `squad-validation-prompts.jsonl`
6. Emit a machine-readable manifest with:
   - dataset IDs
   - configs
   - split dates
   - row counts
   - content hashes
   - sample IDs

Suggested output layout:

```text
artifacts/external-datasets/wiki-squad-v1/
  dataset-manifest.json
  train-sources.jsonl
  validation-sources.jsonl
  train-corpus.txt
  validation-corpus.txt
  train-qa.jsonl
  validation-qa.jsonl
  squad-validation-prompts.jsonl
```

### Runtime And Benchmark Guardrails

Before any LoRA retrain or benchmark run:

- fail closed if Wikipedia source count is not exactly `700/300`
- fail closed if SQuAD validation bank is missing
- fail closed if source manifest hashes change without a new dataset version
- record the external dataset IDs and configs in the adapter artifact manifest

The dataset label for this rebuild should be:

```text
wiki-squad-hybrid-v1
```

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
