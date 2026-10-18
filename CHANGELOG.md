# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `NOTIFY_WEBHOOK_URL`: each transfer posts a summary to Slack, Google Chat, Mattermost or Discord.
- `GOOGLE_USE_GMAIL` and `GOOGLE_USE_DIRECTORY`: leave out the restricted Gmail scope and the
  Workspace-only directory scope, for personal Google accounts.

### Changed

- Dependencies updated: FastAPI 0.136, Starlette 1.8, Authlib 1.7, Uvicorn 0.54, SQLAlchemy 2.0.55,
  Alembic 1.20, Pydantic 2.14, psycopg 3.3, dateparser 1.4, prometheus-client 0.26.

### Security

- Starlette 0.49.1 or later is required, for the Range-header denial-of-service fix in the static
  file serving the web app goes through. Authlib moves past the 1.6.4 and 1.6.5 security fixes.

## [0.1.0] - 2026-10-18

The first public release.

### Added

- Meetings from Google Calendar across connected accounts, or added by hand.
- Notes from the meeting's Notes by Gemini doc (including its transcript tab), the Gemini recap
  email, a paste, or an uploaded `.txt`, `.md`, `.vtt` or `.srt` transcript (Meet, Zoom, Teams).
- AI extraction of action items, decisions, risks and open questions into one strict schema, with
  owners and due dates resolved by code. Providers:
  - `openai`: any OpenAI-compatible endpoint, including OpenAI, Ollama, OpenRouter, LM Studio and vLLM.
  - `anthropic`: Claude with structured outputs.
  - `vertex`: Gemini on Vertex AI.
  - `bedrock`: Amazon Bedrock.
  - `fake`: a rule-based extractor that needs no model.
- A review step: edit, bulk-assign, defer, remove, with autosave.
- Transfer into Google Sheets with layout detection.
  - A preview of exactly where the rows will land, before anything is written.
  - Generated keys, formula columns copied down, real dates in date columns.
  - Conflict detection, and a 10-minute undo.
- A Sheets page to browse, filter, edit cells and add rows in place.
- Export points as Markdown or CSV, or copy them as text.
- Google sign-in, an allow-list with admin and member roles, and an activity log.
- `DISPLAY_TIMEZONE` and `WORKSTREAMS` settings. Google sign-in works for any Google account, or
  only one Workspace domain when `GOOGLE_HOSTED_DOMAIN` is set.
- One Docker image (API and web app), a one-command demo (`docker-compose.demo.yml`), a live
  launcher (`scripts/live.sh`), and a Helm chart with a worker, migrations, External Secrets,
  a ServiceMonitor and alert rules.
- Prometheus metrics on a separate port, circuit breakers per provider, and structured JSON logs.

[Unreleased]: https://github.com/Prathyush-KKK/meeting-desk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Prathyush-KKK/meeting-desk/releases/tag/v0.1.0
