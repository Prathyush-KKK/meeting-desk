# Telemetry - what Meeting Desk emits

The metrics, logs and alert rules the service ships with, and the rules the code keeps so they stay
useful: a separate metrics port, closed label sets, no user content anywhere. The README's
"Telemetry" section maps each metric to the code that sets it.

## Metrics endpoint
- `GET /metrics`, Prometheus text format, on a SEPARATE container port (not the app port), unauthenticated,
  never reachable from public ingress (Service exposes the metrics port by name; ServiceMonitor references it by name).
- No user identifiers or user content in any metric name, label or value.

## Six required metrics (exact names, types, labels)
```
http_requests_total{route, method, status_class}            counter   route = templated path, status_class in 2xx|3xx|4xx|5xx
http_request_duration_seconds{route, method}                histogram buckets 0.05,0.1,0.25,0.5,1,2.5,5,10
external_provider_requests_total{provider, op, outcome}     counter   outcome in success|error|timeout|rejected_by_breaker
external_provider_last_success_timestamp_seconds{provider}  gauge     set on every success; never written with a non-success value; absent after restart is fine
external_provider_breaker_state{provider}                   gauge     0 closed, 1 half-open, 2 open; initialise to 0 for every provider at startup
background_job_total{job_name, outcome}                     counter   outcome in success|failure   (label is job_name, never job)
background_job_last_success_timestamp_seconds{job_name}     gauge
app_build_info{version, commit}                             gauge, always 1
```
- `external_provider_*` MUST cover every outbound call: Google Calendar, Drive, Docs, Gmail, Sheets, People, Vertex, Bedrock, OpenAI-compatible endpoints, Anthropic, Postgres.
  A provider with no breaker still reports requests_total and last_success; its breaker gauge is a constant 0 and the PR says so.
- Cardinality: templated routes only, status_class not raw codes, closed enums for any reason label, every metric under 1000 series,
  series count per metric derived by a test that walks the route table (state naive bound vs real bound).

## Structured logs
Every line one JSON object with `level`, `service`, `event` (stable snake_case token, never interpolated prose), `request_id`
(generated at request entry, on every line of that request), `route`, `duration_ms`, and `failure_reason` on every failure path.
A caught exception that degrades to a fallback logs at warn or error. Never log secrets, tokens, request bodies or user content.

## Remediation text
Any runbook string that quotes log content uses event tokens, e.g. `grep '"event":"(external_call_failed|breaker_opened)"'`,
and a test asserts those tokens exist in the emitting code.

## Verification (PR checklist)
- /metrics returns all six plus app_build_info; not reachable from the public host.
- Every outbound dependency wrapped; last-success gauges never written non-success.
- Route labels contain no record ids, asserted by a test.
- Series counts stated with naive vs real bound, derived from code.
- Logs carry the required fields.
- A consumer exists: at least one alert rule (deploy/helm alerting-rules) reads these metrics, using max_over_time/absent on
  last-success and min by (provider) across pods, with service and severity labels.
- One deliberate failure exercised end to end (break a dependency, watch the counter, the gauge stall, the breaker move, the error log).

## Where each metric comes from

What the service emits, and where it is set:

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

## /metrics is not public

It is served by a second ASGI app on `METRICS_PORT` (9464), never mounted on the API router. The
chart names that container port `metrics`, the Service publishes it by that name, the ServiceMonitor
references it by that name, and the Ingress has no rule for it at all. Prove it after a deploy:

```bash
# From outside the cluster. The app port serves the SPA, so an unknown path comes back as
# index.html - what matters is that the exposition format is never in the body.
if curl -sS https://meeting-desk.example.com/metrics | grep -q '^# TYPE http_requests_total'; then
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

## The failure exercise

One deliberate failure, driven end to end, proves the signals are wired. `api/tests/test_telemetry_breaker.py`
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
