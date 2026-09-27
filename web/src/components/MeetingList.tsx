import { Eye, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { fmtDate } from "@/lib/display";
import type { MeetingItem } from "@/api/types";

const STEP_TEXT: Record<string, string> = {
  meeting: "",
  notes: "notes saved",
  points: "points ready",
  done: "transferred",
};

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
}

export function MeetingList({ items, selectedKey, onSelect, onOpen, onContinue }: Props) {
  return (
    <ul className="divide-y border-y">
      {items.map((m) => {
        const key = itemKey(m);
        const isSel = key === selectedKey;
        const step = STEP_TEXT[m.step] || "";
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
              {[
                m.attendees.length === 1 ? "1 person" : `${m.attendees.length} people`,
                m.source === "calendar" ? "Calendar" : "Manual",
                m.attachments.some((a) => a.kind === "doc") ? "Gemini notes" : "",
                m.points_count > 0 ? (m.points_count === 1 ? "1 point" : `${m.points_count} points`) : "",
              ]
                .filter(Boolean)
                .map((part) => (
                  <span key={part} className="whitespace-nowrap">· {part}</span>
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
      })}
    </ul>
  );
}
