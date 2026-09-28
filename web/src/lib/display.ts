// Formatting and the few vocabularies the UI shows. Everything is rendered in Asia/Kolkata; the
// API already returns IST-local strings, so nothing is converted twice here.

import type { Kind, Status, Transfer } from "@/api/types";

export const IST = "Asia/Kolkata";

export const STATUS_LABEL: Record<Status, string> = {
  open: "open",
  in_progress: "in progress",
  blocked: "blocked",
  done: "done",
  dropped: "dropped",
  decided: "decided",
};

export const STATUSES: Status[] = ["open", "in_progress", "blocked", "done", "dropped"];
export const DECISION_STATUSES: Status[] = ["decided", "open", "dropped"];

export const KIND_ORDER: Kind[] = ["action", "decision", "risk", "question"];
export const KIND_TITLE: Record<Kind, string> = {
  action: "Action items",
  decision: "Decisions",
  risk: "Risks",
  question: "Open questions",
};

/** The workstreams the workspace uses; anything already on a meeting is merged in at runtime. */
export const WORKSTREAMS = ["Nutrition", "Platform", "Household & CDP", "SIApoints", "Prod ops", "Hiring"];

export function mergeWorkstreams(extra: (string | null | undefined)[]): string[] {
  const seen = new Set(WORKSTREAMS);
  const out = [...WORKSTREAMS];
  for (const value of extra) {
    const w = (value || "").trim();
    if (w && !seen.has(w)) {
      seen.add(w);
      out.push(w);
    }
  }
  return out;
}

/**
 * "2026-09-22" -> "Tue 22 Sep". A calendar date, not an instant: it is read and written in UTC so
 * no zone can move it to the day before.
 */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

/**
 * An ISO timestamp -> "16:58" in Asia/Kolkata, the way the header shows "read HH:MM". Spec section
 * 7: "Times shown in Asia/Kolkata everywhere" - it used the browser's zone, so a laptop set to
 * another zone read the same sheet at a different time (screen review R1-25).
 */
export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: IST });
}

/** An ISO timestamp -> "Tue 22 Sep 16:58", day and time both in Asia/Kolkata. */
export function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: IST });
  return `${day} ${fmtClock(iso)}`;
}

export function shortName(email: string | null | undefined): string {
  return (email || "").split("@")[0];
}

/** "1 point", "3 points". */
export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Long provider errors run to a stack trace; the list shows the start and the title the rest. */
export function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/**
 * Today as YYYY-MM-DD on this machine's calendar. Not toISOString: that is UTC, and before 05:30
 * IST it is still yesterday there.
 */
export function localToday(now: Date = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

export type DayGroup = "upcoming" | "today" | "earlier";

/** Where a meeting sits against today; a meeting with no date is history, not a plan. */
export function dayGroup(date: string | null | undefined, today: string): DayGroup {
  if (!date || date < today) return "earlier";
  return date > today ? "upcoming" : "today";
}

export function ago(minutes: number): string {
  if (minutes <= 0) return "just now";
  if (minutes === 1) return "1 min ago";
  return `${minutes} min ago`;
}

/** A tab title if the transfer's snapshot carries one; today's snapshots do not, so the sheet id. */
/** "Nutrition Roadmap / Backlog" from the names the transfer kept; older rows have only the sheet id. */
export function transferSheet(t: Pick<Transfer, "sheet_id" | "snapshot">): string {
  const book = t.snapshot?.workbook_name;
  const tab = t.snapshot?.sheet_title;
  const tabName = typeof tab === "string" && tab ? tab : `sheet ${t.sheet_id}`;
  return typeof book === "string" && book ? `${book} / ${tabName}` : tabName;
}

/** The label that keeps a transferred row tied to its meeting, mirroring the API's meeting_label. */
export function meetingLabel(title: string, date: string | null | undefined): string {
  if (!date) return title;
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return title;
  return `${title} · ${d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}`;
}
