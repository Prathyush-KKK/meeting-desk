// Formatting and the few vocabularies the UI shows. Everything is rendered in Asia/Kolkata; the
// API already returns IST-local strings, so nothing is converted twice here.

import type { Kind, Status } from "@/api/types";

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

/** "2026-09-22" -> "Tue 22 Sep". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

/** An ISO timestamp -> "16:58", the way the header shows "read HH:MM". */
export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function shortName(email: string | null | undefined): string {
  return (email || "").split("@")[0];
}

export function ago(minutes: number): string {
  if (minutes <= 0) return "just now";
  if (minutes === 1) return "1 min ago";
  return `${minutes} min ago`;
}

/** The label that keeps a transferred row tied to its meeting, mirroring the API's meeting_label. */
export function meetingLabel(title: string, date: string | null | undefined): string {
  if (!date) return title;
  const d = new Date(`${date}T00:00:00`);
  if (Number.isNaN(d.getTime())) return title;
  return `${title} · ${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}
