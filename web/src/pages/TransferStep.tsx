import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Grid, MARK_CLASS, type CellMark } from "@/components/Grid";
import {
  a1,
  applyPlan,
  colLetter,
  detectLayout,
  planAppend,
  planCells,
  planFill,
  type Conflict,
  type PointForSheet,
} from "@/lib/sheet";
import { cn } from "@/lib/utils";
import { useBatchId } from "@/lib/batch";
import { fmtClock, meetingLabel, STATUS_LABEL } from "@/lib/display";
import {
  useTab,
  useTransferExecute,
  useTransferPreview,
  useUndoTransfer,
  useWorkbooks,
  usePoints,
  type PreviewIn,
} from "@/api/hooks";
import { ApiError } from "@/api/client";
import type { MeetingItem, Point } from "@/api/types";

interface Props {
  meeting: MeetingItem;
  pointIds: string[];
  onBack: () => void;
  onDone: (workbookId: string, sheetId: string) => void;
}

function numericDropdowns(dd: Record<string, string[]> | undefined): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  for (const [k, v] of Object.entries(dd ?? {})) out[Number(k)] = v;
  return out;
}

export function TransferStep({ meeting, pointIds, onBack, onDone }: Props) {
  const workbooks = useWorkbooks();
  const active = usePoints(meeting.id, "active");
  const deferred = usePoints(meeting.id, "deferred");
  const [wbId, setWbId] = useState<string>("");
  const [sheetId, setSheetId] = useState<string>("");
  const [mode, setMode] = useState<"append" | "fill">("append");
  const [anchor, setAnchor] = useState<{ r: number; c: number } | null>(null);
  const [writeKeys, setWriteKeys] = useState(true);
  const [conflict, setConflict] = useState<Conflict>("skip");
  const [staleNotice, setStaleNotice] = useState("");
  const [repeat, setRepeat] = useState<string>("");

  const books = workbooks.data ?? [];
  const wb = books.find((w) => w.id === wbId) ?? books[0];
  const tabMeta = wb?.tabs.find((t) => t.sheet_id === sheetId) ?? wb?.tabs[0];
  const tab = useTab(wb?.id ?? null, tabMeta?.sheet_id ?? null);
  const execute = useTransferExecute();
  const undo = useUndoTransfer();
  const batch = useBatchId();

  const wanted = new Set(pointIds);
  const points: Point[] = [...(active.data ?? []), ...(deferred.data ?? [])].filter((p) => wanted.has(p.id));

  const previewInput: PreviewIn | null =
    wb && tabMeta && pointIds.length
      ? {
          workbook_id: wb.id,
          sheet_id: tabMeta.sheet_id,
          mode,
          point_ids: pointIds,
          anchor: mode === "fill" ? anchor : null,
          conflict,
          write_keys: writeKeys,
        }
      : null;
  const preview = useTransferPreview(mode === "fill" && !anchor ? null : previewInput);

  const values = tab.data?.values ?? [];
  const dropdowns = useMemo(() => numericDropdowns(tab.data?.dropdowns), [tab.data?.dropdowns]);

  const label = meetingLabel(meeting.title, meeting.date);
  const pointsKey = points.map((p) => `${p.id}|${p.text}|${p.owner_text}|${p.due_text}|${p.status}`).join("\u001e");
  const sheetPoints: PointForSheet[] = useMemo(
    () =>
      points.map((p) => ({
        id: p.id,
        kind: p.kind,
        text: p.text,
        owner: p.owner_text,
        due: p.due_text,
        status: p.status,
        meetingLabel: label,
      })),
    // pointsKey is the content of `points`; `points` itself is a fresh array on every render.
    [pointsKey, label],
  );

  // The client-side preview planner: identical to the server's, so the grid can react instantly.
  const { layout, plan, previewRows, marks } = useMemo(() => {
    const empty = { layout: detectLayout([]), plan: null, previewRows: [] as string[][], marks: new Map<string, { kind: CellMark; value?: string }>() };
    if (!values.length || !sheetPoints.length) return { ...empty, layout: detectLayout(values), previewRows: values };
    const detected = detectLayout(values);
    const cellMarks = new Map<string, { kind: CellMark; value?: string }>();
    if (mode === "append") {
      const built = planAppend(values, dropdowns, sheetPoints);
      for (const w of built.writes) cellMarks.set(`${w.r},${w.c}`, { kind: w.kind === "key" ? "key" : "new" });
      for (let r = built.insertAt; r < values.length; r++) {
        values[r].forEach((cell, c) => cell.trim() && cellMarks.set(`${r + built.count},${c}`, { kind: "moved" }));
      }
      return { layout: detected, plan: built, previewRows: applyPlan(values, built), marks: cellMarks };
    }
    if (!anchor) return { layout: detected, plan: null, previewRows: values, marks: cellMarks };
    const built = planFill(values, dropdowns, sheetPoints, anchor, writeKeys, conflict);
    for (const w of built.writes) {
      const skipped = w.kind === "conflict" && w.existing !== undefined && w.value === w.existing;
      cellMarks.set(`${w.r},${w.c}`, { kind: w.kind === "conflict" ? "conflict" : w.kind === "key" ? "key" : "new", value: skipped ? w.existing : w.value });
    }
    if (conflict === "insert") {
      for (let r = anchor.r; r < values.length; r++) {
        values[r].forEach((cell, c) => cell.trim() && cellMarks.set(`${r + built.count},${c}`, { kind: "moved" }));
      }
    }
    return { layout: detected, plan: built, previewRows: applyPlan(values, built), marks: cellMarks };
  }, [values, dropdowns, mode, anchor, writeKeys, conflict, sheetPoints]);

  useEffect(() => {
    setAnchor(null);
  }, [wbId, sheetId, mode]);

  const write = async (allowRepeat = false) => {
    if (!wb || !tabMeta || !preview.data) return;
    setStaleNotice("");
    if (allowRepeat) setRepeat("");
    try {
      const result = await execute.mutateAsync({
        ...(previewInput as PreviewIn),
        region_hash: preview.data.region_hash,
        allow_repeat: allowRepeat,
        // Review 1, finding 9: one id per press, sent again on a retry, so a write whose answer
        // never arrived replays rather than landing twice.
        batch_id: batch.take(),
      });
      batch.reset();
      toast(`Wrote ${result.cells.length} cells to ${tab.data?.title ?? tabMeta.title}`, {
        description: "Undo is available for 10 minutes.",
        duration: 10_000,
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await undo.mutateAsync(result.batch_id);
              toast.success("Transfer undone, the points are back");
            } catch (error) {
              toast.error(error instanceof Error ? error.message : "Undo failed");
            }
          },
        },
      });
      onDone(wb.id, tabMeta.sheet_id);
    } catch (error) {
      batch.settle(error);
      if (error instanceof ApiError && error.isConflict) {
        if (Array.isArray(error.payload.point_ids)) {
          // A second transfer of the same point needs an explicit choice, never a silent repeat.
          setRepeat(error.message);
          return;
        }
        // Someone edited the tab between the preview and the write: re-read and re-plan.
        setStaleNotice(error.message);
        await tab.refetch();
        await preview.refetch();
        toast.message(error.message);
        return;
      }
      toast.error(error instanceof Error ? error.message : "The write failed");
    }
  };

  if (workbooks.isLoading) return <div className="p-6 text-sm text-muted-foreground">Loading workbooks…</div>;
  if (!wb || !tabMeta) return <div className="p-6 text-sm text-muted-foreground">Connect a workbook on the Sheets page first.</div>;
  if (!pointIds.length) return <div className="p-6 text-sm text-muted-foreground">Select points on the previous step.</div>;

  const anchorHeader = anchor && layout.headerRow >= 0 ? values[layout.headerRow]?.[anchor.c] || "" : "";
  const serverCells = preview.data?.plan.cells ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="h-8 max-w-full rounded border bg-background px-2 text-[13px]"
          value={wb.id}
          onChange={(e) => { setWbId(e.target.value); setSheetId(books.find((x) => x.id === e.target.value)?.tabs[0]?.sheet_id ?? ""); }}
          aria-label="Workbook"
        >
          {books.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <select className="h-8 rounded border bg-background px-2 text-[13px]" value={tabMeta.sheet_id} onChange={(e) => setSheetId(e.target.value)} aria-label="Sheet">
          {wb.tabs.map((t) => <option key={t.sheet_id} value={t.sheet_id}>{t.title}</option>)}
        </select>
        <span className="text-xs text-muted-foreground">read {fmtClock(tab.data?.read_at)}</span>
        <button className="text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => { void tab.refetch(); void preview.refetch(); }}>Refresh</button>
        <div className="ml-auto flex border text-xs">
          <button className={cn("h-7 px-3", mode === "append" ? "bg-primary text-primary-foreground" : "text-muted-foreground")} onClick={() => setMode("append")}>Smart append</button>
          <button className={cn("h-7 px-3", mode === "fill" ? "bg-primary text-primary-foreground" : "text-muted-foreground")} onClick={() => setMode("fill")}>Custom fill</button>
        </div>
      </div>

      {staleNotice && <div className="border px-2 py-1.5 text-xs font-medium">{staleNotice}</div>}
      {repeat && (
        <div className="flex flex-wrap items-center gap-2 border px-2 py-1.5 text-xs">
          <span className="font-medium">{repeat}</span>
          <Button size="sm" variant="outline" className="ml-auto h-7 text-xs" onClick={() => setRepeat("")}>Cancel</Button>
          <Button size="sm" className="h-7 text-xs" data-testid="send-again" onClick={() => void write(true)}>Send again</Button>
        </div>
      )}
      {(preview.data?.warnings ?? []).map((w) => (
        <div key={w} className="text-xs font-medium">{w}</div>
      ))}
      {preview.isError && <div className="border px-2 py-1.5 text-xs font-medium">{preview.error.message}</div>}

      <div className="flex min-h-0 flex-1 flex-col gap-4 md:flex-row">
        <div className="min-w-0 flex-1">
          <Grid
            rows={previewRows}
            layout={detectLayout(previewRows)}
            marks={marks}
            anchor={anchor}
            onCellClick={mode === "fill" ? (r, c) => setAnchor({ r, c }) : undefined}
            maxHeight="min(55vh, calc(100vh - 300px))"
          />
          {/* Review 1, finding 29: no swatches. Each label wears the variant it names, so the
              legend is the rule the grid follows rather than a second copy of it. */}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="transfer-legend">
            <Legend kind="new" text={mode === "append" ? "inserted rows" : "cells to write"} />
            <Legend kind="key" text="key column" />
            <Legend kind="moved" text="moves down" />
            {mode === "fill" && <Legend kind="conflict" text="non-empty cell in the way" />}
          </div>
        </div>

        <aside className="flex w-full shrink-0 flex-col gap-2.5 text-[13px] md:w-[300px] md:border-l md:pl-4">
          {mode === "append" && plan && plan.mode === "append" ? (
            <>
              <Row k={`Header row ${layout.headerRow + 1}`} v="most known header words" />
              <Row k={`Last table row ${layout.lastTableRow + 1}`} v="last key or task value, any status" />
              <Row k={`Insert ${plan.count} after row ${layout.lastTableRow + 1}`} v={plan.moved.length ? `${plan.moved.slice(0, 3).join(", ")}${plan.moved.length > 3 ? "…" : ""} move down` : "nothing moves"} />
              {layout.keyCol >= 0 && <Row k={`Keys ${plan.keys[0]}${plan.keys.length > 1 ? ` to ${plan.keys[plan.keys.length - 1]}` : ""}`} v="allocated at write time, after the re-read" />}
              <Row k="Columns" v={Object.entries(layout.columns).map(([f, c]) => `${colLetter(c as number)} ${f}`).join(", ") || "no header, default order from A"} />
            </>
          ) : mode === "fill" && !anchor ? (
            <p className="text-muted-foreground">Click a cell. Fields fill rightward from it following the headers above; each point takes the next row.</p>
          ) : plan && plan.mode === "fill" ? (
            <>
              <Row k={`From ${a1(anchor!.r, anchor!.c)}`} v={anchorHeader ? `under "${anchorHeader}"` : "no known header, default order"} />
              <div className="mono text-xs leading-relaxed text-muted-foreground">{plan.fieldOrder.map((f) => `${colLetter(f.c)} ${f.field}`).join(" · ")}</div>
              <Row k={`${plan.count} point${plan.count === 1 ? "" : "s"}`} v={`rows ${anchor!.r + 1}-${anchor!.r + plan.count}`} />
              {layout.keyCol >= 0 && layout.keyCol < anchor!.c && (
                <label className="flex items-center gap-2"><Checkbox checked={writeKeys} onCheckedChange={(v) => setWriteKeys(!!v)} /> Write keys in column {colLetter(layout.keyCol)}</label>
              )}
              {plan.conflicts.length > 0 && (
                <div className="border-t pt-2">
                  <div className="mb-1.5 font-medium">{plan.conflicts.length} non-empty cell{plan.conflicts.length === 1 ? "" : "s"}: {plan.conflicts.slice(0, 4).join(", ")}</div>
                  {(["skip", "overwrite", "insert"] as Conflict[]).map((c) => (
                    <label key={c} className="flex items-center gap-2 py-0.5">
                      <input type="radio" name="conflict" checked={conflict === c} onChange={() => setConflict(c)} />
                      {c === "skip" ? "Skip them, keep values" : c === "overwrite" ? "Overwrite" : `Insert rows at ${anchor!.r + 1} instead`}
                    </label>
                  ))}
                </div>
              )}
            </>
          ) : null}
          <div className="mt-auto flex flex-col gap-2 border-t pt-3">
            <div className="text-xs text-muted-foreground">
              {points.length} point{points.length === 1 ? "" : "s"} · {points.map((p) => STATUS_LABEL[p.status]).filter((v, i, a) => a.indexOf(v) === i).join(", ")}
            </div>
            <Button className="h-9" disabled={!plan || !preview.data || execute.isPending} onClick={() => void write()}>
              {execute.isPending
                ? "Writing…"
                : plan
                  ? plan.mode === "append"
                    ? `Insert ${plan.count} rows and write`
                    : `Write ${(serverCells.length || planCells(plan).length)} cells`
                  : "Pick a cell"}
            </Button>
            <Button variant="outline" className="h-9" onClick={onBack}>Back</Button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div><span>{k}</span> <span className="text-muted-foreground">· {v}</span></div>;
}
function Legend({ kind, text }: { kind: CellMark; text: string }) {
  return <span className={cn("px-1", MARK_CLASS[kind])} data-legend={kind}>{text}</span>;
}
