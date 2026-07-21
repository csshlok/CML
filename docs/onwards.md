In simple terms: Vault’s memory system is becoming much more efficient, but we have not yet proved that it improves accuracy on broad, real-world conversations.

## Atomic-memory v8 production wiring and compiler replay (2026-07-21)

The v7 diagnosis was correct that the lossless compiler was only exercised by offline
benchmark code. That disconnect is now closed at ingestion. Production chat-session sync
continues to write the compact `temporal_facts` semantic ledger and now also regenerates a
separate atomic tier:

- `atomic_memory_facts` stores lossless and deterministic semantic atoms with exact message,
  speaker, session, citation, source-hash, quantity, and compiler-version provenance;
- `atomic_memory_source_units` records every bounded unit as either `facts_extracted` or
  `processed_no_fact`;
- `atomic_memory_session_state` makes legacy backfill and compiler upgrades resumable;
- source edits retract superseded derived rows, repeated sync is idempotent, and loaders are
  constrained to retrieval-authorized session IDs;
- the existing temporal table is not filled with raw atoms, avoiding the suggestion/noise
  regression that the earlier diagnostics exposed.

Compiler v8 also adds two conservative, question-independent semantics. Explicit user count
assertions such as “I watched three amateur comedians” are typed as closed cardinalities with
a normalized category. An explicit counter snapshot followed by unambiguous singular increment
events can materialize a derived current total while retaining the complete supporting fact-ID
chain. No benchmark question labels or routing vocabulary were added.

The full backend suite passed `647 passed, 2 skipped`. CUDA preflight passed on the NVIDIA
GeForce RTX 3060 Laptop GPU; the subsequent forced coverage replay was deterministic and made
zero reader or judge calls. Results remained:

| Frozen development set | v7 safe activation | v8 safe activation | False-safe | Source coverage |
| --- | ---: | ---: | ---: | ---: |
| Representative 200 | 4/200 (2.0%) | 4/200 (2.0%) | 0 | 100% |
| Former-final 200 | 5/200 (2.5%) | 5/200 (2.5%) | 0 | 100% |

Four packets changed in each set; one representative reader packet changed and none changed in
the former-final set. The readiness decision therefore remains **NO-GO**, solely because both
sets remain below the preregistered 10% activation threshold. The result means the new write
path is production-wired and regression-safe, but the frozen corpus contains too few newly
closed chains for these rules to move aggregate benchmark activation. The next compiler work
should focus on provenance-safe entity membership and cross-utterance aliases (for example a
named physician belonging to a doctor category), not broader regex routing or another paid run.

## Atomic-memory v9 entity membership and real-vault diagnostics (2026-07-21)

The next compiler layer now records explicit, provenance-backed entity membership without
claiming global closure. Titles such as `Dr.` and explicit appositions such as “Morgan Hale is
my physician” produce canonical doctor membership facts. The question plan exposes a small,
general alias set (doctor/physician/clinician, lawyer/attorney, therapist/counselor, and
professor/academic). Each membership is marked `closed_world_category=false`; it can improve
candidate recall but cannot by itself activate a distinct-count answer.

The new `scripts/backend/inspect_atomic_memory_coverage.py` command performs an integrity check
and SQLite backup before optional backfill, then reports content-free metrics: indexed sessions,
user-turn fact yield, source-unit terminal coverage, closed cardinality count, counter snapshots,
counter increments, and materialized progressive totals. Inspection found no usable local
production corpus: the configured DB contains one empty benchmark vault, and the packaged
pre-vault DB contains zero vaults, sessions, and messages. Consequently there is no honest
real-user activation or fact-yield number to report yet.

Compiler v9 forced a cache-invalidated, model-free replay of both frozen 200-question sets.
Eight packets changed in each set. The representative set had one reader-impact packet; the
former-final set had none. Activation remained 4/200 and 5/200, all 9 activated operations were
correct, false-safe count remained zero, and source-unit coverage remained 100%. Readiness is
still **NO-GO** because activation is below 10%. This was committed as infrastructure and
candidate-recall work with the failed promotion gate explicitly retained, not as a benchmark
promotion.

## Where we are now

We have proven three useful things:

1. Vault can retrieve relevant conversational evidence reasonably well.
2. For facts that change over time, Vault can create much smaller context without losing accuracy.
3. Vault now knows when it should avoid using structured memory instead of forcing irrelevant facts into an answer.

The current public LoCoMo baseline remains:

- Retrieval recall: 76.06%
- Kimi accuracy: 66.75%
- GPT-5.4 accuracy: 63.96%
- Average reader prompt: about 650 tokens
- Full evaluation cost: about $1.74

That is still the benchmark result to treat as authoritative.

## The run before the last run

We tested the new temporal-memory path across all 1,540 LoCoMo questions.

The initial headline looked slightly better:

- F1 increased from 52.59% to 53.06%
- Kimi increased by one correct answer
- GPT-5.4 increased by six correct answers

But that apparent improvement was misleading.

The new temporal system only activated on 34 questions. The other 1,506 questions used the old path, but Kimi regenerated their answers anyway. Because model responses vary between runs, 577 supposedly unchanged answers came out differently.

When we isolated the 34 questions actually affected by the feature, the new path was worse:

| Activated questions | Old path | New path |
|---|---:|---:|
| F1 | 60.08% | 54.19% |
| Kimi accuracy | 76.47% | 61.76% |
| GPT-5.4 accuracy | 64.71% | 61.76% |

The main problem was that questions containing words such as “favorite” were incorrectly treated as preference summaries.

For example:

- “What was her favorite childhood book?” is asking for one historical fact.
- “What does she generally prefer to read?” may require combining preferences across multiple conversations.

Vault was treating both as the second kind. It then added about 659 characters of loosely related preference information, distracting the reader.

That version was rejected.

The run also ended with seven truncated answers. We fixed the benchmark runner so it now retries them immediately and refuses to produce a final report if truncation remains.

## The last run

We tightened the routing rules:

- A word such as “favorite” no longer activates preference synthesis by itself.
- Named-person questions must clearly request an overall or general preference.
- If Vault cannot find preference facts matching the requested topic, it now falls back instead of injecting unrelated information.
- The same routing and topic rules now govern the ordinary chat/Bridge memory packet, not only the typed reducer.
- Unchanged fallback answers and judgments are reused rather than regenerated.

We then reran exactly the same 34-question activation set.

Results:

- All 34 former false activations correctly fell back.
- F1 stayed exactly 60.08%.
- Kimi stayed at 26/34.
- GPT-5.4 stayed at 22/34.
- No API calls were needed.
- Cost was $0.

This means we successfully removed the regression.

A deterministic production-bundle regression now also verifies the desktop packet boundary directly: a bounded question such as “What was Melanie's favorite childhood book?” receives no temporal preference memory, even when the ledger contains unrelated preferences across multiple sessions. Matching bounded facts remain available through ordinary cited retrieval rather than structured preference memory.

However, it does not mean structured preference synthesis improved anything. The corrected system activated on zero of those questions. It passed by correctly staying out of the way.

## The positive result we do have

Our dedicated evolving-memory benchmark tested 40 controlled questions:

- 10 current-preference questions
- 10 preference-history questions
- 10 state-history questions
- 10 relative-date action questions

Both the old and production paths scored 40/40, but the production path was much smaller:

| Metric | Old path | Production path |
|---|---:|---:|
| Accuracy | 100% | 100% |
| Mean prompt tokens | 775 | 181 |
| P95 prompt tokens | 788 | 276 |
| Mean context size | 1,907 characters | 404 characters |
| Estimated uncached reader cost | $0.0332 | $0.0101 |

So, for explicit evolving facts, Vault reduced reader prompt tokens by 76.6% and estimated uncached reader cost by 69.7% without losing accuracy.

That is meaningful, but it is a controlled 40-question test—not proof of broad conversational-memory performance.

## What happens next

We should not immediately run another full 1,540-question LoCoMo evaluation.

First, we need a fresh benchmark containing questions that genuinely require structured memory, such as:

- “What breakfast does this person generally prefer?”
- “How have their travel preferences changed?”
- “What pattern appears across their purchases?”
- “What do they normally avoid?”
- “How did their normal workflow evolve across several months?”

These answers should be distributed across multiple sessions rather than stated once directly.

Then we will run a paired test:

1. Freeze the questions and expected evidence before changing the implementation.
2. Run the normal retrieval path.
3. Run the structured-memory path only where the router activates.
4. Reuse unchanged answers and judgments.
5. Measure wins, losses, tokens, latency, and cost only on genuinely changed questions.
6. Reject the feature if it harms previously correct answers.

Only after that focused test is neutral or positive should we pay for another full LoCoMo run.

## Our benchmarking goal

The goal is not simply to make the headline accuracy number increase.

We want to prove that Vault can:

- preserve or improve answer accuracy;
- use substantially fewer tokens;
- correctly handle facts that change over time;
- combine information across conversations when necessary;
- avoid injecting structured memory when ordinary retrieval is sufficient;
- preserve exact citations and speaker provenance;
- remain reliable as the vault grows;
- produce results that are reproducible rather than caused by model randomness.

The next major success would be:

> On a fresh set of real multi-session synthesis questions, structured memory produces more correct answers than ordinary retrieval, causes no meaningful regression on previously correct answers, and reduces the context required per answer.

We have already proved the efficiency side on controlled evolving facts. The remaining challenge is proving a genuine accuracy improvement on broader, realistic multi-session memory.

## Write-time fact coverage diagnostic

We tested the theory that Vault is leaving benchmark accuracy unused because it performs extraction and synthesis together at query time, while systems such as Mem0 hand the reader pre-extracted facts.

The diagnostic held retrieval fixed. For every LongMemEval question, it used the same top-10 sessions from the published claim-first 10K run, then replaced the query-time claim packet with the facts produced by Vault's current production structured-claim extractor. This isolates representation coverage from retrieval quality and costs no model or judge calls.

Results on all 500 questions, including 470 answerable questions:

| Metric | Current write-time facts | Claim-first baseline |
|---|---:|---:|
| Mean context tokens | 2,391 | 8,604 |
| Relative context size | 27.8% | 100% |
| Answerable questions with any fact from a gold session | 436/470 (92.8%) | n/a |
| Answerable questions with facts from every gold session | 407/470 (86.6%) | n/a |
| Gold answer literally present in extracted gold-session facts | 27/470 (5.7%) | n/a |

The first coverage number is misleadingly generous: it means that the extractor found some fact somewhere in the gold session, not that it retained the answer-bearing fact. Across the retrieved contexts, 14,006 of 18,264 extracted records (76.7%) were assistant suggestions. Representative missed evidence included a user's study-abroad university, a purchased light bulb, and clothing pickups or returns; the extractor retained unrelated suggestions from the same sessions instead.

The clearest family-level failures were:

- single-session assistant: 0/56 literal answers retained, and only half of gold sessions emitted any fact;
- single-session preference: 0/30 literal answers retained;
- single-session user: 8/64 literal answers retained;
- the existing 97 claim-first failures: only 3 had the literal gold answer in current structured facts.

Literal containment understates coverage for derived answers such as counts and temporal calculations, so it is not an accuracy score. It is still a decisive rejection signal for a facts-only reader arm because even the direct single-session families lose nearly all answer-bearing text.

Conclusion: the architectural theory is directionally right, but the capability is not currently sitting unused inside Vault. Vault's existing write-time fact representation is 72.2% smaller, but it is too narrow and too suggestion-heavy to substitute for claim-first evidence. A paid reader/judge run on this representation would mainly measure missing evidence rather than reduced synthesis burden, so we did not run one.

The opportunity requires a broader write-time memory compiler first: atomic user and assistant facts, speaker and date attribution, deduplication, supersession, and immutable source citations. Once that compiler passes an evidence-coverage gate, the correct benchmark is a frozen three-arm comparison: current claim-first, facts-only, and facts plus bounded raw evidence, all using the same retrieval results, reader, judges, and prompt budget.

The reproducible diagnostic is `scripts/backend/analyze_longmemeval_write_time_facts.py`; its local full-row report is `.tmp/vault-odin-memory-benchmark/longmemeval-write-time-fact-coverage.json`.

## Frozen atomic-memory pilot

We implemented and tested the next write-time-memory step without changing production behavior.

The experiment froze 60 LongMemEval questions before extraction: 10 from each official question family, half development and half held-out evaluation. Within each family it included up to five dual-judge claim-first failures and filled the remainder with dual-judge-correct controls. All questions were answerable and had a retrieval hit. Retrieval results, reader, judges, and the saved claim-first baseline were held constant.

The compiler has two intended tiers:

1. a lossless deterministic atomic envelope that persists exact user and assistant source units, table rows, list items, speaker, session, turn, and observation date;
2. optional semantically normalized facts with predicates, quantities, event dates, qualifiers, and supersession keys.

The semantic extraction services were not suitable for the complete pilot. Kimi required roughly two minutes for the first two-session batch, and twelve concurrent requests stalled through the timeout window. GPT-4o-mini took roughly ninety seconds for a trial batch and returned only one validated fact across two sessions. Those attempts were stopped and kept in model-specific caches that were not used by the evaluated arms.

The lossless tier was then materialized for all 600 retrieved sessions. Exact-source validation rejected invented citations, and the compiler persisted both user and assistant evidence instead of classifying all assistant content as suggestions.

### Evidence coverage gate

The frozen evidence labels contained 94 required source spans across the 60 questions.

| Metric | Result |
|---|---:|
| Required evidence spans covered | 93/94 (98.94%) |
| Questions with every required span covered | 59/60 (98.33%) |
| Invalid persisted citations | 0 |
| Mean candidate atomic units per question | 1,061.9 |

This passed the preregistered 90% evidence-recall gate. The only incomplete question was a six-span development temporal question for which five spans survived.

### Held-out three-arm result

The 30 held-out questions were evaluated with the saved Kimi reader and strict Kimi plus GPT-5.4 dual judges.

| Arm | Dual-judge correct | Accuracy | Mean reader prompt tokens | Wins | Losses |
|---|---:|---:|---:|---:|---:|
| Claim-first control | 20/30 | 66.67% | 8,126 | - | - |
| Lossless atomic facts only | 23/30 | 76.67% | 8,739 | 4 | 1 |
| Atomic facts plus bounded raw evidence | 20/30 | 66.67% | 8,796 | 3 | 3 |

Facts-only improved the paired result by three net questions, or 10 percentage points on this deliberately failure-enriched pilot. Its four wins were one knowledge-update question, one previously content-filtered user question, and two temporal questions. Its one loss was a personalized-preference question. Temporal reasoning improved from 3/5 to 5/5 and single-session user from 4/5 to 5/5, while preference accuracy fell from 3/5 to 2/5.

The improvement came from cleaner source-unit presentation and answer discipline, not token compression. In several wins, claim-first supplied the right evidence but the reader began with an incorrect number and later corrected itself; the strict judge rejected the contradictory response. The atomic packet led directly to the correct latest value or date calculation. Facts-only used 7.5% more reader prompt tokens than the control.

The hybrid arm did not help. Duplicating atomic and raw evidence consumed more tokens, lost preference qualifiers, and caused one provider rejection. Its three wins were exactly canceled by three losses.

This is a positive exploratory signal, not a promotable headline result. Only five questions changed correctness in the facts-only comparison (four wins and one loss); the two-sided exact McNemar p-value is 0.375, so the paired sample is too small for a confident broad claim. The evaluation split was intentionally failure-enriched: facts-only recovered 4/10 claim-first failures and regressed 1/20 controls. It also tests the lossless atomic tier, not the unfinished semantic normalization tier envisioned in the original Mem0 comparison.

The next experiment should preserve the successful facts-only packet, add question-independent semantic normalization asynchronously behind it, and improve preference packing without duplicating raw evidence. That version should be tested on a larger frozen held-out set before any full-500 or production rollout.

Reproducible code and local artifacts:

- `backend/app/core/atomic_memory.py`
- `scripts/backend/run_longmemeval_atomic_ablation.py`
- `.tmp/vault-odin-memory-benchmark/atomic-memory-v1/manifest.json`
- `.tmp/vault-odin-memory-benchmark/atomic-memory-v1/coverage.json`
- `.tmp/vault-odin-memory-benchmark/atomic-memory-v1/ablation-report.json`

## Question-only atomic-memory readiness result

The earlier representative and nominal final 200-question manifests have both now been
used during development. Neither is an untouched final holdout anymore. The nominal
final run was stopped before reader and judge calls when its coverage gate failed, but
its evidence labels and question-level diagnostics still make it development data.

Atomic-memory v7 removes the official LongMemEval question family from routing. The
planner sees only the raw question and retrieved-session count, produces a general
operation contract (current state, state comparison, aggregate/list, distinct count,
numeric reduction, temporal difference, or event order), and falls back to claim-first
unless the selected facts prove every required evidence slot. Benchmark question types
remain reporting fields only. The claim-first ablation path likewise receives no
official type label.

Write-time compilation now retains the exact lossless source facts and augments them
with deterministic semantic claims, normalized number words and quantities, speaker,
dates, state/supersession metadata, and immutable citations. Closed-world counts and
lists cannot activate without an explicit closed-world category attestation. A latest
state must itself cover the requested concept; an older matching fact cannot make a
generic later statement appear complete. Every source unit also receives a terminal
compiler outcome (`facts_extracted` or `processed_no_fact`) and immutable content hash.

The v7 numeric compiler fixes grouped-number parsing (`$1,000` is no longer split into
`1` and `0`), filters operands by unit family and grammatical count subject, deduplicates
repeated event mentions, and requires normalized speaker/state identities. Calendar
phrases such as `last Saturday` no longer masquerade as latest-event requests. Offline
evaluation separately checks deterministic results against stored references; that
check is reporting-only and never enters production routing.

The latest closure pass distinguishes explicit cardinality assertions from inferred
list counts, rejects progressive counters when later related facts exist, and keeps
genuine lists behind the closed-world category gate. Current-state selection now stays
inside the requested concept and supersession chain instead of allowing a later loosely
related state to shadow it. Capacity units such as gallons/liters are typed separately
from item counts, preventing container size from being added as inventory.

A frozen 32-case, domain-diverse paraphrase suite plus 128 deterministic metamorphic
variants checks routing behavior without any LongMemEval labels. The focused atomic
implementation and runner suites pass 32/32 tests; the complete backend suite passes
644 tests with 2 conditional skips.
Both 200-question sets were then replayed offline with no reader or judge API calls:

| Metric | Representative 200 | Former final 200 |
|---|---:|---:|
| Stored evidence recall | 98.18% | 98.47% |
| Atomic candidate questions | 119 | 117 |
| Reference-verified atomic activations | 4 (2.0%) | 5 (2.5%) |
| False-safe activations | 0 | 0 |
| Activated-question completeness | 100% | 100% |
| Deterministic result correctness | 4/4 | 5/5 |
| Source-unit compiler coverage | 100% | 100% |
| Temporal anchor recall | 98.11% | 100% |
| Direct-fact recall | 100% | 100% |
| Expected mean prompt tokens | 8,283.92 vs 8,290.75 | 8,303.97 vs 8,320.81 |

The safety gates pass, but the preregistered 10% activation/usefulness gate fails on
both sets. The resulting decision is **no-go**: a paid reader/judge run would mostly
measure the unchanged claim-first baseline and could not establish that atomic memory
improves accuracy. The old start wrapper is therefore guarded and cannot accidentally
launch that consumed run.

### Development sequence from v4 through v7

The final numbers hide several useful rejected iterations:

| Version/iteration | Representative 200 | Former-final 200 | Decision |
|---|---:|---:|---|
| v4 baseline | 3 safe activations | 2 safe activations | Starting point |
| v5 safety/compiler pass | 4, zero false-safe | 4, zero false-safe | Accepted development baseline |
| Early v6 explicit-cardinality attempt | 10, 3 false-safe | 8, 3 false-safe | Rejected |
| Tightened v6 closure/history checks | 4, zero false-safe | 4, zero false-safe | Safety restored |
| v7 state-chain and unit-typing pass | 4, zero false-safe | 5, zero false-safe | Current result; still no-go |

The early v6 activation increase was not real progress. A single local count could be
treated as the total for a broader time range or multiple sessions. Examples included
an earlier project count being used for a cumulative “since starting classes” question
and one event count standing in for all events. The stricter contract now requires a
single unconflicted explicit cardinality, full discriminating-question coverage, and no
later related fact that could change the total. Genuine lists still require explicit
closed-world category coverage.

The state pass fixed a different general problem. The old contract could choose the
latest loosely related state globally, allowing a later reading-habit statement to
shadow the actual current book. v7 chooses the latest fact inside the requested concept
and supersession chain. This safely added the current Kansas City Masterpiece BBQ-sauce
answer on the former-final set while continuing to abstain on plans or unrelated later
states.

A forced full replay then caught a cache and unit interaction that impact-only replay
could not reveal. Cached v6 facts still represented `20-gallon` as an untyped number,
so aquarium capacity values were added as fish counts and produced 50 instead of 17.
Gallons and liters are now typed as capacity, the fact-cache schema advanced to v7,
and the clean replay returns to zero false-safe operations. Vault still abstains on that
question because “a small pleco” has not yet been compiled into an explicit count of
one; safe incompleteness is preferable to an inferred benchmark answer.

### Current blockers and engineering challenges

1. **Implicit entities and cardinality.** Articles and singular noun phrases must become
   cited entities without turning arbitrary mentions, recommendations, or hypotheticals
   into owned/experienced items.
2. **Closed-world category closure.** “Different doctors,” “events,” “purchases,” and
   similar questions need normalized category membership plus proof that every relevant
   source unit was considered. Lexical overlap alone is insufficient.
3. **Progressive totals.** Values such as 4 projects followed by one new project are
   histories, not independent addends and not a safe latest total unless their identity
   and update semantics are explicit.
4. **Repeated-event identity.** The same event may be described more than once with
   different wording, dates, or quantities. Deduplication must preserve distinct events
   while merging true repetitions.
5. **State and supersession breadth.** The current deterministic patterns cover several
   common forms, but real users express ownership, location, status, frequency, and
   preference changes much more broadly.
6. **Coreference and semantic aliases.** Questions often name a category absent from the
   fact text (`doctors` versus `Dr. Lee`, or `fish` versus species names). Normalization
   must improve recall without losing exact speaker/source provenance.
7. **Evaluation-set exhaustion.** Both 200-question sets are development data. Only seven
   eligible untouched LongMemEval questions remain under the current protocol, so a
   meaningful final claim needs a new preregistered corpus or benchmark split.
8. **Activation, not token budget, is the immediate gate.** Evidence recall, source-unit
   coverage, activated correctness, false-safe count, and prompt budget all pass. Safe
   activation remains only 2.0% and 2.5% against the unchanged 10% threshold.

The next implementation should therefore normalize category-linked entities, event
identity, progressive counters, and supersession at ingestion time. It must not add
benchmark-specific vocabulary or lower the safety threshold. Development should use
impact-only offline replays, followed by one cache-invalidated full replay when fact
semantics change. A reader/dual-judge run becomes justified only after both development
sets reach at least 10% activation with zero false-safe operations.

The bottleneck is now precise: source-unit processing is fully accounted for, but the
write-time semantic layer cannot yet prove complete category sets or state chains often
enough. The next implementation should add explicit category/state closure during
ingestion, then require at least
10% safe activation with zero false-safes on both development sets. Only after that
passes should a genuinely new corpus or untouched benchmark split be frozen for final
reader/judge evaluation. LongMemEval itself has only seven eligible untouched questions
under the existing selection rules, which is insufficient for a new 200-question final.

Reproducible readiness commands:

```powershell
.\.venv\Scripts\python.exe scripts/backend/check_atomic_memory_readiness.py
.\scripts\backend\monitor-longmemeval-atomic-large.ps1
.\scripts\backend\run-atomic-development-cycle.ps1 -ChangedComponent quantity
```

The readiness artifact is
`.tmp/vault-odin-memory-benchmark/atomic-memory-readiness.json`. Coverage stages, reader answers, and
judge decisions now use content fingerprints. Repeated identical impact replays return
from the stage cache, while changed prompts, models, token budgets, or evidence packets
invalidate only their dependent stage. Packet-diff reports identify the exact questions
whose reader inputs changed.

Local model-backed benchmarks are CUDA-fail-closed. The project venv uses official
PyTorch `2.12.0+cu130` on the NVIDIA RTX 3060 Laptop GPU; a real matrix-operation smoke
test is required before local model work. Deterministic JSON/contract coverage remains
CPU work because it has no neural tensor workload. Setup and verification:

```powershell
.\scripts\backend\setup-benchmark-cuda.ps1
.\.venv\Scripts\python.exe scripts/backend/check_cuda_runtime.py
```

## July 22 local write-time semantic-ingestion pilot

Vault now has an opt-in implementation of the Mem0-style architectural experiment.
After deterministic chat-memory sync, a low-priority, cancellable
`atomic_semantic_enrichment` job may ask the configured local model to extract atomic
facts. The path is disabled by default and hard-rejects non-loopback model URLs.
Validated model facts are stored separately with provider/model/extractor provenance,
exact turn citations, source hashes, invalid-fact diagnostics, and current/stale state.
Source edits stale semantic output; deterministic memory remains available if local
enrichment is disabled, delayed, or fails.

Long conversations are split into bounded overlapping windows while citations are
translated back to original turn indexes and validated against the unchanged full
session. llama.cpp schema-constrained JSON is used, with one bounded retry and a narrow
repair for Qwen's non-standard escaped apostrophe. Deterministic and semantic facts are
deduplicated before progressive counters are materialized. Content-free coverage now
reports semantic attempted/current, stale/failed, valid-fact, and invalid-fact counts.

The first CUDA pilot used Qwen3 4B Q4_K_M on the RTX 3060 Laptop GPU and frozen
LongMemEval question `gpt4_f2262a51`, "How many different doctors did I visit?" Its
three gold sessions contain about 45,477 characters. Fully enriching the verbose
assistant responses was projected at roughly fifteen minutes, so that diagnostic was
stopped. A user-turn-only diagnostic completed in 343.40 seconds and produced 36
provenance-valid semantic facts. Seven overlap duplicates were removed and one fact was
rejected for a non-exact excerpt. Per-session times were 47.64, 134.48, and 161.28
seconds.

The result is mixed. The model produced concise facts such as `visited_doctor -> Dr.
Lee`, `visited_specialist -> Dr. Patel`, and a primary-care relationship involving Dr.
Smith. Packing changed from 139 deterministic facts / 8,341 estimated tokens to 107
combined facts / 8,498 tokens. But Qwen3 4B emitted zero explicit `entity_category`
qualifiers, occasionally confused a prescription relationship with a completed visit,
and did not prove closed-world category coverage. The distinct-count contract remained
unsafe in both arms. This pilot establishes neither an accuracy improvement nor a
reason to launch a large reader/judge run.

The architecture remains plausible, but this 4B extractor is not yet reliable or
economical enough to promote. Next development should improve compact category and
coreference output on a small question-independent fixture, measure false action/role
conversions, compare a stronger local model if it fits the 6 GB GPU, and require an
offline activation gain with zero false-safe counts before reader evaluation. The
reproducible diagnostic is `scripts/backend/run_local_semantic_ingestion_pilot.py`; its
result is `.tmp/vault-odin-memory-benchmark/atomic-memory-v1/local-semantic-pilot-gpt4_f2262a51.json`.
