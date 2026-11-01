import { describe, expect, it } from "vitest";

import { cuesToText, docxText, readUpload, speakerTurnsToText, uploadText } from "@/lib/transcript";

const VTT = `WEBVTT

NOTE recorded by Meet

1
00:00:00.000 --> 00:00:04.000
<v Alex S>Let's start with uploads.</v>

2
00:00:04.000 --> 00:00:07.500
<v Alex S>The flag is on staging.</v>

00:00:08.000 --> 00:00:12.000
<v.loud Daniel Okafor>I'll mirror the rates feed by 3 Oct &amp; report back.</v>
`;

const SRT = `1
00:00:01,000 --> 00:00:03,000
Noah: Decided, the owner is one person.

2
00:00:03,500 --> 00:00:06,000
Noah: <i>Risk:</i> the flag has no rollback plan.
`;

describe("cuesToText", () => {
  it("keeps who said what, drops timings, ids and notes, and joins a speaker's split cues", () => {
    expect(cuesToText(VTT)).toBe(
      "Alex S: Let's start with uploads. The flag is on staging.\nDaniel Okafor: I'll mirror the rates feed by 3 Oct & report back.",
    );
  });

  it("reads SubRip too", () => {
    expect(cuesToText(SRT)).toBe("Noah: Decided, the owner is one person. Risk: the flag has no rollback plan.");
  });
});

describe("uploadText", () => {
  it("passes plain text and Markdown through", () => {
    expect(uploadText("notes.md", "## Next steps\r\n- Alex: ship it\r\n")).toBe("## Next steps\n- Alex: ship it");
  });

  it("refuses formats it cannot read and empty files", () => {
    expect(() => uploadText("notes.doc", "...")).toThrow(/can't be read/);
    expect(() => uploadText("notes.pdf", "%PDF")).toThrow(/\.docx/);
    expect(() => uploadText("empty.txt", "  \n")).toThrow(/no text/);
  });

  it("turns a Zoom or Teams .txt transcript into speaker lines", () => {
    expect(uploadText("transcript.txt", ZOOM)).toBe(ZOOM_TEXT);
  });

  it("leaves Markdown alone even when it has speaker-like lines", () => {
    const md = "Standup 9:30\n- uploads\nRetro 10:30\n- rates";
    expect(uploadText("agenda.md", md)).toBe(md);
  });
});

const ZOOM = `[Alex S] 10:02:15
Let's start with uploads.

[Alex S] 10:02:21
The flag is on staging.

[Daniel Okafor] 10:02:30
I'll mirror the rates feed by 3 Oct.
`;
const ZOOM_TEXT =
  "Alex S: Let's start with uploads. The flag is on staging.\nDaniel Okafor: I'll mirror the rates feed by 3 Oct.";

const TEAMS = `Vendor call with Maya-20261020_100000-Meeting Recording
October 20, 2026, 10:00AM
32m 10s

Maya Patel started transcription

Maya Patel   0:03
Shall we go through the questionnaire?

Alex S\t0:09
Yes. I'll send it by Friday.
And the security answers with it.

Maya Patel   1:02:15
Great, thanks.

Maya Patel stopped transcription
`;

describe("speakerTurnsToText", () => {
  it("reads Teams' layout: keeps the title lines, drops the transcription notices", () => {
    expect(speakerTurnsToText(TEAMS)).toBe(
      [
        "Vendor call with Maya-20261020_100000-Meeting Recording",
        "October 20, 2026, 10:00AM",
        "32m 10s",
        "Maya Patel: Shall we go through the questionnaire?",
        "Alex S: Yes. I'll send it by Friday. And the security answers with it.",
        "Maya Patel: Great, thanks.",
      ].join("\n"),
    );
  });

  it("is not fooled by notes: one heading, labels with colons and times first are not turns", () => {
    expect(speakerTurnsToText("Alex S 10:02\nsome words")).toBeNull();
    expect(speakerTurnsToText("Agenda: 10:30\nitem\nLunch: 12:00\nitem")).toBeNull();
    expect(speakerTurnsToText("9:30 standup\nitem\n10:30 retro\nitem")).toBeNull();
  });
});

// --- .docx: a real zip around a Word body, built here so the test needs no fixture file --------------

async function deflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new CompressionStream("deflate-raw");
  const writer = stream.writable.getWriter();
  void writer.write(data as Uint8Array<ArrayBuffer>).then(() => writer.close());
  const chunks: Uint8Array[] = [];
  const reader = stream.readable.getReader();
  for (let read = await reader.read(); !read.done; read = await reader.read()) chunks.push(read.value);
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  chunks.reduce((offset, c) => (out.set(c, offset), offset + c.length), 0);
  return out;
}

/** A minimal zip: local headers, the central directory, the end record. CRCs are left 0. */
async function zip(files: Record<string, string>, deflate = true): Promise<Uint8Array> {
  const utf8 = new TextEncoder();
  const locals: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const raw = utf8.encode(text);
    const data = deflate ? await deflateRaw(raw) : raw;
    const nameBytes = utf8.encode(name);
    const local = new Uint8Array(30 + nameBytes.length + data.length);
    const l = new DataView(local.buffer);
    l.setUint32(0, 0x04034b50, true);
    l.setUint16(8, deflate ? 8 : 0, true);
    l.setUint32(18, data.length, true);
    l.setUint32(22, raw.length, true);
    l.setUint16(26, nameBytes.length, true);
    local.set(nameBytes, 30);
    local.set(data, 30 + nameBytes.length);
    const central = new Uint8Array(46 + nameBytes.length);
    const c = new DataView(central.buffer);
    c.setUint32(0, 0x02014b50, true);
    c.setUint16(10, deflate ? 8 : 0, true);
    c.setUint32(20, data.length, true);
    c.setUint32(24, raw.length, true);
    c.setUint16(28, nameBytes.length, true);
    c.setUint32(42, offset, true);
    central.set(nameBytes, 46);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const directorySize = centrals.reduce((n, c) => n + c.length, 0);
  const end = new Uint8Array(22);
  const e = new DataView(end.buffer);
  e.setUint32(0, 0x06054b50, true);
  e.setUint16(8, centrals.length, true);
  e.setUint16(10, centrals.length, true);
  e.setUint32(12, directorySize, true);
  e.setUint32(16, offset, true);
  const parts = [...locals, ...centrals, end];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  parts.reduce((at, p) => (out.set(p, at), at + p.length), 0);
  return out;
}

const run = (text: string) => `<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">${text}</w:t></w:r>`;
const WORD_BODY = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p>${run("Maya Patel")}<w:r><w:tab/></w:r>${run("0:03")}</w:p>
<w:p>${run("Shall we go through the ")}${run("questionnaire &amp; the &lt;security&gt; answers?")}</w:p>
<w:p>${run("Alex S")}<w:r><w:tab/></w:r>${run("0:09")}</w:p>
<w:p>${run("Yes, by Friday.")}<w:r><w:br/></w:r>${run("I'll send both.")}</w:p>
<w:sectPr/></w:body></w:document>`;

describe("docxText", () => {
  it("reads the paragraphs, tabs and line breaks of a deflated Word body", async () => {
    const bytes = await zip({ "[Content_Types].xml": "<Types/>", "word/document.xml": WORD_BODY });
    expect(await docxText(bytes)).toBe(
      "Maya Patel\t0:03\nShall we go through the questionnaire & the <security> answers?\nAlex S\t0:09\nYes, by Friday.\nI'll send both.\n",
    );
  });

  it("reads a stored (uncompressed) entry too", async () => {
    const bytes = await zip({ "word/document.xml": WORD_BODY }, false);
    expect(await docxText(bytes)).toContain("Alex S\t0:09");
  });
});

describe("readUpload", () => {
  it("turns a Teams .docx transcript into speaker lines", async () => {
    const bytes = await zip({ "word/document.xml": WORD_BODY });
    const file = new File([bytes as Uint8Array<ArrayBuffer>], "Vendor call.docx");
    expect(await readUpload(file)).toBe(
      "Maya Patel: Shall we go through the questionnaire & the <security> answers?\nAlex S: Yes, by Friday. I'll send both.",
    );
  });

  it("says so when a .docx is not a Word file, or has no body", async () => {
    await expect(readUpload(new File(["just text"], "renamed.docx"))).rejects.toThrow(/could not be read as a Word document/);
    const empty = await zip({ "word/styles.xml": "<w:styles/>" });
    await expect(readUpload(new File([empty as Uint8Array<ArrayBuffer>], "odd.docx"))).rejects.toThrow(/could not be read/);
  });

  it("reads text files as before", async () => {
    expect(await readUpload(new File([ZOOM], "zoom.txt"))).toBe(ZOOM_TEXT);
  });
});
