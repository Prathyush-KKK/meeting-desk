# Phase 3 report (the web app) - 22 Sep 2026

`cd web && npm run check` → tsc -b clean, **54 vitest tests pass**, `vite build` succeeds.
`cd api && .venv/bin/python -m pytest -q` → **352 passed** (348 from phase 2, 4 new for the static
mount). `ruff check` clean. `docker compose config` valid. The browser walkthrough
(`web/e2e/walkthrough.mjs`, Playwright, headless Chromium) runs **22 steps green** against the fake
API.

## What landed

```
web/                                    (replaces web/placeholder)
  package.json pnpm-lock.yaml           pnpm; @tanstack/react-query added, the shadcn packages
                                        nothing imports removed, vitest + Testing Library + jsdom added
  vite.config.ts                        @ alias, /api -> http://localhost:8000 (prefix stripped),
                                        the vitest config (jsdom, src/**/*.test.*)
  tsconfig*.json tailwind.config.js postcss.config.js components.json .oxlintrc.json index.html
  README.md                             local run and the screen-by-screen walkthrough
  src/main.tsx                          QueryClientProvider
  src/App.tsx                           the shell: Capture / Sheets / Admin, the step line, the
                                        Capture badge (active points only), the connection banner,
                                        page+step+meeting+tab in the URL, 401 / 403 gates
  src/api/client.ts                     one fetch door: base URL (dev `/api`, prod same origin),
                                        credentials: include, ApiError with .status/.payload/.isConflict
  src/api/hooks.ts                      queries and mutations per route group; 15 s on lists, 60 s on
                                        the live tab; usePatchPoint optimistic with rollback;
                                        usePointEditor (500 ms debounce, drafts, flush on unmount);
                                        invalidateAfterWrite for transfers, add-row and sheet saves
  src/api/types.ts                      the wire contract, typed off api/app/schemas.py
  src/lib/sheet.ts                      the prototype's planner, verbatim - the preview planner
  src/lib/display.ts                    dates, clocks, status labels, workstreams, the meeting label
  src/lib/utils.ts src/index.css        the prototype's, untouched
  src/components/Grid.tsx               the prototype's grid + onRowClick/activeRow (Add row's
                                        "above row N") and data-row / data-cell hooks for the e2e
  src/components/MeetingList.tsx        presentational; calendar read-only, manual gets the pencil
  src/components/PointRow.tsx           presentational; active row edits, deferred row Restore/Transfer
  src/components/AddRowPanel.tsx        the Add row form (per mapped header) or "from a point"
  src/components/ui/                    button, checkbox, input, label, sonner, textarea
  src/pages/MeetingStep.tsx             list + paste + Add meeting + the detail overlay + manual form
  src/pages/NotesStep.tsx               sources, imports, include toggles, paste, Extract
  src/pages/PointsStep.tsx              the grid, bulk assign/status/defer, See deferred, Keep/Transfer
  src/pages/TransferStep.tsx            preview + execute + 409 handling + the undo toast
  src/pages/SheetsPage.tsx              registry, live tab, filters, edits, save with both values on
                                        409, recent transfers, Add row
  src/pages/AdminPage.tsx               connections, allow-list, activity
  src/pages/SignIn.tsx                  the 401 sign-in line and the 403 "Not on the list" page
  src/lib/sheet.test.ts                 45 parity tests over api/tests/fixtures/sheets/*.json
  src/components/MeetingList.test.tsx   Testing Library: calendar read-only vs manual editable
  src/components/PointRow.test.tsx      Testing Library: defer, restore, transfer, decision statuses
  src/test/setup.ts                     jest-dom + cleanup
  e2e/walkthrough.mjs                   the walkthrough through a real browser (outside `check`)

api/app/config.py                       + WEB_DIST
api/app/main.py                         + SpaFiles / mount_web: the built app at "/" with an SPA
                                        fallback, mounted after the routers
api/tests/test_web_static.py            4 tests: API-only without WEB_DIST, the app and its assets,
                                        deep links fall back to index.html while API routes do not,
                                        a missing build is ignored

README.md .env.example docker-compose.yml Makefile .gitignore
                                        web run/check/e2e, WEB_DIST, the compose web service is now
                                        the Vite dev server, `make check` includes the web check
```

Deleted from the prototype on the way in: `src/store.tsx` (the API replaced it), `src/lib/extract.ts`
(the server extracts now), `src/hooks/use-toast.ts`, `src/assets/`, and the 40-odd shadcn components
nothing imports.

## Commands and output tails

```
$ cd web && npm run check
> meeting-desk-web@0.1.0 typecheck
> tsc -b

 RUN  v4.1.11 /home/claude/meeting-desk-app/web
 Test Files  3 passed (3)
      Tests  54 passed (54)
   Duration  3.84s

vite v8.3.0 building client environment for production...
✓ 1963 modules transformed.
dist/index.html                   0.39 kB │ gzip:   0.26 kB
dist/assets/index-DCU9bJmB.css   20.23 kB │ gzip:   5.12 kB
dist/assets/index-DInGRIkn.js   420.40 kB │ gzip: 126.39 kB
✓ built in 1.02s
```

```
$ cd api && .venv/bin/python -m pytest -q
........................................................................ [ 81%]
................................................................         [100%]
352 passed in 29.41s

$ cd api && .venv/bin/ruff check .
All checks passed!
```

```
$ cd web && node e2e/walkthrough.mjs        # API on :8000 (FAKE_GOOGLE=1 FAKE_LLM=1), web on :5173
  ok   the app loads signed in - prathyush.kodhanpur@simpleo.ai (617 ms)
  ok   the meeting list is served from the API - 6 meetings (8 ms)
  ok   a calendar card is read-only and a manual card is editable - pencil only on manual (13 ms)
  ok   paste with nothing selected creates a manual meeting - Vendor call with Madhu 024349 (172 ms)
  ok   the pasted note is listed and included - 1 · untick to leave one out (30 ms)
  ok   extract lands on the points step - 4 points (313 ms)
  ok   actions arrive ticked, so Transfer is armed - Transfer 2 (4 ms)
  ok   typing a point autosaves once, debounced, without losing the caret - "(checked with 024349)" saved (1572 ms)
  ok   Defer hides a point without losing it - 4 -> 3 (121 ms)
  ok   See deferred lists it with Restore - the upload flag 024349 has no rollback plan (129 ms)
  ok   Restore brings it back to the active list - the upload flag 024349 has no rollback p (200 ms)
  ok   Transfer previews a Smart append - Insert 2 after row 16 (223 ms)
  ok   the write lands, offers Undo, and opens the Sheets page on that tab - P1 Resolve & Log · Wrote 12 cells to P1 Resolve & Log (311 ms)
  ok   the new rows are in the grid, keyed and linked to the meeting - row 17 T-108 · Vendor call with Madhu 024349 · 22 Sep (6 ms)
  ok   a cell edit is staged, then saved with one batch - G17 = in progress (236 ms)
  ok   Add row above a clicked row lands inside the section - row 12 = T-110 Runbook for the upload flag 024349 (304 ms)
  ok   Add row from a point transfers it out of the tool - "Review dataset for weight information" left the tool (311 ms)
  ok   a cell changed in Google Sheets while editing shows both values - yours: Ansul S (374 ms)
  ok   the admin page shows connections, the allow-list and an attributed log - 12 lines shown, 13 logged, all attributed (93 ms)
  ok   the phone layout is a single column with no horizontal page scroll - 390 px: sidebar becomes a select, the grid scrolls in its box (186 ms)
  ok   401 shows the one-line sign-in page - link -> /api/auth/login (596 ms)
  ok   403 shows a plain not-on-the-list page - This Google account is not on the Meeting Desk allow-list. Ask an admin to add it: prathyush.kodhanpur@simpleo.ai. (383 ms)

22 steps passed.
```

## Decisions the brief left open

1. **pnpm**, as the prototype had. `pnpm-lock.yaml` is committed; every script also runs under
   `npm run`, and `npm run check` is what the acceptance gate uses.
2. **`tsc --noEmit` is realised as `tsc -b`.** The prototype's tsconfig is a solution file with two
   project references, both already `noEmit: true`; a bare `tsc --noEmit` on the root project (which
   has `files: []`) would check nothing. `npm run typecheck` = `tsc -b`.
3. **`/auth/me`, not `/me`.** The API has no `/me`; `GET /auth/me` is the route phase 1 built and
   the one the app calls. Adding an alias would have been a second name for one thing.
4. **The API base is `/api` in dev and empty in production.** Vite proxies `/api` to :8000 with the
   prefix stripped; the production build is served by the API itself and calls the same origin with
   no prefix. `VITE_API_BASE` overrides both. One origin means the session cookie needs no CORS
   exception, though `credentials: "include"` is set anyway so a split-origin deployment works.
5. **The client-side planner drives the grid, the server's plan drives the write.** `lib/sheet.ts`
   plans the preview so the grid reacts to a mode or anchor change with no round trip;
   `POST /transfers/preview` supplies the authoritative `region_hash`, the warnings and the per-point
   rows, and `execute` is sent with that hash. The fixtures prove the two planners agree cell for
   cell, which is the whole point of keeping both.
6. **Only the shadcn components the app imports were kept** (button, checkbox, input, label, sonner,
   textarea). The other forty came with the prototype's scaffold, pulled in ~30 packages, and two of
   them (`calendar`, `resizable`) do not type-check against the versions their own package.json
   pins - so `npm run check` could not have been green with them in. No component was changed and
   none was added; `components.json` still points at the same aliases, so `shadcn add` works.
7. **`selected` is set by the web after an extraction.** The prototype arrived on Step 3 with the
   action items ticked; the API stores `selected` per point and defaults it to false. `useExtract`
   follows a successful extraction with one `POST /points/bulk` that ticks the new actions, rather
   than the API deciding UI state.
8. **Autosave is a draft overlay plus a 500 ms debounce** (`usePointEditor`). A keystroke lands in a
   local draft immediately, so neither a slow request nor the 15 s poll can pull the text out from
   under the person; the PATCH goes 500 ms later and the draft is dropped only when the answer to
   that edit returns. Selects and checkboxes go out at once. Leaving the step flushes what is
   pending straight through `api.patch`, because the component's mutation observer is going away.
   The header shows "saved HH:MM".
9. **A repeat transfer asks.** The API answers 409 with `point_ids` when a point's text went across
   before; the step shows the message with *Send again* (which re-executes with `allow_repeat`) and
   *Cancel*, never a silent repeat. A 409 without `point_ids` is the stale-region case: the tab is
   re-read, the plan rebuilt, and the notice stays on screen.
10. **Add row posts column indexes, not header text.** `POST /sheets/add-row` accepts either
    (`_column_for` takes a digit key or a header string); indexes are unambiguous when two columns
    share a header, and the form is built from the tab's own header row anyway.
11. **Editable cells are "everything but the key and formula columns"**, per spec section 5, rather
    than the prototype's "mapped columns only" - so a Workstream or Meeting column can be corrected
    in place. Dropdown columns still offer only the sheet's values; date columns get a date input.
12. **The manual meeting form dropped Meet link and Recurrence.** `MeetingPatchIn` does not accept
    them (they are Calendar's fields); everything else the prototype's form had is there.
13. **The place is in the URL** (`?page=…&step=…&meeting=…&wb=…&tab=…`, `history.replaceState`), per
    the friction register's "the current step is in the URL". No router was added.
14. **React 19, not 18.** The prototype's `package.json` pins React 19.2 and that is what moved
    across; the spec's "React 18" predates the prototype. Nothing in the app depends on 19-only
    behaviour.
15. **The field wrapper in the manual form was hoisted out of render.** The prototype declared it
    inside the component, which remounts the input on every keystroke and loses focus. Same markup,
    declared once.

## Known gaps

- **TanStack Virtual is not wired in.** Spec section 3 wants it for grids over 300 rows; the Grid
  still renders every row. The fake tabs are ~20 rows, so it never showed here. It is a Grid-only
  change and does not touch the API.
- **Extraction polling.** `JOBS_ENABLED=0` makes `POST /meetings/{id}/extract` answer inline with
  the points, which is what the app uses. With the queue on, the route answers `queued` and
  `GET /extractions/{id}` must be polled; the hook does not do that yet, so a queued deployment
  needs that loop added (the types are already there).
- **Uploads and the Drive picker.** `/notes/sources` offers gemini_doc, transcript, recap_email and
  paste; there is no file upload control, matching the API (phase 5 in the build order).
- **Notes cannot be moved between meetings from the UI** (`POST /notes/{id}/move` exists and is
  unused).
- **Custom fill is wired but only lightly exercised**: the e2e drives Smart append. The conflict
  radio, key writing and the anchor rules are the prototype's, and the planner underneath is the one
  the fixtures test.
- **Offline retry queue.** The friction register asks for an in-memory retry queue and a banner when
  autosave hits a network failure; today the edit rolls back and a toast says so.
- The e2e writes into the fake sheets client, which lives in the API process's memory: re-running it
  against a long-lived API keeps appending rows (harmless, and the script stamps its own text so it
  never collides). Restart the API for a pristine grid.
