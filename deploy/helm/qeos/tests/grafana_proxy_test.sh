#!/usr/bin/env bash
# The grafana-proxy sidecar (templates/grafana.yaml, files/grafana-proxy.conf.template) exactly as the chart renders it
# (image, command, settings, template), run in docker as the pod runs it (user 101, read-only root, no capabilities)
# in front of a stub Grafana on Grafana's unix socket (a volume both share, as the pod's emptyDir) that echoes what
# reaches it. Checks what a cluster cannot show: the key opens it (case included), anything else is 403
# {"detail":"Forbidden"}, the key never reaches Grafana while X-QEOS-User-Email and Host do, /_health needs no key and
# passes neither header, bodies up to 10m pass and larger get 413, a malformed key stops it before nginx starts, and
# the key is never logged. Needs helm 3, yq (mikefarah, v4), docker and curl; no cluster.
#   bash deploy/helm/qeos/tests/grafana_proxy_test.sh
set -uo pipefail

CHART="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mktemp -d)"
RUN="qeos-grafana-proxy-test-$$"
containers=()
cleanup() {
  [ "${#containers[@]}" -eq 0 ] || docker rm -f "${containers[@]}" >/dev/null 2>&1
  docker volume rm -f "$RUN-socket" >/dev/null 2>&1
  rm -rf "$OUT"
}
trap cleanup EXIT
# Git Bash: docker gets Windows paths for bind mounts, and container paths unconverted
docker() { MSYS_NO_PATHCONV=1 command docker "$@"; }
hostpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# ---- the sidecar as rendered (values-ci.yaml) ----
if ! helm template qeos "$CHART" -f "$CHART/values-ci.yaml" --api-versions monitoring.coreos.com/v1/ServiceMonitor \
    --api-versions monitoring.coreos.com/v1/PrometheusRule >"$OUT/ci.yaml" 2>"$OUT/render.err"; then
  echo "FAIL  helm template: $(tail -n 3 "$OUT/render.err")"
  exit 1
fi
sidecar='select(.kind == "Deployment" and .metadata.name == "grafana") | .spec.template.spec.containers[] | select(.name == "grafana-proxy")'
IMAGE="$(yq ea "$sidecar | .image" "$OUT/ci.yaml" | tr -d '\r')"
SHELL_CMD="$(yq ea "$sidecar | .command[0]" "$OUT/ci.yaml" | tr -d '\r')"
SCRIPT="$(yq ea "$sidecar | .command[2]" "$OUT/ci.yaml" | tr -d '\r')"
[ "$(yq ea "$sidecar | .command[1]" "$OUT/ci.yaml" | tr -d '\r')" = -c ] || { echo "FAIL  the sidecar's command is not <shell> -c <script>"; exit 1; }
# The emptyDir nginx's entrypoint renders the template into (a tmpfs here, writable by everyone as an emptyDir is)
RENDERED="$(yq ea "$sidecar | .env[] | select(.name == \"NGINX_ENVSUBST_OUTPUT_DIR\") | .value" "$OUT/ci.yaml" | tr -d '\r')"
# Grafana's socket, as the grafana container is told to listen on it
SOCKET="$(yq ea 'select(.kind == "Deployment" and .metadata.name == "grafana") | .spec.template.spec.containers[]
  | select(.name == "grafana") | .env[] | select(.name == "GF_SERVER_SOCKET") | .value' "$OUT/ci.yaml" | tr -d '\r')"
[ -n "$SOCKET" ] || { echo "FAIL  the grafana container sets no GF_SERVER_SOCKET"; exit 1; }
ENVS=()
while IFS= read -r line; do
  [ -n "$line" ] && ENVS+=(-e "$line")
done < <(yq ea "$sidecar | .env[] | select(.value != null) | .name + \"=\" + .value" "$OUT/ci.yaml" | tr -d '\r')
mkdir -p "$OUT/templates" "$OUT/stub"
yq ea 'select(.kind == "ConfigMap" and .metadata.name == "qeos-grafana-proxy") | .data["grafana-proxy.conf.template"]' "$OUT/ci.yaml" \
  | tr -d '\r' > "$OUT/templates/grafana-proxy.conf.template"
# The stub Grafana: everything that reaches the socket, echoed
cat > "$OUT/stub/default.conf" <<NGINX
server {
    listen unix:$SOCKET;
    default_type text/plain;
    # Any size: the sidecar's limit is the one under test
    client_max_body_size 0;
    location / {
        return 200 "uri=\$request_uri method=\$request_method key=[\$http_x_qeos_grafana_key] email=[\$http_x_qeos_user_email] host=[\$http_host]";
    }
}
NGINX
chmod -R a+rX "$OUT"
# The socket's volume, writable by nginx's user as the emptyDir is by the pod's
docker volume create "$RUN-socket" >/dev/null
docker run --rm --user 0 -v "$RUN-socket:/socket" --entrypoint chmod "$IMAGE" 1777 /socket || { echo "FAIL  the socket volume"; exit 1; }

# start_proxy NAME KEY -- the sidecar with GRAFANA_PROXY_KEY=KEY, as the pod runs it; its published port on stdout
start_proxy() {
  docker run -d --name "$1" --user 101:101 --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:mode=1777 --tmpfs "$RENDERED:mode=1777" \
    -v "$(hostpath "$OUT/templates"):/etc/nginx/templates:ro" -v "$RUN-socket:${SOCKET%/*}" "${ENVS[@]}" -e "GRAFANA_PROXY_KEY=$2" \
    -p 127.0.0.1::8080 --entrypoint "$SHELL_CMD" "$IMAGE" -c "$SCRIPT" >/dev/null || return 1
  containers+=("$1")
}
start_stub() {
  docker run -d --name "$1-stub" --network none --user 101:101 --read-only --cap-drop ALL \
    --tmpfs /tmp:mode=1777 -v "$RUN-socket:${SOCKET%/*}" -v "$(hostpath "$OUT/stub/default.conf"):/etc/nginx/conf.d/default.conf:ro" \
    --entrypoint nginx "$IMAGE" -g 'daemon off;' >/dev/null || return 1
  containers+=("$1-stub")
}
# exited NAME -- the container's exit code once it stopped (at most 20 s), or "running"
exited() {
  for _ in $(seq 20); do
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = false ] && { docker inspect -f '{{.State.ExitCode}}' "$1"; return; }
    sleep 1
  done
  echo running
}

KEY="Qe0s_grafana-proxy-test-key-0123456789abcdefXYZ"
P="$RUN-main"
if ! start_proxy "$P" "$KEY" || ! start_stub "$P"; then
  echo "FAIL  could not start the sidecar and the stub ($IMAGE)"
  exit 1
fi
PORT="$(docker port "$P" 8080/tcp | head -n 1 | sed 's/.*://' | tr -d '\r')"
BASE="http://127.0.0.1:$PORT"
for _ in $(seq 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$BASE/_health")" = 200 ] && break
  sleep 1
done

# req NAME WANT_STATUS WANT_BODY PATH [curl args...] -- WANT_BODY is a glob
req() {
  local name="$1" want="$2" body="$3" path="$4" code got
  shift 4
  code="$(curl -s -o "$OUT/body" -D "$OUT/headers" -w '%{http_code}' --max-time 10 "$@" "$BASE$path")"
  got="$(cat "$OUT/body" 2>/dev/null)"
  # shellcheck disable=SC2053
  if [ "$code" = "$want" ] && [[ "$got" == $body ]]; then
    pass "$name: $code $got"
  else
    fail "$name: got $code '$got', want $want '$body'"
  fi
}
FORBIDDEN='{"detail":"Forbidden"}'
req "/_health needs no key and asks Grafana's /grafana/api/health" 200 "uri=/grafana/api/health method=GET key=[[]]*" /_health
req "/_health passes neither a client's key nor its user header" 200 "uri=/grafana/api/health method=GET key=[[]] email=[[]]*" /_health \
  -H "X-QEOS-Grafana-Key: $KEY" -H "X-QEOS-User-Email: admin@example.com"
req "no key" 403 "$FORBIDDEN" /grafana/api/health
grep -qi '^content-type: application/json' "$OUT/headers" && pass "... as application/json" || fail "... content type: $(grep -i '^content-type' "$OUT/headers")"
req "an empty key" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key;"
req "a wrong key" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key: ci-not-the-key-0123456789abcdefghijklmn"
req "the key in another case" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key: $(printf '%s' "$KEY" | tr '[:lower:]' '[:upper:]')"
req "the key with a suffix" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key: ${KEY}x"
req "the key without its last character" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key: ${KEY%?}"
req "the key twice" 403 "$FORBIDDEN" /grafana/api/health -H "X-QEOS-Grafana-Key: $KEY" -H "X-QEOS-Grafana-Key: $KEY"
req "the user header alone" 403 "$FORBIDDEN" /grafana/api/user -H "X-QEOS-User-Email: admin@example.com"
req "the key: forwarded without it, with the user header and the public Host" 200 \
  "uri=/grafana/api/user?x=1 method=GET key=[[]] email=[[]ops@example.com[]] host=[[]qeos.example.com[]]" \
  "/grafana/api/user?x=1" -H "X-QEOS-Grafana-Key: $KEY" -H "X-QEOS-User-Email: ops@example.com" -H "Host: qeos.example.com"
req "the key, a POST" 200 "uri=/grafana/api/ds/query method=POST key=[[]]*" /grafana/api/ds/query \
  -H "X-QEOS-Grafana-Key: $KEY" -H "Content-Type: application/json" -d '{}'
# The gateway's body limit (10m): a large dashboard saved passes, more is 413
head -c $((9 * 1024 * 1024)) /dev/zero > "$OUT/9m"
head -c $((11 * 1024 * 1024)) /dev/zero > "$OUT/11m"
req "the key, a 9 MiB body" 200 "uri=/grafana/api/dashboards/db method=POST key=[[]]*" /grafana/api/dashboards/db \
  -H "X-QEOS-Grafana-Key: $KEY" --data-binary @"$OUT/9m"
req "the key, an 11 MiB body" 413 "*" /grafana/api/dashboards/db -H "X-QEOS-Grafana-Key: $KEY" --data-binary @"$OUT/11m"
docker logs "$P" >"$OUT/main.log" 2>&1
if grep -qF -- "$KEY" "$OUT/main.log"; then
  fail "the key is in the sidecar's log"
else
  pass "the key is nowhere in the sidecar's log ($(wc -l < "$OUT/main.log") lines)"
fi

# ---- a key the gateway would refuse stops the sidecar before nginx starts, without printing it ----
long="$(printf 'k%.0s' $(seq 129))"
for case in "31 characters:abcdefghijklmnopqrstuvwxyz01234" "129 characters:$long" \
    'a quote:abcdefghijklmnopqrstuvwxyz0123456"' 'a dollar:abcdefghijklmnopqrstuvwxyz012345$x' \
    "a space:abcdefghijklmnopqrstuvwx yz0123456789" "empty:"; do
  label="${case%%:*}"
  key="${case#*:}"
  name="$RUN-bad-$(printf '%s' "$label" | tr -c 'a-z0-9' '-')"
  start_proxy "$name" "$key" || { fail "could not start the sidecar with $label"; continue; }
  code="$(exited "$name")"
  docker logs "$name" >"$OUT/bad.log" 2>&1
  if [ "$code" != running ] && [ "$code" != 0 ] && grep -q '^grafana-proxy: ' "$OUT/bad.log" \
      && { [ -z "$key" ] || ! grep -qF -- "$key" "$OUT/bad.log"; } && ! grep -q 'nginx' "$OUT/bad.log"; then
    pass "a key of $label is refused before nginx starts (exit $code), not printed"
  else
    fail "a key of $label: exit '$code', log: $(head -c 300 "$OUT/bad.log")"
  fi
done
# The longest key the gateway accepts starts
name="$RUN-max"
if start_proxy "$name" "$(printf 'K%.0s' $(seq 128))" && [ "$(exited "$name")" = running ]; then
  pass "a key of 128 characters starts"
else
  fail "a key of 128 characters: $(docker logs "$name" 2>&1 | head -c 300)"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures grafana-proxy check(s) failed"
  exit 1
fi
echo "all grafana-proxy checks passed"
