import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PointRow, ROW_GRID } from "./PointRow";
import type { Point } from "@/api/types";

function point(over: Partial<Point> = {}): Point {
  return {
    id: "p-1",
    meeting_id: "m-1",
    extraction_id: null,
    kind: "action",
    text: "Mirror OpenRates before launch",
    text_norm: "mirror openrates before launch",
    evidence: "",
    owner_text: "Daniel Okafor",
    owner_email: "daniel.okafor@example.com",
    owner_ambiguous: false,
    due_text: "3 Oct",
    due_date: null,
    status: "open",
    workstream: "Mobile",
    lifecycle: "active",
    selected: false,
    updated_by: "daniel.okafor@example.com",
    updated_at: null,
    deleted_at: null,
    ...over,
  };
}

const OWNERS = ["Daniel Okafor", "Alex S", "product"];
const WORKSTREAMS = ["Mobile", "Platform"];

function renderRow(p: Point) {
  const props = {
    point: p,
    owners: OWNERS,
    workstreams: WORKSTREAMS,
    onPatch: vi.fn(),
    onDefer: vi.fn(),
    onRestore: vi.fn(),
    onRemove: vi.fn(),
    onTransfer: vi.fn(),
  };
  render(<PointRow {...props} />);
  return props;
}

describe("PointRow", () => {
  it("defers an active point without deleting it", async () => {
    const props = renderRow(point());
    expect(screen.getByTestId("point-row")).toHaveAttribute("data-lifecycle", "active");
    await userEvent.click(screen.getByRole("button", { name: "Defer" }));
    expect(props.onDefer).toHaveBeenCalledTimes(1);
    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it("edits a field through onPatch so the change autosaves", async () => {
    const props = renderRow(point());
    await userEvent.selectOptions(screen.getByLabelText("Status"), "blocked");
    expect(props.onPatch).toHaveBeenCalledWith({ status: "blocked" });
  });

  it("shows a deferred point read-only with Restore and Transfer", async () => {
    const props = renderRow(point({ lifecycle: "deferred" }));
    const row = screen.getByTestId("point-row");
    expect(row).toHaveAttribute("data-lifecycle", "deferred");
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(props.onRestore).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(props.onTransfer).toHaveBeenCalledTimes(1);
  });

  it("offers only decision statuses on a decision", () => {
    renderRow(point({ kind: "decision", status: "decided" }));
    const options = Array.from(screen.getByLabelText("Status").querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["decided", "open", "dropped"]);
  });
});

// Screen review round 1, R1-01 and R1-09. jsdom has no layout, so these read the structure the
// layout is built from: which controls share a grid track, and which share a line on a phone.
describe("PointRow layout", () => {
  /** The md grid's items: children of an `md:contents` wrapper count as the wrapper's children. */
  function gridItems(row: HTMLElement): HTMLElement[] {
    return Array.from(row.children).flatMap((child) => {
      const el = child as HTMLElement;
      if (el.className.includes("md:contents")) return gridItems(el);
      if (/(^|\s)md:hidden(\s|$)/.test(el.className)) return [];
      return [el];
    });
  }

  it("gives Defer and Remove their own grid track instead of the workstream's", () => {
    renderRow(point());
    const row = screen.getByTestId("point-row");
    const items = gridItems(row);
    const tracks = (ROW_GRID.match(/lg:grid-cols-\[([^\]]+)\]/)?.[1] ?? "").split("_");
    expect(items).toHaveLength(tracks.length);
    expect(tracks).toHaveLength(8);

    const actions = screen.getByTestId("point-actions");
    expect(items).toContain(actions);
    expect(actions).toHaveTextContent("Defer");
    expect(actions.querySelector("select")).toBeNull();
    // Every other track holds exactly one control.
    for (const item of items.filter((i) => i !== actions)) {
      expect(item.matches("select, input, button")).toBe(true);
    }
  });

  it("keeps the text and the row's actions together on a phone, the fields in a grid under them", () => {
    renderRow(point());
    const row = screen.getByTestId("point-row");
    const [first, second] = Array.from(row.children) as HTMLElement[];
    expect(first).toContainElement(screen.getByLabelText("Point"));
    expect(first).toContainElement(screen.getByRole("button", { name: "Defer" }));
    expect(first).toContainElement(screen.getByRole("button", { name: "Remove point" }));
    expect(first).not.toContainElement(screen.getByLabelText("Kind"));
    for (const field of ["Kind", "Owner", "Due", "Status", "Workstream"]) {
      expect(second).toContainElement(screen.getByLabelText(field));
    }
    // R4-03: a grid that wraps within the row, never a strip that scrolls sideways.
    expect(second.className).toMatch(/(^|\s)grid-cols-6(\s|$)/);
    expect(second.className).not.toMatch(/overflow-x-(auto|scroll)/);
    // Two lines of six columns: kind 2 + owner 4, then due 2 + status 2 + workstream 2.
    const spans = ["Kind", "Owner", "Due", "Status", "Workstream"].map((f) =>
      Number(/max-md:col-span-(\d)/.exec(screen.getByLabelText(f).className)?.[1]),
    );
    expect(spans).toEqual([2, 4, 2, 2, 2]);
  });

  it("offers one Remove, at every width", () => {
    renderRow(point());
    expect(screen.getAllByRole("button", { name: "Remove point" })).toHaveLength(1);
  });

  it("puts Kind back in front of the text from 768 px", () => {
    renderRow(point());
    expect(screen.getByLabelText("Kind").className).toMatch(/md:order-2/);
    expect(screen.getByLabelText("Point").className).toMatch(/md:order-3/);
  });
});

// Screen review round 4, R4-01: on a phone the point's text was a one-line field, cut at the edge
// ("Send the Northwind questionnaire by Frida"). Under 768 px it is a textarea that wraps and grows.
describe("PointRow on a phone", () => {
  const LINE = 20;
  let restore: PropertyDescriptor | undefined;

  beforeEach(() => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: true,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      })),
    );
    // jsdom has no layout: 30 characters to a 20 px line is all the growing needs.
    restore = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
      configurable: true,
      get(this: HTMLTextAreaElement) {
        return Math.max(1, Math.ceil(this.value.length / 30)) * LINE + 22;
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (restore) Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", restore);
    else delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight;
  });

  it("shows the whole point in a box that grows with it, with no scrollbar", () => {
    const long = "Send the Northwind questionnaire by Friday and chase the answers by the following Tuesday";
    renderRow(point({ text: long }));
    const text = screen.getByLabelText("Point");
    expect(text.tagName).toBe("TEXTAREA");
    expect(text).toHaveValue(long);
    expect(text.style.height).toBe(`${3 * LINE + 22}px`);
    expect(text.style.overflowY).toBe("hidden");
  });

  it("autosaves what is typed, through the same onPatch as the desktop field", async () => {
    const props = renderRow(point({ text: "Mirror" }));
    const text = screen.getByLabelText("Point");
    await userEvent.click(text);
    await userEvent.keyboard("{End}s");
    expect(props.onPatch).toHaveBeenLastCalledWith({ text: "Mirrors" });
  });

  it("keeps the point one line in the sheet: Enter adds nothing, a pasted break becomes a space", async () => {
    const props = renderRow(point({ text: "Mirror" }));
    const text = screen.getByLabelText("Point");
    await userEvent.click(text);
    await userEvent.keyboard("{End}{Enter}");
    expect(props.onPatch).not.toHaveBeenCalled();
    await userEvent.paste("a\nb");
    expect(props.onPatch).toHaveBeenLastCalledWith({ text: "Mirrora b" });
  });

  it("stays a one-line input from 768 px", () => {
    vi.unstubAllGlobals();
    renderRow(point());
    expect(screen.getByLabelText("Point").tagName).toBe("INPUT");
  });
});

describe("a deferred point", () => {
  it("wraps its text on a phone and truncates it only from 768 px (R4-04)", () => {
    renderRow(point({ lifecycle: "deferred", text: "the upload flag has no rollback plan and nobody owns it yet" }));
    const text = screen.getByTestId("deferred-text");
    expect(text.className.split(/\s+/)).not.toContain("truncate");
    expect(text.className).toMatch(/md:truncate/);
  });
});
