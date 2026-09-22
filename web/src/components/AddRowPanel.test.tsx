// Review 1, finding 8 (the web half): "Above a row" defaulted to `header_row + 1`, so the first
// press put the new row directly under the header - the one place the planner used to copy the
// header's formulas and formatting from. There is no default row now: the insert goes after the
// table until a row number is clicked, and the API's refusal for a header row is shown here.
//
// Finding 9's key rides on the same button.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddRowPanel } from "@/components/AddRowPanel";
import { ApiError } from "@/api/client";
import type { TabState } from "@/api/types";

const h = vi.hoisted(() => ({ addRow: vi.fn() }));

vi.mock("@/api/hooks", () => ({
  useAddRow: () => ({ mutateAsync: h.addRow, isPending: false }),
  useMeetings: () => ({ data: { items: [{ id: "m-1", title: "Vendor call with Madhu" }] } }),
  usePoints: () => ({ data: [] }),
}));

const tab: TabState = {
  workbook_id: "wb-1",
  sheet_id: "t1",
  title: "Roadmap",
  values: [
    ["Nutrition roadmap", "", "", "", ""],
    ["ID", "Task", "Owner", "Due", "Status"],
    ["T-101", "Mirror Open Food Facts", "Ansul S", "3 Oct", "open"],
    ["T-102", "Send the Sprinto questionnaire", "Nishchay S", "26 Sep", "open"],
  ],
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
  region_hash: "b".repeat(64),
  read_at: "2026-09-22T10:00:00+05:30",
  can_edit: true,
};

function panel(aboveRow: number | null = null) {
  const onPickRow = vi.fn();
  const onDone = vi.fn();
  const view = render(<AddRowPanel tab={tab} aboveRow={aboveRow} onPickRow={onPickRow} onDone={onDone} />);
  return { ...view, onPickRow, onDone };
}

beforeEach(() => {
  h.addRow.mockReset();
  h.addRow.mockResolvedValue({ ok: true, batch_id: "b", insert_at: 4, keys: ["T-103"], cells: [], transfer: null, tab });
});

describe("where the row lands", () => {
  it("defaults to after the table, with no row picked", () => {
    panel(null);
    expect(screen.getByLabelText(/After the table/)).toBeChecked();
    expect(screen.getByTestId("addrow-above")).not.toBeChecked();
    expect(screen.getByTestId("add-row-lands")).toHaveTextContent("Lands after row 4");
  });

  it("cannot be switched to 'above' without clicking a row, so it cannot land under the header", async () => {
    const { onPickRow } = panel(null);
    const above = screen.getByTestId("addrow-above");
    expect(above).toBeDisabled();
    expect(screen.getByText(/Above a row - click a row number in the grid/)).toBeInTheDocument();

    await userEvent.click(above);
    expect(above).not.toBeChecked();
    // The old panel answered this click with header_row + 1. Nothing is picked now.
    expect(onPickRow).not.toHaveBeenCalled();
  });

  it("sends after_table when nothing is picked", async () => {
    panel(null);
    await userEvent.type(screen.getByLabelText(/Task/), "Runbook for the upload flag");
    await userEvent.click(screen.getByTestId("add-row-submit"));
    await waitFor(() => expect(h.addRow).toHaveBeenCalledTimes(1));
    expect(h.addRow.mock.calls[0][0].position).toEqual({ mode: "after_table" });
    expect(h.addRow.mock.calls[0][0].region_hash).toBe("b".repeat(64));
  });

  it("uses the clicked row once there is one", async () => {
    panel(2);
    expect(screen.getByTestId("addrow-above")).toBeChecked();
    expect(screen.getByText("Above row 3")).toBeInTheDocument();
    expect(screen.getByTestId("add-row-lands")).toHaveTextContent("Lands at row 3, pushing the rest down");

    await userEvent.type(screen.getByLabelText(/Task/), "Runbook for the upload flag");
    await userEvent.click(screen.getByTestId("add-row-submit"));
    await waitFor(() => expect(h.addRow).toHaveBeenCalledTimes(1));
    expect(h.addRow.mock.calls[0][0].position).toEqual({ mode: "above", row: 2 });
  });

  it("clears back to after the table", async () => {
    const { onPickRow } = panel(2);
    await userEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(onPickRow).toHaveBeenCalledWith(null);
  });
});

describe("what the API refuses", () => {
  it("shows the header-row message beside the radio instead of only in a toast", async () => {
    panel(1);
    h.addRow.mockRejectedValueOnce(
      new ApiError(409, "That row is in or above the header. Pick a row inside the table.", {}),
    );
    await userEvent.type(screen.getByLabelText(/Task/), "Runbook for the upload flag");
    await userEvent.click(screen.getByTestId("add-row-submit"));

    const refused = await screen.findByTestId("add-row-refused");
    expect(refused).toHaveTextContent("That row is in or above the header. Pick a row inside the table.");
    // The panel stays open with what was typed, so the person clicks another row and presses again.
    expect(screen.getByLabelText(/Task/)).toHaveValue("Runbook for the upload flag");
  });

  it("shows the below-the-table message the same way", async () => {
    panel(9);
    h.addRow.mockRejectedValueOnce(
      new ApiError(409, "That row is below the table (it ends at row 4). Insert after the table instead.", {}),
    );
    await userEvent.type(screen.getByLabelText(/Task/), "Runbook");
    await userEvent.click(screen.getByTestId("add-row-submit"));
    expect(await screen.findByTestId("add-row-refused")).toHaveTextContent("Insert after the table instead.");
  });

  it("clears the message on the next press", async () => {
    panel(2);
    h.addRow.mockRejectedValueOnce(new ApiError(409, "That row is in or above the header.", {}));
    await userEvent.type(screen.getByLabelText(/Task/), "Runbook");
    await userEvent.click(screen.getByTestId("add-row-submit"));
    await screen.findByTestId("add-row-refused");

    await userEvent.click(screen.getByTestId("add-row-submit"));
    await waitFor(() => expect(screen.queryByTestId("add-row-refused")).toBeNull());
  });
});

describe("the add-row idempotency key", () => {
  it("sends a uuid and holds it while the outcome is unknown", async () => {
    panel(null);
    h.addRow.mockRejectedValueOnce(new ApiError(0, "The API is not reachable.", {}));
    await userEvent.type(screen.getByLabelText(/Task/), "Runbook");
    await userEvent.click(screen.getByTestId("add-row-submit"));
    await waitFor(() => expect(h.addRow).toHaveBeenCalledTimes(1));
    expect(h.addRow.mock.calls[0][0].batch_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );

    await userEvent.click(screen.getByTestId("add-row-submit"));
    await waitFor(() => expect(h.addRow).toHaveBeenCalledTimes(2));
    expect(h.addRow.mock.calls[1][0].batch_id).toBe(h.addRow.mock.calls[0][0].batch_id);
  });
});
