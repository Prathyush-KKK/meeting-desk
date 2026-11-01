// The points of a meeting as a file to take elsewhere: CSV for a spreadsheet, Jira's or Notion's
// CSV import, Markdown for a doc, a PR, an issue or a chat message. Built in the browser from what
// the page already shows; nothing leaves the tool except the file the person saves.

import type { Point } from "@/api/types";
import { KIND_ORDER, KIND_TITLE, STATUS_LABEL, clip } from "@/lib/display";

export interface ExportMeeting {
  title: string;
  date: string | null;
}

const COLUMNS = ["Kind", "Point", "Owner", "Owner email", "Due", "Due date", "Status", "Workstream", "Meeting", "Meeting date"];

function csvCell(value: string): string {
  // Quote what needs it, and defuse a leading =, +, - or @ so a spreadsheet does not run it.
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

function toCsv(header: string[], rows: string[][]): string {
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/** A point's first non-empty line, as a title no longer than ``max``. */
function titleOf(text: string, max: number, fallback = "Untitled action item"): string {
  return clip(text.split("\n").find((line) => line.trim())?.trim() || fallback, max);
}

const isoDay = (value: string | null) => (value ? value.slice(0, 10) : "");

function ordered(points: Point[]): Point[] {
  return [...points].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
}

export function pointsToCsv(points: Point[], meeting: ExportMeeting): string {
  const rows = ordered(points).map((p) => [
    p.kind,
    p.text,
    p.owner_text,
    p.owner_email ?? "",
    p.due_text,
    isoDay(p.due_date),
    STATUS_LABEL[p.status] ?? p.status,
    p.workstream,
    meeting.title,
    meeting.date ?? "",
  ]);
  return toCsv(COLUMNS, rows);
}

/** Jira's summary field holds 255 characters. */
const JIRA_SUMMARY_MAX = 255;

/**
 * One Jira issue per action item, for Jira's "Import issues from CSV". The headers are Jira's
 * field names, so the importer maps them on its own; Assignee is the owner's email, which Jira
 * matches to an account; the due date is yyyy-MM-dd, the date format to pick in the importer.
 * Labels carry "meeting-desk" and the workstream, spaces made dashes since a Jira label has none.
 */
export function pointsToJiraCsv(points: Point[], meeting: ExportMeeting): string {
  const context = `From the meeting "${meeting.title}"${meeting.date ? ` on ${meeting.date}` : ""}.`;
  const rows = points
    .filter((p) => p.kind === "action")
    .map((p) => {
      const owner = p.owner_text && !p.owner_email ? `\nOwner named in the notes: ${p.owner_text}.` : "";
      const due = p.due_text && !p.due_date ? `\nDue: ${p.due_text}.` : "";
      const labels = ["meeting-desk", p.workstream.trim().replace(/\s+/g, "-")].filter(Boolean).join(" ");
      return [titleOf(p.text, JIRA_SUMMARY_MAX), `${p.text.trim()}\n\n${context}${owner}${due}`, "Task", p.owner_email ?? "", isoDay(p.due_date), labels];
    });
  return toCsv(["Summary", "Description", "Issue Type", "Assignee", "Due date", "Labels"], rows);
}

/**
 * Every point as a row of a Notion database: Notion makes a CSV's first column the page title,
 * and reads yyyy-MM-dd as a date once the column is switched to a Date property.
 */
export function pointsToNotionCsv(points: Point[], meeting: ExportMeeting): string {
  const rows = ordered(points).map((p) => [
    p.text.trim(),
    p.kind,
    p.owner_text || p.owner_email || "",
    p.owner_email ?? "",
    isoDay(p.due_date),
    p.due_date ? "" : p.due_text,
    STATUS_LABEL[p.status] ?? p.status,
    p.workstream,
    meeting.title,
    meeting.date ?? "",
  ]);
  return toCsv(["Name", "Kind", "Owner", "Owner email", "Due date", "Due (as written)", "Status", "Workstream", "Meeting", "Meeting date"], rows);
}

export function pointsToMarkdown(points: Point[], meeting: ExportMeeting): string {
  const lines = [`# ${meeting.title}${meeting.date ? ` (${meeting.date})` : ""}`, ""];
  for (const kind of KIND_ORDER) {
    const group = points.filter((p) => p.kind === kind);
    if (!group.length) continue;
    lines.push(`## ${KIND_TITLE[kind]}`, "");
    for (const p of group) {
      const owner = p.owner_text ? `**${p.owner_text}**: ` : "";
      const due = p.due_text ? ` - due ${p.due_text}` : "";
      const box = kind === "action" ? (p.status === "done" ? "[x] " : "[ ] ") : "";
      const status = kind === "action" && p.status !== "open" && p.status !== "done" ? ` _(${STATUS_LABEL[p.status]})_` : "";
      lines.push(`- ${box}${owner}${p.text}${due}${status}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

/** A GitHub issue title over this reads badly in lists; the full text stays in the description. */
const ISSUE_TITLE_MAX = 100;

/** One copyable issue title and body per action item. No GitHub connection is needed. */
export function pointsToGithubMarkdown(points: Point[], meeting: ExportMeeting): string {
  const inline = (value: string) => value.replace(/\s+/g, " ").trim();
  const context = `${inline(meeting.title)}${meeting.date ? ` (${meeting.date})` : ""}`;
  return points.filter((p) => p.kind === "action").map((p) => {
    const text = p.text.replace(/\r\n?/g, "\n").trim();
    const title = titleOf(text, ISSUE_TITLE_MAX);
    const owner = inline(p.owner_text) || p.owner_email || "Unassigned";
    const due = p.due_date ? p.due_date.slice(0, 10) : inline(p.due_text) || "Not set";
    return [
      `## ${title}`, "",
      `**Owner:** ${owner}`,
      `**Due date:** ${due}`,
      `**Meeting:** ${context}`, "",
      "### Description", "",
      text || "Untitled action item", "",
    ].join("\n");
  }).join("\n---\n\n");
}

/** "Mobile roadmap review" on 2026-09-19 -> "2026-09-19-mobile-roadmap-review". */
export function exportName(meeting: ExportMeeting): string {
  const slug = meeting.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "meeting";
  return meeting.date ? `${meeting.date}-${slug}` : slug;
}

/** Hand the text to the browser as a download. */
export function download(text: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
