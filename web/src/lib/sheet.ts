// Sheet layout detection and transfer planning.
// Rows are 0-indexed arrays of strings; the UI shows them 1-indexed like Sheets.

export type Field = "id" | "task" | "owner" | "due" | "priority" | "effort" | "status" | "notes" | "decision" | "risk" | "severity" | "question";

const SYNONYMS: Record<Field, string[]> = {
  id: ["id", "key", "ref", "#"],
  task: ["task", "item", "title", "action", "action item", "work item", "deliverable"],
  owner: ["owner", "assignee", "who", "person", "assigned to", "responsible"],
  due: ["due", "deadline", "eta", "target", "due date", "by"],
  priority: ["priority", "prio", "p"],
  effort: ["effort", "size", "estimate", "t-shirt"],
  status: ["status", "state", "progress"],
  notes: ["notes", "note", "remarks", "source", "comment", "comments", "context"],
  decision: ["decision", "decided", "rule"],
  risk: ["risk"],
  severity: ["severity", "sev", "impact"],
  question: ["question", "open question", "open"],
};

export interface Layout {
  headerRow: number; // 0-indexed, -1 when none
  firstCol: number;
  lastCol: number;
  columns: Partial<Record<Field, number>>; // field -> column index
  keyCol: number; // -1 when none
  keyPrefix: string;
  lastTableRow: number; // 0-indexed; equals headerRow when the table is empty
  headerScore: number;
}

export function colLetter(i: number): string {
  let s = "";
  let n = i;
  do {
    s = String.fromCharCode(65 + (n % 26)) + s;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return s;
}

export function a1(r: number, c: number): string {
  return `${colLetter(c)}${r + 1}`;
}

function norm(s: string): string {
  return (s || "").trim().toLowerCase().replace(/[^a-z0-9# ]+/g, " ").replace(/\s+/g, " ").trim();
}

function matchField(header: string): Field | null {
  const h = norm(header);
  if (!h) return null;
  for (const [field, words] of Object.entries(SYNONYMS) as [Field, string[]][]) {
    if (words.includes(h)) return field;
  }
  for (const [field, words] of Object.entries(SYNONYMS) as [Field, string[]][]) {
    if (words.some((w) => w.length > 2 && (h.startsWith(w + " ") || h.endsWith(" " + w)))) return field;
  }
  return null;
}

const KEY_RE = /^([A-Z]{1,4})-(\d+)$/;

export function detectLayout(rows: string[][]): Layout {
  const width = Math.max(0, ...rows.map((r) => r.length));
  let best = { row: -1, score: 0 };
  const limit = Math.min(rows.length, 40);
  for (let r = 0; r < limit; r++) {
    let score = 0;
    for (const cell of rows[r] || []) if (matchField(cell)) score++;
    if (score > best.score) best = { row: r, score };
  }
  const layout: Layout = {
    headerRow: -1,
    firstCol: 0,
    lastCol: Math.max(0, width - 1),
    columns: {},
    keyCol: -1,
    keyPrefix: "",
    lastTableRow: -1,
    headerScore: best.score,
  };
  if (best.score < 2) {
    // no header: table is everything with content
    let last = -1;
    rows.forEach((row, i) => {
      if (row.some((c) => (c || "").trim())) last = i;
    });
    layout.lastTableRow = last;
    return layout;
  }
  layout.headerRow = best.row;
  const header = rows[best.row];
  let first = -1;
  let last = -1;
  header.forEach((cell, c) => {
    if ((cell || "").trim()) {
      if (first < 0) first = c;
      last = c;
      const f = matchField(cell);
      if (f && layout.columns[f] === undefined) layout.columns[f] = c;
    }
  });
  layout.firstCol = Math.max(0, first);
  layout.lastCol = Math.max(0, last);
  // key column: header "id" or a column whose values look like T-101
  if (layout.columns.id !== undefined) layout.keyCol = layout.columns.id;
  else {
    for (let c = layout.firstCol; c <= layout.lastCol; c++) {
      const vals = rows.slice(best.row + 1).map((r) => (r[c] || "").trim()).filter(Boolean);
      if (vals.length && vals.filter((v) => KEY_RE.test(v)).length / vals.length > 0.6) {
        layout.keyCol = c;
        break;
      }
    }
  }
  if (layout.keyCol >= 0) {
    const sample = rows.slice(best.row + 1).map((r) => (r[layout.keyCol] || "").trim()).find((v) => KEY_RE.test(v));
    const m = sample ? sample.match(KEY_RE) : null;
    layout.keyPrefix = m ? m[1] : "";
  }
  // table extent: last row with a value in the key or task column (any status)
  const probeCols = [layout.keyCol, layout.columns.task ?? -1, layout.columns.decision ?? -1, layout.columns.risk ?? -1].filter((c) => c >= 0);
  let lastRow = best.row;
  for (let r = best.row + 1; r < rows.length; r++) {
    if (probeCols.some((c) => ((rows[r] || [])[c] || "").trim())) lastRow = r;
  }
  layout.lastTableRow = lastRow;
  return layout;
}

export function nextKeys(rows: string[][], layout: Layout, count: number): string[] {
  if (layout.keyCol < 0) return Array(count).fill("");
  let max = 0;
  for (const r of rows) {
    const m = ((r[layout.keyCol] || "").trim()).match(KEY_RE);
    if (m && m[1] === (layout.keyPrefix || m[1])) max = Math.max(max, parseInt(m[2], 10));
  }
  const prefix = layout.keyPrefix || "T";
  const width = 3;
  return Array.from({ length: count }, (_, i) => `${prefix}-${String(max + 1 + i).padStart(width, "0")}`);
}

export interface PointForSheet {
  id: string;
  kind: "action" | "decision" | "risk" | "question";
  text: string;
  owner: string;
  due: string;
  status: string;
  meetingLabel: string;
}

const STATUS_WORDS: Record<string, string[]> = {
  open: ["open", "to do", "todo", "not started", "new", "backlog"],
  in_progress: ["in progress", "doing", "started", "wip", "moving"],
  blocked: ["blocked", "waiting", "on hold"],
  done: ["done", "complete", "completed", "shipped", "closed"],
  dropped: ["dropped", "cancelled", "canceled", "won't do", "removed"],
  decided: ["decided", "agreed", "done"],
};

export function mapStatus(status: string, allowed?: string[]): string {
  if (!allowed || !allowed.length) return status.replace("_", " ");
  const words = STATUS_WORDS[status] || [status];
  for (const a of allowed) {
    if (words.includes(norm(a))) return a;
  }
  return "";
}

export function valuesFor(p: PointForSheet, layout: Layout, dropdowns: Record<number, string[]>): Partial<Record<Field, string>> {
  const v: Partial<Record<Field, string>> = {};
  const textField: Field = p.kind === "decision" && layout.columns.decision !== undefined ? "decision" : p.kind === "risk" && layout.columns.risk !== undefined ? "risk" : "task";
  v[textField] = p.text;
  v.owner = p.owner;
  v.due = p.due;
  const statusCol = layout.columns.status;
  v.status = mapStatus(p.status, statusCol !== undefined ? dropdowns[statusCol] : undefined);
  v.notes = p.meetingLabel;
  return v;
}

export interface CellWrite {
  r: number;
  c: number;
  value: string;
  kind: "new" | "key" | "conflict";
  existing?: string;
}

export interface AppendPlan {
  mode: "append";
  insertAt: number; // row index where new rows begin (0-indexed)
  count: number;
  writes: CellWrite[];
  keys: string[];
  moved: string[]; // a1 refs of cells that move down
}

export function planAppend(rows: string[][], dropdowns: Record<number, string[]>, points: PointForSheet[]): AppendPlan {
  const layout = detectLayout(rows);
  const insertAt = layout.lastTableRow + 1;
  const keys = nextKeys(rows, layout, points.length);
  const writes: CellWrite[] = [];
  points.forEach((p, i) => {
    const r = insertAt + i;
    if (layout.keyCol >= 0) writes.push({ r, c: layout.keyCol, value: keys[i], kind: "key" });
    const vals = valuesFor(p, layout, dropdowns);
    for (const [field, value] of Object.entries(vals) as [Field, string][]) {
      const c = layout.columns[field];
      if (c === undefined || !value) continue;
      writes.push({ r, c, value, kind: "new" });
    }
    if (layout.headerRow < 0) {
      // no header: default order from the first column
      const order = [p.text, p.owner, p.due, p.status.replace("_", " ")];
      order.forEach((value, k) => value && writes.push({ r, c: k, value, kind: "new" }));
    }
  });
  const moved: string[] = [];
  for (let r = insertAt; r < rows.length; r++) {
    (rows[r] || []).forEach((cell, c) => {
      if ((cell || "").trim()) moved.push(a1(r, c));
    });
  }
  return { mode: "append", insertAt, count: points.length, writes, keys, moved };
}

export type Conflict = "skip" | "overwrite" | "insert";

export interface FillPlan {
  mode: "fill";
  anchor: { r: number; c: number };
  writes: CellWrite[];
  conflicts: string[];
  fieldOrder: { c: number; field: Field | "default" }[];
  insertAt?: number;
  count: number;
}

const DEFAULT_ORDER: Field[] = ["task", "owner", "due", "status"];

export function planFill(
  rows: string[][],
  dropdowns: Record<number, string[]>,
  points: PointForSheet[],
  anchor: { r: number; c: number },
  writeKeys: boolean,
  conflict: Conflict,
): FillPlan {
  const layout = detectLayout(rows);
  // field order from the header cells at and right of the anchor
  const fieldOrder: { c: number; field: Field | "default" }[] = [];
  const header = layout.headerRow >= 0 ? rows[layout.headerRow] : [];
  const anchorField = layout.headerRow >= 0 ? matchField(header[anchor.c] || "") : null;
  if (layout.headerRow >= 0 && anchorField) {
    for (let c = anchor.c; c <= layout.lastCol; c++) {
      const f = matchField(header[c] || "");
      if (f) fieldOrder.push({ c, field: f });
    }
  } else {
    DEFAULT_ORDER.forEach((f, k) => fieldOrder.push({ c: anchor.c + k, field: f }));
  }
  const writes: CellWrite[] = [];
  const conflicts: string[] = [];
  const keys = nextKeys(rows, layout, points.length);
  const effectiveRows = conflict === "insert" ? insertBlank(rows, anchor.r, points.length) : rows;
  points.forEach((p, i) => {
    const r = anchor.r + i;
    const vals = valuesFor(p, layout, dropdowns);
    if (!anchorField) {
      vals.task = p.text;
      vals.status = p.status.replace("_", " ");
    }
    const planned: { c: number; value: string }[] = [];
    for (const fo of fieldOrder) {
      const field = fo.field === "default" ? "task" : fo.field;
      const value = vals[field] ?? "";
      if (value) planned.push({ c: fo.c, value });
    }
    if (writeKeys && layout.keyCol >= 0 && layout.keyCol < anchor.c) planned.push({ c: layout.keyCol, value: keys[i] });
    for (const { c, value } of planned) {
      const existing = ((effectiveRows[r] || [])[c] || "").trim();
      const isKey = c === layout.keyCol;
      if (existing && conflict !== "insert") {
        conflicts.push(a1(r, c));
        if (conflict === "skip") {
          writes.push({ r, c, value: existing, kind: "conflict", existing });
          continue;
        }
        writes.push({ r, c, value, kind: "conflict", existing });
      } else {
        writes.push({ r, c, value, kind: isKey ? "key" : "new" });
      }
    }
  });
  return { mode: "fill", anchor, writes, conflicts, fieldOrder, insertAt: conflict === "insert" ? anchor.r : undefined, count: points.length };
}

function insertBlank(rows: string[][], at: number, count: number): string[][] {
  const width = Math.max(0, ...rows.map((r) => r.length));
  const blank = Array.from({ length: count }, () => Array(width).fill(""));
  return [...rows.slice(0, at), ...blank, ...rows.slice(at)];
}

export function applyPlan(rows: string[][], plan: AppendPlan | FillPlan): string[][] {
  const width = Math.max(0, ...rows.map((r) => r.length));
  let out = rows.map((r) => [...r, ...Array(Math.max(0, width - r.length)).fill("")]);
  if (plan.mode === "append") out = insertBlank(out, plan.insertAt, plan.count);
  else if (plan.insertAt !== undefined) out = insertBlank(out, plan.insertAt, plan.count);
  for (const w of plan.writes) {
    if (w.kind === "conflict" && w.existing !== undefined && w.value === w.existing) continue; // skipped
    while (out.length <= w.r) out.push(Array(width).fill(""));
    out[w.r][w.c] = w.value;
  }
  return out;
}

export function planCells(plan: AppendPlan | FillPlan): string[] {
  return plan.writes.filter((w) => !(w.kind === "conflict" && w.existing !== undefined && w.value === w.existing)).map((w) => a1(w.r, w.c));
}
