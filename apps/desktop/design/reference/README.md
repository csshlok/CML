# Graph References

These files are local reference implementations for the `ClusterMap` rewrite.

Use them as source-grounded examples, not as code to copy verbatim.

## Files

- `graphify_export.py`
  Graphify's HTML export implementation. This contains the `vis-network` force config, community color handling, sidebar structure, and hyperedge rendering logic.

- `graphify_graph_sample.html`
  A rendered Graphify sample export. Useful for checking the visual relationship between graph canvas, sidebar, community colors, and edge density.

- `graphify_prompt_snippets.md`
  Prompt-ready snippets extracted from Graphify's force config, palette, and sizing logic. Useful when iterating on the map without reopening the whole exporter.

- `ignis_bridge_styles.css`
  A local style reference from Ignis. Useful for muted status language, restrained borders, and Obsidian-adjacent UI tone.

- `juggl_visualization.ts`
  Juggl's core Obsidian graph visualization logic. This is the most relevant reference for Obsidian-style force graph behavior in an actual vault context.

- `juggl_layout_settings.ts`
  Juggl layout and force-related settings. Useful for translating vault-like motion and spacing decisions into CML's map.

- `juggl_stylesheet.ts`
  Juggl's graph node and edge styling rules. Useful for understanding how Obsidian-style graph emphasis is handled without oversized UI chrome.

- `juggl_sidebar.svelte`
  A small sidebar reference from Juggl's UI layer. Useful as a reference for a graph-adjacent inspector rather than card-heavy dashboard styling.

## Intended Use

For the next `ClusterMap` pass:

1. Use `graphify_export.py` and `graphify_graph_sample.html` for graph structure ideas:
   force behavior, edge styling, community shading, sidebar information hierarchy.
2. Use the Juggl files for Obsidian-like graph behavior:
   lighter node language, less rigid positioning, vault-like interaction patterns.
3. Preserve CML's light app palette and routing shell rather than importing Graphify's dark theme directly.

## Quick Open

To open the Graphify sample locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/frontend/open-graph-reference.ps1
```
