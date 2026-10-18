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
- `external_provider_*` MUST cover every outbound call: Google Calendar, Drive, Docs, Gmail, Sheets, People, Vertex, Bedrock, Postgres.
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
