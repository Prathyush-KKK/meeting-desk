import { describe, expect, it } from "vitest";

import { cuesToText, uploadText } from "@/lib/transcript";

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
    expect(() => uploadText("notes.docx", "PK...")).toThrow(/can't be read/);
    expect(() => uploadText("empty.txt", "  \n")).toThrow(/no text/);
  });
});
