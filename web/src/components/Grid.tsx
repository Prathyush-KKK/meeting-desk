import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button } from "@/components/ui/button";
import { a1, colLetter, type Layout } from "@/lib/sheet";
import { cn } from "@/lib/utils";
import { useCloseOnBack, useNarrow } from "@/lib/overlay";

export type CellMark = "new" | "key" | "conflict" | "moved" | "edited";

/**
 * Spec section 3: "TanStack Virtual (grids over 300 rows)". Under that the table renders every row
 * - it is cheaper than the measuring, and the sticky header, the column letters and the cell
 * editor all behave without a second code path to keep in step. Over it, only the rows in view are
 * in the DOM and two spacer rows hold the scrollbar at the right length, so the markup, the sticky
 * column and the editor stay exactly as they are.
 */
export const VIRTUALIZE_OVER = 300;
/** h-7: 1.75rem. The rows are a fixed height, so no measurement pass is needed. */
const ROW_HEIGHT = 28;
/** jsdom reports a zero-sized scroll box; without a starting rect nothing would ever render. */
const INITIAL_RECT = { width: 1200, height: 640 };

/**
 * The five marks, in the one selection hue (Review 1, finding 29). Three variants carry all of
 * them: a tint for what is being written, an outline for what needs a decision, a strike for what
 * only moves. The Transfer legend wears the same three on its own labels, so the legend is the
 * rule rather than a copy of it.
 */
export const MARK_CLASS: Record<CellMark, string> = {
  new: "sel-tint",
  edited: "sel-tint font-medium",
  key: "sel-soft italic",
  conflict: "sel-outline sel-soft",
  moved: "sel-strike",
};

interface Props {
  rows: string[][];
  layout: Layout;
  marks?: Map<string, { kind: CellMark; value?: string }>;
  anchor?: { r: number; c: number } | null;
  onCellClick?: (r: number, c: number) => void;
  editable?: { cols: Set<number>; dropdowns: Record<number, string[]>; onChange: (r: number, c: number, value: string) => void; fromRow: number };
  maxHeight?: string;
  dim?: boolean;
  rowIndexes?: number[];
  /** Clicking a row number picks the row an Add row insert lands above. */
  onRowClick?: (r: number) => void;
  activeRow?: number | null;
}

export function Grid({ rows, layout, marks, anchor, onCellClick, editable, maxHeight = "100%", dim, rowIndexes, onRowClick, activeRow }: Props) {
  const width = Math.max(8, ...rows.map((r) => r.length));
  const [editing, setEditing] = useState<{ r: number; c: number; value: string } | null>(null);
  const [draft, setDraft] = useState("");
  const colWidth = (c: number) => {
    if (c === layout.columns.task || c === layout.columns.decision || c === layout.columns.risk) return 320;
    if (c === layout.columns.notes) return 200;
    if (c === layout.keyCol) return 76;
    if (c === layout.columns.owner) return 170;
    return 108;
  };
  const display = Math.max(rows.length, 22);
  const order = rowIndexes ?? Array.from({ length: display }, (_, i) => i);

  // Spec section 7, "Sheets page": "Editing on a phone · tap opens a bottom editor with the column
  // name, not an inline input." Under 768 px the inline input is not rendered at all, so it cannot
  // take the focus or raise the keyboard behind the sheet.
  const narrow = useNarrow();
  const closeEditor = () => setEditing(null);
  useCloseOnBack(narrow && !!editing, closeEditor);

  const openEditor = (r: number, c: number, value: string) => {
    setEditing({ r, c, value });
    setDraft(value);
  };
  const commit = (value: string) => {
    if (editing && value !== editing.value) editable?.onChange(editing.r, editing.c, value);
    setEditing(null);
  };

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualised = order.length > VIRTUALIZE_OVER;
  const virtualizer = useVirtualizer({
    count: order.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 16,
    initialRect: INITIAL_RECT,
  });
  const window_ = virtualised ? virtualizer.getVirtualItems() : null;
  const visible = window_ ? window_.map((item) => order[item.index]) : order;
  const padTop = window_ && window_.length ? window_[0].start : 0;
  const padBottom =
    window_ && window_.length ? Math.max(0, virtualizer.getTotalSize() - window_[window_.length - 1].end) : 0;
  const spacer = (key: string, height: number) => (
    <tr key={key} aria-hidden="true" data-spacer={key}>
      <td colSpan={width + 1} style={{ height, padding: 0, border: 0 }} />
    </tr>
  );

  const columnName = (c: number) => {
    const header = layout.headerRow >= 0 ? (rows[layout.headerRow]?.[c] ?? "").trim() : "";
    return header || `Column ${colLetter(c)}`;
  };

  return (
    <>
      <div
        ref={scrollRef}
        className="overflow-auto rounded-md border bg-card"
        style={{ maxHeight }}
        data-virtualised={virtualised ? "true" : "false"}
        data-rows={order.length}
      >
        <table className="border-separate border-spacing-0 text-[12.5px]" style={{ minWidth: "100%" }}>
          <thead className="sticky top-0 z-20">
            <tr>
              <th className="sticky left-0 z-30 h-7 w-10 border-b border-r bg-grid-header text-center font-medium text-muted-foreground"></th>
              {Array.from({ length: width }, (_, c) => (
                <th key={c} className="h-7 border-b border-r bg-grid-header text-center font-medium text-muted-foreground" style={{ minWidth: colWidth(c) }}>
                  {colLetter(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {padTop > 0 && spacer("top", padTop)}
            {visible.map((r) => {
              const row = rows[r] || [];
              const isHeader = r === layout.headerRow;
              return (
                <tr key={r} className={cn(isHeader && "font-semibold")}>
                  <th
                    data-row={r}
                    onClick={onRowClick ? () => onRowClick(r) : undefined}
                    aria-label={onRowClick ? `Row ${r + 1}` : undefined}
                    className={cn(
                      "sticky left-0 z-10 h-7 border-b border-r bg-grid-header text-center font-medium text-muted-foreground mono",
                      onRowClick && "cursor-pointer hover:text-foreground",
                      activeRow === r && "sel-tint text-foreground",
                    )}
                  >
                    {r + 1}
                  </th>
                  {Array.from({ length: width }, (_, c) => {
                    const key = `${r},${c}`;
                    const mark = marks?.get(key);
                    const value = mark?.value !== undefined ? mark.value : row[c] || "";
                    const isAnchor = anchor && anchor.r === r && anchor.c === c;
                    const canEdit = !!editable && r >= editable.fromRow && editable.cols.has(c) && !isHeader;
                    const isEditing = editing && editing.r === r && editing.c === c;
                    const dd = editable?.dropdowns[c];
                    return (
                      <td
                        key={c}
                        data-cell={`${r},${c}`}
                        onClick={() => {
                          onCellClick?.(r, c);
                          if (canEdit) openEditor(r, c, value);
                        }}
                        title={value}
                        className={cn(
                          "h-7 max-w-[320px] truncate border-b border-r px-1.5 align-middle",
                          isHeader && "bg-grid-header",
                          mark && MARK_CLASS[mark.kind],
                          isAnchor && "outline outline-2 -outline-offset-2 outline-sel",
                          (onCellClick || canEdit) && "cursor-pointer hover:bg-accent/60",
                          dim && !mark && !isHeader && "text-muted-foreground",
                        )}
                      >
                        {isEditing && canEdit && !narrow ? (
                          dd ? (
                            <select
                              autoFocus
                              className="h-6 w-full rounded border bg-background px-1 text-[12px]"
                              defaultValue={value}
                              onBlur={() => setEditing(null)}
                              onChange={(e) => commit(e.target.value)}
                            >
                              <option value=""></option>
                              {dd.map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              autoFocus
                              className="h-6 w-full rounded border bg-background px-1 text-[12px]"
                              defaultValue={value}
                              onBlur={(e) => commit(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                if (e.key === "Escape") setEditing(null);
                              }}
                            />
                          )
                        ) : (
                          value
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {padBottom > 0 && spacer("bottom", padBottom)}
          </tbody>
        </table>
      </div>

      {narrow && editing && editable && (
        <div
          data-testid="cell-editor"
          role="dialog"
          aria-label={`Edit ${columnName(editing.c)}`}
          className="fixed inset-x-0 bottom-0 z-50 border-t bg-background p-3 md:hidden"
          style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom, 0px))" }}
        >
          <div className="mb-2 flex items-baseline gap-2">
            <span className="text-[13px] font-medium" data-testid="cell-editor-column">{columnName(editing.c)}</span>
            <span className="mono text-xs text-muted-foreground">{a1(editing.r, editing.c)}</span>
            <span className="ml-auto min-w-0 truncate text-xs text-muted-foreground" data-testid="cell-editor-current">
              now: {editing.value || "(blank)"}
            </span>
          </div>
          {editable.dropdowns[editing.c] ? (
            <select
              autoFocus
              aria-label={columnName(editing.c)}
              className="h-11 w-full rounded border bg-background px-2 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            >
              <option value=""></option>
              {editable.dropdowns[editing.c].map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          ) : (
            <input
              autoFocus
              aria-label={columnName(editing.c)}
              className="h-11 w-full rounded border bg-background px-2 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit(draft);
                if (e.key === "Escape") setEditing(null);
              }}
            />
          )}
          <div className="mt-2 flex gap-2">
            <Button variant="outline" className="h-11 flex-1" onClick={closeEditor}>Cancel</Button>
            <Button className="h-11 flex-1" data-testid="cell-editor-save" onClick={() => commit(draft)}>Save</Button>
          </div>
        </div>
      )}
    </>
  );
}
