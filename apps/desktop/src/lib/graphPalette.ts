// Theme-aware color palette for canvas-rendered graphs (Knowledge Map,
// Project Graph/Odin). Canvas 2D contexts cannot resolve CSS custom
// properties on their own (fillStyle/strokeStyle only accept literal color
// strings), so this module reads the live computed values of the semantic
// tokens declared in styles.css and re-reads them whenever the effective
// theme changes, via theme.ts's subscribeTheme (which applies the new
// data-theme/.dark attributes synchronously before notifying listeners).
//
// Consumers should call `useGraphPalette()` and pass the returned values
// into react-force-graph-2d's color/canvas-object props. Because those
// props are diffed by the underlying force-graph library on every render,
// a new palette object naturally triggers a redraw without resetting node
// positions, zoom, selection, or fetched data.

import { useEffect, useState } from "react";
import { subscribeTheme } from "@/lib/theme";

export type GraphCategory = "sage" | "terracotta" | "sky" | "sand" | "lavender" | "blush";

export interface GraphPalette {
  /** The six categorical accent families, for node kind/cluster color coding. */
  categorical: Record<GraphCategory, string>;
  /** Neutral fallback for kinds that don't map to one of the six categories. */
  neutral: string;
  /** A warmer, brand-toned neutral for a second uncategorized kind that
   * still needs to read as distinct from `neutral` (e.g. "source" vs.
   * "unclustered collection" in the Knowledge Map). */
  accentNeutral: string;
  /** The canvas/card surface a force-graph instance should paint as its own
   * backgroundColor, so it matches the surrounding chrome in both themes
   * instead of hardcoding white. */
  canvasBackground: string;
  /** Default node/edge label text color. */
  label: string;
  /** De-emphasized label text (e.g. edge/link labels). */
  labelMuted: string;
  /** Background color to halo/stroke behind canvas text so it stays legible
   * over any node/edge it overlaps, in either theme. */
  labelHalo: string;
  /** Default edge/link stroke color. */
  edge: string;
  /** De-emphasized edge stroke color (e.g. similarity/secondary links). */
  edgeMuted: string;
  /** Edge stroke color for a selected/highlighted relationship. */
  edgeSelected: string;
  /** Ring/outline color for a selected node. */
  nodeSelectedRing: string;
  /** Fill/ring color for a node in a warning state (e.g. stale, unavailable). */
  nodeWarning: string;
  /** Fill/ring color for a node in a stale/muted state. */
  nodeStale: string;
  /** Stroke color drawn around solid node fills for edge definition against
   * the canvas background (documented fallback constant: matches --bg-card,
   * not a literal design color). */
  nodeStroke: string;
}

function readVar(name: string, fallback: string): string {
  if (typeof window === "undefined" || typeof document === "undefined") return fallback;
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

/**
 * Reads the current resolved-theme palette from computed CSS custom
 * properties. Safe to call outside React (e.g. inside a canvas draw
 * callback) as long as the DOM has already applied data-theme/.dark.
 */
export function readGraphPalette(): GraphPalette {
  return {
    categorical: {
      sage: readVar("--cluster-sage", "#5B8A5B"),
      terracotta: readVar("--cluster-terracotta", "#C0704A"),
      sky: readVar("--cluster-sky", "#4A78A8"),
      sand: readVar("--cluster-sand", "#B8944A"),
      lavender: readVar("--cluster-lavender", "#8A7CC0"),
      blush: readVar("--cluster-blush", "#C06878"),
    },
    neutral: readVar("--graph-label-muted", "#6B6A66"),
    accentNeutral: readVar("--primary", "#7C6E5A"),
    canvasBackground: readVar("--bg-card", "#FFFFFF"),
    label: readVar("--graph-label", "#3D3C39"),
    labelMuted: readVar("--graph-label-muted", "#6B6A66"),
    labelHalo: readVar("--bg-canvas", "#FAFAF8"),
    edge: readVar("--graph-edge", "#8F8D86"),
    edgeMuted: readVar("--graph-edge-muted", "#E8E7E3"),
    edgeSelected: readVar("--graph-edge-selected", "#7C6E5A"),
    nodeSelectedRing: readVar("--graph-node-selected-ring", "#7C6E5A"),
    nodeWarning: readVar("--graph-node-warning", "#C88A3A"),
    nodeStale: readVar("--graph-node-stale", "#615F5B"),
    nodeStroke: readVar("--bg-card", "#FFFFFF"),
  };
}

/**
 * React hook: returns the live graph palette, updating (with a new object
 * reference) whenever the effective theme changes. Does not itself force a
 * canvas redraw — pass the returned value into color-producing props so the
 * consuming force-graph instance's own prop-diffing triggers the redraw.
 */
export function useGraphPalette(): GraphPalette {
  const [palette, setPalette] = useState<GraphPalette>(() => readGraphPalette());
  useEffect(() => {
    const unsubscribe = subscribeTheme(() => {
      setPalette(readGraphPalette());
    });
    return unsubscribe;
  }, []);
  return palette;
}

/** Maps a node "kind" string to one of the six categorical accent families. */
export function categoryForKind(kind: string): GraphCategory | null {
  switch (kind) {
    case "route":
      return "terracotta";
    case "class":
      return "lavender";
    case "function":
    case "method":
      return "sage";
    case "file":
    case "module":
    case "fact":
      return "sky";
    case "package":
      return "sand";
    default:
      return null;
  }
}
