// Screen review round 1: the Step 1 fixes that are behaviour rather than layout.
//
//   R1-03  "updated N min ago" and Refresh are shown at every width, under the list.
//   R1-04  a click on another card while the detail is open moves the detail to that card, and the
//          list's own Continue steps aside for the panel's.
//   R1-21  deleting a manual meeting offers Undo for ten seconds (spec section 7).
//   empty  the empty list says what to do.

import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MeetingStep } from "@/pages/MeetingStep";
import type { MeetingItem } from "@/api/types";

const h = vi.hoisted(() => ({
  items: [] as MeetingItem[],
  remove: vi.fn(() => Promise.resolve({ ok: true, id: "m-1" })),
  restore: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("@/api/hooks", () => ({
  useMeetings: () => ({ data: { items: h.items, age_minutes: 3, empty_hint: h.items.length ? "" : "No meeting here? Add one, or paste the notes straight into the box above." }, isLoading: false, isError: false }),
  useRefreshMeetings: () => ({ mutate: h.refresh, isPending: false }),
  useCaptureCalendarEvent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateManualMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useQuickPaste: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchMeeting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteMeeting: () => ({ mutateAsync: h.remove }),
  useRestoreMeeting: () => ({ mutate: h.restore }),
}));

const toast = vi.hoisted(() => Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), message: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

function meeting(over: Partial<MeetingItem>): MeetingItem {
  return {
    id: null,
    key: null,
    source: "calendar",
    title: "A meeting",
    description: "",
    location: "",
    date: "2026-09-22",
    start: "16:00",
    end: "16:48",
    start_at: "2026-09-22T16:00:00+05:30",
    end_at: "2026-09-22T16:48:00+05:30",
    timezone: "Asia/Kolkata",
    organizer_email: "ansul.s@simpleo.ai",
    organizer_name: "Ansul S",
    attendees: [],
    conference: {},
    attachments: [],
    calendar_event_id: "evt-1",
    ical_uid: "evt-1@google.com",
    recurring_event_id: null,
    html_link: null,
    workstream: "Platform",
    step: "meeting",
    in_progress_by: null,
    editable: false,
    saved: false,
    notes_count: 0,
    points_count: 0,
    ...over,
  };
}

const CALENDAR = meeting({ title: "Platform squad sync" });
const MANUAL = meeting({
  id: "m-1",
  key: "M-116",
  source: "manual",
  editable: true,
  saved: true,
  title: "Sprinto call prep",
  calendar_event_id: null,
  ical_uid: null,
});

/** The selection lives above the page, as it does in App. */
function Harness() {
  const [key, setKey] = useState<string | null>(null);
  return <MeetingStep selectedKey={key} onSelectKey={setKey} onContinue={() => {}} />;
}

beforeEach(() => {
  h.items = [CALENDAR, MANUAL];
  h.remove.mockClear();
  h.restore.mockClear();
  toast.message.mockClear();
});

describe("MeetingStep", () => {
  it("moves the open detail to the card that was clicked", async () => {
    render(<Harness />);
    const [calendarRow, manualRow] = screen.getAllByTestId("meeting-row");
    await userEvent.click(within(calendarRow).getByLabelText("Show meeting details"));
    expect(within(screen.getByTestId("meeting-detail")).getByRole("heading")).toHaveTextContent("Platform squad sync");

    await userEvent.click(manualRow);
    expect(within(screen.getByTestId("meeting-detail")).getByRole("heading")).toHaveTextContent("Sprinto call prep");
  });

  it("leaves one Continue beside the open detail", async () => {
    render(<Harness />);
    const listContinue = () => screen.getAllByRole("button", { name: "Continue" })[0];
    expect(listContinue().className).not.toMatch(/md:hidden/);
    await userEvent.click(within(screen.getAllByTestId("meeting-row")[0]).getByLabelText("Show meeting details"));
    const buttons = screen.getAllByRole("button", { name: "Continue" });
    expect(buttons).toHaveLength(2);
    expect(buttons[0].className).toMatch(/md:hidden/); // the list's, under the panel from 768 px
    expect(within(screen.getByTestId("meeting-detail")).getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("says how old the calendar list is, at every width, with Refresh beside it", async () => {
    render(<Harness />);
    const age = screen.getByTestId("calendar-age");
    expect(age).toHaveTextContent("updated 3 min ago");
    expect(age.className).not.toMatch(/hidden/);
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(h.refresh).toHaveBeenCalledTimes(1);
  });

  it("offers Undo for ten seconds after deleting a manual meeting", async () => {
    render(<Harness />);
    await userEvent.click(within(screen.getAllByTestId("meeting-row")[1]).getByLabelText("Edit meeting"));
    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));
    expect(h.remove).toHaveBeenCalledWith("m-1");
    expect(toast.message).toHaveBeenCalledTimes(1);
    const [, options] = toast.message.mock.calls[0] as [string, { duration: number; action: { label: string; onClick: () => void } }];
    expect(options.duration).toBe(10_000);
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    expect(h.restore).toHaveBeenCalledWith("m-1");
  });

  it("says what to do when there are no meetings, without an empty list under it", () => {
    h.items = [];
    render(<Harness />);
    expect(screen.getByText("No meeting here? Add one, or paste the notes straight into the box above.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
