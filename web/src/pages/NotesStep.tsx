import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { shortName } from "@/lib/display";
import {
  ExtractionCancelled,
  useDeleteNote,
  useExtract,
  useImportNote,
  useMeetings,
  useMoveNote,
  useNotes,
  usePasteNote,
  usePatchNote,
  useSources,
} from "@/api/hooks";
import type { MeetingItem, NoteSource } from "@/api/types";

interface Props {
  meeting: MeetingItem;
  onBack: () => void;
  onExtracted: () => void;
}

const SRC_LABEL: Record<string, string> = {
  gemini_doc: "Doc",
  transcript: "Transcript",
  recap_email: "Email",
  paste: "Paste",
  upload: "Upload",
};

export function NotesStep({ meeting, onBack, onExtracted }: Props) {
  const meetingId = meeting.id!;
  const notes = useNotes(meetingId);
  const sources = useSources(meetingId);
  const importNote = useImportNote(meetingId);
  const pasteNote = usePasteNote(meetingId);
  const patchNote = usePatchNote(meetingId);
  const deleteNote = useDeleteNote(meetingId);
  const extract = useExtract(meetingId);
  const moveNote = useMoveNote(meetingId);
  const meetings = useMeetings();
  const [paste, setPaste] = useState("");
  // Only saved meetings can hold a note; a calendar card that was never opened has no row yet.
  const targets = (meetings.data?.items ?? []).filter((m) => m.id && m.id !== meetingId);

  const move = async (noteId: string, targetId: string) => {
    if (!targetId) return;
    try {
      await moveNote.mutateAsync({ id: noteId, meeting_id: targetId });
      toast.success(`Moved to ${targets.find((m) => m.id === targetId)?.title || "the other meeting"}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not move the note");
    }
  };

  const rows = notes.data ?? [];
  const imported = (source: string) => rows.some((n) => n.source === source);

  const runImport = async (source: NoteSource, origin_ref: string) => {
    try {
      const result = await importNote.mutateAsync({ source: source as "gemini_doc" | "transcript" | "recap_email", origin_ref });
      toast.success(result.created ? `Saved ${result.note.title}` : "That text was already saved");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed");
    }
  };

  const savePaste = async () => {
    const text = paste.trim();
    if (!text) return;
    try {
      const result = await pasteNote.mutateAsync({ text, title: "Pasted summary" });
      setPaste("");
      if (result.truncated) toast.message("Long paste: only the first 200k characters go to the model.");
      toast.success(result.created ? "Saved" : "That text was already saved");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save");
    }
  };

  const runExtract = async () => {
    try {
      const result = await extract.mutateAsync();
      toast.success(result.points.length ? `${result.points.length} points` : "Nothing new");
      onExtracted();
    } catch (error) {
      if (error instanceof ExtractionCancelled) toast.message(error.message);
      else toast.error(error instanceof Error ? error.message : "Extraction failed");
    }
  };

  // With the queue on, the API answers `queued` and the hook polls /extractions/{id} every 2 s.
  const extractLabel =
    extract.phase === "queued"
      ? "Queued…"
      : extract.isPending
        ? "Extracting…"
        : "Extract points";

  return (
    <div className="flex h-full min-h-0 flex-col gap-6 md:flex-row md:gap-8">
      <section className="w-full shrink-0 md:w-[320px]">
        <h2 className="mb-1 text-[15px] font-semibold">Sources</h2>
        <p className="mb-3 text-xs text-muted-foreground">Found from the meeting record. Nothing is fetched until you import.</p>
        <ul className="divide-y border-y">
          {(sources.data?.sources ?? []).map((s, i) => (
            <li key={`${s.key}-${i}`} className={cn("flex items-center gap-3 py-2.5", !s.available && "text-muted-foreground")}>
              <div className="min-w-0 flex-1">
                <div className="text-[13px]">{s.title}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {s.message || (s.connection ? `through ${shortName(s.connection)}@` : "available")}
                </div>
              </div>
              {s.source === "paste" ? (
                <span className="text-xs text-muted-foreground">below</span>
              ) : imported(s.source) ? (
                <span className="text-xs text-muted-foreground">imported</span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  disabled={!s.available || importNote.isPending}
                  onClick={() => void runImport(s.source as NoteSource, s.origin_ref)}
                >
                  Import
                </Button>
              )}
            </li>
          ))}
          {sources.isLoading && <li className="py-2.5 text-xs text-muted-foreground">Looking…</li>}
        </ul>
        <button
          className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => void sources.refetch()}
        >
          Retry the lookup
        </button>
      </section>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-5">
        <div>
          <div className="mb-1 flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold">Saved notes</h2>
            <span className="text-xs text-muted-foreground">{rows.length} · untick to leave one out</span>
          </div>
          {rows.length === 0 ? (
            <div className="border-y py-4 text-center text-xs text-muted-foreground">No notes yet.</div>
          ) : (
            <ul className="divide-y border-y">
              {rows.map((n) => (
                <li key={n.id} className="flex items-center gap-3 py-2 text-[13px]">
                  <Checkbox
                    checked={n.include}
                    onCheckedChange={(v) => patchNote.mutate({ id: n.id, include: !!v })}
                    aria-label="Include in extraction"
                  />
                  <span className="w-14 shrink-0 text-xs text-muted-foreground">{SRC_LABEL[n.source] ?? n.source}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {n.title} <span className="text-muted-foreground">· {n.word_count} words · {shortName(n.created_by)}</span>
                  </span>
                  {/* Spec section 7: "a note can be moved to another meeting afterwards" (R1-22). */}
                  {targets.length > 0 && (
                    <select
                      className="h-7 w-20 shrink-0 rounded border bg-background px-1 text-xs text-muted-foreground md:w-24"
                      aria-label="Move to another meeting"
                      value=""
                      disabled={moveNote.isPending}
                      onChange={(e) => void move(n.id, e.target.value)}
                    >
                      <option value="">Move…</option>
                      {targets.map((m) => (
                        <option key={m.id} value={m.id!}>{m.title || "Untitled"}</option>
                      ))}
                    </select>
                  )}
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" aria-label="Delete note" onClick={() => deleteNote.mutate(n.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1 flex items-center gap-2">
            <h2 className="text-[15px] font-semibold">Paste</h2>
            <Button size="sm" className="ml-auto h-8" disabled={!paste.trim() || pasteNote.isPending} onClick={() => void savePaste()}>Save note</Button>
          </div>
          <Textarea
            id="paste"
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            placeholder="Paste notes, a transcript or a summary"
            className="min-h-[180px] flex-1 resize-none text-[13px] leading-relaxed md:min-h-[220px]"
          />
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" className="h-9" onClick={onBack}>Back</Button>
          {/* R1-11: no fixed model name here; Step 3 names whoever actually answered. */}
          {extract.isPending && <span className="hidden text-xs text-muted-foreground sm:inline">Extracting… you can leave this page.</span>}
          {extract.isPolling && (
            <Button variant="outline" className="ml-auto h-9" data-testid="cancel-extract" onClick={extract.cancel}>
              Cancel
            </Button>
          )}
          <Button
            className={cn("h-9", extract.isPolling ? "" : "ml-auto")}
            disabled={!rows.some((n) => n.include) || extract.isPending}
            onClick={() => void runExtract()}
          >
            {extractLabel}
          </Button>
        </div>
      </section>
    </div>
  );
}
