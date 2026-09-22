# Review 1 (adversarial, pre-production) - 22 Sep 2026

Findings ranked by severity. Each item: file:line, scenario, fix. See the fix log in docs/REVIEW-1-FIXES.md once done.

## Critical
1. transfers.py:332-345 Undo deletes the inserted row even if other columns were filled since. Fix: hash the whole row range at write time into snapshot; re-hash before delete; 409 with row contents on mismatch.
2. config.py:37,42 main.py:95 Default session secret and AUTH_DEV_USER accepted in production. Fix: in create_app, when environment not in (local, test): raise on default secret, on len < 32, on non-empty auth_dev_user.

## High
3. jobs/token_health.py:36-40 Marks expired on any GoogleError. Fix: only AuthExpired sets expired; other errors set last_error only.
4. web SheetsPage.tsx:109-112 `before` recomputed from latest poll, defeating the pre-save guard. Fix: capture {before, after} at edit time in pending and send that before.
5. notes_store.py:32-36, routes/notes.py:350-357 vs unique constraint: re-paste after soft delete → 500. Fix: partial unique index (deleted_at IS NULL) via migration or un-delete existing row; catch IntegrityError → 409.
6. web SheetsPage.tsx:245-261 Grid overflows its slot at 390 px and 768 px, painting over Save and Add row. Fix: overflow-hidden on the slot and maxHeight 100%, or let main scroll on mobile.
7. routes/sheets.py:133-144 /sheets/save writes header row cells. Fix: reject r <= header_row or r > last_table_row.
8. planner.py:185-193, AddRowPanel.tsx:125 Add row above the first data row copies header formulas/formatting. Fix: skip fill when insert_at - 1 <= header_row; use the row below as source or leave blank.
9. transfers.py:204-254, sheets.py:246-295 Sheets write outside DB transaction, no idempotency key. Fix: client batch_id; insert transfers as pending and commit before the Google call; commit completion; repeat batch_id returns stored result.

## Medium
10. google/sheets.py:304,408-415 Dates re-parsed from due_text at write time vs points.due_date. Fix: pass due_date through PointForSheet; text parse only when null.
11. postprocess.py:135,159-171, sheets/dates.py:18 "end of month", EOW, EOD, "by the 31st", "next Thursday" wrong or None. Fix: explicit handling; next <weekday> = following week.
12. extract/prompt.py:20-37,66-71 No instruction to ignore instructions in notes; fence not escaped. Fix: add rule; neutralise delimiter; random per-call delimiter.
13. extract/schema.py, parse.py:63-90 Schema not strict; {} counts as success. Fix: additionalProperties false, propertyOrdering, forbid extras, payload missing all four keys → InvalidModelOutput retry.
14. layout.py:266-287 region_hash covers only header..last_table_row. Fix: extend a few rows above and below; hash the exact rows a plan touches.
15. routes/sheets.py:190 add-row skips guard on empty region_hash. Fix: Field(min_length=64), always compare.
16. transfers.py:266-275 Repeat check scans whole transfers table. Fix: indexed text_norm column scoped by workbook.
17. google/http.py:98,112-118,166-171 Backoff keyed by connection only; a Calendar 429 blocks Sheets. Fix: key by (connection, provider); rate-limit refresh=true.
18. routes/admin.py:144-146 vs meetings.py:51-56 Connect does not clear calendar_cache. Fix: clear on connect/disconnect; key on healthy connection set.
19. helm values.yaml:190-196, externalsecret.yaml MEETING_DESK_TOKEN_KEY_PREVIOUS required. Fix: behind a values flag or dataFrom find.
20. main.py:96-102 CORS "*" with credentials not rejected. Fix: raise outside local.
21. main.py:95 OAuth state cookie not Secure, no max_age. Fix: https_only outside local, max_age 600, distinct cookie name.
22. auth/oidc.py, google/oauth.py No PKCE. Fix: S256 on both flows.
23. Grid.tsx, MeetingStep.tsx Mobile: inline 24 px input instead of bottom editor with 44 px targets; overlay does not push history. Fix: md:hidden bottom sheet editor; pushState + popstate.
24. transfers.py:377-398 _restore_point re-inserts with original PK (500 on replay), drops due_date/extraction_id. Fix: un-delete if present; carry fields in snapshot.
25. google/http.py:218,255-262 Retry-After honoured unbounded. Fix: min(retry_after, 8 s) + jitter, then cooldown.

## Low
26. main.py:168-195 SPA serves dotfiles. Fix: 404 any segment starting with ".".
27. routes/common.py:136-146 bare id fallback accepts ? # .. . Fix: fullmatch [A-Za-z0-9_-]{20,}.
28. routes/admin.py readers use authenticate not require_admin. Fix: AdminUser on the four readers.
29. index.css, Grid.tsx, TransferStep.tsx Five hues in play. Fix: collapse to one hue with tint/outline variants; text legend.
30. tests/test_telemetry_cardinality.py Not run with WEB_DIST set. Fix: parametrise over web_dist.

## Verified correct (do not re-check)
insertDimension index math; batchUpdate op order; keys allocated after re-read; region_hash catches appended rows; four 409 paths; soft-delete filtering; transfer DB work is one transaction; iCalUID de-dup; resync scope; Docs tab walking; Gmail quoting; Drive filters; People prefix search and ambiguity; 429 bounds; token encryption/rotation and log scrubbing; metrics port separation; probes; Dockerfile user; alembic matches models; TanStack Virtual row numbers; optimistic rollback; polling loop; SPA mount ordering; fake reset dev-only.
