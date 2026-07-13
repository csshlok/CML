# PDF Ingestion Work Path

Last updated: 2026-06-12

## Goal

Public V1 PDF ingestion must work across three common document shapes:

1. text-based prose PDFs
2. scanned/image-only PDFs
3. table-heavy PDFs

The ingestion pipeline should preserve enough structure for retrieval and memory extraction without breaking the current `sources -> source_pages -> source_chunks` model.

## Decisions

- Keep direct text extraction as the first path for readable PDFs.
- Keep OCR as the fallback for scanned/image-only PDFs; OCR is not being replaced.
- Add table-aware extraction for table-heavy PDFs.
- Store extracted table structure as normalized JSON.
- Generate canonical text from extracted tables for embeddings, retrieval, and memory extraction.
- Prefer a Camelot-first prototype for text-based table extraction in the packaged Python stack.
- Treat Tabula/Java as a secondary fallback only if Camelot coverage is not good enough to justify staying Python-only.
- Do not train experts on raw JSON blobs; train on canonical text generated from structured tables while keeping the JSON for exact grounding.

## Target Data Shape

Each table-capable PDF source should preserve:

- source record
- page records
- standard extracted page text
- structured table records
- canonical table text derived from structured tables
- citations back to source/page/table

Suggested new logical records:

- `source_tables`
- `source_table_cells` or compact `table_json`
- `source_table_text`

The exact schema can be finalized during implementation, but the pipeline must support both:

- structured row/column lookup
- semantic retrieval over flattened canonical text

## Workstreams

### 1. Table Detection And Extraction

Deliverables:

- Detect pages likely to contain tables.
- Run a table extractor on text-based table pages.
- Track extraction confidence and parser mode.
- Fail gracefully when a table cannot be reconstructed reliably.

Preferred first tool:

- Camelot

Fallback to evaluate only if needed:

- tabula-py / tabula-java

Primary repo areas:

- `backend/app/core/extraction.py`
- `backend/app/core/quarantine.py`
- contributor dependency manifests under `requirements/`

Exit criteria:

- CML can extract structured tables from representative text-based PDFs without regressing normal prose PDF ingestion.

### 2. OCR And Table Interop

Deliverables:

- Preserve the existing OCR fallback for scanned PDFs.
- Define how OCR-derived pages are re-attempted for table extraction, if at all.
- Mark OCR-derived table confidence separately from text-native table confidence.

Primary repo areas:

- `backend/app/core/extraction.py`
- `backend/app/core/ocr.py`

Exit criteria:

- Scanned PDFs still ingest correctly, and table-aware logic does not incorrectly replace the OCR fallback path.

### 3. Structured Table Storage

Deliverables:

- Persist normalized table JSON per source/page/table index.
- Preserve headers, rows, and basic metadata such as page number and table title/region when available.
- Keep provenance links back to the parent source/page.

Primary repo areas:

- `backend/app/core/database.py`
- `backend/app/core/migrations.py`
- `backend/app/schemas.py`

Exit criteria:

- Extracted tables can be reloaded independently of page text and linked back to their source evidence.

### 4. Canonical Table Text Generation

Deliverables:

- Generate stable text from structured tables, for example:
  - table title
  - column list
  - row-wise key/value rendering
- Chunk and embed that canonical text like other source-derived content.
- Make canonical text the default expert-training representation of tables.

Primary repo areas:

- `backend/app/core/extraction.py`
- `backend/app/core/embeddings.py`
- `backend/app/core/training_dataset.py`

Exit criteria:

- Table data participates in semantic retrieval without forcing models to parse raw JSON.

### 5. Retrieval And Citation Integration

Deliverables:

- Allow semantic retrieval to match table-derived canonical text.
- Preserve citations back to source/page/table.
- Add exact lookup helpers later if needed, but V1 must at least return grounded table evidence cleanly.

Primary repo areas:

- `backend/app/api/routes/search.py`
- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/bridge.py`

Exit criteria:

- Queries against values in tables can return grounded evidence without relying only on flattened page prose.

### 6. Memory And Expert Integration

Deliverables:

- Let distilled-memory extraction read canonical table text.
- Let cluster profiles and context packets include canonical table text when relevant.
- Keep structured JSON available for exact grounding and future tool-style access.

Primary repo areas:

- `backend/app/core/background_jobs.py`
- future memory extraction module
- `backend/app/core/training_dataset.py`

Exit criteria:

- Context packets can use table-derived content while citing the original table evidence.

### 7. Evaluation

Deliverables:

- Build a table-heavy PDF fixture set.
- Measure:
  - extraction coverage
  - header/row fidelity
  - retrieval usefulness
  - expert-dataset usefulness
- Compare baseline prose-only extraction versus table-aware extraction.

Primary repo areas:

- `backend/tests/`
- `scripts/backend/`
- new report doc under `docs/`

Exit criteria:

- CML can justify the added ingestion complexity with measurable gains on real table-heavy PDFs.

## Recommended Implementation Order

1. Table detection and Camelot prototype
2. Structured table storage schema
3. Canonical table text generation
4. Retrieval integration
5. Memory and expert integration
6. OCR/table interop refinement
7. Evaluation and release proof

## Release Rule

Do not claim strong PDF ingestion for public V1 until:

- prose PDFs still ingest correctly,
- scanned PDFs still rely on OCR correctly,
- table-heavy PDFs can preserve structure,
- canonical table text is searchable and trainable,
- and evaluation shows clear gains over prose-only extraction.
