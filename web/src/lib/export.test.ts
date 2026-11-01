import { describe, expect, it } from "vitest";

import type { Point } from "@/api/types";
import { exportName, pointsToCsv, pointsToGithubMarkdown, pointsToJiraCsv, pointsToMarkdown, pointsToNotionCsv } from "@/lib/export";

function point(overrides: Partial<Point>): Point {
  return {
    id: "p",
    meeting_id: "m",
    extraction_id: null,
    kind: "action",
    text: "",
    text_norm: "",
    evidence: "",
    owner_text: "",
    owner_email: null,
    owner_ambiguous: false,
    due_text: "",
    due_date: null,
    status: "open",
    workstream: "Mobile",
    lifecycle: "active",
    selected: false,
    updated_by: null,
    updated_at: null,
    deleted_at: null,
    ...overrides,
  } as Point;
}

const MEETING = { title: "Mobile roadmap review", date: "2026-09-19" };
const POINTS = [
  point({ kind: "decision", text: "The Owner column holds a person, not a team", status: "decided" }),
  point({ text: 'Mirror the "rates" feed, then report', owner_text: "Daniel Okafor", owner_email: "daniel.okafor@example.com", due_text: "before 3 Oct", due_date: "2026-10-03T00:00:00+05:30" }),
  point({ text: "=HYPERLINK(1)", status: "blocked" }),
];

describe("pointsToCsv", () => {
  it("puts actions first, quotes what needs it and defuses formulas", () => {
    const lines = pointsToCsv(POINTS, MEETING).trimEnd().split("\r\n");
    expect(lines[0]).toBe("Kind,Point,Owner,Owner email,Due,Due date,Status,Workstream,Meeting,Meeting date");
    expect(lines[1]).toBe(
      'action,"Mirror the ""rates"" feed, then report",Daniel Okafor,daniel.okafor@example.com,before 3 Oct,2026-10-03,open,Mobile,Mobile roadmap review,2026-09-19',
    );
    expect(lines[2].split(",")[1]).toBe("'=HYPERLINK(1)");
    expect(lines[3].startsWith("decision,")).toBe(true);
  });
});

describe("pointsToMarkdown", () => {
  it("groups by kind with checkboxes for actions", () => {
    const md = pointsToMarkdown(POINTS, MEETING);
    expect(md).toContain("# Mobile roadmap review (2026-09-19)");
    expect(md).toContain('## Action items\n\n- [ ] **Daniel Okafor**: Mirror the "rates" feed, then report - due before 3 Oct');
    expect(md).toContain("- [ ] =HYPERLINK(1) _(blocked)_");
    expect(md).toContain("## Decisions\n\n- The Owner column holds a person, not a team");
  });
});

describe("exportName", () => {
  it("is the date and a slug of the title", () => {
    expect(exportName(MEETING)).toBe("2026-09-19-mobile-roadmap-review");
    expect(exportName({ title: "!!", date: null })).toBe("meeting");
  });
});

describe("pointsToGithubMarkdown", () => {
  it("exports one issue block per action, in input order, with meeting context", () => {
    const md = pointsToGithubMarkdown(POINTS, MEETING);
    expect(md).toContain('## Mirror the "rates" feed, then report');
    expect(md).toContain("**Owner:** Daniel Okafor");
    expect(md).toContain("**Due date:** 2026-10-03");
    expect(md).toContain("**Meeting:** Mobile roadmap review (2026-09-19)");
    expect(md).not.toContain("The Owner column holds a person");
    expect(md.match(/^## /gm)).toHaveLength(2);
    expect(md.indexOf('## Mirror')).toBeLessThan(md.indexOf('## =HYPERLINK'));
  });

  it("keeps multiline action text in the body and uses its first nonempty line as the title", () => {
    const md = pointsToGithubMarkdown([point({ text: "\nSend the notes\nInclude the timeline\n\nKeep the appendix" })], MEETING);
    expect(md).toContain("## Send the notes\n");
    expect(md).toContain("### Description\n\nSend the notes\nInclude the timeline\n\nKeep the appendix");
  });

  it("handles missing metadata and falls back to the owner's email and natural-language due date", () => {
    const md = pointsToGithubMarkdown([
      point({ text: "Follow up", owner_email: "alex@example.com", due_text: "next Friday" }),
      point({ text: "" }),
    ], { title: "Planning", date: null });
    expect(md).toContain("**Owner:** alex@example.com");
    expect(md).toContain("**Due date:** next Friday");
    expect(md).toContain("**Owner:** Unassigned");
    expect(md).toContain("**Due date:** Not set");
    expect(md).toContain("## Untitled action item");
    expect(md).toContain("**Meeting:** Planning\n");
    expect(md).not.toContain("null");
  });

  it("shortens a long title and keeps the whole text in the description", () => {
    const long = `Draft the migration plan ${"for every regional team ".repeat(8)}`.trim();
    const md = pointsToGithubMarkdown([point({ text: long })], MEETING);
    const title = md.split("\n")[0].slice(3);
    expect(title).toHaveLength(100);
    expect(title.endsWith("…")).toBe(true);
    expect(md).toContain(`### Description\n\n${long}\n`);
  });

  it("returns no issue blocks for an empty list or non-action points", () => {
    expect(pointsToGithubMarkdown([], MEETING)).toBe("");
    expect(pointsToGithubMarkdown([point({ kind: "decision", text: "Choose a plan" })], MEETING)).toBe("");
  });
});

/** A CSV parsed back into rows, quotes and all: what an importer would read. */
function parseCsv(csv: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < csv.length; i++) {
    const ch = csv[i];
    if (quoted && ch === '"' && csv[i + 1] === '"') {
      cell += '"';
      i++;
    } else if (ch === '"') {
      quoted = !quoted;
    } else if (quoted || (ch !== "," && ch !== "\n" && ch !== "\r")) {
      cell += ch;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    }
  }
  return rows;
}

describe("pointsToJiraCsv", () => {
  it("is one Task per action with Jira's field names, the owner's email and an ISO due date", () => {
    const [header, ...rows] = parseCsv(pointsToJiraCsv(POINTS, MEETING));
    expect(header).toEqual(["Summary", "Description", "Issue Type", "Assignee", "Due date", "Labels"]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual([
      'Mirror the "rates" feed, then report',
      'Mirror the "rates" feed, then report\n\nFrom the meeting "Mobile roadmap review" on 2026-09-19.',
      "Task",
      "daniel.okafor@example.com",
      "2026-10-03",
      "meeting-desk Mobile",
    ]);
    expect(rows[1][0]).toBe("'=HYPERLINK(1)");
  });

  it("keeps an owner or due date it could not resolve in the description, and makes labels Jira-safe", () => {
    const [, row] = parseCsv(
      pointsToJiraCsv([point({ text: "Line one\nLine two", owner_text: "Sam", due_text: "after the offsite", workstream: "Prod ops" })], {
        title: "Ops sync",
        date: null,
      }),
    );
    expect(row[0]).toBe("Line one");
    expect(row[1]).toBe('Line one\nLine two\n\nFrom the meeting "Ops sync".\nOwner named in the notes: Sam.\nDue: after the offsite.');
    expect(row[3]).toBe("");
    expect(row[4]).toBe("");
    expect(row[5]).toBe("meeting-desk Prod-ops");
  });

  it("cuts a summary at Jira's 255 characters", () => {
    const [, row] = parseCsv(pointsToJiraCsv([point({ text: "x".repeat(400) })], MEETING));
    expect(row[0]).toHaveLength(255);
  });

  it("has only the header without action items", () => {
    expect(parseCsv(pointsToJiraCsv([POINTS[0]], MEETING))).toHaveLength(1);
  });
});

describe("pointsToNotionCsv", () => {
  it("puts the point first, as Notion's title column, and keeps every kind", () => {
    const [header, ...rows] = parseCsv(pointsToNotionCsv(POINTS, MEETING));
    expect(header[0]).toBe("Name");
    expect(header).toContain("Due date");
    expect(rows.map((r) => r[1])).toEqual(["action", "action", "decision"]);
    expect(rows[0]).toEqual([
      'Mirror the "rates" feed, then report',
      "action",
      "Daniel Okafor",
      "daniel.okafor@example.com",
      "2026-10-03",
      "",
      "open",
      "Mobile",
      "Mobile roadmap review",
      "2026-09-19",
    ]);
  });

  it("keeps a due phrase it could not turn into a date", () => {
    const [, row] = parseCsv(pointsToNotionCsv([point({ text: "Plan", due_text: "after the offsite" })], MEETING));
    expect(row[4]).toBe("");
    expect(row[5]).toBe("after the offsite");
  });
});
