# Meeting Desk - Mac session handoff (for the Claude Code session, updated 27 Sep 2026)

State: the app is built, running and reachable at http://localhost:8000 on this Mac
(docker-compose.live.yml, Colima). Prathyush has signed in once. The repo is committed locally
(`git log`), the remote is set to `git@bitbucket.org:simpleo/meeting-desk.git`, nothing is pushed.
Cowork's shell cannot reach the ssh key or docker; these steps need macOS:

## 1. Push (needs the Bitbucket ssh key on this Mac)

```bash
cd ~/Code/simplev-dev/meeting-desk
git push -u origin master
```

If Bitbucket answers "repository not found": create the empty repo `simpleo/meeting-desk`
(private, no README) at bitbucket.org, then push again. Report the push result.

## 2. Rebuild and restart after any change

```bash
./LAUNCH-MEETING-DESK.command      # = scripts/mac-launch.sh: builds, starts, waits for /healthz
tail -20 .launch.log
```

Run it ONCE at a time: two concurrent runs race on the container name.

## 3. Bedrock (only once Prathyush has put the keys in .env)

`.env` needs `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (and `AWS_SESSION_TOKEN` if temporary)
and a `BEDROCK_MODEL` that is enabled under Bedrock > Model access in ap-south-1. Then set
`FAKE_LLM=0` and `EXTRACTION_PROVIDER=bedrock` and run step 2 (the image is rebuilt with boto3).
Never print `.env`. Smoke test after restart: sign in, paste a Gemini summary, Extract, and check
that the points page says the provider is bedrock (`GET /meetings/{id}/extractions` shows it).

## 4. Verify and report

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/            # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/auth/me     # 401 without a cookie
docker compose -f docker-compose.live.yml logs --tail=30 api
```

Write `docs/MAC-LAUNCH-RESULT.md` with the push result, the launch tail and the curl results, and
commit it (attribution lines as in `git log`).
