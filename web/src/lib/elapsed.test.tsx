// The counter on Extract and Re-extract: an extraction takes one to two minutes, and a bare
// "Extracting…" for that long reads as stuck.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useElapsedSeconds } from "./elapsed";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useElapsedSeconds", () => {
  it("stays at 0 while inactive", () => {
    const { result } = renderHook(() => useElapsedSeconds(false));
    act(() => vi.advanceTimersByTime(5_000));
    expect(result.current).toBe(0);
  });

  it("ticks once a second while active and starts again from 0 the next time", () => {
    const { result, rerender } = renderHook(({ on }) => useElapsedSeconds(on), { initialProps: { on: true } });
    expect(result.current).toBe(0);
    act(() => vi.advanceTimersByTime(999));
    expect(result.current).toBe(0);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(1);
    act(() => vi.advanceTimersByTime(89_000));
    expect(result.current).toBe(90);

    rerender({ on: false });
    expect(result.current).toBe(0);
    rerender({ on: true });
    expect(result.current).toBe(0);
    act(() => vi.advanceTimersByTime(2_000));
    expect(result.current).toBe(2);
  });
});
