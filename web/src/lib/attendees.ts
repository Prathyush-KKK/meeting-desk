import type { Attendee } from "@/api/types";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * "Alex S, sam@acme.com, Priya" -> attendees. A name or email already on the meeting keeps its
 * stored address and response; a typed email is taken as the address; a new bare name gets no
 * address rather than an invented one, so a point's owner is never resolved to a mailbox that does
 * not exist.
 */
export function parseAttendees(text: string, existing: Attendee[] = []): Attendee[] {
  const out: Attendee[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(",")) {
    const entry = raw.trim();
    if (!entry) continue;
    const lower = entry.toLowerCase();
    const known = existing.find((a) => a.name.toLowerCase() === lower || a.email.toLowerCase() === lower);
    const attendee: Attendee = known
      ? { ...known }
      : EMAIL_RE.test(entry)
        ? { name: "", email: entry, response: "accepted" }
        : { name: entry, email: "", response: "accepted" };
    const key = (attendee.email || attendee.name).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(attendee);
  }
  return out;
}
