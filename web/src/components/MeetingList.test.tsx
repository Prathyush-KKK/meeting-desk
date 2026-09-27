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

    expect(within(calendarRow).getByText("· Calendar")).toBeInTheDocument();
    expect(within(calendarRow).queryByLabelText("Edit meeting")).not.toBeInTheDocument();
    expect(within(calendarRow).getByLabelText("Show meeting details")).toBeInTheDocument();

    expect(within(manualRow).getByText("· Manual")).toBeInTheDocument();
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

  // Screen review round 1, R1-02: the rows' negative margins made each row wider than the list's
  // scroll box, so on a phone the box scrolled sideways and cut the first letters of every title.
  it("keeps every row inside the list box", () => {
    renderList();
    for (const row of screen.getAllByTestId("meeting-row")) {
      expect(row.className).not.toMatch(/(^|\s)-m[lrx]-/);
    }
  });

  // R1-39: a separator on its own could end a wrapped line.
  it("keeps each separator with the item after it", () => {
    renderList({ items: [meeting({ points_count: 1, attendees: [] })] });
    const meta = screen.getByTestId("meeting-meta");
    const parts = Array.from(meta.children).map((el) => el.textContent);
    expect(parts).not.toContain("·");
    expect(parts.slice(1)).toEqual(["· 0 people", "· Calendar", "· 1 point"]);
  });

  it("picks a card with Space and continues with Enter, from the keyboard (R1-45)", async () => {
    const props = renderList();
    const calendarRow = screen.getAllByTestId("meeting-row")[0];
    await userEvent.tab();
    expect(calendarRow).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(props.onSelect).toHaveBeenCalledWith(CALENDAR);
    await userEvent.keyboard("{Enter}");
    expect(props.onContinue).toHaveBeenCalledWith(CALENDAR);
  });
});
