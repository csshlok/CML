# Retired RAG accuracy experiments

Status: dead code retained only for audit and reproducibility.

These experiments are not production features and their executable entry points
are intentionally blocked. They must not be re-enabled without a new design, a
new answer-blind selection, and preregistered promotion gates.

## Reader-evidence packing

- First frozen local A/B: legacy `0.64`, candidate `0.62` (`-0.02`).
- Disjoint v2 A/B: legacy `0.50`, candidate `0.44` (`-0.06`).
- Later routed-reader v3.2 and v4 official promotion sets each missed the
  retention gate, so no full-500 rerun was authorized.
- Production remains on the legacy claim packer and legacy numeric semantics.

Retained audit surfaces:

- `scripts/backend/benchmark_reader_evidence_local.py`
- `scripts/backend/run-reader-evidence-local.ps1`
- `backend/tests/test_reader_evidence_local_benchmark.py`
- `backend/tests/fixtures/reader_evidence_local_ab_v2_selection.json`

## Local-Qwen fact extraction

The fixed-retrieval five-question directional run produced:

- raw evidence: `2/5` (`0.40`)
- facts only: `0/5` (`0.00`), two losses versus raw
- hybrid facts plus raw evidence: `1/5` (`0.20`), one loss versus raw
- extracted facts had a measured invalid rate of `0.261538`

This did not improve accuracy and increased reader latency. Production continues
to use the existing RAG evidence path without this extraction stage.

Retained audit surfaces:

- `scripts/backend/benchmark_fact_extraction_local.py`
- `scripts/backend/prepare_longmemeval_fact_ab.py`
- `scripts/backend/run-fact-extraction-local-ab.ps1`
- `backend/tests/test_fact_extraction_local_benchmark.py`

## Still active

The following evidence-presentation work is independent of the failed accuracy
experiments and remains active: stable evidence IDs, inline citations, source
file/page/line/symbol locators, preserved multiline code excerpts, and a compact
chat evidence packet without duplicated snippets.
