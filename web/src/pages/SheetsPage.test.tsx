// `before` used to be recomputed from the latest poll at save time, so a value
// somebody else had written in the meantime became the baseline and the API's pre-save guard - the
// one thing standing between two people editing the same cell - could never fire.
//
// The tab is polled every 60 s and a save can be pressed any time, so the poll landing between the
// two is the ordinary case, not a rare one. These tests drive exactly that ordering, and the
// second pair covers the idempotency key the same button sends.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SheetsPage } from "@/pages/SheetsPage";
import { ApiError } from "@/api/client";
import type { Me, TabState, Workbook } from "@/api/types";

const h = vi.hoisted(() => ({
  save: vi.fn(),
  addRow: vi.fn(),
  refetch: vi.fn(() => Promise.resolve()),
  tab: null as TabState | null,
}));

vi.mock("@/api/hooks", () => ({
  useWorkbooks: () => ({ data: [book], isLoading: false }),
  useTab: () => ({ data: h.tab, isError: false, error: null, refetch: h.refetch }),
  useTransfers: () => ({ data: [] }),
  useConnectWorkbook: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisconnectWorkbook: () => ({ mutateAsync: vi.fn() }),
  useUndoTransfer: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveSheet: () => ({ mutateAsync: h.save, isPending: false }),
  useAddRow: () => ({ mutateAsync: h.addRow, isPending: false }),
  useMeetings: () => ({ data: { items: [] } }),
  usePoints: () => ({ data: [] }),
}));

const book: Workbook = {
  id: "wb-1",
  spreadsheet_id: "ss-1",
  name: "Mobile App Product Roadmap",
  url: "https://docs.google.com/spreadsheets/d/ss-1",
  connection_id: "c-1",
  connected_by: "daniel.okafor@example.com",
  connected_at: "2026-09-01T09:00:00+05:30",
  last_read_at: null,
  can_edit: true,
  last_error: null,
  tabs: [{ sheet_id: "t1", title: "Roadmap", index: 0 }],
};

const HEADER = ["ID", "Task", "Owner", "Due", "Status"];
const rows = (owner: string, task = "Mirror OpenRates"): string[][] => [
  ["Mobile roadmap", "", "", "", ""],
  HEADER,
  ["T-101", task, owner, "3 Oct", "open"],
  ["T-102", "Send the Northwind questionnaire", "Alex S", "26 Sep", "open"],
];

function tabState(values: string[][], readAt = "2026-09-22T10:00:00+05:30"): TabState {
  return {
    workbook_id: "wb-1",
    sheet_id: "t1",
    title: "Roadmap",
    values,
    dropdowns: { "4": ["open", "in progress", "done"] },
    formula_cols: [],
    date_cols: [3],
    layout: {
      header_row: 1,
      first_col: 0,
      last_col: 4,
      columns: { id: 0, task: 1, owner: 2, due: 3, status: 4 },
      key_col: 0,
      key_prefix: "T-",
      last_table_row: 3,
      header_score: 5,
      formula_cols: [],
      date_cols: [3],
    },
    region_hash: "a".repeat(64),
    read_at: readAt,
    can_edit: true,
  };
}

const me: Me = {
  id: "u-1",
  email: "daniel.okafor@example.com",
  name: "Daniel Okafor",
  role: "admin",
  is_admin: true,
};

function page() {
  const onSelect = vi.fn();
  const view = render(<SheetsPage selection={{ wb: "wb-1", tab: "t1" }} onSelect={onSelect} me={me} />);
  const rerender = () =>
    view.rerender(<SheetsPage selection={{ wb: "wb-1", tab: "t1" }} onSelect={onSelect} me={me} />);
  return { ...view, rerender };
}

const cell = (container: HTMLElement, ref: string) => container.querySelector(`[data-cell="${ref}"]`) as HTMLElement;

/** Change C3 (row 2, the Owner of T-101) through the inline editor and leave it staged. */
async function editOwner(container: HTMLElement, value: string) {
  await userEvent.click(cell(container, "2,2"));
  const input = cell(container, "2,2").querySelector("input") as HTMLInputElement;
  await userEvent.clear(input);
  await userEvent.type(input, `${value}{Enter}`);
}

beforeEach(() => {
  h.save.mockReset();
  h.addRow.mockReset();
  h.tab = tabState(rows("Alex S"));
  h.save.mockResolvedValue({ ok: true, batch_id: "b", edits: [{}], tab: h.tab });
});

afterEach(() => vi.unstubAllGlobals());

describe("the Sheets page pre-save guard", () => {
  it("sends the value the cell held when it was changed, not the one the poll brought in", async () => {
    const { container, rerender } = page();
    await editOwner(container, "Noah S");
    await screen.findByText("1 unsaved");

    // 60 s later the poll lands: somebody else has put Sofia Silva in the same cell.
    h.tab = tabState(rows("Sofia Silva"), "2026-09-22T10:01:00+05:30");
    rerender();
    // The rest of the grid shows what was read; the staged cell still shows what was typed.
    expect(cell(container, "2,2")).toHaveTextContent("Noah S");
    expect(screen.getByText(/read /)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(1));
    expect(h.save.mock.calls[0][0].edits).toEqual([{ cell: "C3", before: "Alex S", after: "Noah S" }]);
  });

  it("keeps the first baseline when the same cell is changed twice", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    await editOwner(container, "Maya R");
    await screen.findByText("1 unsaved");

    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(1));
    expect(h.save.mock.calls[0][0].edits).toEqual([{ cell: "C3", before: "Alex S", after: "Maya R" }]);
  });

  it("re-sends a kept edit against what the sheet holds now, so the guard passes", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    h.save.mockRejectedValueOnce(
      new ApiError(
        409,
        {
          message: "Some of these cells changed in Google Sheets while you were editing. Pick one.",
          clashes: [{ cell: "C3", yours: "Noah S", theirs: "Sofia Silva", was: "Alex S" }],
        },
        {},
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await screen.findByText("These cells changed in Google Sheets while you were editing. Pick one per cell.");
    await userEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));

    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(2));
    expect(h.save.mock.calls[1][0].edits).toEqual([{ cell: "C3", before: "Sofia Silva", after: "Noah S" }]);
  });

  it("drops the edit entirely when theirs is taken", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    h.save.mockRejectedValueOnce(
      new ApiError(
        409,
        { message: "Pick one.", clashes: [{ cell: "C3", yours: "Noah S", theirs: "Sofia Silva", was: "Alex S" }] },
        {},
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await screen.findByRole("button", { name: "Take theirs" });
    await userEvent.click(screen.getByRole("button", { name: "Take theirs" }));
    await screen.findByText("0 unsaved");
    expect(screen.getByRole("button", { name: "Save to Sheet" })).toBeDisabled();
  });
});

describe("the Sheets page idempotency key", () => {
  it("sends a uuid with the save and a fresh one for the next save", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(1));
    const first = h.save.mock.calls[0][0].batch_id;
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

    await editOwner(container, "Maya R");
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(2));
    expect(h.save.mock.calls[1][0].batch_id).not.toBe(first);
  });

  it("re-sends the same id when the first attempt never got an answer", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    h.save.mockRejectedValueOnce(new ApiError(0, "The API is not reachable. Is it running on port 8000?", {}));

    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(1));
    // Still staged: nothing is discarded when the write may or may not have landed.
    await screen.findByText("1 unsaved");

    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(2));
    expect(h.save.mock.calls[1][0].batch_id).toBe(h.save.mock.calls[0][0].batch_id);
  });

  it("uses a new id after the server refused, because the body changed", async () => {
    const { container } = page();
    await editOwner(container, "Noah S");
    h.save.mockRejectedValueOnce(
      new ApiError(
        409,
        { message: "Pick one.", clashes: [{ cell: "C3", yours: "Noah S", theirs: "Sofia Silva", was: "Alex S" }] },
        {},
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));
    await screen.findByRole("button", { name: "Keep mine" });
    await userEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    await userEvent.click(screen.getByRole("button", { name: "Save to Sheet" }));

    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(2));
    expect(h.save.mock.calls[1][0].batch_id).not.toBe(h.save.mock.calls[0][0].batch_id);
  });
});
