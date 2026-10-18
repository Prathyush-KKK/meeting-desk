# Meeting Desk

Meetings in, rows in a Google Sheet out. Capture a meeting, keep its notes, turn them into points,
and transfer those points into the roadmap workbook without retyping anything.

Specs: `MEETING-DESK-TECH-SPEC-V6-22SEP.md` (sections 4, 5 and 7 are binding) and
`MEETING-DESK-HANDOVER.md` (repo layout, phases, acceptance).

## Where the build is

**All four phases are done: the backend core, the real Google clients, token storage, extraction
on Vertex / Bedrock, the job queue, the web app, and the deployment.** Everything Google touches
sits behind a Protocol in `api/app/google/`, with an in-memory fake selected by `FAKE_GOOGLE=1` and
the real clients (plain `httpx` against the REST endpoints) selected by `FAKE_GOOGLE=0`. Extraction
sits behind `api/app/extract/provider.py`, with a rule-based fake selected by `FAKE_LLM=1` and
Gemini on Vertex AI (Bedrock as the configured fallback) selected by `FAKE_LLM=0`. The prototype UI
lives in `web/`, wired to the API through TanStack Query - see `web/README.md`. One image serves
the API and that build; a Helm chart in `deploy/helm/meeting-desk/` deploys it, the worker, the
migration hook and the alert rules.

See `docs/PHASE1-REPORT.md` … `docs/PHASE4-REPORT.md`, and
`docs/ALERT-EMISSION-STANDARD-SUMMARY.md` for the telemetry the service must emit.

## Run it locally

```bash
make install          # creates api/.venv (Python 3.12) and installs the API with its dev extras
make run              # http://localhost:8000 with FAKE_GOOGLE=1, FAKE_LLM=1 and a SQLite file

make web-install      # pnpm install in web/
make web-dev          # http://localhost:5173, proxying /api to the API above
```

`make run` sets three things that matter:

| variable | what it does |
| --- | --- |
| `FAKE_GOOGLE=1` | Calendar, Drive, Docs, Gmail, Sheets and People come from `api/app/google/fake.py`, built from the prototype's seed and the sheet fixtures. No network, no credentials. |
| `FAKE_LLM=1` | Extraction runs the rule-based provider ported from the prototype's `lib/extract.ts`. |
| `AUTH_DEV_USER` | Every request is signed in as that email, skipping Google OIDC. Local and tests only - a deployment must leave it empty. |

Open http://localhost:8000/docs for the API. The database is seeded with the prototype's world:
six meetings (two of them calendar-only so the Step 1 list has something to merge), one note, six
points, three connected workbooks and two admin connections.

### The walkthrough

Through the app: `web/README.md` walks it screen by screen (paste, extract, points, transfer, the rows in Sheets, an edit, Add row above a row), and `web/e2e/walkthrough.mjs` drives the same path through a browser.

Through the API alone, which is `api/tests/test_walkthrough.py` by hand:

```bash
BASE=http://localhost:8000

# 1. Paste with no meeting selected - a manual meeting appears, titled from the first line
curl -s -X POST $BASE/notes/quick -H 'content-type: application/json' -d '{
  "text": "Vendor call with Maya\n\nThe Next Steps\nAlex S: Send the questionnaire by Friday\nDaniel Okafor: Mirror OpenRates before 3 Oct\nDecided: the Owner column holds a person, not a team"
}'

# 2. Extract, then look at the points
curl -s -X POST $BASE/meetings/<meeting-id>/extract
curl -s "$BASE/points?meeting_id=<meeting-id>"

# 3. Read the tab, preview the append, then write it
curl -s "$BASE/workbooks"
curl -s "$BASE/workbooks/<workbook-id>/tabs/t1"
curl -s -X POST $BASE/transfers/preview -H 'content-type: application/json' -d '{
  "workbook_id": "<workbook-id>", "sheet_id": "t1", "mode": "append", "point_ids": ["<point-id>"]
}'
curl -s -X POST $BASE/transfers/execute -H 'content-type: application/json' -d '{
  "workbook_id": "<workbook-id>", "sheet_id": "t1", "mode": "append",
  "point_ids": ["<point-id>"], "region_hash": "<from the tab read>"
}'

# 4. The rows are there, keyed, with the meeting title in Notes
curl -s "$BASE/workbooks/<workbook-id>/tabs/t1"
```

## The switches, and what each client needs

Two flags pick the implementation. Everything else below only matters when the flag is off.

| flag | on (`1`, the default) | off (`0`) |
| --- | --- | --- |
| `FAKE_GOOGLE` | Calendar, Drive, Docs, Gmail, Sheets and People come from `api/app/google/fake.py`, built from the seed and the sheet fixtures; the clock is pinned to the demo world. | The real clients under `api/app/google/` (`calendar.py`, `drive.py`, `docs.py`, `gmail.py`, `sheets.py`, `people.py`) run as the admin connections' refresh tokens, through one HTTP layer (`http.py`: bearer tokens, 401 refresh, 429 backoff, error mapping). Needs the **admin connections** block below. |
| `FAKE_LLM` | The rule-based provider ported from the prototype's `lib/extract.ts`. | `EXTRACTION_PROVIDER` picks Vertex or Bedrock; needs the **extraction** block below and `make install-llm` (not for Bedrock's OpenAI-compatible endpoint, which is plain `httpx`). |

### Admin connections (`FAKE_GOOGLE=0`)

The Google clients never hold credentials of their own: every call runs as one of the admin
connections made through **Admin → Connect an account** (`GET /admin/connections/connect`, an
authorization-code flow with `access_type=offline`, `prompt=consent` and
`include_granted_scopes=true`). The refresh token is Fernet-encrypted before it is stored.

| variable | used by | what it is |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | the connect flow, every token refresh | The internal OAuth client (Workspace-internal, so tokens do not expire on a timer). Register both `GOOGLE_OIDC_REDIRECT_URI` and `GOOGLE_CONNECT_REDIRECT_URI` on it. |
| `GOOGLE_CONNECT_REDIRECT_URI` | the connect flow | Where Google sends the admin back; default `http://localhost:8000/admin/connections/callback`. |
| `GOOGLE_HOSTED_DOMAIN` | sign-in and connect | Only accounts of this Workspace may sign in or be connected. |
| `MEETING_DESK_TOKEN_KEY` | token storage | The Fernet key for refresh tokens at rest. `make token-key` prints one. Required when `FAKE_GOOGLE=0`. |
| `MEETING_DESK_TOKEN_KEY_VERSION` | token storage | The number stored on `connections.key_version` for rows encrypted with the current key (default `1`). |
| `MEETING_DESK_TOKEN_KEY_PREVIOUS` | token storage, during a rotation | The key being retired. Rows are read with the key matching their version first, then the other one. Rotate: set PREVIOUS to the old key, KEY to a new one, bump VERSION, deploy, `POST /admin/connections/rotate-keys`, then drop PREVIOUS. |
| `GOOGLE_API_TIMEOUT_SECONDS` | all clients | Per-request timeout (30). |
| `GOOGLE_MAX_RETRIES`, `GOOGLE_BACKOFF_BASE_SECONDS` | Sheets writes and reads | 429 / `rateLimitExceeded` retries with exponential backoff (5 tries, 0.5 s base: 0.5, 1, 2, 4, 8). A `Retry-After` is honoured, capped at 8 s and jittered, so a quota answer of minutes does not hold the request open. |
| `GOOGLE_CONNECTION_BACKOFF_SECONDS` | all clients | After the retries run out, that (connection, Google API) pair is skipped for this long (doubling on repeats) - quotas are per API, so a rate-limited Calendar does not stop Sheets - and the other connections carry on. Calendar never retries inside a request: the list is served from cache. |
| `SHEETS_MAX_ROWS` | Sheets | The table region is never read past this row (5000). |
| `CALENDAR_CACHE_SECONDS`, `CALENDAR_LOOKBACK_DAYS` | Calendar | The in-process cache per connection (60 s) and the window (last 7 days and today). |

Scopes requested (`api/app/google/oauth.py`): `calendar.readonly`, `drive.readonly`,
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

### Extraction (`FAKE_LLM=0`)

| variable | used by | what it is |
| --- | --- | --- |
| `EXTRACTION_PROVIDER` | provider selection | `fake`, `vertex`, `bedrock` or `bedrock_openai`. `bedrock` is the OpenAI-compatible endpoint when `BEDROCK_BASE_URL` and `AWS_BEARER_TOKEN_BEDROCK` are both set, and the Converse API otherwise; `bedrock_openai` forces the OpenAI-compatible endpoint. `GET /health` reports the one running as `extraction_provider` (`bedrock_openai` or `bedrock`). |
| `VERTEX_PROJECT`, `VERTEX_LOCATION`, `VERTEX_MODEL` | Vertex | The GCP project, `asia-south1`, `gemini-2.5-flash`. Credentials come from Application Default Credentials (a service account on the pod). The call is schema-constrained: `response_mime_type=application/json`, `response_schema` from `schema.py`, temperature 0, one retry on invalid output. |
| `BEDROCK_BASE_URL`, `AWS_BEARER_TOKEN_BEDROCK`, `BEDROCK_MODEL_ID` | Bedrock, OpenAI-compatible endpoint | The nutrition service's Bedrock access under its own names, pasted as they are: e.g. `https://bedrock-mantle.us-east-1.api.aws/openai/v1`, a Bedrock API key (sent as `Authorization: Bearer`), `google.gemma-4-26b-a4b`. One `POST {BEDROCK_BASE_URL}/chat/completions` with plain `httpx` (`app/extract/openai_compat.py`): the `prompt.py` prompt with the schema appended to the system message, temperature 0, `max_tokens` from `EXTRACTION_MAX_OUTPUT_TOKENS`, `response_format: json_object` - dropped (and remembered for the process) if the model answers 400 to it. One retry on an answer that is not the schema, telling the model what was wrong. 401/403 is "credentials refused", 404 names the model, 429 is backed off once; none of them moves the breaker. The region is read off the URL. `BEDROCK_API_KEY` also works for the key. |
| `BEDROCK_REGION`, `BEDROCK_MODEL` | Bedrock, Converse API | `ap-south-1` and the model id (Bedrock has no Gemini; a Claude id is the default - confirm it is enabled in the account). Credentials come from the AWS chain (IRSA on the pod, or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`). The schema is enforced through a forced tool call on the Converse API. A non-empty `BEDROCK_MODEL_ID` wins over `BEDROCK_MODEL` for either path. |
| `EXTRACT_FALLBACK_TO_BEDROCK` | provider selection | With `EXTRACTION_PROVIDER=vertex`, a Vertex failure is retried on Bedrock (picked by the same rule as `bedrock`); the extraction record and the response carry `fallback_from=vertex` so the UI can say who answered. |
| `EXTRACTION_MAX_OUTPUT_TOKENS` | all three | 8192. |

### Jobs (`JOBS_ENABLED=1`)

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

## Run the tests

```bash
make ci                                     # the gate: ruff, pytest, tsc, vitest, vite build,
                                            # helm lint, helm template, docker build
make check                                  # the fast inner loop: ruff + pytest + the web check
cd api && .venv/bin/python -m pytest -q     # or: make test
cd web && pnpm check                        # tsc -b, vitest run, vite build   (or: make web-check)
make e2e                                    # the browser walkthrough; needs both servers running
```

`make ci` (`scripts/ci.sh`) fetches `helm` into `~/.local/bin` if it is missing, so it runs on a
bare box. The `docker build` step reports **skipped** where no daemon is reachable and the run
still passes - a sandbox with no daemon is a fact about the sandbox, not about the Dockerfile.

No test touches the network - a socket guard in `api/tests/conftest.py` fails any test that opens
an internet socket. Every test runs against SQLite (a fresh file per test), signed in through
`AUTH_DEV_USER`, with either the in-memory Google and the rule-based extraction provider, or the
real clients against `httpx.MockTransport` and the recorded responses under
`api/tests/fixtures/google/` (contract tests per client, plus `test_real_mode_end_to_end.py` which
runs the app with `FAKE_GOOGLE=0` end to end). Vertex and Bedrock are tested on recorded model
outputs under `api/tests/fixtures/llm/`.

The sheet planner's fixtures live in `api/tests/fixtures/sheets/*.json`. Everything under each
fixture's `expect` key was **generated by the prototype's own `lib/sheet.ts`**, by
`api/tests/fixtures/sheets/_generate_from_reference.mjs`:

```bash
node --experimental-strip-types api/tests/fixtures/sheets/_generate_from_reference.mjs
```

so the Python port is checked against the TypeScript reference rather than against itself.
`web/src/lib/sheet.test.ts` reads the same files and asserts the same `expect` blocks, so the
preview in the browser and the write on the server cannot drift apart.

The web app adds two Testing Library suites (the meeting list: calendar read-only versus manual
editable; the points row: defer, restore, transfer) and `web/e2e/walkthrough.mjs`, a Playwright
script that drives paste → extract → points → transfer → the rows in Sheets → an edit → Add row
above a row against the running dev servers. It is deliberately outside `pnpm check`.

## With Postgres

```bash
cp .env.example .env
docker compose up --build        # postgres 16, the API on :8000, the web app on :5173
docker compose config            # validate the file without starting anything
```

`make migrate` runs Alembic against whatever `DATABASE_URL` points at.

To serve the app from the API instead of Vite, build it and point `WEB_DIST` at the output:

```bash
make web-build                                     # writes web/dist
WEB_DIST=../web/dist make run                      # the API answers the app and the API on :8000
```

The routers are registered before the static mount, so API paths keep answering as themselves and
everything else falls through to `index.html`. The schema is
`api/alembic/versions/0001_initial_schema.py`, generated from `api/app/models.py`, which is spec
section 4 table for table.

## Telemetry

Per `docs/ALERT-EMISSION-STANDARD-SUMMARY.md`, condensed from
`SIALET-ALERT-EMISSION-STANDARD` v1.2. What the service emits, and where it comes from:

| metric | where it is set |
| --- | --- |
| `http_requests_total{route,method,status_class}` | `app/telemetry/middleware.py`; `route` is the matched route's declared path, `status_class` the bucket |
| `http_request_duration_seconds{route,method}` | the same middleware; buckets 0.05 … 10 |
| `external_provider_requests_total{provider,op,outcome}` | `track_provider()` in `app/telemetry/providers.py`, wrapped around `app/google/http.py` (every Google REST call), the token refresh, the Vertex and Bedrock calls (`op` `converse` or `chat_completions`), and every Postgres statement |
| `external_provider_last_success_timestamp_seconds{provider}` | the same wrapper, **only** on success |
| `external_provider_breaker_state{provider}` | `app/telemetry/breaker.py`; 0 closed, 1 half-open, 2 open, initialised to 0 for every provider at startup |
| `background_job_total{job_name,outcome}` | `track_job()` around `perform_extraction`, `fetch_missing_docs`, `check_connection_health` - so both the queued and the inline path are counted |
| `background_job_last_success_timestamp_seconds{job_name}` | the same |
| `app_build_info{version,commit}` | `APP_VERSION` / `GIT_COMMIT`, set by the chart from `image.tag` and `build.commit` |

Providers are a closed enum: `google_calendar`, `google_drive`, `google_docs`, `google_gmail`,
`google_sheets`, `google_people`, `google_oauth`, `google_api` (the catch-all), `vertex`, `bedrock`,
`postgres`. Each Google API and each LLM provider has a **real breaker**: five consecutive
dependency failures open it, the next call thirty seconds later is the trial. A 404, a 403, a 429
and an `invalid_grant` are *answers* - counted as `outcome="error"` so the alerts see them, but they
never move a breaker. `postgres` has no breaker and its gauge is a constant 0: there is nothing to
fall back to and opening it would turn a slow database into a hard outage.

Logs are one JSON object per line - `level`, `service`, `event` (a token from
`app/telemetry/events.py`, never prose), `request_id` (per request, echoed as `X-Request-ID`),
`route`, `duration_ms`, and `failure_reason` from a closed enum on every failure path. No secret,
token, request body or user content is ever written: `log_event` takes named fields only and the
formatter drops anything that looks like a credential.

### /metrics is not public

It is served by a second ASGI app on `METRICS_PORT` (9464), never mounted on the API router. The
chart names that container port `metrics`, the Service publishes it by that name, the ServiceMonitor
references it by that name, and the Ingress has no rule for it at all. Prove it after a deploy:

```bash
# From outside the cluster. The app port serves the SPA, so an unknown path comes back as
# index.html - what matters is that the exposition format is never in the body.
if curl -sS https://meeting-desk.internal.example.com/metrics | grep -q '^# TYPE http_requests_total'; then
  echo "LEAK: /metrics is reachable from the ingress"; exit 1
else
  echo "ok: /metrics is not public"
fi

# The real endpoint, on its own port, from inside the cluster:
kubectl -n meeting-desk exec deploy/meeting-desk-api -- python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9464/metrics').read().decode()[:400])"
```

Locally, `make run` behaves the same way: `curl localhost:8000/metrics` is a 404 (or the SPA's
index.html once `WEB_DIST` is set) and `curl localhost:9464/metrics` is the text format.
`api/tests/test_telemetry_metrics.py` asserts both, with and without the SPA mounted.

### The failure exercise

The standard asks for one deliberate failure driven end to end. `api/tests/test_telemetry_breaker.py`
is that, automated, against the real Sheets client and a scripted Google. By hand, against a
deployment:

1. Take Sheets away from one connection - revoke the `spreadsheets` scope on the admin account, or
   set `SHEETS_MAX_ROWS=0` on a canary pod, or block `sheets.googleapis.com` with a NetworkPolicy.
2. Open the Sheets page and let it refresh a few times.
3. Watch, on the metrics port:
   `external_provider_requests_total{provider="google_sheets",outcome="error"}` climbing;
   `external_provider_last_success_timestamp_seconds{provider="google_sheets"}` **not moving**;
   `external_provider_breaker_state{provider="google_sheets"}` at 2 after the fifth failure.
4. `kubectl logs … | grep '"event":"(external_call_failed|breaker_opened)"'` - one line per failure
   with a `failure_reason`, then one `breaker_opened`.
5. Put it back; within 30 s the next call is the trial and the gauge returns to 0 with a
   `breaker_closed` line. `MeetingDeskProviderBreakerOpen` resolves on its own.

## Deploy

### The image

One image (`deploy/Dockerfile.api`) holds the API, the built SPA and the worker:

```bash
docker build -f deploy/Dockerfile.api -t ghcr.io/hellosia/meeting-desk:0.1.0 .
docker push ghcr.io/hellosia/meeting-desk:0.1.0
```

Three stages: node + pnpm build `web/dist`, a Python stage builds a venv, and a `python:3.12-slim`
runtime carries neither toolchain. It runs as uid 10001, has a `HEALTHCHECK` on `/healthz`, and
exposes 8000 (API + SPA) and 9464 (metrics). `--workers 1` on purpose: the metrics server binds its
port inside the process, so more uvicorn workers would fight over it. Scale with replicas.

`deploy/Dockerfile.web` builds the SPA behind nginx instead. It is **not** what the chart deploys -
`main.py` already serves `WEB_DIST` at `/` with an SPA fallback, one origin means the session cookie
needs no CORS exception, and one image means one tag to move per release. It is kept working for a
split-origin deployment (a CDN, or the app on a different host); see the note at the top of the file.

### GCP project setup

Once, by a Workspace admin, in the project that owns the OAuth client and Vertex:

1. **Project.** `hellosia-meeting-desk` (any name; it goes in `VERTEX_PROJECT`).
2. **APIs.** Enable Google Calendar API, Google Drive API, Google Docs API, Gmail API, Google
   Sheets API, People API and Vertex AI API.
3. **OAuth consent screen → Internal.** Internal matters: an External app in testing mode expires
   refresh tokens after seven days, which is the failure the friction register calls "testing-mode
   7-day expiry". Fill in the app name, the support email and the developer contact. Scopes:
   `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `.../auth/calendar.readonly`,
   `.../auth/drive.readonly`, `.../auth/documents.readonly`, `.../auth/gmail.readonly`,
   `.../auth/spreadsheets`, `.../auth/directory.readonly` (the list is
   `api/app/google/oauth.py::CONNECTION_SCOPES`).
4. **OAuth client → Web application.** One client serves both flows. Authorised redirect URIs:

   | URI | used by |
   | --- | --- |
   | `https://meeting-desk.internal.example.com/auth/callback` | sign-in (`GOOGLE_OIDC_REDIRECT_URI`) |
   | `https://meeting-desk.internal.example.com/admin/connections/callback` | Connect an account (`GOOGLE_CONNECT_REDIRECT_URI`) |
   | `http://localhost:8000/auth/callback` | local development |
   | `http://localhost:8000/admin/connections/callback` | local development |

   Authorised JavaScript origins: `https://meeting-desk.internal.example.com` and
   `http://localhost:5173`. Put the client id and secret in Infisical (below).
5. **Vertex service account.** `meeting-desk-vertex@<project>.iam.gserviceaccount.com` with
   **Vertex AI User** (`roles/aiplatform.user`) and nothing else. Create a JSON key and paste the
   whole file into Infisical at `/meeting-desk/VERTEX_SERVICE_ACCOUNT_KEY`. The chart's second
   `ExternalSecret` mounts it at `/var/run/secrets/vertex/key.json` and sets
   `GOOGLE_APPLICATION_CREDENTIALS`; nothing else reads it. (Workload Identity Federation from EKS
   would remove the key file and is the right follow-up; a key is what gets the first deploy out.)

### Bedrock (the fallback) on IRSA

Bedrock is the configured fallback for Vertex (`EXTRACT_FALLBACK_TO_BEDROCK=1`). The pods
authenticate with IRSA - no AWS key anywhere:

```bash
eksctl create iamserviceaccount \
  --cluster hellosia-internal --namespace meeting-desk --name meeting-desk \
  --role-name meeting-desk-bedrock --attach-policy-arn <the policy below> --approve
```

or, by hand: create `meeting-desk-bedrock` with a trust policy on the cluster's OIDC provider and
`system:serviceaccount:meeting-desk:meeting-desk`, then attach

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MeetingDeskBedrockInvoke",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:Converse"],
      "Resource": "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0"
    }
  ]
}
```

and put the role ARN in `serviceAccount.annotations["eks.amazonaws.com/role-arn"]`
(`values-internal.yaml`). The model must also be **enabled** in Bedrock model access for the
account in `ap-south-1`; `BEDROCK_MODEL` is configuration and has to be confirmed there.

### Infisical entries

Every secret is read by External Secrets Operator from `/meeting-desk/<KEY>`. No value is ever in
this repo or in a rendered manifest - only the path.

| path | what it is |
| --- | --- |
| `/meeting-desk/DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/meetingdesk` for the RDS instance |
| `/meeting-desk/SESSION_SECRET` | 32+ random bytes; signs the session cookie. Rotating it signs everyone out. |
| `/meeting-desk/GOOGLE_CLIENT_ID` | the OAuth client above |
| `/meeting-desk/GOOGLE_CLIENT_SECRET` | its secret |
| `/meeting-desk/MEETING_DESK_TOKEN_KEY` | the Fernet key encrypting refresh tokens at rest - `make token-key` |
| `/meeting-desk/MEETING_DESK_TOKEN_KEY_PREVIOUS` | empty except during a rotation |
| `/meeting-desk/VERTEX_SERVICE_ACCOUNT_KEY` | the whole service-account JSON file |

### First deploy

```bash
# 0. The namespace, the ClusterSecretStore for Infisical and the ESO install are platform work.
kubectl create namespace meeting-desk

# 1. Render it and read it before anything is applied.
helm template meeting-desk deploy/helm/meeting-desk \
  -f deploy/helm/meeting-desk/values-internal.yaml | less

# 2. Either install directly …
helm upgrade --install meeting-desk deploy/helm/meeting-desk \
  -n meeting-desk -f deploy/helm/meeting-desk/values-internal.yaml \
  --set image.tag=0.1.0 --set build.commit=$(git rev-parse --short HEAD) --wait

# 3. … or hand it to ArgoCD: copy deploy/helm/meeting-desk/ into hellosia-infra at
#    charts/meeting-desk/, then
kubectl apply -n argocd -f deploy/argocd/application.yaml
```

The chart's pre-install / pre-upgrade hook runs `alembic upgrade head` as a Job before any new pod
starts, so a failed migration fails the release and the old pods keep serving.
procrastinate's own tables are **not** in Alembic; install them once per database:

```bash
kubectl -n meeting-desk exec deploy/meeting-desk-api -- python -m app.jobs.schema
```

Then, in the app: sign in, add the allow-list entries on **Admin**, and **Connect an account**
twice (the Admin page warns until there are two - reads fall back across connections).

### The worker

`worker.enabled=true` runs `python -m app.jobs.queue` as its own Deployment. It picks up the
extraction jobs the API defers *and* runs procrastinate's periodic tasks (`fetch_missing_docs`
every 5 minutes, `token_health` daily), which is why it is a Deployment and not a CronJob - a
CronJob could only do the second half, and an extraction would sit in the queue until the next tick.

```bash
make worker            # locally: JOBS_ENABLED=1 against Postgres
kubectl -n meeting-desk logs deploy/meeting-desk-worker -f
kubectl -n meeting-desk scale deploy/meeting-desk-worker --replicas=2   # jobs are locked per job
```

With `worker.enabled=false` (or `JOBS_ENABLED=0`) the API runs extraction inline in the request and
the two periodic jobs are run by hand from `POST /admin/jobs/fetch-docs` and
`POST /admin/connections/health`.

### The token key: generating and rotating

```bash
make token-key        # prints a fresh Fernet key
```

`connections.refresh_token_enc` is Fernet over the refresh token and `connections.key_version` says
which key wrote it. To rotate without a moment where tokens cannot be read:

1. Put the **current** key in `/meeting-desk/MEETING_DESK_TOKEN_KEY_PREVIOUS`, and set
   `externalSecrets.rotation.enabled=true` so the ExternalSecret starts asking for it. It is off
   the rest of the time: a key ESO is told to fetch and cannot find stops the whole Secret from
   syncing, which would leave the pods with no secrets at all.
2. Put the **new** key in `/meeting-desk/MEETING_DESK_TOKEN_KEY` and bump
   `env.MEETING_DESK_TOKEN_KEY_VERSION` in the values.
3. Deploy. Decryption tries the key matching each row's version first and the other one second, so
   both old and new rows open (this is the spec's "dual-read during rotation").
4. `curl -X POST .../admin/connections/rotate-keys` (an admin session) re-encrypts every row with
   the new key and stamps the new version.
5. Set `externalSecrets.rotation.enabled=false`, clear `MEETING_DESK_TOKEN_KEY_PREVIOUS` and deploy
   again.

Losing the key means every admin has to reconnect their Google account - nothing else is lost.

### Resetting the fake

The in-memory Google (`FAKE_GOOGLE=1`) keeps its spreadsheets in the API process's memory - one
`FakeGoogle` per process, on `app.state.google`. So the browser walkthrough's rows accumulate across
runs against one long-lived dev server. Restarting the API has always been the reset; there is now
also `POST /admin/fake/reset` (admin only, refuses with 409 when `FAKE_GOOGLE=0`), which rebuilds it
from the seed and the sheet fixtures without a restart. Neither touches the database - that is
`rm api/meeting-desk.db`.

## Layout

```
api/
  app/config.py        pydantic-settings: FAKE_GOOGLE, FAKE_LLM, AUTH_DEV_USER, the keys, the rest
  app/models.py        spec section 4, SQLAlchemy 2
  app/runtime.py       settings + db + clock + google + extraction, built once for the API or a worker
  app/auth/            Google OIDC sign-in, the session cookie, the allow-list, the dev bypass, roles
  app/google/          interface.py (Protocols), fake.py, http.py (bearer, retries, backoff, errors),
                       tokens.py (Fernet, key versions, the broker), oauth.py (Connect an account),
                       picker.py (first healthy connection able to see an item),
                       calendar.py drive.py docs.py gmail.py sheets.py people.py, real.py (the suite)
  app/sheets/          layout.py and planner.py - the port of lib/sheet.ts, plus add-row, hashes, dates
  app/extract/         schema.py, provider.py, fake.py, postprocess.py, prompt.py, parse.py,
                       vertex.py, bedrock.py (Converse), openai_compat.py (Bedrock API key), fallback.py
  app/routes/          meetings, notes, extract, points, workbooks, transfers, sheets, admin
  app/jobs/            extract, fetch_doc, token_health (plain functions), queue.py (procrastinate)
  app/telemetry/       metrics.py (the six + app_build_info), providers.py (track_provider),
                       breaker.py, middleware.py (request id, http metrics), server.py (/metrics on
                       its own port), logs.py (the JSON line), events.py (the event tokens)
  tests/               pytest; fixtures/sheets (planner), fixtures/google (contract), fixtures/llm
web/
  src/api/             client.ts (one fetch door, ApiError), hooks.ts (queries, mutations, polling,
                       the queued-extraction loop), types.ts (the wire contract)
  src/lib/sheet.ts     the preview planner, verbatim from the prototype; vitest runs it over the
                       same fixtures the Python planner is tested on
  src/components/Grid.tsx  the grid; plain table under 300 rows, TanStack Virtual over it
  src/pages/           the four capture steps, Sheets, Admin, the sign-in pages
  e2e/walkthrough.mjs  the walkthrough driven through a browser (Playwright, outside `check`)
deploy/
  Dockerfile.api       the image that ships: web build -> python build -> slim non-root runtime
  Dockerfile.web       the nginx alternative for a split-origin deployment (not what the chart uses)
  helm/meeting-desk/   the chart: api + worker Deployments, Services, internal Ingress, ESO
                       ExternalSecrets, ConfigMap, the alembic pre-upgrade Job, ServiceMonitor,
                       PrometheusRule; values.yaml and values-internal.yaml
  argocd/application.yaml  the ArgoCD Application pointing at the chart in hellosia-infra
scripts/ci.sh          what `make ci` runs
```

## Rules this codebase keeps

- Google and the LLM are always behind an interface; tests never reach the network (the socket
  guard in conftest makes sure).
- Every read goes through the connection picker: the first healthy admin connection able to see
  the item answers, and the answer says which one. A refused refresh token marks that connection
  `expired` in the session that met it; the other connections carry on.
- Every write to a sheet re-reads the region first, compares `region_hash`, and goes out as one
  `batchUpdate`. A mismatch returns 409 with the fresh grid and a rebuilt plan - never a silent
  overwrite.
- Formula columns are never written, only copied down after an insert. Date columns are written as
  dates.
- Points are `active` or `deferred`. A transferred point is deleted and the transfer row keeps the
  cells, the previous values and a full snapshot, which is what lets undo put it back.
- Every change records the person who made it.
