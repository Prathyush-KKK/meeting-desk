// Review 1, finding 23, second half: "the overlay does not push history". Back has to close what
// is on top rather than leave the app, and closing any other way must not leave a dead entry
// behind for Back to land on.

import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCloseOnBack, useNarrow, NARROW_QUERY } from "@/lib/overlay";

/** jsdom does not move through history on its own; popstate is what a Back press delivers. */
const back = () => act(() => void window.dispatchEvent(new PopStateEvent("popstate")));

describe("useCloseOnBack", () => {
  it("pushes one entry while the overlay is open and closes it on Back", () => {
    const close = vi.fn();
    const before = window.history.length;
    const { result } = renderHook(({ open }) => useCloseOnBack(open, close), { initialProps: { open: true } });

    expect(window.history.length).toBe(before + 1);
    expect(window.history.state).toMatchObject({ mdOverlay: true });
    expect(result.current).toBeUndefined();

    back();
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("does not push anything while the overlay is shut", () => {
    const close = vi.fn();
    const before = window.history.length;
    renderHook(({ open }) => useCloseOnBack(open, close), { initialProps: { open: false } });
    expect(window.history.length).toBe(before);
    back();
    expect(close).not.toHaveBeenCalled();
  });

  it("takes its own entry back when the overlay is closed by a button instead", async () => {
    const close = vi.fn();
    const spy = vi.spyOn(window.history, "back");
    const { rerender } = renderHook(({ open }) => useCloseOnBack(open, close), { initialProps: { open: true } });

    rerender({ open: false });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    // The entry is dropped, not re-closed: the overlay is already shut.
    expect(close).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("does not take an entry back when Back is what closed it", async () => {
    const close = vi.fn();
    const spy = vi.spyOn(window.history, "back");
    const { rerender } = renderHook(({ open }) => useCloseOnBack(open, close), { initialProps: { open: true } });

    back();
    rerender({ open: false });
    expect(close).toHaveBeenCalledTimes(1);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("uses the latest close without re-pushing when the component re-renders", () => {
    const first = vi.fn();
    const second = vi.fn();
    const before = window.history.length;
    const { rerender } = renderHook(({ close }) => useCloseOnBack(true, close), { initialProps: { close: first } });
    rerender({ close: second });
    rerender({ close: second });

    expect(window.history.length).toBe(before + 1);
    back();
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});

describe("useNarrow", () => {
  it("reads the 768 px breakpoint and follows it", () => {
    const listeners = new Set<() => void>();
    const mql = {
      matches: true,
      media: NARROW_QUERY,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    };
    const matchMedia = vi.fn(() => mql as unknown as MediaQueryList);
    vi.stubGlobal("matchMedia", matchMedia);

    const { result } = renderHook(() => useNarrow());
    expect(matchMedia).toHaveBeenCalledWith("(max-width: 767.98px)");
    expect(result.current).toBe(true);

    mql.matches = false;
    act(() => listeners.forEach((fn) => fn()));
    expect(result.current).toBe(false);

    vi.unstubAllGlobals();
  });

  it("reads as wide where there is no matchMedia at all", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { result } = renderHook(() => useNarrow());
    expect(result.current).toBe(false);
    vi.unstubAllGlobals();
  });
});
