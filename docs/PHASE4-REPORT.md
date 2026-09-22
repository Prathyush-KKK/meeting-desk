# Phase 4 report (deployment, operations, telemetry) - 22 Sep 2026

`make ci` green: ruff, **409 pytest** (352 at the end of phase 3, 57 new), tsc, **64 vitest**
(54 at the end of phase 3, 10 new), `vite build`, `helm lint` x2, `helm template` x2 with the
ServiceMonitor and the PrometheusRule rendering, `docker build` **skipped** (no daemon in this
sandbox). `docker compose config` valid. The browser walkthrough still runs **22 steps green**.

## What landed

```
api/app/telemetry/                     new package - docs/ALERT-EMISSION-STANDARD-SUMMARY.md
  metrics.py       the six required names + app_build_info on their own CollectorRegistry, the
                   histogram buckets 0.05…10, status_class() (a bucket, never a raw code)
  providers.py     track_provider(provider, op): the one wrapper every outbound call goes through;
                   the closed provider/op/outcome enums; classify_google(url); classify_failure();
                   track_job(job_name) and record_job()
  breaker.py       Breaker (5 consecutive failures -> open, half-open after 30 s) + BreakerRegistry
                   wired to the gauge; BreakerOpen
  middleware.py    pure-ASGI: request id (in, out as X-Request-ID), the two http metrics with the
                   matched route's declared path, one log line per request. The route is worked out
                   from the route table *before* the handler runs (Starlette's own algorithm), so
                   every line of a request carries it, and confirmed afterwards from
                   scope["endpoint"]
  server.py        MetricsApp (GET /metrics and /healthz, nothing else) and MetricsServer: uvicorn
                   in a daemon thread on METRICS_PORT
  logs.py          the JSON line (level, service, event, request_id, route, duration_ms,
                   failure_reason), the contextvars, the scrub list
  events.py        the event tokens and the failure_reason enum

api/app/main.py        configure_logging + build info + breaker init in create_app;
                       TelemetryMiddleware added last (outermost); /healthz (readiness, hits the
                       database) and /livez (liveness, touches nothing); MetricsServer in lifespan
api/app/config.py      METRICS_ENABLED / METRICS_PORT / METRICS_HOST, LOG_LEVEL, APP_VERSION,
                       GIT_COMMIT
api/app/db.py          instrument(engine): every statement counts on provider "postgres"
api/app/google/http.py request() wraps _send() in track_provider(); one count per logical call
api/app/google/tokens.py  the refresh is provider "google_oauth", op "token_refresh"; an
                       AuthExpired also logs oauth_refresh_failed with a hashed connection ref
api/app/google/picker.py  Pick.only_rate_limited
api/app/routes/common.py  pick_for re-raises it, so an all-throttled read is a 503 with Retry-After
                       instead of "not shared with any admin account"
api/app/extract/vertex.py, bedrock.py   wrapped in track_provider
api/app/jobs/extract.py, fetch_doc.py, token_health.py   wrapped in track_job (both the queued and
                       the inline path go through the same function, so the counter is right either
                       way); extraction_failed logged
api/app/jobs/queue.py  the worker configures logging, build info and its own MetricsServer
api/app/auth/deps.py   the first-sign-in insert race (see decision 8)
api/app/google/fake.py FakeGoogle.reset()
api/app/routes/admin.py  POST /admin/fake/reset (admin, 409 when FAKE_GOOGLE=0)
api/app/routes/sheets.py, transfers.py   sheets_write_conflict / transfer_conflict log lines
api/pyproject.toml     prometheus-client==0.21.1

api/tests/test_telemetry_metrics.py       21 tests: the six names on the metrics app, samples once
                       traffic has run, the registry holds nothing else, the buckets, the metrics
                       app answers nothing but /metrics and /healthz, /metrics is not a route on
                       the API (with and without the SPA mounted), the request counter and the
                       X-Request-ID echo, the postgres provider, the breaker gauges starting at 0,
                       last_success absent until a success, background_job_*, job_name not job,
                       the JSON line's fields, secrets/tokens/user content never logged, the event
                       tokens are greppable, /healthz and /livez, and that every line of a request
                       carries its route and its request id, not only the last one
api/tests/test_telemetry_cardinality.py   5 tests: no path-parameter value in a route label (driven
                       with real uuids through 10 routes), the http bound from the route table, the
                       provider bound from the provider tables, the job bound, status_class is a
                       bucket
api/tests/test_telemetry_breaker.py       19 tests: the deliberate failure end to end (counter,
                       stalled gauge, breaker at 2, the sixth call never leaving the process, the
                       three log tokens), half-open after 30 s and closed on a success, a failed
                       trial re-opening it, "an answer is not an outage", a 404 x6 leaving the
                       breaker closed, every Google URL classified, the warn/error level on a
                       degraded path
api/tests/test_telemetry_alerts.py        10 tests: every event token a rule greps for exists in
                       events.py AND is used at a call site; every rule reads one of the six
                       metrics; every rule has service + severity + a remediation in event tokens;
                       the last-success rules use max_over_time / absent / min by (provider); the
                       five rules the spec names are present; Service and ServiceMonitor agree on
                       the port name; the Ingress never points at the metrics port; no secret value
                       anywhere in the chart
api/tests/test_real_mode_end_to_end.py    + the route-level Sheets 429: 503 with Retry-After, the
                       per-connection cooldown, the counter, the breaker staying closed
api/tests/test_auth.py                    + the first-sign-in race
api/tests/conftest.py                     metrics_enabled=False (the socket guard) and an autouse
                       fixture that gives every test fresh counters and fresh breakers

web/src/components/Grid.tsx     TanStack Virtual over 300 rows; the plain table at or under it;
                       two spacer rows keep the scrollbar honest; data-virtualised / data-rows
web/src/components/Grid.test.tsx  4 tests: both paths, the threshold, marks under virtualisation
web/src/api/hooks.ts            pollExtraction() + useExtract polls /extractions/{id} every 2 s
                       when the API answers queued, with cancel() and a 10-minute give-up
web/src/api/extraction-poll.test.ts  6 tests, no timers and no network
web/src/api/types.ts            ExtractionStatus, ExtractionJobStatus
web/src/pages/NotesStep.tsx     "Queued…" and a Cancel button while polling
web/src/test/setup.ts           jsdom has no layout: a size for the grid's scroll box, a
                       ResizeObserver stub
web/package.json                + @tanstack/react-virtual

deploy/Dockerfile.api           multi-stage (pnpm build -> venv -> python:3.12-slim), non-root uid
                       10001, HEALTHCHECK on /healthz, EXPOSE 8000 9464, --workers 1
deploy/Dockerfile.web           the nginx alternative, documented as not what ships
deploy/nginx.conf               its config (immutable assets, SPA fallback, /metrics -> 404)
deploy/helm/meeting-desk/       Chart.yaml, values.yaml, values-internal.yaml and templates:
                       _helpers.tpl, configmap.yaml, externalsecret.yaml (x2: the env secret and
                       the Vertex key file), serviceaccount.yaml (IRSA annotation),
                       deployment-api.yaml (+ PDB), deployment-worker.yaml, service.yaml (x2, both
                       naming a `metrics` port), ingress.yaml (internal, http only),
                       job-migrate.yaml (alembic as a pre-install/pre-upgrade hook),
                       servicemonitor.yaml (flagged), prometheusrule.yaml (flagged), NOTES.txt
deploy/argocd/application.yaml  the ArgoCD Application pointing at charts/meeting-desk in
                       hellosia-infra

scripts/ci.sh                   what `make ci` runs; fetches helm into ~/.local/bin when missing
Makefile                        ci, helm-lint, helm-template, docker-build
README.md                       Telemetry and Deploy sections (below)
web/README.md                   the two web gaps that closed
docker-compose.yml              the metrics port on the api and the worker
.env.example .gitignore
```

## Commands and output tails

```
$ make ci
== ruff
All checks passed!
ok   ruff

== pytest
........................................................................ [ 88%]
................................................                         [100%]
409 passed in 30.53s
ok   pytest

== tsc
ok   tsc

== vitest
 Test Files  5 passed (5)
      Tests  64 passed (64)
ok   vitest

== vite build
✓ 1967 modules transformed.
dist/index.html                   0.39 kB │ gzip:   0.26 kB
dist/assets/index-CsZgqP0l.css   20.51 kB │ gzip:   5.16 kB
dist/assets/index-GpMEEwfY.js   447.44 kB │ gzip: 134.99 kB
✓ built in 866ms
ok   vite build

== helm lint / helm lint (values-internal)
1 chart(s) linted, 0 chart(s) failed        (INFO: Chart.yaml: icon is recommended)
ok   helm lint
ok   helm lint (values-internal)

== helm template (defaults) / (values-internal)
ok   helm template (defaults)
ok   helm template (values-internal)

== the ServiceMonitor and the PrometheusRule render
ok   ServiceMonitor and PrometheusRule are in the render

== docker build
skip docker build - no docker daemon is reachable here (expected in the sandbox)

skipped: docker build
ci green
```

`helm template … -f values-internal.yaml` renders, in order: PodDisruptionBudget, ServiceAccount,
ConfigMap, Service (api), Service (worker, headless), Deployment (api), Deployment (worker),
Ingress, ExternalSecret (env), ExternalSecret (vertex key), PrometheusRule, ServiceMonitor, Job
(the alembic hook).

The cardinality numbers the test prints (derived from the route table and the provider tables, not
typed in):

```
http_requests_total: 60 routes x 4 methods x 4 status classes = 960 naive, 288 real
http_request_duration_seconds: 748 real            (route x method x (8 buckets + sum + count))
external_provider_requests_total: 11 providers x 18 ops x 4 outcomes = 792 naive, 112 real
external_provider_last_success_timestamp_seconds / breaker_state: 11 each
background_job_total: 6 real; background_job_last_success_timestamp_seconds: 3
```

Ceiling asserted: 1000 per metric. Without templated routes there is no bound at all - one series
per distinct URL ever requested - which is why the route label is the declared path and everything
unmatched collapses into `__unmatched__`.

Exercised against a running process, not only in tests:

```
$ METRICS_PORT=9477 uvicorn app.main:app --port 8077
{"level":"info","service":"meeting_desk","event":"metrics_server_started","request_id":"","route":"","logger":"meeting_desk.metrics","port":9477}
$ curl -o /dev/null -w '%{http_code}\n' localhost:8077/healthz    200
$ curl -o /dev/null -w '%{http_code}\n' localhost:8077/metrics    404
$ curl -s localhost:9477/metrics | head
# TYPE http_requests_total counter
http_requests_total{method="GET",route="/healthz",status_class="2xx"} 1.0
http_requests_total{method="GET",route="__unmatched__",status_class="4xx"} 1.0
…
app_build_info{commit="unknown",version="0.1.0"} 1.0
```

## Decisions

1. **One image, not two.** `deploy/Dockerfile.api` builds the web app in its first stage and copies
   `dist` in as `WEB_DIST`. `main.py` already serves it at `/` with an SPA fallback (phase 3), so an
   nginx image would add a hop, a second tag to move, and a CORS exception for the session cookie,
   and buy nothing for 450 kB of static files. `deploy/Dockerfile.web` keeps the nginx route working
   for a split-origin deployment and says at the top that it is not what the chart deploys; CI
   builds it too, so it cannot rot.

2. **`--workers 1` per container.** The metrics server binds `METRICS_PORT` *inside* the process, so
   `uvicorn --workers N` would have N processes fighting over it. Scale with replicas; the chart
   does.

3. **A worker Deployment, not a CronJob.** procrastinate's scheduler owns the periodic cadence
   (`fetch_missing_docs` every 5 minutes, `token_health` daily) *and* the same process picks up the
   extraction jobs the API defers. A CronJob could do only the first half, and an extraction would
   sit in the queue until the next tick. The worker gets its own headless Service so
   `background_job_*` is scraped where the jobs actually run.

4. **The telemetry registry is its own, not the process-global one.** `/metrics` answers exactly
   the six plus `app_build_info` - no `python_gc_*`, no `process_*` - so the cardinality statement
   covers the whole endpoint and a test can assert the set of names exactly.

5. **Where `track_provider` sits.** Around `GoogleHttp.request()` rather than around each client, so
   every Google call is covered by construction and a 429 retried four times is *one* call, not
   five. Postgres is instrumented through SQLAlchemy engine events (`after_cursor_execute` /
   `handle_error`) with one op, `query`, so the series count does not follow the statement count.
   The provider label stays `postgres` even on the SQLite file a local run uses: it names the
   deployed dependency, not the driver.

6. **An answer is not an outage.** A 404 from Docs (nobody shared it), a 403 from Sheets (a
   protected range), a 429, and an `invalid_grant` on one connection are counted as
   `outcome="error"` - the alerts see them - but they never move a breaker. Only 5xx, transport
   failures and timeouts do. Otherwise one unshared document would open the Docs breaker for
   everybody.

7. **`google_oauth` is its own provider** (and `google_api` is a catch-all so an unmapped URL can
   never invent a label). "OAuth refresh failures" is one of the alerts the spec asks for and it
   needs its own series; the catch-all keeps `classify_google` total.

8. **Two behaviour changes fell out of the instrumentation**, both small and both tested:
   * `pick_for` now re-raises when *every* connection tried came back rate-limited. Before, a
     429 on the only connection was reported as "This workbook is not shared with any admin
     connection", which is false and unactionable; now it is a 503 with `Retry-After`, which is what
     the friction register's "the UI shows the retry" means.
   * the first sign-in on a fresh database could 500. The app fires four list requests on load; two
     of them reach the `users` insert together and one loses the unique index on `google_sub`. The
     insert now falls back to a read. Reproduced with eight parallel first requests against a fresh
     database: 8 x 200, zero 5xx.

9. **409 rate without a seventh metric.** The six metrics carry a status *class*, not a raw code, so
   the "transfer 409 rate" rule is the 4xx rate on `/transfers/execute`, `/sheets/save` and
   `/sheets/add-row` - 409 is the only 4xx those three return in normal use (422 is a malformed
   client call). The rule's annotation says so, and the `transfer_conflict` /
   `sheets_write_conflict` log lines carry the reason (`region_hash_changed` or
   `already_transferred`).

10. **`min by (provider)` on the last-success rule**, as the standard words it, even though
    `max by` would be the "any pod is fine" reading. Taken literally: if one pod has stopped
    succeeding against a dependency, that is worth looking at. Written in the template so it is one
    edit if the platform team disagrees.

11. **Secrets are paths, never values.** Six keys plus the Vertex service-account JSON come from
    Infisical at `/meeting-desk/<KEY>` through two `ExternalSecret`s. A test walks every YAML file
    in the chart and fails on anything that looks like a literal secret.

12. **Logs carry no user identifier.** `log_event` takes named fields and the formatter drops
    anything in a deny list (authorization, tokens, bodies, note text, emails). A connection is
    identified in a log line by the first 12 hex of the sha256 of its address, so an operator can
    tell two connections apart without the address being in the log.

13. **jsdom needed two stubs for the virtualised grid** (a size for the scroll box, a
    `ResizeObserver`). They are in `web/src/test/setup.ts` and scoped to the element carrying
    `data-rows`, so nothing else in the suite sees a layout it would not see in a browser.

14. **`metrics_enabled=False` in the test settings.** The metrics server is a real listening socket
    and conftest's socket guard forbids those. The metrics app itself is exercised through an ASGI
    client, and the thread was verified by hand against a running process (above).

## Gaps from the earlier reports - closed

| gap (phase 3 report) | now |
| --- | --- |
| TanStack Virtual is not wired in | `Grid.tsx` virtualises over 300 rows; `Grid.test.tsx` covers both paths |
| Extraction polling with the queue on | `pollExtraction` + `useExtract`; every 2 s, cancel, timeout; 6 tests |
| Sheets 429 handling at the route level | `test_real_mode_end_to_end.py`: 503 + `Retry-After`, the cooldown, the counter |
| The fake sheets client accumulates rows across e2e runs | `FakeGoogle.reset()` and `POST /admin/fake/reset`; documented in the README |
| Alerts per the standard are not emitted (phase 2 report) | the whole telemetry package and the PrometheusRule |

## Known gaps

- **Nothing here has met a real cluster.** `helm template` and `helm lint` pass; `kubectl apply
  --dry-run=server`, ESO actually resolving an Infisical path, and the Prometheus Operator actually
  selecting the ServiceMonitor are all first-deploy work. The `release: kube-prometheus-stack` label
  in `values-internal.yaml` is a guess at this cluster's Prometheus selector and must be confirmed.
- **`docker build` has not run here** (no daemon). The Dockerfile is written against the same
  commands `make web-build` and `pip install .` run in this sandbox, but the first real build is
  where a missing system library would show.
- **The alert thresholds are starting points**, not tuned numbers: 20 % extraction failures, 10 %
  Sheets errors, 25 % conflicts, p95 over 5 s, last success older than 30 minutes. Expect to move
  them after a week of real traffic.
- **The Vertex service account uses a JSON key.** Workload Identity Federation from EKS to GCP
  would remove the file; it is the right follow-up and was not in scope.
- **The breaker is per process**, not shared across replicas: five failures in *one* pod open it in
  that pod only. That is the usual trade-off (no shared state, no new dependency) and the alert
  takes `max by (provider)` across pods so one open breaker is still visible.
- **Half-open allows more than one trial** if several requests arrive in the same instant. The first
  result still decides; the cost is a handful of extra calls to a dependency that may still be down.
- **`background_job_total{job_name="extract"}` counts a meeting with no included notes as a
  success.** The job ran and there was nothing to extract; the `extractions` row still records the
  reason.
- **No dashboards.** The rules exist; a Grafana board on the same six metrics is the obvious next
  half-day.
- The e2e walkthrough and `make run` were left stopped in this sandbox; `make run` + `make web-dev`
  bring them back.

## What a human must do before first production run

Nothing below can be done from this repo - it is all credentials, consoles and DNS.

1. **Google Cloud project** (a Workspace admin). Create the project; enable Calendar, Drive, Docs,
   Gmail, Sheets, People and Vertex AI APIs. Configure the OAuth consent screen as **Internal** -
   External-in-testing expires refresh tokens after 7 days, which is the failure the friction
   register calls out. Add the nine scopes listed in the README.
2. **OAuth client** (Web application) with all four redirect URIs from the README's table (the two
   production ones and the two localhost ones) and the two JavaScript origins. Copy the client id
   and secret into Infisical.
3. **Vertex service account** `meeting-desk-vertex@<project>` with `roles/aiplatform.user` only;
   create a JSON key and paste the whole file into Infisical at
   `/meeting-desk/VERTEX_SERVICE_ACCOUNT_KEY`. Set `VERTEX_PROJECT` in `values-internal.yaml`.
4. **Bedrock** (AWS). Enable model access for the Claude model in `ap-south-1` and confirm the model
   id in `env.BEDROCK_MODEL` - it is configuration, not a fact. Create the IRSA role
   `meeting-desk-bedrock` with the policy in the README, trusted by the cluster's OIDC provider for
   `system:serviceaccount:meeting-desk:meeting-desk`, and put its ARN in
   `serviceAccount.annotations`.
5. **RDS**. Create the Postgres 16 instance and database, and put the full
   `postgresql+psycopg://…` URL in `/meeting-desk/DATABASE_URL`. Confirm daily snapshots are on
   (spec section 7).
6. **Infisical entries** - all seven paths in the README's table. `MEETING_DESK_TOKEN_KEY` from
   `make token-key`; `SESSION_SECRET` 32+ random bytes; `MEETING_DESK_TOKEN_KEY_PREVIOUS` empty.
   Confirm the `ClusterSecretStore` named `infisical` exists and can read `/meeting-desk/*`.
7. **DNS and TLS**. An internal A/CNAME for `meeting-desk.internal.simpleo.ai` at the internal NLB,
   and the `meeting-desk-tls` certificate in the namespace (or switch `ingress.tls.enabled` off).
   Confirm the ingress class name for this cluster - `nginx-internal` is a values default, not a
   fact.
8. **Namespace and platform bits**: `kubectl create namespace meeting-desk`; External Secrets
   Operator installed; the Prometheus Operator's ServiceMonitor selector label confirmed and set in
   `serviceMonitor.labels` / `prometheusRule.labels`.
9. **Image**. Build and push `ghcr.io/hellosia/meeting-desk:<tag>` and set `image.tag` and
   `build.commit`; make sure the cluster can pull from ghcr (an `imagePullSecret` if the package is
   private).
10. **First deploy**, then once per database: `python -m app.jobs.schema` inside a pod to install
    procrastinate's tables (they are deliberately not in Alembic).
11. **In the app**: sign in, add the allow-list entries on Admin, and **Connect an account** for at
    least two Google admins - the Admin page warns until there are two, and reads fall back across
    connections.
12. **Prove the telemetry**: run the README's "/metrics is not public" curl against the real host,
    and do the deliberate-failure exercise once so the on-call has seen the counter move, the gauge
    stall, the breaker open and the log line appear.
