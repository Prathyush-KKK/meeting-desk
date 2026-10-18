// Turning an uploaded transcript or notes file into the plain text a pasted note would be.
// WebVTT (Google Meet, Zoom, Teams) and SubRip lose their cue numbers and timings and keep who
// said what; plain text and Markdown pass through as they are.

export const UPLOAD_ACCEPT = ".txt,.md,.markdown,.vtt,.srt,text/plain,text/markdown,text/vtt";
export const UPLOAD_MAX_BYTES = 2 * 1024 * 1024;

const TIMING_RE = /^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s+-->\s+(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}/;
const VOICE_RE = /<v(?:\.[^\s>]+)?\s+([^>]+)>/g;
const TAG_RE = /<\/?[^>]+>/g;

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"');
}

/** The spoken lines of a WebVTT or SubRip file, one per cue, "Speaker: words" where it says. */
export function cuesToText(raw: string): string {
  const blocks = raw.replace(/\r\n?/g, "\n").split(/\n{2,}/);
  const lines: string[] = [];
  for (const block of blocks) {
    const rows = block.split("\n").map((r) => r.trim()).filter(Boolean);
    const timing = rows.findIndex((r) => TIMING_RE.test(r));
    if (timing === -1) continue; // the WEBVTT header, NOTE, STYLE and REGION blocks
    const text = rows
      .slice(timing + 1)
      .join(" ")
      .replace(VOICE_RE, (_m, speaker: string) => `${speaker.trim()}: `)
      .replace(TAG_RE, "");
    const clean = decodeEntities(text).replace(/\s+/g, " ").trim();
    if (!clean) continue;
    // Captioners split one sentence across cues; the same speaker's next cue joins the line.
    const previous = lines[lines.length - 1];
    const speaker = clean.match(/^([^:]{1,60}):\s/)?.[1];
    if (previous && speaker && previous.startsWith(`${speaker}: `)) {
      lines[lines.length - 1] = `${previous} ${clean.slice(speaker.length + 2)}`;
    } else {
      lines.push(clean);
    }
  }
  return lines.join("\n");
}

export function isCueFile(name: string, raw: string): boolean {
  return /\.(vtt|srt)$/i.test(name) || raw.trimStart().startsWith("WEBVTT");
}

/** The note text for an uploaded file; throws with a message the UI can show. */
export function uploadText(name: string, raw: string): string {
  if (/\.(docx?|pdf|rtf|pages)$/i.test(name)) {
    throw new Error("That file type can't be read here. Upload .txt, .md, .vtt or .srt, or paste the text.");
  }
  const text = isCueFile(name, raw) ? cuesToText(raw) : raw.replace(/\r\n?/g, "\n").trim();
  if (!text) throw new Error(`${name} has no text in it.`);
  return text;
}
