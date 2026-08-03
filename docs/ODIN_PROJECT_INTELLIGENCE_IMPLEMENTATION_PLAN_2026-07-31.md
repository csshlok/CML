# Odin Project Intelligence Implementation Plan

Date: 2026-07-31
Status: Local planning document; not a release commitment
Scope: Odin project indexing, project understanding, change context, and agent-facing context delivery

RepoWise comparison refreshed: 2026-08-01 at upstream commit
`18316eaf6ad5338f4f7144b74345608896e9fc70`. The review used public behavior and
architecture as research input only. RepoWise remains AGPL-3.0; no implementation
source is to be copied into Odin.

## 1. Purpose

This plan evolves Odin from a project-scoped retrieval system with an evidence-backed
code graph into a durable project-intelligence layer.

The objective is not to reproduce RepoWise or turn Vault into a general code-quality
analytics product. The objective is to make Odin answer four practical questions
reliably:

1. What does this project do?
2. How is it structured and how does a request or operation flow through it?
3. What is affected by a proposed or observed change?
4. Why was the relevant code designed this way?

The implementation must remain:

- local-first and compatible with user-provided local models;
- deterministic wherever the fact can be derived without a model;
- evidence-backed, snapshot-bound, and honest about missing information;
- incremental rather than dependent on full-project regeneration;
- useful without requiring generated prose;
- bounded for large repositories;
- independent implementation informed by public product concepts, without copying
  AGPL-licensed RepoWise source.

## 2. Current Odin Baseline

Odin already provides the foundation this plan should extend:

- explicit project registration and discovery scopes;
- immutable project snapshots and atomic retrieval activation;
- incremental changed-path synchronization;
- versioned AST extraction across supported languages;
- persisted file, symbol, route, package, and relationship nodes;
- evidence-backed graph edges with source locations and confidence classes;
- bounded graph/tree projections, neighbors, and shortest paths;
- project-scoped retrieval and cited answers;
- a deterministic project brief derived from README or manifest metadata;
- a Projects workspace, on-demand project map, CLI, API, and local access controls.

The principal gaps are:

- the project brief is a single shallow string rather than a structured, refreshable
  understanding of the project;
- graph orientation relies mainly on local degree and bounded walks;
- Git history is used for freshness but not behavioral intelligence;
- architectural decisions are ordinary retrieved text rather than governed records;
- project context calls expose useful primitives but do not yet assemble complete,
  task-shaped intelligence;
- project-scoped chat reduces a project to its backing retrieval cluster, so questions
  about the latest repository changes can be answered from semantically similar but
  stale documents instead of live Git and Odin snapshot state;
- the model-visible context packet exposes internal citation handles and asks the
  model to cite them, which can produce duplicate user-facing citations and leak
  `chunk:*` identifiers when a local model does not follow formatting guidance;
- Odin does not map changes to guarding tests;
- no explicit confidence and provenance contract exists for every project-level
  interpretation.

## 3. Product Principles

### 3.1 Facts before prose

Odin should first build a model-independent structured record. Generated prose is an
optional presentation layer over that record.

### 3.2 Unknown is a valid result

An empty list must not silently mean "none." Responses must distinguish:

- known empty;
- unavailable because a layer has not been built;
- incomplete because a bounded scan was truncated;
- stale because the project changed;
- unsupported for the language or repository type.

### 3.3 Snapshot identity travels with every result

Every project-intelligence response must identify:

- project ID;
- retrieval snapshot ID;
- structure snapshot ID;
- indexed commit when available;
- generated-at timestamp;
- active extractor/intelligence contract versions;
- stale or partial layers.

### 3.4 Incremental invalidation

A changed file should invalidate only the intelligence derived from that file and its
bounded dependents. A one-file edit must not regenerate a whole-project wiki or run
unbounded graph analysis.

### 3.5 Explainable signals

Graph and Git signals should expose their inputs. Odin should initially report
centrality, churn, co-change, ownership, and cycles rather than collapse them into an
opaque universal health score.

### 3.6 Model portability

The system may ask a model to describe facts, but it must not require one specific
model to discover the facts or interpret a private prompt convention correctly.

### 3.7 Live state outranks retrieved descriptions

Questions whose answer depends on current repository state must read the bounded live
project-state authority. Semantic retrieval can explain a change, but it cannot decide
which change is latest.

For example, "What are the latest changes in this repo?" must be answered from current
HEAD, recent commits, the working-tree delta, Odin's indexed commit, and the active
snapshot. A README, changelog, or project-context document that describes an older
release must not override those facts merely because its wording is semantically
similar.

If no project is selected, Odin should request a project selection rather than search
the entire vault for a plausible repository description.

### 3.8 Structured citations are the user-facing authority

Models receive evidence labels sufficient for attribution, but user-facing citations
come from the structured response contract and are rendered once by the client.

- The answer model must not be asked to emit Markdown links, packet handles, a
  `Citations` section, or a `Sources` section.
- Internal `chunk:*` and `source:*` handles must never appear in final answer text.
- The backend must retain the authoritative citation objects independently of model
  output.
- Output cleanup should remove only known internal handles or a clearly generated
  trailing citation block when structured citations already exist; it must not
  broadly rewrite legitimate user content or arbitrary Markdown.
- Local-model noncompliance is an expected contract case, not a model-specific defect.

### 3.9 Lessons from the refreshed RepoWise review

Adopt the product ideas that reinforce Odin's existing architecture:

- deterministic graph and Git intelligence should become useful before any generated
  documentation or model synthesis is available;
- task-shaped operations should answer a user goal in one bounded response rather than
  force callers through chains of entity-shaped lookups;
- every response should carry one quiet freshness envelope comparing the indexed
  snapshot with the live repository, without warning merely because an index is old;
- retrieval quality and answer confidence are different signals and must remain
  separately inspectable;
- graph views should progressively disclose communities, important files, paths, and
  evidence rather than render the entire repository by default;
- truncation is a normal bounded state and should say exactly what is shown, what is
  omitted, and how to expand safely;
- flow and path results should explain why each hop exists and whether the relationship
  was extracted or inferred.

Adapt these ideas to Odin instead of recreating RepoWise's implementation:

- persist intelligence beside Odin's immutable project snapshots in the existing
  SQLite authority; do not add a parallel graph/vector database;
- reuse Odin's source eligibility, encryption, job, snapshot, retrieval, and access
  controls rather than introduce repository-local state or automatic agent hooks;
- compute only the graph and Git signals required by the four user questions in this
  plan; do not import a universal health score or analytics dashboard;
- use the existing Project Map graph renderer and improve orientation, disclosure, and
  interaction around it rather than replacing a graph users already understand.

Continue to reject or defer generated per-file wikis, broad dead-code claims,
contributor surveillance, automatic transcript mining, cross-repository workspaces,
and always-on editor hooks until an Odin-specific user case and accuracy gate exists.

### 3.10 Project Map rework: preserve the graph, simplify understanding

The current graph visualization is a product strength and should remain visually and
behaviorally recognizable. Rework the surrounding experience so a non-expert can move
from orientation to evidence without learning graph terminology:

- open with a short, evidence-backed explanation of what slice is visible and why;
- present simple `Communities` and `Files` scopes when community data is ready, while
  keeping advanced direction/depth controls behind progressive disclosure;
- turn observed flows into selectable, plain-language journeys with a named start,
  end, relationship types, confidence, and the reason the flow was selected;
- add a two-target path finder that searches indexed nodes and highlights a bounded
  evidence-backed path without changing the underlying graph layout;
- make every selected node answer: what is this, why is it shown, what calls it, what
  it calls, and which source span supports each relationship;
- replace an ambiguous `more available` suffix with exact shown/available counts and
  stepped expansion that states when a larger view may be slower;
- keep search, selection, focus, clear, close, keyboard navigation, and back behavior
  predictable; never require canvas precision for the only path to an action;
- keep empty, partial, stale, unsupported-language, and truncated states distinct and
  actionable without stacking warning panels;
- validate the page at small, medium, and large real repositories. A readable default
  view is more important than maximizing visible node count.

## 4. Target Architecture

### 4.1 Project Intelligence Snapshot

Each active Odin structure snapshot gains one immutable intelligence record:

```text
ProjectIntelligenceSnapshot
├── identity
│   ├── name
│   ├── repository kind
│   ├── purpose candidates
│   └── technology evidence
├── architecture
│   ├── modules and communities
│   ├── entry points
│   ├── key areas
│   ├── dependency cycles
│   └── bounded execution flows
├── repository signals
│   ├── churn
│   ├── ownership
│   ├── co-change
│   └── bug-fix history
├── decisions
│   ├── active
│   ├── proposed
│   ├── stale
│   └── conflicting
├── interpretation
│   ├── deterministic synopsis
│   ├── optional generated synopsis
│   └── evidence and confidence
└── freshness
    ├── layer versions
    ├── partial/truncated state
    └── invalidation reasons
```

This is a derived, replaceable artifact. Existing project sources, chunks, nodes, and
edges remain authoritative.

### 4.2 Provenance record

Every interpreted field should reference one or more provenance records containing:

- source type: README, manifest, code graph, Git commit, ADR, comment, or user;
- source identifier and path;
- source snapshot or commit;
- optional line span;
- extraction method and version;
- confidence class;
- evidence excerpt hash;
- verification state: exact, derived, model_summarized, or unverified.

Model-written text cannot become authoritative evidence. It can only summarize
already-authoritative records.

### 4.3 Layer state

Each layer has its own status:

- waiting;
- building;
- ready;
- partial;
- stale;
- unavailable;
- failed.

Failure of optional Git, decision, or interpretation work must not deactivate healthy
structure or retrieval snapshots.

## 5. Implementation Phases

## Phase 0 — Contracts and measurement

### Scope 0A: Freeze current behavior

- Add representative fixtures for Python, TypeScript/React, a non-Git folder, a small
  monorepo, and a repository with sparse documentation.
- Capture current brief, graph-summary, context, freshness, and project-map outputs.
- Record current indexing time, graph-query latency, database size, and peak memory.

### Scope 0B: Define versioned response contracts

- Define `ProjectIntelligenceSnapshot`, `IntelligenceLayerState`,
  `IntelligenceEvidence`, and `UnknownReason`.
- Specify stable JSON responses before adding UI.
- Define backward-compatible behavior when no intelligence snapshot exists.

### Focused test batch A

Run after both scopes:

- contract serialization and validation tests;
- migration upgrade/idempotence tests;
- baseline snapshot tests;
- existing project context and graph API tests most directly affected.

Exit condition: contracts are stable and existing projects still load without
reindexing.

## Phase 1 — Deterministic project overview

### Scope 1A: Evidence-backed identity and purpose

- Preserve README and manifest descriptions as separate evidence candidates.
- Add deterministic technology, workspace, entrypoint, route, and module facts.
- Rank purpose candidates by source authority and freshness.
- Never treat badges, navigation, installation text, or generated counts as purpose.

### Scope 1B: Project overview assembler

- Build a structured overview from purpose evidence plus graph facts.
- Produce a deterministic synopsis that remains useful without a generation model.
- Allow optional local-model prose only after the structured overview is complete.
- Require generated prose to cite or reference the facts it summarized.
- Store model ID and prompt/contract version separately from the authoritative facts.

### UI behavior

- Replace the single brief paragraph with the active overview synopsis.
- Show "Based on README", "Derived from project structure", or equivalent provenance.
- Show a stale/partial state without replacing the last healthy overview.
- Provide a small evidence disclosure rather than dumping all source material.

### Focused test batch B

Run after both scopes:

- README/manifest purpose extraction matrix;
- sparse/no-documentation project behavior;
- generated-prose validation and fallback;
- incremental overview invalidation;
- project-details rendered UI test;
- weak/local model compatibility using contract-shaped fakes rather than one model's
  preferred wording.

Exit condition: "What this project does" is meaningful, sourced, and refreshes when
its contributing evidence changes.

## Phase 2 — Graph intelligence

### Scope 2A: High-value deterministic metrics

Implement only:

- PageRank or an equivalent directed centrality measure;
- strongly connected components and actionable dependency cycles;
- deterministic community/module detection;
- per-node in-degree and out-degree;
- bounded entrypoint-to-handler execution-flow candidates.

Do not add every available graph metric. Betweenness and more expensive analyses
should be added only if a measured user question requires them.

### Scope 2B: Retrieval and map integration

- Bias overview and structural-context selection using centrality and query relevance.
- Use communities to group project-map nodes and generate module summaries.
- Prefer implementation nodes over tests and generic symbols unless the question asks
  for tests.
- Include edge confidence and relationship type in flow selection.
- Improve TypeScript/React import, reference, and re-export resolution before using
  centrality as a strong authority signal.

### Focused test batch C

Run after both scopes:

- known graph fixtures with exact SCC/community expectations;
- deterministic repeated-run output;
- TypeScript/React import and re-export fixtures;
- bounded-map and structural-ranking tests;
- 1K/10K-node synthetic graph latency and memory checks.

Exit condition: key areas and flows are more representative than degree-only ranking,
without making map or context queries noticeably slower.

## Phase 3 — Git behavioral intelligence

### Scope 3A: Explainable per-file signals

Add bounded, incremental computation for:

- recent churn;
- last meaningful changes;
- ownership percentages;
- contributor concentration;
- bug-fix commit count with an explicit heuristic label;
- repository-history availability and truncation.

### Scope 3B: Co-change and change context

- Compute bounded co-change pairs from recent commits.
- Keep co-change distinct from structural dependency.
- Add a change-context response containing changed files, structural dependents,
  co-change partners, affected communities, known tests, and unknowns.
- Add a bounded live repository-state record containing:
  - current HEAD and branch;
  - Odin's indexed commit and active snapshot identity;
  - recent meaningful commits with commit time and subject;
  - staged, unstaged, untracked, renamed, and deleted paths;
  - whether each pending path is already represented in the active Odin snapshot;
  - truncation, shallow-history, non-Git, and read-failure states.
- Treat live repository state as authoritative for recency. Retrieved documents may
  provide rationale or release context only after the current changes are established.
- Report why every file appears in the result.

### Focused test batch D

Run after both scopes:

- synthetic Git-history fixtures;
- rename, merge, shallow clone, no-Git, and rewritten-history cases;
- co-change versus import distinction;
- recent commits plus dirty working-tree changes;
- indexed commit behind, equal to, and ahead of the inspected worktree;
- stale documentation claiming to describe the "latest" release;
- bounded history and changed-path truncation;
- incremental recomputation;
- bounded large-history benchmark.

Exit condition: Odin can explain likely companion files without presenting historical
correlation as a definite dependency, and can answer current-change questions without
using document recency as a substitute for Git state.

## Phase 4 — Task-shaped Odin context

### Scope 4A: Context operations

Add composed service operations:

- `get_project_overview`;
- `get_code_context(targets, include)`;
- `get_project_state`;
- `get_change_context(base, head or working_tree)`;
- `get_blast_radius(targets)`.

These operations should use the existing project authority and snapshot data rather
than build a second index.

### Scope 4B: Intent-guided context assembly

- Route overview, structural, change, symbol, and general project questions to the
  appropriate intelligence layers.
- Extend the router source ontology with a typed `project_state` source. It is
  available only when a valid project scope exists and must never silently widen to
  all vault documents.
- Route questions that require current repository state through `project_state`.
  Semantic/model classification provides guidance, while deterministic scope and
  source-availability validation prevents an invalid route from becoming authoritative.
- When no project is selected for a repository-state question, return a project
  selection requirement rather than an inferred answer from unrelated documents.
- Use semantic/model routing as guidance, not as the only safety boundary.
- Batch multiple targets in one call.
- Return compact defaults with explicit expansion paths.
- Preserve raw source access as a bounded follow-up rather than placing whole files in
  every response.
- Give the model human-readable evidence labels without exposing internal expansion
  handles in the answer-writing instructions.
- Require answer text and structured citations as separate response fields. Render
  structured citations exactly once in chat.
- Apply a narrow internal-handle/citation-block guard after generation so a local
  model that repeats packet metadata cannot leak implementation identifiers.

### Focused test batch E

Run after both scopes:

- intent families expressed with varied natural language;
- invalid router output fallback;
- current-repository questions with and without a selected project;
- live Git state winning over a stale semantically similar project document;
- committed changes, uncommitted changes, and a clean repository;
- multi-target batching;
- stale and partial-layer behavior;
- token-budget and citation integrity;
- a local model that emits Markdown citation links or repeats `chunk:*` handles;
- exactly one rendered structured citation set with no internal handles in answer text;
- MCP/CLI/API parity for the new operations.

Exit condition: common project questions require one composed call rather than a
sequence of low-level graph and retrieval calls, and current-change answers remain
fresh and presentation-safe across local model behaviors.

## Phase 5 — Architectural decision intelligence

### Scope 5A: Conservative extraction

Start with:

- ADR/MADR files;
- explicit `WHY`, `DECISION`, `RATIONALE`, and `TRADEOFF` markers;
- high-confidence Git commit messages;
- user-created or user-confirmed decisions.

Each decision stores:

- statement;
- rationale;
- governed paths/nodes;
- source evidence;
- status: proposed, active, superseded, stale, dismissed;
- confidence and verification state.

### Scope 5B: Decision relationships and delivery

- Support `supersedes`, `refines`, `relates_to`, and `conflicts_with`.
- Require review for uncertain supersession or conflict.
- Recompute staleness when governed nodes materially change.
- Add decisions to project overview and target context only when relevant.
- Never silently inject unverified decisions as instructions to a coding agent.

### Deferred

- coding-agent transcript mining;
- automatic behavioral promotion from user conversations;
- broad comment archaeology without centrality and rationale gates.

### Focused test batch F

Run after both scopes:

- exact provenance and line-span validation;
- false-positive fixtures;
- supersession/conflict lifecycle;
- stale governed-file behavior;
- dismissal tombstones and reindex idempotence;
- hostile text treated as evidence rather than instructions.

Exit condition: Odin can answer "Why is this designed this way?" with inspectable,
reviewable evidence.

## Phase 6 — Coverage-backed impacted tests

### Scope 6A: Coverage ingestion

- Support one format first, selected from the repository's actual frontend/backend
  coverage outputs.
- Store per-file coverage separately from per-test-to-code mappings.
- Preserve commit/snapshot identity for the coverage artifact.
- Treat missing or stale coverage as unknown.

### Scope 6B: Impacted test selection

- Select tests whose recorded execution intersects changed files or changed lines.
- Label filename-pattern matches as guesses, separate from coverage evidence.
- When no trustworthy map exists, advise focused discovery or the full suite rather
  than returning an authoritative empty list.

### Focused test batch G

Run after both scopes:

- coverage parsing and path normalization;
- ambiguous basename refusal;
- changed-line intersection;
- stale coverage;
- deletion-only changes;
- known-empty versus no-map behavior;
- bounded large-map lookup.

Exit condition: Odin can recommend focused tests with an honest evidence classification.

## 6. Persistence and Migration Strategy

Prefer a small number of normalized tables:

- `project_intelligence_snapshots`;
- `project_intelligence_evidence`;
- `project_graph_metrics`;
- `project_git_file_signals`;
- `project_cochange_edges`;
- `project_decisions`;
- `project_decision_evidence`;
- `project_decision_edges`;
- optional later coverage tables.

Requirements:

- foreign keys bind derived records to project and snapshot;
- candidate results remain invisible until their owning layer is ready;
- activating optional intelligence must not rewrite active source/chunk membership;
- old derived snapshots are retention-managed independently from authoritative project
  snapshots;
- migration must be idempotent and allow lazy backfill;
- upgraded users must not be forced into an immediate full-project analysis before
  existing search and map features work.

## 7. Background Job Design

Use the existing job system and avoid one job per file.

Recommended jobs:

- `project_intelligence_overview`;
- `project_graph_metrics`;
- `project_git_intelligence`;
- `project_decision_refresh`;
- `project_coverage_ingest`.

Rules:

- enqueue work per project snapshot or bounded changed-path batch;
- coalesce duplicate pending jobs;
- checkpoint long Git and graph work;
- retain the previous healthy layer while a replacement builds;
- make optional-layer failures independently retryable;
- expose progress in units meaningful to users: files, commits, nodes, decisions;
- allow pause, cancellation, restart, and stale-worker recovery.

## 8. Performance and Scale Gates

Initial budgets are engineering gates, not public product claims:

| Operation | Initial gate |
| --- | --- |
| Load project overview | p95 under 150 ms from persisted snapshot |
| Multi-target code context, 10 targets | p95 under 500 ms excluding model generation |
| Bounded blast radius | p95 under 750 ms at configured traversal bounds |
| Incremental one-file intelligence refresh | under 10 s on the reference medium project |
| Full graph metrics, 10K nodes / 50K edges | under 30 s and under 500 MiB additional RSS |
| Git intelligence, 5K recent commits | under 30 s and bounded memory |
| Project overview response | default estimated context under 2,500 tokens |

Retain the existing 50,000-file Odin discovery gate. Add intelligence-specific gates
only after the corresponding phase is implemented; do not run every scale gate after
every small edit.

## 9. Testing Policy

Implementation should follow the requested focused-batch discipline:

- complete at least two related implementation scopes before running their focused
  batch, unless a fast smoke test is necessary to diagnose a defect;
- do not run the whole regression suite after each phase;
- use deterministic fixtures and property/invariant checks rather than exact prose;
- test multiple paraphrases and malformed model contracts to avoid routing overfit;
- test repository-state routing by required information source, not by one fixed phrase
  such as "latest changes";
- include model outputs that ignore citation-format instructions and verify the
  structured citation boundary still holds;
- include non-Git, sparse-doc, large, unsupported-language, and stale-index cases;
- run the full regression suite only at the final integration gate;
- run release build and packaged-app verification only when explicitly entering release
  promotion.

The final integration gate must include:

- focused batches A through G;
- full backend regression;
- desktop typecheck and production build;
- Electron behavior tests;
- relevant Playwright project workflows;
- migrations from supported prior schema versions;
- existing Odin 50K discovery gate;
- new graph/Git intelligence scale gates;
- packaged validation only for a release candidate.

## 10. Security and Privacy

- Continue to index only approved eligible paths.
- Never execute repository code to infer architecture.
- Do not store raw credentials, secret files, or ignored content in intelligence
  evidence.
- Apply the existing path-disclosure and scoped-client rules to new APIs.
- Treat repository comments, documentation, commits, and generated text as data, not
  executable instructions.
- Keep transcript mining disabled and out of scope until separately designed and
  explicitly consented to.
- Diagnostic output should report counts, hashes, statuses, and bounded paths rather
  than raw source content.

## 11. Explicit Non-goals

This plan does not currently include:

- a universal code-health score;
- automated refactoring or patch generation;
- a generated wiki page for every file;
- remote repository indexing;
- cross-repository workspaces;
- PR hosting or review bots;
- automatic agent-session hooks;
- silent coding-agent transcript mining;
- arbitrary plugin execution;
- copying RepoWise implementation code.

Any of these requires a separate product case and evidence that it improves Odin's
core workflow.

## 12. Delivery Sequence

Recommended implementation order:

1. Phase 0 contracts and baseline.
2. Phase 1 deterministic project overview.
3. Phase 2 graph intelligence.
4. Phase 4 task-shaped context using the improved overview and graph.
5. Phase 3 Git intelligence and change context.
6. Phase 5 decisions.
7. Phase 6 impacted tests.

Phase 4 intentionally precedes the full Git layer so users receive value from the
existing graph sooner. Its initial contract may declare `project_state` unavailable;
Phase 3 activates that source with bounded live Git evidence, after which the combined
Phase 3D/4E focused tests become mandatory.

## 13. Definition of Done

The plan is complete when:

- the project page displays a current, evidence-backed explanation of what the project
  does;
- Odin can identify modules, key areas, cycles, entrypoint flows, and authoritative
  cross-file relationships;
- project answers state their snapshot, evidence, confidence, freshness, and unknowns;
- current repository-change questions use HEAD, recent commits, working-tree state,
  Odin's indexed commit, and active snapshot rather than treating project documents as
  a source of live state;
- an unscoped repository-state question requests project selection instead of
  searching the full vault;
- generated answer text contains no internal chunk/source handles or duplicate model-
  authored citation section when structured citations are present;
- change context distinguishes structural dependencies from historical co-change;
- architectural decisions are reviewable, cited, and freshness-aware;
- focused test recommendations distinguish coverage evidence from guesses;
- incremental updates preserve prior healthy layers and remain bounded;
- weak or user-supplied local models can consume the structured contracts without
  special-case prompt behavior;
- focused, full-regression, scale, migration, and final release gates pass at their
  appropriate promotion stages.

## 14. First Implementation Batch

The first approved coding batch should contain exactly:

1. Phase 0B response/data contracts and lazy migration.
2. Phase 1A evidence-backed identity and purpose extraction.

Then run focused batch A plus the purpose-extraction portion of batch B.

Do not add graph algorithms, Git mining, decisions, coverage ingestion, or new model
prompts in that first batch. This keeps the first change independently useful and
limits the migration and behavioral surface under review.

## 15. Implementation checkpoint — 2026-08-01

Completed in the first implementation tranche:

- Phase 0B outer response contracts, schema migration 29, snapshot/evidence tables,
  idempotent writes, and a lazy response for projects indexed before this schema;
- Phase 1A root README and supported-manifest purpose candidates, stored separately
  with line spans, source identity, extractor version, confidence class, and excerpt
  hashes;
- deterministic technology, workspace, entrypoint, route, symbol, and relationship
  facts without adding a generated-authority layer;
- project details rendering for sourced purpose and explicit unknown-purpose states;
- the first Project Map explainability tranche: shown-versus-indexed counts, bounded
  expansion, a quiet legend, progressive advanced controls, selectable evidence-backed
  flows, current-view upstream/downstream context, two-target path tracing, and honest
  tree filtering with an explicit no-match state.

Focused verification completed:

- contract validation, migration idempotence, legacy loading, purpose candidate
  separation, README-chrome rejection, 5,000 irrelevant nested-file stability,
  incremental purpose refresh, bounded graph totals/flow evidence, and tree-filter
  honesty;
- desktop TypeScript type checking;
- real isolated indexing of CML (547 eligible files / 9,897 graph nodes), Smart Traffic
  AI (81 / 531), and RepoWise (3,074 / 35,181), with the map projection remaining
  bounded at 90 items;
- CML project-context retrieval and the same retrieval path used by project chat:
  authoritative current evidence, implementation-file citations, matching project
  scope, and no partial-failure mode;
- browser verification of graph/tree switching, expansion, advanced disclosure,
  ambiguity recovery, exact path tracing, node selection, upstream/downstream
  navigation, detail closing, and project overview provenance/unknown states.

The configured local generation model was not treated as passing: its existing model
verification check failed during the run. Retrieval and chat grounding were verified
without claiming that final prose generation is healthy. The next tranche should move
to Scope 1B, then Phase 2A, while retaining these focused and real-repository gates.

## 16. Implementation checkpoint — Phase 1B through Phase 6 — 2026-08-01

Implemented end to end:

- Phase 1B structured overview assembly, deterministic no-model synopsis, active-snapshot
  evidence validation for optional generated prose, separate model/prompt identity, and
  progressive overview provenance/freshness disclosure;
- Phase 2 bounded directed centrality, iterative SCC/cycle detection, deterministic
  path-based communities, in/out degree, entrypoint/route flow candidates, lazy repair
  for older or partially published metrics, and Project Map explanations that say why
  an area is important and which community it belongs to;
- Phase 3 bounded Git history, churn, ownership shares, explicit bug-fix heuristics,
  recent commits, current HEAD/branch, indexed-commit relation, staged/unstaged/untracked/
  renamed/deleted paths, snapshot representation, shallow/truncated/unavailable states,
  and historical co-change stored and labeled separately from structural dependency;
- Phase 4 one compact operations contract for overview, code context, project state,
  change context, blast radius, decisions, and coverage, exposed through API, Odin CLI,
  and MCP. Typed project-state routing requires an explicit project scope; project chat
  answers current Git questions from live repository state, while generated project
  answers and MCP payloads remove internal retrieval handles;
- Phase 5 ADR/MADR and explicit-marker extraction, exact source hashes and line spans,
  explicit decision-commit extraction, user-confirmed idempotent decisions, governed-path
  staleness, dismissal tombstones, review-gated relationships, and confirmed supersession;
- Phase 6 LCOV ingestion with per-file coverage kept separate from per-test mappings,
  snapshot/commit identity, exact changed-line intersection, stale and missing states,
  ambiguous-basename refusal, deleted-path identity, and guesses kept visibly separate
  from coverage evidence;
- schema migration 30 and normalized storage for graph metrics/communities/flows, Git
  snapshots/file signals/co-change, decisions/evidence/relationships, and coverage
  snapshots/files/test maps. Optional layer failure does not deactivate structure or
  retrieval.

Focused verification completed:

- 12 Phase 1B–6 tests, including a deterministic 10,000-node graph fixture, SCC
  false-positive protection, conservative intent paraphrases, real temporary Git
  worktrees, live project-chat routing, ADR and hostile-text handling, decision lifecycle,
  LCOV path/line/staleness/no-map/known-empty cases, and idempotence;
- 42-test combined project-intelligence, MCP, graph, and project-chat regression gate;
- 32-test MCP/bridge focused gate, four existing project graph/context/chat regressions,
  Python compile validation, and desktop TypeScript validation;
- isolated CML run: 593 files, 10,037 graph nodes, 15 communities, two cycle groups,
  nine flow candidates, 43.34 seconds, and project chat with six authoritative citations
  and no partial failure;
- isolated Smart Traffic AI run: 83 files and healthy overview/Git/change-context layers;
  its missing initial metric publication exposed the lazy-publication defect fixed in
  this tranche, and a targeted rerun built 533 graph nodes and six communities;
- targeted RepoWise discovery/structure/metrics run: 35,362 nodes, 26 communities,
  seven cycle groups, one bounded flow candidate, and 60.67 seconds without executing
  repository code;
- rendered-browser verification of overview disclosure, fresh/changed-state messaging,
  centrality/community explanations, bounded map counts, node selection, backed file and
  line detail, inbound connections, detail closing, and zero final console errors.

The local generation model remains an external unavailable dependency: its model
verification check still fails. Deterministic overview, retrieval, typed live-state chat,
graph, decisions, and coverage workflows are verified without it; no claim is made that
optional model-written prose is operational until the configured model itself passes
runtime verification.

## 17. Stabilization and release checkpoint — 2026-08-01

The previously unavailable model dependency is now verified. The user-supplied
`Qwen3-4B-Q4_K_M.gguf` was loaded directly from its existing path, without copying or
modifying it, through Odin's packaged llama.cpp runtime. CUDA activation succeeded and
the runtime was stopped after each isolated verification.

Implemented after the Phase 6 checkpoint:

- optional overview, graph metrics, Git intelligence, decision refresh, and LCOV import
  now run as snapshot-bound, retryable, cancellable jobs with stable deduplication keys;
- project activation publishes the searchable structure/retrieval snapshot before
  optional layers, so expensive interpretation cannot hold the usable index hostage;
- user-requested local overview wording has high queue priority, while automatic graph,
  Git, and decision refreshes remain lower-priority background work;
- overview generation consumes a bounded structured-fact packet and JSON contract. The
  stored prose must cite active fact IDs and/or active evidence IDs; invented facts,
  foreign evidence, malformed JSON, and internal retrieval handles are rejected;
- deterministic overview facts remain authoritative and available when the model is
  missing, blocked, cancelled, or fails;
- current-work operations recalculate the live Git worktree, HEAD, branch, and indexed
  relation at request time while retaining bounded cached history signals;
- legacy or partially migrated databases skip unavailable optional tables instead of
  failing core indexing or the existing graph projection;
- Project details now provide one progressive-disclosure area for Current work,
  Decisions, and Test impact, plus an explicit local-wording action. Unknown coverage is
  shown as unknown rather than replaced with a guess.

Verified behavior and scale:

- real isolated CML indexing produced 593 eligible files, 9,201 symbols, 18,709
  relationships, 235 routes, and four workspaces for the structured overview packet;
- Qwen generated a two-sentence CML synopsis on CUDA in 13.42 seconds, citing eight
  structured fact IDs and one active README evidence ID;
- deterministic graph computation passed over 10,000 nodes and Git-history parsing
  passed over 5,000 commits;
- the explicit 50,000-file discovery gate passed with 68.3 MiB peak traced memory and
  116.889 seconds of measured discovery time on this Windows machine;
- focused intelligence, scheduler, model-contract, legacy-schema, bridge, and project
  regression gates passed, including job coalescing and scheduler completion;
- the production desktop build and TypeScript checks passed; all 166 Electron behavior
  tests passed;
- the full Playwright suite passed 18 of 18 tests. The project flow personally exercised
  Current work, Decisions, Test impact, graph navigation and return, settings, focus, and
  console cleanliness; the rendered compact layout was also visually inspected;
- the backend gate passed 986 tests, three subtests, and one expected skip after excluding
  one assertion whose tracked OCR README is already deleted in the user's worktree. That
  unrelated deletion was deliberately not restored or overwritten.

The implementation from Phase 1B through Phase 6 is therefore operational with both the
deterministic fallback and the supplied local model. The remaining failed all-files gate
is not a project-intelligence behavior failure: it is the pre-existing tracked deletion
of `backend/bin/ocr/README.md` in the shared dirty worktree.
