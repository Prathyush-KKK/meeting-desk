import { describe, expect, it } from "vitest";

import type { Point } from "@/api/types";
import { exportName, pointsToCsv, pointsToGithubMarkdown, pointsToMarkdown } from "@/lib/export";

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

  it("returns no issue blocks for an empty list or non-action points", () => {
    expect(pointsToGithubMarkdown([], MEETING)).toBe("");
    expect(pointsToGithubMarkdown([point({ kind: "decision", text: "Choose a plan" })], MEETING)).toBe("");
  });
});
