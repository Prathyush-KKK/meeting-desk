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
    for (const variant of [".sel-tint", ".sel-soft", ".sel-outline", ".sel-strike", ".sel-anchor"]) {
      expect(css).toContain(variant);
    }
    expect(css).toMatch(/\.sel-anchor\s*\{\s*outline: 2px solid hsl\(var\(--sel\)\);/);
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

// Screen review round 1. These are rules of the whole app, so like the palette above they are read
// from the source: a component test can only prove the component it renders.
describe("the screen review's app-wide rules", () => {
  const files = sources();

  it("draws no shadows: 1 px borders only (R1-27)", () => {
    const shadow = /(?<![\w-])shadow(?:-(?:sm|md|lg|xl|2xl|inner))?(?![\w-])/;
    const offenders = files
      .filter((f) => /\.tsx?$/.test(f))
      .filter((f) => shadow.test(readFileSync(f, "utf8").replace(/\/\/.*$/gm, "")))
      .map((f) => path.relative(SRC, f));
    expect(offenders).toEqual([]);
    expect(css).toMatch(/\[data-sonner-toast\]\s*\{\s*box-shadow:\s*none !important;/);
  });

  it("gives every focus ring the foreground colour, not the browser's (R1-08)", () => {
    expect(css).toMatch(/:focus-visible\s*\{\s*outline:\s*2px solid hsl\(var\(--ring\)\);/);
  });

  it("makes every control at least 44 px on a phone (R1-07)", () => {
    const phone = css.slice(css.indexOf("@media (max-width: 767.98px)"));
    expect(phone).toContain("min-height: 44px");
    expect(phone).toMatch(/:has\(> svg:only-child\)\s*\{\s*min-width: 44px;/);
    expect(phone).toMatch(/\[role="checkbox"\]::after\s*\{[^}]*inset: -14px -8px;/);
  });

  it("applies hover styles only where a pointer can hover (R1-28)", () => {
    const config = readFileSync(path.join(SRC, "..", "tailwind.config.js"), "utf8");
    expect(config).toMatch(/hoverOnlyWhenSupported:\s*true/);
  });

  it("tints the grid more strongly in the dark, where 14 % disappears (R1-35)", () => {
    expect(css).toContain("background-color: hsl(var(--sel) / var(--sel-tint-alpha));");
    const alphas = [...css.matchAll(/--sel-tint-alpha:\s*([\d.]+)/g)].map((m) => Number(m[1]));
    expect(alphas).toEqual([0.14, 0.3, 0.3]);
  });
});
