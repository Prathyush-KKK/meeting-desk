import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MeetingList, itemKey } from "./MeetingList";
import type { MeetingItem } from "@/api/types";

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
    attendees: [{ email: "ansul.s@simpleo.ai", name: "Ansul S", response: "accepted" }],
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
  key: "M-119",
  source: "manual",
  editable: true,
  saved: true,
  title: "Sprinto call prep",
  calendar_event_id: null,
  ical_uid: null,
});

function renderList(overrides: Partial<Parameters<typeof MeetingList>[0]> = {}) {
  const props = {
    items: [CALENDAR, MANUAL],
    selectedKey: null,
    onSelect: vi.fn(),
    onOpen: vi.fn(),
    onContinue: vi.fn(),
    ...overrides,
  };
  render(<MeetingList {...props} />);
  return props;
}

describe("MeetingList", () => {
  it("shows a calendar meeting as read-only and a manual one as editable", () => {
    renderList();
    const [calendarRow, manualRow] = screen.getAllByTestId("meeting-row");

    expect(within(calendarRow).getByText("Calendar")).toBeInTheDocument();
    expect(within(calendarRow).queryByLabelText("Edit meeting")).not.toBeInTheDocument();
    expect(within(calendarRow).getByLabelText("Show meeting details")).toBeInTheDocument();

    expect(within(manualRow).getByText("Manual")).toBeInTheDocument();
    expect(within(manualRow).getByLabelText("Edit meeting")).toBeInTheDocument();
  });

  it("opens the manual card straight in edit mode from the pencil", async () => {
    const props = renderList();
    const manualRow = screen.getAllByTestId("meeting-row")[1];
    await userEvent.click(within(manualRow).getByLabelText("Edit meeting"));
    expect(props.onOpen).toHaveBeenCalledWith(MANUAL, true);
    expect(props.onSelect).not.toHaveBeenCalled(); // the pencil does not double as a row click
  });

  it("opens details read-only from the eye on a calendar card", async () => {
    const props = renderList();
    const calendarRow = screen.getAllByTestId("meeting-row")[0];
    await userEvent.click(within(calendarRow).getByLabelText("Show meeting details"));
    expect(props.onOpen).toHaveBeenCalledWith(CALENDAR, false);
  });

  it("selects on click and continues on double click", async () => {
    const props = renderList();
    const calendarRow = screen.getAllByTestId("meeting-row")[0];
    await userEvent.click(calendarRow);
    expect(props.onSelect).toHaveBeenCalledWith(CALENDAR);
    await userEvent.dblClick(calendarRow);
    expect(props.onContinue).toHaveBeenCalledWith(CALENDAR);
  });

  it("keys a calendar card on its event until it is captured", () => {
    expect(itemKey(CALENDAR)).toBe("event:evt-1");
    expect(itemKey(MANUAL)).toBe("m-1");
  });
});
