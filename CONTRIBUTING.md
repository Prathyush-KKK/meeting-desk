# Contributing to Meeting Desk

Thanks for helping. Bug reports, fixes, new note sources, new export targets and documentation are
all welcome.

## Ground rules

- **Open an issue first for anything bigger than a small fix**, so we can agree on the approach
  before you spend time on it.
- **Keep pull requests focused.** One change per PR, with tests.
- **Never commit credentials.** No test touches the network: Google and the LLMs are fakes or
  recorded responses (`api/tests/fixtures/`), and a socket guard in `api/tests/conftest.py` fails
  any test that opens one.
- Be kind. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setting up

You need Python 3.12, Node 22 with pnpm, and optionally Docker.

```bash
make install        # api/.venv with the dev extras
make web-install    # pnpm install in web/
make run            # API on :8000 with the in-memory Google and the rule-based extractor
make web-dev        # web app on :5173, proxying /api to :8000
```

No Google account or API key is needed for any of that: `FAKE_GOOGLE=1` and `FAKE_LLM=1` run a
complete demo world (`api/app/seed_data.py`).

## Before you open a pull request

```bash
make check          # ruff + pytest + tsc + vitest + vite build
```

`make ci` runs everything CI runs, including `helm lint` and a Docker build. If you changed the UI,
`make e2e` drives the main flow through a real browser (both servers must be running), and
`node web/e2e/screens.mjs <name>` photographs every screen into `docs/screenshots/<name>/`.

## Where things live

| Area | Path |
| --- | --- |
| API routes | `api/app/routes/` |
| Google clients (real and fake) | `api/app/google/` |
| LLM providers and the extraction prompt | `api/app/extract/` |
| Sheet layout detection and write planning | `api/app/sheets/` (mirrored in `web/src/lib/sheet.ts`) |
| Web app | `web/src/` |
| Deployment | `deploy/` |

### Adding an LLM provider

Implement the `ExtractionProvider` protocol in `api/app/extract/provider.py`, build it in
`api/app/extract/__init__.py`, wrap the call in `track_provider(...)` (add the provider to
`api/app/telemetry/providers.py`), and add tests against recorded responses. Most hosted models
already work through `EXTRACTION_PROVIDER=openai` (any OpenAI-compatible endpoint), so check that
first.

### Changing the sheet planner

`api/app/sheets/` is a port of `web/src/lib/sheet.ts`. Both are tested against the same fixtures in
`api/tests/fixtures/sheets/`, generated from the TypeScript planner:

```bash
node --experimental-strip-types api/tests/fixtures/sheets/_generate_from_reference.mjs
```

Change both sides together, regenerate, and run both test suites.

## Commit messages

Use the imperative mood ("Add CSV export", not "Added") and explain *why* in the body when it is
not obvious.
