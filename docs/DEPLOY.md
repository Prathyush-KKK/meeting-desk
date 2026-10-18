# Deploying Meeting Desk

Three ways to run it for real, from the smallest:

1. **One machine with Docker** - `scripts/live.sh` (Postgres + the app, real Google sign-in). See
   [GOOGLE_SETUP.md](GOOGLE_SETUP.md#5-run-it-with-your-account).
2. **The image anywhere** - one container serves the API and the web app; give it Postgres and the
   settings in [CONFIGURATION.md](CONFIGURATION.md).
3. **Kubernetes** - the Helm chart in `deploy/helm/meeting-desk/`, described below.

## The image

One image (`deploy/Dockerfile.api`) holds the API, the built SPA and the worker. Build it:

```bash
docker build -f deploy/Dockerfile.api -t meeting-desk:dev .                       # fake/openai only
docker build -f deploy/Dockerfile.api --build-arg EXTRAS='[llm]' -t meeting-desk:dev .   # + Vertex, Bedrock, Claude SDKs
```

Three stages: node + pnpm build `web/dist`, a Python stage builds a venv, and a `python:3.12-slim`
runtime carries neither toolchain. It runs as uid 10001, has a `HEALTHCHECK` on `/healthz`, and
exposes 8000 (API + SPA) and 9464 (metrics). `--workers 1` on purpose: the metrics server binds its
port inside the process, so more uvicorn workers would fight over it. Scale with replicas.

`deploy/Dockerfile.web` builds the SPA behind nginx instead. It is **not** what the chart deploys -
`main.py` already serves `WEB_DIST` at `/` with an SPA fallback, one origin means the session cookie
needs no CORS exception, and one image means one tag to move per release. It is kept working for a
split-origin deployment (a CDN, or the app on a different host); see the note at the top of the file.

## Google

Create the OAuth client as in [GOOGLE_SETUP.md](GOOGLE_SETUP.md), with your deployment's two
callback URLs registered.

**Vertex service account** (only with `EXTRACTION_PROVIDER=vertex`): create
`meeting-desk-vertex@<project>.iam.gserviceaccount.com` with **Vertex AI User**
(`roles/aiplatform.user`) and nothing else, create a JSON key, and store the whole file in your
secret store at `/meeting-desk/VERTEX_SERVICE_ACCOUNT_KEY`. The chart's second `ExternalSecret`
mounts it at `/var/run/secrets/vertex/key.json` and sets `GOOGLE_APPLICATION_CREDENTIALS`; nothing
else reads it. (On GKE, or with Workload Identity Federation, you can drop the key file.)

## Bedrock on EKS (IRSA)

With `EXTRACTION_PROVIDER=bedrock` (Converse API), or as the Vertex fallback
(`EXTRACT_FALLBACK_TO_BEDROCK=1`), pods on EKS can authenticate with IRSA - no AWS key anywhere:

```bash
eksctl create iamserviceaccount \
  --cluster <your-cluster> --namespace meeting-desk --name meeting-desk \
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
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0"
    }
  ]
}
```

and put the role ARN in `serviceAccount.annotations["eks.amazonaws.com/role-arn"]`
(`values-production.example.yaml`). The model must also be **enabled** in Bedrock model access for the
account in that region; `BEDROCK_MODEL` is configuration and has to be confirmed there.

## Secrets

Every secret is read by [External Secrets Operator](https://external-secrets.io) from
`/meeting-desk/<KEY>` in your secret store (Infisical, Vault, AWS Secrets Manager, GCP Secret
Manager, ...); name the store in `externalSecrets.secretStore`. No value is ever in
this repo or in a rendered manifest - only the path.

| path | what it is |
| --- | --- |
| `/meeting-desk/DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/meetingdesk` for your Postgres |
| `/meeting-desk/SESSION_SECRET` | 32+ random bytes; signs the session cookie. Rotating it signs everyone out. |
| `/meeting-desk/GOOGLE_CLIENT_ID` | the OAuth client above |
| `/meeting-desk/GOOGLE_CLIENT_SECRET` | its secret |
| `/meeting-desk/MEETING_DESK_TOKEN_KEY` | the Fernet key encrypting refresh tokens at rest - `make token-key` |
| `/meeting-desk/MEETING_DESK_TOKEN_KEY_PREVIOUS` | empty except during a rotation |
| `/meeting-desk/VERTEX_SERVICE_ACCOUNT_KEY` | the whole service-account JSON file |

## First deploy

```bash
# 0. Once per cluster: External Secrets Operator and a (Cluster)SecretStore for your secret manager.
kubectl create namespace meeting-desk

# 1. Render it and read it before anything is applied.
helm template meeting-desk deploy/helm/meeting-desk \
  -f deploy/helm/meeting-desk/values-production.example.yaml | less

# 2. Install. Copy the example values first and set your host, domain and secret store.
helm upgrade --install meeting-desk deploy/helm/meeting-desk \
  -n meeting-desk -f deploy/helm/meeting-desk/values-production.example.yaml \
  --set image.tag=0.1.0 --set build.commit=$(git rev-parse --short HEAD) --wait
```

The chart's pre-install / pre-upgrade hook runs `alembic upgrade head` as a Job before any new pod
starts, so a failed migration fails the release and the old pods keep serving.
procrastinate's own tables are **not** in Alembic; install them once per database:

```bash
kubectl -n meeting-desk exec deploy/meeting-desk-api -- python -m app.jobs.schema
```

Then, in the app: sign in, add the allow-list entries on **Admin**, and **Connect an account**
twice (the Admin page warns until there are two - reads fall back across connections).

## The worker

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

## The token key: generating and rotating

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
   both old and new rows open (dual-read during the rotation).
4. `curl -X POST .../admin/connections/rotate-keys` (an admin session) re-encrypts every row with
   the new key and stamps the new version.
5. Set `externalSecrets.rotation.enabled=false`, clear `MEETING_DESK_TOKEN_KEY_PREVIOUS` and deploy
   again.

Losing the key means every admin has to reconnect their Google account - nothing else is lost.
