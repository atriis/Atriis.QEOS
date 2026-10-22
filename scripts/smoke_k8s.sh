#!/usr/bin/env bash
# End-to-end checks of the Helm chart on kind (ADR-038, spec 5.10), through a `kubectl port-forward` to the gateway
# Service. The gateway runs with GATEWAY_TLS=off there, so the checks speak plain HTTP to the forward.
#   kubectl -n qeos port-forward svc/gateway 28080:8080 &
#   bash scripts/smoke_k8s.sh http://localhost:28080 qeos               # everything
#   bash scripts/smoke_k8s.sh http://localhost:28080 qeos --health-only # the health checks only
# Everything else needs qeos-collector on PATH (`pip install ./collector`). It registers a user and reads its
# verification token from the in-cluster CI PostgreSQL (`kubectl exec`), so it runs against kind only.
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <base-url> <namespace> [--health-only]" >&2
  exit 2
fi
BASE="${1%/}"
NAMESPACE="$2"
HEALTH_ONLY=false
[ "${3:-}" = "--health-only" ] && HEALTH_ONLY=true

# It creates users and runs psql in the cluster: never against a real deployment. The URL must be a local forward and
# the kubectl context a kind cluster
case "$BASE" in
  http://localhost:*|http://127.0.0.1:*) ;;
  *) echo "FAIL  $BASE is not http://localhost:<port> (a kubectl port-forward): kind only"; exit 1 ;;
esac
context="$(kubectl config current-context 2>/dev/null)"
case "$context" in
  kind-*) ;;
  *) echo "FAIL  kubectl context '${context:-none}' is not a kind cluster: kind only"; exit 1 ;;
esac
KUBECTL=(kubectl -n "$NAMESPACE")

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
failures=0

pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# check NAME EXPECTED_STATUS METHOD URL [curl args...]; body -> $TMP/body
check() {
  local name="$1" expected="$2" method="$3" url="$4"
  shift 4
  local status
  status="$(curl -s -o "$TMP/body" -w '%{http_code}' --max-time 30 -X "$method" "$@" "$url")"
  if [ "$status" = "$expected" ]; then
    pass "$name ($status)"
  else
    fail "$name: expected $expected, got $status: $(head -c 300 "$TMP/body" 2>/dev/null)"
  fi
}

# body_has NAME TEXT -- the last response body contains TEXT
body_has() {
  if grep -qF -- "$2" "$TMP/body" 2>/dev/null; then
    pass "$1"
  else
    fail "$1: body was $(head -c 300 "$TMP/body" 2>/dev/null)"
  fi
}

# json_id -- the first "id" of the last response body
json_id() { grep -o '"id":[0-9]*' "$TMP/body" | head -1 | cut -d: -f2; }

# ---- health: the gateway itself, one route per service, the dashboard ----
check "gateway /health" 200 GET "$BASE/health"
body_has "gateway /health body" '{"status":"healthy"}'
for svc in auth organizations projects ingestion test-management; do
  check "/health/$svc reaches the service" 200 GET "$BASE/health/$svc"
done
check "the dashboard answers /" 200 GET "$BASE/"
check "the dashboard's config.js" 200 GET "$BASE/config.js"

if [ "$failures" -ne 0 ]; then
  # A 301 here is a TLS-on gateway: the port is some other stack's (Compose's), not the kind forward
  echo "$failures k8s health check(s) failed: is $BASE the port-forward to the kind gateway?"
  exit 1
fi
if [ "$HEALTH_ONLY" = true ]; then
  echo "all k8s health checks passed"
  exit 0
fi

# ---- a real user: register -> verify (token from the database, as from the email) -> log in ----
SUFFIX="$(date +%s)-$$"
EMAIL="smoke-k8s-$SUFFIX@example.com"
PASSWORD="Smoke-pw-123456"
check "register a user -> auth-service" 202 POST "$BASE/api/v1/auth/register" \
  -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
VERIFY_TOKEN="$("${KUBECTL[@]}" exec deploy/postgres -- psql -U postgres -d auth_db -tAc \
  "SELECT token FROM pending_registrations WHERE email='$EMAIL' ORDER BY id DESC LIMIT 1" 2>"$TMP/psql_err" \
  | tr -d ' \r\n')"
[ -n "$VERIFY_TOKEN" ] || fail "no verification token in auth_db: $(head -c 300 "$TMP/psql_err")"
check "verify the email" 200 GET "$BASE/api/v1/auth/verify-email?token=$VERIFY_TOKEN"
check "log in" 200 POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
TOKEN="$(grep -o '"access_token":"[^"]*"' "$TMP/body" | head -1 | cut -d'"' -f4)"
AUTH=(-H "Authorization: Bearer ${TOKEN}")
check "/api/v1/users/me with the token" 200 GET "$BASE/api/v1/users/me" "${AUTH[@]}"
body_has "... is the new user" "\"email\":\"$EMAIL\""

# ---- organization -> project -> API key ----
check "create an organization -> organization-service" 201 POST "$BASE/api/v1/organizations" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Smoke k8s $SUFFIX\",\"slug\":\"smoke-k8s-$SUFFIX\",\"plan_tier\":\"free\"}"
ORG_ID="$(json_id)"
check "create a project -> project-service" 201 POST "$BASE/api/v1/organizations/${ORG_ID:-0}/projects" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d "{\"name\":\"Smoke k8s $SUFFIX\"}"
PROJECT_ID="$(json_id)"
check "create an API key -> ingestion-service" 201 POST "$BASE/api/v1/projects/${PROJECT_ID:-0}/api-keys" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d '{"name":"smoke-k8s"}'
API_KEY="$(sed -n 's/.*"key":"\(qeos_[^"]*\)".*/\1/p' "$TMP/body")"
[ -n "$API_KEY" ] || fail "the API key response carries no key"
check "test cases -> test-management-service" 200 GET "$BASE/api/v1/projects/${PROJECT_ID:-0}/cases" "${AUTH[@]}"

# ---- the collector: JUnit file -> qeos-collector -> gateway -> ingestion, then read back ----
cat > "$TMP/junit.xml" <<'XML'
<testsuites>
  <testsuite name="smoke-k8s">
    <testcase classname="smoke" name="passes" time="0.1"/>
    <testcase classname="smoke" name="fails" time="0.2"><failure message="boom">boom</failure></testcase>
    <testcase classname="smoke" name="skips"><skipped/></testcase>
  </testsuite>
</testsuites>
XML
if ! command -v qeos-collector >/dev/null 2>&1; then
  fail "qeos-collector is not on PATH: pip install ./collector"
elif QEOS_URL="$BASE" QEOS_API_KEY="$API_KEY" qeos-collector upload "$TMP/junit.xml" --branch smoke-k8s \
      --fail-on-error 2>"$TMP/collector_err"; then
  pass "qeos-collector uploads a JUnit file through the gateway"
else
  fail "qeos-collector upload: $(tail -c 400 "$TMP/collector_err")"
fi
RUN_ID="$(sed -n 's/.*uploaded run \([0-9][0-9]*\).*/\1/p' "$TMP/collector_err" 2>/dev/null | head -1)"
check "read the run back -> /api/v1/runs" 200 GET "$BASE/api/v1/runs/${RUN_ID:-0}" "${AUTH[@]}"
body_has "... with the collector's counts" '"total":3,"passed":1,"failed":1,"skipped":1,"errored":0'
check "the project lists it" 200 GET "$BASE/api/v1/projects/${PROJECT_ID:-0}/runs" "${AUTH[@]}"
body_has "... including the run" "\"id\":${RUN_ID:-0}"

if [ "$failures" -eq 0 ]; then
  echo "all k8s checks passed"
  exit 0
fi
echo "$failures k8s check(s) failed"
exit 1
