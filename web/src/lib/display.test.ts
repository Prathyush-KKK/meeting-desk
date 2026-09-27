// Screen review round 1, R1-25. Spec section 7: "Times shown in Asia/Kolkata everywhere." These
// hold whatever zone the machine running them is in: the instant is fixed, the answer must be IST.

import { describe, expect, it } from "vitest";
import { fmtClock, fmtDate, meetingLabel } from "./display";

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

  it("leaves nothing for nothing", () => {
    expect(fmtClock(null)).toBe("");
    expect(fmtDate("")).toBe("");
  });
});
