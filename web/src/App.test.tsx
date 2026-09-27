// The banner on every page. Spec section 7: "Admin connection expires: a banner on every page names
// the connection and the admin; paste, points and manual meetings keep working without Google."
//
// Review 1, finding 28 made `/admin/connections` admin-only, and App used to read the banner from
// it - so it stopped asking for members, and members saw no banner at all (screen review R1-23).
// The banner now comes from `/admin/connections/status`, which anyone signed in may read and which
// carries nothing but what the banner says.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "@/App";
import type { ConnectionStatus, Me } from "@/api/types";

const h = vi.hoisted(() => ({
  me: null as Me | null,
  status: vi.fn(),
  connections: vi.fn(),
}));

vi.mock("@/api/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hooks")>();
  return {
    ...actual,
    useMe: () => ({ data: h.me, isLoading: false, error: null }),
    useConnectionStatus: h.status,
    useConnections: h.connections,
    useMeetings: () => ({ data: { items: [], age_minutes: 0 }, isLoading: false, isError: false, error: null }),
    useRefreshMeetings: () => ({ mutate: vi.fn(), isPending: false }),
    useCaptureCalendarEvent: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateManualMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    usePatchMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeleteMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useRestoreMeeting: () => ({ mutate: vi.fn() }),
    useQuickPaste: () => ({ mutateAsync: vi.fn(), isPending: false }),
  };
});

const BANNER: ConnectionStatus = {
  banner: "Google connection needs reconnecting: ansul.s@simpleo.ai. Paste, points and manual meetings keep working.",
  first_run: false,
  first_run_notice: "",
  can_connect: true,
};

const FIRST_RUN: ConnectionStatus = {
  banner: "",
  first_run: true,
  first_run_notice: "No Google account is connected yet.",
  can_connect: true,
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
  h.status.mockReset();
  h.connections.mockReset();
  // What TanStack Query hands back for a query that is not enabled.
  h.status.mockReturnValue({ data: undefined, isLoading: false, error: null });
  h.connections.mockReturnValue({ data: undefined, isLoading: false, error: null });
});

describe("the expired-connection banner", () => {
  it("reaches a member too (R1-23)", () => {
    h.me = user("member");
    h.status.mockReturnValue({ data: { ...BANNER, can_connect: false }, isLoading: false, error: null });
    render(<App />);
    expect(h.status.mock.calls.every((call) => call[0] === true)).toBe(true);
    expect(screen.getByTestId("connection-banner")).toHaveTextContent("ansul.s@simpleo.ai");
    // The admin-only list is never asked for on a member's behalf (finding 28).
    expect(h.connections.mock.calls.every((call) => call[0] !== true)).toBe(true);
  });

  it("is shown to an admin", () => {
    h.me = user("admin");
    h.status.mockReturnValue({ data: BANNER, isLoading: false, error: null });
    render(<App />);
    expect(screen.getByTestId("connection-banner")).toHaveTextContent("needs reconnecting");
  });

  it("stays unasked while it is still unknown who is signed in", () => {
    h.me = null;
    render(<App />);
    expect(h.status.mock.calls.every((call) => call[0] === false)).toBe(true);
  });

  it("carries no colour of its own", () => {
    h.me = user("admin");
    h.status.mockReturnValue({ data: BANNER, isLoading: false, error: null });
    render(<App />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner.className).not.toMatch(/warn|bad|destructive/);
    expect(banner.className).toContain("border-b");
  });
});

describe("the first-run notice", () => {
  it("offers an admin the connect flow, returning to Step 1, when nothing is connected", () => {
    h.me = user("admin");
    h.status.mockReturnValue({ data: FIRST_RUN, isLoading: false, error: null });
    render(<App />);
    const banner = screen.getByTestId("first-run-banner");
    expect(banner.textContent).toContain("No Google account is connected yet.");
    const link = banner.querySelector("a");
    expect(link?.getAttribute("href")).toMatch(/\/admin\/connections\/connect\?next=\/$/);
    expect(screen.queryByTestId("connection-banner")).toBeNull();
  });

  it("gives a member the notice without a link they could not use", () => {
    h.me = user("member");
    h.status.mockReturnValue({
      data: { ...FIRST_RUN, first_run_notice: "No Google account is connected yet. Ask an admin.", can_connect: false },
      isLoading: false,
      error: null,
    });
    render(<App />);
    const banner = screen.getByTestId("first-run-banner");
    expect(banner).toHaveTextContent("Ask an admin.");
    expect(banner.querySelector("a")).toBeNull();
  });

  it("gives way to the reconnect banner", () => {
    h.me = user("admin");
    h.status.mockReturnValue({ data: { ...BANNER, first_run: true, first_run_notice: "x" }, isLoading: false, error: null });
    render(<App />);
    expect(screen.getByTestId("connection-banner")).toBeTruthy();
    expect(screen.queryByTestId("first-run-banner")).toBeNull();
  });
});

// Screen review R2-01: a toast with Undo sat on the step's primary button for ten seconds.
describe("toasts", () => {
  it("never sit bottom right, where every step keeps its primary button", async () => {
    const { toastPosition } = await import("@/App");
    expect(toastPosition(false)).toBe("bottom-center"); // from 768 px: over hint text at most
    expect(toastPosition(true)).toBe("top-center"); // a phone's bottom is all buttons
  });
});
