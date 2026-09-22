# Phase 1 report (backend core) - accepted 22 Sep 2026

`cd api && .venv/bin/python -m pytest -q` → 247 passed. `make check` = ruff + pytest, green.
`alembic check` reports no drift (asserted by a test). `docker compose config` valid.

## Layout

```
api/app/  main.py config.py db.py models.py schemas.py activity.py bootstrap.py clock.py seed_data.py
api/app/auth/     deps.py oidc.py session.py           (OIDC scaffold, session cookie, allow-list, AUTH_DEV_USER bypass)
api/app/extract/  schema.py provider.py fake.py postprocess.py vertex.py bedrock.py   (vertex/bedrock are stubs)
api/app/google/   interface.py fake.py real.py         (real.py is a stub raising NotImplementedError)
api/app/jobs/     extract.py fetch_doc.py token_health.py   (functions exist; not scheduled)
api/app/routes/   common.py meetings.py notes.py extract.py points.py workbooks.py transfers.py sheets.py admin.py
api/app/sheets/   layout.py planner.py ops.py          (port of web lib/sheet.ts; verified against it)
api/tests/        conftest.py sheet_fixtures.py test_*.py  fixtures/sheets/*.json  fixtures/sheets/_generate_from_reference.mjs
```

## Decisions taken in Phase 1

1. Header tie-break follows lib/sheet.ts (strict `>`, upper row wins on a tie). If the spec's "lower
   row wins" is wanted, change both planners in the same phase.
2. Formula and date columns are hooks fed by the reader; with none, Python equals the TS planner
   cell for cell. Fixtures `formula_col` and `date_col` carry a `with_hooks` block.
3. Array columns are JSON (JSONB on Postgres) so SQLite runs the tests.
4. Undo of a transfer restores the points from `transfers.snapshot` with their original ids.
5. A pinned clock in fake mode (`app/clock.py`) keeps the seeded calendar window deterministic.
6. Note text is stored normalised (markdown stripped) and hashed on that form.
7. Seed splits meetings: some are rows, two stay calendar-only so the merge and iCalUID de-dup run.
8. Point delete returns `undo_until` (10 s) and `recoverable_until` (30 d); restore is
   `POST /points/{id}/restore`.

## Known gaps left for Phase 2+

- Real Google clients, token encryption (columns exist), OIDC round trip, 429 backoff, scheduled
  jobs (procrastinate listed as optional dep; extraction runs inline through `run_extraction`),
  web app, Helm chart, hardened Dockerfiles.
