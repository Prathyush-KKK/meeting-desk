# web - the Meeting Desk app

The prototype (`meeting-desk/`: React 19, TypeScript, Vite, Tailwind, shadcn/ui, the minimal
black-on-white theme) moved here and is wired to the API. Its `store.tsx` is gone; the server is the
store.

```
src/api/client.ts    one typed fetch door: base URL, credentials, ApiError with the 409 payload
src/api/hooks.ts     TanStack Query hooks per route group; 15 s on lists, 60 s on the live tab,
                     optimistic point edits with rollback, invalidation after every write
src/api/types.ts     the wire contract, typed off api/app/schemas.py
src/lib/sheet.ts     kept verbatim as the client-side preview planner (and vitest's reference)
src/lib/display.ts   dates, clocks, status labels, the workstream list
src/components/      Grid (the sheet), MeetingList, PointRow, AddRowPanel, ui/ (six shadcn parts)
src/pages/           MeetingStep, NotesStep, PointsStep, TransferStep, SheetsPage, AdminPage, SignIn
e2e/walkthrough.mjs  the README walkthrough driven through a real browser
```

## Run it locally

Two terminals. The API first, with the fakes, so nothing needs Google credentials:

```bash
cd api
FAKE_GOOGLE=1 FAKE_LLM=1 AUTH_DEV_USER=prathyush.kodhanpur@simpleo.ai \
  DATABASE_URL=sqlite:///./meeting-desk.db \
  .venv/bin/uvicorn app.main:app --reload --port 8000
# or, from the repo root: make run
```

Then the web app:

```bash
cd web
pnpm install
pnpm dev            # http://localhost:5173
```

The dev server proxies `/api/*` to `http://localhost:8000` with the prefix stripped, so the browser
only ever sees one origin and the session cookie behaves as it will in production. Point it
somewhere else with `VITE_API_TARGET=http://other-host:8000 pnpm dev`.

**Sign-in.** The app asks `GET /auth/me` on load. `AUTH_DEV_USER` makes that succeed without Google,
which is what the local run uses. Without it the API answers 401 and the app shows a one-line page
with a *Sign in with Google* link to the API's `/auth/login`; an account that signs in but is not on
the allow-list gets 403 and a plain "Not on the list" page naming who to ask.

## Checks

```bash
pnpm check          # tsc -b, vitest run, vite build   (npm run check works the same)
pnpm lint           # oxlint
pnpm e2e            # the browser walkthrough; needs both servers up (see below)
```

`pnpm check` is the acceptance gate and needs no servers. Package manager: **pnpm** (the lockfile is
`pnpm-lock.yaml`); every script also runs under `npm run`.

`vitest` covers two things:

* `src/lib/sheet.test.ts` reads `../api/tests/fixtures/sheets/*.json` and asserts the same `expect`
  blocks `api/tests/test_layout.py` and `test_planner.py` assert. Those fixtures were generated from
  this very module, so the preview in the browser and the write on the server cannot drift apart.
* `src/components/MeetingList.test.tsx` and `src/components/PointRow.test.tsx` (Testing Library):
  calendar cards are read-only and manual ones carry the pencil; a point defers, restores and
  transfers.
* `src/components/Grid.test.tsx`: both paths through the grid - the plain table at or under 300
  rows, TanStack Virtual over it (a window of rows in the DOM plus two spacer rows holding the
  scrollbar). jsdom has no layout, so `src/test/setup.ts` gives the grid's scroll box a size and
  stubs `ResizeObserver`; nothing else in the suite sees a layout it would not see in a browser.
* `src/api/extraction-poll.test.ts`: the queued-extraction loop - every 2 s until `done`, the job's
  own error surfaced rather than polled around, Cancel stopping it, and a timeout so a stuck job
  cannot poll for ever. `pollExtraction` takes its clock, its sleep and its cancel flag, so the
  test needs neither timers nor network.

## The walkthrough

With the API on `:8000` and the web app on `:5173`:

1. **Paste.** On *Capture* with nothing selected, paste into the box at the top:

   ```
   Vendor call with Madhu

   The Next Steps
   Ansul S: Send the Sprinto questionnaire by Friday
   Prathyush Kodhanpur: Mirror Open Food Facts before 3 Oct
   Decided: the Owner column holds a person, not a team
   Risk: the upload flag has no rollback plan
   ```

   *Save and continue* creates a manual meeting titled from the first line and lands on **Notes**
   with the paste saved. (With a meeting selected it saves the note on that meeting instead; a
   calendar card is captured into a record first.)
2. **Extract.** *Extract points* runs the extraction and opens **Points** with the action items
   already ticked. Owners and dues come from the notes; nothing is invented.
3. **Points.** Edit any field - typing autosaves 500 ms later ("saved HH:MM" in the header), a
   select or a checkbox goes out at once, and anything the API refuses rolls back. *Defer* on a row
   (or the bulk *Defer*) hides a point; *See deferred* lists the deferred ones with **Restore** and
   **Transfer**. *Remove* is a soft delete with a ten-second Undo. The Capture badge counts active
   points only.
4. **Transfer.** *Transfer N* opens step 4. Pick the workbook and tab (**Nutrition Sialet Product
   Roadmap › P1 Resolve & Log**), leave *Smart append*, and the grid shows exactly where the rows
   land - the keys, the columns, what moves down. *Insert N rows and write* re-reads the region,
   writes one batch, and offers **Undo** for ten minutes. If somebody edited the tab in between the
   write is refused, the grid is re-read and the plan rebuilt; if these points went across before,
   a **Send again** confirmation appears rather than a silent repeat.
5. **Sheets shows the rows.** The app lands on that tab. The new rows carry their key (`T-108`…) and
   the meeting title and date in *Notes*.
6. **Edit a cell, save.** Click a cell (anything but the key and formula columns), pick a value -
   dropdown columns offer the sheet's own values - and *Save to Sheet*. The save re-reads those
   cells first: if one changed in Google Sheets meanwhile, nothing is written and both values are
   shown per cell with *Keep mine* / *Take theirs*.
7. **Add row above a row.** *Add row* opens a form built from the tab's headers (the key column says
   "generated on write", formula columns "copied down"), or *From a point* to pick an active or
   deferred point. Click a row number in the grid to switch the position from "after the table" to
   "above row N"; the insert lands there, inherits the formatting from the row above, and everything
   below moves down. A point used this way is transferred out of the tool.

### Driving it from a browser

`e2e/walkthrough.mjs` does all of the above with Playwright, and also checks the debounced autosave
(typing keeps the caret and reaches the API once), the phone layout at 390 px, and the 401 and 403
pages. It is kept out of `pnpm check` because it needs both servers running, and it stamps its own
notes so a re-run against a long-lived API is a fresh meeting rather than a repeat transfer.

```bash
node e2e/walkthrough.mjs
# E2E_WEB=http://127.0.0.1:5173 E2E_API=http://localhost:8000 E2E_CHROMIUM=/opt/pw-browsers/chromium
```

## Production: the API serves this build

`pnpm build` writes `web/dist`. Point the API at it and one process serves both:

```bash
WEB_DIST=../web/dist .venv/bin/uvicorn app.main:app --port 8000
```

The routers are registered first, so every API path still answers as itself; anything else falls
through to `index.html`. The client then calls the API on the same origin with no `/api` prefix
(`import.meta.env.DEV` picks the prefix; `VITE_API_BASE` overrides both).

## What was kept, and what changed

The theme, the layout and the responsive behaviour are the prototype's, untouched: system font,
black on white, 1 px borders, 4 px radius, no colour badges, one selection colour for the grid.
Below 768 px it is a single column, the meeting detail is a full-screen overlay, the points row wraps
to two lines, the transfer panel drops under the grid, the Sheets sidebar becomes a select, and
grids scroll horizontally inside their own box with sticky row numbers and column letters.

Gone: `src/store.tsx` (the API replaced it), `src/lib/extract.ts` (the server extracts now), the
shadcn components nothing imports, and `src/assets`.

Added in phase 4: **TanStack Virtual** in `src/components/Grid.tsx` for tabs over 300 rows (spec
section 3) - under that the table renders every row, which is cheaper than measuring and keeps one
code path for the sticky header, the column letters and the cell editor; and the **queued
extraction loop** in `useExtract`, so a deployment with `JOBS_ENABLED=1` (where
`POST /meetings/{id}/extract` answers `{"queued": true}`) polls `GET /extractions/{id}` every two
seconds until the points land, with a Cancel that stops the polling and says the job itself carries
on. With the queue off the same hook still resolves straight from the POST, so the app does not
care which deployment it is talking to.
