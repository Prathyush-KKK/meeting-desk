// The banner on every page. Spec section 7: "Admin connection expires: a banner on every page names
// the connection and the admin; paste, points and manual meetings keep working without Google."
//
// Review 1, finding 28 made `/admin/connections` admin-only, and App used to read the banner from
// it - so it stopped asking for members, and members saw no banner at all (screen review R1-23).
// The banner now comes from `/admin/connections/status`, which anyone signed in may read and which
// carries nothing but what the banner says.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "@/App";
import type { ConnectionStatus, Me, MeetingItem } from "@/api/types";

const h = vi.hoisted(() => ({
  me: null as Me | null,
  status: vi.fn(),
  connections: vi.fn(),
  items: [] as MeetingItem[],
}));

vi.mock("@/api/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hooks")>();
  return {
    ...actual,
    useMe: () => ({ data: h.me, isLoading: false, error: null }),
    useConnectionStatus: h.status,
    useConnections: h.connections,
    useMeetings: () => ({ data: { items: h.items, age_minutes: 0 }, isLoading: false, isError: false, error: null }),
    useRefreshMeetings: () => ({ mutate: vi.fn(), isPending: false }),
    useCaptureCalendarEvent: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateManualMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    usePatchMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeleteMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useRestoreMeeting: () => ({ mutate: vi.fn() }),
    useQuickPaste: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useExtractions: () => ({ data: [], isLoading: false }),
    useMeetingTransfers: () => ({ data: [], isLoading: false }),
  };
});

// The steps themselves have their own tests; here only which meeting and which step App opens.
vi.mock("@/pages/NotesStep", () => ({ NotesStep: ({ meeting }: { meeting: MeetingItem }) => <div data-testid="page">notes:{meeting.id}</div> }));
vi.mock("@/pages/PointsStep", () => ({ PointsStep: ({ meeting }: { meeting: MeetingItem }) => <div data-testid="page">points:{meeting.id}</div> }));
vi.mock("@/pages/TransferStep", () => ({ TransferStep: ({ meeting }: { meeting: MeetingItem }) => <div data-testid="page">transfer:{meeting.id}</div> }));

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
  // App reads and writes its place in the URL; each test starts on Step 1 with nothing open.
  window.history.replaceState(null, "", "/");
  h.items = [];
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

function meeting(over: Partial<MeetingItem>): MeetingItem {
  return {
    id: null, key: null, source: "calendar", title: "A meeting", description: "", location: "",
    date: "2026-09-01", start: "16:00", end: "16:48", start_at: null, end_at: null, timezone: "Asia/Kolkata",
    organizer_email: "ansul.s@simpleo.ai", organizer_name: "Ansul S", attendees: [], conference: {}, attachments: [],
    calendar_event_id: "evt-1", ical_uid: null, recurring_event_id: null, html_link: null, workstream: "Platform",
    step: "meeting", in_progress_by: null, editable: false, saved: false, notes_count: 0, points_count: 0,
    ...over,
  };
}

const SAVED = meeting({ id: "m-1", key: "M-101", saved: true, title: "Vendor call with Madhu", calendar_event_id: "evt-1", points_count: 2 });
const OTHER = meeting({ id: "m-2", key: "M-102", saved: true, title: "Sprinto call prep", calendar_event_id: "evt-2" });
const CARD = meeting({ title: "Platform squad sync", calendar_event_id: "evt-3" });

// "I should be able to access the meeting pages regardless of when it's coming up": a saved meeting
// opens at its notes or points without going through Continue first.
describe("the step bar", () => {
  const bar = () => within(document.querySelector("header ol") as HTMLElement);
  const stepButton = (label: string) => bar().getByRole("button", { name: new RegExp(`${label}$`) });
  const row = (title: string) => screen.getAllByTestId("meeting-row").find((r) => r.textContent?.includes(title))!;

  beforeEach(() => {
    h.me = user("admin");
    h.items = [SAVED, OTHER, CARD];
  });

  it("opens Notes and Points for a saved meeting picked on Step 1, adopting it", async () => {
    render(<App />);
    expect(stepButton("Points")).toBeDisabled();
    await userEvent.click(row("Vendor call with Madhu"));
    expect(stepButton("Notes")).toBeEnabled();
    expect(stepButton("Points")).toBeEnabled();
    expect(stepButton("Transfer")).toBeDisabled(); // no points were picked on any meeting
    await userEvent.click(stepButton("Points"));
    expect(screen.getByTestId("page")).toHaveTextContent("points:m-1");
    expect(screen.getByTestId("current-meeting")).toHaveTextContent("Vendor call with Madhu");
    expect(window.location.search).toContain("meeting=m-1");
    await userEvent.click(stepButton("Notes"));
    expect(screen.getByTestId("page")).toHaveTextContent("notes:m-1");
  });

  it("stays shut for a calendar card that has no record yet", async () => {
    render(<App />);
    await userEvent.click(row("Platform squad sync"));
    expect(stepButton("Notes")).toBeDisabled();
    expect(stepButton("Points")).toBeDisabled();
  });

  it("follows the highlighted card, not the meeting from an earlier visit kept in the URL", async () => {
    window.history.replaceState(null, "", "/?page=capture&step=meeting&meeting=m-1");
    render(<App />);
    await userEvent.click(row("Sprinto call prep"));
    // Transfer carries points picked on another meeting, so it waits for this one's Step 3.
    expect(stepButton("Transfer")).toBeDisabled();
    await userEvent.click(stepButton("Points"));
    expect(screen.getByTestId("page")).toHaveTextContent("points:m-2");
  });

  it("opens a meeting's points from the count on its card", async () => {
    render(<App />);
    await userEvent.click(within(row("Vendor call with Madhu")).getByTestId("open-points"));
    expect(screen.getByTestId("page")).toHaveTextContent("points:m-1");
  });

  it("opens a meeting's notes from its detail panel", async () => {
    render(<App />);
    await userEvent.click(within(row("Sprinto call prep")).getByLabelText("Show meeting details"));
    await userEvent.click(within(screen.getByTestId("meeting-history")).getByRole("button", { name: "Open notes" }));
    expect(screen.getByTestId("page")).toHaveTextContent("notes:m-2");
  });
});
