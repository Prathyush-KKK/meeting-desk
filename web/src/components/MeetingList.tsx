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
            className={cn("group relative cursor-pointer py-2.5 pl-3 pr-20 -ml-3 -mr-3 md:-mx-0 md:pl-2", isSel ? "bg-secondary" : "hover:bg-secondary/60")}
          >
            <div className="flex items-baseline gap-2">
              <span className={cn("truncate text-[14px]", !m.title && "italic text-muted-foreground", isSel && "font-medium")}>
                {m.title || "Untitled manual meeting"}
              </span>
              {step && <span className="shrink-0 text-xs text-muted-foreground">· {step}</span>}
              {m.in_progress_by && <span className="shrink-0 text-xs text-muted-foreground">· {m.in_progress_by.split("@")[0]} here</span>}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
              <span className="mono">{fmtDate(m.date)} {m.start}</span>
              <span>·</span>
              <span>{m.attendees.length} people</span>
              <span>·</span>
              <span>{m.source === "calendar" ? "Calendar" : "Manual"}</span>
              {m.attachments.some((a) => a.kind === "doc") && <><span>·</span><span>Gemini notes</span></>}
              {m.points_count > 0 && <><span>·</span><span>{m.points_count} points</span></>}
            </div>
            <div className="absolute right-1 top-1.5 flex gap-0.5">
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
