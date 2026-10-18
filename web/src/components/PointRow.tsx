import { useRef } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useAutoGrow } from "@/lib/autogrow";
import { useNarrow } from "@/lib/overlay";
import { DECISION_STATUSES, KIND_ORDER, STATUSES, STATUS_LABEL } from "@/lib/display";
import type { Point, Status } from "@/api/types";
import type { PointPatch } from "@/api/hooks";

export const SELECT_CLASS = "h-8 rounded border bg-background px-2 text-xs";

/**
 * Eight tracks, one control each: tick, kind, point, owner, due, status, workstream, and the row's
 * own actions (Defer, Remove). Screen review round 1, R1-01: the actions used to share the
 * workstream's 130 px track, so at 1280 px they sat past the right edge and the list scrolled
 * sideways to reach them. The tracks narrow between 768 and 1024 px so the row still fits there.
 */
export const ROW_GRID =
  "md:grid md:grid-cols-[20px_80px_minmax(0,1fr)_130px_90px_104px_110px_68px] lg:grid-cols-[24px_88px_minmax(0,1fr)_170px_110px_120px_130px_76px] md:items-center md:gap-2 md:py-1";

/** Each field fills its cell: the phone's six-column grid, or its track from 768 px. */
const FIELD = "w-full min-w-0";

interface Props {
  point: Point;
  owners: string[];
  workstreams: string[];
  onPatch: (patch: PointPatch) => void;
  onDefer: () => void;
  onRestore: () => void;
  onRemove: () => void;
  onTransfer?: () => void;
}

/**
 * One point. Deferred points are shown read-only with Restore and Transfer, per spec section 2.
 *
 * Under 768 px the row wraps (spec section 2): the tick, the point's text (wrapping and growing,
 * R4-01), Defer and Remove; then the fields in a six-column grid, two lines, nothing scrolling
 * sideways (R4-03). From 768 px both parts dissolve (`md:contents`) into the eight grid tracks, and
 * `md:order-*` puts Kind in front of the text and the actions last.
 */
export function PointRow({ point, owners, workstreams, onPatch, onDefer, onRestore, onRemove, onTransfer }: Props) {
  const deferred = point.lifecycle === "deferred";
  const narrow = useNarrow();

  if (deferred) {
    return (
      <div data-testid="point-row" data-lifecycle="deferred" className="flex flex-wrap items-center gap-2 border-b px-2 py-2 text-[13px]">
        <span className="hidden w-20 shrink-0 text-xs text-muted-foreground sm:inline">{point.kind}</span>
        {/* R4-04: read in full on a phone too, like an active point's text (R4-01). */}
        <span className="min-w-0 flex-1 break-words md:truncate" data-testid="deferred-text">{point.text || "Untitled point"}</span>
        <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
          {point.owner_text || "unassigned"}{point.due_text ? ` · ${point.due_text}` : ""}
        </span>
        <Button size="sm" variant="outline" className="h-8" onClick={onRestore}>Restore</Button>
        {onTransfer && <Button size="sm" variant="outline" className="h-8" onClick={onTransfer}>Transfer</Button>}
      </div>
    );
  }

  const statuses: Status[] = point.kind === "decision" ? DECISION_STATUSES : STATUSES;
  return (
    <div
      data-testid="point-row"
      data-lifecycle="active"
      className={cn("border-b px-2 py-2", ROW_GRID, point.selected && "bg-secondary/60")}
    >
      <div className="flex items-start gap-2 md:contents md:items-center" data-line="1">
        <Checkbox className="mt-3.5 md:order-1 md:mt-0" checked={point.selected} onCheckedChange={(v) => onPatch({ selected: !!v })} aria-label="Select point" />
        {narrow ? (
          <PointText value={point.text} onChange={(text) => onPatch({ text })} />
        ) : (
          <Input
            className="h-8 min-w-0 flex-1 border-transparent bg-transparent px-1 text-[13px] hover:border-input focus:border-input md:order-3 md:text-[13px]"
            value={point.text}
            onChange={(e) => onPatch({ text: e.target.value })}
            placeholder="Describe the point"
            aria-label="Point"
          />
        )}
        {/* The row's own actions: beside the text on a phone, the eighth track from 768 px. */}
        <div className="flex shrink-0 items-center gap-1 md:order-8" data-testid="point-actions">
          <Button variant="ghost" size="sm" className="h-7 px-1.5 text-xs text-muted-foreground" onClick={onDefer}>Defer</Button>
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-destructive" aria-label="Remove point" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {/* R4-03: on a phone the fields are a six-column grid, two lines - kind and owner; due,
          status and workstream. They used to be a strip that scrolled sideways inside the row. */}
      <div className="mt-1.5 grid grid-cols-6 gap-1.5 md:contents" data-line="2">
        <select className={cn(SELECT_CLASS, FIELD, "max-md:col-span-2 md:order-2")} value={point.kind} onChange={(e) => onPatch({ kind: e.target.value })} aria-label="Kind">
          {KIND_ORDER.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <select
          className={cn(SELECT_CLASS, FIELD, "max-md:col-span-4 md:order-4", point.owner_ambiguous && "font-medium underline decoration-dotted underline-offset-2")}
          value={point.owner_text}
          onChange={(e) => onPatch({ owner_text: e.target.value })}
          aria-label="Owner"
        >
          <option value="">unassigned</option>
          {point.owner_text && !owners.includes(point.owner_text) && (
            <option value={point.owner_text}>{point.owner_text}{point.owner_email ? "" : " (unknown)"}</option>
          )}
          {owners.map((o) => <option key={o}>{o}</option>)}
        </select>
        <Input
          className={cn(FIELD, "h-8 bg-background px-2 text-xs max-md:col-span-2 md:order-5 md:text-xs")}
          value={point.due_text}
          onChange={(e) => onPatch({ due_text: e.target.value })}
          placeholder="due"
          aria-label="Due"
        />
        <select className={cn(SELECT_CLASS, FIELD, "max-md:col-span-2 md:order-6")} value={point.status} onChange={(e) => onPatch({ status: e.target.value })} aria-label="Status">
          {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <select className={cn(SELECT_CLASS, FIELD, "max-md:col-span-2 md:order-7")} value={point.workstream} onChange={(e) => onPatch({ workstream: e.target.value })} aria-label="Workstream">
          {point.workstream && !workstreams.includes(point.workstream) && <option value={point.workstream}>{point.workstream}</option>}
          {workstreams.map((w) => <option key={w}>{w}</option>)}
        </select>
      </div>
    </div>
  );
}

/**
 * The point's text on a phone (screen review R4-01): it wraps and the box grows with it, so the
 * whole point reads without scrolling inside a one-line field ("Send the Northwind questionnaire by
 * Frida"). A point is one line in the sheet, so Enter does not add a line break; the wrapping is
 * only how it is shown. Same value, same onChange as the desktop input, so autosave and the caret
 * behave the same way.
 */
function PointText({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(ref, value, Number.POSITIVE_INFINITY);
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\r?\n/g, " "))}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.preventDefault();
      }}
      placeholder="Describe the point"
      aria-label="Point"
      data-testid="point-text-phone"
      className="min-h-11 min-w-0 flex-1 resize-none overflow-hidden rounded-md border border-transparent bg-transparent px-1 py-[11px] text-[13px] leading-5 placeholder:text-muted-foreground hover:border-input focus:border-input focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    />
  );
}
