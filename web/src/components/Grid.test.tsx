// Both paths through the grid: the plain table under 300 rows, TanStack Virtual over it.
// Then both cell editors: the inline one from 768 px up, the bottom sheet under it (finding 23).

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Grid, MARK_CLASS, VIRTUALIZE_OVER, type CellMark } from "@/components/Grid";
import { detectLayout } from "@/lib/sheet";

function sheet(dataRows: number): string[][] {
  const rows: string[][] = [["ID", "Task", "Owner", "Due", "Status"]];
  for (let i = 1; i <= dataRows; i++) {
    rows.push([`T-${100 + i}`, `Row ${i}`, "Ansul S", "24 Sep", "Open"]);
  }
  return rows;
}

function grid(rows: string[][]) {
  const { container } = render(<Grid rows={rows} layout={detectLayout(rows)} maxHeight="640px" />);
  const box = container.querySelector("[data-rows]") as HTMLElement;
  const bodyRows = container.querySelectorAll("tbody tr:not([data-spacer])");
  return { container, box, bodyRows };
}

describe("Grid", () => {
  it("renders every row of a small tab, with no virtualisation", () => {
    const { box, container, bodyRows } = grid(sheet(20));
    expect(box.dataset.virtualised).toBe("false");
    // 21 real rows, padded to the prototype's 22-row minimum.
    expect(bodyRows.length).toBe(22);
    expect(container.querySelectorAll("[data-spacer]").length).toBe(0);
    expect(screen.getByText("Row 1")).toBeInTheDocument();
    expect(screen.getByText("Row 20")).toBeInTheDocument();
  });

  it("keeps the last row of a tab right on the threshold", () => {
    const { box, bodyRows } = grid(sheet(VIRTUALIZE_OVER - 1));
    expect(box.dataset.rows).toBe(String(VIRTUALIZE_OVER));
    expect(box.dataset.virtualised).toBe("false");
    expect(bodyRows.length).toBe(VIRTUALIZE_OVER);
  });

  it("virtualises a tab over 300 rows: a window in the DOM, spacers holding the scrollbar", () => {
    const rows = sheet(800);
    const { box, container, bodyRows } = grid(rows);
    expect(box.dataset.virtualised).toBe("true");
    expect(box.dataset.rows).toBe("801");
    expect(bodyRows.length).toBeGreaterThan(0);
    expect(bodyRows.length).toBeLessThan(rows.length);

    // The top of the sheet is rendered; the far end is not, but the scrollbar is still full length.
    expect(screen.getByText("ID")).toBeInTheDocument();
    expect(screen.getByText("Row 1")).toBeInTheDocument();
    expect(screen.queryByText("Row 800")).toBeNull();

    const bottom = container.querySelector('[data-spacer="bottom"] td') as HTMLElement;
    expect(bottom).toBeTruthy();
    // 801 rows x 28px, minus what is rendered: several thousand pixels of scroll left below.
    expect(Number.parseInt(bottom.style.height, 10)).toBeGreaterThan(1000);
  });

  it("still marks cells and rows when virtualised", () => {
    const rows = sheet(400);
    const marks = new Map([["5,1", { kind: "new" as const, value: "Inserted by Meeting Desk" }]]);
    render(<Grid rows={rows} layout={detectLayout(rows)} marks={marks} maxHeight="640px" activeRow={5} />);
    expect(screen.getByText("Inserted by Meeting Desk")).toBeInTheDocument();
  });
});

// --- one selection colour, finding 29 -------------------------------------------------------------

describe("grid marks", () => {
  const KINDS: CellMark[] = ["new", "key", "conflict", "moved", "edited"];

  it("paints all five marks in the one selection hue, as a tint, an outline or a strike", () => {
    const rows = sheet(6);
    const marks = new Map(KINDS.map((kind, i) => [`${i + 1},1`, { kind }] as const));
    const { container } = render(<Grid rows={rows} layout={detectLayout(rows)} marks={marks} maxHeight="640px" anchor={{ r: 1, c: 3 }} />);

    for (const [i, kind] of KINDS.entries()) {
      const cell = container.querySelector(`[data-cell="${i + 1},1"]`) as HTMLElement;
      for (const cls of MARK_CLASS[kind].split(" ")) expect(cell.className).toContain(cls);
    }
    // The anchor is the same hue as an outline, not a sixth colour.
    expect((container.querySelector('[data-cell="1,3"]') as HTMLElement).className).toContain("outline-sel");
  });

  it("names no hue but the selection one", () => {
    const rows = sheet(6);
    const marks = new Map(KINDS.map((kind, i) => [`${i + 1},1`, { kind }] as const));
    const { container } = render(<Grid rows={rows} layout={detectLayout(rows)} marks={marks} maxHeight="640px" activeRow={2} />);
    const classes = [...container.querySelectorAll<HTMLElement>("[class]")].map((el) => el.className).join(" ");
    for (const gone of ["grid-new", "grid-key", "grid-conflict", "grid-anchor", "warn", "text-bad", "text-ok"]) {
      expect(classes).not.toContain(gone);
    }
  });
});

// --- the two cell editors, finding 23 -------------------------------------------------------------

function editableGrid(rows: string[][], narrow: boolean) {
  const listeners = new Set<() => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: narrow,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    })),
  );
  const onChange = vi.fn();
  const view = render(
    <Grid
      rows={rows}
      layout={detectLayout(rows)}
      maxHeight="640px"
      editable={{
        cols: new Set([1, 2, 4]),
        dropdowns: { 4: ["open", "in progress", "done"] },
        fromRow: 1,
        onChange,
      }}
    />,
  );
  return { ...view, onChange };
}

afterEach(() => vi.unstubAllGlobals());

describe("the cell editor under 768 px", () => {
  it("opens a bottom editor with the column name, the current value and a 44 px control", async () => {
    const { container, onChange } = editableGrid(sheet(4), true);
    await userEvent.click(container.querySelector('[data-cell="2,2"]') as HTMLElement);

    // No inline input in the cell: the tap opened the sheet at the bottom instead.
    expect(container.querySelector('[data-cell="2,2"] input')).toBeNull();
    const editor = screen.getByTestId("cell-editor");
    expect(editor.className).toContain("md:hidden");
    expect(within(editor).getByTestId("cell-editor-column")).toHaveTextContent("Owner");
    expect(within(editor).getByText("C3")).toBeInTheDocument();
    expect(within(editor).getByTestId("cell-editor-current")).toHaveTextContent("Ansul S");

    const control = within(editor).getByLabelText("Owner");
    expect(control.tagName).toBe("INPUT");
    expect(control.className).toContain("h-11");
    for (const name of ["Save", "Cancel"]) {
      expect(within(editor).getByRole("button", { name }).className).toContain("h-11");
    }

    await userEvent.clear(control);
    await userEvent.type(control, "Nishchay S");
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(within(editor).getByRole("button", { name: "Save" }));
    expect(onChange).toHaveBeenCalledWith(2, 2, "Nishchay S");
    expect(screen.queryByTestId("cell-editor")).toBeNull();
  });

  it("uses a select on a dropdown column and keeps it 44 px", async () => {
    const { container, onChange } = editableGrid(sheet(4), true);
    await userEvent.click(container.querySelector('[data-cell="1,4"]') as HTMLElement);

    const control = within(screen.getByTestId("cell-editor")).getByLabelText("Status");
    expect(control.tagName).toBe("SELECT");
    expect(control.className).toContain("h-11");
    await userEvent.selectOptions(control, "done");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onChange).toHaveBeenCalledWith(1, 4, "done");
  });

  it("Cancel closes it and writes nothing", async () => {
    const { container, onChange } = editableGrid(sheet(4), true);
    await userEvent.click(container.querySelector('[data-cell="2,1"]') as HTMLElement);
    await userEvent.type(screen.getByLabelText("Task"), " and more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("cell-editor")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Back closes the editor instead of leaving the app", async () => {
    const { container, onChange } = editableGrid(sheet(4), true);
    window.history.replaceState({ probe: "page" }, "");
    await userEvent.click(container.querySelector('[data-cell="2,1"]') as HTMLElement);
    expect(screen.getByTestId("cell-editor")).toBeInTheDocument();
    // The tap put an entry of its own on the stack, so Back has something to pop that is not the
    // page the person came from.
    expect(window.history.state).toMatchObject({ probe: "page", mdOverlay: true });

    act(() => void window.dispatchEvent(new PopStateEvent("popstate")));
    expect(screen.queryByTestId("cell-editor")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not open a header cell or a column nobody may edit", async () => {
    const { container } = editableGrid(sheet(4), true);
    await userEvent.click(container.querySelector('[data-cell="0,1"]') as HTMLElement);
    expect(screen.queryByTestId("cell-editor")).toBeNull();
    await userEvent.click(container.querySelector('[data-cell="2,0"]') as HTMLElement);
    expect(screen.queryByTestId("cell-editor")).toBeNull();
  });
});

describe("the cell editor from 768 px up", () => {
  it("stays inline in the cell, with no bottom sheet", async () => {
    const { container, onChange } = editableGrid(sheet(4), false);
    await userEvent.click(container.querySelector('[data-cell="2,2"]') as HTMLElement);

    expect(screen.queryByTestId("cell-editor")).toBeNull();
    const inline = container.querySelector('[data-cell="2,2"] input') as HTMLInputElement;
    expect(inline).toBeTruthy();
    await userEvent.clear(inline);
    await userEvent.type(inline, "Nishchay S{Enter}");
    expect(onChange).toHaveBeenCalledWith(2, 2, "Nishchay S");
  });

  it("pushes no history entry for an inline edit", async () => {
    const { container } = editableGrid(sheet(4), false);
    window.history.replaceState({ probe: "page" }, "");
    await userEvent.click(container.querySelector('[data-cell="2,2"]') as HTMLElement);
    expect(window.history.state).toEqual({ probe: "page" });
  });
});
