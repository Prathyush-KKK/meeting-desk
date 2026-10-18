# Configuration

Every setting is an environment variable (or a line in `.env`), read by `api/app/config.py`.
`.env.example` lists them for development and `.env.live.example` for running with real Google on
your own machine.

## The two switches

Two flags pick the implementation. Everything else below only matters when the flag is off.

| flag | on (`1`, the default) | off (`0`) |
| --- | --- | --- |
| `FAKE_GOOGLE` | Calendar, Drive, Docs, Gmail, Sheets and People come from `api/app/google/fake.py`, built from the seed and the sheet fixtures; the clock is pinned to the demo world. | The real clients under `api/app/google/` (`calendar.py`, `drive.py`, `docs.py`, `gmail.py`, `sheets.py`, `people.py`) run as the admin connections' refresh tokens, through one HTTP layer (`http.py`: bearer tokens, 401 refresh, 429 backoff, error mapping). Needs the **admin connections** block below. |
| `FAKE_LLM` | A rule-based extractor that reads headings such as "Next steps", "Decided:" and "Risk:" - no model, no network. | `EXTRACTION_PROVIDER` picks the model; see **Extraction** below. |

## Core

| variable | default | what it is |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | Anything but `local` or `test` is a deployment: the app then refuses to start with the default `SESSION_SECRET`, one shorter than 32 characters, `AUTH_DEV_USER` set, or `*` in `CORS_ORIGINS`, and cookies are `Secure`. |
| `DATABASE_URL` | local Postgres | `postgresql+psycopg://...` or `sqlite:///./meeting-desk.db`. `make migrate` runs Alembic against it. |
| `SESSION_SECRET` | dev value | Signs the session cookie. 32+ characters in a deployment. |
| `AUTH_DEV_USER` | empty | Every request is signed in as this email without Google. Local and tests only. |
| `BOOTSTRAP_ADMINS` | empty | Comma-separated emails put on the allow-list as admins at every start - how the first admin gets in. |
| `GOOGLE_HOSTED_DOMAIN` | empty | Only accounts of this Workspace domain may sign in or be connected. Empty: any Google account (the allow-list still decides). |
| `WEB_DIST` | empty | Path to the built web app (`web/dist`). Set, the API serves it at `/` with an SPA fallback. |
| `WEB_BASE_URL`, `CORS_ORIGINS` | `:5173` | Where the web app lives when it is served separately (Vite in development). |

## Display

| variable | default | what it is |
| --- | --- | --- |
| `DISPLAY_TIMEZONE` | `UTC` | The IANA zone every time is shown in - the meeting list, manual meetings, due dates, "read HH:MM". Relative dues ("by Friday") are resolved in it. |
| `WORKSTREAMS` | `Product,Engineering,Design,Growth,Operations,Hiring` | The workstreams offered on a meeting and a point. Any workstream already used is offered too. |
| `CALENDAR_LOOKBACK_DAYS`, `CALENDAR_LOOKAHEAD_DAYS` | `30`, `14` | The calendar window of the meeting list. Captured meetings stay listed whatever their date. |

## Notifications

| variable | what it is |
| --- | --- |
| `NOTIFY_WEBHOOK_URL` | After every transfer, post who sent which points to which tab (up to ten lines, then "...and N more", plus the sheet's link). The body is `{"text": ...}`, which works with **Slack** and **Mattermost** incoming webhooks, **Google Chat** space webhooks, and **Discord** webhook URLs with `/slack` on the end. Sent after the response; a failing webhook is logged and counted (`provider="webhook"`) but never fails the transfer. |

## Admin connections (`FAKE_GOOGLE=0`)

[GOOGLE_SETUP.md](GOOGLE_SETUP.md) walks through creating the OAuth client.

The Google clients never hold credentials of their own: every call runs as one of the admin
connections made through **Admin → Connect an account** (`GET /admin/connections/connect`, an
authorization-code flow with `access_type=offline`, `prompt=consent` and
`include_granted_scopes=true`). The refresh token is Fernet-encrypted before it is stored.

| variable | used by | what it is |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | sign-in, the connect flow, every token refresh | The OAuth client. Register both `GOOGLE_OIDC_REDIRECT_URI` and `GOOGLE_CONNECT_REDIRECT_URI` on it. |
| `GOOGLE_USE_GMAIL` | Gmail | `1`. Off: `gmail.readonly` is not requested and the recap email source on the Notes step reads "Gmail is off". Gmail is a restricted scope, so turn it off for an External OAuth app you don't want to send for Google's verification. |
| `GOOGLE_USE_DIRECTORY` | People | `1`. Off: `directory.readonly` is not requested and owners resolve against the meeting's attendees only. Turn it off for personal (non-Workspace) accounts. |
| `GOOGLE_CONNECT_REDIRECT_URI` | the connect flow | Where Google sends the admin back; default `http://localhost:8000/admin/connections/callback`. |
| `MEETING_DESK_TOKEN_KEY` | token storage | The Fernet key for refresh tokens at rest. `make token-key` prints one. Required when `FAKE_GOOGLE=0`. |
| `MEETING_DESK_TOKEN_KEY_VERSION` | token storage | The number stored on `connections.key_version` for rows encrypted with the current key (default `1`). |
| `MEETING_DESK_TOKEN_KEY_PREVIOUS` | token storage, during a rotation | The key being retired. Rows are read with the key matching their version first, then the other one. Rotate: set PREVIOUS to the old key, KEY to a new one, bump VERSION, deploy, `POST /admin/connections/rotate-keys`, then drop PREVIOUS. |
| `GOOGLE_API_TIMEOUT_SECONDS` | all clients | Per-request timeout (30). |
| `GOOGLE_MAX_RETRIES`, `GOOGLE_BACKOFF_BASE_SECONDS` | Sheets writes and reads | 429 / `rateLimitExceeded` retries with exponential backoff (5 tries, 0.5 s base: 0.5, 1, 2, 4, 8). A `Retry-After` is honoured, capped at 8 s and jittered, so a quota answer of minutes does not hold the request open. |
| `GOOGLE_CONNECTION_BACKOFF_SECONDS` | all clients | After the retries run out, that (connection, Google API) pair is skipped for this long (doubling on repeats) - quotas are per API, so a rate-limited Calendar does not stop Sheets - and the other connections carry on. Calendar never retries inside a request: the list is served from cache. |
| `SHEETS_MAX_ROWS` | Sheets | The table region is never read past this row (5000). |
| `CALENDAR_CACHE_SECONDS` | Calendar | The in-process cache per connection (60 s). |

Scopes requested (`api/app/google/oauth.py`, explained in [GOOGLE_SETUP.md](GOOGLE_SETUP.md)): `calendar.readonly`, `drive.readonly`,
`documents.readonly`, `gmail.readonly`, `spreadsheets`, `directory.readonly`, plus `openid`,
`email` and `profile` to identify the account. The Admin page shows which of these a connection
granted; `?missing=` on the callback names any it did not.

What each client calls, and which connection it runs as:

| client | endpoints | connection |
| --- | --- | --- |
| Calendar | `events.list` on `primary` (`singleEvents=true`, `orderBy=startTime`, a `fields` mask limited to what `models.py` stores, all pages) | every healthy admin connection; merged and de-duplicated on `iCalUID` by the route |
| Drive | `files.list` (`name contains '<title>' and name contains 'Notes by Gemini'`, `createdTime` within ±2 h of the start), `files.get?fields=name,capabilities/canEdit` | the first connection that finds it / can edit |
| Docs | `documents.get?includeTabsContent=true`, tabs walked recursively, "Full notes" preferred | the first connection that can read it |
| Gmail | `messages.list` with `from:gemini-notes@google.com "<title>" after:<date>`, then `messages.get?format=full`; HTML to text | the connection whose mailbox received it |
| Sheets | `spreadsheets.get`, `values.batchGet` (first 40 rows, then the table region, then `valueRenderOption=FORMULA`), `spreadsheets.get?includeGridData` on the header row and first data row (validation, number formats), one `spreadsheets.batchUpdate` per write (`insertDimension`, `copyPaste` `PASTE_FORMULA`, `updateCells`) | reads: the workbook's connection, then any; writes: the workbook's connection only |
| People | `people:searchDirectoryPeople` (prefix query, domain profiles) | any healthy connection |

## Extraction (`FAKE_LLM=0`)

Set `FAKE_LLM=0` and pick a provider with `EXTRACTION_PROVIDER`. Whichever answers, the notes go
through the same prompt (`api/app/extract/prompt.py`) and come back in the same JSON schema
(`schema.py`); an answer that is not the schema is retried once. Owners, dates and statuses are
then resolved by code, never by the model. `GET /health` reports the provider that is running.

| `EXTRACTION_PROVIDER` | what it uses | settings |
| --- | --- | --- |
| `openai` | **Any OpenAI-compatible `/chat/completions` endpoint**: OpenAI, [Ollama](https://ollama.com), OpenRouter, LM Studio, vLLM, Together, Groq, ... Plain `httpx`, no SDK. | `LLM_BASE_URL` (default `https://api.openai.com/v1`), `LLM_API_KEY` (also read from `OPENAI_API_KEY`; optional for a local server), `LLM_MODEL` (default `gpt-4.1-mini`), `LLM_REASONING_EFFORT` (sent only when set), `LLM_TIMEOUT_SECONDS` (180). JSON mode is asked for and dropped (once, remembered) if the endpoint refuses it. |
| `anthropic` | **Claude** through the Anthropic SDK, with the schema as a structured output. Needs the `anthropic` extra (`pip install '.[anthropic]'`, or `make install-llm`). | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-5-5`), `ANTHROPIC_EFFORT` (`medium`). Server-side refusal fallbacks are on. |
| `vertex` | **Gemini on Vertex AI**, schema-constrained (`response_schema`), temperature 0. Needs the `vertex` extra. | `VERTEX_PROJECT`, `VERTEX_LOCATION` (`us-central1`), `VERTEX_MODEL` (`gemini-2.5-flash`). Credentials from Application Default Credentials. |
| `bedrock` | **Amazon Bedrock**: its OpenAI-compatible endpoint when `BEDROCK_BASE_URL` and `AWS_BEARER_TOKEN_BEDROCK` are both set (plain `httpx`), otherwise the Converse API with the schema as a forced tool (needs the `bedrock` extra). | `BEDROCK_BASE_URL`, `AWS_BEARER_TOKEN_BEDROCK` (or `BEDROCK_API_KEY`), `BEDROCK_MODEL_ID`; or `BEDROCK_REGION` (`us-east-1`), `BEDROCK_MODEL` and the AWS credential chain. |
| `bedrock_openai` | Forces Bedrock's OpenAI-compatible endpoint. | as above |

Examples:

```bash
# OpenAI
FAKE_LLM=0 EXTRACTION_PROVIDER=openai LLM_API_KEY=sk-... LLM_MODEL=gpt-4.1-mini

# A local model with Ollama - nothing leaves your machine
ollama pull llama3.1
FAKE_LLM=0 EXTRACTION_PROVIDER=openai LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=llama3.1
# (from inside Docker: LLM_BASE_URL=http://host.docker.internal:11434/v1)

# OpenRouter
FAKE_LLM=0 EXTRACTION_PROVIDER=openai LLM_BASE_URL=https://openrouter.ai/api/v1 LLM_API_KEY=... LLM_MODEL=<vendor/model>

# Claude
FAKE_LLM=0 EXTRACTION_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...
```

Other extraction settings:

| variable | what it is |
| --- | --- |
| `EXTRACT_FALLBACK_TO_BEDROCK` | With `EXTRACTION_PROVIDER=vertex`, a Vertex failure is retried on Bedrock; the extraction record and the response carry `fallback_from=vertex` so the UI can say who answered. |
| `EXTRACTION_MAX_OUTPUT_TOKENS` | 8192 (Claude gets at least 16000, since its thinking shares the budget). |
| `BEDROCK_TIMEOUT_SECONDS` | Read timeout on Bedrock's OpenAI-compatible endpoint (180). |

A small or local model works best on notes that have a "Next steps" section; the bigger hosted
models also cope with a raw transcript.

## Jobs (`JOBS_ENABLED=1`)

| variable | what it is |
| --- | --- |
| `JOBS_ENABLED` | Off (default): `POST /meetings/{id}/extract` runs inline and answers with the points. On: the API enqueues, answers `{"queued": true, "poll": "/extractions/{id}"}`, and `GET /extractions/{id}` reports `queued`, `running`, `done` or `error` and the points once done. |
| `JOBS_DATABASE_URL` | Where procrastinate keeps its jobs; defaults to `DATABASE_URL` (Postgres only). `make jobs-schema` once, then `make worker`. |

The worker runs three tasks: `meeting_desk.extract_meeting` on demand,
`meeting_desk.fetch_missing_docs` every 5 minutes (a captured calendar meeting that ended in the
last hour and has no Notes by Gemini note yet gets one lookup; a found doc is imported and pinned
on the meeting), and `meeting_desk.token_health` daily (a refused refresh token marks the
connection `expired` with `last_error`; the Admin banner names it). Without a queue,
`POST /admin/connections/health` and `POST /admin/jobs/fetch-docs` run the same functions by hand.

## Telemetry

`METRICS_ENABLED` (1), `METRICS_PORT` (9464), `METRICS_HOST`, `LOG_LEVEL` (INFO), and `APP_VERSION` /
`GIT_COMMIT` for `app_build_info`. See [TELEMETRY.md](TELEMETRY.md).

