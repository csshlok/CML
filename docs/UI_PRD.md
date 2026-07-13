# Context Management Layer UI PRD

## 1. UI Vision

The app should feel like a welcoming AI workspace for personal context. The first surface is a CML memory workspace where the user searches, inspects, and routes saved data. Chat remains a core workspace, but it should not be the first tab.

The visual language should combine:

- Mindly's approachable capture and visual organization.
- Obsidian's graph-based knowledge map.
- A calm desktop productivity tool rather than a technical ML dashboard.

The user should never feel like they are managing models. They are managing spaces of context.

## 2. Primary Interface Model

The app has four persistent regions:

- **Left sidebar**: vault, clusters, sources, saved chats.
- **Center**: memory board, map, chat, or selected workspace.
- **Right panel**: selected cluster/source/context inspector.
- **Map layer**: visual cluster graph/globe that can be opened as a main view or compact side view.

The first screen after onboarding should be the Mind workspace, not chat and not a marketing-style landing page.

## 3. Navigation

Primary navigation items:

- Mind
- Sources
- Map
- Clusters
- Chat
- Bridge
- Settings

Secondary actions:

- Add files
- Add folder
- Add link
- Paste text
- New cluster
- Reindex

The app should include a command palette for fast actions.

## 4. Onboarding

Onboarding goal: get the user to their first useful answer with minimal setup.

Required onboarding steps:

1. Choose or create a local vault.
2. Drop files, choose a folder, paste text, or add links.
3. Show indexing progress.
4. Show suggested clusters.
5. Let user confirm or rename clusters.
6. Open the memory board with the new sources and clusters available.

Onboarding should avoid technical language like embeddings or vector indexes unless the user opens advanced details.

Preferred user-facing terms:

- "Vault" instead of database.
- "Cluster" or "Space" instead of embedding group.
- "Local chat model" instead of runtime or provider terminology.
- "Ready", "Learning", "Needs update", "Issue" instead of internal statuses.

## 5. Chat Experience

Chat is a core product surface, but the app should land on the memory board. Chat should be easy to reach from a selected source, cluster, or map detail.

Required chat features:

- Global chat mode.
- Selected cluster chat mode.
- Cluster routing indicator.
- Manual cluster override.
- Source citations.
- Attachments in prompt.
- Response streaming.
- Save useful answer.
- Mark answer as useful/not useful.
- Add answer to cluster memory.
- Regenerate with different cluster.
- Ask same prompt across multiple clusters.

The routing indicator should be understandable:

Example:

> Using X Assignment because your prompt asks for its style.

When multiple clusters contribute:

> Using X Assignment for style and Y Research for facts.

## 6. Cluster UI

Each cluster should have:

- Name.
- Color or icon.
- Short description.
- Source count.
- Last active date.
- Local expert status.
- Confidence/health indicator.
- Recent chats.
- Key sources.
- Summary.
- Style profile.

Cluster actions:

- Open chat with cluster.
- Rename.
- Add sources.
- Move sources.
- Merge.
- Split.
- Retrain local expert.
- Reset local expert.
- Export cluster.

The cluster detail panel should have tabs:

- Overview
- Sources
- Chats
- Expert
- Map

## 7. Local Expert UI

The local expert must be visible but not intimidating.

Normal UI status labels:

- `Setting up`
- `Learning`
- `Ready`
- `Needs update`
- `Paused`
- `Issue`

Advanced details may show:

- training data count
- last trained time
- expert version
- model path
- training logs
- rollback option

The app should clearly distinguish:

- context is searchable now
- expert is still learning
- expert is ready

This prevents the user from thinking the app is broken while training runs.

## 8. Sources UI

The Sources view should let users inspect what the app knows.

Required features:

- File/link list.
- Source type icon.
- Cluster assignment.
- Processing status.
- Extracted text preview.
- Summary.
- Tags.
- Reindex action.
- Remove action.

Supported processing states:

- Waiting
- Extracting
- Indexed
- Needs review
- Failed

## 9. Map / Globe UI

The map should help users understand their context landscape.

V1 may use a 2D graph first if faster to build. The long-term target is an Obsidian-like globe/map view with Mindly-like friendliness.

Map requirements:

- Cluster blobs on the overview, without visible lines between clusters by default.
- Source nodes optionally visible.
- Source/data point names hidden on the overview unless shown in a hover preview.
- Similarity lines and source spokes may appear inside a selected cluster detail view.
- Blob size based on source count or activity.
- Blob glow/ring when local expert is learning.
- Double-click cluster blob to open its connected data inside the map tab.
- Hover source/data point to preview file name, text snippet, and open/reveal actions.
- Drag/pan/zoom.
- Search and focus node.
- Filter by source type, recency, or expert status.

The map must not be decorative only. It should support navigation and cluster correction.

## 10. Visual Design Direction

The interface should be:

- Soft and refined.
- Calm.
- Spacious but not empty.
- Easy for non-technical users.
- Dense enough for power users after onboarding.

Avoid:

- Overly technical dashboards.
- Heavy cyberpunk styling.
- Pure dark-blue/purple gradient themes.
- Floating card overload.
- Marketing-style hero screens.

Recommended palette direction:

- Warm neutral base.
- Soft accent colors per cluster.
- Clear restrained status colors.
- High contrast text.
- Light and dark modes.

Cards should be used for repeated objects like source items and cluster previews, not for every page section.

## 11. Desktop Behavior

The app should behave like a native desktop workspace.

Required:

- Drag and drop files/folders.
- App menu actions.
- Keyboard shortcuts.
- Local file picker.
- Background indexing indicator.
- Offline-first behavior.
- Clear storage location in settings.
- Optional local Context Bridge service for external LLM tools.

Important shortcuts:

- Command/Ctrl + K: command palette.
- Command/Ctrl + L: add link.
- Command/Ctrl + O: open vault.
- Command/Ctrl + N: new chat.
- Command/Ctrl + Shift + N: new cluster.

## 12. Context Bridge UI

The Context Bridge lets other local LLM tools use the user's vault, clusters, source retrieval, style profiles, and local experts.

The UI should explain this in user language:

> Let other AI apps ask your local memory for relevant context.

Supported bridge surfaces:

- MCP server for compatible AI tools.
- Local API for developer tools.
- CLI for terminal workflows.
- Copy context for manual paste.

Required controls:

- Enable/disable Context Bridge.
- Show bridge status.
- Show local endpoint.
- Copy MCP configuration.
- Copy CLI examples.
- Choose allowed vaults.
- Choose allowed clusters.
- Allow or block raw source snippets.
- Allow or block style profile access.
- Allow or block cluster profile context.
- View recent context requests.

Bridge status labels:

- `Off`
- `Running`
- `Client connected`
- `Needs setup`
- `Issue`

Example bridge actions:

- Copy context for Claude.
- Copy context for terminal.
- Configure MCP client.
- Test bridge.
- Stop bridge.

The bridge UI must make privacy boundaries obvious. Users should understand that bridge access lets another local AI tool request selected context, but it should not expose the full vault by default.

## 13. Empty States

Empty states should guide action without sounding technical.

Examples:

- No vault: "Choose a place for your local memory."
- Empty vault: "Drop files, links, screenshots, or notes to begin."
- No clusters: "Add a few items and we will suggest clusters."
- Expert learning: "This cluster is usable now. Its local expert is still learning in the background."
- Bridge off: "Turn on the Context Bridge when you want another AI app to use your local memory."

## 14. Trust And Transparency

The UI must show:

- Which cluster was used.
- Which sources were used.
- Whether the local expert was ready or bootstrapping.
- Whether the answer includes inferred information.
- Whether any remote service was used.
- Whether context was served to an external local client.

The user should be able to click citations and inspect source snippets.

## 15. Error States

Required visible errors:

- File extraction failed.
- Link fetch failed.
- OCR failed.
- Indexing failed.
- Local model unavailable.
- Project indexing failed.
- Vault path unavailable.
- Disk space low.
- Context Bridge failed to start.
- External client requested blocked context.

Errors should include a next action:

- Retry.
- Open file.
- Remove source.
- Reindex.
- View details.
- Open Bridge settings.

## 16. V1 UI Acceptance Criteria

V1 UI is successful when:

- User can create/open a vault.
- User can drag files and links into the app.
- User sees processing progress.
- User sees suggested clusters.
- User can confirm, rename, merge, and move cluster content.
- User can chat globally or with a selected cluster.
- User can see which cluster and sources informed an answer.
- User can see local expert status for every cluster.
- User can open a map view and use it to navigate clusters.
- User lands on the memory board after onboarding.
- User can search, filter, sort, add content, and open source detail from the Mind workspace.
- User can enable/disable the Context Bridge.
- User can copy MCP or CLI setup instructions.
- User can see recent external context requests.
- The product feels like a consumer second-brain app, not a developer tool.

## 17. Future UI Ideas

- Timeline view.
- Calendar-based memory view.
- Browser extension capture.
- Deferred: redesign the removed global capture flow before considering a floating capture window.
- Voice note capture.
- Full 3D globe mode.
- Multi-cluster comparison mode.
- Writing style studio.
- Expert quality report.
- Local discovery scanner for explicitly selected folders.
- Per-client bridge permissions.
- One-click setup for popular local LLM clients.
