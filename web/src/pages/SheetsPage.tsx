import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Grid, type CellMark } from "@/components/Grid";
import { AddRowPanel } from "@/components/AddRowPanel";
import { a1, detectLayout } from "@/lib/sheet";
import { cn } from "@/lib/utils";
import { useBatchId } from "@/lib/batch";
import { fmtClock, shortName } from "@/lib/display";
import { ApiError } from "@/api/client";
import {
  useConnectWorkbook,
  useDisconnectWorkbook,
  useSaveSheet,
  useTab,
  useTransfers,
  useWorkbooks,
} from "@/api/hooks";
import type { Me, SaveClash } from "@/api/types";

interface Props {
  selection: { wb: string; tab: string } | null;
  onSelect: (sel: { wb: string; tab: string }) => void;
  me: Me;
}

type Filter = "all" | "open" | "overdue" | "mine" | "noowner";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "overdue", label: "Overdue" },
  { key: "mine", label: "Mine" },
  { key: "noowner", label: "No owner" },
];

/**
 * One staged cell edit. `before` is what the cell held **when the person changed it**, not what the
 * 60 s poll last brought in - Review 1, finding 4. The API compares `before` against a fresh read
 * of that cell and refuses the save when they differ, which is the whole pre-save guard; recomputing
 * it from the latest poll would quietly adopt someone else's value as the baseline and the guard
 * would never fire. A second edit of the same cell keeps the first `before`: the baseline is the
 * value the person started from.
 */
interface PendingEdit {
  before: string;
  after: string;
}

export function SheetsPage({ selection, onSelect, me }: Props) {
  const workbooks = useWorkbooks();
  const books = workbooks.data ?? [];
  const wb = books.find((w) => w.id === selection?.wb) ?? books[0];
  const tabMeta = wb?.tabs.find((t) => t.sheet_id === selection?.tab) ?? wb?.tabs[0];
  const tab = useTab(wb?.id ?? null, tabMeta?.sheet_id ?? null);
  const transfers = useTransfers(wb?.id);
  const connect = useConnectWorkbook();
  const disconnect = useDisconnectWorkbook();
  const save = useSaveSheet();

  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [pending, setPending] = useState<Map<string, PendingEdit>>(new Map());
  const [clashes, setClashes] = useState<SaveClash[]>([]);
  const [newUrl, setNewUrl] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [aboveRow, setAboveRow] = useState<number | null>(null);
  const saveBatch = useBatchId();

  const values = useMemo(() => tab.data?.values ?? [], [tab.data]);
  const layout = useMemo(() => detectLayout(values), [values]);
  const server = tab.data?.layout;
  const me_handle = shortName(me.email).split(".")[0];

  useEffect(() => {
    setPending(new Map());
    setClashes([]);
    setAboveRow(null);
    setFilter("all");
  }, [wb?.id, tabMeta?.sheet_id]);

  const rowIndexes = useMemo(() => {
    if (!values.length) return [];
    const all = Array.from({ length: Math.max(values.length, 22) }, (_, i) => i);
    if (filter === "all" && !q.trim()) return all;
    const sc = layout.columns.status ?? -1;
    const oc = layout.columns.owner ?? -1;
    const dc = layout.columns.due ?? -1;
    return all.filter((r) => {
      if (r === layout.headerRow) return true;
      if (r <= layout.headerRow || r > layout.lastTableRow) return false;
      const row = values[r] || [];
      const status = (sc >= 0 ? row[sc] : "").toLowerCase();
      const owner = (oc >= 0 ? row[oc] : "").toLowerCase();
      const due = dc >= 0 ? row[dc] : "";
      if (q.trim() && !row.join(" ").toLowerCase().includes(q.trim().toLowerCase())) return false;
      if (filter === "open") return !["done", "dropped", "closed", "removed", "decided"].includes(status);
      if (filter === "overdue") return !!due && !["done", "dropped"].includes(status) && isPast(due, tab.data?.read_at);
      if (filter === "mine") return owner.includes(me_handle);
      if (filter === "noowner") return !owner.trim();
      return true;
    });
  }, [values, filter, q, layout, me_handle, tab.data?.read_at]);

  const marks = useMemo(() => {
    const m = new Map<string, { kind: CellMark; value?: string }>();
    pending.forEach((edit, key) => m.set(key, { kind: "edited", value: edit.after }));
    return m;
  }, [pending]);

  const editableCols = useMemo(() => {
    const cols = new Set<number>();
    const formula = new Set(server?.formula_cols ?? []);
    for (let c = layout.firstCol; c <= layout.lastCol; c++) {
      if (c === layout.keyCol || formula.has(c)) continue;
      cols.add(c);
    }
    return cols;
  }, [layout, server]);

  /**
   * A cell was changed in the grid. The baseline is read here, from the render the person clicked
   * in, and kept for as long as the edit is unsaved - a poll landing before Save must not move it.
   */
  const stageEdit = (r: number, c: number, after: string) => {
    const seen = values[r]?.[c] ?? "";
    setPending((p) => {
      const next = new Map(p);
      const already = next.get(`${r},${c}`);
      next.set(`${r},${c}`, { before: already ? already.before : seen, after });
      return next;
    });
  };

  const runSave = async () => {
    if (!wb || !tabMeta || !pending.size) return;
    const edits = [...pending.entries()].map(([key, edit]) => {
      const [r, c] = key.split(",").map(Number);
      return { cell: a1(r, c), before: edit.before, after: edit.after };
    });
    setClashes([]);
    try {
      const result = await save.mutateAsync({
        workbook_id: wb.id,
        sheet_id: tabMeta.sheet_id,
        edits,
        batch_id: saveBatch.take(),
      });
      saveBatch.reset();
      setPending(new Map());
      toast.success(`Wrote ${result.edits.length} cell${result.edits.length === 1 ? "" : "s"}`);
    } catch (error) {
      // A 4xx means nothing was written and the next press carries a different body; anything else
      // leaves it unknown, so the id is held and a second press replays instead of writing twice.
      saveBatch.settle(error);
      if (error instanceof ApiError && error.isConflict) {
        const found = error.payload.clashes;
        if (Array.isArray(found)) setClashes(found as SaveClash[]);
        toast.message(error.message);
        void tab.refetch();
        return;
      }
      toast.error(error instanceof Error ? error.message : "Save failed");
    }
  };

  const resolveClash = (clash: SaveClash, take: "mine" | "theirs") => {
    const [row, col] = parse(clash.cell);
    const key = `${row},${col}`;
    setPending((p) => {
      const next = new Map(p);
      // Keeping mine re-sends against what the sheet holds now, which is their value: that is the
      // baseline the person just looked at and chose to overwrite.
      if (take === "theirs") next.delete(key);
      else next.set(key, { before: clash.theirs, after: clash.yours });
      return next;
    });
    setClashes((list) => list.filter((c) => c.cell !== clash.cell));
  };

  const doConnect = async () => {
    try {
      const result = await connect.mutateAsync(newUrl.trim());
      setNewUrl("");
      toast.success(`Connected ${result.name}`);
      if (result.share_request) toast.message(result.share_request, { duration: 12_000 });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not connect that workbook");
    }
  };

  const tableRows = Math.max(0, layout.lastTableRow - layout.headerRow);
  const transfersHere = (transfers.data ?? []).filter((t) => t.sheet_id === tabMeta?.sheet_id).slice(0, 5);
  const pick = (v: string) => {
    const [w, t] = v.split("|");
    onSelect({ wb: w, tab: t });
  };

  return (
    // Review 1, finding 6. Under 768 px there is no `h-full`: `main` scrolls, the grid keeps a
    // fixed slice of the viewport and everything below it - Add row, the clash list, Save - is
    // reached by scrolling the page. From 768 px up the page does not scroll and the grid takes
    // whatever is left, which is why every slot below is `shrink-0` and the grid's is `min-h-0`.
    <div className="flex min-h-0 flex-col gap-4 md:h-full md:flex-row md:gap-8">
      <aside className="flex w-full shrink-0 flex-col gap-3 md:w-[260px]">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold">Sheets</h2>
          <span className="text-xs text-muted-foreground">{books.length} workbooks</span>
        </div>
        <select
          className="h-9 w-full rounded border bg-background px-2 text-[13px] md:hidden"
          value={wb && tabMeta ? `${wb.id}|${tabMeta.sheet_id}` : ""}
          onChange={(e) => pick(e.target.value)}
          aria-label="Workbook and tab"
        >
          {books.map((w) => w.tabs.map((t) => <option key={`${w.id}|${t.sheet_id}`} value={`${w.id}|${t.sheet_id}`}>{w.name} › {t.title}</option>))}
        </select>
        <div className="hidden min-h-0 flex-1 overflow-y-auto border-y md:block" data-testid="workbook-tree">
          {books.map((w) => (
            <div key={w.id} className="border-b py-1.5 last:border-b-0">
              <div className="flex items-start gap-2 px-1 py-1">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium">{w.name}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {shortName(w.connected_by)} · {(w.connected_at ?? "").slice(0, 10)}{w.can_edit ? "" : " · read-only"}
                  </div>
                </div>
                <button
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Disconnect"
                  onClick={async () => { await disconnect.mutateAsync(w.id); toast.message(`Disconnected ${w.name}`); }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <ul>
                {w.tabs.map((t) => (
                  <li key={t.sheet_id}>
                    <button
                      className={cn("w-full py-1 pl-4 pr-2 text-left text-[13px] hover:bg-secondary", t.sheet_id === tabMeta?.sheet_id && w.id === wb?.id && "bg-secondary font-medium")}
                      onClick={() => pick(`${w.id}|${t.sheet_id}`)}
                    >
                      {t.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Input id="wburl" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="Google Sheets URL" className="h-8 text-xs" />
          <Button size="sm" variant="outline" className="h-8" onClick={() => void doConnect()} disabled={!newUrl.trim() || connect.isPending}>Connect</Button>
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        {!wb || !tabMeta ? (
          <div className="border-y py-8 text-center text-xs text-muted-foreground">Connect a workbook to start.</div>
        ) : (
          <>
            <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-[15px] font-semibold">{tab.data?.title ?? tabMeta.title}</h2>
              <span className="text-xs text-muted-foreground">
                {wb.name} · header row {layout.headerRow + 1} · {tableRows} rows · read {fmtClock(tab.data?.read_at)}
              </span>
              <button className="text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => void tab.refetch()}>Refresh</button>
              <a className="text-xs text-muted-foreground underline-offset-2 hover:underline" href={wb.url} target="_blank" rel="noreferrer">Open in Google Sheets</a>
              {!wb.can_edit && <span className="text-xs font-medium">read-only: no admin connection can edit it</span>}
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={cn("h-7 border px-2.5 text-xs", filter === f.key ? "border-foreground bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
                >
                  {f.label}
                </button>
              ))}
              <Input id="sheetq" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find" className="ml-auto h-7 w-40 text-xs" />
              <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="add-row-toggle" onClick={() => setAddOpen((v) => !v)}>{addOpen ? "Close" : "Add row"}</Button>
            </div>

            {tab.isError && <div className="shrink-0 border px-2 py-1.5 text-xs font-medium">{tab.error.message}</div>}

            <div className="h-[52vh] min-h-[200px] shrink-0 overflow-hidden md:h-auto md:min-h-0 md:flex-1 md:shrink" data-testid="grid-slot">
              <Grid
                rows={values}
                layout={layout}
                marks={marks}
                rowIndexes={rowIndexes}
                maxHeight="100%"
                onRowClick={addOpen ? (r) => setAboveRow(r) : undefined}
                activeRow={addOpen ? aboveRow : null}
                editable={{
                  cols: editableCols,
                  dropdowns: numericDropdowns(tab.data?.dropdowns),
                  fromRow: layout.headerRow + 1,
                  onChange: stageEdit,
                }}
              />
            </div>

            {addOpen && tab.data && (
              <AddRowPanel
                tab={tab.data}
                aboveRow={aboveRow}
                onPickRow={setAboveRow}
                onDone={() => { setAddOpen(false); setAboveRow(null); }}
              />
            )}

            {clashes.length > 0 && (
              <div className="shrink-0 border p-2 text-xs">
                <div className="mb-1 font-medium">These cells changed in Google Sheets while you were editing. Pick one per cell.</div>
                <ul className="flex flex-col gap-1">
                  {clashes.map((c) => (
                    <li key={c.cell} className="flex flex-wrap items-center gap-2">
                      <span className="mono w-12 shrink-0">{c.cell}</span>
                      <span className="min-w-0 flex-1 truncate">yours: <span className="font-medium">{c.yours || "(blank)"}</span></span>
                      <span className="min-w-0 flex-1 truncate">theirs: <span className="font-medium">{c.theirs || "(blank)"}</span></span>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resolveClash(c, "mine")}>Keep mine</Button>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resolveClash(c, "theirs")}>Take theirs</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex shrink-0 flex-wrap items-center gap-3 text-xs" data-testid="save-bar">
              <span className="text-muted-foreground">Click a cell to change it. Dropdown columns use the sheet's values. The key column{(server?.formula_cols.length ?? 0) > 0 ? " and formula columns are" : " is"} fixed.</span>
              <span className={cn("ml-auto", pending.size ? "text-foreground" : "text-muted-foreground")}>{pending.size} unsaved</span>
              <Button size="sm" variant="outline" className="h-8" disabled={!pending.size} onClick={() => { setPending(new Map()); setClashes([]); }}>Discard</Button>
              <Button size="sm" className="h-8" disabled={!pending.size || save.isPending} onClick={() => void runSave()}>Save to Sheet</Button>
            </div>

            {transfersHere.length > 0 && (
              <div className="shrink-0 border-t pt-2 text-xs">
                <div className="mb-1 text-muted-foreground">Recent transfers into this tab</div>
                <ul className="flex flex-col gap-0.5">
                  {transfersHere.map((t) => (
                    <li key={t.id} className="flex gap-2">
                      <span className="mono text-muted-foreground">{t.cells[0] || ""}</span>
                      <span className="truncate">{t.point_text}</span>
                      <span className="ml-auto hidden shrink-0 text-muted-foreground sm:inline">{t.meeting_title} · {shortName(t.actor)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function numericDropdowns(dd: Record<string, string[]> | undefined): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  for (const [k, v] of Object.entries(dd ?? {})) out[Number(k)] = v;
  return out;
}

function parse(ref: string): [number, number] {
  const m = /^([A-Za-z]+)(\d+)$/.exec(ref.trim());
  if (!m) return [0, 0];
  let col = 0;
  for (const ch of m[1].toUpperCase()) col = col * 26 + (ch.charCodeAt(0) - 64);
  return [Number(m[2]) - 1, col - 1];
}

/** "3 Oct" against the moment the tab was read. Text dates are all these sheets carry. */
function isPast(due: string, readAt: string | undefined): boolean {
  const m = /(\d{1,2})\s+([A-Za-z]{3})/.exec(due);
  if (!m) return false;
  const months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const mi = months.indexOf(m[2].toLowerCase().slice(0, 3));
  if (mi < 0) return false;
  const now = readAt ? new Date(readAt) : new Date();
  const year = now.getFullYear();
  return new Date(year, mi, Number(m[1])).getTime() < now.getTime();
}
