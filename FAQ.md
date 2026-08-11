# Vault FAQ

This FAQ mirrors all 74 questions currently available in **Vault -> Help** for release **0.1.14**. The in-app Help screen remains the interactive source for searchable guidance, related articles, and visual callouts.

The canonical article data lives in
[`apps/desktop/src/lib/helpContent.ts`](apps/desktop/src/lib/helpContent.ts). For
the product overview, installation, and development instructions, see the
[README](ReadME.md).

## Contents

- [Getting started](#getting-started) (4)
- [Sources & imports](#sources-and-imports) (10)
- [Clusters](#clusters) (5)
- [Search & retrieval](#search-and-retrieval) (5)
- [Chat & answers](#chat-and-answers) (7)
- [Odin projects](#odin-projects) (7)
- [Map & connections](#map-and-connections) (4)
- [Tasks & background work](#tasks-and-background-work) (4)
- [Models & OCR](#models-and-ocr) (6)
- [Storage & backups](#storage-and-backups) (6)
- [Connections & sharing](#connections-and-sharing) (5)
- [Privacy & security](#privacy-and-security) (4)
- [Troubleshooting](#troubleshooting) (7)

## Getting started

### What should I do in my first ten minutes?

Add a small set of useful sources, wait for indexing, then ask one focused question.

Vault works best when you begin with material you already understand. A small first import makes it easy to confirm that extraction, clustering, and chat citations are behaving as expected.

A source marked Ready is searchable and available to chat. Clusters and map connections may appear shortly afterward because they are derived in separate background tasks.

What to do:

1. Open Sources and add three to ten related documents or one folder.
2. Wait until each source shows Ready.
3. Open Clusters and review the suggested grouping.
4. Open Chat, choose the cluster, and ask a question whose answer you know.
5. Open at least one citation to confirm the answer is grounded in the right source.

**Where in Vault:** Sources → Add files → Clusters → Chat → choose a scope

**Related questions:** What do source statuses mean?; How do I control which sources Chat uses?; How does automatic clustering work?

### What are sources, clusters, chats, projects, and maps?

Sources are the evidence; the other views organize, retrieve, explain, or connect that evidence.

A source is one imported item. Clusters group related sources. Chat retrieves passages and writes cited answers. Odin projects add code-aware snapshots and relationships. Maps visualize connections; they do not create new evidence.

What to do:

1. Add evidence in Sources.
2. Review its organization in Clusters.
3. Ask questions in Chat with a deliberate scope.
4. Use Projects for code repositories and Map for relationships.

**Where in Vault:** Sources → Clusters → Chat; Projects for code; Map for relationships

**Related questions:** What should I do in my first ten minutes?; When should I use Search instead of Chat?; What is the difference between a folder import and an Odin project?

### Which Vault feature should I use for my task?

Use Sources to collect, Search to locate, Chat to synthesize, Clusters to organize, and Map to inspect relationships.

Choose the smallest tool that answers the question. Search is fastest for finding a known phrase or file. Chat is better for synthesis. Clusters expose themes. Map is useful only when the relationship itself matters.

What to do:

1. Need a file or phrase? Use Search.
2. Need an explanation across evidence? Use Chat.
3. Need to tidy themes? Use Clusters.
4. Need code structure? Use an Odin project.
5. Need relationship context? Use Map.

**Where in Vault:** Search / Chat / Clusters / Projects / Map

**Related questions:** What are sources, clusters, chats, projects, and maps?; When should I use Search instead of Chat?; How do I control which sources Chat uses?

### Does work continue after I close Vault?

Normal background work is durable, but fully quitting the desktop application stops its local workers until the next launch.

Navigating away does not cancel an import, reindex, or metric job. Closing the window may quit the desktop application depending on platform behavior; queued work remains recorded and resumes safely when services return.

What to do:

1. Check Tasks before quitting.
2. Pause cancellable work if you need to stop intentionally.
3. Relaunch Vault later.
4. Confirm queued or interrupted work resumes instead of starting duplicate jobs.

**Where in Vault:** Tasks → Active → pause or leave running

**Related questions:** What do task statuses mean?; When can I pause, resume, or cancel a task?; What should I do when restart takes longer than expected?

## Sources & imports

### What do source statuses mean?

Waiting, Processing, Ready, and Failed describe ingestion—not whether a source is clustered.

Ingestion and organization are separate. Ready means Vault extracted usable content and indexed it for search and chat. A ready source can still be unclustered while similarity work is queued or while no suitable cluster exists.

Failed means that generation of the source did not finish. Open the source inspector for the recorded error before retrying.

What to do:

1. Open Sources and use the status filter.
2. Select a source to open its inspector.
3. Read the ingestion detail and page or chunk counts.
4. Use Reindex only for a failed or incomplete source.

**Where in Vault:** Sources → select a source → Source details

**Related questions:** Why is a source ready but not clustered?; How do I follow a batch upload?; How should I retry a failed source?

### Why is a source ready but not clustered?

The source is indexed, but cluster assignment is a separate background step.

Ready confirms that Vault can search and quote the source. Clustering compares that source with other indexed material and may finish later, especially during a large import.

You do not need to wait for clustering to use the source. Choose Unclustered sources in Chat, or assign the source manually if you already know where it belongs.

What to do:

1. Open Sources and select Unclustered sources.
2. Select the ready source and inspect its content.
3. Choose a cluster in the source inspector if the destination is obvious.
4. Otherwise open Clusters and use Refresh clustering once the import job is idle.

**Where in Vault:** Sources → Unclustered sources → select source → Cluster

**Related questions:** How do I follow a batch upload?; Can Chat answer from unclustered sources?; How does automatic clustering work?

### How do I follow a batch upload?

Use the persistent import progress bar and wait for the whole durable job, not only the first file.

A batch is one durable job with per-file progress. The first document can reach Ready while later documents are still extracting, indexing, or waiting for clustering.

Leaving Sources does not cancel the job. Vault keeps the progress surface visible across routes and reports completed, failed, and remaining counts.

What to do:

1. Add the files or import a folder.
2. Watch the import progress surface for the total and completed counts.
3. Do not use Refresh clustering while files are still Processing unless you need an interim grouping.
4. Review Failed items separately when the job finishes.

**Where in Vault:** Sources → Add files or Import folder → Import progress

**Related questions:** What do source statuses mean?; Why is a source ready but not clustered?; How should I retry a failed source?

### Which files and source types can I add?

Vault supports common documents, text, code, images through OCR, links, pasted notes, audio or video transcripts, and folder imports.

Support depends on an available extractor. A file can be accepted but still require OCR, a transcript provider, or a compatible parser. The import preview and failure detail identify unsupported or unreadable items.

What to do:

1. Choose Add files, Add link, Paste text, or Import folder.
2. Review the native file picker filter.
3. Watch the import summary for skipped items.
4. Open any failed source to see the missing extractor.

**Where in Vault:** Sources → Add files / Add link / Paste text / Import folder

**Related questions:** Why were some files skipped during a folder import?; How do scanned PDFs and images become searchable?; How should I retry a failed source?

### Should I add individual files or import a folder?

Use individual files for a small selection; use a folder when its nested structure and future additions matter.

Folder imports retain the import root and relative paths, which lets Sources reconstruct nested folders. Individual files are simpler and do not create a folder grouping.

What to do:

1. Use Add files for a hand-picked set.
2. Use Import folder for a maintained collection.
3. Open the folder row in Sources to browse subfolders.
4. Use an Odin project instead when code structure and Git changes matter.

**Where in Vault:** Sources → Add files or Import folder

**Related questions:** What is the difference between a folder import and an Odin project?; What happens if I import the same source twice?; How do folder imports pick up added, changed, or deleted files?

### What happens if I import the same source twice?

Vault tries to recognize the same file or URL, but moved, copied, or materially changed inputs may become separate sources.

Identity can use paths, import roots, URLs, fingerprints, and content. A duplicate warning protects against accidental repetition; separate copies may still be useful when they belong to different maintained collections.

What to do:

1. Search the title before importing again.
2. Compare original paths and summaries in the inspectors.
3. Keep the source with the correct maintained path.
4. Delete only the redundant source after verifying citations and project membership.

**Where in Vault:** Sources → Search → select each possible duplicate

**Related questions:** What changes when I delete a source?; Should I add individual files or import a folder?; What do source statuses mean?

### Why were some files skipped during a folder import?

Vault skips unsupported, hidden, temporary, generated, symlinked, or unreadable files to keep imports safe and useful.

Build directories and symlinks can be huge or escape the selected folder. Temporary and unsupported files usually add noise. The batch summary distinguishes skipped items from failures that created a source record.

What to do:

1. Open the final import summary.
2. Check whether the item was skipped or failed.
3. Move a genuinely useful file into a supported readable format.
4. Import that file directly if it should bypass the folder exclusions.

**Where in Vault:** Sources → Import progress → final summary

**Related questions:** Which files and source types can I add?; How do I follow a batch upload?; How should I retry a failed source?

### How do scanned PDFs and images become searchable?

Vault uses OCR when a page has little or no extractable text and an OCR runtime is ready.

OCR reads pixels, so quality depends on resolution, orientation, language, contrast, and handwriting. The original remains the source of truth; OCR text is a searchable derived layer.

What to do:

1. Confirm OCR is Ready in Settings → Models & search.
2. Import the scan normally.
3. Open source pages and inspect extracted text.
4. Correct orientation or image quality and reindex if the output is unusable.

**Where in Vault:** Settings → Models & search → OCR; Sources → source → Pages

**Related questions:** How do language and image quality affect OCR?; Why does Vault need chat, embedding, and OCR models?; How should I retry a failed source?

### What changes when I delete a source?

The source and its derived index data are removed from Vault; the original external file is not deleted unless explicitly stated.

Deleting a source removes its chunks, embeddings, cluster membership, and future retrieval. Existing chat history can retain citation labels, but the underlying source may no longer open.

What to do:

1. Open the source inspector and verify its path.
2. Check whether important chats or projects depend on it.
3. Use the confirmed Delete action.
4. Reimport the original later if the deletion was intentional but temporary.

**Where in Vault:** Sources → select source → Delete

**Related questions:** Does deleting a cluster delete its sources?; What happens if I import the same source twice?; How should I back up a vault?

### How do folder imports pick up added, changed, or deleted files?

Folder synchronization compares the registered root with its last known state and applies changes as durable source jobs.

Adding a file creates a source, changing a file creates a new ingestion generation, and deleting a file can require confirmation depending on sync policy. Automatic, notify, and manual modes determine when changes are applied.

What to do:

1. Open Settings → Code connections or the folder's sync controls.
2. Review its sync mode and last scan.
3. Scan for changes.
4. Approve or apply the reported additions, updates, and removals.

**Where in Vault:** Settings → Code connections → Folder sync → Scan or Apply

**Related questions:** Should I add individual files or import a folder?; How do I follow a batch upload?; What changes when I delete a source?

## Clusters

### How does automatic clustering work?

Vault groups indexed sources by semantic similarity while leaving uncertain material for you to review.

Cluster membership is derived from source embeddings and the current cluster profile. It is not based only on filenames or folders.

Manual moves remain authoritative. Refresh clustering recalculates suggestions; it should not silently override a deliberate user move without new evidence.

What to do:

1. Open Clusters and compare names, descriptions, and source counts.
2. Open a cluster to review its Sources tab.
3. Move an obviously misplaced source using its row action.
4. Use Refresh clustering after a large import or major source move.

**Where in Vault:** Clusters → open cluster → Sources → Move

**Related questions:** Why is a source ready but not clustered?; How do I see only the sources in one cluster?; Can Chat answer from unclustered sources?

### How do I see only the sources in one cluster?

Open the cluster and choose View all sources; Vault carries the cluster filter into Sources.

The cluster detail page offers a short recent list and a searchable Sources tab. View all sources opens the full Sources workspace while preserving the cluster in the URL.

Selecting a row also preserves that filter, so closing the inspector returns you to the same cluster list.

What to do:

1. Open Clusters and choose the cluster.
2. Use the Sources tab for a quick search.
3. Choose View all sources for filters, pagination, and source details.

**Where in Vault:** Clusters → [cluster] → Sources or View all sources

**Related questions:** How does automatic clustering work?; How do I control which sources Chat uses?; Why does the map show no connections?

### Is Unclustered sources a real cluster?

It is a live collection of indexed sources without a cluster assignment, not a stored semantic cluster.

The collection changes automatically when sources are assigned or removed. It has no independent profile or color, but it can be opened in Sources and selected as a Chat scope.

What to do:

1. Open Clusters and select Unclustered sources.
2. Review or search the complete collection.
3. Ask it questions from Chat if needed.
4. Assign sources only when the destination is clear.

**Where in Vault:** Clusters → Unclustered sources; Chat → Unclustered sources

**Related questions:** Why is a source ready but not clustered?; Can Chat answer from unclustered sources?; How does automatic clustering work?

### When should I move a source or merge two clusters?

Move one misplaced source; merge clusters only when their overall subjects and future use are genuinely the same.

A move changes one membership. A merge affects every source, chats or links scoped to the clusters, and the combined profile. Review merge artifacts and the destination before confirming.

What to do:

1. Compare cluster descriptions and representative sources.
2. Move isolated mistakes individually.
3. Use Merge only for duplicate concepts.
4. Review the merge artifact and undo path immediately after completion.

**Where in Vault:** Cluster → Sources → Move; Clusters → Manage → Merge

**Related questions:** Does deleting a cluster delete its sources?; How does automatic clustering work?; How do I see only the sources in one cluster?

### Does deleting a cluster delete its sources?

No. Deleting a cluster preserves its sources and returns them to the unclustered collection.

The cluster profile, membership, and cluster-specific views are removed. Source records and original files remain. Scoped chats may keep history but can no longer retrieve through the deleted cluster.

What to do:

1. Open Manage cluster.
2. Read the source-preservation confirmation.
3. Delete the cluster.
4. Review the sources under Unclustered sources and reassign them if needed.

**Where in Vault:** Cluster → Manage → Delete cluster

**Related questions:** Is Unclustered sources a real cluster?; What changes when I delete a source?; When should I move a source or merge two clusters?

## Search & retrieval

### When should I use Search instead of Chat?

Use Search to locate evidence; use Chat to combine and explain evidence.

Search returns ranked sources or passages without generating a narrative. Chat adds model interpretation, which is useful for synthesis but should be verified through citations.

What to do:

1. Use Search for a filename, phrase, person, or known fact.
2. Open the source to verify it directly.
3. Use Chat when the question spans several sources.
4. Follow citations for consequential answers.

**Where in Vault:** Search for retrieval; Chat for synthesis

**Related questions:** Which Vault feature should I use for my task?; Why does Search find related wording instead of the exact phrase?; How do I verify an answer?

### Why does Search find related wording instead of the exact phrase?

Vault can combine lexical matching with semantic similarity, so conceptually related text may rank beside exact words.

Exact matching is strongest for identifiers, filenames, quoted phrases, and uncommon terms. Semantic matching helps when the source uses different wording. Filters and more specific queries reduce broad matches.

What to do:

1. Use distinctive terms or the exact filename.
2. Add source-type or cluster filters.
3. Open a result and inspect the matched excerpt.
4. Use Chat only after the relevant source set is clear.

**Where in Vault:** Search → query → filters → result excerpt

**Related questions:** When should I use Search instead of Chat?; Why does Search return no results for a source I can see?; How do filters change search results?

### How do filters change search results?

Filters define the eligible source set before ranking, so a narrow filter can hide an otherwise strong match.

Cluster, project, type, date, and status constraints should agree with where the source actually lives. Clear filters when results look unexpectedly small, then reapply them one at a time.

What to do:

1. Read every active filter.
2. Clear filters and repeat the same query.
3. Confirm the expected source appears.
4. Reapply only the constraints needed for the task.

**Where in Vault:** Search → active filters → Clear → reapply

**Related questions:** Why does Search find related wording instead of the exact phrase?; Why does Search return no results for a source I can see?; How do I control which sources Chat uses?

### Why does Search return no results for a source I can see?

The source may be filtered out, not yet indexed, grouped under a project, or indexed with text different from the query.

A visible source record does not guarantee searchable chunks. Check Ready status and chunk count, clear filters, search the exact title, then reindex search only if the source remains absent.

What to do:

1. Open the source inspector and confirm Ready plus a nonzero chunk count.
2. Clear Search filters.
3. Search its exact title or a phrase from extracted text.
4. Reindex the source before considering a vault-wide search rebuild.

**Where in Vault:** Sources → source details; Search → clear filters; Source → Reindex

**Related questions:** What do source statuses mean?; When should I rebuild the search index?; How do filters change search results?

### When should I rebuild the search index?

Use a vault-wide rebuild only when many Ready sources are missing or diagnostics report index drift.

Reindexing one source is cheaper and safer for an isolated problem. A full rebuild is durable background work and can temporarily reduce retrieval completeness while new data is validated.

What to do:

1. Test more than one known source.
2. Check System health and Tasks for index drift.
3. Retry an individual source when the problem is isolated.
4. Use Reindex vault search only for a confirmed broad inconsistency.

**Where in Vault:** Settings → Models & search → Reindex vault search

**Related questions:** Why does Search return no results for a source I can see?; What do task statuses mean?; Why does Vault need chat, embedding, and OCR models?

## Chat & answers

### How do I control which sources Chat uses?

Use the scope selector above the conversation and verify the scope label below the composer.

All vault context searches broadly. A cluster, Odin project, or Unclustered sources scope narrows retrieval before the model writes an answer.

The selected scope is stored with the conversation. Existing project chats continue to show the project name so you can tell project retrieval from its underlying source cluster.

What to do:

1. Open Chat and create or open a conversation.
2. Open the scope selector beside the chat title.
3. Choose all vault context, unclustered sources, a cluster, or the current Odin project.
4. Confirm the scope label below the composer before sending.

**Where in Vault:** Chat → scope selector → choose retrieval context

**Related questions:** Can Chat answer from unclustered sources?; How do I verify an answer?; Why is Odin interpretation unavailable?

### Can Chat answer from unclustered sources?

Yes. Choose Unclustered sources as the conversation scope.

Unclustered does not mean unavailable. Indexed unclustered sources are searchable and can answer questions without being placed into a semantic cluster first.

This scope is useful after a batch import, when reviewing ambiguous material, or when you want to avoid unrelated established clusters.

What to do:

1. Open Chat.
2. Choose Unclustered sources in the scope selector.
3. Ask a focused question and inspect the returned citations.
4. Move useful sources into clusters later if their destination becomes clear.

**Where in Vault:** Chat → scope selector → Unclustered sources

**Related questions:** Why is a source ready but not clustered?; How do I control which sources Chat uses?; How do I verify an answer?

### How do I verify an answer?

Open a citation and use View source to inspect the exact document behind the claim.

A useful answer is not enough by itself. Citation popovers show the source title, evidence excerpt, and page or code location when available.

View source opens that specific source—not the global library—so you can compare the answer with the original text.

What to do:

1. Open a citation below the assistant answer.
2. Read the evidence excerpt and location.
3. Choose View source.
4. Compare the source inspector text with the answer before relying on it.

**Where in Vault:** Chat → citation → View source

**Related questions:** How do I control which sources Chat uses?; Can Chat answer from unclustered sources?; What stays local, and what can leave Vault?

### Why does Chat say an answer is partial or incomplete?

Vault found useful evidence but could not cover every requested part within the selected scope or retrieval limits.

Partial is an honesty signal, not necessarily a model failure. The coverage details can identify missing clusters, excluded sources, truncated retrieval, or unavailable project interpretation.

What to do:

1. Read the coverage or warning text below the answer.
2. Open the cited evidence.
3. Broaden the scope only if the missing material should be included.
4. Ask a narrower follow-up for the uncovered part.

**Where in Vault:** Chat → answer → coverage details / warnings

**Related questions:** How do I control which sources Chat uses?; How do I verify an answer?; When should I retry or regenerate an answer?

### What is the difference between attaching a file and importing it?

An attachment is conversation context; an imported source becomes a durable, searchable part of the vault.

Use attachments for temporary questions or files you do not want organized. Import material that should appear in Search, Clusters, Map, future chats, or project context.

What to do:

1. Attach a file for a one-off conversation.
2. Review the attachment notice before sending.
3. Import it through Sources if it should persist.
4. Use citations to distinguish durable sources from temporary context.

**Where in Vault:** Chat → Attach files; Sources → Add files for durable import

**Related questions:** Which files and source types can I add?; How do I control which sources Chat uses?; What happens when I save, rename, or delete a chat?

### When should I retry or regenerate an answer?

Retry after a runtime interruption; regenerate when you want a new answer from the same user question and scope.

Changing scope, sources, or the question is not a regeneration—it is a new request. Keep the original answer when comparing results, and use citations rather than phrasing alone to judge improvement.

What to do:

1. Retry if the answer stopped because the model or service failed.
2. Regenerate when the run completed but another synthesis may help.
3. Change scope explicitly before asking a broader question.
4. Compare evidence coverage and citations.

**Where in Vault:** Chat → answer actions → Retry or Regenerate

**Related questions:** Why does Chat say an answer is partial or incomplete?; How do I control which sources Chat uses?; What should I do when Chat says the model is unavailable?

### What happens when I save, rename, or delete a chat?

Saving marks a conversation for easier retrieval, renaming changes its label, and deleting removes that conversation—not its cited sources.

Chat scope, messages, generations, citations, and feedback belong to the conversation. Deleting it does not delete sources, clusters, projects, or model files. Saved is an organizational flag rather than a separate backup.

What to do:

1. Rename the title at the top of the chat.
2. Use Save for conversations you want to find quickly.
3. Open chat history to return later.
4. Use the confirmed Delete action only when the conversation history is no longer needed.

**Where in Vault:** Chat → title / Save / Delete; Chat history → saved conversation

**Related questions:** How do I control which sources Chat uses?; How do I verify an answer?; What is the difference between attaching a file and importing it?

## Odin projects

### Why is Odin interpretation unavailable?

Interpretation depends on a current project snapshot, retrieval index, and an available local chat model.

Structure and retrieval can be Ready while interpretation is still unavailable. Interpretation is a separate derived layer that needs the active snapshot and model runtime to agree on the same project generation.

Use the project status first. Reindex only the missing layer instead of deleting and recreating the project.

What to do:

1. Open the Odin project and read each readiness row.
2. Open Settings → Models & search and confirm the chat model is Ready.
3. Run Odin status or doctor for a terminal-side explanation.
4. Reindex the interpretation layer if structure and retrieval are current.

**Where in Vault:** Projects → [project] → Intelligence readiness

Commands:

- `odin doctor` -- Check pairing, runtimes, and project prerequisites.
- `odin project status [path]` -- Show snapshot and derived-layer readiness.
- `odin project reindex [path] --layer interpretation` -- Rebuild only interpretation.

**Related questions:** When should TurboVec activate?; Why do project graph metrics fail?; What should I do when restart takes longer than expected?

### When should TurboVec activate?

TurboVec activates only after its benchmark shows a reliable benefit for the active vault and hardware.

Source count alone does not force activation. Vault considers corpus size, benchmark results, hardware compatibility, index freshness, and the runtime safety gate.

If the vault qualifies but activation is absent, System health and the benchmark record should explain which gate is still pending or failed.

What to do:

1. Open Settings → System health.
2. Find embedding and TurboVec readiness.
3. Confirm no benchmark or model-runtime task is failed in Tasks.
4. Run doctor before forcing a rebuild.

**Where in Vault:** Settings → System health → Vector search

Commands:

- `odin doctor` -- Report runtime and acceleration blockers.
- `odin project status [path]` -- Confirm the project retrieval snapshot is current.

**Related questions:** Why is Odin interpretation unavailable?; Why do project graph metrics fail?; Why do old failed tasks still appear?

### Why do project graph metrics fail?

Metrics require a valid current graph snapshot; repeated failure usually points to stale graph data or a blocked model task.

Graph construction and metric generation are separate tasks. A project can open while its newest metric run has failed, because Vault keeps the last validated snapshot available.

Check the newest task, not the historical failure count. A later successful run supersedes earlier failures without deleting their diagnostic history.

What to do:

1. Open Tasks and filter to Needs attention.
2. Open the newest project graph metrics task.
3. Confirm the project graph snapshot is current.
4. Retry once after resolving the named dependency; avoid repeated blind retries.

**Where in Vault:** Tasks → Needs attention → newest Project graph metrics task

Commands:

- `odin project status [path]` -- Check graph and snapshot freshness.
- `odin project reindex [path] --layer structure` -- Rebuild structure when the graph is stale.

**Related questions:** Why is Odin interpretation unavailable?; Why do old failed tasks still appear?; What should I do when restart takes longer than expected?

### What is the difference between a folder import and an Odin project?

A folder import preserves files and folders; an Odin project additionally understands code structure, snapshots, Git changes, and symbol relationships.

Use a normal folder for documents or code you only need to search. Register an Odin project when entrypoints, dependencies, change impact, interpretation, or project maps are important.

What to do:

1. Use Import folder for ordinary searchable files.
2. Use Projects → Add project folder for code-aware analysis.
3. Do not register the same root both ways unless you intentionally want separate records.
4. Open the project readiness rows after registration.

**Where in Vault:** Sources → Import folder; Projects → Add project folder

Commands:

- `odin project add [path] --name "Project name"` -- Register the folder as a code-aware Odin project.

**Related questions:** Should I add individual files or import a folder?; What is an Odin project snapshot?; Why is Odin interpretation unavailable?

### What is an Odin project snapshot?

A snapshot is the validated project state that structure, retrieval, interpretation, and graph outputs refer to.

Snapshots prevent half-updated project views. New changes build candidate outputs first; Vault activates them together only after validation. The working tree can be dirty while the active snapshot remains internally consistent.

What to do:

1. Open the project and read Indexed commit and Working tree status.
2. Treat Active snapshot as the currently answerable state.
3. Preview changes before syncing.
4. Sync when you want the active snapshot to include them.

**Where in Vault:** Projects → project → Snapshot and repository status

Commands:

- `odin project status [path]` -- Show active snapshot and repository freshness.

**Related questions:** How do I bring current code changes into an Odin project?; Why is Odin interpretation unavailable?; Why do project graph metrics fail?

### How do I bring current code changes into an Odin project?

Preview the change set, then sync or reindex the smallest required project layers.

Automatic sync can apply ordinary changes when enabled. Manual or notify mode leaves the active snapshot unchanged until you approve work. Deleted, renamed, or large structural changes may require more layers than a text-only edit.

What to do:

1. Open project Changes or run the changes command.
2. Review added, changed, deleted, and renamed files.
3. Choose Sync.
4. Wait for the new snapshot and required derived layers to become Ready.

**Where in Vault:** Projects → project → Changes → Sync

Commands:

- `odin project changes [path]` -- Preview without indexing.
- `odin project sync [path]` -- Apply current file changes.

**Related questions:** What is an Odin project snapshot?; Which Odin project layer should I reindex?; Does work continue after I close Vault?

### Which Odin project layer should I reindex?

Rebuild only the failed or stale layer unless diagnostics show that an earlier dependency is invalid.

Manifest feeds structure; structure feeds graph and interpretation; retrieval depends on indexed project content. A full rebuild is appropriate only when several dependent layers disagree or the active snapshot is invalid.

What to do:

1. Read project readiness from top to bottom.
2. Find the first stale or failed dependency.
3. Reindex that layer.
4. Use full only when multiple layers or the snapshot contract are broken.

**Where in Vault:** Project → Intelligence readiness → Reindex layer

Commands:

- `odin project reindex [path] --layer structure` -- Replace structure with manifest, retrieval, interpretation, graph, or full as diagnosed.

**Related questions:** Why is Odin interpretation unavailable?; Why do project graph metrics fail?; What is an Odin project snapshot?

## Map & connections

### Why does the map show no connections?

Connections appear only after the selected mode has valid edges for the visible sources.

Current connections come from stored relationships. Semantic connections are calculated from source similarity and may use a minimum score. A map can contain nodes but no visible edges when the wrong mode, a narrow filter, or an unfinished relationship job removes every edge.

Use the legend and selected mode before assuming data is missing. Expanding the view should request more relevant items and their edges together.

What to do:

1. Open Map and clear search or cluster filters.
2. Switch between Current and Semantic connections.
3. Select a source and inspect its connection count.
4. Use Show more to expand the relevant neighborhood.
5. Check Tasks if both modes remain empty for known-related sources.

**Where in Vault:** Map → connection mode → select source → Show more

**Related questions:** What does Show more add to the map?; How does automatic clustering work?; Why do old failed tasks still appear?

### What does Show more add to the map?

It expands the result set with the next sources relevant to the current question or selection.

The first map view is bounded so it remains readable and responsive. Show more continues the same ranked query; it should not restart with unrelated global sources.

The final expansion can include every source that clears the relevance rule, while the viewport may still simplify labels or hide details until selection.

What to do:

1. Ask the project map a specific question or select a source.
2. Inspect the first result set and its connection mode.
3. Choose Show more and confirm the existing nodes remain.
4. Continue until the control reports that all relevant sources are shown.

**Where in Vault:** Project map → ask a question → Show more

**Related questions:** Why does the map show no connections?; Why do project graph metrics fail?; How do I control which sources Chat uses?

### What is the difference between Current and Semantic connections?

Current connections are stored relationships; Semantic connections are similarity-based suggestions calculated from content.

Current edges are stronger evidence that a relationship was explicitly derived or saved. Semantic edges are useful for discovery but can be broad, so their score and supporting sources matter.

What to do:

1. Open Map and note the active mode.
2. Use Current for established structure.
3. Use Semantic to discover related material.
4. Select an edge or node to inspect why it appears.

**Where in Vault:** Map → Current connections / Semantic connections

**Related questions:** Why does the map show no connections?; What should I do when the map is too dense or a connection looks wrong?; What does Show more add to the map?

### What should I do when the map is too dense or a connection looks wrong?

Narrow the question or filters, switch connection mode, and inspect the evidence behind the specific edge.

Dense graphs trade completeness for readability. Labels may be hidden until selection. A semantic connection can be plausible but unhelpful; a current connection should have stored evidence that can be inspected or repaired.

What to do:

1. Narrow the project question or cluster filter.
2. Switch between Current and Semantic.
3. Select the suspicious connection.
4. Open its sources and report or repair the underlying relationship rather than judging line position.

**Where in Vault:** Map → filter or ask → select connection → evidence

**Related questions:** What is the difference between Current and Semantic connections?; What does Show more add to the map?; How do I verify an answer?

## Tasks & background work

### What do task statuses mean?

Queued waits for a worker, Running is active, Paused waits for you, Blocked waits for a dependency, and Failed needs attention.

Tasks are durable, so their state survives navigation and restart. Succeeded and cancelled tasks remain in history. Partial success means useful work completed but some items need review.

What to do:

1. Use Active for queued and running work.
2. Use Needs attention for blocked, failed, or review states.
3. Open a task for its dependency and latest detail.
4. Use History for completed attempts.

**Where in Vault:** Tasks → Active / Needs attention / History

**Related questions:** When can I pause, resume, or cancel a task?; Why is a task blocked instead of failed?; Why do old failed tasks still appear?

### When can I pause, resume, or cancel a task?

Only tasks that declare the operation safe expose it; stopping a task never means deleting already validated output.

Pause preserves resumable progress. Cancel requests a safe stopping point and records cancellation. Some database, migration, or atomic publishing steps cannot be interrupted without risking consistency.

What to do:

1. Open the task detail.
2. Read whether it is cancellable or pausable.
3. Use Pause for temporary resource control.
4. Use Cancel only when you no longer want the result.

**Where in Vault:** Tasks → active task → Pause / Resume / Cancel

**Related questions:** What do task statuses mean?; Does work continue after I close Vault?; Why is a task blocked instead of failed?

### Why is a task blocked instead of failed?

Blocked means the work is still valid but cannot start until a named model, dependency, approval, or resource becomes available.

Unlike failure, blocked work usually does not need a new job. Fix the dependency and Vault can resume it. The task detail identifies setup-required, local-model, dependency, or manual-review blocks.

What to do:

1. Open the blocked task.
2. Read the dependency or approval detail.
3. Fix that prerequisite in Settings or the referenced feature.
4. Return to Tasks and confirm automatic resumption.

**Where in Vault:** Tasks → Needs attention → blocked task → dependency

**Related questions:** What should I do when Chat says the model is unavailable?; What do task statuses mean?; Why is Odin interpretation unavailable?

### Why does a task have no time estimate or a changing estimate?

Estimates appear only after Vault has enough progress data, and they change when file complexity, model speed, or resource contention changes.

Document pages, OCR, embeddings, graphs, and model generations have different cost distributions. Counts are usually more reliable than an early time estimate.

What to do:

1. Use completed and total counts first.
2. Wait for the task to process a representative sample.
3. Check whether another model-heavy task is running.
4. Investigate only when progress and status detail stop changing.

**Where in Vault:** Tasks → active task → Progress and estimated remaining

**Related questions:** What do task statuses mean?; Why is the local model slow?; Does work continue after I close Vault?

## Models & OCR

### Why does Vault need chat, embedding, and OCR models?

They do different work: chat writes answers, embeddings retrieve by meaning, and OCR reads text from pixels.

One ready model does not make every feature ready. Search and clustering depend on embeddings; conversational synthesis and interpretation depend on chat; scanned documents depend on OCR.

What to do:

1. Open Settings → Models & search.
2. Review each runtime separately.
3. Set up only the roles your workflows need.
4. Use System health to confirm their active state.

**Where in Vault:** Settings → Models & search

**Related questions:** How should I choose a local chat model?; What should I do when Chat says the model is unavailable?; How do scanned PDFs and images become searchable?

### How should I choose a local chat model?

Use Vault's hardware recommendation, then balance answer quality, context size, memory use, and speed for your typical questions.

The largest model that fits is not always the best daily choice. A model with adequate context and stable speed produces a better experience than one that continually exhausts memory or falls back.

What to do:

1. Open the hardware recommendation.
2. Choose the recommended compatible model first.
3. Test it with a known cited question.
4. Change models only after comparing quality and measured speed.

**Where in Vault:** Settings → Models & search → Chat model recommendation

**Related questions:** Why is the local model slow?; What should I do when Chat says the model is unavailable?; What is the difference between downloading and importing a model?

### What is the difference between downloading and importing a model?

Download obtains a supported model through Vault; Import registers a compatible model file already on this computer.

Both should use durable progress and verify the final artifact. Imported models still need format, architecture, tokenizer, and runtime compatibility checks before activation.

What to do:

1. Use Download for a recommended model you do not have.
2. Use Import local model for an existing compatible file.
3. Choose a model storage folder with enough space.
4. Wait for verification before activating it.

**Where in Vault:** Settings → Models & search → Download or Import local model

**Related questions:** How should I choose a local chat model?; Can models be stored outside the vault?; What should I do when Chat says the model is unavailable?

### Why is the local model slow?

Speed depends on model size, context length, CPU/GPU support, memory pressure, and other active model jobs.

The first answer can also include model loading time. Long conversations and broad retrieval increase prompt processing. A smaller compatible model or narrower question often helps more than restarting repeatedly.

What to do:

1. Check System health for the active runtime and acceleration.
2. Try a shorter scoped conversation.
3. Pause other model-heavy tasks.
4. Compare measured speed with the model recommendation.

**Where in Vault:** Settings → System health → Local model; Chat → narrow scope

**Related questions:** How should I choose a local chat model?; Why does a task have no time estimate or a changing estimate?; When should TurboVec activate?

### What should I do when Chat says the model is unavailable?

Open model readiness, resolve setup or runtime failure, and retry the interrupted answer after the model reports Ready.

The conversation and user message remain stored. Unavailable can mean no active model, incompatible hardware, failed loading, missing files, or a managed runtime that is restarting.

What to do:

1. Open Settings from the Chat warning.
2. Check the active chat model and runtime detail.
3. Activate or repair a compatible model.
4. Return to Chat and use Retry.

**Where in Vault:** Chat warning → Settings → Models & search → activate or repair

**Related questions:** Why does Vault need chat, embedding, and OCR models?; When should I retry or regenerate an answer?; What should I do when restart takes longer than expected?

### How do language and image quality affect OCR?

OCR is most accurate when the configured language matches clear, upright, high-contrast text.

Mixed languages, handwriting, tables, faint scans, skew, compression, and unusual layouts reduce accuracy. OCR output should be checked before using exact names, numbers, or quotations.

What to do:

1. Choose the appropriate OCR language support.
2. Prefer scans near their original resolution.
3. Correct rotation and contrast before reindexing.
4. Verify critical text against the image page.

**Where in Vault:** Settings → Models & search → OCR; Source → Pages

**Related questions:** How do scanned PDFs and images become searchable?; How do I verify an answer?; How should I retry a failed source?

## Storage & backups

### Where does Vault store my library?

The active vault path contains the library database and managed derived data; model storage can use a separate location.

Settings shows the authoritative path. The hidden .vault directory is managed application data and should not be edited manually while Vault is running.

What to do:

1. Open Settings → Profile or Library & security.
2. Read the displayed library path.
3. Use Vault's move and backup actions instead of moving internal files manually.
4. Review model storage separately under Models & search.

**Where in Vault:** Settings → Library & security → Library location

**Related questions:** How do I move my vault to another folder or drive?; How should I back up a vault?; Can models be stored outside the vault?

### How should I back up a vault?

Use Vault's backup action so the database and required managed files are captured from a consistent state.

Copying an active database directory manually can capture mismatched files. A backup is especially important before moving, deleting, resetting security, or performing major repairs.

What to do:

1. Open Settings → Library & security.
2. Choose Create backup.
3. Save it outside the active vault directory.
4. Verify the backup completes and record its date before destructive work.

**Where in Vault:** Settings → Library & security → Create backup

**Related questions:** How do I recover from a vault backup?; How do I move my vault to another folder or drive?; What happens when I delete a vault?

### How do I recover from a vault backup?

Restore into a safe destination, validate it as a vault, then select it through the setup or recovery flow.

Do not overwrite a healthy active vault while testing a backup. Recovery may require the original passphrase or vendor recovery material when vault security is enabled.

What to do:

1. Keep the current vault untouched.
2. Use the recovery or restore flow to choose the backup.
3. Restore into a new folder.
4. Unlock and verify source counts, chats, and project readiness before retiring the old vault.

**Where in Vault:** Startup recovery → Restore or choose existing library

**Related questions:** How should I back up a vault?; What does locking the vault protect?; Why does Vault say no library is selected?

### How do I move my vault to another folder or drive?

Use the Library move action, which copies, verifies, switches the active pointer, and only then retires the old location.

The destination cannot be a drive root, overlap the source, or contain an incompatible vault. External drives must remain available whenever Vault starts.

What to do:

1. Create a backup.
2. Open Settings → Library & security → Move library.
3. Choose an empty non-root destination with enough space.
4. Wait for copy verification and the active-path switch.

**Where in Vault:** Settings → Library & security → Move library

**Related questions:** How should I back up a vault?; Where does Vault store my library?; What happens when disk space is low?

### What happens when disk space is low?

Imports, model downloads, backups, and index publishing may pause or fail safely rather than leave partial active data.

Original sources, extracted text, embeddings, project snapshots, models, and backups can each be large. Free space on both the vault and model storage locations matters.

What to do:

1. Open System health and Tasks for disk diagnostics.
2. Check both library and model storage drives.
3. Remove unneeded external backups or unused models through their managed controls.
4. Retry the blocked task after space is available.

**Where in Vault:** Settings → System health; Settings → Models & search; Tasks

**Related questions:** Can models be stored outside the vault?; What do task statuses mean?; How should I back up a vault?

### Can models be stored outside the vault?

Yes. Model storage is separate so large reusable model files do not need to live inside every vault.

Moving or deleting a vault should not silently delete shared model files. The selected model root must remain readable and have enough space for downloads and temporary verification files.

What to do:

1. Open Settings → Models & search.
2. Review or choose the model storage folder.
3. Use a stable local drive where possible.
4. Re-scan models after moving files through supported controls.

**Where in Vault:** Settings → Models & search → Model storage

**Related questions:** What is the difference between downloading and importing a model?; Where does Vault store my library?; What happens when disk space is low?

## Connections & sharing

### What does Code Connections or Bridge do?

It lets approved external AI tools read selected Vault context and optionally propose or save reviewed outputs.

Bridge does not automatically expose the whole vault. Connection setup defines allowed vaults, clusters, raw-snippet access, and write capabilities. Review surfaces remain part of the security boundary.

What to do:

1. Open Bridge or Settings → Code connections.
2. Choose the minimum required access.
3. Connect the external tool.
4. Review activity and revoke the connection when it is no longer needed.

**Where in Vault:** Bridge; Settings → Code connections

**Related questions:** How should I choose connection permissions?; Why does an external write need review?; How do I disconnect or revoke an external tool?

### How should I choose connection permissions?

Grant only the vaults, clusters, evidence detail, and write actions required by the external workflow.

Metadata, profiles, raw snippets, and write-back have different sensitivity. A tool that only needs cluster summaries should not receive raw source passages or global vault access.

What to do:

1. Identify the exact external task.
2. Choose the smallest vault or cluster set.
3. Leave raw snippets and writes off unless required.
4. Review activity after the first use.

**Where in Vault:** Settings → Code connections → Connection access

**Related questions:** What does Code Connections or Bridge do?; Why does an external write need review?; What stays local, and what can leave Vault?

### Why does an external write need review?

Review prevents a connected assistant from silently changing source organization or saving untrusted output as vault evidence.

Some captures can be stored as external artifacts, while trusted reuse or changes to managed data need explicit approval. The review explains what will be created, changed, or kept gated.

What to do:

1. Open the pending review.
2. Inspect the proposed content and destination.
3. Approve only if the source and scope are correct.
4. Reject or keep gated when provenance is unclear.

**Where in Vault:** Bridge → Review → pending write

**Related questions:** How should I choose connection permissions?; What does Code Connections or Bridge do?; How do I disconnect or revoke an external tool?

### Why does the Odin command line need pairing?

Pairing gives a specific local CLI client a revocable credential and explicit project scopes without exposing the desktop backend token.

The request shows the executable identity, computer name, and requested scopes. Approve only a command you just initiated on a computer you recognize.

What to do:

1. Run odin auth pair in the intended terminal.
2. Return to Vault and review the pairing request.
3. Approve the requested scopes.
4. Run odin auth status to confirm the connection.

**Where in Vault:** Terminal → odin auth pair; Vault → pairing approval

Commands:

- `odin auth pair` -- Request a new local pairing.
- `odin auth status` -- Verify the active credential.

**Related questions:** How do I disconnect or revoke an external tool?; How should I choose connection permissions?; What is the difference between a folder import and an Odin project?

### How do I disconnect or revoke an external tool?

Revoke its client or connection credential; do not rely only on closing the external application.

Revocation prevents future authenticated requests. Rotating a credential is useful when the same trusted client should continue with a new secret; deletion is appropriate when access should end.

What to do:

1. Open Settings → Code connections.
2. Find the client or connection.
3. Choose Revoke or Disconnect.
4. Confirm activity stops and pair again only if needed.

**Where in Vault:** Settings → Code connections → client → Revoke

Commands:

- `odin auth logout` -- Remove this terminal's stored credential.
- `odin auth forget` -- Forget stale local pairing state.

**Related questions:** What does Code Connections or Bridge do?; Why does the Odin command line need pairing?; How should I choose connection permissions?

## Privacy & security

### What stays local, and what can leave Vault?

Your vault, indexes, and local-model conversations stay on this computer unless you explicitly connect or export them.

Vault stores the library under its selected vault path and uses local model runtimes by default. Bridge and connected tools have explicit scopes and review surfaces.

Treat exported diagnostics and manually shared snippets as separate artifacts. Review their contents before sending them elsewhere.

What to do:

1. Open Settings → Library & security to review the vault path and lock state.
2. Open Code connections to review allowed vaults, clusters, and raw-snippet access.
3. Keep raw snippets disabled unless a workflow requires them.
4. Review diagnostic bundles before sharing.

**Where in Vault:** Settings → Library & security; Settings → Code connections

**Related questions:** How do I verify an answer?; What happens when I delete a vault?; What should I do when restart takes longer than expected?

### What does locking the vault protect?

Locking prevents Vault from opening protected library material until the correct passphrase or recovery flow succeeds.

A lock is different from closing a view or signing out of a connection. Forgetting a passphrase can make encrypted data unrecoverable without configured recovery material.

What to do:

1. Set a memorable strong passphrase and store recovery material safely.
2. Use Ctrl/Cmd+L or Lock library when leaving the computer.
3. Unlock inside the dedicated lock screen.
4. Use Reset or recover only after reading its data consequences.

**Where in Vault:** Command palette → Lock library; Lock screen → Unlock

**Related questions:** What does vault encryption cover—and not cover?; How do I recover from a vault backup?; What stays local, and what can leave Vault?

### What does vault encryption cover—and not cover?

Vault encryption protects managed vault material at rest; files outside the vault and anything you explicitly export follow their own storage security.

Operating-system access, backups, model files, diagnostic exports, clipboard contents, and connected tools have separate boundaries. Encryption does not replace device security or careful sharing.

What to do:

1. Review the active vault path and security status.
2. Protect backups and recovery material separately.
3. Review exports before sharing.
4. Use connection scopes for external tools.

**Where in Vault:** Settings → Library & security

**Related questions:** What does locking the vault protect?; What can a diagnostic bundle contain?; How should I choose connection permissions?

### What can a diagnostic bundle contain?

Diagnostics can include versions, health states, bounded logs, job errors, and configuration metadata needed to investigate a problem.

A well-formed bundle avoids credentials and limits oversized paths or stack details, but filenames, vault identifiers, and error context may still be sensitive. Review it before sharing.

What to do:

1. Create the diagnostic bundle only when needed.
2. Open or inspect its contents.
3. Remove or withhold anything inappropriate for the recipient.
4. Share through a trusted channel.

**Where in Vault:** Settings → Advanced → Create diagnostic bundle

**Related questions:** What does vault encryption cover—and not cover?; Where should I look when something behaves incorrectly?; What stays local, and what can leave Vault?

## Troubleshooting

### How should I retry a failed source?

Inspect the recorded failure first, then retry that source without reuploading the whole batch.

Vault retains failed source records so the original path, stage, and diagnostic detail remain available. Reimporting everything can create duplicates and hides whether the original failure was actually resolved.

Password-protected, unreadable, unsupported, or missing files need different fixes. The source inspector identifies the stage that failed.

What to do:

1. Open Sources and filter to Failed.
2. Select the source and read its failure detail.
3. Resolve the named file, OCR, model, or storage issue.
4. Choose Reindex and watch the durable task in Tasks.

**Where in Vault:** Sources → Status: Failed → select source → Reindex

**Related questions:** What do source statuses mean?; How do I follow a batch upload?; Why do old failed tasks still appear?

### Why do old failed tasks still appear?

Tasks keeps diagnostic history; current readiness is determined by the newest run for that work.

A successful retry does not erase earlier failures. This makes recurring issues diagnosable and prevents a later success from hiding how often a task needed intervention.

Use the status views and timestamps to distinguish a current blocker from historical evidence.

What to do:

1. Open Tasks and choose Needs attention.
2. Sort mentally by the newest timestamp for the affected feature.
3. If a newer run succeeded, treat the older failure as history.
4. If the newest run failed, open it and act on the first specific dependency error.

**Where in Vault:** Tasks → Needs attention → newest matching task

**Related questions:** Why do project graph metrics fail?; How should I retry a failed source?; What should I do when restart takes longer than expected?

### What should I do when restart takes longer than expected?

Use the Settings restart action and let the desktop process supervise shutdown and recovery outside normal API timeouts.

Stopping local models and database work can legitimately take longer than a normal request. Restart and vault deletion therefore use desktop-supervised operations instead of the generic short request timeout.

Avoid force-closing Vault while a deletion confirmation is in progress. A failed pre-vault restart should restore the previous pointer and data rather than leave a half-deleted library.

What to do:

1. Open Settings → Advanced.
2. Choose Restart local services once.
3. Watch the persistent progress or recovery surface.
4. If startup fails, use the displayed repair action or create a diagnostic bundle.

**Where in Vault:** Settings → Advanced → Restart local services

**Related questions:** Why do old failed tasks still appear?; What happens when I delete a vault?; Why is Odin interpretation unavailable?

### What happens when I delete a vault?

Vault confirms the exact library, stops managed services, tombstones the data, and returns to setup.

Deleting a vault is intentionally different from deleting a source or cluster. It affects the active library directory and desktop setup state, so Vault requires a dedicated authorization step.

If the restart handoff fails before deletion is committed, Vault restores the prior data and active pointer. Once deletion succeeds, recovery depends on your external backups.

What to do:

1. Create and verify a backup first.
2. Open Settings → Library & security.
3. Choose Delete library and read the exact path.
4. Complete the dedicated confirmation and wait for setup to reopen.

**Where in Vault:** Settings → Library & security → Delete library

**Related questions:** What stays local, and what can leave Vault?; What should I do when restart takes longer than expected?; Why do old failed tasks still appear?

### Why does Vault say no library is selected?

The desktop setup has no valid active vault pointer, or the saved vault path is missing or unavailable.

This can happen after moving a folder manually, disconnecting an external drive, clearing setup state, or opening a backup on another computer. Do not create a new empty vault over existing data.

What to do:

1. Confirm the expected drive and folder are available.
2. Use Choose existing library or recovery.
3. Select the folder that contains the valid .vault database.
4. Create a new vault only if no existing library should be recovered.

**Where in Vault:** Startup setup or recovery → Choose existing library

**Related questions:** How do I recover from a vault backup?; Where does Vault store my library?; What should I do when the Vault service is offline?

### What should I do when the Vault service is offline?

Use System health or the startup repair surface; repeated refreshes cannot repair a backend that failed identity or readiness checks.

The desktop validates that the local service is authenticated, loopback-only, in the correct mode, and opened on the expected vault paths. A different process on the same port is not accepted as Vault.

What to do:

1. Open System health if the application shell is available.
2. Use Restart local services once.
3. Read the phase-specific startup repair message.
4. Create diagnostics if readiness still fails.

**Where in Vault:** Settings → System health → Vault service; Startup repair

**Related questions:** What should I do when restart takes longer than expected?; Where should I look when something behaves incorrectly?; Why does Vault say no library is selected?

### Where should I look when something behaves incorrectly?

Start with the affected item's detail, then Tasks, System health, and finally a diagnostic bundle.

The nearest error is usually the most specific: source inspector for ingestion, project readiness for Odin, answer warnings for Chat, and task detail for background work. System-wide restart should come later.

What to do:

1. Open the affected source, chat, project, map item, or task.
2. Read the newest specific error or warning.
3. Check the named dependency in System health.
4. Create diagnostics only when the cause remains unclear.

**Where in Vault:** Affected item → Tasks → System health → Advanced diagnostics

**Related questions:** What do task statuses mean?; What should I do when the Vault service is offline?; What can a diagnostic bundle contain?
