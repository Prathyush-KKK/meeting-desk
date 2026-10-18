// Step 4:
//   prereq the prerequisites: with no workbook there is a Connect right here, and a reload (which
//          loses the ids passed from Step 3) falls back to the points ticked there, or offers the
//          way back to them - it used to be a one-line dead end either way.
//   anchor an anchor in or above the header is blocked with one line and no plan beside it.
//   count  "Write 1 cell", not "Write 1 cells".

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TransferStep } from "@/pages/TransferStep";
import type { MeetingItem, Point, TabState, Workbook } from "@/api/types";

const h = vi.hoisted(() => ({
  books: [] as unknown[],
  active: [] as unknown[],
  preview: vi.fn(),
  previewData: null as unknown,
  tab: null as unknown,
}));

vi.mock("@/api/hooks", () => ({
  useWorkbooks: () => ({ data: h.books, isLoading: false }),
  usePoints: (_m: string, lifecycle: string) => ({ data: lifecycle === "active" ? h.active : [], isLoading: false }),
  useTab: () => ({ data: h.tab, refetch: vi.fn() }),
  useTransferPreview: (input: unknown) => {
    h.preview(input);
    return { data: input ? h.previewData : undefined, isError: false, refetch: vi.fn() };
  },
  useTransferExecute: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUndoTransfer: () => ({ mutateAsync: vi.fn() }),
  useConnectWorkbook: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const MEETING = { id: "m-1", title: "Vendor call with Maya", date: "2026-09-22" } as unknown as MeetingItem;

const BOOK: Workbook = {
  id: "wb-1",
  spreadsheet_id: "ss-1",
  name: "Mobile App Product Roadmap",
  url: "https://docs.google.com/spreadsheets/d/ss-1",
  connection_id: "c-1",
  connected_by: "daniel.okafor@example.com",
  connected_at: "2026-09-21T09:00:00+05:30",
  last_read_at: null,
  can_edit: true,
  last_error: null,
  tabs: [{ sheet_id: "t1", title: "P1 Resolve & Log", index: 0 }],
};

const VALUES = [
  ["P1 Resolve & Log", "", "", "", ""],
  ["ID", "Task", "Owner", "Due", "Status"],
  ["T-101", "Photo capture flow", "Anna Moreno", "5 Sep", "done"],
  ["T-102", "Manual entry flow", "Anna Moreno", "5 Sep", "done"],
  ["", "", "", "", ""],
];

const TAB = {
  workbook_id: "wb-1",
  sheet_id: "t1",
  title: "P1 Resolve & Log",
  values: VALUES,
  dropdowns: {},
  read_at: "2026-09-22T17:02:00+05:30",
} as unknown as TabState;

function point(id: string, selected: boolean): Point {
  return {
    id,
    meeting_id: "m-1",
    kind: "action",
    text: `Point ${id}`,
    owner_text: "Alex S",
    due_text: "by Friday",
    status: "open",
    lifecycle: "active",
    selected,
  } as unknown as Point;
}

const renderStep = (pointIds: string[] = [], onBack = vi.fn()) => {
  render(<TransferStep meeting={MEETING} pointIds={pointIds} onBack={onBack} onDone={vi.fn()} />);
  return onBack;
};

beforeEach(() => {
  h.books = [BOOK];
  h.active = [point("p-1", true), point("p-2", false)];
  h.tab = TAB;
  h.previewData = { plan: { cells: ["B5"] }, region_hash: "h", warnings: [] };
  h.preview.mockClear();
});

describe("TransferStep prerequisites", () => {
  it("offers Connect right here when no workbook is connected", () => {
    h.books = [];
    renderStep(["p-1"]);
    const block = screen.getByTestId("transfer-prerequisites");
    expect(block).toHaveTextContent("none connected yet");
    expect(within(block).getByLabelText("Google Sheets URL")).toBeInTheDocument();
    expect(within(block).getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("uses the points ticked on Step 3 when the page was reloaded without ids", () => {
    renderStep([]);
    expect(screen.queryByTestId("transfer-prerequisites")).not.toBeInTheDocument();
    const inputs = h.preview.mock.calls.map(([input]) => input).filter(Boolean) as { point_ids: string[] }[];
    expect(inputs.at(-1)?.point_ids).toEqual(["p-1"]);
  });

  it("offers the way back when no point is ticked at all", async () => {
    h.active = [point("p-1", false)];
    const onBack = renderStep([]);
    const block = screen.getByTestId("transfer-prerequisites");
    expect(block).toHaveTextContent("none selected");
    await userEvent.click(within(block).getByRole("button", { name: "Back to points" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe("TransferStep custom fill", () => {
  it("blocks an anchor in the header with one line and no plan", async () => {
    renderStep(["p-1"]);
    await userEvent.click(screen.getByRole("button", { name: "Custom fill" }));
    h.preview.mockClear();
    await userEvent.click(document.querySelector('[data-cell="1,1"]') as HTMLElement);
    expect(screen.getByTestId("anchor-blocked")).toHaveTextContent("Pick a cell below the header row (row 2).");
    expect(screen.queryByText("Skip them, keep values")).not.toBeInTheDocument();
    expect(h.preview.mock.calls.every(([input]) => input === null)).toBe(true);
    expect(screen.getByRole("button", { name: "Pick a cell" })).toBeDisabled();
  });

  it("counts one cell as one cell", async () => {
    renderStep(["p-1"]);
    await userEvent.click(screen.getByRole("button", { name: "Custom fill" }));
    await userEvent.click(document.querySelector('[data-cell="4,1"]') as HTMLElement);
    expect(screen.getByRole("button", { name: "Write 1 cell" })).toBeInTheDocument();
  });
});

describe("TransferStep read-only workbook", () => {
  it("says the workbook is read-only and keeps the write button off", () => {
    h.books = [{ ...BOOK, can_edit: false }];
    renderStep(["p-1"]);
    expect(screen.getByTestId("read-only-notice")).toHaveTextContent("read-only");
    expect(screen.getByRole("button", { name: /Insert 1 row and write/ })).toBeDisabled();
  });
});
