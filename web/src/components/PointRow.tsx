import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { DECISION_STATUSES, KIND_ORDER, STATUSES, STATUS_LABEL } from "@/lib/display";
import type { Point, Status } from "@/api/types";
import type { PointPatch } from "@/api/hooks";

export const SELECT_CLASS = "h-8 rounded border bg-background px-2 text-xs";
export const ROW_GRID = "md:grid md:grid-cols-[24px_88px_minmax(0,1fr)_170px_96px_120px_130px] md:items-center md:gap-2 md:py-1";

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

/** One point. Deferred points are shown read-only with Restore and Transfer, per spec section 2. */
export function PointRow({ point, owners, workstreams, onPatch, onDefer, onRestore, onRemove, onTransfer }: Props) {
  const deferred = point.lifecycle === "deferred";

  if (deferred) {
    return (
      <div data-testid="point-row" data-lifecycle="deferred" className="flex flex-wrap items-center gap-2 border-b px-2 py-2 text-[13px]">
        <span className="w-20 shrink-0 text-xs text-muted-foreground">{point.kind}</span>
        <span className="min-w-0 flex-1 truncate">{point.text || "Untitled point"}</span>
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
      <div className="flex items-center gap-2 md:contents">
        <Checkbox checked={point.selected} onCheckedChange={(v) => onPatch({ selected: !!v })} aria-label="Select point" />
        <select className={cn(SELECT_CLASS, "w-24")} value={point.kind} onChange={(e) => onPatch({ kind: e.target.value })} aria-label="Kind">
          {KIND_ORDER.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <div className="flex min-w-0 flex-1 items-center gap-1 md:contents">
          <Input
            className="h-8 min-w-0 flex-1 border-transparent bg-transparent px-1 text-[13px] hover:border-input focus:border-input"
            value={point.text}
            onChange={(e) => onPatch({ text: e.target.value })}
            placeholder="Describe the point"
            aria-label="Point"
          />
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-destructive md:hidden" aria-label="Remove point" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 md:contents">
        <select
          className={cn(SELECT_CLASS, "max-w-[170px]", point.owner_ambiguous && "font-medium underline decoration-dotted underline-offset-2")}
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
        <Input className="h-8 w-24 px-2 text-xs" value={point.due_text} onChange={(e) => onPatch({ due_text: e.target.value })} placeholder="due" aria-label="Due" />
        <select className={SELECT_CLASS} value={point.status} onChange={(e) => onPatch({ status: e.target.value })} aria-label="Status">
          {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <div className="flex items-center gap-1">
          <select className={SELECT_CLASS} value={point.workstream} onChange={(e) => onPatch({ workstream: e.target.value })} aria-label="Workstream">
            {point.workstream && !workstreams.includes(point.workstream) && <option value={point.workstream}>{point.workstream}</option>}
            {workstreams.map((w) => <option key={w}>{w}</option>)}
          </select>
          <Button variant="ghost" size="sm" className="h-7 px-1.5 text-xs text-muted-foreground" onClick={onDefer}>Defer</Button>
          <Button variant="ghost" size="icon" className="hidden h-7 w-7 shrink-0 text-destructive md:inline-flex" aria-label="Remove point" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
