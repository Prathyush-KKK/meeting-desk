// The README walkthrough, driven through a real browser against the running dev servers.
//
//   cd api && FAKE_GOOGLE=1 FAKE_LLM=1 AUTH_DEV_USER=... uvicorn app.main:app --port 8000
//   cd web && pnpm dev
//   cd web && node e2e/walkthrough.mjs
//
// Or against the Docker demo, which serves the app and the API on one port:
//
//   docker compose -f docker-compose.demo.yml up -d
//   cd web && E2E_WEB=http://localhost:8000 node e2e/walkthrough.mjs
//
// paste -> extract -> points (defer, restore) -> transfer -> the Sheets page shows the rows ->
// edit a cell -> save -> Add row above a row.
//
// It is deliberately outside `npm run check`: it needs both servers up. Everything it asserts is
// asserted through the UI; the API is only asked where a row landed, so the script never hard-codes
// a row number.

import { chromium } from "playwright";

const WEB = process.env.E2E_WEB ?? "http://localhost:5173";
const API = process.env.E2E_API ?? "http://localhost:8000";
// Playwright's own Chromium (`npx playwright install chromium`) unless E2E_CHROMIUM names another.
const EXECUTABLE = process.env.E2E_CHROMIUM || undefined;
const STAMP = new Date().toISOString().slice(11, 19).replace(/:/g, "");

// Stamped so a re-run against a long-lived API is a fresh meeting with fresh points, rather than a
// repeat transfer (which the API rightly stops until someone confirms).
const NOTES = `Vendor call with Maya ${STAMP}

The Next Steps
Alex S: Send the Northwind questionnaire ${STAMP} by Friday
Daniel Okafor: Mirror OpenRates ${STAMP} before 3 Oct
Decided: the Owner column ${STAMP} holds a person, not a team
Risk: the upload flag ${STAMP} has no rollback plan
`;

let passed = 0;
const failures = [];

async function step(name, fn) {
  const started = Date.now();
  try {
    const detail = await fn();
    passed += 1;
    console.log(`  ok   ${name}${detail ? ` - ${detail}` : ""} (${Date.now() - started} ms)`);
  } catch (error) {
    failures.push(name);
    console.log(`  FAIL ${name}: ${error.message}`);
    throw error;
  }
}

const json = async (path) => {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
};

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: EXECUTABLE });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.log(`  [page error] ${error.message}`));

  // Toasts stay in the DOM (React owns them) but never swallow a click meant for the page beneath.
  const unblockToasts = () =>
    page.addStyleTag({ content: "[data-sonner-toaster],[data-sonner-toast]{pointer-events:none !important}" });

  try {
    await step("the app loads signed in", async () => {
      await page.goto(WEB, { waitUntil: "domcontentloaded" });
      await unblockToasts();
      await page.getByText("Meeting Desk").first().waitFor({ timeout: 20_000 });
      await page.getByRole("button", { name: /capture/i }).waitFor();
      return await page.locator("header span.ml-auto").first().innerText();
    });

    await step("the meeting list is served from the API", async () => {
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      const rows = await page.locator("[data-testid=meeting-row]").count();
      return `${rows} meetings`;
    });

    await step("a calendar card is read-only and a manual card is editable", async () => {
      const calendar = page.locator("[data-testid=meeting-row][data-source=calendar]").first();
      const manual = page.locator("[data-testid=meeting-row][data-source=manual]").first();
      await calendar.waitFor();
      if ((await calendar.getByLabel("Edit meeting").count()) !== 0) throw new Error("calendar card offered an edit pencil");
      await manual.waitFor();
      if ((await manual.getByLabel("Edit meeting").count()) !== 1) throw new Error("manual card has no edit pencil");
      return "pencil only on manual";
    });

    await step("paste with nothing selected creates a manual meeting", async () => {
      await page.fill("#quickpaste", NOTES);
      await page.getByRole("button", { name: "Save and continue" }).click();
      await page.getByRole("heading", { name: "Saved notes" }).waitFor({ timeout: 20_000 });
      const title = await page.getByTestId("current-meeting").innerText();
      if (!title.startsWith("Vendor call with Maya")) throw new Error(`titled "${title}"`);
      return title;
    });

    await step("the pasted note is listed and included", async () => {
      await page.getByText(/Pasted note/).first().waitFor({ timeout: 10_000 });
      return await page.locator("section >> text=/\\d+ · untick to leave one out/").first().innerText();
    });

    await step("extract lands on the points step", async () => {
      await page.getByRole("button", { name: "Extract points" }).click();
      await page.locator("[data-testid=point-row]").first().waitFor({ timeout: 30_000 });
      const rows = await page.locator("[data-testid=point-row][data-lifecycle=active]").count();
      if (rows < 4) throw new Error(`only ${rows} points`);
      return `${rows} points`;
    });

    await step("actions arrive ticked, so Transfer is armed", async () => {
      const label = await page.locator("button", { hasText: /^Transfer \d+$/ }).first().innerText();
      return label;
    });

    await step("typing a point autosaves once, debounced, without losing the caret", async () => {
      const row = page.locator("[data-testid=point-row][data-lifecycle=active]").first();
      const field = row.locator("input[aria-label=Point]");
      const before = await field.inputValue();
      const suffix = ` (checked with ${STAMP})`;
      await field.click();
      await page.keyboard.press("End");
      await page.keyboard.type(suffix, { delay: 25 });
      if ((await field.inputValue()) !== before + suffix) throw new Error("the field lost what was typed");
      if (!(await field.evaluate((el) => el === document.activeElement))) throw new Error("the field lost focus mid-typing");
      const wanted = before + suffix;
      const deadline = Date.now() + 15_000;
      while (Date.now() < deadline) {
        const points = await json("/points");
        if (points.some((p) => p.text === wanted)) return `"${suffix.trim()}" saved`;
        await page.waitForTimeout(250);
      }
      throw new Error("the edit never reached the API");
    });

    let deferredText = "";
    await step("Defer hides a point without losing it", async () => {
      const before = await page.locator("[data-testid=point-row][data-lifecycle=active]").count();
      const row = page.locator("[data-testid=point-row][data-lifecycle=active]").last();
      deferredText = await row.locator("input[aria-label=Point]").inputValue();
      await row.getByRole("button", { name: "Defer" }).click();
      await page.waitForFunction(
        (n) => document.querySelectorAll("[data-testid=point-row][data-lifecycle=active]").length === n,
        before - 1,
        { timeout: 15_000 },
      );
      return `${before} -> ${before - 1}`;
    });

    await step("See deferred lists it with Restore", async () => {
      await page.getByRole("button", { name: "See deferred" }).click();
      const row = page.locator("[data-testid=point-row][data-lifecycle=deferred]").first();
      await row.waitFor({ timeout: 10_000 });
      await row.getByRole("button", { name: "Transfer" }).waitFor();
      return await row.innerText().then((t) => t.split("\n")[1] ?? t);
    });

    await step("Restore brings it back to the active list", async () => {
      await page.locator("[data-testid=point-row][data-lifecycle=deferred]").first().getByRole("button", { name: "Restore" }).click();
      await page.waitForFunction(
        (text) =>
          [...document.querySelectorAll("[data-testid=point-row][data-lifecycle=active] input[aria-label=Point]")].some(
            (i) => i.value === text,
          ),
        deferredText,
        { timeout: 10_000 },
      );
      await page.getByRole("button", { name: "Hide deferred" }).click();
      return deferredText.slice(0, 40);
    });

    let transferred = [];
    await step("Transfer previews a Smart append", async () => {
      transferred = await page.$$eval("[data-testid=point-row][data-lifecycle=active]", (rows) =>
        rows
          .filter((r) => r.querySelector("input[type=checkbox][data-state=checked], button[role=checkbox][data-state=checked]"))
          .map((r) => r.querySelector("input[aria-label=Point]")?.value ?? ""),
      );
      await page.locator("button", { hasText: /^Transfer \d+$/ }).first().click();
      await page.locator("button", { hasText: /^Insert \d+ rows and write$/ }).waitFor({ timeout: 20_000 });
      const summary = await page.locator("aside >> text=/^Insert \\d+ after row/").first().innerText();
      return summary;
    });

    await step("the write lands, offers Undo, and opens the Sheets page on that tab", async () => {
      await page.locator("button", { hasText: /^Insert \d+ rows and write$/ }).click();
      await page.getByRole("heading", { name: "Sheets" }).waitFor({ timeout: 30_000 });
      await page.getByRole("button", { name: "Overdue" }).waitFor({ timeout: 20_000 });
      const toast = await page.locator("[data-sonner-toast]").first().innerText();
      if (!/Undo/.test(toast)) throw new Error(`no undo offered: ${toast.replace(/\s+/g, " ")}`);
      return `${await page.locator("section h2").first().innerText()} · ${toast.split("\n")[0]}`;
    });

    const workbook = (await json("/workbooks")).find((w) => w.name === "Mobile App Product Roadmap");
    let tabState = await json(`/workbooks/${workbook.id}/tabs/t1`);
    let writtenRow = -1;

    await step("the new rows are in the grid, keyed and linked to the meeting", async () => {
      const wanted = transferred[0];
      writtenRow = tabState.values.findIndex((row) => row[1] === wanted);
      if (writtenRow < 0) throw new Error(`"${wanted}" is not in the tab`);
      const cell = page.locator(`[data-cell="${writtenRow},1"]`);
      await cell.waitFor({ timeout: 20_000 });
      const key = await page.locator(`[data-cell="${writtenRow},0"]`).innerText();
      const notes = await page.locator(`[data-cell="${writtenRow},7"]`).innerText();
      if (!key.startsWith("T-")) throw new Error(`key column shows "${key}"`);
      if (!notes.startsWith("Vendor call with Maya")) throw new Error(`notes column shows "${notes}"`);
      return `row ${writtenRow + 1} ${key} · ${notes}`;
    });

    await step("a cell edit is staged, then saved with one batch", async () => {
      await page.locator(`[data-cell="${writtenRow},6"]`).click();
      await page.locator(`[data-cell="${writtenRow},6"] select`).selectOption("in progress");
      await page.getByText("1 unsaved").waitFor({ timeout: 10_000 });
      await page.getByRole("button", { name: "Save to Sheet" }).click();
      await page.getByText("0 unsaved").waitFor({ timeout: 20_000 });
      tabState = await json(`/workbooks/${workbook.id}/tabs/t1`);
      if (tabState.values[writtenRow][6] !== "in progress") throw new Error(`the sheet says "${tabState.values[writtenRow][6]}"`);
      return `G${writtenRow + 1} = in progress`;
    });

    const headerRow = tabState.layout.header_row;
    const aboveRow = headerRow + 3;
    const newTask = `Runbook for the upload flag ${STAMP}`;

    await step("Add row opens on 'after the table', with no row picked for it", async () => {
      await page.getByTestId("add-row-toggle").click();
      await page.getByTestId("add-row-panel").waitFor({ timeout: 10_000 });
      const above = page.getByTestId("addrow-above");
      // This used to come up pre-set to the first data row under the header.
      if (await above.isChecked()) throw new Error("'Above a row' was checked before a row was clicked");
      if (!(await above.isDisabled())) throw new Error("'Above a row' can be picked with no row");
      const lands = await page.getByTestId("add-row-lands").innerText();
      if (!lands.startsWith("Lands after row")) throw new Error(`the panel says "${lands}"`);
      return lands;
    });

    await step("Add row above the header row is refused, and says why", async () => {
      await page.locator(`th[data-row="${headerRow}"]`).click();
      await page.getByText(`Above row ${headerRow + 1}`).waitFor({ timeout: 10_000 });
      await page.fill("#addrow-1", `Refused ${STAMP}`);
      await page.getByTestId("add-row-submit").click();
      const message = await page.getByTestId("add-row-refused").innerText({ timeout: 20_000 });
      if (!/in or above the header/i.test(message)) throw new Error(`the panel says "${message}"`);
      const after = await json(`/workbooks/${workbook.id}/tabs/t1`);
      if (after.values.length !== tabState.values.length) throw new Error("a row was inserted anyway");
      return message;
    });

    await step("Add row above a clicked mid-table row lands inside the section", async () => {
      if (aboveRow <= headerRow + 1 || aboveRow >= tabState.layout.last_table_row) {
        throw new Error(`row ${aboveRow + 1} is not mid-table`);
      }
      await page.locator(`th[data-row="${aboveRow}"]`).click();
      await page.getByText(`Above row ${aboveRow + 1}`).waitFor({ timeout: 10_000 });
      await page.fill("#addrow-1", newTask);
      await page.locator("#addrow-2").fill("Noah S");
      await page.selectOption("#addrow-6", "open");
      await page.getByTestId("add-row-submit").click();
      await page.waitForFunction(
        ({ row, text }) => document.querySelector(`[data-cell="${row},1"]`)?.textContent?.trim() === text,
        { row: aboveRow, text: newTask },
        { timeout: 20_000 },
      );
      const after = await json(`/workbooks/${workbook.id}/tabs/t1`);
      if (after.values[aboveRow][1] !== newTask) throw new Error("the sheet did not take the row");
      if (after.values[aboveRow + 1][1] !== tabState.values[aboveRow][1]) throw new Error("the row below was overwritten, not pushed down");
      return `row ${aboveRow + 1} = ${after.values[aboveRow][0]} ${newTask}`;
    });

    await step("Add row from a point transfers it out of the tool", async () => {
      const before = await json("/points");
      await page.getByTestId("add-row-toggle").click();
      await page.getByTestId("add-row-panel").waitFor({ timeout: 10_000 });
      await page.getByText("From a point").click();
      const select = page.getByLabel("Point");
      await select.waitFor({ timeout: 10_000 });
      await page.waitForFunction(() => document.querySelectorAll("select[aria-label=Point] option").length > 1, null, { timeout: 10_000 });
      const chosen = await select.locator("option").nth(1).getAttribute("value");
      const chosenText = before.find((p) => p.id === chosen)?.text ?? "";
      await select.selectOption(chosen);
      await page.getByTestId("add-row-submit").click();
      await page.waitForFunction(
        (text) => [...document.querySelectorAll("td[data-cell]")].some((td) => td.textContent?.trim() === text),
        chosenText,
        { timeout: 20_000 },
      );
      const after = await json("/points");
      if (after.length !== before.length - 1) throw new Error(`${before.length} -> ${after.length} points`);
      return `"${chosenText.slice(0, 40)}" left the tool`;
    });

    await step("a cell changed in Google Sheets while editing shows both values", async () => {
      const current = await json(`/workbooks/${workbook.id}/tabs/t1`);
      const row = current.values.findIndex((r) => r[1] === newTask);
      await page.locator(`[data-cell="${row},2"]`).click();
      await page.locator(`[data-cell="${row},2"] input`).fill("Alex S");
      await page.keyboard.press("Enter");
      await page.getByText("1 unsaved").waitFor({ timeout: 10_000 });

      // Someone else edits the same cell in the sheet between the read and the save.
      const elsewhere = await fetch(`${API}/sheets/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workbook_id: workbook.id,
          sheet_id: "t1",
          edits: [{ cell: `C${row + 1}`, before: current.values[row][2], after: "Sofia Silva" }],
        }),
      });
      if (!elsewhere.ok) throw new Error(`the other writer failed: ${elsewhere.status}`);

      await page.getByRole("button", { name: "Save to Sheet" }).click();
      await page.getByText("These cells changed in Google Sheets while you were editing. Pick one per cell.").waitFor({ timeout: 20_000 });
      const panel = await page.locator("text=/yours: .*/").first().innerText();
      await page.getByRole("button", { name: "Take theirs" }).click();
      await page.getByText("0 unsaved").waitFor({ timeout: 10_000 });
      return panel.replace(/\s+/g, " ");
    });

    await step("the admin page shows connections, the allow-list and an attributed log", async () => {
      await page.getByRole("button", { name: /admin/i }).click();
      await page.getByRole("heading", { name: "Google connections" }).waitFor({ timeout: 20_000 });
      await page.getByRole("heading", { name: "Allow-list" }).waitFor();
      await page.getByRole("heading", { name: "Activity" }).waitFor();
      const rows = page.locator("section", { hasText: "Activity" }).last().locator("li");
      await rows.first().waitFor({ timeout: 20_000 });
      const lines = await rows.count();
      const log = await json("/admin/activity?limit=100");
      for (const wanted of ["Transferred", "Added a row"]) {
        if (!log.some((a) => a.text.includes(wanted))) throw new Error(`the log has no "${wanted}" line`);
      }
      if (log.some((a) => !a.actor)) throw new Error("an activity line has no actor");
      return `${lines} lines shown, ${log.length} logged, all attributed`;
    });
    await step("the phone layout is a single column with no horizontal page scroll", async () => {
      await page.setViewportSize({ width: 390, height: 780 });
      await page.getByRole("button", { name: /capture/i }).click();
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      const capture = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      await page.getByRole("button", { name: /sheets/i }).click();
      await page.locator("select[aria-label='Workbook and tab']").waitFor({ timeout: 20_000 });
      const sheets = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const gridScrolls = await page.evaluate(() => {
        const box = document.querySelector("table")?.parentElement;
        return !!box && box.scrollWidth > box.clientWidth;
      });
      if (capture > 0 || sheets > 0) throw new Error(`page overflows: capture ${capture}px, sheets ${sheets}px`);
      if (!gridScrolls) throw new Error("the grid does not scroll inside its own box");
      return "390 px: sidebar becomes a select, the grid scrolls in its box";
    });

    // The grid used to be sized `min(60vh, 100vh - 330px)` inside a slot that
    // was shorter than that, so it painted over Save and Add row. The geometry is the assertion.
    const gridIsInsideItsSlot = async (label) => {
      await page.getByRole("button", { name: /sheets/i }).click();
      await page.getByTestId("grid-slot").waitFor({ timeout: 20_000 });
      await page.locator("td[data-cell]").first().waitFor({ timeout: 20_000 });
      const box = await page.evaluate(() => {
        const slot = document.querySelector("[data-testid=grid-slot]");
        const grid = slot?.querySelector("[data-rows]");
        const save = [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Save to Sheet");
        const bar = document.querySelector("[data-testid=save-bar]");
        const r = (el) => (el ? el.getBoundingClientRect() : null);
        return {
          slot: r(slot),
          grid: r(grid),
          save: r(save),
          bar: r(bar),
          pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      });
      const slack = 1; // sub-pixel rounding
      if (box.grid.bottom > box.slot.bottom + slack) {
        throw new Error(`${label}: the grid runs ${Math.round(box.grid.bottom - box.slot.bottom)}px past its slot`);
      }
      if (box.grid.bottom > box.save.top + slack) {
        throw new Error(`${label}: the grid overlaps Save by ${Math.round(box.grid.bottom - box.save.top)}px`);
      }
      if (box.grid.bottom > box.bar.top + slack) throw new Error(`${label}: the grid overlaps the save bar`);
      if (box.pageOverflow > 0) throw new Error(`${label}: the page scrolls sideways by ${box.pageOverflow}px`);
      if (box.grid.height < 120) throw new Error(`${label}: the grid collapsed to ${Math.round(box.grid.height)}px`);
      return `${label}: grid ${Math.round(box.grid.height)}px ends ${Math.round(box.save.top - box.grid.bottom)}px above Save`;
    };

    await step("the Sheets grid stays inside its slot at 390 px, clear of Save", async () => {
      await page.setViewportSize({ width: 390, height: 780 });
      return await gridIsInsideItsSlot("390 px");
    });

    await step("the Sheets grid stays inside its slot at 768 px, clear of Save", async () => {
      await page.setViewportSize({ width: 768, height: 1024 });
      return await gridIsInsideItsSlot("768 px");
    });

    // A phone used to get an inline 24 px input instead of a bottom editor with 44 px targets. The
    // tap now opens a sheet at the bottom naming the column.
    await step("tapping a cell on a phone opens the bottom editor, not an inline input", async () => {
      await page.setViewportSize({ width: 390, height: 780 });
      const current = await json(`/workbooks/${workbook.id}/tabs/t1`);
      const row = current.values.findIndex((r) => r[1] === newTask);
      if (row < 0) throw new Error("the added row is gone");

      await page.locator(`[data-cell="${row},2"]`).click();
      const editor = page.getByTestId("cell-editor");
      await editor.waitFor({ timeout: 20_000 });
      if ((await page.locator(`[data-cell="${row},2"] input`).count()) !== 0) {
        throw new Error("an inline input opened in the cell as well");
      }
      const column = await page.getByTestId("cell-editor-column").innerText();
      const control = editor.locator("input, select").first();
      const height = await control.evaluate((el) => el.getBoundingClientRect().height);
      if (height < 44) throw new Error(`the control is ${height}px high, not 44`);
      for (const name of ["Save", "Cancel"]) {
        const h = await editor.getByRole("button", { name }).evaluate((el) => el.getBoundingClientRect().height);
        if (h < 44) throw new Error(`${name} is ${h}px high, not 44`);
      }

      const wanted = current.values[row][2] === "Noah S" ? "Alex S" : "Noah S";
      await control.fill(wanted);
      await editor.getByRole("button", { name: "Save" }).click();
      await page.getByTestId("cell-editor").waitFor({ state: "detached", timeout: 10_000 });
      await page.getByText("1 unsaved").waitFor({ timeout: 10_000 });
      await page.getByRole("button", { name: "Save to Sheet" }).click();
      await page.getByText("0 unsaved").waitFor({ timeout: 20_000 });
      const after = await json(`/workbooks/${workbook.id}/tabs/t1`);
      if (after.values[row][2] !== wanted) throw new Error(`the sheet says "${after.values[row][2]}"`);
      return `${column} on row ${row + 1}: ${current.values[row][2] || "(blank)"} -> ${wanted}, written from the bottom sheet`;
    });

    await step("Back closes the bottom editor instead of leaving the app", async () => {
      const current = await json(`/workbooks/${workbook.id}/tabs/t1`);
      const row = current.values.findIndex((r) => r[1] === newTask);
      await page.locator(`[data-cell="${row},2"]`).click();
      await page.getByTestId("cell-editor").waitFor({ timeout: 20_000 });
      await page.goBack();
      await page.getByTestId("cell-editor").waitFor({ state: "detached", timeout: 10_000 });
      await page.getByText("Meeting Desk").first().waitFor({ timeout: 10_000 });
      if ((await page.getByText("0 unsaved").count()) !== 1) throw new Error("Back staged an edit");
      return "the editor closed, the page is still open";
    });

    // The detail overlay traps the back button: it pushes history, and Back closes it.
    await step("Back closes the meeting detail overlay instead of leaving the app", async () => {
      await page.getByRole("button", { name: /capture/i }).click();
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 20_000 });
      await page.locator("[data-testid=meeting-row]").first().getByLabel("Show meeting details").click();
      const detail = page.getByTestId("meeting-detail");
      await detail.waitFor({ timeout: 10_000 });
      // It really is a full-screen overlay at this width, which is why Back matters.
      const covers = await detail.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return getComputedStyle(el).position === "fixed" && r.width >= window.innerWidth - 1;
      });
      if (!covers) throw new Error("the detail is not a full-screen overlay at 390 px");

      await page.goBack();
      await detail.waitFor({ state: "detached", timeout: 10_000 });
      await page.locator("[data-testid=meeting-row]").first().waitFor({ timeout: 10_000 });
      if (!/page=/.test(page.url())) throw new Error(`Back left the app: ${page.url()}`);
      await page.setViewportSize({ width: 1280, height: 900 });
      return "overlay closed, the meeting list is still there";
    });

    const second = await context.newPage();
    await step("401 shows the one-line sign-in page", async () => {
      await second.route("**/auth/me", (route) =>
        route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Sign in with Google to continue." }) }),
      );
      await second.goto(WEB, { waitUntil: "domcontentloaded" });
      const link = second.getByRole("link", { name: "Sign in with Google" });
      await link.waitFor({ timeout: 20_000 });
      return `link -> ${await link.getAttribute("href")}`;
    });

    await step("403 shows a plain not-on-the-list page", async () => {
      await second.unroute("**/auth/me");
      await second.route("**/auth/me", (route) =>
        route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "This Google account is not on the Meeting Desk allow-list. Ask an admin to add it: daniel.okafor@example.com." }),
        }),
      );
      await second.reload({ waitUntil: "domcontentloaded" });
      await second.getByRole("heading", { name: "Not on the list" }).waitFor({ timeout: 20_000 });
      return await second.locator("p").first().innerText();
    });
  } finally {
    await page.screenshot({ path: "e2e/last-run.png", fullPage: false }).catch(() => {});
    await browser.close();
  }
}

main()
  .then(() => {
    console.log(`\n${passed} steps passed.`);
    process.exit(0);
  })
  .catch(() => {
    console.log(`\n${passed} steps passed, failed at: ${failures.join(", ")}`);
    process.exit(1);
  });
