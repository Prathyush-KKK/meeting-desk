# Meeting Desk - launch on this Mac (handoff for the Claude Code session)

Goal: Meeting Desk running for real at http://localhost:8000 so Prathyush can sign in with Google,
connect admin Google accounts and paste meeting notes. Everything is prepared; only the docker
steps remain, and they need macOS (Colima), which the Cowork shell cannot reach.

## State (23 Sep 2026)

- Repo: `~/Code/simplev-dev/meeting-desk` (git initialised, 2 commits).
- `.env` is filled: `BOOTSTRAP_ADMINS`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (OAuth client
  "Meeting Desk (Mac, localhost)" in GCP project `meeting-desk-509415`, Internal consent screen,
  redirect URIs `http://localhost:8000/auth/callback` and
  `http://localhost:8000/admin/connections/callback`). `SESSION_SECRET` and
  `MEETING_DESK_TOKEN_KEY` are empty on purpose: `scripts/mac-launch.sh` generates them.
- Stack: `docker-compose.live.yml` (postgres:16 + one image from `deploy/Dockerfile.api` that
  serves the API and the built SPA; `FAKE_GOOGLE=0`, `FAKE_LLM=1`, no `AUTH_DEV_USER`).

## Do

```bash
cd ~/Code/simplev-dev/meeting-desk
rm -f .git/index.lock                 # stale lock left by the Cowork VM shell
docker info >/dev/null 2>&1 || colima start
make live                             # = scripts/mac-launch.sh: fills the two keys, builds, starts, waits for /healthz
```

Success looks like: `Meeting Desk is up: http://localhost:8000`. First build: node + Python stages,
several minutes on the 2019 Intel Mac.

Then verify and report:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/            # 200 (the SPA)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/auth/me     # 401 (not signed in yet)
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://localhost:8000/auth/login   # 302 to accounts.google.com
docker compose -f docker-compose.live.yml logs --tail=30 api
```

Do not open the browser or sign in; Prathyush does that himself. Do not print `.env`.

## If it fails

- `docker is not running`: `colima start` (or open OrbStack), rerun `make live`.
- Build error in the `web` stage: `cd web && corepack enable && pnpm install --frozen-lockfile && pnpm run build`
  reproduces it outside docker; paste the error.
- Build error in the Python stage: `pip install .` from `api/`; paste the error.
- `not healthy after 120 s`: the script prints the last 60 log lines; look for
  `UnsafeConfiguration` (a guard refused the config: fix `.env`, rerun) or an alembic error.
- Port 8000 busy: `lsof -i :8000`; stop the other process or set `PUBLIC_URL`/ports in
  `docker-compose.live.yml` (then the OAuth redirect URIs must change too, so prefer freeing 8000).

## Report

Write `docs/MAC-LAUNCH-RESULT.md`: the exact `make live` tail, the three curl results, and
anything changed. Commit with the repo's attribution lines.
