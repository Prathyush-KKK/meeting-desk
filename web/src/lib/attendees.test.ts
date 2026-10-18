import { describe, expect, it } from "vitest";

import { parseAttendees } from "@/lib/attendees";

const EXISTING = [
  { name: "Alex S", email: "alex.s@example.com", response: "tentative" },
  { name: "Daniel Okafor", email: "daniel.okafor@example.com", response: "accepted" },
];

describe("parseAttendees", () => {
  it("keeps a known attendee's address and response, by name or by email", () => {
    expect(parseAttendees("Alex S, daniel.okafor@example.com", EXISTING)).toEqual(EXISTING);
  });

  it("takes a typed email as the address and never invents one for a bare name", () => {
    expect(parseAttendees("sam@acme.dev, Priya", EXISTING)).toEqual([
      { name: "", email: "sam@acme.dev", response: "accepted" },
      { name: "Priya", email: "", response: "accepted" },
    ]);
  });

  it("drops blanks and duplicates", () => {
    expect(parseAttendees(" , Alex S,alex s, ", EXISTING)).toHaveLength(1);
  });
});
