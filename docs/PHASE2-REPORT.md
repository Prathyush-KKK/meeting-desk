# Phase 2 report (Google and extraction) - 22 Sep 2026

`make check` = ruff + pytest, green. `cd api && .venv/bin/python -m pytest -q` → 348 passed
(247 from phase 1, all still passing; 101 new). `alembic check` still reports no drift: no table
changed. `docker compose config` valid. No web work, no Helm.

## What landed

```
api/app/google/
  interface.py   + RateLimited, AuthExpired; DriveFile.created_at; Drive search on creation time
                   and the "Notes by Gemini" marker; recap_query() / quoted_phrase() for Gmail
  http.py        one HTTP door: bearer per connection, 401 → refresh once, 429 / 403
                 rateLimitExceeded → exponential backoff (max 5) then per-connection cooldown,
                 5xx retried, Google error JSON → NotFoundError / PermissionDenied / GoogleError
  tokens.py      TokenCipher (Fernet, MEETING_DESK_TOKEN_KEY[_PREVIOUS|_VERSION], dual-read,
                 rotate_connections), DbRefreshTokens, TokenBroker (access tokens, invalid_grant →
                 AuthExpired), StaticTokens / InMemoryRefreshTokens for tests
  oauth.py       "Connect an account": authlib OAuth2Client, the scope list, offline access,
                 prompt=consent, include_granted_scopes, userinfo, store_connection (upsert)
  picker.py      first_able(): the first healthy connection able to see an item, which one, why not
  calendar.py    events.list per connection: singleEvents, orderBy=startTime, fields mask, paging,
                 60 s cache per (connection, window), all-day events, organizer zone kept, IST shown
  drive.py       files.list q on name + marker + createdTime window; files.get capabilities/canEdit
  docs.py        documents.get?includeTabsContent=true, tabs walked recursively, paragraphs,
                 headings, bullets (nested), tables, smart chips → lines; preferred_tab()
  gmail.py       messages.list + messages.get?format=full, MIME walk, HTML → text
  people.py      people:searchDirectoryPeople prefix query, domain profiles
  sheets.py      the five-call read (meta, first 40 rows, table region, FORMULA render, grid data on
                 header + first data row), ONE_OF_LIST / ONE_OF_RANGE dropdowns, one batchUpdate
                 (insertDimension inheritFromBefore, copyPaste PASTE_FORMULA, updateCells grouped
                 per row run; dates as serials, text as stringValue), 429 × 5, protected-range
                 naming on 403, read_cells for the pre-save re-read
  real.py        RealGoogle assembled from settings + DB + optional httpx transport
api/app/sheets/dates.py      Sheets serials; "written as dates when it reads as one, else text"
api/app/extract/
  prompt.py      the deterministic system + user prompt (rules, meeting context, notes; 200k cap)
  parse.py       model answer → ExtractionOutput; fences / preambles tolerated; InvalidModelOutput
  vertex.py      GenerativeModel in asia-south1, response_mime_type json, response_schema, temp 0,
                 one retry; lazy SDK import; model_factory hook for tests
  bedrock.py     converse() in ap-south-1, schema as a forced tool; lazy boto3; client hook
  fallback.py    Vertex then Bedrock behind EXTRACT_FALLBACK_TO_BEDROCK; usage.fallback_from
  postprocess.py first-name candidates now include one-letter-apart spellings (see decisions)
api/app/jobs/
  extract.py     start_extraction / perform_extraction / run_extraction; status via usage["job"]
  fetch_doc.py   fetch_missing_docs(): meetings that ended in the last hour, no Gemini note → look
                 up, import Full notes, pin the attachment
  token_health.py RateLimited is not "expired"
  queue.py       procrastinate App: extract_meeting on demand, fetch_missing_docs */5 * * * *,
                 token_health daily; plain run_* functions the tests call; worker entry point
  schema.py      `make jobs-schema`
api/app/runtime.py           settings + db + clock + google + extraction for the API and the worker
api/app/notes_store.py       save_note() shared by the routes and the Doc fetch job
api/app/routes/
  admin.py       GET /admin/connections/connect, GET /admin/connections/callback,
                 POST /admin/connections/rotate-keys, POST /admin/jobs/fetch-docs
  extract.py     queue path (queued → poll) beside the inline path; GET /extractions/{id} + points
  common.py      pick_for(): the picker plus marking an expired connection in this session
  notes.py, workbooks.py, meetings.py   every read through the picker; recap_query; preferred_tab
api/app/main.py  create_app(settings, transport=, jobs=, extraction=); RateLimited → 503,
                 AuthExpired → 502; lifespan opens/closes the queue
api/app/config.py  token keys, connect redirect, Google API knobs, Bedrock model, jobs
api/tests/
  conftest.py    the socket guard (autouse): any AF_INET/AF_INET6 socket fails the test
  google_mock.py MockGoogleApi over httpx.MockTransport, routes by (method, path), records requests
  fixtures/google/*.json   30 hand-written responses: Calendar (2 pages, EDT organizer, all-day,
                 cancelled), Drive, Docs (nested tabs, table, smart chip), Gmail (HTML), People,
                 Sheets (meta, window, region, formulas, grid data, protection), errors, tokens
  fixtures/llm/*.json      recorded Vertex and Bedrock outputs, valid and invalid
  test_google_http.py test_tokens.py test_google_calendar_drive.py
  test_google_docs_gmail_people.py test_google_sheets.py test_oauth_connect.py
  test_real_mode_end_to_end.py (FAKE_GOOGLE=0 through the app) test_llm_providers.py
  test_jobs_queue.py test_picker.py; test_extract.py + the ambiguity cases
README.md        "The switches, and what each client needs": env vars per client, FAKE_GOOGLE /
                 FAKE_LLM, connect flow, key rotation, jobs
Makefile         install-llm, jobs-schema, worker, token-key    .env.example, docker-compose (worker)
pyproject.toml   cryptography, procrastinate, psycopg-pool core; [llm] = aiplatform + boto3
```

## Decisions the spec left open

1. **httpx, not googleapiclient.** httpx is already a core dependency, needs no discovery document,
   and `httpx.MockTransport` lets the contract tests assert the exact request (query, fields mask,
   batchUpdate body) against hand-written responses. google-api-python-client was dropped from the
   extras; the Vertex and Bedrock SDKs stay optional (`[llm]`) and are imported lazily.
2. **Job status without a column.** `extractions` is spec section 4 exactly; a queued or running
   extraction keeps `{"job": {"status": ...}}` in `usage` until the provider's usage replaces it.
   `GET /extractions/{id}` answers `queued | running | done | error` and the points once done.
3. **Who marks a connection expired.** The token broker raises `AuthExpired`; the route or job that
   met it marks the row in its own session (`pick_for`, the calendar merge, token_health). A second
   writer from inside the broker deadlocked SQLite and is a race on Postgres too.
4. **Drive search on `createdTime`, not `modifiedTime`.** A recurring meeting's Notes doc has the
   same name every week and is edited long after it appears; creation time is what ties it to one
   instance. The interface parameters were renamed `created_after` / `created_before` (the fake
   follows). The search also requires "Notes by Gemini" in the name and the Docs MIME type.
5. **Dates in one batchUpdate.** Everything goes out as `updateCells` in the single
   `spreadsheets.batchUpdate` (insertDimension + copyPaste need it). A date column gets a serial
   number when the value reads as a date (ISO, then the extractor's dateparser rules), else text;
   text is always `stringValue`, so nothing is auto-parsed. `values.batchUpdate` with USER_ENTERED
   would have meant a second call per transfer.
6. **Ambiguity with near-identical first names.** The brief's case (Prathyush Kodhanpur and Pratyush
   Chaudhary both attendees, bare "Prathyush") is not an exact first-name collision, so the resolver
   now treats first names one letter apart (four letters or more) as competing candidates: two in
   the room → `owner_ambiguous` with both, `owner_email` empty; one → resolved. This changes phase 1's
   `test_a_first_name_shared_by_two_attendees_is_flagged_not_guessed`, which had encoded the
   opposite (exact-only) rule.
7. **The People directory** is asked after the model call, only for owners the attendee list did not
   settle, with the first token of the name, through the first connection that answers. In fake
   mode the seed directory is used up front as before (the rule-based provider recognises owner
   lines by name). The alias table is still `seed_data.ALIASES`; there is no aliases table in the
   spec.
8. **The Doc re-check imports.** When `fetch_missing_docs` finds the doc it imports the preferred
   tab as a `gemini_doc` note (actor `meeting-desk (doc fetch)`) and pins the attachment on the
   meeting; the Sources line then shows it without another Drive search. Only captured calendar
   meetings (rows in `meetings`) are checked - a calendar-only card has nothing to attach to.
9. **Calendar never retries inside a request.** The route already serves the list from cache with
   "updated N min ago"; a 429 backs the connection off (60 s, doubling, capped at 10 min) and the
   other connections carry on. Sheets reads and writes retry five times in-call.
10. **Bedrock model default** is a Claude 3.5 Sonnet id for ap-south-1; Bedrock has no Gemini. It
    is configuration and must be confirmed per account.
11. **Token key env names** are `MEETING_DESK_TOKEN_KEY`, `_PREVIOUS`, `_VERSION`, with the field
    names still accepted as keywords (`Settings(token_key=...)` beats a stray env var).
12. **Protected ranges.** On a 403 from batchUpdate the client fetches `protectedRanges` for the
    sheet and names the one the write overlaps, with its editors; the route's message carries it.

## Known gaps

- Real Google has not been exercised against a live project (no credentials here); the clients
  are built from the public REST shapes and the recorded fixtures. First live run: confirm the
  Docs tab nesting of a current Notes by Gemini doc, the recap sender address, and the Bedrock
  model id.
- The procrastinate worker was not run against Postgres here (SQLite only); the queue path is
  tested with `InMemoryConnector` and the job functions directly. `make jobs-schema` +
  `make worker` are the first thing to try on a Postgres box.
- `dateparser` needs an explicit `TIMEZONE` (set); a host `TZ` like `Asia/Calcutta` trips
  `tzlocal` otherwise.
- Sheets `read_tab` bounds the region read at `SHEETS_MAX_ROWS` (5000); a larger tab is read only
  that far.
- Alerts per `SIALET-ALERT-EMISSION-STANDARD` (OAuth refresh failures, extraction error rate,
  Sheets 4xx/5xx) are not emitted yet - phase 4 alongside the chart.
- Web app and Helm: phases 3 and 4.
