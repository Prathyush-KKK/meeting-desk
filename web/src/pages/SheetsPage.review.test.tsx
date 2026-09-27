// Screen review round 1, the Sheets page:
//   R1-17  with no workbook, the empty state carries the Connect field itself.
//   R1-19  a tap on the key column, a formula column or a read-only workbook says why it cannot be
//          edited (spec section 7); it used to do nothing.
//   R1-20  "Undo is available for 10 minutes": the recent-transfer lines carry Undo while the server
//          says the window is open, not only the ten-second toast.
//   R1-24  Disconnect offers Undo, which connects the same URL again.
//   R1-43  a filter that matches nothing says so and offers the way back.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SheetsPage } from "@/pages/SheetsPage";
import type { Me, TabState, Transfer, Workbook } from "@/api/types";

const h = vi.hoisted(() => ({
  books: [] as unknown[],
  tab: null as unknown,
  transfers: [] as unknown[],
  undo: vi.fn(() => Promise.resolve({})),
  disconnect: vi.fn(() => Promise.resolve({ ok: true })),
  connect: vi.fn(() => Promise.resolve({ name: "Roadmap" })),
}));

vi.mock("@/api/hooks", () => ({
  useWorkbooks: () => ({ data: h.books, isLoading: false }),
  useTab: () => ({ data: h.tab, isError: false, error: null, refetch: vi.fn() }),
  useTransfers: () => ({ data: h.transfers }),
  useConnectWorkbook: () => ({ mutateAsync: h.connect, isPending: false }),
  useDisconnectWorkbook: () => ({ mutateAsync: h.disconnect }),
  useUndoTransfer: () => ({ mutateAsync: h.undo, isPending: false }),
  useSaveSheet: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAddRow: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMeetings: () => ({ data: { items: [] } }),
  usePoints: () => ({ data: [] }),
}));

const toast = vi.hoisted(() => Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), message: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const BOOK: Workbook = {
  id: "wb-1",
  spreadsheet_id: "ss-1",
  name: "Roadmap",
  url: "https://docs.google.com/spreadsheets/d/ss-1",
  connection_id: "c-1",
  connected_by: "prathyush.kodhanpur@simpleo.ai",
  connected_at: "2026-09-21T09:00:00+05:30",
  last_read_at: null,
  can_edit: true,
  last_error: null,
  tabs: [{ sheet_id: "t1", title: "Roadmap", index: 0 }],
};

const VALUES = [
  ["Roadmap", "", "", "", "", ""],
  ["ID", "Task", "Owner", "Due", "Status", "Days"],
  ["T-101", "Mirror Open Food Facts", "Ansul S", "3 Oct", "open", "12"],
  ["T-102", "Send the Sprinto questionnaire", "Ansul S", "26 Sep", "open", "4"],
];

const TAB = {
  workbook_id: "wb-1",
  sheet_id: "t1",
  title: "Roadmap",
  values: VALUES,
  dropdowns: {},
  formula_cols: [5],
  date_cols: [],
  layout: {
    header_row: 1,
    first_col: 0,
    last_col: 5,
    columns: { id: 0, task: 1, owner: 2, due: 3, status: 4 },
    key_col: 0,
    key_prefix: "T-",
    last_table_row: 3,
    header_score: 5,
    formula_cols: [5],
    date_cols: [],
  },
  region_hash: "a".repeat(64),
  read_at: "2026-09-22T10:00:00+05:30",
  can_edit: true,
} as unknown as TabState;

function transfer(over: Partial<Transfer>): Transfer {
  return {
    id: "tr-1",
    batch_id: "b-1",
    at: "2026-09-22T17:02:00+05:30",
    actor: "prathyush.kodhanpur@simpleo.ai",
    meeting_id: "m-1",
    meeting_title: "Vendor call with Madhu",
    point_text: "Send the Sprinto questionnaire",
    workbook_id: "wb-1",
    sheet_id: "t1",
    mode: "append",
    cells: ["A17"],
    snapshot: {},
    previous: {},
    undone_at: null,
    can_undo: true,
    ...over,
  };
}

const me: Me = { id: "u-1", email: "prathyush.kodhanpur@simpleo.ai", name: "Prathyush Kodhanpur", role: "admin", is_admin: true };
const page = () => render(<SheetsPage selection={{ wb: "wb-1", tab: "t1" }} onSelect={vi.fn()} me={me} />);
const cell = (container: HTMLElement, ref: string) => container.querySelector(`[data-cell="${ref}"]`) as HTMLElement;

beforeEach(() => {
  h.books = [BOOK];
  h.tab = TAB;
  h.transfers = [];
  for (const fn of [h.undo, h.disconnect, h.connect, toast.message, toast.success]) fn.mockClear();
});

describe("Sheets: empty state", () => {
  it("offers the Connect field where it says to connect", () => {
    h.books = [];
    h.tab = null;
    page();
    const empty = screen.getByTestId("sheets-empty");
    expect(within(empty).getByLabelText("Google Sheets URL")).toBeInTheDocument();
    expect(within(empty).getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });
});

describe("Sheets: cells that cannot be edited say why", () => {
  it("explains the key column", async () => {
    const { container } = page();
    await userEvent.click(cell(container, "2,0"));
    expect(toast.message).toHaveBeenCalledWith(expect.stringMatching(/^A \(ID\) is the key column/));
    expect(cell(container, "2,0").querySelector("input, select")).toBeNull();
  });

  it("explains a formula column", async () => {
    const { container } = page();
    await userEvent.click(cell(container, "2,5"));
    expect(toast.message).toHaveBeenCalledWith("F (Days) holds a formula. Change it in Google Sheets.");
  });

  it("explains a read-only workbook on any cell", async () => {
    h.books = [{ ...BOOK, can_edit: false }];
    const { container } = page();
    await userEvent.click(cell(container, "2,2"));
    expect(toast.message).toHaveBeenCalledWith("Roadmap is read-only: no admin connection can edit it.");
    expect(cell(container, "2,2").querySelector("input")).toBeNull();
  });

  it("stays quiet on an editable cell", async () => {
    const { container } = page();
    await userEvent.click(cell(container, "2,2"));
    expect(toast.message).not.toHaveBeenCalled();
    expect(cell(container, "2,2").querySelector("input")).not.toBeNull();
  });
});

describe("Sheets: recent transfers", () => {
  it("offers Undo once per batch while the server says it is open", async () => {
    h.transfers = [transfer({ id: "tr-1" }), transfer({ id: "tr-2", cells: ["A18"], point_text: "Mirror Open Food Facts" })];
    page();
    const list = screen.getByTestId("recent-transfers");
    const undo = within(list).getAllByRole("button", { name: "Undo" });
    expect(undo).toHaveLength(1);
    await userEvent.click(undo[0]);
    expect(h.undo).toHaveBeenCalledWith("b-1");
  });

  it("offers no Undo once the window has closed", () => {
    h.transfers = [transfer({ can_undo: false })];
    page();
    expect(within(screen.getByTestId("recent-transfers")).queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });
});

describe("Sheets: disconnect", () => {
  it("offers Undo, which connects the same URL again", async () => {
    page();
    await userEvent.click(screen.getByTitle("Disconnect Roadmap"));
    await waitFor(() => expect(h.disconnect).toHaveBeenCalledWith("wb-1"));
    const call = toast.message.mock.calls.find(([text]) => String(text).startsWith("Disconnected"));
    expect(call).toBeTruthy();
    const options = call![1] as { action: { label: string; onClick: () => void } };
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    expect(h.connect).toHaveBeenCalledWith(BOOK.url);
  });
});

describe("Sheets: a filter that matches nothing", () => {
  it("says so and offers every row back", async () => {
    page();
    await userEvent.type(screen.getByPlaceholderText("Find"), "no such task");
    expect(screen.getByTestId("no-match")).toHaveTextContent("No rows match.");
    await userEvent.click(screen.getByRole("button", { name: "Show all rows" }));
    expect(screen.queryByTestId("no-match")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Find")).toHaveValue("");
  });
});

// R2-06: on a phone the heading, the Connect field and five filter buttons pushed the grid below the
// first screen. The filter is a select there and Connect waits behind the select's last option.
describe("Sheets on a phone", () => {
  it("filters from a select that drives the same filter as the buttons", async () => {
    page();
    await userEvent.selectOptions(screen.getByLabelText("Filter rows"), "mine");
    expect(screen.getByRole("button", { name: "Mine" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps Connect behind the select's last option until it is picked", async () => {
    page();
    const form = screen.getByLabelText("Google Sheets URL").closest("form") as HTMLElement;
    expect(form.className).toMatch(/(^|\s)hidden(\s|$)/);
    expect(form.className).toMatch(/md:flex/);
    await userEvent.selectOptions(screen.getByLabelText("Workbook and tab"), "Connect another workbook…");
    expect(form.className).not.toMatch(/(^|\s)hidden(\s|$)/);
  });
});

// Round 3, P3s: the empty tree box, and the save group staying together on the right.
describe("Sheets: small things", () => {
  it("draws no empty workbook tree when nothing is connected", () => {
    h.books = [];
    h.tab = null;
    page();
    expect(screen.getByTestId("workbook-tree").className).not.toMatch(/md:block/);
  });

  it("keeps the unsaved count, Discard and Save to Sheet in one group", () => {
    page();
    const group = screen.getByTestId("save-actions");
    expect(group).toHaveTextContent("0 unsaved");
    expect(within(group).getByRole("button", { name: "Discard" })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Save to Sheet" })).toBeInTheDocument();
    expect(group.className).toMatch(/ml-auto/);
  });
});
