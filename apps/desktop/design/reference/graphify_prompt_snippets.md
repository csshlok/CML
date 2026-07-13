# Graphify Prompt Snippets

These are the concrete snippets worth preserving from Graphify when refining `ClusterMap.tsx`.

They are not a drop-in implementation. They are prompt-ready references for force behavior, community coloring, and sidebar structure.

## Force Physics

Use this as the target motion profile when moving from a hand-rolled layout toward a more graph-native simulation:

```js
physics: {
  enabled: true,
  solver: "forceAtlas2Based",
  forceAtlas2Based: {
    gravitationalConstant: -60,
    centralGravity: 0.005,
    springLength: 120,
    springConstant: 0.08,
    damping: 0.4,
    avoidOverlap: 0.8,
  },
  stabilization: { iterations: 200, fit: true },
}
```

## Community Palette

Graphify uses a restrained multi-community palette. The exact colors are useful as a reference even if CML keeps its own tint system:

```js
const COMMUNITY_COLORS = [
  "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
  "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
];
```

## Node Sizing Rule

This is the closest Graphify-side rule to CML's `indexed_source_count` sizing target:

```js
const size = 10 + 30 * (count / maxCount);
```

For CML, interpret `count` as `indexed_source_count` and clamp small clusters so they still feel clickable.

## Sidebar Structure

Graphify's rendered map works because the graph canvas stays dominant and the sidebar stays narrow and informational.

Recommended structure:

1. Search at the top.
2. Selected cluster summary next.
3. Relationship details below.
4. Legend and small graph stats last.

The important constraint is not to turn the sidebar into a dashboard. Keep it like a graph inspector.

## Translation Notes For CML

- Preserve CML's light theme instead of importing Graphify's dark shell.
- Keep cluster identity colors from the existing tint system.
- Prefer softer edges, smaller labels, and more empty space than the current rigid layout.
- Use community shading sparingly so the graph still reads like a note field, not a network admin panel.
