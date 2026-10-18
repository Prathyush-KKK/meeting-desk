// On a phone the paste textarea grows with content, and Save and continue appears as soon as there
// is text. It used to be a fixed six rows, so a pasted summary scrolled out of its own box and the
// first lines could not be seen.

import { useLayoutEffect, type RefObject } from "react";

/** The tallest the box grows before it scrolls: 40 % of the viewport, so the list stays in view. */
export function growCap(): number {
  return Math.round((typeof window === "undefined" ? 800 : window.innerHeight) * 0.4);
}

/**
 * Sizes a textarea to its content, from its `rows` height up to `maxPx`, scrolling only past that
 * (pass `Infinity` for a box that never scrolls). Runs before paint, so the box never flashes at the
 * wrong height, and again when the window is resized.
 */
export function useAutoGrow(ref: RefObject<HTMLTextAreaElement | null>, value: string, maxPx: number = growCap()): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.height = "auto";
      const borders = Math.max(0, el.offsetHeight - el.clientHeight);
      const wanted = el.scrollHeight + borders;
      el.style.height = `${Math.min(wanted, maxPx)}px`;
      el.style.overflowY = wanted > maxPx ? "auto" : "hidden";
    };
    fit();
    // A phone turned on its side re-wraps the text; the height has to follow.
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [ref, value, maxPx]);
}
