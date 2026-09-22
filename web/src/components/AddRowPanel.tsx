import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { colLetter } from "@/lib/sheet";
import { cn } from "@/lib/utils";
import { useBatchId } from "@/lib/batch";
import { ApiError } from "@/api/client";
import { useAddRow, useMeetings, usePoints } from "@/api/hooks";
import type { TabState } from "@/api/types";

interface Props {
  tab: TabState;
  /** The grid row the insert lands above; null means "after the table". */
  aboveRow: number | null;
  onPickRow: (row: number | null) => void;
  onDone: () => void;
}

interface FieldSpec {
  col: number;
  label: string;
  kind: "text" | "select" | "date" | "generated" | "formula";
  options: string[];
}

/** Full-height controls on a phone, the compact ones from 768 px up. */
const CONTROL = "h-11 rounded border bg-background px-2 text-sm md:h-9";

/**
 * Add row: one field per mapped header, or a point picked from the active and deferred lists.
 * The key column is generated server-side after the re-read; formula columns are copied down.
 *
 * The insert lands after the table unless a row number is clicked in the grid (Review 1, finding 8:
 * "Above a row" used to default to `header_row + 1`, so the first press put a row directly under
 * the header and took the header's formatting). There is no default row: the radio turns on when
 * one is picked, and the API refuses an insert in or above the header, whose message is shown here.
 */
export function AddRowPanel({ tab, aboveRow, onPickRow, onDone }: Props) {
  const addRow = useAddRow();
  const meetings = useMeetings();
  const [mode, setMode] = useState<"form" | "point">("form");
  const [pointId, setPointId] = useState("");
  const [fields, setFields] = useState<Record<number, string>>({});
  const [refused, setRefused] = useState("");
  const batch = useBatchId();

  const active = usePoints(null, "active", mode === "point");
  const deferred = usePoints(null, "deferred", mode === "point");

  const specs = useMemo<FieldSpec[]>(() => {
    const layout = tab.layout;
    const header = layout.header_row >= 0 ? tab.values[layout.header_row] ?? [] : [];
    const formula = new Set(layout.formula_cols);
    const dates = new Set(layout.date_cols);
    const out: FieldSpec[] = [];
    for (let c = layout.first_col; c <= layout.last_col; c++) {
      const label = (header[c] || "").trim() || `Column ${colLetter(c)}`;
      if (layout.header_row >= 0 && !(header[c] || "").trim()) continue;
      if (c === layout.key_col) {
        out.push({ col: c, label, kind: "generated", options: [] });
        continue;
      }
      if (formula.has(c)) {
        out.push({ col: c, label, kind: "formula", options: [] });
        continue;
      }
      const options = tab.dropdowns[String(c)] ?? [];
      out.push({ col: c, label, kind: options.length ? "select" : dates.has(c) ? "date" : "text", options });
    }
    return out;
  }, [tab]);

  const titles = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of meetings.data?.items ?? []) if (m.id) map.set(m.id, m.title);
    return map;
  }, [meetings.data]);

  const pickable = [
    ...(active.data ?? []).map((p) => ({ p, tag: "" })),
    ...(deferred.data ?? []).map((p) => ({ p, tag: " · deferred" })),
  ];

  const submit = async () => {
    const values: Record<string, string> = {};
    if (mode === "form") {
      for (const [col, value] of Object.entries(fields)) if (value.trim()) values[col] = value;
      if (!Object.keys(values).length) {
        toast.message("Fill at least one field.");
        return;
      }
    }
    setRefused("");
    try {
      const result = await addRow.mutateAsync({
        workbook_id: tab.workbook_id,
        sheet_id: tab.sheet_id,
        region_hash: tab.region_hash,
        point_id: mode === "point" ? pointId || null : null,
        values,
        position: aboveRow === null ? { mode: "after_table" } : { mode: "above", row: aboveRow },
        batch_id: batch.take(),
      });
      batch.reset();
      toast.success(
        `Row ${result.insert_at + 1} added${result.keys[0] ? ` as ${result.keys[0]}` : ""}` +
          (result.transfer ? " · the point was transferred" : ""),
      );
      setFields({});
      setPointId("");
      onDone();
    } catch (error) {
      batch.settle(error);
      const message = error instanceof Error ? error.message : "Could not add the row";
      // The header-row and below-the-table refusals are 409s. They are about the row that was
      // clicked, so the message belongs beside the radio rather than only in a toast that goes.
      if (error instanceof ApiError && error.isConflict) {
        setRefused(message);
        toast.message(message);
        return;
      }
      setRefused(message);
      toast.error(message);
    }
  };

  const disabled = addRow.isPending || (mode === "point" && !pointId);

  return (
    <div className="border p-3 text-[13px]" data-testid="add-row-panel">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <span className="font-medium">Add row</span>
        <div className="flex border text-xs">
          <button className={cn("h-7 px-3", mode === "form" ? "bg-primary text-primary-foreground" : "text-muted-foreground")} onClick={() => setMode("form")}>Fields</button>
          <button className={cn("h-7 px-3", mode === "point" ? "bg-primary text-primary-foreground" : "text-muted-foreground")} onClick={() => setMode("point")}>From a point</button>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <label className="flex min-h-[44px] items-center gap-1.5 md:min-h-0">
            <input type="radio" name="addrow-position" checked={aboveRow === null} onChange={() => onPickRow(null)} />
            After the table
          </label>
          <label className={cn("flex min-h-[44px] items-center gap-1.5 md:min-h-0", aboveRow === null && "text-muted-foreground")}>
            <input
              type="radio"
              name="addrow-position"
              data-testid="addrow-above"
              checked={aboveRow !== null}
              disabled={aboveRow === null}
              readOnly
            />
            {aboveRow === null ? "Above a row - click a row number in the grid" : `Above row ${aboveRow + 1}`}
          </label>
          {aboveRow !== null && (
            <button className="text-muted-foreground underline-offset-2 hover:underline" onClick={() => { onPickRow(null); setRefused(""); }}>
              clear
            </button>
          )}
        </div>
      </div>

      {refused && <div className="mb-2 border px-2 py-1.5 text-xs font-medium" data-testid="add-row-refused">{refused}</div>}

      {mode === "form" ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {specs.map((s) => (
            <div key={s.col} className="flex flex-col gap-1">
              <Label htmlFor={`addrow-${s.col}`} className="text-xs text-muted-foreground">
                {s.label} <span className="mono">{colLetter(s.col)}</span>
              </Label>
              {s.kind === "generated" ? (
                <div id={`addrow-${s.col}`} className={cn(CONTROL, "flex items-center border-dashed text-xs text-muted-foreground")}>generated on write</div>
              ) : s.kind === "formula" ? (
                <div id={`addrow-${s.col}`} className={cn(CONTROL, "flex items-center border-dashed text-xs text-muted-foreground")}>formula, copied down</div>
              ) : s.kind === "select" ? (
                <select
                  id={`addrow-${s.col}`}
                  className={CONTROL}
                  value={fields[s.col] ?? ""}
                  onChange={(e) => setFields((f) => ({ ...f, [s.col]: e.target.value }))}
                >
                  <option value=""></option>
                  {s.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <Input
                  id={`addrow-${s.col}`}
                  type={s.kind === "date" ? "date" : "text"}
                  className="h-11 md:h-9"
                  value={fields[s.col] ?? ""}
                  onChange={(e) => setFields((f) => ({ ...f, [s.col]: e.target.value }))}
                />
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <select
            className={cn(CONTROL, "w-full")}
            value={pointId}
            onChange={(e) => setPointId(e.target.value)}
            aria-label="Point"
          >
            <option value="">Pick a point…</option>
            {pickable.map(({ p, tag }) => (
              <option key={p.id} value={p.id}>
                {(titles.get(p.meeting_id) ?? "meeting")} · {p.text || "untitled"}{tag}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">A point used here is transferred: it is logged and leaves the tool.</p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground" data-testid="add-row-lands">
          {aboveRow === null ? `Lands after row ${tab.layout.last_table_row + 1}` : `Lands at row ${aboveRow + 1}, pushing the rest down`}
        </span>
        <Button size="sm" variant="outline" className="ml-auto h-11 md:h-8" onClick={onDone}>Cancel</Button>
        <Button size="sm" className="h-11 md:h-8" data-testid="add-row-submit" disabled={disabled} onClick={() => void submit()}>Add row</Button>
      </div>
    </div>
  );
}
