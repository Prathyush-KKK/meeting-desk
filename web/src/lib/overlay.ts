// Back closes what is on top, instead of leaving the app.
//
// The detail overlay traps the back button: it pushes history, and Back closes it. The mobile cell
// editor does the same - on a phone both of them cover the page, and Back is the gesture people
// reach for.
//
// The entry carries no URL change (App.tsx owns the query string), so the URL effect there never
// sees a difference and never replaces what was pushed.

import { useEffect, useRef, useState } from "react";

/** Below the 768 px breakpoint, where the detail panel and the cell editor become overlays. */
export const NARROW_QUERY = "(max-width: 767.98px)";

/**
 * Whether the viewport is under the breakpoint. Used where a CSS `md:` variant is not enough on its
 * own - an overlay that pushes history, or an input that must not steal focus on the other side of
 * the breakpoint. A browser with no `matchMedia` (and jsdom, unless a test stubs it) reads as wide,
 * which is the desktop path.
 */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = typeof window.matchMedia === "function" ? window.matchMedia(NARROW_QUERY) : null;
    if (!query) return;
    const read = () => setNarrow(query.matches);
    read();
    query.addEventListener("change", read);
    return () => query.removeEventListener("change", read);
  }, []);
  return narrow;
}

/**
 * While `open`, one history entry belongs to this overlay: Back pops it and calls `close` instead
 * of leaving the app. Closing any other way (the X, Save, Cancel, Escape) drops the entry again, so
 * the overlay never leaves a dead step in the history for Back to land on.
 */
export function useCloseOnBack(open: boolean, close: () => void): void {
  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    if (!open) return;
    let byBack = false;
    window.history.pushState({ ...(window.history.state as object | null), mdOverlay: true }, "");
    const onPop = () => {
      byBack = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (!byBack) window.history.back();
    };
  }, [open]);
}
