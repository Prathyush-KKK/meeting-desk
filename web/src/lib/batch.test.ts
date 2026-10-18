// The id is per user intent, not per attempt.

import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { isDefiniteRefusal, newBatchId, useBatchId } from "@/lib/batch";
import { ApiError } from "@/api/client";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("newBatchId", () => {
  it("is a v4 uuid, and a different one every time", () => {
    const ids = new Set(Array.from({ length: 200 }, newBatchId));
    expect(ids.size).toBe(200);
    for (const id of ids) expect(id).toMatch(UUID);
  });
});

describe("isDefiniteRefusal", () => {
  it("is true for a refusal the server actually gave", () => {
    expect(isDefiniteRefusal(new ApiError(409, "That row is in or above the header.", {}))).toBe(true);
    expect(isDefiniteRefusal(new ApiError(403, "no", {}))).toBe(true);
    expect(isDefiniteRefusal(new ApiError(422, "no", {}))).toBe(true);
  });

  it("is false when nobody knows whether the write landed", () => {
    // status 0 is the client's own "the API is not reachable"; a 500 may have written first.
    expect(isDefiniteRefusal(new ApiError(0, "The API is not reachable.", {}))).toBe(false);
    expect(isDefiniteRefusal(new ApiError(500, "boom", {}))).toBe(false);
    expect(isDefiniteRefusal(new ApiError(502, "boom", {}))).toBe(false);
    expect(isDefiniteRefusal(new Error("TypeError: failed to fetch"))).toBe(false);
  });
});

describe("useBatchId", () => {
  it("hands out the same id until the write settles, so a retry cannot double-write", () => {
    const { result } = renderHook(() => useBatchId());
    const first = result.current.take();
    expect(result.current.take()).toBe(first);
    expect(result.current.take()).toBe(first);

    act(() => result.current.reset());
    expect(result.current.take()).not.toBe(first);
  });

  it("keeps the id when the outcome is unknown and drops it when the server refused", () => {
    const { result } = renderHook(() => useBatchId());

    const attempt = result.current.take();
    act(() => result.current.settle(new ApiError(0, "The API is not reachable.", {})));
    expect(result.current.take()).toBe(attempt);

    act(() => result.current.settle(new ApiError(503, "upstream", {})));
    expect(result.current.take()).toBe(attempt);

    // A 409 is an answer: nothing was written, and the next press carries a different body.
    act(() => result.current.settle(new ApiError(409, "Pick one.", {})));
    const afterRefusal = result.current.take();
    expect(afterRefusal).not.toBe(attempt);

    // Success settles with no error at all.
    act(() => result.current.settle());
    expect(result.current.take()).not.toBe(afterRefusal);
  });
});
