// The TypeScript half of the planner parity suite.
//
// `api/tests/fixtures/sheets/*.json` was generated straight out of this module by
// `_generate_from_reference.mjs`, and `api/tests/test_layout.py` / `test_planner.py` assert the
// Python port against the very same `expect` blocks. Running both sides over one file is what keeps
// the preview in the browser and the write on the server from ever disagreeing.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  a1,
  applyPlan,
  colLetter,
  detectLayout,
  nextKeys,
  planAppend,
  planCells,
  planFill,
  type AppendPlan,
  type Conflict,
  type FillPlan,
  type PointForSheet,
} from "./sheet";

const FIXTURE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../../api/tests/fixtures/sheets");

const NAMES = [
  "headers_row_1",
  "headers_row_9_banner",
  "no_header",
  "two_header_rows",
  "formula_col",
  "date_col",
  "task_keyed_no_id",
];

const CONFLICTS: Conflict[] = ["skip", "overwrite", "insert"];

interface Fixture {
  name: string;
  title: string;
  rows: string[][];
  dropdowns: Record<string, string[]>;
  points: { id: string; kind: string; text: string; owner: string; due: string; status: string; meeting_label: string }[];
  fill: { anchor: { r: number; c: number }; write_keys: boolean };
  expect: {
    layout: Record<string, unknown>;
    next_keys: string[];
    append: Record<string, unknown>;
    fill: Record<string, Record<string, unknown>>;
  };
}

function load(name: string): Fixture {
  return JSON.parse(readFileSync(resolve(FIXTURE_DIR, `${name}.json`), "utf8")) as Fixture;
}

function dropdownsOf(fx: Fixture): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  for (const [k, v] of Object.entries(fx.dropdowns)) out[Number(k)] = v;
  return out;
}

function pointsOf(fx: Fixture): PointForSheet[] {
  return fx.points.map((p) => ({
    id: p.id,
    kind: p.kind as PointForSheet["kind"],
    text: p.text,
    owner: p.owner,
    due: p.due,
    status: p.status,
    meetingLabel: p.meeting_label,
  }));
}

/** The exact shape `_generate_from_reference.mjs` wrote, so the comparison is byte-for-byte. */
function writesOf(plan: AppendPlan | FillPlan) {
  return plan.writes.map((w) => ({ ref: a1(w.r, w.c), r: w.r, c: w.c, value: w.value, kind: w.kind, existing: w.existing ?? null }));
}

describe("lib/sheet against the shared fixtures", () => {
  it.each(NAMES)("%s: detectLayout matches the fixture", (name) => {
    const fx = load(name);
    const layout = detectLayout(fx.rows);
    const want = fx.expect.layout;
    expect(layout.headerRow).toBe(want.header_row);
    expect(layout.firstCol).toBe(want.first_col);
    expect(layout.lastCol).toBe(want.last_col);
    expect(layout.columns).toEqual(want.columns);
    expect(layout.keyCol).toBe(want.key_col);
    expect(layout.keyPrefix).toBe(want.key_prefix);
    expect(layout.lastTableRow).toBe(want.last_table_row);
    expect(layout.headerScore).toBe(want.header_score);
  });

  it.each(NAMES)("%s: nextKeys matches the fixture", (name) => {
    const fx = load(name);
    expect(nextKeys(fx.rows, detectLayout(fx.rows), 3)).toEqual(fx.expect.next_keys);
  });

  it.each(NAMES)("%s: planAppend matches the fixture", (name) => {
    const fx = load(name);
    const plan = planAppend(fx.rows, dropdownsOf(fx), pointsOf(fx));
    const want = fx.expect.append;
    expect(planCells(plan)).toEqual(want.cells);
    expect(plan.insertAt).toBe(want.insert_at);
    expect(plan.count).toBe(want.count);
    expect(plan.keys).toEqual(want.keys);
    expect(writesOf(plan)).toEqual(want.writes);
    expect(plan.moved).toEqual(want.moved);
    expect(applyPlan(fx.rows, plan)).toEqual(want.applied);
  });

  describe.each(CONFLICTS)("planFill with conflict=%s", (conflict) => {
    it.each(NAMES)("%s matches the fixture", (name) => {
      const fx = load(name);
      const plan = planFill(fx.rows, dropdownsOf(fx), pointsOf(fx), fx.fill.anchor, fx.fill.write_keys, conflict);
      const want = fx.expect.fill[conflict];
      expect(planCells(plan)).toEqual(want.cells);
      expect(writesOf(plan)).toEqual(want.writes);
      expect(plan.conflicts).toEqual(want.conflicts);
      expect(plan.fieldOrder).toEqual(want.field_order);
      expect(plan.insertAt ?? null).toEqual(want.insert_at);
      expect(plan.count).toBe(want.count);
      expect(applyPlan(fx.rows, plan)).toEqual(want.applied);
    });
  });
});

describe("lib/sheet behaviour the fixtures pin down", () => {
  it("keeps existing values when conflicts are skipped", () => {
    const fx = load("headers_row_9_banner");
    const plan = planFill(fx.rows, dropdownsOf(fx), pointsOf(fx), { r: 10, c: 1 }, true, "skip");
    expect(plan.conflicts.length).toBeGreaterThan(0);
    for (const w of plan.writes) {
      if (w.kind === "conflict") {
        expect(w.value).toBe(w.existing);
        expect(planCells(plan)).not.toContain(a1(w.r, w.c));
      }
    }
    expect(applyPlan(fx.rows, plan)[10][1]).toBe(fx.rows[10][1]);
  });

  it("pushes rows down when conflicts are inserted around", () => {
    const fx = load("headers_row_9_banner");
    const plan = planFill(fx.rows, dropdownsOf(fx), pointsOf(fx), { r: 10, c: 1 }, true, "insert");
    expect(plan.insertAt).toBe(10);
    expect(plan.conflicts).toEqual([]);
    const after = applyPlan(fx.rows, plan);
    expect(after.length).toBe(fx.rows.length + 3);
    expect(after[13][1]).toBe(fx.rows[10][1]);
  });

  it("numbers columns the way Sheets does", () => {
    expect([0, 1, 25, 26, 27, 51, 52].map(colLetter)).toEqual(["A", "B", "Z", "AA", "AB", "AZ", "BA"]);
    expect(a1(9, 2)).toBe("C10");
  });
});
