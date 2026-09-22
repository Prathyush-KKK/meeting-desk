#!/usr/bin/env bash
# Everything that has to be green before a merge, in one command: `make ci`.
#
#   ruff            api lint
#   pytest          api tests (404+; no network, a socket guard makes sure)
#   tsc -b          web typecheck
#   vitest run      web tests
#   vite build      web build (also what the API serves as WEB_DIST)
#   helm lint       the chart
#   helm template   the chart rendered twice: defaults, and values-internal with the
#                   ServiceMonitor and the PrometheusRule on
#   docker build    the API image (skipped, loudly, where there is no docker daemon)
#
# helm is fetched into ~/.local/bin if it is missing, so this runs on a bare box. Docker is not
# fetched: if there is no daemon the step reports SKIPPED and the run still passes, because a
# sandbox without a daemon is a fact about the sandbox, not about the Dockerfile.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HELM_VERSION="${HELM_VERSION:-v3.16.3}"
LOCAL_BIN="${LOCAL_BIN:-$HOME/.local/bin}"
PATH="$LOCAL_BIN:$PATH"
export PATH

CHART="deploy/helm/meeting-desk"
RENDER_DIR="${RENDER_DIR:-$ROOT/.ci}"

FAILED=()
SKIPPED=()

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '\033[32mok\033[0m   %s\n' "$*"; }
bad() { printf '\033[31mFAIL\033[0m %s\n' "$*"; FAILED+=("$1"); }
skip() { printf '\033[33mskip\033[0m %s - %s\n' "$1" "$2"; SKIPPED+=("$1"); }

step() { # step <name> <command...>
  local name="$1"; shift
  say "$name"
  if "$@"; then ok "$name"; else bad "$name"; fi
}

# --- helm, fetched if missing ---------------------------------------------------------------------
ensure_helm() {
  if command -v helm >/dev/null 2>&1; then return 0; fi
  say "helm is not installed - fetching $HELM_VERSION into $LOCAL_BIN"
  local arch
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) arch="$(uname -m)" ;;
  esac
  local tmp
  tmp="$(mktemp -d)"
  if curl -fsSL -o "$tmp/helm.tgz" "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz" \
    && tar -xzf "$tmp/helm.tgz" -C "$tmp" \
    && mkdir -p "$LOCAL_BIN" \
    && install -m 0755 "$tmp/linux-${arch}/helm" "$LOCAL_BIN/helm"; then
    rm -rf "$tmp"
    return 0
  fi
  rm -rf "$tmp"
  return 1
}

# --- the API ---------------------------------------------------------------------------------------
PY="$ROOT/api/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "api/.venv is missing. Run 'make install' first." >&2
  exit 2
fi

step "ruff" "$ROOT/api/.venv/bin/ruff" check "$ROOT/api"
step "pytest" env -C "$ROOT/api" "$PY" -m pytest -q

# --- the web app -------------------------------------------------------------------------------------
if [[ -d "$ROOT/web/node_modules" ]]; then
  step "tsc" env -C "$ROOT/web" npx tsc -b
  step "vitest" env -C "$ROOT/web" npx vitest run
  step "vite build" env -C "$ROOT/web" npx vite build
else
  skip "web" "web/node_modules is missing; run 'make web-install'"
fi

# --- the chart ---------------------------------------------------------------------------------------
if ensure_helm; then
  step "helm lint" helm lint "$CHART"
  step "helm lint (values-internal)" helm lint "$CHART" -f "$CHART/values-internal.yaml"
  mkdir -p "$RENDER_DIR"
  step "helm template (defaults)" bash -c \
    "helm template meeting-desk '$CHART' > '$RENDER_DIR/default.yaml'"
  step "helm template (values-internal)" bash -c \
    "helm template meeting-desk '$CHART' -f '$CHART/values-internal.yaml' > '$RENDER_DIR/internal.yaml'"
  # Both sides of the rotation flag render: off (the steady state) and on (during a key rotation).
  step "helm template (rotation on)" bash -c \
    "helm template meeting-desk '$CHART' --set externalSecrets.rotation.enabled=true \
      > '$RENDER_DIR/rotation.yaml'"
  # The two manifests the acceptance check names have to be in the internal render.
  say "the ServiceMonitor and the PrometheusRule render"
  if grep -q "^kind: ServiceMonitor" "$RENDER_DIR/internal.yaml" \
    && grep -q "^kind: PrometheusRule" "$RENDER_DIR/internal.yaml"; then
    ok "ServiceMonitor and PrometheusRule are in the render"
  else
    bad "ServiceMonitor / PrometheusRule missing from the render"
  fi
  # The previous token key is only ever asked of Infisical while a rotation is in flight; a
  # required-but-absent secret key stops the whole ExternalSecret from syncing.
  say "the previous token key is behind the rotation flag"
  if ! grep -q "MEETING_DESK_TOKEN_KEY_PREVIOUS" "$RENDER_DIR/default.yaml" \
    && grep -q "MEETING_DESK_TOKEN_KEY_PREVIOUS" "$RENDER_DIR/rotation.yaml"; then
    ok "MEETING_DESK_TOKEN_KEY_PREVIOUS is off by default and on with the flag"
  else
    bad "MEETING_DESK_TOKEN_KEY_PREVIOUS is not behind externalSecrets.rotation.enabled"
  fi
else
  skip "helm" "could not install helm (no network?); the chart was not rendered"
fi

# --- the image ---------------------------------------------------------------------------------------
say "docker build"
if ! command -v docker >/dev/null 2>&1; then
  skip "docker build" "docker is not installed here"
elif ! docker info >/dev/null 2>&1; then
  skip "docker build" "no docker daemon is reachable here (expected in the sandbox)"
else
  if docker build -f deploy/Dockerfile.api -t meeting-desk-api:ci .; then
    ok "docker build (api, the image the chart deploys)"
  else
    bad "docker build (api)"
  fi
  # The nginx image is the documented alternative, not what ships; build it so it cannot rot.
  if docker build -f deploy/Dockerfile.web -t meeting-desk-web:ci .; then
    ok "docker build (web, the split-origin alternative)"
  else
    bad "docker build (web)"
  fi
fi

# --- the verdict ---------------------------------------------------------------------------------------
printf '\n'
if ((${#SKIPPED[@]})); then
  printf '\033[33mskipped:\033[0m %s\n' "${SKIPPED[*]}"
fi
if ((${#FAILED[@]})); then
  printf '\033[31mFAILED:\033[0m %s\n' "${FAILED[*]}"
  exit 1
fi
printf '\033[32mci green\033[0m\n'
