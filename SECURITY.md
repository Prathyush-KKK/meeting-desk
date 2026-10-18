# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through GitHub's
[private vulnerability reporting](https://github.com/Prathyush-KKK/meeting-desk/security/advisories/new)
(the repository's **Security** tab → **Report a vulnerability**).

Include what you found, how to reproduce it, and the impact you expect. You should get an answer
within a week. Once a fix is released you will be credited in the release notes, unless you would
rather not be.

## Supported versions

Security fixes go into the latest release only.

## What to know when you deploy it

- Meeting Desk holds Google refresh tokens for the admin connections. They are encrypted at rest
  with `MEETING_DESK_TOKEN_KEY` (Fernet). Keep that key in a secret manager, not in a file in the
  repository.
- Outside `ENVIRONMENT=local` or `test` the app refuses to start with the default `SESSION_SECRET`,
  a secret shorter than 32 characters, `AUTH_DEV_USER` set, or `*` in `CORS_ORIGINS`.
- `/metrics` is served on its own port (`METRICS_PORT`) and must not be exposed publicly.
- Sign-in is Google only, limited to `GOOGLE_HOSTED_DOMAIN` when it is set, and then to the
  allow-list on the Admin page.
- Meeting notes are sent to the LLM provider you configure. Pick one whose data terms you accept,
  or run a local model through Ollama (`EXTRACTION_PROVIDER=openai`).
