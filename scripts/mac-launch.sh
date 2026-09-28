#!/usr/bin/env bash
# Start Meeting Desk for real on this machine: docker-compose.live.yml, the shipped image, Postgres,
# Google sign-in. Idempotent: run it again after editing .env or pulling a change.
#
#   scripts/mac-launch.sh            build (if needed), start, wait for /healthz
#   scripts/mac-launch.sh logs       follow the API log
#   scripts/mac-launch.sh down       stop (the database volume stays)
#   scripts/mac-launch.sh reset      stop and delete the database volume
#
# Needs docker with the compose plugin (Colima or OrbStack on the Mac) and openssl. No Python or
# node on the host: the image builds both.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.live.yml)
ENV_FILE=.env

case "${1:-up}" in
  logs) exec "${COMPOSE[@]}" logs -f --tail=200 api ;;
  down) exec "${COMPOSE[@]}" down ;;
  reset) exec "${COMPOSE[@]}" down -v ;;
  up) ;;
  *) echo "usage: $0 [up|logs|down|reset]" >&2; exit 2 ;;
esac

if ! docker info >/dev/null 2>&1; then
  echo "docker is not running (colima start / open OrbStack), then run this again." >&2
  exit 1
fi

[ -f "$ENV_FILE" ] || cp .env.live.example "$ENV_FILE"

# --- fill what can be generated -----------------------------------------------------------------
value_of() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true; }
set_value() {
  # Replace the line if the key exists, append otherwise. Values never touch the shell's history.
  local key=$1 val=$2 tmp
  tmp=$(mktemp)
  if grep -qE "^$key=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp"; printf '%s=%s\n' "$key" "$val" >>"$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
}

if [ -z "$(value_of SESSION_SECRET)" ]; then
  set_value SESSION_SECRET "$(openssl rand -base64 48 | tr -d '\n')"
  echo "SESSION_SECRET: generated"
fi
if [ -z "$(value_of MEETING_DESK_TOKEN_KEY)" ]; then
  # A Fernet key is the url-safe base64 of 32 random bytes - what `make token-key` prints.
  set_value MEETING_DESK_TOKEN_KEY "$(openssl rand 32 | base64 | tr '+/' '-_' | tr -d '\n')"
  echo "MEETING_DESK_TOKEN_KEY: generated (losing it means every admin reconnects; back up .env)"
fi

# --- refuse to start without the things only a person can supply -------------------------------
missing=()
[ -n "$(value_of GOOGLE_CLIENT_ID)" ] || missing+=(GOOGLE_CLIENT_ID)
[ -n "$(value_of GOOGLE_CLIENT_SECRET)" ] || missing+=(GOOGLE_CLIENT_SECRET)
[ -n "$(value_of BOOTSTRAP_ADMINS)" ] || missing+=(BOOTSTRAP_ADMINS)
if [ ${#missing[@]} -gt 0 ]; then
  echo "Fill these in $ENV_FILE first: ${missing[*]}" >&2
  echo "The OAuth client: README.md, 'GCP project setup'. Redirect URIs to register:" >&2
  echo "  $(value_of PUBLIC_URL)/auth/callback" >&2
  echo "  $(value_of PUBLIC_URL)/admin/connections/callback" >&2
  exit 1
fi

# --- the model: which extra to build, and is it configured --------------------------------------
# A value from .env, else from the shell: docker-compose.live.yml passes the credentials through
# from either.
setting() {
  local v
  v="$(value_of "$1")"
  [ -n "$v" ] || v="${!1:-}"
  printf '%s' "$v"
}

provider="$(value_of EXTRACTION_PROVIDER)"
if [ "$(value_of FAKE_LLM)" = "0" ]; then
  case "$provider" in
    bedrock | bedrock_openai)
      # Two credentials, the app picks the same way (app/extract/__init__.py):
      #   AWS_BEARER_TOKEN_BEDROCK + BEDROCK_BASE_URL - the nutrition service's Bedrock API key on
      #     the OpenAI-compatible endpoint. Plain HTTP: no SDK in the image.
      #   AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY - the Converse API in BEDROCK_REGION, which
      #     needs boto3 (the [bedrock] extra). EXTRACTION_PROVIDER=bedrock only.
      # BEDROCK_MODEL_ID wins over BEDROCK_MODEL when both are set.
      token="$(setting AWS_BEARER_TOKEN_BEDROCK)"
      base_url="$(setting BEDROCK_BASE_URL)"
      model="$(setting BEDROCK_MODEL_ID)"
      model="${model:-$(setting BEDROCK_MODEL)}"
      half=""
      [ -n "$token" ] || [ -z "$base_url" ] || half=AWS_BEARER_TOKEN_BEDROCK
      [ -n "$base_url" ] || [ -z "$token" ] || half=BEDROCK_BASE_URL
      if [ -n "$token" ] && [ -n "$base_url" ]; then
        path="OpenAI-compatible endpoint"
      elif [ "$provider" = bedrock_openai ]; then
        echo "EXTRACTION_PROVIDER=bedrock_openai needs AWS_BEARER_TOKEN_BEDROCK and BEDROCK_BASE_URL (in $ENV_FILE or the shell)." >&2
        exit 1
      elif [ -n "$(setting AWS_ACCESS_KEY_ID)" ] && [ -n "$(setting AWS_SECRET_ACCESS_KEY)" ]; then
        path="Converse API"
        export EXTRAS="[bedrock]"
        [ -z "$half" ] || echo "note: $half is empty, so the access key pair (the Converse API) is used."
      elif [ -n "$half" ]; then
        echo "$half is empty: EXTRACTION_PROVIDER=bedrock with a Bedrock API key needs both AWS_BEARER_TOKEN_BEDROCK and BEDROCK_BASE_URL." >&2
        exit 1
      elif [ -n "$(setting AWS_ACCESS_KEY_ID)" ]; then
        echo "AWS_SECRET_ACCESS_KEY is empty: the access key pair needs both halves." >&2
        exit 1
      else
        echo "EXTRACTION_PROVIDER=bedrock needs a credential (in $ENV_FILE or the shell), either:" >&2
        echo "  AWS_BEARER_TOKEN_BEDROCK + BEDROCK_BASE_URL (+ BEDROCK_MODEL_ID) - the nutrition service's values, or" >&2
        echo "  AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ BEDROCK_MODEL, BEDROCK_REGION) - the Converse API." >&2
        exit 1
      fi
      [ -n "$model" ] || { echo "BEDROCK_MODEL_ID (or BEDROCK_MODEL) is empty." >&2; exit 1; }
      if [ "$path" = "Converse API" ]; then
        echo "extraction: Bedrock ($path) $model in $(setting BEDROCK_REGION)"
      else
        echo "extraction: Bedrock ($path) $model at $base_url"
      fi
      ;;
    vertex)
      export EXTRAS="[vertex]"
      [ -n "$(value_of VERTEX_PROJECT)" ] || { echo "VERTEX_PROJECT is empty." >&2; exit 1; }
      echo "extraction: Vertex $(value_of VERTEX_MODEL) in $(value_of VERTEX_LOCATION), project $(value_of VERTEX_PROJECT)"
      ;;
    *) echo "FAKE_LLM=0 but EXTRACTION_PROVIDER is '$provider' (bedrock, bedrock_openai or vertex)." >&2; exit 1 ;;
  esac
else
  echo "extraction: rule-based (FAKE_LLM=1)"
fi

# --- build, start, wait -------------------------------------------------------------------------
"${COMPOSE[@]}" up -d --build
url="$(value_of PUBLIC_URL)"
url="${url:-http://localhost:8000}"
echo -n "waiting for $url/healthz "
for _ in $(seq 1 60); do
  if curl -fsS "$url/healthz" >/dev/null 2>&1; then
    echo
    echo "Meeting Desk is up: $url"
    echo "Sign in with a $(value_of GOOGLE_HOSTED_DOMAIN) account on the allow-list ($(value_of BOOTSTRAP_ADMINS)),"
    echo "then Admin -> Connect an account. Logs: $0 logs"
    exit 0
  fi
  echo -n .
  sleep 2
done
echo
echo "not healthy after 120 s; the last log lines:" >&2
"${COMPOSE[@]}" logs --tail=60 api >&2
exit 1
