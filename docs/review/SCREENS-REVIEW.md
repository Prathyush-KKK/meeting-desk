# Meeting Desk - screen review (27 Sep 2026)

The bar: `UI-FEEDBACK.md` (the owner's direction, verbatim) and `SPEC-V6-UI.md` sections 1, 2 and the
on-screen friction items. Every screen was photographed against the fake stack, looked at, judged
against that bar, fixed, gated and photographed again. Three rounds, then a fourth on the
coordinator's two Step 3 changes at 390 px.

| | P1 | P2 | P3 | total |
| --- | --- | --- | --- | --- |
| Round 1 found | 2 | 25 | 19 | 46 |
| Round 2 found | 0 | 4 | 2 | 6 |
| Round 3 found | 0 | 0 | 4 | 4 |
| Round 4 found | 0 | 3 | 1 | 4 |
| **Fixed** | **2** | **32** | **26** | **60** |
| Remaining | 0 | 0 | 0 (see "Not changed", below) | |

Round 3 found no P1 or P2. Round 4 took the coordinator's two changes (the point text readable in
full on a phone; the bulk toolbar wrapping instead of scrolling) and the rule behind them - nothing
on a phone scrolls sideways except a grid inside its own box - which also retired round 1's
scrolling field strip (R1-09, now R4-03) and round 2's scrolling toolbar (R2-05, now R4-02).

**At 390 px nothing but the grids scrolls sideways.** The final capture measures `scrollWidth`
against `clientWidth` on every element whose computed `overflow-x` is `auto` or `scroll`, on all
19 phone screens, plus the page itself: no container other than a grid box scrolls sideways on any
of them; the grids scroll inside their own box on the 8 phone screens that show one (Step 4 and
Sheets). Text fields (`input`, `select`) scrolling their own text are left out of the count;
textareas are in. `shots/final/metrics.json` carries the per-screen result.

## How the screens were taken

`web/e2e/screens.mjs <round>` drives the running app (API with `FAKE_GOOGLE=1 FAKE_LLM=1` on a fresh
SQLite file, Vite on :5173) through every screen and writes `docs/review/shots/round-N/`:

- 1280 x 900 and 390 x 844 (2x) for every screen, 768 x 1024 for the Sheets grid and the Step 1
  detail, and a `colorScheme: "dark"` pass over Steps 1, 3, 4 and Sheets (1280 and 390).
- A `-full.png` beside any screen whose page scrolls.
- `metrics.json`: per screen, how far the page scrolls sideways, and on a phone every visible control
  under 44 px (a Radix tick counts its hit area, a radio its label) and, from round 4, every scroll
  container wider than its box (`sideways`), with the grids counted apart
  (`gridsScrollingInTheirBox`). `checks` holds the browser assertions the capture makes along the way.
- States the fake cannot reach are answered in the browser for that one route: an empty calendar,
  no workbook, first run, an expired connection, a member, 401 and 403.
- Data: the seed's six meetings and three workbooks, one long-titled manual meeting (truncation), and
  one paste in the walkthrough's pattern, extracted and transferred.

`node e2e/screens.mjs final` writes `docs/review/shots/final/`, the set kept for viewing.

## Round 1 - `shots/round-1/`

Severity: P1 broken or contradicts the direction; P2 wrong or unclear; P3 polish. Every row is
fixed; the test column names what holds it.

| id | screen | width | sev | evidence | cause | fix | test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1-01 | Step 3 points | 1280, 768+ | P1 | 1280-09, 1280-11, 1280-34 | `PointRow`: Defer and Remove shared the workstream's 130 px grid track, so they sat past the right edge and the list scrolled sideways (clipping tick and kind) | eight tracks, one control each; narrower tracks 768-1024 px | `PointRow.test` "own grid track" |
| R1-02 | Step 1 list | 390 | P1 | 390-04 | `MeetingList`: rows had `-ml-3 -mr-3` inside the list's scroll box; the box scrolled sideways and cut every title's first letters | no negative margins | `MeetingList.test` "inside the list box" |
| R1-03 | Step 1 | 390, 1280 | P2 | 390-01, 1280-02 | "updated N min ago" was `hidden sm:inline` and wrapped in the 380 px column | moved under the list with Refresh, all widths | `MeetingStep.test` |
| R1-04 | Step 1 detail | 1280 | P2 | 1280-02/03 | clicking another card left the panel on the first; two Continue buttons meant two meetings | panel follows the selection; list Continue hidden beside the panel | `MeetingStep.test` (2) |
| R1-05 | Step 1 manual edit | 1280, 390 | P2 | 1280-04, 390-03 | form grid stretched its rows over the panel height | `content-start` | visual (round 2 1280-04) |
| R1-06 | Step 1 paste | 1280, 390 | P2 | 1280-06, 390-04 | fixed six rows; pasted text scrolled out of its box (spec 7: grows with content) | `useAutoGrow`, up to 40 % of the viewport | `autogrow.test` (3) |
| R1-07 | all | 390 | P2 | metrics.json (28, 32, 36, 16 px targets) | controls sized for desktop | one rule under 768 px in `index.css`: controls 44 px high, icon buttons 44 wide, tick hit area 44 high | `theme.test`; metrics.json rounds 2-3 empty |
| R1-08 | bottom cell editor, native controls | 390 | P2 | 390-12, 390-19 | browser focus ring (orange on a phone): a hue nobody chose | `:focus-visible` outline in the foreground colour | `theme.test` |
| R1-09 | Step 3 points | 390 | P2 | 390-06 | row wrapped to three lines, text cut to ~14 characters | line 1 tick + text + Remove; line 2 fields in a strip that scrolls inside the row (superseded by R4-01, R4-03) | `PointRow.test` "two lines" |
| R1-10 | Step 3 footer | 390 | P2 | 390-06 | Transfer wrapped alone to the left | 2 x 2 block, Transfer bottom right | `PointsStep.test` |
| R1-11 | Steps 2, 3 | all | P2 | 1280-07, 1280-09 | "gemini-2.5-flash · Vertex AI asia-south1" and "runs on Gemini 2.5 Flash" hard-coded; the fake said provider `fake` | Step 3 reads `GET /meetings/{id}/extractions` (model, provider, fallback); Step 2 names none | `PointsStep.test` (3), `NotesStep.test` |
| R1-12 | Step 3 due | 1280 | P2 | 1280-09 | due field 14 px beside 12 px selects, clipped ("before 3 Oc") | `md:text-xs`, wider track, opaque ground | visual (round 2 1280-09) |
| R1-13 | Step 4 grid | 1280, 390 | P2 | 1280-12, 390-08, 1280-37 | planned rows below a 55vh window, empty space under it | grid takes the step's height; `Grid revealCell` scrolls the first planned cell into view | `Grid.test` "revealCell" (2) |
| R1-14 | Step 4 custom fill | 1280 | P2 | 1280-14 | anchor in the header: top line said blocked, side panel offered a plan and conflict choices | blocked in the client too, one line, no plan, no preview request | `TransferStep.test` |
| R1-15 | Step 4 | 1280 | P2 | 1280-15 | "Write 1 cells" | plurals ("Write 1 cell", "Insert 1 row") | `TransferStep.test` |
| R1-16 | Step 4 prerequisites | 1280 | P2 | 1280-16, 1280-17 | no workbook: one line pointing at another page; reload: "Select points on the previous step", no way there (spec 7) | prerequisites block with Connect and Back to points; a reload falls back to the ticked points; read-only workbook says so | `TransferStep.test` (4) |
| R1-17 | Sheets, no workbook | 1280 | P2 | 1280-26 | "Connect a workbook to start." with the field at the far bottom of the sidebar | the field is in the empty state (`ConnectWorkbook`) | `SheetsPage.review.test` |
| R1-18 | Sheets Add row | 1280 | P2 | 1280-24, 1280-36 | picked row shown only as a darker number (its tint lost to `bg-grid-header`) | tinted number and a 2 px line across the row's top | `Grid.test` "picked row" |
| R1-19 | Sheets grid | all | P2 | spec 7 | key and formula cells did nothing on tap (spec: say why) | `Grid editable.onLocked`; key, formula and read-only each explained | `SheetsPage.review.test` (4) |
| R1-20 | Sheets recent transfers | 1280 | P2 | 1280-19 | toast said "Undo is available for 10 minutes"; only the 10-second toast carried Undo | API `GET /transfers` gains `can_undo` (server clock); Undo on the log, once per batch | `test_transfers.py` (2), `SheetsPage.review.test` (2) |
| R1-21 | Step 1 delete | 1280 | P2 | spec 7 "10-second undo toast" | meeting delete toast had no Undo | Undo via `POST /meetings/{id}/restore` | `MeetingStep.test` |
| R1-22 | Step 2 notes | 1280 | P2 | spec 7 "a note can be moved" | API had `POST /notes/{id}/move`, no UI | "Move…" select on each note | `NotesStep.test` |
| R1-23 | banner, all pages | all | P2 | spec 7; `App.tsx` | banner came from admin-only `/admin/connections`, so members never saw it | API `GET /admin/connections/status` (banner, first run, can_connect) for anyone signed in; a member's notice names the admins, no Connect link | `test_admin.py` (3), `App.test` (7) |
| R1-24 | Sheets disconnect | 1280, 390 | P2 | 1280-20, 390-10 | one click, no undo, a shared workbook; not reachable on a phone | Undo (connects the same URL again); Disconnect link on a phone | `SheetsPage.review.test` |
| R1-25 | all times | all | P2 | spec 7 "Asia/Kolkata everywhere" | `fmtClock` used the browser's zone | `timeZone: Asia/Kolkata`; calendar dates cannot shift a day | `display.test` (run with `TZ=America/Los_Angeles` too) |
| R1-45 | Step 1 list | 1280 | P2 | 1280-05 | a card could only be picked with a mouse | `tabIndex`, Space picks, Enter continues, visible ring | `MeetingList.test` |
| R1-46 | Step 4 anchor | 1280 | P2 | round 1 check | `outline` dropped by tailwind-merge beside `outline-2`; anchor showed only on a conflict cell | `.sel-anchor` class | `Grid.test` "anchor" |
| R1-26 | Step 1 | 1280 | P3 | 1280-01, 1280-18 | double rule under the paste box and under the empty state | one rule; no empty list | `MeetingStep.test` |
| R1-27 | buttons, inputs, toasts | all | P3 | 1280-19 | shadcn `shadow*`, sonner's own shadow | removed; 1 px borders only | `theme.test` |
| R1-28 | Step 1 list | 390 | P3 | 390-04 | tapped row kept its hover tint | `hoverOnlyWhenSupported` | `theme.test` |
| R1-29 | Step 1 detail | 1280 | P3 | 1280-02 | "not captured yet" set in mono | mono only for a key | visual |
| R1-30 | Step 4 side panel | 1280 | P3 | 1280-12 | planner working ("most known header words") and field names | labels, the sheet's own column names | visual |
| R1-31 | cell editors | 1280, 390 | P3 | 1280-22, 390-12 | spellcheck squiggles under names | `spellCheck={false}` | visual |
| R1-32 | Sheets sidebar, Admin | 1280 | P3 | 1280-20, 1280-27 | ISO dates beside "Tue, 22 Sept" | `fmtDate` | visual |
| R1-33 | Admin | 1280 | P3 | 1280-28, 1280-30 | banner shown twice; "Only one account" with none | one banner; API warns only at exactly one | `test_admin.py` |
| R1-34 | Admin | 1280 | P3 | 1280-27 | actor truncated; connection rows two shapes | short names; one row shape | visual |
| R1-35 | dark grid | 1280 | P3 | 1280-36 | staged-edit tint invisible | `--sel-tint-alpha` 0.3 in dark | `theme.test` |
| R1-36 | Add row | 390 | P3 | 390-14 | Add row wrapped alone to the left | 2-column footer | visual |
| R1-37 | Step 1 detail, Sheets | 768 | P3 | 768-01, 768-02 | cramped detail labels; transfer text cut to 7 characters | narrower list and labels at md; text before meta | visual |
| R1-38 | 403 | 1280 | P3 | 1280-33 | "Try another account" not underlined | underlined | visual |
| R1-39 | Step 1 cards | all | P3 | 1280-02, 390-01 | wrapped meta line ended on a lone dot; "1 people" | separator travels with its item; "1 person" | `MeetingList.test` |
| R1-40 | Admin allow-list | 390 | P3 | 390-15 | "not yet signed in" broke over two lines | role and state on a second line | visual |
| R1-41 | Step 2 paste | 1280 | P3 | 1280-08 | placeholder looked like pasted content | an instruction | visual |
| R1-42 | Sheets | 390 | P3 | 390-10 | long hint sentence | "Tap a cell to edit it. The key column is fixed." | visual |
| R1-43 | Sheets filter | 1280 | P3 | (no-match state) | a filter matching nothing showed a bare header row | "No rows match. Show all rows" | `SheetsPage.review.test` |
| R1-44 | Step 3 toolbar | 390 | P3 | 390-06 | extraction label took a line on a phone | hidden under 768 px | visual |

Files (round 1): `web/src/components/{PointRow,MeetingList,Grid,AddRowPanel,ConnectWorkbook}.tsx`,
`web/src/components/ui/{button,input,textarea,checkbox,sonner}.tsx`,
`web/src/pages/{MeetingStep,NotesStep,PointsStep,TransferStep,SheetsPage,AdminPage,SignIn}.tsx`,
`web/src/{App.tsx,index.css}`, `web/src/lib/{autogrow,display}.ts`, `web/src/api/{hooks,types}.ts`,
`web/tailwind.config.js`, `api/app/routes/{admin,transfers}.py`; tests added in
`web/src/**/*.test.ts(x)` and `api/tests/test_{admin,transfers}.py`.

Gate (round 1):

```
api  ruff: All checks passed!    pytest: 495 passed in 50.70s
web  tsc -b: ok    vitest: Test Files 18 passed (18), Tests 164 passed (164)    vite build: built in 1.08s
e2e  walkthrough: 29 steps passed.
```

(The first walkthrough run stopped at 18/29: the new "Disconnect SIApoints - Earn Points" button
name matched the walkthrough's `getByLabel("Point")`. The name went back to "Disconnect", with the
workbook in its title, and the run was 29/29.)

## Round 2 - `shots/round-2/`

| id | screen | width | sev | evidence | cause | fix | test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R2-01 | every step's primary button | 1280 | P2 | round-2 1280-12 (toast over Keep here and Transfer); the capture could not press Transfer for 30 s | Toaster at bottom right, where Continue, Transfer, Insert and write and Save to Sheet live | bottom centre from 768 px (covers hint text at most), top centre on a phone | `App.test` "toasts" |
| R2-04 | Admin, member | 1280 | P2 | round-2 1280-26 | a member got three empty admin sections and a live "Connect an account" link (`disabled` does nothing on an anchor) that led to a 403 | the notice is a member's whole page | `AdminPage.test` (2) |
| R2-05 | Step 3 toolbar | 390 | P2 | round-2 390-06 | bulk controls wrapped to two 44 px lines; a third of the screen before the first point | one strip scrolling sideways under 768 px (superseded by R4-02); deferred rows drop the kind label there | `PointsStep.test` |
| R2-06 | Sheets | 390 | P2 | round-2 390-10 | heading, Connect field, links and five filter buttons pushed the grid below the first screen | heading hidden, Connect behind the select's last option, filter as a select beside Find and Add row | `SheetsPage.review.test` (2) |
| R2-02 | Step 3 label | 1280 | P3 | round-2 1280-09 | "Extracted with rule-based · the local rule-based fake" | "Extracted by the local rule-based fake" | `PointsStep.test` |
| R2-03 | Step 4 legend | 1280 | P3 | round-2 1280-14 | legend floated at the bottom of the slot under a short grid | legend above the grid | visual (round 3 1280-13) |

The round 2 capture has no Step 4 desktop shots: R2-01 is why. Round 3 has them.

Files (round 2): `web/src/{App.tsx,App.test.tsx}`, `web/src/pages/{PointsStep,AdminPage,TransferStep,SheetsPage}.tsx`,
`web/src/components/PointRow.tsx`, their tests, and `web/e2e/screens.mjs` (member banner, locked cell,
no-match screens; the banner intercepts answer the new status route).

Gate (round 2):

```
api  ruff: All checks passed!    pytest: 495 passed in 49.72s
web  tsc -b: ok    vitest: Test Files 19 passed (19), Tests 170 passed (170)    vite build: built in 1.19s
e2e  walkthrough: 29 steps passed.
```

## Round 3 - `shots/round-3/`

63 screens, no capture failure, no sideways page scroll at any width, no control under 44 px at
390 px. Nothing at P1 or P2; these four were polish:

| id | screen | width | sev | evidence | cause | fix | test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R3-01 | Step 4 warnings, activity log | 1280 | P3 | round-3 1280-16, 1280-32 | API strings "11 cell(s) already have content", "Transferred 2 point(s)" | worded counts in `transfers.py` | `test_transfers.py` |
| R3-02 | Sheets, no workbook | 1280 | P3 | round-3 1280-31 | empty tree box between two rules | tree only with workbooks | `SheetsPage.review.test` |
| R3-03 | Sheets filter select | 390 | P3 | round-3 390-10 | select 36 px inside a 44 px minimum | `h-11` (on the final capture the text sits centred) | visual (final 390-10) |
| R3-04 | Sheets save bar | 390, 768 | P3 | round-3 390-13, 768-01 | Discard and Save to Sheet wrapped to the left under the hint | count, Discard and Save as one right-aligned group | `SheetsPage.review.test` |

Files (round 3): `api/app/routes/transfers.py`, `api/tests/test_transfers.py`, `web/src/pages/SheetsPage.tsx`,
`web/src/pages/SheetsPage.review.test.tsx`, `web/e2e/screens.mjs` (`final` target).

Gate (round 3, the code as it stands):

```
api  ruff: All checks passed!    pytest: 496 passed in 55.63s      (490 before the review)
web  tsc -b: ok    vitest: Test Files 19 passed (19), Tests 172 passed (172)      (11 files, 116 tests before)
     vite build: dist/assets/index-DmTemI7N.js 460.21 kB, gzip 138.73 kB, built in 1.17s
e2e  walkthrough: 29 steps passed.
```

(The round 3 capture and its fixes were superseded as the kept set by round 4's final capture.)

## Round 4 - `shots/round-4/`, then `shots/final/`

The coordinator's direction, on `final/390-06`: the point's text must read in full on a phone, and
the bulk toolbar must wrap rather than scroll; nothing on a phone scrolls sideways except grids in
their own box.

| id | screen | width | sev | evidence | cause | fix | test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R4-01 | Step 3 point text | 390 | P2 | round-3 390-06 ("Send the Sprinto questionnaire by Frida") | a one-line `Input` at every width | under 768 px a textarea that wraps and grows with its content (`useAutoGrow`, no cap, no scrollbar; re-fits on resize); Enter adds nothing and a pasted line break becomes a space, since a point is one line in the sheet; from 768 px the one-line input as before | `PointRow.test` "on a phone" (4); browser check below |
| R4-02 | Step 3 bulk toolbar | 390 | P2 | round-3 390-06 (Defer cut to "D") | round 2's one-line strip scrolling sideways (R2-05) | two rows of three under 768 px: count, Assign to, Set status; Apply, Defer, Add point | `PointsStep.test` "two rows of three" |
| R4-03 | Step 3 point fields | 390 | P2 | round-3 390-06 (status, workstream, Defer off to the right) | round 1's field strip scrolling sideways inside the row (R1-09) | a six-column grid under the text, two lines (kind, owner; due, status, workstream); Defer and Remove beside the text; one Remove at every width instead of two | `PointRow.test` "fields in a grid", "one Remove" |
| R4-04 | Step 3 deferred point | 390 | P3 | round-4 390-07 ("the upload flag has no rol...") | `truncate` at every width | wraps under 768 px, truncates from there | `PointRow.test` "a deferred point" |

Autosave and the caret on the phone's textarea, checked in a real browser by the capture
(`final/metrics.json`, `checks`): typing at the end and then five characters back leaves the text
as typed and the caret where it was, the field keeps focus, the box grows (64 -> 84 px) without an
inner scroll, and the debounced save reaches the API:

```
check {"check":"390 point text","textIntact":true,"caretKept":true,"focused":true,"grew":"64 -> 84 px","innerScroll":false,"savedToApi":true}
```

The walkthrough's own caret step runs at 1280 px on the desktop input, which is unchanged, and
passes. Desktop Step 3 (`final/1280-09`, `1280-11`) is as it was: eight tracks, one line per point.

Files (round 4): `web/src/components/PointRow.tsx`, `web/src/pages/PointsStep.tsx`,
`web/src/lib/autogrow.ts`, `web/src/components/PointRow.test.tsx`, `web/src/pages/PointsStep.test.tsx`,
`web/e2e/screens.mjs` (the scroll-container measurement and the phone text check).

Gate (round 4, the code as it stands):

```
api  ruff: All checks passed!    pytest: 496 passed in 48.16s
web  tsc -b: ok    vitest: Test Files 19 passed (19), Tests 178 passed (178)
     vite build: dist/assets/index-CFb8ih6N.js 460.79 kB, gzip 138.85 kB, built in 994ms
e2e  walkthrough: 29 steps passed.
```

Then `node e2e/screens.mjs final` on a fresh API: 63 screens, 0 failures; at 390 px no page
overflow, no control under 44 px, no scroll container but the grids scrolling sideways. Those PNGs
are `docs/review/shots/final/`.

## Kept as they were

The minimal theme is unchanged: the tokens in `index.css` still define one selection hue and the
delete colour (`theme.test` pins it); `text-destructive` is still worn only by Remove point and
Delete meeting. The new marks (`.sel-anchor`, `.sel-insert-above`, `.sel-row-picked`) are the same
selection hue. No file under `.env*`, `docker-compose*.yml`, `scripts/`, `deploy/`,
`web/src/lib/sheet.ts` or `api/app/sheets/` was touched.

## Not changed, and why

- **Grid rows stay 28 px on a phone.** Every other control is 44 px there (R1-07), but a 44 px row
  shows about nine rows in the phone's grid slot instead of fifteen, and the Sheets grid is the page
  the owner calls the most important. Cells open a 44 px bottom editor once tapped. Listed for
  product below.
- **Date and time inputs follow the device's locale** (the capture's headless Chromium is en-US, so
  the manual form shows 09/18/2026 and 03:00 PM beside "Fri, 18 Sept" elsewhere). They are the native
  pickers; a custom picker would add weight to a minimal UI for a locale that real users will not see
  unless their device is set to it.
- **Step 4 shows the conflict count twice** (the API's warning line and the side panel's list). The
  warning is the API's contract for any client; the panel is where the choice is made.
- **"saved HH:MM" sits in the Points toolbar**, beside the fields it describes, not in the top bar.
- **A toast on the Sheets page covers the middle of the recent-transfer lines** for its few seconds;
  their Undo is at the right end, clear of it.
- **Not verifiable against the fake:** "a point changed by someone else in the last minute shows
  their name" and "owner ambiguity shows both candidates" need a second signed-in person or an
  ambiguous directory; the capture signs in as one person against a directory with no ambiguity.

## For product

1. **Grid row height on a phone:** 28 px rows (more of the sheet on screen, below the 44 px target
   rule) or 44 px rows (the rule, about nine rows visible). Currently 28 px.
2. **A point on a phone is more than two lines now.** Spec section 2 says "the points row wraps to
   two lines"; with the text wrapping in full (R4-01) and no sideways scroll (R4-02, R4-03), a point
   is its text (one line or more) plus two lines of fields - kind and owner, then due, status and
   workstream. If status matters more than kind while triaging on a phone, the grid can lead with it.
3. **Toast placement:** bottom centre from 768 px, top centre on a phone (R2-01). Any other place
   that keeps them off the primary buttons works as well.
4. **A member's first-run and reconnect banner names the admin accounts** (spec 7 asks for it). The
   Admin page itself stays admin-only (Review 1, finding 28).
