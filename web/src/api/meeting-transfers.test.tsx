// One meeting's transfer log: GET /transfers?meeting_id=, under a key of its own that a write
// still invalidates.

import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { invalidateAfterWrite, qk, useMeetingTransfers } from "@/api/hooks";

const fetchMock = vi.fn(async () => new Response(JSON.stringify([{ id: "t-1", point_text: "Send the deck" }]), { status: 200 }));

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockClear();
});

describe("useMeetingTransfers", () => {
  it("asks for one meeting's transfers", async () => {
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useMeetingTransfers("m-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toMatch(/\/transfers\?meeting_id=m-1$/);
    expect(client.getQueryData(["transfers", "meeting", "m-1"])).toHaveLength(1);
  });

  it("asks nothing without a meeting", () => {
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient();
    const { result } = renderHook(() => useMeetingTransfers(null), { wrapper: wrapper(client) });
    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps off a workbook's key, and goes stale after a transfer or an undo", () => {
    expect(qk.meetingTransfers("m-1")).not.toEqual(qk.transfers("m-1"));
    const client = new QueryClient();
    client.setQueryData(qk.meetingTransfers("m-1"), []);
    invalidateAfterWrite(client, "wb-1", "1234");
    expect(client.getQueryState(qk.meetingTransfers("m-1"))?.isInvalidated).toBe(true);
  });
});
