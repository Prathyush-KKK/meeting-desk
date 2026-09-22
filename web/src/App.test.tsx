// Review 1, finding 28 (the web half): `/admin/connections` became `require_admin`, and App asked
// for it on every page for the expired-connection banner. A member got a 403 every fifteen seconds
// and no banner either way, so the question is only asked when the answer can come back.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "@/App";
import type { Connections, Me } from "@/api/types";

const h = vi.hoisted(() => ({
  me: null as Me | null,
  connections: vi.fn(),
}));

vi.mock("@/api/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hooks")>();
  return {
    ...actual,
    useMe: () => ({ data: h.me, isLoading: false, error: null }),
    useConnections: h.connections,
    useMeetings: () => ({ data: { items: [], age_minutes: 0 }, isLoading: false, isError: false, error: null }),
    useRefreshMeetings: () => ({ mutate: vi.fn(), isPending: false }),
    useCaptureCalendarEvent: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateManualMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    usePatchMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeleteMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useQuickPaste: () => ({ mutateAsync: vi.fn(), isPending: false }),
  };
});

const BANNER: Connections = {
  connections: [],
  warning: "",
  banner: "ansul.s@simpleo.ai needs reconnecting. Ask prathyush.kodhanpur@simpleo.ai.",
};

function user(role: "admin" | "member"): Me {
  return {
    id: "u-1",
    email: role === "admin" ? "prathyush.kodhanpur@simpleo.ai" : "nishchay.s@simpleo.ai",
    name: "Somebody",
    role,
    is_admin: role === "admin",
  };
}

beforeEach(() => {
  h.connections.mockReset();
  // What TanStack Query hands back for a query that is not enabled.
  h.connections.mockReturnValue({ data: undefined, isLoading: false, error: null });
});

describe("the expired-connection banner", () => {
  it("is not even asked for when a member is signed in", () => {
    h.me = user("member");
    render(<App />);
    expect(h.connections).toHaveBeenCalled();
    expect(h.connections.mock.calls.every((call) => call[0] === false)).toBe(true);
    expect(screen.queryByTestId("connection-banner")).toBeNull();
  });

  it("is asked for and shown to an admin", () => {
    h.me = user("admin");
    h.connections.mockReturnValue({ data: BANNER, isLoading: false, error: null });
    render(<App />);
    expect(h.connections.mock.calls.every((call) => call[0] === true)).toBe(true);
    expect(screen.getByTestId("connection-banner")).toHaveTextContent("needs reconnecting");
  });

  it("stays unasked while it is still unknown who is signed in", () => {
    h.me = null;
    render(<App />);
    expect(h.connections.mock.calls.every((call) => call[0] === false)).toBe(true);
  });

  it("carries no colour of its own", () => {
    h.me = user("admin");
    h.connections.mockReturnValue({ data: BANNER, isLoading: false, error: null });
    render(<App />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner.className).not.toMatch(/warn|bad|destructive/);
    expect(banner.className).toContain("border-b");
  });
});
