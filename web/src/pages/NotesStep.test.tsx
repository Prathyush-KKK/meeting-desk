// Screen review round 1, Step 2:
//   R1-22  a saved note can be moved to another meeting (spec section 7; POST /notes/{id}/move).
//   R1-11  no fixed model name on the page, except the wait hint while a run is pending.
//   wait   an extraction takes one to two minutes, so the button counts the seconds.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotesStep } from "@/pages/NotesStep";
import type { MeetingItem, Note } from "@/api/types";

const h = vi.hoisted(() => ({
  move: vi.fn(() => Promise.resolve({})),
  extract: { isPending: false, isPolling: false, phase: "idle" },
}));

vi.mock("@/api/hooks", () => ({
  ExtractionCancelled: class extends Error {},
  useNotes: () => ({ data: [NOTE] }),
  useSources: () => ({ data: { sources: [] }, isLoading: false, refetch: vi.fn() }),
  useImportNote: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePasteNote: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchNote: () => ({ mutate: vi.fn() }),
  useDeleteNote: () => ({ mutate: vi.fn() }),
  useExtract: () => ({ mutateAsync: vi.fn(), cancel: vi.fn(), ...h.extract }),
  useMoveNote: () => ({ mutateAsync: h.move, isPending: false }),
  useMeetings: () => ({
    data: {
      items: [
        { id: "m-1", title: "Vendor call with Maya" },
        { id: "m-2", title: "Northwind call prep" },
        { id: null, title: "Platform squad sync" },
      ],
    },
  }),
}));

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), message: vi.fn() }) }));

const NOTE = {
  id: "n-1",
  meeting_id: "m-1",
  source: "paste",
  title: "Pasted note",
  word_count: 55,
  include: true,
  created_by: "daniel.okafor@example.com",
} as unknown as Note;

const MEETING = { id: "m-1", title: "Vendor call with Maya" } as unknown as MeetingItem;

beforeEach(() => {
  h.move.mockClear();
  h.extract = { isPending: false, isPolling: false, phase: "idle" };
});

describe("NotesStep", () => {
  it("moves a note to another saved meeting", async () => {
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    const select = screen.getByLabelText("Move to another meeting");
    // Not the meeting it is on, and not a calendar card that has no record yet.
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["Move…", "Northwind call prep"]);
    await userEvent.selectOptions(select, "m-2");
    expect(h.move).toHaveBeenCalledWith({ id: "n-1", meeting_id: "m-2" });
  });

  it("names no model before anything has been extracted", () => {
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    expect(screen.queryByText(/Gemini 2\.5 Flash/)).not.toBeInTheDocument();
  });

  it("names no model and shows no wait hint while idle", () => {
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Extract points" })).toBeInTheDocument();
    expect(screen.queryByTestId("extract-hint")).not.toBeInTheDocument();
  });
});

describe("NotesStep while extracting", () => {
  afterEach(() => vi.useRealTimers());

  it("counts the seconds on the button and says how long it usually takes", () => {
    vi.useFakeTimers();
    h.extract = { isPending: true, isPolling: false, phase: "running" };
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Extracting… 0s" })).toBeDisabled();
    act(() => vi.advanceTimersByTime(3_000));
    expect(screen.getByRole("button", { name: "Extracting… 3s" })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(62_000));
    expect(screen.getByRole("button", { name: "Extracting… 65s" })).toBeInTheDocument();
    expect(screen.getByTestId("extract-hint")).toHaveTextContent(
      "The model usually takes one to two minutes. You can leave this page; the points appear on step 3.",
    );
  });

  it("keeps Cancel while the run is queued, with the same counter", () => {
    vi.useFakeTimers();
    h.extract = { isPending: true, isPolling: true, phase: "queued" };
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole("button", { name: "Queued… 2s" })).toBeDisabled();
    expect(screen.getByTestId("cancel-extract")).toBeInTheDocument();
  });
});
