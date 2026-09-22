# Review 1 - fix log

22 Sep 2026. One line per finding in `docs/REVIEW-1.md`: what changed, and the test that proves it.
Every fix went in as a failing test first. Everything is done: the backend, chart and CI findings
in the first pass, then the web-only ones (4, 6, 23, 29, the Add row default in 8, the client half
of 9 and the member-safe banner in 28) in the second.

Suite: 409 -> 480 pytest, 64 -> 114 vitest, `web/e2e/walkthrough.mjs` 22 -> 29 steps.

## Critical

1. **Undo deleted a row somebody had since filled in.** The transfer now hashes the whole row as it
   stands after the write (a fresh read, so a copied-down formula's value is in it) into
   `snapshot.row_hash`; undo re-hashes before deleting and answers 409 with the row's contents when
   it moved. Cells the transfer wrote are still checked as before.
   `app/sheets/layout.py:row_hash`, `app/routes/transfers.py:_touched_rows` ·
   `test_review1_01_undo_refuses_when_the_row_was_filled_in_elsewhere`
2. **A deployment could start with the local shortcuts.** `create_app` calls `guard_environment`:
   outside `local` and `test` it raises `UnsafeConfiguration` on the repository's default session
   secret, on a secret under 32 characters, on a non-empty `AUTH_DEV_USER`, and on a `*` CORS
   origin (finding 20). `app/main.py` ·
   `test_review1_02_a_deployment_refuses_the_local_shortcuts`,
   `test_review1_02_a_configured_deployment_starts`,
   `test_review1_02_local_and_test_keep_every_convenience`

## High

3. **Any Google error marked a connection expired.** Only `AuthExpired` - the refresh token refused
   - does now; a 429, a 500 or a Calendar outage records `last_error` and leaves the status alone.
   `app/jobs/token_health.py` · `test_review1_03_only_an_auth_failure_marks_a_connection_expired`,
   `test_review1_03_an_auth_failure_still_marks_it_expired`
4. **`before` was recomputed from the latest poll, so the pre-save guard could never fire.** A
   staged edit is now `{before, after}`: `before` is read in the render the person clicked in and
   held until the edit is saved or discarded, and a second edit of the same cell keeps the first
   one. Resolving a clash with "Keep mine" re-sends against `theirs`, which is what the sheet holds
   and what the person just chose to overwrite. No API change was needed - it already compares the
   client's `before` against a fresh read of exactly those cells.
   `web/src/pages/SheetsPage.tsx:stageEdit,runSave,resolveClash` ·
   `sends the value the cell held when it was changed, not the one the poll brought in`,
   `keeps the first baseline when the same cell is changed twice`,
   `re-sends a kept edit against what the sheet holds now, so the guard passes`,
   `drops the edit entirely when theirs is taken`
5. **Re-pasting a note after it was removed was a 500.** `unique(meeting_id, text_hash)` became a
   partial unique index on `deleted_at IS NULL` (Postgres `postgresql_where`, SQLite
   `sqlite_where`), in migration `0002`; `save_note` and the note move catch `IntegrityError` and
   answer 409 with the same message the pre-check would have given.
   `app/models.py`, `alembic/versions/0002_notes_partial_unique_index.py`, `app/notes_store.py`,
   `app/routes/notes.py` · `test_review1_05_the_same_note_can_be_pasted_again_after_it_was_removed`,
   `test_review1_05_a_racing_duplicate_note_is_a_409_not_a_500`,
   `test_a_note_is_unique_per_meeting_and_text_while_it_is_live`
6. **The grid painted over Save and Add row at 390 px and 768 px.** It was sized
   `min(60vh, 100vh - 330px)` inside a slot that could be shorter than either. The slot is
   `overflow-hidden` and the grid is `maxHeight: 100%`, so it can never leave it. Under 768 px the
   page itself scrolls (`main` already did; the Sheets root no longer claims `h-full`) and the grid
   keeps a fixed 52vh of it; from 768 px up the page does not scroll, the grid takes what is left
   (`min-h-0 flex-1`) and every other slot is `shrink-0`. The Add row panel is readable on a phone:
   44 px controls, and the position radios have 44 px rows.
   `web/src/pages/SheetsPage.tsx`, `web/src/components/AddRowPanel.tsx` ·
   walkthrough `the Sheets grid stays inside its slot at 390 px, clear of Save` and the same at
   768 px, both asserting the grid's rect against the slot's, against Save's and against the save
   bar's. Screenshots: `/tmp/mdshots2/390-*.png`, `/tmp/mdshots2/768-*.png`
7. **`/sheets/save` could write the header row.** Saving now rejects any cell in or above the header
   row (column names are changed in Google Sheets) and anything below the last table row (that is
   what Add row is for). `app/routes/sheets.py:_reject_cells_outside_the_table` ·
   `test_review1_07_save_refuses_the_header_row_and_anything_below_the_table`
8. **An insert under the header copied the header's formulas and formatting.** The planner takes
   the formula source from the row *below* the insert when the row above is the header, or copies
   nothing if the table is empty; `insertDimension` gets `inheritFromBefore: false` in the same
   case, so the new row inherits a data row's formatting. The AddRowPanel's "Above a row" default
   (`header_row + 1`) is the web half and is **not done**.
   `app/sheets/planner.py:_formula_fill`, `app/sheets/ops.py:inherits_from_above`,
   `app/google/interface.py:InsertRows` ·
   `test_review1_08_an_insert_under_the_header_takes_formatting_and_formulas_from_below`,
   `test_review1_08_an_empty_table_copies_nothing`

   _(web)_ The panel opens on "After the table" and there is no default row: "Above a row" is
   disabled and reads "click a row number in the grid" until one is clicked, and a `clear` link
   puts it back. The API's refusals - in or above the header, below the table - are shown in the
   panel next to the radio as well as in a toast, with what was typed still in the form.
   `web/src/components/AddRowPanel.tsx` ·
   `defaults to after the table, with no row picked`,
   `cannot be switched to 'above' without clicking a row, so it cannot land under the header`,
   `sends after_table when nothing is picked`, `uses the clicked row once there is one`,
   `shows the header-row message beside the radio instead of only in a toast`,
   `shows the below-the-table message the same way`, `clears the message on the next press` ·
   walkthrough `Add row opens on 'after the table', with no row picked for it`,
   `Add row above the header row is refused, and says why`,
   `Add row above a clicked mid-table row lands inside the section`
9. **Sheets writes had no idempotency key.** `transfers/execute`, `sheets/save` and
   `sheets/add-row` take an optional client `batch_id` (uuid) and go through `app/write_batch.py`:
   the intent row is written `pending` and **committed before** the Google call, settled `done`
   with the stored response after it, and left `failed` with the reason when Google refuses - with
   no point deleted and no edit logged. A repeat of a finished `batch_id` returns the stored
   result, checked at the top of the route before anything else runs; the same id with a different
   body is a 409, and one still in flight is a 409. New table `write_batches`, migration `0003`.
   `app/write_batch.py`, `app/routes/transfers.py`, `app/routes/sheets.py`, `app/models.py` ·
   `test_review1_09_a_repeated_transfer_batch_id_replays_the_stored_result`,
   `test_review1_09_a_repeated_save_and_add_row_batch_id_replay_too`,
   `test_review1_09_the_intent_is_recorded_before_the_google_call`,
   `test_review1_09_a_batch_id_reused_for_a_different_write_is_refused`

   _(web)_ `lib/batch.ts` mints one `crypto.randomUUID()` per press and holds it: the write landing
   clears it, a 4xx clears it (nothing was written, and the next press carries a different body),
   and a transport failure or a 5xx keeps it - which is exactly the case the key exists for, so
   pressing Save again replays instead of writing twice. All three routes send it:
   `transfers/execute`, `sheets/save` and `sheets/add-row`.
   `web/src/lib/batch.ts`, `web/src/pages/TransferStep.tsx`, `web/src/pages/SheetsPage.tsx`,
   `web/src/components/AddRowPanel.tsx`, `web/src/api/hooks.ts` ·
   `is a v4 uuid, and a different one every time`,
   `hands out the same id until the write settles, so a retry cannot double-write`,
   `keeps the id when the outcome is unknown and drops it when the server refused`,
   `is true for a refusal the server actually gave`,
   `is false when nobody knows whether the write landed`,
   `sends a uuid with the save and a fresh one for the next save`,
   `re-sends the same id when the first attempt never got an answer`,
   `uses a new id after the server refused, because the body changed`,
   `sends a uuid and holds it while the outcome is unknown`

## Medium

10. **Dates were re-parsed from `due_text` at write time.** `PointForSheet` carries `due_date`, the
    planner puts it on the write as `date_value`, and `cell_data` only reads the text when there is
    none. Points created or edited by hand now resolve `due_date` the same way extraction does, so
    "by EOW" means the same day everywhere. `app/sheets/planner.py`, `app/sheets/ops.py`,
    `app/google/sheets.py`, `app/routes/points.py` ·
    `test_review1_10_a_date_column_is_written_from_the_points_own_due_date`,
    `test_review1_10_the_text_is_only_parsed_when_the_point_has_no_date`
11. **EOD, EOW, "end of month", "by the 31st" and "next Thursday" were wrong or empty.** A new
    `app/relative_dates.py` resolves them explicitly against the meeting's date before dateparser
    is asked: the week ends on Friday, a day of the month is clamped to that month's last day, and
    "next <weekday>" is the weekday in the *following* week. Both parsers use it.
    `app/relative_dates.py`, `app/extract/postprocess.py`, `app/sheets/dates.py` ·
    `test_review1_11_the_shorthand_resolves_against_the_meeting`,
    `test_review1_11_by_the_31st_is_clamped_to_the_base_month_every_month`,
    `test_review1_11_end_of_week_and_next_weekday_cross_month_boundaries`,
    `test_review1_11_a_phrase_nobody_uses_is_still_nothing`
12. **Nothing stopped the notes instructing the model.** The system text says the notes are data
    and names what to ignore; the fence is a random per-call `<<<NOTES-…>>>`, and any copy of it
    (or of `>>>`) in the body is replaced before the prompt is built, case-insensitively.
    `app/extract/prompt.py` ·
    `test_review1_12_the_prompt_says_the_notes_are_data_and_fences_them_freshly`,
    `test_review1_12_a_note_that_tries_to_close_the_fence_cannot`,
    `test_review1_12_neutralise_is_case_insensitive`
13. **`{}` counted as a successful extraction.** The JSON schema is `additionalProperties: false`
    with `propertyOrdering` at every level, the Pydantic models are `extra="forbid"`, and a payload
    with none of the four keys raises `InvalidModelOutput` - so the single retry runs instead of
    the person being told the notes held nothing. The fake provider is unchanged.
    `app/extract/schema.py`, `app/extract/parse.py` ·
    `test_review1_13_the_json_schema_is_strict_at_every_level`,
    `test_review1_13_a_payload_with_none_of_the_four_keys_is_not_an_empty_extraction`,
    `test_review1_13_an_invented_field_is_refused_so_the_retry_runs`,
    `test_review1_13_the_single_retry_runs_on_an_empty_object`,
    `test_review1_13_the_fake_provider_still_works`
14. **`region_hash` covered only header..last_table_row.** It now covers `header_row - 2` to
    `last_table_row + 5`, clamped to the grid, and a Custom fill additionally hashes the exact rows
    it writes over, which is the case the region could never reach. An append or Add row lands
    inside the region by construction, so its digest is unchanged.
    `app/sheets/layout.py:region_bounds`, `app/routes/transfers.py:guard_hash` ·
    `test_review1_14_the_region_hash_covers_the_rows_around_the_table`,
    `test_review1_14_a_fill_anchored_below_the_region_is_still_guarded`
15. **Add row skipped the guard on an empty `region_hash`.** `AddRowIn.region_hash` is
    `Field(min_length=64, max_length=64)` and is always compared. `app/schemas.py`,
    `app/routes/sheets.py` · `test_review1_15_add_row_without_a_real_region_hash_is_refused`
16. **The repeat check scanned every transfer ever made.** `transfers.text_norm` is an indexed
    column (migration `0003` backfills it from the snapshot) and the question is asked per
    workbook. `app/models.py`, `app/routes/transfers.py:_already_transferred` ·
    `test_review1_16_the_repeat_check_reads_the_column_and_is_scoped_to_the_workbook`
17. **A Calendar 429 blocked Sheets on the same connection.** Backoff is keyed by
    `(connection, provider)`, because Google's quotas are per API. Refresh on the meeting list is
    rate-limited to one forced fetch per `CALENDAR_REFRESH_MIN_SECONDS` (10 s).
    `app/google/http.py`, `app/routes/meetings.py` ·
    `test_review1_17_a_calendar_rate_limit_does_not_block_sheets`,
    `test_review1_17_refresh_does_not_bypass_the_cache_more_than_once_in_a_few_seconds`
18. **Connecting an account left the stale meeting list cached.** The cache entry carries the
    healthy-connection set it was filled from and is ignored when that set changes; connecting also
    clears it outright. `app/routes/meetings.py`, `app/routes/admin.py` ·
    `test_review1_18_the_calendar_cache_is_keyed_on_the_healthy_connections`,
    `test_review1_18_connecting_an_account_clears_the_cache`
19. **`MEETING_DESK_TOKEN_KEY_PREVIOUS` was always required.** It moved behind
    `externalSecrets.rotation.enabled` (default false), so the ExternalSecret does not ask
    Infisical for a key that only exists during a rotation. `scripts/ci.sh` renders the chart both
    ways and asserts the key appears only with the flag.
    `deploy/helm/meeting-desk/values.yaml`, `values-internal.yaml`, `templates/externalsecret.yaml`,
    `scripts/ci.sh` · `test_review1_19_the_previous_token_key_is_behind_the_rotation_flag`
20. **CORS `*` with credentials.** Covered by the startup guard in 2.
    `test_review1_20_a_wildcard_cors_origin_with_credentials_is_refused`
21. **The OAuth state cookie was not Secure and had no max age.** `SessionMiddleware` gets its own
    cookie name (`md_oauth_state`, distinct from the sign-in cookie), `max_age=600` and
    `https_only` outside local and test. `app/main.py`, `app/config.py` ·
    `test_review1_21_the_oauth_state_cookie_is_its_own_short_lived_cookie`,
    `test_review1_21_the_state_cookie_is_set_on_the_redirect`
22. **No PKCE on either flow.** Sign-in registers `code_challenge_method: S256` so authlib carries
    the verifier in the session; "Connect an account" generates the verifier, keeps it beside the
    state and sends it with the code. Both tests assert the challenge is the S256 of the verifier,
    that the verifier never appears in the redirect, and that it does appear in the token request.
    `app/auth/oidc.py`, `app/google/oauth.py`, `app/routes/admin.py` ·
    `test_review1_22_connecting_an_account_uses_pkce_s256`,
    `test_review1_22_signing_in_uses_pkce_s256`
23. **A 24 px inline input on a phone, and an overlay the back button could not close.** Under
    768 px a tap on an editable cell opens a bottom editor (`md:hidden`) naming the column, showing
    what the cell holds now, and offering a 44 px control - a select on a dropdown column, an input
    otherwise - with 44 px Save and Cancel. The inline editor is not rendered at all at that width,
    so it cannot take the focus or raise the keyboard behind the sheet; from 768 px up it is
    unchanged. Both the bottom editor and the meeting detail overlay push one history entry while
    they are open, so Back closes them instead of leaving the app, and closing them any other way
    takes that entry back rather than leaving a dead step behind.
    `web/src/lib/overlay.ts:useCloseOnBack,useNarrow`, `web/src/components/Grid.tsx`,
    `web/src/pages/MeetingStep.tsx` ·
    `opens a bottom editor with the column name, the current value and a 44 px control`,
    `uses a select on a dropdown column and keeps it 44 px`, `Cancel closes it and writes nothing`,
    `Back closes the editor instead of leaving the app`,
    `does not open a header cell or a column nobody may edit`,
    `stays inline in the cell, with no bottom sheet`, `pushes no history entry for an inline edit`,
    `pushes one entry while the overlay is open and closes it on Back`,
    `does not push anything while the overlay is shut`,
    `takes its own entry back when the overlay is closed by a button instead`,
    `does not take an entry back when Back is what closed it`,
    `uses the latest close without re-pushing when the component re-renders`,
    `reads the 768 px breakpoint and follows it`,
    `reads as wide where there is no matchMedia at all` ·
    walkthrough `tapping a cell on a phone opens the bottom editor, not an inline input`,
    `Back closes the bottom editor instead of leaving the app`,
    `Back closes the meeting detail overlay instead of leaving the app`
24. **`_restore_point` re-inserted with the original primary key and dropped fields.** It un-deletes
    the row when it is still there, so a replayed undo is a plain 409 rather than a 500, and
    carries `due_date` and `extraction_id` back with everything else.
    `app/routes/transfers.py:_restore_point` ·
    `test_review1_24_undo_restores_the_point_with_its_date_and_survives_a_replay`,
    `test_review1_24_a_point_restored_over_a_row_that_came_back_is_undeleted`
25. **`Retry-After` was honoured unbounded.** Capped at 8 s plus jitter; the rest of the cooldown is
    served by the per-(connection, API) backoff, so a five-minute quota answer no longer holds a
    worker open. `app/google/http.py` ·
    `test_review1_25_a_long_retry_after_is_capped_and_jittered`,
    `test_review1_25_a_short_retry_after_is_still_honoured`

## Low

26. **The SPA served dotfiles.** Any path segment starting with `.` is a 404, with no index.html
    fallback. `app/main.py:is_dotfile` · `test_review1_26_the_spa_does_not_serve_dotfiles`
27. **The bare-id fallback accepted `?`, `#` and `..`.** It is a
    `fullmatch` of `[A-Za-z0-9_-]{20,}` now. `app/routes/common.py` ·
    `test_review1_27_a_bare_workbook_id_has_to_look_like_one`
28. **Four admin readers used `authenticate`.** `/admin/connections`, `/admin/allow-list`,
    `/admin/activity` and `/admin/health` are `require_admin`. Note for the web: `App.tsx` fetches
    `/admin/connections` for the expired-connection banner on every page, so a member now gets a
    403 there and no banner. `app/routes/admin.py` ·
    `test_review1_28_the_admin_readers_are_admin_only`,
    `test_members_cannot_change_or_read_the_allow_list`

    _(web)_ The banner query is gated on the role from `/auth/me`, so a member never asks for it
    and never polls a 403 every fifteen seconds; the Admin page gates its three readers the same
    way and says once, in a line, that those three are admins only.
    `web/src/App.tsx`, `web/src/pages/AdminPage.tsx`, `web/src/api/hooks.ts` ·
    `is not even asked for when a member is signed in`, `is asked for and shown to an admin`,
    `stays unasked while it is still unknown who is signed in`, `carries no colour of its own`
29. **Five hues in play.** The palette is the neutrals plus `--sel` and `--destructive`, and
    nothing else: `--ok`, `--warn`, `--bad`, `--grid-new`, `--grid-key`, `--grid-conflict` and
    `--grid-anchor` are gone from `index.css` and from the Tailwind config. The five grid marks
    wear three variants of the one hue - `sel-tint` (new, edited), `sel-soft` (key), `sel-outline`
    (conflict, and the Custom fill anchor) and `sel-strike` (moves down) - declared once in
    `index.css` and exported as `MARK_CLASS`. The Transfer legend has no swatches: each label wears
    the variant it names, read from the same `MARK_CLASS`, so the legend is the rule rather than a
    copy of it. Warnings, errors, the read-only notice and the expired-connection banner are
    `font-medium` text inside a 1 px border; an ambiguous owner is underlined, not coloured. The
    delete affordances - Remove point, Delete meeting - are the only `text-destructive` in the app,
    and native radios and ticks get `accent-color: hsl(var(--sel))` so the browser's own blue is
    not a sixth hue. Theme unchanged otherwise: black on white, system font, 1 px borders, 4 px
    radius.
    `web/src/index.css`, `web/tailwind.config.js`, `web/src/components/Grid.tsx`,
    `web/src/pages/TransferStep.tsx`, `App.tsx`, `AdminPage.tsx`, `SheetsPage.tsx`,
    `MeetingStep.tsx`, `PointRow.tsx` ·
    `has exactly one coloured token beyond the delete affordance`,
    `still defines the neutrals and the one selection hue in every theme`,
    `no longer defines the hues the review counted`,
    `carries the three grid variants, so the grid and the legend cannot drift`,
    `uses no class built on a hue that is gone`,
    `spends the destructive colour only on the two things that delete something`,
    `gives native radios and ticks the selection hue rather than the browser's`,
    `keeps the tailwind palette down to the neutrals, the selection hue and destructive`,
    `paints all five marks in the one selection hue, as a tint, an outline or a strike`,
    `names no hue but the selection one`.
    Screenshots: `/tmp/mdshots2/1280-02-transfer-legend.png`, `/tmp/mdshots2/1280-03-transfer-fill.png`
30. **The cardinality tests never ran with `WEB_DIST` set.** The module's `client` fixture is
    parametrised over both shapes, which is what the container actually serves. It found one thing:
    with the SPA mounted, unknown paths collapse into the mount's `/{path:path}` label rather than
    `__unmatched__` - one templated label either way, which is what the bound needs.
    `tests/test_telemetry_cardinality.py` ·
    `test_no_path_parameter_value_reaches_a_route_label[web_dist]` and the three bounds, each run
    twice
