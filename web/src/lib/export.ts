// The points of a meeting as a file to take elsewhere: CSV for a spreadsheet or tracker import,
// Markdown for a doc, a PR, an issue or a chat message. Built in the browser from what the page
// already shows; nothing leaves the tool except the file the person saves.

import type { Point } from "@/api/types";
import { KIND_ORDER, KIND_TITLE, STATUS_LABEL } from "@/lib/display";

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

function ordered(points: Point[]): Point[] {
  return [...points].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
}

export function pointsToCsv(points: Point[], meeting: ExportMeeting): string {
  const rows = ordered(points).map((p) =>
    [
      p.kind,
      p.text,
      p.owner_text,
      p.owner_email ?? "",
      p.due_text,
      p.due_date ? p.due_date.slice(0, 10) : "",
      STATUS_LABEL[p.status] ?? p.status,
      p.workstream,
      meeting.title,
      meeting.date ?? "",
    ].map(csvCell),
  );
  return [COLUMNS.map(csvCell), ...rows].map((r) => r.join(",")).join("\r\n") + "\r\n";
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

/** One copyable issue title and body per action item. No GitHub connection is needed. */
export function pointsToGithubMarkdown(points: Point[], meeting: ExportMeeting): string {
  const inline = (value: string) => value.replace(/\s+/g, " ").trim();
  const context = `${inline(meeting.title)}${meeting.date ? ` (${meeting.date})` : ""}`;
  return points.filter((p) => p.kind === "action").map((p) => {
    const text = p.text.replace(/\r\n?/g, "\n").trim();
    const title = text.split("\n").find((line) => line.trim())?.trim() || "Untitled action item";
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
