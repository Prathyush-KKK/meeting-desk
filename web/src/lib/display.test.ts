// Screen review round 1, R1-25. Spec section 7: "Times shown in Asia/Kolkata everywhere." These
// hold whatever zone the machine running them is in: the instant is fixed, the answer must be IST.

import { describe, expect, it } from "vitest";
import { clip, dayGroup, fmtClock, fmtDate, fmtStamp, localToday, meetingLabel, plural, transferSheet } from "./display";

describe("times and dates", () => {
  it("shows an instant as Asia/Kolkata wall-clock time", () => {
    expect(fmtClock("2026-09-22T11:32:00Z")).toBe("17:02");
    expect(fmtClock("2026-09-22T17:02:00+05:30")).toBe("17:02");
    expect(fmtClock("2026-09-22T20:00:00-07:00")).toBe("08:30"); // the next morning in India
  });

  it("never moves a calendar date to another day", () => {
    expect(fmtDate("2026-09-22")).toMatch(/22 Sep/);
    expect(meetingLabel("Vendor call", "2026-09-22")).toMatch(/· 22 Sep/);
  });

  it("stamps an instant with its day and time in Asia/Kolkata", () => {
    expect(fmtStamp("2026-09-22T17:02:00+05:30")).toMatch(/^Tue 22 Sept? 17:02$/);
    expect(fmtStamp("2026-09-22T20:00:00Z")).toMatch(/^Wed 23 Sept? 01:30$/); // already the next day in India
  });

  it("leaves nothing for nothing", () => {
    expect(fmtClock(null)).toBe("");
    expect(fmtDate("")).toBe("");
    expect(fmtStamp(null)).toBe("");
  });
});

describe("the meeting list's day groups", () => {
  it("reads today off the local calendar, not UTC", () => {
    expect(localToday(new Date(2026, 8, 22, 0, 30))).toBe("2026-09-22");
    expect(localToday(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("puts a meeting before, on or after today, and one with no date in Earlier", () => {
    expect(dayGroup("2026-09-23", "2026-09-22")).toBe("upcoming");
    expect(dayGroup("2026-09-22", "2026-09-22")).toBe("today");
    expect(dayGroup("2026-08-31", "2026-09-22")).toBe("earlier");
    expect(dayGroup(null, "2026-09-22")).toBe("earlier");
  });
});

describe("history lines", () => {
  it("counts in words", () => {
    expect(plural(1, "point")).toBe("1 point");
    expect(plural(0, "note")).toBe("0 notes");
  });

  it("clips a long error with an ellipsis and leaves a short one alone", () => {
    expect(clip("short", 10)).toBe("short");
    const clipped = clip("a".repeat(300), 160);
    expect(clipped).toHaveLength(160);
    expect(clipped.endsWith("…")).toBe(true);
  });

  it("names the sheet by the names the transfer kept, else by its id", () => {
    expect(transferSheet({ sheet_id: "1234", snapshot: {} })).toBe("sheet 1234");
    expect(transferSheet({ sheet_id: "1234", snapshot: { sheet_title: "Roadmap" } })).toBe("Roadmap");
    expect(transferSheet({ sheet_id: "1234", snapshot: { workbook_name: "Nutrition", sheet_title: "Roadmap" } })).toBe("Nutrition / Roadmap");
    expect(transferSheet({ sheet_id: "1234", snapshot: { workbook_name: "Nutrition" } })).toBe("Nutrition / sheet 1234");
  });
});
