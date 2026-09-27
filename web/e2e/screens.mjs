// Every screen of the app, photographed at the widths the spec names, for the screen review loop
// (docs/review/SCREENS-REVIEW.md).
//
//   cd api && FAKE_GOOGLE=1 FAKE_LLM=1 AUTH_DEV_USER=... uvicorn app.main:app --port 8000   (fresh DB)
//   cd web && pnpm dev
//   cd web && node e2e/screens.mjs <round>        -> docs/review/shots/round-<round>/*.png
//
// 1280x900 and 390x844 for everything, 768x1024 for the Sheets grid, and a dark pass over Step 3
// and Sheets. Beside the PNGs it writes metrics.json: per screen, how far the page scrolls sideways
// and which tap targets are under 44 px on a phone - the two things a picture hides.
//
// It drives the fake world only: the seed's six meetings and three workbooks, plus one paste in the
// walkthrough's pattern. States the fake cannot reach (an empty calendar, a first-run or an expired
// connection, no workbook, 401, 403) are produced by answering that one route in the browser.

import { chromium } from "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";

const WEB = process.env.E2E_WEB ?? "http://127.0.0.1:5173";
const API = process.env.E2E_API ?? "http://localhost:8000";
const EXECUTABLE = process.env.E2E_CHROMIUM ?? "/opt/pw-browsers/chromium";
const ROUND = process.argv[2] ?? process.env.ROUND ?? "1";
// `node e2e/screens.mjs final` writes the set kept for viewing, docs/review/shots/final.
const OUT = path.resolve(import.meta.dirname, "..", "..", "docs", "review", "shots", ROUND === "final" ? "final" : `round-${ROUND}`);
const STAMP = new Date().toISOString().slice(11, 19).replace(/:/g, "");

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const NOTES = `Vendor call with Madhu ${STAMP}

The Next Steps
Ansul S: Send the Sprinto questionnaire by Friday
Prathyush Kodhanpur: Mirror Open Food Facts before 3 Oct
Shambhavi Singh: Confirm the barcode fallback copy with design by 30 Sep
Decided: the Owner column holds a person, not a team
Risk: the upload flag has no rollback plan
`;
const LONG_TITLE =
  "Quarterly planning with the nutrition, platform and prod ops squads, including the SIApoints discount rules and the household wealth roadmap";

const metrics = [];
const failures = [];
const checks = [];
const counters = new Map();

const api = async (method, route, body) => {
  const response = await fetch(`${API}${route}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${route} -> ${response.status} ${await response.text()}`);
  return response.json();
};

/** Horizontal page overflow, and the tap targets under 44 px (only meaningful on a phone). */
async function measure(page) {
  return page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small = [];
    const seen = new Set();
    for (const el of document.querySelectorAll("button, a[href], select, input:not([type=hidden]), textarea, [role=checkbox]")) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.bottom < 0 || r.top > window.innerHeight) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") continue;
      // A native checkbox or radio inside a 44 px label counts as the label; a Radix tick counts
      // its ::after hit area (index.css), which is what takes the tap.
      const label = el.closest("label");
      const box = label ? label.getBoundingClientRect() : r;
      let height = box.height;
      if (el.getAttribute("role") === "checkbox") {
        const after = getComputedStyle(el, "::after");
        if (after.content !== "none" && after.position === "absolute") height = r.height - 2 * parseFloat(after.top || "0");
      }
      if (height >= 43.5) continue;
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.tagName).trim().slice(0, 40);
      const key = `${name}:${Math.round(box.height)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      small.push(`${name} (${Math.round(box.width)}x${Math.round(box.height)})`);
    }
    // Every scroll container, not only the page: nothing on a phone may scroll sideways but a grid
    // inside its own box (round 4). A text field scrolling its own text is how a field works, so
    // inputs and selects are left out; textareas are in.
    const sideways = [];
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest("[data-rows]")) continue;
      if (el.matches("input, select")) continue;
      const style = getComputedStyle(el);
      if (style.display === "none" || !/(auto|scroll)/.test(style.overflowX)) continue;
      const extra = el.scrollWidth - el.clientWidth;
      if (extra > 1) {
        const id = el.dataset.testid ? `[data-testid=${el.dataset.testid}]` : `${el.tagName.toLowerCase()}.${String(el.className).split(/\s+/).slice(0, 3).join(".")}`;
        sideways.push(`${id} (+${extra}px)`);
      }
    }
    const grids = [...document.querySelectorAll("[data-rows]")].filter((el) => el.scrollWidth > el.clientWidth + 1).length;
    return { overflow, small, sideways, grids };
  });
}

async function shot(page, name, { full = false, toasts = false } = {}) {
  const width = page.viewportSize().width;
  const n = (counters.get(width) ?? 0) + 1;
  counters.set(width, n);
  const file = `${width}-${String(n).padStart(2, "0")}-${name}.png`;
  await page.evaluate((show) => {
    let style = document.getElementById("__shots_toasts");
    if (!style) {
      style = document.createElement("style");
      style.id = "__shots_toasts";
      document.head.appendChild(style);
    }
    style.textContent = show ? "" : "[data-sonner-toaster]{display:none !important}";
  }, toasts);
  await page.waitForTimeout(350);
  await page.screenshot({ path: path.join(OUT, file), fullPage: false });
  if (full) {
    const scrolls = await page.evaluate(() => {
      const main = document.querySelector("main");
      return document.documentElement.scrollHeight > window.innerHeight + 2 || (main && main.scrollHeight > main.clientHeight + 2);
    });
    if (scrolls) {
      // `main` is the scroller from 768 px down; give it its full height for the long shot.
      await page.evaluate(() => {
        const main = document.querySelector("main");
        if (!main) return;
        main.dataset.shotsFull = "1";
        document.getElementById("root").style.height = "auto";
        main.style.overflow = "visible";
        main.style.flex = "none";
        document.documentElement.style.height = "auto";
        document.body.style.height = "auto";
      });
      await page.screenshot({ path: path.join(OUT, file.replace(".png", "-full.png")), fullPage: true });
      await page.evaluate(() => {
        const main = document.querySelector("main");
        if (!main) return;
        document.getElementById("root").style.height = "";
        main.style.overflow = "";
        main.style.flex = "";
        document.documentElement.style.height = "";
        document.body.style.height = "";
      });
    }
  }
  const m = await measure(page);
  metrics.push({
    file,
    width,
    overflow: m.overflow,
    small: width < 768 ? m.small : [],
    sideways: width < 768 ? m.sideways : [],
    gridsScrollingInTheirBox: m.grids,
  });
  const notes = [m.overflow > 0 ? `page scrolls sideways ${m.overflow}px` : "", width < 768 && m.sideways.length ? `sideways: ${m.sideways.join(", ")}` : ""].filter(Boolean);
  console.log(`  ${file}${notes.length ? `  [${notes.join("; ")}]` : ""}`);
}

/** Toasts are hidden for most shots; a step that waits on one has to show them first. */
const showToasts = (page) =>
  page.evaluate(() => {
    const style = document.getElementById("__shots_toasts");
    if (style) style.textContent = "";
  });

async function screen(name, fn) {
  try {
    await fn();
  } catch (error) {
    failures.push(`${name}: ${error.message.split("\n")[0]}`);
    console.log(`  FAIL ${name}: ${error.message.split("\n")[0]}`);
  }
}

async function open(browser, width, height, { dark = false, scale } = {}) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: scale ?? (width < 768 ? 2 : 1),
    colorScheme: dark ? "dark" : "light",
    hasTouch: width < 768,
    isMobile: width < 768,
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.log(`  [page error] ${error.message}`));
  return { context, page };
}

const goto = async (page, query) => {
  await page.goto(`${WEB}/?${query}`, { waitUntil: "domcontentloaded" });
  await page.getByText("Meeting Desk").first().waitFor({ timeout: 20_000 });
};

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: EXECUTABLE });

  // --- the fake world, plus two meetings of our own ------------------------------------------------
  const long = await api("POST", "/meetings/manual", {
    title: LONG_TITLE,
    date: "2026-09-22",
    start: "15:00",
    end: "16:00",
    workstream: "Platform",
    description: "Agenda in the planning doc.",
    attendees: [{ name: "Ansul S", email: "ansul.s@simpleo.ai", response: "accepted" }],
  });
  const list = await api("GET", "/meetings/list");
  const nutrition = list.items.find((m) => m.title === "Nutrition roadmap review");
  const workbook = (await api("GET", "/workbooks")).find((w) => w.name === "Nutrition Sialet Product Roadmap");
  let pasted = null; // the meeting the paste creates

  // ================================================================ 1280, light ====================
  {
    const { context, page } = await open(browser, 1280, 900);
    await screen("step 1 list", async () => {
      await goto(page, "page=capture");
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await shot(page, "step1-list");
    });
    await screen("step 1 detail (calendar)", async () => {
      await page.locator("[data-testid=meeting-row][data-source=calendar]").first().getByLabel("Show meeting details").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-detail-calendar");
      await page.getByTestId("meeting-detail").getByLabel("Close").click();
    });
    await screen("step 1 detail (manual)", async () => {
      await page.locator("[data-testid=meeting-row]", { hasText: "Sprinto call prep" }).getByLabel("Show meeting details").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-detail-manual");
      await page.getByTestId("meeting-detail").getByLabel("Close").click();
    });
    await screen("step 1 manual edit", async () => {
      await page.locator("[data-testid=meeting-row]", { hasText: "Sprinto call prep" }).getByLabel("Edit meeting").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-manual-edit");
      await page.getByTestId("meeting-detail").getByLabel("Close").click();
    });
    await screen("step 1 selected + focus", async () => {
      await page.locator("[data-testid=meeting-row]", { hasText: "Nutrition roadmap review" }).click();
      // Keyboard: from the paste box, Tab lands on the first card.
      await page.locator("#quickpaste").focus();
      await page.keyboard.press("Tab");
      await page.locator("[data-testid=meeting-row]").nth(3).hover();
      await shot(page, "step1-selected-focus-hover");
    });
    await screen("step 1 paste", async () => {
      await goto(page, "page=capture");
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await page.fill("#quickpaste", NOTES);
      await shot(page, "step1-paste");
    });
    await screen("step 1 paste -> step 2", async () => {
      await page.getByRole("button", { name: "Save and continue" }).click();
      await page.getByRole("heading", { name: "Saved notes" }).waitFor({ timeout: 20_000 });
      const meetings = await api("GET", "/meetings/list");
      pasted = meetings.items.find((m) => m.title.startsWith(`Vendor call with Madhu ${STAMP}`));
      await page.fill("#paste", "Follow-up from Slack\nAnsul S: share the Sprinto login with Nishchay by Monday");
      await shot(page, "step2-notes-paste", { full: true });
    });
    await screen("step 2 sources (calendar meeting)", async () => {
      await goto(page, `page=capture&step=notes&meeting=${nutrition.id}`);
      await page.getByRole("heading", { name: "Saved notes" }).waitFor({ timeout: 20_000 });
      await page.getByText("Looking…").waitFor({ state: "detached", timeout: 20_000 }).catch(() => {});
      await shot(page, "step2-sources", { full: true });
    });
    await screen("step 3 points", async () => {
      await goto(page, `page=capture&step=notes&meeting=${pasted.id}`);
      await page.getByRole("button", { name: "Extract points" }).click();
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 30_000 });
      await page.waitForTimeout(600);
      await shot(page, "step3-points", { full: true });
    });
    await screen("step 3 bulk bar in use", async () => {
      await page.getByLabel("Assign selected to").selectOption({ index: 1 });
      await shot(page, "step3-bulk");
      await page.getByLabel("Assign selected to").selectOption({ index: 0 });
    });
    await screen("step 3 see deferred", async () => {
      const row = page.locator("[data-testid=point-row][data-lifecycle=active]").last();
      await row.getByRole("button", { name: "Defer" }).click();
      await page.waitForTimeout(800);
      await page.getByRole("button", { name: "See deferred" }).click();
      await page.locator("[data-testid=point-row][data-lifecycle=deferred]").first().waitFor({ timeout: 10_000 });
      await shot(page, "step3-deferred-open");
      await page.getByRole("button", { name: "Hide deferred" }).click();
    });
    await screen("step 3 remove + undo toast", async () => {
      const row = page.locator("[data-testid=point-row][data-lifecycle=active]", { has: page.locator("input[value*='barcode']") }).first();
      const target = (await row.count()) ? row : page.locator("[data-testid=point-row][data-lifecycle=active]").nth(2);
      await showToasts(page);
      await target.getByLabel("Remove point").locator("visible=true").first().click();
      await page.locator("[data-sonner-toast]", { hasText: "Point removed" }).waitFor({ timeout: 10_000 });
      await shot(page, "step3-removed-undo-toast", { toasts: true });
      await page.locator("[data-sonner-toast]", { hasText: "Point removed" }).getByRole("button", { name: "Undo" }).click();
      await page.waitForTimeout(800);
    });
    await screen("step 4 smart append", async () => {
      await page.locator("button", { hasText: /^Transfer \d+$/ }).first().click();
      await page.locator("button", { hasText: /^Insert \d+ rows and write$/ }).waitFor({ timeout: 20_000 });
      await shot(page, "step4-smart-append", { full: true });
    });
    await screen("step 4 custom fill, no anchor", async () => {
      await page.getByRole("button", { name: "Custom fill" }).click();
      await shot(page, "step4-custom-fill-pick");
    });
    await screen("step 4 custom fill, anchor in header", async () => {
      await page.locator(`[data-cell="${workbook ? 8 : 8},1"]`).click();
      await page.waitForTimeout(600);
      await shot(page, "step4-custom-fill-header-anchor");
    });
    await screen("step 4 custom fill with anchor", async () => {
      await page.locator(`[data-cell="14,1"]`).click();
      await page.waitForTimeout(900);
      await shot(page, "step4-custom-fill-anchor-plan", { full: true });
      await page.getByRole("button", { name: "Smart append" }).click();
    });
    await screen("step 4 prerequisites: no workbook", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/workbooks", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
      await goto(p2, `page=capture&step=transfer&meeting=${pasted.id}`);
      await p2.waitForTimeout(1200);
      await shot(p2, "step4-prereq-no-workbook");
      await p2.close();
    });
    await screen("step 4 reload (ids fall back to the ticked points)", async () => {
      const p2 = await context.newPage();
      await goto(p2, `page=capture&step=transfer&meeting=${pasted.id}`);
      await p2.waitForTimeout(1200);
      await shot(p2, "step4-reload");
      await p2.close();
    });
    await screen("step 1 empty state", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/meetings/list*", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [],
            fetched_at: new Date().toISOString(),
            age_minutes: 4,
            connections: ["prathyush.kodhanpur@simpleo.ai"],
            empty_hint: "No meeting here? Add one, or paste the notes straight into the box above.",
          }),
        }),
      );
      await goto(p2, "page=capture");
      await p2.waitForTimeout(1200);
      await shot(p2, "step1-empty");
      await p2.close();
    });
    await context.close();
  }

  // ================================================================ 390, light =====================
  {
    const { page } = await open(browser, 390, 844);
    await screen("390 step 1 list", async () => {
      await goto(page, "page=capture");
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await shot(page, "step1-list", { full: true });
    });
    await screen("390 step 1 detail overlay", async () => {
      await page.locator("[data-testid=meeting-row][data-source=calendar]").first().getByLabel("Show meeting details").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-detail-overlay");
      await page.goBack();
      await page.getByTestId("meeting-detail").waitFor({ state: "detached", timeout: 5_000 });
    });
    await screen("390 step 1 manual edit overlay", async () => {
      await page.locator("[data-testid=meeting-row]", { hasText: "Sprinto call prep" }).getByLabel("Edit meeting").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-manual-edit-overlay", { full: true });
      await page.goBack();
      await page.getByTestId("meeting-detail").waitFor({ state: "detached", timeout: 5_000 });
    });
    await screen("390 step 1 paste", async () => {
      await page.fill("#quickpaste", NOTES);
      await shot(page, "step1-paste");
      await page.fill("#quickpaste", "");
    });
    await screen("390 step 2", async () => {
      await goto(page, `page=capture&step=notes&meeting=${nutrition.id}`);
      await page.getByRole("heading", { name: "Saved notes" }).waitFor({ timeout: 20_000 });
      await page.waitForTimeout(800);
      await page.fill("#paste", "Follow-up from Slack\nAnsul S: share the Sprinto login with Nishchay by Monday");
      await shot(page, "step2-notes", { full: true });
    });
    await screen("390 step 3", async () => {
      await goto(page, `page=capture&step=points&meeting=${pasted.id}`);
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 20_000 });
      await shot(page, "step3-points", { full: true });
    });
    await screen("390 step 3 deferred", async () => {
      await page.getByRole("button", { name: "See deferred" }).click();
      await page.locator("[data-testid=point-row][data-lifecycle=deferred]").first().waitFor({ timeout: 10_000 });
      await page.locator("[data-testid=point-row][data-lifecycle=deferred]").first().scrollIntoViewIfNeeded();
      await shot(page, "step3-deferred-open");
      await page.getByRole("button", { name: "Hide deferred" }).click();
    });
    await screen("390 point text: caret, growth, autosave", async () => {
      // Round 4, R4-01: the phone's point text is a growing textarea. Typed text stays where it was
      // typed, focus stays, the box grows instead of scrolling, and the debounced save lands.
      const box = page.locator("[data-testid=point-row][data-lifecycle=active]").first().locator("textarea[aria-label=Point]");
      const before = await box.inputValue();
      const h0 = await box.evaluate((el) => el.getBoundingClientRect().height);
      await box.click();
      await page.keyboard.press("End");
      const suffix = " and chase the answers by Tuesday";
      await page.keyboard.type(suffix, { delay: 15 });
      for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowLeft");
      await page.keyboard.type("X");
      const state = await box.evaluate((el) => ({
        value: el.value,
        caret: el.selectionStart,
        focused: el === document.activeElement,
        height: el.getBoundingClientRect().height,
        innerScroll: el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1,
      }));
      const expected = `${before}${suffix}`.slice(0, -5) + "X" + `${before}${suffix}`.slice(-5);
      let saved = false;
      for (let i = 0; i < 40 && !saved; i++) {
        saved = (await api("GET", `/points?meeting_id=${pasted.id}`)).some((p) => p.text === expected);
        if (!saved) await page.waitForTimeout(250);
      }
      const result = {
        check: "390 point text",
        textIntact: state.value === expected,
        caretKept: state.caret === expected.length - 5,
        focused: state.focused,
        grew: `${Math.round(h0)} -> ${Math.round(state.height)} px`,
        innerScroll: state.innerScroll,
        savedToApi: saved,
      };
      checks.push(result);
      console.log(`  check ${JSON.stringify(result)}`);
      if (!result.textIntact || !result.caretKept || !result.focused || result.innerScroll || !saved) {
        throw new Error(`phone point text: ${JSON.stringify(result)}`);
      }
    });
    await screen("390 step 4", async () => {
      await page.locator("button", { hasText: /^Transfer \d+$/ }).first().click();
      await page.locator("button", { hasText: /^Insert \d+ rows and write$/ }).waitFor({ timeout: 20_000 });
      await shot(page, "step4-smart-append", { full: true });
    });
    await screen("390 step 4 custom fill", async () => {
      await page.getByRole("button", { name: "Custom fill" }).click();
      await page.locator(`[data-cell="14,1"]`).click();
      await page.waitForTimeout(900);
      await shot(page, "step4-custom-fill-anchor", { full: true });
    });
    await page.context().close();
  }

  // ================================================================ the write, then Sheets at 1280 =
  {
    const { context, page } = await open(browser, 1280, 900);
    await screen("step 4 write", async () => {
      await goto(page, `page=capture&step=points&meeting=${pasted.id}`);
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 20_000 });
      await page.locator("button", { hasText: /^Transfer \d+$/ }).first().click();
      const write = page.locator("button", { hasText: /^Insert \d+ rows and write$/ });
      await write.waitFor({ timeout: 20_000 });
      await showToasts(page);
      await write.click();
      await page.getByRole("heading", { name: "Sheets" }).waitFor({ timeout: 30_000 });
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await shot(page, "sheets-after-transfer-toast", { toasts: true });
    });
    await screen("sheets registry + live tab", async () => {
      await goto(page, `page=sheets&wb=${workbook.id}&tab=t1`);
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await shot(page, "sheets-registry-grid", { full: true });
    });
    await screen("sheets filter + search", async () => {
      await page.getByRole("button", { name: "Open", exact: true }).click();
      await page.fill("#sheetq", "Prathyush");
      await shot(page, "sheets-filter-search");
      await page.fill("#sheetq", "");
      await page.getByRole("button", { name: "All", exact: true }).click();
    });
    await screen("sheets staged edit", async () => {
      await page.locator(`[data-cell="13,6"]`).click();
      await page.locator(`[data-cell="13,6"] select`).selectOption("in progress");
      await page.getByText("1 unsaved").waitFor({ timeout: 10_000 });
      await page.locator(`[data-cell="14,2"]`).click();
      await shot(page, "sheets-staged-edit");
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Discard" }).click();
    });
    await screen("sheets add row after table", async () => {
      await page.getByTestId("add-row-toggle").click();
      await page.getByTestId("add-row-panel").waitFor();
      await shot(page, "sheets-addrow-after-table", { full: true });
    });
    await screen("sheets add row above row", async () => {
      await page.locator(`th[data-row="11"]`).click();
      await page.getByText("Above row 12").waitFor({ timeout: 5_000 });
      await page.fill("#addrow-1", "Runbook for the upload flag");
      await shot(page, "sheets-addrow-above-row", { full: true });
    });
    await screen("sheets add row from a point", async () => {
      await page.getByText("From a point").click();
      await page.waitForTimeout(800);
      await shot(page, "sheets-addrow-from-point");
      await page.getByTestId("add-row-toggle").click();
    });
    await screen("sheets key cell says why", async () => {
      await showToasts(page);
      await page.locator(`[data-cell="12,0"]`).click();
      await page.locator("[data-sonner-toast]", { hasText: "key column" }).first().waitFor({ timeout: 5_000 });
      await shot(page, "sheets-key-cell-explains", { toasts: true });
    });
    await screen("sheets no match", async () => {
      await page.fill("#sheetq", "no such task anywhere");
      await shot(page, "sheets-no-match");
      await page.fill("#sheetq", "");
    });
    await screen("member sees the banner", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/auth/me", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: "u-2", email: "nishchay.s@simpleo.ai", name: "Nishchay S", role: "member", is_admin: false }),
        }),
      );
      await p2.route("**/api/admin/connections/status", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            banner: "Google connection needs reconnecting: ansul.s@simpleo.ai. Paste, points and manual meetings keep working.",
            first_run: false,
            first_run_notice: "",
            can_connect: false,
          }),
        }),
      );
      await goto(p2, "page=capture");
      await p2.getByTestId("connection-banner").waitFor({ timeout: 10_000 });
      await shot(p2, "member-reconnect-banner");
      await goto(p2, "page=admin");
      await p2.getByTestId("admin-members-notice").waitFor({ timeout: 10_000 });
      await shot(p2, "member-admin-page");
      await p2.close();
    });
    await screen("sheets empty registry", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/workbooks", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
      await goto(p2, "page=sheets");
      await p2.waitForTimeout(1200);
      await shot(p2, "sheets-no-workbook");
      await p2.close();
    });
    await screen("admin", async () => {
      await goto(page, "page=admin");
      await page.getByRole("heading", { name: "Activity" }).waitFor({ timeout: 20_000 });
      await page.waitForTimeout(600);
      await shot(page, "admin", { full: true });
    });
    await screen("admin first run", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/admin/connections/status", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            banner: "",
            first_run: true,
            first_run_notice: "No Google account is connected yet, so the calendar, Notes by Gemini and Sheets are off. Connect yours to switch them on.",
            can_connect: true,
          }),
        }),
      );
      await p2.route("**/api/admin/connections", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            connections: [],
            warning: "Only one Google account is connected. Connect a second so reads keep working if one expires.",
            banner: "",
            first_run: true,
            first_run_notice: "No Google account is connected yet, so the calendar, Notes by Gemini and Sheets are off. Connect yours to switch them on.",
          }),
        }),
      );
      await goto(p2, "page=admin");
      await p2.getByTestId("first-run-banner").waitFor({ timeout: 10_000 });
      await shot(p2, "admin-first-run-banner");
      await goto(p2, "page=capture");
      await p2.waitForTimeout(1000);
      await shot(p2, "step1-first-run-banner");
      await p2.close();
    });
    await screen("admin reconnect", async () => {
      const p2 = await context.newPage();
      const real = await api("GET", "/admin/connections");
      real.connections[1] = { ...real.connections[1], status: "expired", last_error: "invalid_grant" };
      real.banner = `Google connection needs reconnecting: ${real.connections[1].email}. Paste, points and manual meetings keep working.`;
      await p2.route("**/api/admin/connections", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(real) }),
      );
      await p2.route("**/api/admin/connections/status", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ banner: real.banner, first_run: false, first_run_notice: "", can_connect: true }),
        }),
      );
      await goto(p2, "page=admin");
      await p2.getByTestId("connection-banner").waitFor({ timeout: 10_000 });
      await shot(p2, "admin-reconnect-banner");
      await goto(p2, "page=sheets");
      await p2.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await shot(p2, "sheets-reconnect-banner");
      await p2.close();
    });
    await screen("401 and 403", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/auth/me", (route) =>
        route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Sign in with Google to continue." }) }),
      );
      await p2.goto(WEB, { waitUntil: "domcontentloaded" });
      await p2.getByRole("link", { name: "Sign in with Google" }).waitFor({ timeout: 20_000 });
      await shot(p2, "signin-401");
      await p2.unroute("**/api/auth/me");
      await p2.route("**/api/auth/me", (route) =>
        route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "This Google account is not on the Meeting Desk allow-list. Ask an admin to add it: prathyush.kodhanpur@simpleo.ai." }),
        }),
      );
      await p2.reload({ waitUntil: "domcontentloaded" });
      await p2.getByRole("heading", { name: "Not on the list" }).waitFor({ timeout: 20_000 });
      await shot(p2, "not-on-list-403");
      await p2.close();
    });
    await context.close();
  }

  // ================================================================ 390, Sheets and the rest =======
  {
    const { context, page } = await open(browser, 390, 844);
    await screen("390 sheets select + grid", async () => {
      await goto(page, `page=sheets&wb=${workbook.id}&tab=t1`);
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await shot(page, "sheets-select-grid", { full: true });
    });
    await screen("390 sheets grid scrolled", async () => {
      await page.evaluate(() => {
        const box = document.querySelector("[data-rows]");
        box.scrollLeft = 400;
        box.scrollTop = 120;
      });
      await shot(page, "sheets-grid-scrolled-sticky");
      await page.evaluate(() => {
        const box = document.querySelector("[data-rows]");
        box.scrollLeft = 0;
        box.scrollTop = 0;
      });
    });
    await screen("390 sheets bottom editor", async () => {
      await page.locator(`[data-cell="13,2"]`).click();
      await page.getByTestId("cell-editor").waitFor({ timeout: 10_000 });
      await shot(page, "sheets-bottom-editor");
      await page.getByTestId("cell-editor").getByRole("button", { name: "Cancel" }).click();
    });
    await screen("390 sheets bottom editor (dropdown)", async () => {
      await page.locator(`[data-cell="13,6"]`).click();
      await page.getByTestId("cell-editor").waitFor({ timeout: 10_000 });
      await page.getByTestId("cell-editor").locator("select").selectOption("blocked");
      await page.getByTestId("cell-editor").getByRole("button", { name: "Save" }).click();
      await page.getByText("1 unsaved").waitFor({ timeout: 10_000 });
      await page.getByTestId("save-bar").scrollIntoViewIfNeeded();
      await shot(page, "sheets-staged-edit");
      await page.getByRole("button", { name: "Discard" }).click();
    });
    await screen("390 sheets add row", async () => {
      await page.getByTestId("add-row-toggle").click();
      await page.getByTestId("add-row-panel").waitFor();
      await page.locator(`th[data-row="11"]`).click();
      await page.getByTestId("add-row-panel").scrollIntoViewIfNeeded();
      await shot(page, "sheets-addrow-above-row", { full: true });
      await page.getByTestId("add-row-toggle").click();
    });
    await screen("390 admin", async () => {
      await goto(page, "page=admin");
      await page.getByRole("heading", { name: "Activity" }).waitFor({ timeout: 20_000 });
      await page.waitForTimeout(600);
      await shot(page, "admin", { full: true });
    });
    await screen("390 admin reconnect banner", async () => {
      const p2 = await context.newPage();
      const real = await api("GET", "/admin/connections");
      real.connections[1] = { ...real.connections[1], status: "expired", last_error: "invalid_grant" };
      real.banner = `Google connection needs reconnecting: ${real.connections[1].email}. Paste, points and manual meetings keep working.`;
      await p2.route("**/api/admin/connections", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(real) }),
      );
      await p2.route("**/api/admin/connections/status", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ banner: real.banner, first_run: false, first_run_notice: "", can_connect: true }),
        }),
      );
      await goto(p2, "page=capture");
      await p2.getByTestId("connection-banner").waitFor({ timeout: 10_000 });
      await shot(p2, "step1-reconnect-banner");
      await p2.close();
    });
    await screen("390 401 and 403", async () => {
      const p2 = await context.newPage();
      await p2.route("**/api/auth/me", (route) =>
        route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Sign in with Google to continue." }) }),
      );
      await p2.goto(WEB, { waitUntil: "domcontentloaded" });
      await p2.getByRole("link", { name: "Sign in with Google" }).waitFor({ timeout: 20_000 });
      await shot(p2, "signin-401");
      await p2.unroute("**/api/auth/me");
      await p2.route("**/api/auth/me", (route) =>
        route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "This Google account is not on the Meeting Desk allow-list. Ask an admin to add it: prathyush.kodhanpur@simpleo.ai." }),
        }),
      );
      await p2.reload({ waitUntil: "domcontentloaded" });
      await p2.getByRole("heading", { name: "Not on the list" }).waitFor({ timeout: 20_000 });
      await shot(p2, "not-on-list-403");
      await p2.close();
    });
    await context.close();
  }

  // ================================================================ 768, the Sheets grid ===========
  {
    const { context, page } = await open(browser, 768, 1024, { scale: 1 });
    await screen("768 sheets", async () => {
      await goto(page, `page=sheets&wb=${workbook.id}&tab=t1`);
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await shot(page, "sheets-grid");
    });
    await screen("768 step 1", async () => {
      await goto(page, "page=capture");
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await page.locator("[data-testid=meeting-row][data-source=calendar]").first().getByLabel("Show meeting details").click();
      await page.getByTestId("meeting-detail").waitFor();
      await shot(page, "step1-detail");
    });
    await context.close();
  }

  // ================================================================ dark ============================
  {
    const { context, page } = await open(browser, 1280, 900, { dark: true });
    await screen("dark step 3", async () => {
      await goto(page, `page=capture&step=points&meeting=${nutrition.id}`);
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 20_000 });
      await shot(page, "dark-step3-points");
    });
    await screen("dark step 1", async () => {
      await goto(page, "page=capture");
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await page.locator("[data-testid=meeting-row][data-source=calendar]").first().getByLabel("Show meeting details").click();
      await shot(page, "dark-step1-detail");
    });
    await screen("dark sheets", async () => {
      await goto(page, `page=sheets&wb=${workbook.id}&tab=t1`);
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await page.locator(`[data-cell="13,6"]`).click();
      await page.locator(`[data-cell="13,6"] select`).selectOption("in progress");
      await page.getByTestId("add-row-toggle").click();
      await page.locator(`th[data-row="11"]`).click();
      await shot(page, "dark-sheets");
      await page.getByRole("button", { name: "Discard" }).click();
    });
    await screen("dark step 4", async () => {
      await goto(page, `page=capture&step=points&meeting=${nutrition.id}`);
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 20_000 });
      const transfer = page.locator("button", { hasText: /^Transfer \d+$/ }).first();
      if (await transfer.isDisabled()) {
        await page.getByLabel("Select point").first().click();
      }
      await transfer.click();
      await page.locator("button", { hasText: /^Insert \d+ rows and write$/ }).waitFor({ timeout: 20_000 });
      await shot(page, "dark-step4");
    });
    await context.close();
    const mobile = await open(browser, 390, 844, { dark: true });
    await screen("dark 390 sheets", async () => {
      await goto(mobile.page, `page=sheets&wb=${workbook.id}&tab=t1`);
      await mobile.page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      await mobile.page.locator(`[data-cell="13,2"]`).click();
      await shot(mobile.page, "dark-sheets-bottom-editor");
    });
    await mobile.context.close();
  }

  await browser.close();
  writeFileSync(path.join(OUT, "metrics.json"), JSON.stringify({ round: ROUND, failures, checks, metrics }, null, 2));
  console.log(`\n${metrics.length} screens, ${failures.length} failures -> ${OUT}`);
  if (failures.length) {
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
