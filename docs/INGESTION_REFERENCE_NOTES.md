# Ingestion Reference Notes

Source reviewed: `t:\csshl\m2-res_480p.mp4`

Date reviewed: 2026-05-27

## What The Video Shows

The video presents a personal memory app that solves scattered information across files, images, notes, links, apps, and tasks.

Observed capture surfaces:

- Files.
- Images.
- Notes.
- Links.
- Web pages and articles.
- Research papers.
- Design/reference assets.
- Tasks and task lists.
- GitHub/repository-related pages.
- Company/business pages such as Crunchbase.
- App-connected content from services the user already uses.
- Quick command capture through a shortcut.

The command palette shown in the video includes:

- Create summary.
- Add file.
- Add note.

## How The Data Appears To Be Stored

The video does not reveal actual backend storage internals. The visible product model appears to store everything as normalized memory cards.

Each stored item appears to have:

- Type, such as `LINK`, `FILE`, `NOTE`, or `TASK`.
- Title.
- Preview or extracted body text.
- Optional image/thumbnail.
- Tags.
- Source-specific metadata, such as link URL, file identity, or task date.
- Generated summary.

The app shows all items in one place after ingestion, suggesting a unified source table/object model rather than separate user-facing silos for notes, files, links, and tasks.

## Organization Model

The visible organization approach is automatic tagging and summarization.

Observed examples of automatic tags:

- `TRANSFORMER`
- `SELF-ATTENTION`
- `NLP`
- `MACHINE LEARNING`
- `RESEARCH`
- `NEURAL NETWORKS`
- `ENCODER`
- `PARALLELIZATION`

Other visible tags include:

- `LINK`
- `REPOSITORY`
- `WORK`
- `GIT`
- `ARTICLE`
- `AI`
- `TECH`
- `STARTUPS`
- `ENTREPRENEURSHIP`
- `PRODUCTIVITY`

This implies a pipeline like:

1. Capture item.
2. Detect item type.
3. Extract readable content.
4. Generate a summary.
5. Generate tags.
6. Store the original source reference plus extracted text.
7. Make the item searchable across the whole memory space.

## Implications For CML

CML should keep a normalized source model and avoid creating separate storage systems per source type.

Recommended V1 source fields:

- `id`
- `vault_id`
- `cluster_id`
- `source_type`
- `title`
- `original_path`
- `url`
- `raw_text`
- `extracted_text`
- `summary`
- `tags`
- `state`
- `created_at`
- `updated_at`

Near-term ingestion priorities based on the video:

- Add file.
- Add note/pasted text.
- Add link.
- Add image/screenshot.
- Add task/list item.
- Auto-summary.
- Auto-tags.

The key product lesson is that users should not think in source formats. They add anything, and the app turns it into a consistent memory object with type, preview, summary, tags, and source reference.

## CML Implementation Direction

CML should follow this product model:

- Every ingested thing is a source/memory card.
- Cluster assignment should be automatic when enough readable context exists.
- If automatic assignment is uncertain, the source still exists as a loose data point on the map.
- Loose data points should remain visible, hoverable, inspectable, and moveable into a cluster later.
- Cluster creation should be conservative and user-correctable. A first-pass local heuristic is acceptable until embeddings are available.
