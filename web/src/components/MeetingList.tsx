import type { MouseEvent } from "react";
import { Eye, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { dayGroup, fmtDate, localToday, plural, type DayGroup } from "@/lib/display";
import type { MeetingItem } from "@/api/types";

const STEP_TEXT: Record<string, string> = {
  meeting: "",
  notes: "notes saved",
  points: "points ready",
  done: "transferred",
};

const GROUPS: { key: DayGroup; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "today", label: "Today" },
  { key: "earlier", label: "Earlier" },
];

/** A calendar card has no row yet, so it is keyed on the event id until it is captured. */
export function itemKey(item: MeetingItem): string {
  return item.id ?? `event:${item.calendar_event_id ?? item.ical_uid ?? item.title}`;
}

interface Props {
  items: MeetingItem[];
  selectedKey: string | null;
  onSelect: (item: MeetingItem) => void;
  onOpen: (item: MeetingItem, edit: boolean) => void;
  onContinue: (item: MeetingItem) => void;
  onOpenNotes: (item: MeetingItem) => void;
  onOpenPoints: (item: MeetingItem) => void;
}

/** A count in the meta that goes straight to that step. Neither a pick nor a Continue on the row. */
function MetaLink({ label, testId, children, onClick }: { label: string; testId: string; children: string; onClick: () => void }) {
  const stop = (e: MouseEvent) => e.stopPropagation();
  return (
    <button
      type="button"
      aria-label={label}
      data-testid={testId}
      className="underline-offset-2 hover:text-foreground hover:underline"
      onClick={(e) => { stop(e); onClick(); }}
      onDoubleClick={stop}
    >
      {children}
    </button>
  );
}

export function MeetingList({ items, selectedKey, onSelect, onOpen, onContinue, onOpenNotes, onOpenPoints }: Props) {
  // The calendar window runs 30 days back and 14 ahead, so the list says which side of today a
  // meeting is on. Each group keeps the API's order.
  const today = localToday();
  const groups = GROUPS.map((g) => ({ ...g, items: items.filter((m) => dayGroup(m.date, today) === g.key) })).filter((g) => g.items.length);

  const row = (m: MeetingItem) => {
    const key = itemKey(m);
    const isSel = key === selectedKey;
    const step = STEP_TEXT[m.step] || "";
    const meta: { part: string; open?: "notes" | "points" }[] = [
      { part: m.attendees.length === 1 ? "1 person" : `${m.attendees.length} people` },
      { part: m.source === "calendar" ? "Calendar" : "Manual" },
      { part: m.attachments.some((a) => a.kind === "doc") ? "Gemini notes" : "" },
      // A calendar card has no row yet, so nothing to open; its counts stay plain text.
      { part: m.id && m.notes_count > 0 ? plural(m.notes_count, "note") : "", open: "notes" },
      { part: m.points_count > 0 ? plural(m.points_count, "point") : "", open: m.id ? "points" : undefined },
    ];
    return (
      <li
        key={key}
        data-testid="meeting-row"
        data-source={m.source}
        onClick={() => onSelect(m)}
        onDoubleClick={() => onContinue(m)}
        // R1-45: a card could only be picked with a mouse. Tab reaches it, Space picks it, Enter
        // continues with it - the keyboard's click and double-click.
        tabIndex={0}
        aria-current={isSel ? "true" : undefined}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter") {
            e.preventDefault();
            onContinue(m);
          } else if (e.key === " ") {
            e.preventDefault();
            onSelect(m);
          }
        }}
        // No negative margins: inside the list's scroll box they made the row wider than the box,
        // so on a phone the box scrolled sideways and clipped the titles (R1-02).
        className={cn("group relative cursor-pointer py-2.5 pl-2 pr-24 focus-visible:-outline-offset-2 md:pr-20", isSel ? "bg-secondary" : "hover:bg-secondary/60")}
      >
        <div className="flex items-baseline gap-2">
          <span className={cn("truncate text-[14px]", !m.title && "italic text-muted-foreground", isSel && "font-medium")}>
            {m.title || "Untitled manual meeting"}
          </span>
          {step && <span className="shrink-0 text-xs text-muted-foreground">· {step}</span>}
          {m.in_progress_by && <span className="shrink-0 text-xs text-muted-foreground">· {m.in_progress_by.split("@")[0]} here</span>}
        </div>
        {/* Each separator travels with the item after it, so a wrapped line never ends on a dot. */}
        <div className="mt-0.5 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground" data-testid="meeting-meta">
          <span className="mono">{fmtDate(m.date)} {m.start}</span>
          {meta
            .filter(({ part }) => part)
            .map(({ part, open }) => (
              <span key={part} className="whitespace-nowrap">
                {"· "}
                {open === "notes" ? (
                  <MetaLink label="Open notes" testId="open-notes" onClick={() => onOpenNotes(m)}>{part}</MetaLink>
                ) : open === "points" ? (
                  <MetaLink label="Open points" testId="open-points" onClick={() => onOpenPoints(m)}>{part}</MetaLink>
                ) : (
                  part
                )}
              </span>
            ))}
        </div>
        <div className="absolute right-0 top-1 flex gap-0.5">
          {m.editable && (
            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" aria-label="Edit meeting" onClick={(e) => { e.stopPropagation(); onOpen(m, true); }}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" aria-label="Show meeting details" onClick={(e) => { e.stopPropagation(); onOpen(m, false); }}>
            <Eye className="h-3.5 w-3.5" />
          </Button>
        </div>
      </li>
    );
  };

  return (
    <div>
      {groups.map((g, i) => (
        <div key={g.key} data-testid="meeting-group" data-group={g.key}>
          <div className={cn("px-2 pb-1 text-[11px] uppercase tracking-wide text-muted-foreground", i > 0 && "pt-4")}>{g.label}</div>
          <ul className="divide-y border-y">{g.items.map(row)}</ul>
        </div>
      ))}
    </div>
  );
}
