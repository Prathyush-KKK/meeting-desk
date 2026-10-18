import { useCallback, useMemo, useRef, useState } from "react";
import { Plus, X, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MeetingList, itemKey } from "@/components/MeetingList";
import { ExtractionLines, TransferLines } from "@/components/History";
import { cn } from "@/lib/utils";
import { useCloseOnBack } from "@/lib/overlay";
import { useAutoGrow } from "@/lib/autogrow";
import { ago, displayTimeZone, fmtDate, mergeWorkstreams, plural, zoneLabel } from "@/lib/display";
import { parseAttendees } from "@/lib/attendees";
import {
  useCaptureCalendarEvent,
  useCreateManualMeeting,
  useDeleteMeeting,
  useExtractions,
  useMeetings,
  useMeetingTransfers,
  usePatchMeeting,
  useQuickPaste,
  useRefreshMeetings,
  useRestoreMeeting,
  type ManualMeetingIn,
} from "@/api/hooks";
import type { MeetingItem } from "@/api/types";

interface Props {
  selectedKey: string | null;
  onSelectKey: (key: string | null) => void;
  onContinue: (meetingId: string) => void;
  /** Straight to a saved meeting's notes or points, whatever its date and however far it got. */
  onOpenStep: (meetingId: string, step: "notes" | "points") => void;
}

const today = () => new Date().toISOString().slice(0, 10);

export function MeetingStep({ selectedKey, onSelectKey, onContinue, onOpenStep }: Props) {
  const meetings = useMeetings();
  const refresh = useRefreshMeetings();
  const capture = useCaptureCalendarEvent();
  const createManual = useCreateManualMeeting();
  const quickPaste = useQuickPaste();

  const [openKey, setOpenKey] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [paste, setPaste] = useState("");
  const pasteRef = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(pasteRef, paste);

  const items = meetings.data?.items ?? [];
  const selected = items.find((m) => itemKey(m) === selectedKey) ?? null;
  const open = items.find((m) => itemKey(m) === openKey) ?? null;
  const workstreams = useMemo(() => mergeWorkstreams(items.map((m) => m.workstream)), [items]);

  /** A calendar card has no row until it is picked; Continue and paste both need one. */
  const ensureSaved = async (item: MeetingItem): Promise<string> => {
    if (item.id) return item.id;
    if (!item.calendar_event_id) throw new Error("This card cannot be captured.");
    const saved = await capture.mutateAsync({ calendar_event_id: item.calendar_event_id, workstream: item.workstream });
    onSelectKey(saved.id);
    return saved.id!;
  };

  const go = async (item: MeetingItem) => {
    try {
      onContinue(await ensureSaved(item));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not open that meeting");
    }
  };

  const addMeeting = async () => {
    const body: ManualMeetingIn = { title: "", date: today(), start: "10:00", end: "10:30", workstream: workstreams[1] ?? "" };
    const created = await createManual.mutateAsync(body);
    onSelectKey(created.id);
    setOpenKey(created.id);
    setEditing(true);
  };

  const savePaste = async () => {
    const text = paste.trim();
    if (!text) return;
    try {
      const meetingId = selected ? await ensureSaved(selected) : null;
      const result = await quickPaste.mutateAsync({ text, meeting_id: meetingId });
      setPaste("");
      onSelectKey(result.meeting.id);
      toast.success(result.created_meeting ? `Created "${result.meeting.title}" from the paste` : `Saved on ${result.meeting.title}`);
      if (!result.created) toast.message("That text was already saved on this meeting.");
      onContinue(result.meeting.id!);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save the paste");
    }
  };

  const openPanel = (m: MeetingItem, edit: boolean) => {
    setOpenKey(itemKey(m));
    setEditing(edit && m.editable);
    onSelectKey(itemKey(m));
  };
  const closePanel = useCallback(() => { setOpenKey(null); setEditing(false); }, []);

  /**
   * A click on another card while the detail is open moves the detail to that card. It used
   * to stay on the first one, so the panel's Continue and the list's Continue meant two meetings.
   */
  const select = (m: MeetingItem) => {
    const key = itemKey(m);
    onSelectKey(key);
    if (openKey && openKey !== key) {
      setOpenKey(key);
      setEditing(false);
    }
  };

  // The detail is a full-screen overlay under 768 px, so Back has to close it rather than leave
  // the app. Above the breakpoint the same entry makes
  // Back close the side panel, which is also where a person expects to land.
  useCloseOnBack(!!open, closePanel);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 md:flex-row md:gap-8">
      <section className={cn("flex min-h-0 flex-col transition-[width] duration-200", open ? "md:w-[320px] md:shrink-0 lg:w-[380px]" : "mx-auto w-full md:max-w-[640px]")}>
        <div className="mb-2 flex items-center gap-3">
          <h2 className="text-[15px] font-semibold">Meetings</h2>
          <span className="text-xs text-muted-foreground">{items.length}</span>
          <Button size="sm" variant="outline" className="ml-auto h-8" onClick={addMeeting} disabled={createManual.isPending}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Add meeting
          </Button>
        </div>

        <div className="mb-3">
          <Textarea
            id="quickpaste"
            ref={pasteRef}
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            rows={2}
            placeholder={selected ? `Paste notes for "${selected.title || selected.key}"` : "Paste notes here. With no meeting selected, a manual meeting is created from the first line."}
            className="min-h-0 resize-none text-[13px]"
          />
          {paste.trim() && (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-xs text-muted-foreground">{selected ? `Saves as a note on ${selected.title || selected.key}` : "Creates a manual meeting"}</span>
              <Button size="sm" className="ml-auto h-8" onClick={savePaste} disabled={quickPaste.isPending}>Save and continue</Button>
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {meetings.isLoading && <div className="border-y py-6 text-center text-xs text-muted-foreground">Reading the calendars…</div>}
          {meetings.isError && <div className="border-y py-6 text-center text-xs font-medium">{meetings.error.message}</div>}
          {!meetings.isLoading && !meetings.isError && items.length === 0 && (
            <div className="border-y py-6 text-center text-xs text-muted-foreground">
              {meetings.data?.empty_hint || "No meeting here? Add one, or paste the notes straight into the box above."}
            </div>
          )}
          {items.length > 0 && (
            <MeetingList
              items={items}
              selectedKey={selectedKey}
              onSelect={select}
              onOpen={openPanel}
              onContinue={(m) => void go(m)}
              onOpenNotes={(m) => m.id && onOpenStep(m.id, "notes")}
              onOpenPoints={(m) => m.id && onOpenStep(m.id, "points")}
            />
          )}
        </div>
        {/* The calendar cache: "updated N min ago" and an explicit Refresh, at every width (it was
            hidden under 640 px and wrapped in the narrow column). */}
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          {meetings.data && <span data-testid="calendar-age">updated {ago(meetings.data.age_minutes)}</span>}
          <button
            className="underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? "Refreshing…" : "Refresh"}
          </button>
          {/* With the detail open, its own Continue is the one; one button, one meeting. */}
          <Button
            className={cn("ml-auto h-9", open && "md:hidden")}
            disabled={!selected || capture.isPending}
            onClick={() => selected && void go(selected)}
          >
            Continue
          </Button>
        </div>
      </section>

      {open && (
        <aside key={itemKey(open)} data-testid="meeting-detail" className="fixed inset-0 z-40 flex min-h-0 flex-col overflow-y-auto bg-background p-4 md:static md:z-auto md:min-w-0 md:flex-1 md:border-l md:pl-8 md:pr-0 md:pt-0 md:animate-in md:fade-in md:slide-in-from-right-2 md:duration-200" style={{ paddingTop: "max(1rem, env(safe-area-inset-top, 0px))" }}>
          <div className="mb-3 flex items-start gap-2">
            <div className="min-w-0">
              <h3 className="truncate text-[15px] font-semibold">{open.title || "New manual meeting"}</h3>
              <div className="text-xs text-muted-foreground">
                {open.key ? <span className="mono">{open.key}</span> : "Not captured yet"} · {open.source === "calendar" ? "Google Calendar, read-only" : editing ? "Manual, editing" : "Manual"}
              </div>
            </div>
            <div className="ml-auto flex gap-1">
              {open.editable && !editing && <Button variant="outline" size="sm" className="h-8" onClick={() => setEditing(true)}>Edit</Button>}
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Close" onClick={closePanel}><X className="h-4 w-4" /></Button>
            </div>
          </div>

          {editing && open.id ? (
            <ManualForm
              meeting={open}
              workstreams={workstreams}
              onSaved={() => { setEditing(false); toast.success("Saved"); }}
              onDeleted={() => { closePanel(); onSelectKey(null); }}
            />
          ) : (
            <div className="flex-1">
              <dl className="grid content-start grid-cols-[96px_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-[13px] lg:grid-cols-[120px_minmax(0,1fr)]">
                <dt className="text-muted-foreground">When</dt><dd>{fmtDate(open.date)} · {open.start}-{open.end} {zoneLabel()}</dd>
                <dt className="text-muted-foreground">Organizer</dt><dd className="break-all">{open.organizer_email}</dd>
                <dt className="text-muted-foreground">Attendees</dt>
                <dd>{open.attendees.length ? open.attendees.map((a) => `${a.name || a.email} (${a.response})`).join(", ") : "none"}</dd>
                <dt className="text-muted-foreground">Meet</dt><dd className="break-all">{open.conference?.meet_link || "none"}</dd>
                <dt className="text-muted-foreground">Location</dt><dd>{open.location || "none"}</dd>
                <dt className="text-muted-foreground">Recurrence</dt><dd>{open.recurring_event_id ? "part of a series" : "single event"}</dd>
                <dt className="text-muted-foreground">Description</dt><dd className="whitespace-pre-wrap">{open.description || "none"}</dd>
                <dt className="text-muted-foreground">Attachments</dt><dd>{open.attachments.length ? open.attachments.map((a) => a.title).join(", ") : "none"}</dd>
                <dt className="text-muted-foreground">Workstream</dt><dd>{open.workstream || "not set"}</dd>
                <dt className="text-muted-foreground">Shown in</dt><dd>{displayTimeZone()}{open.timezone && open.timezone !== displayTimeZone() ? ` (organizer: ${open.timezone})` : ""}</dd>
                {open.calendar_event_id && <><dt className="text-muted-foreground">Event id</dt><dd className="mono break-all">{open.calendar_event_id}</dd></>}
              </dl>
              {open.id ? (
                <MeetingHistory meeting={open} onOpenStep={onOpenStep} />
              ) : (
                <p className="mt-5 border-t pt-3 text-xs text-muted-foreground">Not captured yet. Continue captures it.</p>
              )}
            </div>
          )}

          {!editing && (
            <div className="mt-4 flex items-center gap-2 border-t pt-3">
              <Button className="ml-auto h-9" onClick={() => void go(open)}>Continue</Button>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

const LABEL = "mb-1 mt-3 text-[11px] uppercase tracking-wide text-muted-foreground";

/**
 * What already happened on a saved meeting, so a past one is somewhere to look things up rather
 * than only something to continue. No headings here: the panel's one heading is its title.
 */
function MeetingHistory({ meeting, onOpenStep }: { meeting: MeetingItem; onOpenStep: Props["onOpenStep"] }) {
  const id = meeting.id!;
  const extractions = useExtractions(id);
  const transfers = useMeetingTransfers(id);
  return (
    <div data-testid="meeting-history" className="mt-5 border-t pt-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span>{plural(meeting.notes_count, "note")}</span>
        <span>{plural(meeting.points_count, "point")}</span>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" className="h-8" onClick={() => onOpenStep(id, "notes")}>Open notes</Button>
          <Button variant="outline" size="sm" className="h-8" onClick={() => onOpenStep(id, "points")}>Open points</Button>
        </div>
      </div>
      <div className={LABEL}>Extractions</div>
      <ExtractionLines runs={extractions.data ?? []} loading={extractions.isLoading} />
      <div className={LABEL}>Transfers</div>
      <TransferLines transfers={transfers.data ?? []} loading={transfers.isLoading} empty="Nothing transferred yet." />
    </div>
  );
}

function ManualForm({
  meeting,
  workstreams,
  onSaved,
  onDeleted,
}: {
  meeting: MeetingItem;
  workstreams: string[];
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const patch = usePatchMeeting();
  const remove = useDeleteMeeting();
  const restore = useRestoreMeeting();
  const [f, setF] = useState({
    title: meeting.title,
    date: meeting.date ?? today(),
    start: meeting.start ?? "10:00",
    end: meeting.end ?? "10:30",
    description: meeting.description,
    location: meeting.location,
    workstream: meeting.workstream || workstreams[0],
    attendeesText: meeting.attendees.map((a) => a.name || a.email).join(", "),
  });

  const save = async () => {
    const attendees = parseAttendees(f.attendeesText, meeting.attendees);
    try {
      await patch.mutateAsync({
        id: meeting.id!,
        patch: { title: f.title, date: f.date, start: f.start, end: f.end, description: f.description, location: f.location, workstream: f.workstream, attendees },
      });
      onSaved();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save");
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* content-start: the fields sit together at the top instead of spreading over the panel's
          height. */}
      <div className="grid flex-1 grid-cols-1 content-start gap-3 sm:grid-cols-2">
        <Field id="mt" label="Title" full><Input id="mt" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Meeting title" /></Field>
        <Field id="md" label="Date"><Input id="md" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field id="ms" label="Start"><Input id="ms" type="time" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
          <Field id="me" label="End"><Input id="me" type="time" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
        </div>
        <Field id="mw" label="Workstream">
          <select id="mw" className="h-9 rounded border bg-background px-2 text-sm" value={f.workstream} onChange={(e) => setF({ ...f, workstream: e.target.value })}>
            {workstreams.map((w) => <option key={w}>{w}</option>)}
          </select>
        </Field>
        <Field id="ma" label="Attendees, comma separated" full><Input id="ma" value={f.attendeesText} onChange={(e) => setF({ ...f, attendeesText: e.target.value })} placeholder="Alex S, Daniel Okafor" /></Field>
        <Field id="mloc" label="Location"><Input id="mloc" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field id="mdesc" label="Description" full><Textarea id="mdesc" rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      </div>
      <div className="mt-4 flex items-center gap-2 border-t pt-3">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-destructive"
          onClick={async () => {
            const id = meeting.id!;
            await remove.mutateAsync(id);
            // Accidental delete: a soft delete with a 10-second undo toast.
            toast.message(`Deleted ${meeting.title || "the meeting"}`, {
              description: "10 seconds to undo; recoverable for 30 days.",
              duration: 10_000,
              action: { label: "Undo", onClick: () => restore.mutate(id) },
            });
            onDeleted();
          }}
        >
          <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
        </Button>
        <Button className="ml-auto h-9" onClick={() => void save()} disabled={!f.title.trim() || patch.isPending}>Save</Button>
      </div>
    </div>
  );
}

function Field({ id, label, children, full }: { id: string; label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-1", full && "sm:col-span-2")}>
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}
