import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PointRow } from "./PointRow";
import type { Point } from "@/api/types";

function point(over: Partial<Point> = {}): Point {
  return {
    id: "p-1",
    meeting_id: "m-1",
    extraction_id: null,
    kind: "action",
    text: "Mirror Open Food Facts before launch",
    text_norm: "mirror open food facts before launch",
    evidence: "",
    owner_text: "Prathyush Kodhanpur",
    owner_email: "prathyush.kodhanpur@simpleo.ai",
    owner_ambiguous: false,
    due_text: "3 Oct",
    due_date: null,
    status: "open",
    workstream: "Nutrition",
    lifecycle: "active",
    selected: false,
    updated_by: "prathyush.kodhanpur@simpleo.ai",
    updated_at: null,
    deleted_at: null,
    ...over,
  };
}

const OWNERS = ["Prathyush Kodhanpur", "Ansul S", "product"];
const WORKSTREAMS = ["Nutrition", "Platform"];

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
