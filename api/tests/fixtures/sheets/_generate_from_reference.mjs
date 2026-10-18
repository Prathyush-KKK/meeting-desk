// Builds api/tests/fixtures/sheets/*.json from the prototype's lib/sheet.ts so the Python port is
// checked against the TypeScript reference rather than against itself.
import { writeFileSync, mkdirSync } from "node:fs";
import * as S from "/home/claude/meeting-desk/src/lib/sheet.ts";

const OUT = "/home/claude/meeting-desk-app/api/tests/fixtures/sheets";
mkdirSync(OUT, { recursive: true });

const pad = (rows, min = 8) => {
  const w = Math.max(min, ...rows.map((r) => r.length));
  return rows.map((r) => [...r, ...Array(Math.max(0, w - r.length)).fill("")]);
};

const STATUS_DD = ["open", "in progress", "blocked", "done", "dropped"];
const PRIO_DD = ["P0", "P1", "P2", "P3"];
const EFFORT_DD = ["XS", "S", "M", "L"];

const POINTS = [
  { id: "p1", kind: "action", text: "Mirror OpenRates before launch", owner: "Daniel Okafor", due: "3 Oct", status: "open", meetingLabel: "Platform squad sync · 22 Sep" },
  { id: "p2", kind: "decision", text: "Owner column holds a person, not a team", owner: "", due: "", status: "decided", meetingLabel: "Platform squad sync · 22 Sep" },
  { id: "p3", kind: "risk", text: "Receipt OCR accuracy is unmeasured", owner: "Anna Moreno", due: "", status: "blocked", meetingLabel: "Platform squad sync · 22 Sep" },
];

// --- grids -------------------------------------------------------------------------------------

// 1. headers on row 1 (store.tsx "Decisions")
const headersRow1 = pad([
  ["ID", "Decision", "Workstream", "Meeting", "Date", "Status", "Notes"],
  ["D-039", "Owner column holds a person, not a team", "Mobile", "Sheet review", "21 Sep", "decided", ""],
  ["D-040", "Prioritise user acquisition over perfecting AI receipt accuracy; add a verification step", "Mobile", "Mobile roadmap review", "19 Sep", "decided", ""],
  ["Q-011", "Is a tip an expense?", "Mobile", "Mobile roadmap review", "19 Sep", "open", "unblocks two items"],
  ["Q-012", "Accountant identity model", "Mobile", "Mobile roadmap review", "19 Sep", "open", "sets the P6 timeline"],
  [],
]);

// 2. headers on row 9, banner rows above, a stray note below the table (store.tsx "P1 Resolve & Log")
const headersRow9 = pad([
  ["P1 Resolve & Log"],
  ["", "Phase goal: all five capture flows ship; receipt scan is ours alone"],
  [],
  ["", "Owner is the assignee, one person (decided 21 Sep)"],
  [], [], [], [],
  ["ID", "Task", "Owner", "Due", "Priority", "Effort", "Status", "Notes"],
  ["T-101", "Photo capture flow", "Anna Moreno", "5 Sep", "P0", "M", "done", "v1.1"],
  ["T-102", "Manual entry flow", "Anna Moreno", "5 Sep", "P0", "S", "done", ""],
  ["T-103", "Card import flow", "Sofia Silva", "12 Sep", "P1", "S", "done", ""],
  ["T-104", "Receipt scan flow", "Daniel Okafor", "12 Sep", "P1", "M", "blocked", "OCR accuracy unmeasured"],
  ["T-105", "Northwind vendor verification call with Maya", "Alex S", "", "P2", "XS", "open", "from 15 Sep sync"],
  ["T-106", "Mirror OpenRates before launch", "Daniel Okafor", "3 Oct", "P0", "S", "open", "503s past ~10 req/min"],
  ["T-107", "Confirmation screen for receipt scanning", "Daniel Okafor", "3 Oct", "P1", "M", "in progress", ""],
  [],
  ["", "", "", "", "", "", "", "check dropdown on Status"],
  [], [],
]);

// 3. no header at all
const noHeader = pad([
  ["Fix the upload retry", "Noah S", "26 Sep", "open"],
  ["Ship the telemetry dashboard", "Sofia Silva", "30 Sep", "in progress"],
  [],
  ["", "", "", ""],
], 4);

// 4. two header rows: a merged group row above the real header row
const twoHeaderRows = pad([
  ["Delivery tracker", "Task", "Owner", "", "", "", "", ""],
  ["ID", "Task", "Owner", "Due", "Priority", "Effort", "Status", "Notes"],
  ["H-001", "Technical complexity evaluation", "Daniela Mehta", "17 Sep", "P0", "M", "in progress", ""],
  ["H-002", "Billing model decision", "Alex S", "15 Sep", "P0", "S", "blocked", ""],
  [],
]);

// 5. two formula columns: "Days left" (unmapped) and a rolled-up "Status" the planner would
//    otherwise write into.
const formulaCol = pad([
  ["ID", "Task", "Owner", "Due", "Days left", "Status", "Notes"],
  ["T-301", "Parse the vendor CSV exports", "Daniel Okafor", "10 Oct", "18", "open", ""],
  ["T-302", "Legal review of tax table", "product", "3 Oct", "11", "blocked", "buy an hour"],
  [],
], 7);
const formulaColFormulas = pad([
  ["ID", "Task", "Owner", "Due", "Days left", "Status", "Notes"],
  ["T-301", "Parse the vendor CSV exports", "Daniel Okafor", "10 Oct", "=DATEDIF(TODAY(),D2,\"D\")", "=IF(E2<0,\"overdue\",\"open\")", ""],
  ["T-302", "Legal review of tax table", "product", "3 Oct", "=DATEDIF(TODAY(),D3,\"D\")", "=IF(E3<0,\"overdue\",\"open\")", "buy an hour"],
  [],
], 7);

// 6. a date column: Due carries a DATE number format
const dateCol = pad([
  ["ID", "Task", "Owner", "Due", "Status", "Notes"],
  ["T-401", "Mirror OpenRates", "Daniel Okafor", "03/10/2026", "open", ""],
  ["T-402", "Confirmation screen", "Daniel Okafor", "03/10/2026", "in progress", ""],
  [],
], 6);
const dateColFormats = [
  ["TEXT", "TEXT", "TEXT", "TEXT", "TEXT", "TEXT"],
  ["TEXT", "TEXT", "TEXT", "DATE", "TEXT", "TEXT"],
  ["TEXT", "TEXT", "TEXT", "DATE", "TEXT", "TEXT"],
  ["TEXT", "TEXT", "TEXT", "TEXT", "TEXT", "TEXT"],
];

// 7. keyed on Task, no ID column (store.tsx "Earn Points")
const taskKeyed = pad([
  ["Task", "Points", "Cap", "Status", "Notes"],
  ["Upload an ID", "100", "one time", "live", ""],
  ["Sharing a document", "50", "daily", "live", ""],
  ["Complete profile", "200", "one time", "live", ""],
  [],
], 5);

const FIXTURES = [
  {
    name: "headers_row_1",
    description: "Headers on row 1; the table runs to the last decision row.",
    title: "Decisions",
    rows: headersRow1,
    dropdowns: { 5: ["decided", "open", "superseded"] },
    formula_cols: [],
    date_cols: [],
    fill: { anchor: { r: 5, c: 1 }, write_keys: true },
  },
  {
    name: "headers_row_9_banner",
    description: "Headers on row 9 under four banner rows, with a stray note two rows below the table.",
    title: "P1 Resolve & Log",
    rows: headersRow9,
    dropdowns: { 4: PRIO_DD, 5: EFFORT_DD, 6: STATUS_DD },
    formula_cols: [],
    date_cols: [],
    fill: { anchor: { r: 10, c: 1 }, write_keys: true },
  },
  {
    name: "no_header",
    description: "No header row: the default column order is used from the first column.",
    title: "Scratch",
    rows: noHeader,
    dropdowns: {},
    formula_cols: [],
    date_cols: [],
    fill: { anchor: { r: 0, c: 0 }, write_keys: false },
  },
  {
    name: "two_header_rows",
    description: "A merged group row above the real header row; the lower row scores higher and wins.",
    title: "Delivery tracker",
    rows: twoHeaderRows,
    dropdowns: { 4: PRIO_DD, 5: EFFORT_DD, 6: STATUS_DD },
    formula_cols: [],
    date_cols: [],
    fill: { anchor: { r: 2, c: 1 }, write_keys: true },
  },
  {
    name: "formula_col",
    description: "Days left is a formula column: never written, copied down after an insert.",
    title: "P4 Regional & AI",
    rows: formulaCol,
    formulas: formulaColFormulas,
    dropdowns: {},
    formula_cols: [4, 5],
    date_cols: [],
    fill: { anchor: { r: 1, c: 1 }, write_keys: false },
    // Hand-written: what the Python planner must produce once the reader's formula columns are fed
    // in. The TypeScript reference has no notion of formula columns, so this is not derived from it.
    with_hooks: {
      append_cells: ["A4", "B4", "C4", "D4", "G4", "A5", "B5", "G5", "A6", "B6", "C6", "G6"],
      formula_fill: [
        { col: 4, source_row: 2, target_rows: [3, 4, 5] },
        { col: 5, source_row: 2, target_rows: [3, 4, 5] },
      ],
      fill_skip_cells: ["G2", "B4", "C4", "G4"],
      fill_skip_conflicts: ["B2", "C2", "D2", "B3", "G3"],
      date_cells: [],
    },
  },
  {
    name: "date_col",
    description: "Due carries a DATE number format, so the write is flagged as a date.",
    title: "P2 Dates",
    rows: dateCol,
    number_formats: dateColFormats,
    dropdowns: { 4: STATUS_DD },
    formula_cols: [],
    date_cols: [3],
    fill: { anchor: { r: 1, c: 1 }, write_keys: false },
    // Hand-written, as above: the date column changes no cell, only how the value is sent.
    with_hooks: {
      append_cells: ["A4", "B4", "C4", "D4", "E4", "F4", "A5", "B5", "E5", "F5", "A6", "B6", "C6", "E6", "F6"],
      formula_fill: [],
      date_cells: ["D4"],
    },
  },
  {
    name: "task_keyed_no_id",
    description: "Keyed on Task with no ID column: no keys are allocated.",
    title: "Earn Points",
    rows: taskKeyed,
    dropdowns: { 3: ["live", "planned", "removed"] },
    formula_cols: [],
    date_cols: [],
    fill: { anchor: { r: 1, c: 0 }, write_keys: false },
  },
];

const toDropdowns = (dd) => {
  const out = {};
  for (const [k, v] of Object.entries(dd)) out[Number(k)] = v;
  return out;
};

const writeOut = (w) => ({ ref: S.a1(w.r, w.c), r: w.r, c: w.c, value: w.value, kind: w.kind, existing: w.existing ?? null });

for (const f of FIXTURES) {
  const dd = toDropdowns(f.dropdowns);
  const layout = S.detectLayout(f.rows);
  const append = S.planAppend(f.rows, dd, POINTS);
  const fills = {};
  for (const conflict of ["skip", "overwrite", "insert"]) {
    const plan = S.planFill(f.rows, dd, POINTS, f.fill.anchor, f.fill.write_keys, conflict);
    fills[conflict] = {
      cells: S.planCells(plan),
      writes: plan.writes.map(writeOut),
      conflicts: plan.conflicts,
      field_order: plan.fieldOrder,
      keys: plan.keys,
      insert_at: plan.insertAt ?? null,
      count: plan.count,
      applied: S.applyPlan(f.rows, plan),
    };
  }
  const out = {
    name: f.name,
    description: f.description,
    title: f.title,
    rows: f.rows,
    formulas: f.formulas ?? null,
    number_formats: f.number_formats ?? null,
    dropdowns: f.dropdowns,
    formula_cols: f.formula_cols,
    date_cols: f.date_cols,
    points: POINTS.map((p) => ({ id: p.id, kind: p.kind, text: p.text, owner: p.owner, due: p.due, status: p.status, meeting_label: p.meetingLabel })),
    fill: f.fill,
    with_hooks: f.with_hooks ?? null,
    // Everything below is produced by meeting-desk/src/lib/sheet.ts - the reference implementation.
    expect: {
      layout: {
        header_row: layout.headerRow,
        first_col: layout.firstCol,
        last_col: layout.lastCol,
        columns: layout.columns,
        key_col: layout.keyCol,
        key_prefix: layout.keyPrefix,
        last_table_row: layout.lastTableRow,
        header_score: layout.headerScore,
      },
      next_keys: S.nextKeys(f.rows, layout, 3),
      append: {
        insert_at: append.insertAt,
        count: append.count,
        keys: append.keys,
        cells: S.planCells(append),
        writes: append.writes.map(writeOut),
        moved: append.moved,
        applied: S.applyPlan(f.rows, append),
      },
      fill: fills,
    },
  };
  writeFileSync(`${OUT}/${f.name}.json`, JSON.stringify(out, null, 2) + "\n");
  console.log(f.name, "header", layout.headerRow, "key", layout.keyCol, layout.keyPrefix, "extent", layout.lastTableRow, "append cells", S.planCells(append).join(","));
}
console.log("wrote", FIXTURES.length, "fixtures");
