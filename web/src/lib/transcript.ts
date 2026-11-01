// Turning an uploaded transcript or notes file into the plain text a pasted note would be.
// WebVTT (Google Meet, Zoom, Teams) and SubRip lose their cue numbers and timings and keep who
// said what. So do the plain-text transcripts Zoom and Teams save, where each turn starts with a
// "speaker + timestamp" line, and Teams' .docx download, which is read here in the browser.
// Markdown, and plain text without speaker lines, pass through as they are.

export const UPLOAD_ACCEPT =
  ".txt,.md,.markdown,.vtt,.srt,.docx,text/plain,text/markdown,text/vtt," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export const UPLOAD_MAX_BYTES = 2 * 1024 * 1024;

const TIMING_RE = /^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s+-->\s+(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}/;
const VOICE_RE = /<v(?:\.[^\s>]+)?\s+([^>]+)>/g;
const TAG_RE = /<\/?[^>]+>/g;
// A turn's heading on a line of its own: Zoom's "[Alex S] 10:02:15", Teams' "Alex S   0:03".
// The name has no colon and does not start with a digit, so "Agenda: 10:30" and "9:30 standup"
// are not headings.
const SPEAKER_HEADING_RE = /^\[?([^\]\d:\s][^\]:]{0,59}?)\]?[ \t]+(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?$/;
const TRANSCRIPTION_NOTICE_RE = /^.{1,80}\s(started|stopped) transcription\.?$/i;
const READABLE_FORMATS = "Upload .txt, .md, .vtt, .srt or .docx, or paste the text.";

function decodeEntities(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&");
}

/** Appends "Speaker: words", joining it to the line before when the same speaker carries on. */
function pushTurn(lines: string[], speaker: string | undefined, words: string): void {
  const text = words.replace(/\s+/g, " ").trim();
  if (!text) return;
  const previous = lines[lines.length - 1];
  if (speaker && previous?.startsWith(`${speaker}: `)) {
    lines[lines.length - 1] = `${previous} ${text}`;
  } else {
    lines.push(speaker ? `${speaker}: ${text}` : text);
  }
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
    // Captioners split one sentence across cues; the same speaker's next cue joins the line.
    const speaker = clean.match(/^([^:]{1,60}):\s/)?.[1];
    pushTurn(lines, speaker, speaker ? clean.slice(speaker.length + 2) : clean);
  }
  return lines.join("\n");
}

/**
 * A Zoom or Teams plain-text transcript as "Speaker: words" lines, or null when the text has
 * fewer than two speaker headings and so is not one. Lines before the first heading (Teams puts
 * the meeting title, date and length there) are kept as they are.
 */
export function speakerTurnsToText(raw: string): string | null {
  const rows = raw.replace(/\r\n?/g, "\n").split("\n").map((r) => r.trim());
  if (rows.filter((r) => SPEAKER_HEADING_RE.test(r)).length < 2) return null;
  const lines: string[] = [];
  let speaker: string | undefined;
  let words: string[] = [];
  for (const row of rows) {
    const heading = row.match(SPEAKER_HEADING_RE);
    if (heading) {
      pushTurn(lines, speaker, words.join(" "));
      speaker = heading[1].trim();
      words = [];
    } else if (!row || TRANSCRIPTION_NOTICE_RE.test(row)) {
      continue;
    } else if (speaker) {
      words.push(row);
    } else {
      lines.push(row); // the preamble, line by line
    }
  }
  pushTurn(lines, speaker, words.join(" "));
  return lines.join("\n");
}

export function isCueFile(name: string, raw: string): boolean {
  return /\.(vtt|srt)$/i.test(name) || raw.trimStart().startsWith("WEBVTT");
}

/** The note text for an uploaded file's text; throws with a message the UI can show. */
export function uploadText(name: string, raw: string): string {
  if (/\.(doc|pdf|rtf|pages|odt)$/i.test(name)) {
    throw new Error(`That file type can't be read here. ${READABLE_FORMATS}`);
  }
  const plain = raw.replace(/\r\n?/g, "\n");
  const text = isCueFile(name, plain)
    ? cuesToText(plain)
    : /\.(md|markdown)$/i.test(name)
      ? plain.trim()
      : (speakerTurnsToText(plain) ?? plain.trim());
  if (!text) throw new Error(`${name} has no text in it.`);
  return text;
}

/** The note text for an uploaded file: .docx is unpacked here, everything else is read as text. */
export async function readUpload(file: File): Promise<string> {
  if (!/\.docx$/i.test(file.name)) return uploadText(file.name, await file.text());
  let text: string;
  try {
    text = await docxText(new Uint8Array(await file.arrayBuffer()));
  } catch (error) {
    if (error instanceof NoInflate) throw new Error(`This browser can't open .docx files. ${READABLE_FORMATS}`);
    throw new Error(`${file.name} could not be read as a Word document. ${READABLE_FORMATS}`);
  }
  return uploadText(file.name, text);
}

// --- .docx -------------------------------------------------------------------------------------------

class NoInflate extends Error {}

/**
 * The paragraphs of a .docx, one per line, with its tabs. Teams' transcript download is a Word
 * file; reading word/document.xml out of the zip in the browser keeps the file on this machine
 * and needs no library: the zip directory is parsed here and the browser inflates the entry.
 */
export async function docxText(bytes: Uint8Array): Promise<string> {
  const xml = await zipEntry(bytes, "word/document.xml");
  const token = /<w:t(?:\s[^>]*)?>([^<]*)<\/w:t>|<w:tab\s*\/>|<w:(?:br|cr)\s*\/>|<\/w:p>/g;
  let out = "";
  for (const match of xml.matchAll(token)) {
    const tag = match[0];
    if (match[1] !== undefined) out += decodeEntities(match[1]);
    else if (tag.startsWith("<w:tab")) out += "\t";
    else out += "\n";
  }
  return out;
}

async function zipEntry(bytes: Uint8Array, name: string): Promise<string> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  // The end-of-central-directory record: the last 22 bytes, unless a comment follows it.
  let end = -1;
  for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 22 - 0xffff); at--) {
    if (view.getUint32(at, true) === 0x06054b50) {
      end = at;
      break;
    }
  }
  if (end < 0) throw new Error("not a zip file");
  const entries = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const utf8 = new TextDecoder();
  for (let n = 0; n < entries && view.getUint32(at, true) === 0x02014b50; n++) {
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const nameLength = view.getUint16(at + 28, true);
    const skip = nameLength + view.getUint16(at + 30, true) + view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    if (utf8.decode(bytes.subarray(at + 46, at + 46 + nameLength)) === name) {
      const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
      const data = bytes.subarray(start, start + size);
      if (method === 0) return utf8.decode(data);
      if (method === 8) return utf8.decode(await inflateRaw(data));
      throw new Error(`unsupported compression ${method}`);
    }
    at += 46 + skip;
  }
  throw new Error(`no ${name}`);
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream !== "function") throw new NoInflate();
  const stream = new DecompressionStream("deflate-raw");
  const writer = stream.writable.getWriter();
  const written = writer.write(data as Uint8Array<ArrayBuffer>).then(() => writer.close());
  const chunks: Uint8Array[] = [];
  const reader = stream.readable.getReader();
  for (let read = await reader.read(); !read.done; read = await reader.read()) chunks.push(read.value);
  await written;
  const out = new Uint8Array(chunks.reduce((total, chunk) => total + chunk.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}
