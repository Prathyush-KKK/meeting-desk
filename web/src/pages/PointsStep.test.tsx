// Step 3:
//   model  the "Extracted with" label names whoever answered, read from the meeting's extractions;
//          it was a fixed "gemini-2.5-flash · Vertex AI asia-south1".
//   footer the footer ends on Transfer, so on a phone's 2 x 2 block it is bottom right.
//   history "See transferred" lists what left this meeting; a failed last extraction says so.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PointsStep } from "@/pages/PointsStep";
import type { ExtractionRecord, MeetingItem, Point, Transfer } from "@/api/types";

const h = vi.hoisted(() => ({
  extractions: [] as unknown[],
  points: [] as unknown[],
  transfers: [] as unknown[],
  transfersFor: [] as (string | null)[],
  extracting: false,
}));

vi.mock("@/api/hooks", () => ({
  usePoints: (_m: string, lifecycle: string) => ({ data: lifecycle === "active" ? h.points : [], isLoading: false }),
  usePointEditor: () => ({ merge: (p: Point[]) => p, edit: vi.fn(), pending: 0, savedAt: null }),
  useBulkPatchPoints: () => ({ mutate: vi.fn() }),
  useDeferPoints: () => ({ mutateAsync: vi.fn() }),
  useRestorePoint: () => ({ mutate: vi.fn() }),
  useDeletePoint: () => ({ mutateAsync: vi.fn() }),
  useAddPoint: () => ({ mutate: vi.fn() }),
  useCopyPointsAsText: () => ({ mutateAsync: vi.fn() }),
  useExtract: () => ({ mutateAsync: vi.fn(), isPending: h.extracting }),
  useExtractions: () => ({ data: h.extractions }),
  useMeetingTransfers: (id: string | null) => {
    h.transfersFor.push(id);
    return { data: id ? h.transfers : undefined, isLoading: false };
  },
}));

const MEETING = {
  id: "m-1",
  title: "Vendor call with Maya",
  date: "2026-09-22",
  attendees: [],
  workstream: "Mobile",
} as unknown as MeetingItem;

const POINT = {
  id: "p-1",
  meeting_id: "m-1",
  kind: "action",
  text: "Send the Northwind questionnaire",
  owner_text: "Alex S",
  owner_email: null,
  owner_ambiguous: false,
  due_text: "by Friday",
  status: "open",
  workstream: "Mobile",
  lifecycle: "active",
  selected: true,
} as unknown as Point;

function record(over: Partial<ExtractionRecord>): ExtractionRecord {
  return { id: "e-1", meeting_id: "m-1", provider: "vertex", model: "gemini-2.5-flash", region: "asia-south1", status: "done", fallback_from: null, error: null, ...over };
}

const renderStep = () => render(<PointsStep meeting={MEETING} onBack={vi.fn()} onTransfer={vi.fn()} onKeep={vi.fn()} />);

beforeEach(() => {
  h.points = [POINT];
  h.extractions = [];
  h.transfers = [];
  h.transfersFor = [];
  h.extracting = false;
});

describe("PointsStep", () => {
  it("names the model and provider that actually answered", () => {
    h.extractions = [record({ provider: "fake", model: "rule-based", region: "local" })];
    renderStep();
    const label = screen.getByTestId("extracted-with");
    expect(label).toHaveTextContent("Extracted by the local rule-based fake");
    expect(label).not.toHaveTextContent("gemini");
  });

  it("says when Bedrock answered after Vertex failed", () => {
    h.extractions = [record({ provider: "bedrock", model: "claude", region: "ap-south-1", fallback_from: "vertex" })];
    renderStep();
    expect(screen.getByTestId("extracted-with")).toHaveTextContent("Amazon Bedrock ap-south-1, after Vertex AI failed");
  });

  it("claims no model when the points did not come from an extraction", () => {
    renderStep();
    expect(screen.queryByTestId("extracted-with")).not.toBeInTheDocument();
    expect(screen.queryByText(/gemini-2\.5-flash/)).not.toBeInTheDocument();
  });

  it("ends the footer on Transfer, which a phone's 2 x 2 block puts bottom right", () => {
    renderStep();
    const footer = screen.getByTestId("points-footer");
    const buttons = Array.from(footer.querySelectorAll("button")).map((b) => b.textContent);
    expect(buttons).toEqual(["Back", "Copy as text", "Keep here", "Transfer 1"]);
    expect(footer.className).toMatch(/grid-cols-2/);
  });

  it("lays the bulk controls out as two rows of three on a phone, never scrolling sideways", () => {
    renderStep();
    const bar = screen.getByTestId("bulk-bar");
    expect(bar.children).toHaveLength(6);
    expect(bar.className).toMatch(/(^|\s)grid-cols-3(\s|$)/);
    expect(bar.className).not.toMatch(/overflow-x-(auto|scroll)/);
    expect(bar.className).not.toMatch(/flex-nowrap/);
    const labels = Array.from(bar.children).map((el) => el.getAttribute("aria-label") ?? el.textContent);
    expect(labels).toEqual(["1 selected", "Assign selected to", "Set status of selected", "Apply", "Defer", "Add point"]);
    expect(bar.className).toMatch(/md:flex/); // one row again from 768 px
  });

  it("shows what was transferred from this meeting, read-only, once asked", async () => {
    h.transfers = [
      { id: "t-2", at: "2026-09-22T17:05:00+05:30", actor: "noah.s@example.com", point_text: "Share the deck", sheet_id: "1234", snapshot: {}, undone_at: "2026-09-22T17:07:00+05:30" },
      { id: "t-1", at: "2026-09-22T17:02:00+05:30", actor: "alex.s@example.com", point_text: "Send the Northwind questionnaire", sheet_id: "1234", snapshot: {}, undone_at: null },
    ] as Partial<Transfer>[];
    renderStep();
    expect(screen.queryByTestId("transferred")).not.toBeInTheDocument();
    expect(h.transfersFor.every((id) => id === null)).toBe(true); // not fetched until opened

    await userEvent.click(screen.getByRole("button", { name: "See transferred" }));
    const section = screen.getByTestId("transferred");
    expect(h.transfersFor).toContain("m-1");
    expect(section).toHaveTextContent("Transferred · 2");
    const lines = screen.getAllByTestId("transfer-line");
    expect(lines[0]).toHaveTextContent(/^Share the deck → sheet 1234 · Tue 22 Sept? 17:05 · noah\.s · undone$/);
    expect(lines[1]).not.toHaveTextContent("undone");
    expect(section.querySelector("input, select, textarea")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Hide transferred" }));
    expect(screen.queryByTestId("transferred")).not.toBeInTheDocument();
  });

  it("says when nothing has been transferred from this meeting", async () => {
    renderStep();
    await userEvent.click(screen.getByRole("button", { name: "See transferred" }));
    expect(screen.getByTestId("transferred")).toHaveTextContent("Nothing transferred from this meeting.");
  });

  it("says the last extraction failed, and why, beside Re-extract", () => {
    const reason = `ThrottlingException: Too many requests, please wait before trying again. ${"y".repeat(300)}`;
    h.extractions = [record({ id: "e-2", provider: "bedrock", model: "gemma-4", status: "error", error: reason }), record({})];
    renderStep();
    const line = screen.getByTestId("extraction-error");
    expect(line).toHaveTextContent(/^Last extraction failed: ThrottlingException: Too many requests/);
    expect(line.textContent!.length).toBeLessThanOrEqual("Last extraction failed: ".length + 200);
    expect(line.getAttribute("title")).toBe(reason);
    expect(line.nextElementSibling).toHaveTextContent("Re-extract");
    // The label still names the run that produced the points on the page.
    expect(screen.getByTestId("extracted-with")).toHaveTextContent("gemini-2.5-flash");
  });

  it("drops the failure once a newer run has succeeded", () => {
    h.extractions = [record({ id: "e-2" }), record({ id: "e-1", status: "error", error: "timed out" })];
    renderStep();
    expect(screen.queryByTestId("extraction-error")).not.toBeInTheDocument();
  });
});

describe("PointsStep while re-extracting", () => {
  afterEach(() => vi.useRealTimers());

  it("counts the seconds on the Re-extract link", () => {
    vi.useFakeTimers();
    h.extracting = true;
    renderStep();
    expect(screen.getByText("Extracting… 0s")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByText("Extracting… 5s")).toBeDisabled();
  });
});
