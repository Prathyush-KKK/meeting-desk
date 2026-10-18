// Screen review round 1: the Step 1 fixes that are behaviour rather than layout.
//
//   R1-03  "updated N min ago" and Refresh are shown at every width, under the list.
//   R1-04  a click on another card while the detail is open moves the detail to that card, and the
//          list's own Continue steps aside for the panel's.
//   R1-21  deleting a manual meeting offers Undo for ten seconds (spec section 7).
//   empty  the empty list says what to do.
//   history a saved meeting's detail shows its extraction runs and transfers, and opens its pages.

import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MeetingStep } from "@/pages/MeetingStep";
import type { ExtractionRecord, MeetingItem, Transfer } from "@/api/types";

const h = vi.hoisted(() => ({
  items: [] as MeetingItem[],
  remove: vi.fn(() => Promise.resolve({ ok: true, id: "m-1" })),
  restore: vi.fn(),
  refresh: vi.fn(),
  openStep: vi.fn(),
  extractions: [] as ExtractionRecord[],
  transfers: [] as Transfer[],
  historyFor: [] as (string | null)[],
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
  useExtractions: (id: string | null) => { h.historyFor.push(id); return { data: h.extractions, isLoading: false }; },
  useMeetingTransfers: () => ({ data: h.transfers, isLoading: false }),
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
    organizer_email: "alex.s@example.com",
    organizer_name: "Alex S",
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
  title: "Northwind call prep",
  calendar_event_id: null,
  ical_uid: null,
});

/** The selection lives above the page, as it does in App. */
function Harness() {
  const [key, setKey] = useState<string | null>(null);
  return <MeetingStep selectedKey={key} onSelectKey={setKey} onContinue={() => {}} onOpenStep={h.openStep} />;
}

beforeEach(() => {
  h.items = [CALENDAR, MANUAL];
  h.remove.mockClear();
  h.restore.mockClear();
  toast.message.mockClear();
  h.openStep.mockClear();
  h.extractions = [];
  h.transfers = [];
  h.historyFor = [];
});

function run(over: Partial<ExtractionRecord>): ExtractionRecord {
  return { id: "e-1", meeting_id: "m-1", provider: "bedrock", model: "gemma-4", region: "us-east-1", status: "done", fallback_from: null, error: null, ...over };
}

function transfer(over: Partial<Transfer>): Transfer {
  return {
    id: "t-1",
    batch_id: "b-1",
    at: "2026-09-22T17:02:00+05:30",
    actor: "alex.s@example.com",
    meeting_id: "m-1",
    meeting_title: "Northwind call prep",
    point_text: "Send the Northwind questionnaire",
    workbook_id: "wb-1",
    sheet_id: "1234",
    mode: "append",
    cells: ["A5"],
    snapshot: {},
    previous: {},
    undone_at: null,
    ...over,
  };
}

describe("MeetingStep", () => {
  it("moves the open detail to the card that was clicked", async () => {
    render(<Harness />);
    const [calendarRow, manualRow] = screen.getAllByTestId("meeting-row");
    await userEvent.click(within(calendarRow).getByLabelText("Show meeting details"));
    expect(within(screen.getByTestId("meeting-detail")).getByRole("heading")).toHaveTextContent("Platform squad sync");

    await userEvent.click(manualRow);
    expect(within(screen.getByTestId("meeting-detail")).getByRole("heading")).toHaveTextContent("Northwind call prep");
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

  it("shows a saved meeting's history and opens its notes or points from the detail", async () => {
    h.items = [CALENDAR, { ...MANUAL, notes_count: 2, points_count: 1 }];
    const longError = `Bedrock timed out reading the model answer. ${"x".repeat(300)}`;
    h.extractions = [
      run({ id: "e-3", status: "error", error: longError }),
      run({ id: "e-2", provider: "fake", model: "rule-based", created_points: 4 }),
      run({ id: "e-1" }),
    ];
    h.transfers = [
      transfer({ id: "t-2", point_text: "Share the deck", undone_at: "2026-09-22T17:05:00+05:30", snapshot: { sheet_title: "Roadmap" } }),
      transfer({}),
    ];
    render(<Harness />);
    await userEvent.click(within(screen.getAllByTestId("meeting-row")[1]).getByLabelText("Show meeting details"));
    const history = within(screen.getByTestId("meeting-history"));
    expect(h.historyFor).toContain("m-1");
    expect(screen.getByTestId("meeting-history")).toHaveTextContent(/^2 notes1 point/);

    const runs = history.getAllByTestId("extraction-line");
    expect(runs.map((r) => r.dataset.status)).toEqual(["error", "done", "done"]); // newest first, as the API sends them
    const error = runs[0].querySelector("[title]")!;
    expect(error.getAttribute("title")).toBe(longError);
    expect(error.textContent!.length).toBeLessThanOrEqual(160);
    expect(error.textContent).toMatch(/^Bedrock timed out.*…$/);
    expect(runs[1]).toHaveTextContent("rule-based fake · done · 4 new");
    expect(runs[2]).toHaveTextContent("gemma-4 · done · 0 new");

    const lines = history.getAllByTestId("transfer-line");
    // ICU writes "Sep" or "Sept" for en-GB depending on its version.
    expect(lines[0]).toHaveTextContent(/^Share the deck → Roadmap · Tue 22 Sept? 17:02 · alex\.s · undone$/);
    expect(lines[1]).toHaveTextContent("Send the Northwind questionnaire → sheet 1234");
    expect(lines[1]).not.toHaveTextContent("undone");

    await userEvent.click(history.getByRole("button", { name: "Open points" }));
    expect(h.openStep).toHaveBeenCalledWith("m-1", "points");
    await userEvent.click(history.getByRole("button", { name: "Open notes" }));
    expect(h.openStep).toHaveBeenCalledWith("m-1", "notes");
  });

  it("says when nothing has been extracted or transferred yet", async () => {
    render(<Harness />);
    await userEvent.click(within(screen.getAllByTestId("meeting-row")[1]).getByLabelText("Show meeting details"));
    const history = screen.getByTestId("meeting-history");
    expect(history).toHaveTextContent("No extraction yet.");
    expect(history).toHaveTextContent("Nothing transferred yet.");
  });

  it("has no history for a calendar card that was never captured", async () => {
    render(<Harness />);
    await userEvent.click(within(screen.getAllByTestId("meeting-row")[0]).getByLabelText("Show meeting details"));
    expect(screen.queryByTestId("meeting-history")).not.toBeInTheDocument();
    expect(screen.getByTestId("meeting-detail")).toHaveTextContent("Not captured yet. Continue captures it.");
  });

  it("opens a saved meeting's points from its card", async () => {
    h.items = [CALENDAR, { ...MANUAL, points_count: 3 }];
    render(<Harness />);
    await userEvent.click(screen.getByTestId("open-points"));
    expect(h.openStep).toHaveBeenCalledWith("m-1", "points");
  });
});
