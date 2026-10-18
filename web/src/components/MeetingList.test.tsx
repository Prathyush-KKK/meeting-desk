import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
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
    organizer_email: "alex.s@example.com",
    organizer_name: "Alex S",
    attendees: [{ email: "alex.s@example.com", name: "Alex S", response: "accepted" }],
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
  title: "Northwind call prep",
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
    onOpenNotes: vi.fn(),
    onOpenPoints: vi.fn(),
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

  // The rows' negative margins used to make each row wider than the list's
  // scroll box, so on a phone the box scrolled sideways and cut the first letters of every title.
  it("keeps every row inside the list box", () => {
    renderList();
    for (const row of screen.getAllByTestId("meeting-row")) {
      expect(row.className).not.toMatch(/(^|\s)-m[lrx]-/);
    }
  });

  // A separator on its own could end a wrapped line.
  it("keeps each separator with the item after it", () => {
    renderList({ items: [meeting({ points_count: 1, attendees: [] })] });
    const meta = screen.getByTestId("meeting-meta");
    const parts = Array.from(meta.children).map((el) => el.textContent);
    expect(parts).not.toContain("·");
    expect(parts.slice(1)).toEqual(["· 0 people", "· Calendar", "· 1 point"]);
  });

  it("picks a card with Space and continues with Enter, from the keyboard", async () => {
    const props = renderList();
    const calendarRow = screen.getAllByTestId("meeting-row")[0];
    await userEvent.tab();
    expect(calendarRow).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(props.onSelect).toHaveBeenCalledWith(CALENDAR);
    await userEvent.keyboard("{Enter}");
    expect(props.onContinue).toHaveBeenCalledWith(CALENDAR);
  });

  it("opens a saved meeting's points or notes straight from its counts, without picking the row", async () => {
    const saved = { ...MANUAL, notes_count: 2, points_count: 3 };
    const props = renderList({ items: [saved] });
    const row = screen.getByTestId("meeting-row");
    expect(within(row).getByTestId("meeting-meta")).toHaveTextContent("· 2 notes· 3 points");

    await userEvent.click(within(row).getByRole("button", { name: "Open points" }));
    expect(props.onOpenPoints).toHaveBeenCalledWith(saved);
    await userEvent.click(within(row).getByTestId("open-notes"));
    expect(props.onOpenNotes).toHaveBeenCalledWith(saved);
    await userEvent.dblClick(within(row).getByTestId("open-points"));
    expect(props.onSelect).not.toHaveBeenCalled();
    expect(props.onContinue).not.toHaveBeenCalled();
  });

  it("leaves a calendar card's counts as plain text: there is no record to open yet", () => {
    renderList({ items: [meeting({ points_count: 2, notes_count: 1 })] });
    expect(screen.queryByTestId("open-points")).not.toBeInTheDocument();
    expect(screen.queryByTestId("open-notes")).not.toBeInTheDocument();
    expect(screen.getByTestId("meeting-meta")).toHaveTextContent("· 2 points");
    expect(screen.getByTestId("meeting-meta")).not.toHaveTextContent("note");
  });
});

// The calendar window runs 30 days back and 14 ahead; the list says which side of today each is on.
describe("MeetingList groups", () => {
  afterEach(() => vi.useRealTimers());

  const at = (date: string) => {
    // Only the clock: user-event needs real timers.
    vi.useFakeTimers({ toFake: ["Date"] });
    const [y, m, d] = date.split("-").map(Number);
    vi.setSystemTime(new Date(y, m - 1, d, 0, 30)); // 00:30 local: in IST, UTC is still the day before
  };

  it("splits the rows into Upcoming, Today and Earlier, keeping the order inside each", () => {
    at("2026-09-22");
    const items = [
      meeting({ id: "u-2", title: "Later still", date: "2026-10-01" }),
      meeting({ id: "u-1", title: "Tomorrow", date: "2026-09-23" }),
      meeting({ id: "t-1", title: "This afternoon", date: "2026-09-22" }),
      meeting({ id: "e-1", title: "Last week", date: "2026-09-15" }),
      meeting({ id: "e-2", title: "No date", date: null }),
    ];
    renderList({ items });
    const groups = screen.getAllByTestId("meeting-group");
    expect(groups.map((g) => g.dataset.group)).toEqual(["upcoming", "today", "earlier"]);
    const titles = (g: HTMLElement) => within(g).getAllByTestId("meeting-row").map((r) => r.querySelector("span")?.textContent);
    expect(groups[0]).toHaveTextContent(/^Upcoming/);
    expect(titles(groups[0])).toEqual(["Later still", "Tomorrow"]);
    expect(titles(groups[1])).toEqual(["This afternoon"]);
    expect(titles(groups[2])).toEqual(["Last week", "No date"]);
  });

  it("skips a group with nothing in it", () => {
    at("2026-09-22");
    renderList({ items: [meeting({ date: "2026-09-10" })] });
    expect(screen.getAllByTestId("meeting-group").map((g) => g.dataset.group)).toEqual(["earlier"]);
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("keeps Tab, Space and Enter on the rows across groups", async () => {
    at("2026-09-22");
    const upcoming = meeting({ id: "u-1", title: "Tomorrow", date: "2026-09-23" });
    const props = renderList({ items: [upcoming, CALENDAR] });
    await userEvent.tab();
    expect(screen.getAllByTestId("meeting-row")[0]).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(props.onSelect).toHaveBeenCalledWith(upcoming);
  });
});
