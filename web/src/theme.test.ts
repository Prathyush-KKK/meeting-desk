// Review 1, finding 29: "Five hues in play. Fix: collapse to one hue with tint/outline variants;
// text legend."
//
// A component test can only prove the component it renders. The finding is about the whole app, so
// this one reads the source: the palette may define exactly one coloured token beyond the delete
// affordance, and no file may reach for a token that is gone. It is the cheapest thing that fails
// when somebody reintroduces an amber warning six months from now.

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = import.meta.dirname;

function sources(dir = SRC): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

const css = readFileSync(path.join(SRC, "index.css"), "utf8");

/** `--name: H S% L%;` - the shape every token in index.css is written in. */
const TOKENS = [...css.matchAll(/(--[a-z-]+):\s*(\d+)\s+(\d+)%\s+(\d+)%/g)].map((m) => ({
  name: m[1],
  saturation: Number(m[3]),
}));

describe("the palette", () => {
  it("has exactly one coloured token beyond the delete affordance", () => {
    const coloured = [...new Set(TOKENS.filter((t) => t.saturation > 0).map((t) => t.name))].sort();
    expect(coloured).toEqual(["--destructive", "--sel"]);
  });

  it("still defines the neutrals and the one selection hue in every theme", () => {
    // light, .dark/[data-theme=dark], and the prefers-color-scheme block.
    expect(css.match(/--sel:/g)).toHaveLength(3);
    expect(css.match(/--background:/g)).toHaveLength(3);
  });

  it("no longer defines the hues the review counted", () => {
    for (const gone of ["--ok", "--warn", "--bad", "--grid-new", "--grid-key", "--grid-conflict", "--grid-anchor"]) {
      expect(css).not.toContain(`${gone}:`);
      expect(css).not.toContain(`${gone}-soft:`);
    }
  });

  it("carries the three grid variants, so the grid and the legend cannot drift", () => {
    for (const variant of [".sel-tint", ".sel-soft", ".sel-outline", ".sel-strike"]) {
      expect(css).toContain(variant);
    }
  });
});

describe("the app's classes", () => {
  const files = sources();

  it("scans every source file", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it("uses no class built on a hue that is gone", () => {
    const banned = /\b(?:text|bg|border|outline|decoration|ring|fill)-(?:ok|warn|bad|grid-(?:new|key|conflict|anchor))\b/;
    const offenders = files
      .filter((f) => f !== path.join(SRC, "index.css"))
      .filter((f) => banned.test(readFileSync(f, "utf8")))
      .map((f) => path.relative(SRC, f));
    expect(offenders).toEqual([]);
  });

  it("spends the destructive colour only on the two things that delete something", () => {
    const wearers = files
      .filter((f) => !f.includes(`${path.sep}ui${path.sep}`))
      .filter((f) => /\btext-destructive\b/.test(readFileSync(f, "utf8")))
      .map((f) => path.relative(SRC, f).replaceAll(path.sep, "/"))
      .sort();
    // Remove a point, and delete a manual meeting. Disconnecting a workbook or taking an email off
    // the allow-list removes access, not content, and stays neutral.
    expect(wearers).toEqual(["components/PointRow.tsx", "pages/MeetingStep.tsx"]);
  });

  it("gives native radios and ticks the selection hue rather than the browser's", () => {
    expect(css).toContain("accent-color: hsl(var(--sel))");
  });

  it("keeps the tailwind palette down to the neutrals, the selection hue and destructive", () => {
    const config = readFileSync(path.join(SRC, "..", "tailwind.config.js"), "utf8");
    for (const gone of ["--ok", "--warn", "--bad", "--grid-new", "--grid-key", "--grid-conflict", "--grid-anchor"]) {
      expect(config).not.toContain(gone);
    }
    expect(config).toContain("hsl(var(--sel))");
    expect(config).toContain("hsl(var(--destructive))");
  });
});
