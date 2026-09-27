// Screen review round 1, Step 2:
//   R1-22  a saved note can be moved to another meeting (spec section 7; POST /notes/{id}/move).
//   R1-11  no fixed model name on the page.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotesStep } from "@/pages/NotesStep";
import type { MeetingItem, Note } from "@/api/types";

const h = vi.hoisted(() => ({ move: vi.fn(() => Promise.resolve({})) }));

vi.mock("@/api/hooks", () => ({
  ExtractionCancelled: class extends Error {},
  useNotes: () => ({ data: [NOTE] }),
  useSources: () => ({ data: { sources: [] }, isLoading: false, refetch: vi.fn() }),
  useImportNote: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePasteNote: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchNote: () => ({ mutate: vi.fn() }),
  useDeleteNote: () => ({ mutate: vi.fn() }),
  useExtract: () => ({ mutateAsync: vi.fn(), isPending: false, isPolling: false, phase: "idle", cancel: vi.fn() }),
  useMoveNote: () => ({ mutateAsync: h.move, isPending: false }),
  useMeetings: () => ({
    data: {
      items: [
        { id: "m-1", title: "Vendor call with Madhu" },
        { id: "m-2", title: "Sprinto call prep" },
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
  created_by: "prathyush.kodhanpur@simpleo.ai",
} as unknown as Note;

const MEETING = { id: "m-1", title: "Vendor call with Madhu" } as unknown as MeetingItem;

beforeEach(() => h.move.mockClear());

describe("NotesStep", () => {
  it("moves a note to another saved meeting", async () => {
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    const select = screen.getByLabelText("Move to another meeting");
    // Not the meeting it is on, and not a calendar card that has no record yet.
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["Move…", "Sprinto call prep"]);
    await userEvent.selectOptions(select, "m-2");
    expect(h.move).toHaveBeenCalledWith({ id: "n-1", meeting_id: "m-2" });
  });

  it("names no model before anything has been extracted", () => {
    render(<NotesStep meeting={MEETING} onBack={vi.fn()} onExtracted={vi.fn()} />);
    expect(screen.queryByText(/Gemini 2\.5 Flash/)).not.toBeInTheDocument();
  });
});
