import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// jsdom has no layout: every element is 0x0 and there is no ResizeObserver. TanStack Virtual
// measures its scroll box through both, so without these the virtualised grid renders an empty
// window and the test would be asserting nothing. Giving the box a size is the only thing a real
// browser supplies that jsdom does not.
// jsdom has no matchMedia either. Sonner's Toaster asks for it on mount, and `useNarrow` asks for
// it to decide between the inline cell editor and the bottom one. The stub answers "no match",
// which is the desktop side of the 768 px breakpoint; the tests that want the phone side stub it
// again with `vi.stubGlobal`.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

if (!("ResizeObserver" in globalThis)) {
  class StubResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = StubResizeObserver;
}

// TanStack Virtual sizes its scroll box with offsetWidth/offsetHeight, which jsdom always reports
// as 0. Only the grid's box is given a size (it is the one element carrying data-rows), so nothing
// else in the suite sees a layout it would not see in a browser.
const VIEWPORT = { width: 1200, height: 640 };
for (const [property, value] of [
  ["offsetWidth", VIEWPORT.width],
  ["offsetHeight", VIEWPORT.height],
] as const) {
  Object.defineProperty(HTMLElement.prototype, property, {
    configurable: true,
    get(this: HTMLElement) {
      return this.dataset.rows === undefined ? 0 : value;
    },
  });
}
