// How the grid marks a cell, kept out of Grid.tsx so that file exports only components.

export type CellMark = "new" | "key" | "conflict" | "moved" | "edited";

/**
 * The five marks, in the one selection hue. Three variants carry all of
 * them: a tint for what is being written, an outline for what needs a decision, a strike for what
 * only moves. The Transfer legend wears the same three on its own labels, so the legend is the
 * rule rather than a copy of it.
 */
export const MARK_CLASS: Record<CellMark, string> = {
  new: "sel-tint",
  edited: "sel-tint font-medium",
  key: "sel-soft italic",
  conflict: "sel-outline sel-soft",
  moved: "sel-strike",
};
