#!/usr/bin/env bash
# The QEOS chart's monitoring on kind (ADR-038 Stage 2), seen from the cluster's Prometheus, Alertmanager and Grafana:
# every scrape target up with Compose's job names, Compose's rule groups loaded (qeos-host left out), the ingestion
# scrape keeping honor_labels with its series still in the QEOS namespace, postgres-exporter connected as qeos_monitor,
# Watchdog in Alertmanager with no channel configured (the null receiver, Review Focus 4), and Grafana behind the
# gateway's sign-in and the grafana-proxy sidecar's key (Review Focus 3), with Compose's dashboards and a data source
# that reaches Prometheus. It port-forwards and queries APIs; the only write is the Grafana user its auth proxy check
# signs in (qeos-k8s-check@example.com). It reads grafana-proxy-key and grafana-admin-password from the CI Secret
# (SECRET, qeos-secrets) and never prints them. Needs kubectl, curl, base64 and yq (mikefarah, v4).
#   bash scripts/check_k8s_monitoring.sh qeos [qeos-monitoring]
# The forwards use local ports PROM_PORT (29090), AM_PORT (29093), GW_PORT (29080, the gateway), GF_PORT (29300,
# Service grafana), GF_DIRECT_PORT (29301, the Grafana pod's 3000, where nothing must answer) and GF_POD_PORT (29302,
# the Grafana pod's 8080).
set -uo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <namespace> [monitoring namespace]" >&2
  exit 2
fi
NAMESPACE="$1"
MONITORING="${2:-qeos-monitoring}"
PROM_PORT="${PROM_PORT:-29090}"
AM_PORT="${AM_PORT:-29093}"
GW_PORT="${GW_PORT:-29080}"
GF_PORT="${GF_PORT:-29300}"
GF_DIRECT_PORT="${GF_DIRECT_PORT:-29301}"
GF_POD_PORT="${GF_POD_PORT:-29302}"
# The CI Secret holding grafana-proxy-key and grafana-admin-password (values-ci.yaml, secrets.source kubernetes)
SECRET="${SECRET:-qeos-secrets}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Scrapes every 15 s, rules every 30 s, alerts sent to Alertmanager after their first evaluation: 3 minutes is plenty
WAIT_SECONDS="${WAIT_SECONDS:-180}"

# Prometheus's view of a CI cluster (the job counts are kind's replicas): kind only
context="$(kubectl config current-context 2>/dev/null)"
case "$context" in
  kind-*) ;;
  *) echo "FAIL  kubectl context '${context:-none}' is not a kind cluster: kind only"; exit 1 ;;
esac

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

TMP="$(mktemp -d)"
forwards=()
cleanup() {
  [ "${#forwards[@]}" -eq 0 ] || kill "${forwards[@]}" 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

# forward NAMESPACE TARGET LOCAL REMOTE READY_PATH -- a port-forward to a Service (or to TARGET kind/name, such as
# deploy/grafana), once READY_PATH answers 200
forward() {
  local target="svc/$2" log="$TMP/forward-${2//\//-}.log"
  case "$2" in */*) target="$2" ;; esac
  kubectl -n "$1" port-forward "$target" "$3:$4" >"$log" 2>&1 &
  forwards+=("$!")
  for _ in $(seq 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$3$5")" = 200 ] && return 0
    sleep 1
  done
  fail "no answer from $2 through localhost:$3: $(head -c 300 "$log")"
  return 1
}
forward "$MONITORING" qeos-monitoring-prometheus "$PROM_PORT" 9090 /-/ready || exit 1
forward "$NAMESPACE" alertmanager "$AM_PORT" 9093 /-/ready || exit 1
PROM="http://localhost:$PROM_PORT"
AM="http://localhost:$AM_PORT"

# fetch YQ URL [curl args...] -- a GET's JSON answer through the yq expression YQ; every API read goes through it.
# A failed request (no 200, an empty or non-JSON body, or from a Prometheus /api/v1/ endpoint a status that is not
# "success") prints "fetch failed: ..." and returns 1 instead, which no expected value equals: a dropped port-forward
# never passes a "nothing down" or "no rule in error" check
fetch() {
  local expr="$1" url="$2" code status
  shift 2
  code="$(curl -s -o "$TMP/fetch.json" -w '%{http_code}' --max-time 10 "$@" "$url")"
  if [ "$code" != 200 ] || [ ! -s "$TMP/fetch.json" ] || ! yq -p json -o yaml '.' "$TMP/fetch.json" >/dev/null 2>&1; then
    echo "fetch failed: HTTP ${code:-none} from $url"
    return 1
  fi
  case "$url" in
    */api/v1/*)
      status="$(yq -p json -o yaml '.status' "$TMP/fetch.json" 2>/dev/null | tr -d '\r')"
      if [ "$status" != success ]; then
        echo "fetch failed: status ${status:-none} from $url"
        return 1
      fi
      ;;
  esac
  yq -p json -o yaml "$expr" "$TMP/fetch.json" | tr -d '\r'
}
# query PROMQL YQ -- an instant query's JSON through YQ (fetch: a failed query prints "fetch failed: ...")
query() { fetch "$2" "$PROM/api/v1/query" -G --data-urlencode "query=$1"; }
# eventually NAME WANT PROMQL YQ -- polls until the query gives WANT, at most WAIT_SECONDS after the script started
eventually() {
  local got
  while :; do
    got="$(query "$3" "$4")"
    [ "$got" = "$2" ] && { pass "$1: $got"; return 0; }
    [ "$SECONDS" -ge "$WAIT_SECONDS" ] && { fail "$1: got '$got', want '$2'"; return 1; }
    sleep 5
  done
}
by_job='[.data.result[] | .metric.job + "=" + .value[1]] | sort | join(" ")'

# ---- the scrape targets: Compose's job names, every replica up ----
want="alertmanager=1 auth=2 ingestion=2 organization=2 postgres=1 project=2 test-management=2"
if ! eventually "targets up in $NAMESPACE, by job" "$want" "count by (job) (up{namespace=\"$NAMESPACE\"} == 1)" "$by_job"; then
  fetch "[.data.activeTargets[] | select(.labels.namespace == \"$NAMESPACE\") | .labels.job + \" \" + .health + \" \" + .lastError] | .[]" \
    "$PROM/api/v1/targets"
fi
eventually "no target of $NAMESPACE down" "" "up{namespace=\"$NAMESPACE\"} == 0" "$by_job"

# ---- the series keep the services' own labels ----
# The operator's target label service="<Kubernetes Service>" is dropped: the services' service="auth" stays as on Compose
eventually "build_info by service (the services' own label)" "auth=2 ingestion=2 organization=2 project=2 test-management=2" \
  "count by (service) (build_info{namespace=\"$NAMESPACE\"})" '[.data.result[] | .metric.service + "=" + .value[1]] | sort | join(" ")'
got="$(query '{exported_service=~".+"}' '.data.result | length')"
[ "$got" = 0 ] && pass "no series has exported_service (no clash with the target's service label)" \
  || fail "$got series carry exported_service"

# ---- the ingestion scrape: honor_labels (the loop jobs' heartbeats carry their own job), namespace still enforced ----
fetch '.data.yaml' "$PROM/api/v1/status/config" > "$TMP/config.yaml" || fail "Prometheus's configuration: $(cat "$TMP/config.yaml")"
job="serviceMonitor/$NAMESPACE/qeos-ingestion/0"
honor="$(yq "[.scrape_configs[] | select(.job_name == \"$job\")] | .[0].honor_labels" "$TMP/config.yaml" | tr -d '\r')"
[ "$honor" = true ] && pass "$job has honor_labels: true" || fail "$job's honor_labels is '$honor'"
# The other jobs label the series themselves (Prometheus leaves honor_labels: false out of the configuration it shows)
honor="$(yq "[.scrape_configs[] | select(.job_name == \"serviceMonitor/$NAMESPACE/qeos-apis/0\")] | (length | tostring) + \" \" + (.[0].honor_labels // false | tostring)" "$TMP/config.yaml" | tr -d '\r')"
[ "$honor" = "1 false" ] && pass "serviceMonitor/$NAMESPACE/qeos-apis/0 has honor_labels: false" || fail "qeos-apis's job count and honor_labels are '$honor'"
# Every series the ingestion targets yield (their pod and port labels; kube-state-metrics, which describes the same
# pods, left out) carries namespace=<QEOS namespace>, its own job label or not
got="$(query "count by (namespace) ({pod=~\"ingestion-service-.+\", endpoint=\"http\", job!=\"kube-state-metrics\"})" \
  '[.data.result[] | .metric.namespace] | sort | join(" ")')"
[ "$got" = "$NAMESPACE" ] && pass "every series of the ingestion scrape is in namespace $NAMESPACE" \
  || fail "the ingestion scrape's series are in namespaces '$got'"
got="$(query "count by (namespace) ({__name__=~\"job_last_(success|error)_timestamp_seconds\"})" '[.data.result[] | .metric.namespace] | sort | join(" ")')"
case "$got" in
  "") echo "note  no loop job heartbeat yet (job_last_*_timestamp_seconds): nothing to check beyond the line above" ;;
  "$NAMESPACE") pass "the loop jobs' heartbeats (their own job label) are in namespace $NAMESPACE" ;;
  *) fail "the loop jobs' heartbeats are in namespaces '$got'" ;;
esac

# ---- postgres-exporter: connected as qeos_monitor; the recording rules on its series ----
eventually "pg_up (postgres-exporter reaches PostgreSQL)" 1 "pg_up{namespace=\"$NAMESPACE\"}" '.data.result[0].value[1]'
eventually "postgresql_database_size_bytes (qeos-recording) for auth_db" 1 \
  "count(postgresql_database_size_bytes{datname=\"auth_db\", namespace=\"$NAMESPACE\"})" '.data.result[0].value[1]'

# ---- the rules: Compose's groups, without monitoring.skipRuleGroups' qeos-host and qeos-containers ----
groups="$(fetch '[.data.groups[].name | select(test("^qeos-"))] | sort | join(" ")' "$PROM/api/v1/rules")"
[[ " $groups " == *" qeos-services "* && " $groups " == *" qeos-thresholds "* && " $groups " != *" qeos-host "* \
    && " $groups " != *" qeos-containers "* ]] \
  && pass "rule groups: $groups (qeos-host and qeos-containers left out)" || fail "rule groups are '$groups'"
bad="$(fetch '[.data.groups[] | select(.name | test("^qeos-")) | .rules[] | select(.health == "err") | .name + ": " + .lastError] | join("; ")' \
  "$PROM/api/v1/rules")"
[ -z "$bad" ] && pass "no QEOS rule fails to evaluate" || fail "rules in error: $bad"

# ---- Alertmanager: Watchdog arrives, with no channel configured (the null receiver) ----
while :; do
  got="$(fetch '[.[] | select(.labels.alertname == "Watchdog") | .labels.namespace + " " + ([.receivers[].name] | join(","))] | join(";")' \
    "$AM/api/v2/alerts")"
  { [ -n "$got" ] && [[ "$got" != "fetch failed"* ]]; } || [ "$SECONDS" -ge "$WAIT_SECONDS" ] && break
  sleep 5
done
[ "$got" = "$NAMESPACE null" ] && pass "Alertmanager holds Watchdog (namespace $NAMESPACE), routed to the null receiver" \
  || fail "Watchdog in Alertmanager: '$got', want '$NAMESPACE null'"
if config="$(fetch '.config.original' "$AM/api/v2/status")"; then
  channels="$(printf '%s\n' "$config" | grep -c -E '(email|slack|msteamsv2)_configs')"
  [ "$channels" = 0 ] && pass "Alertmanager runs with no channel configured" || fail "Alertmanager's configuration has $channels channel(s)"
else
  fail "Alertmanager's configuration: $config"
fi

# ---- Grafana: behind the gateway's sign-in, and behind the grafana-proxy sidecar's key (Review Focus 3) ----
# The key and the admin password come from the CI Secret (secrets.source kubernetes) into files only this user reads;
# curl reads them from there, so neither is ever on a command line or printed
umask 077
secret_value() { kubectl -n "$NAMESPACE" get secret "$SECRET" -o "jsonpath={.data.$1}" | base64 -d; }
{ printf 'X-QEOS-Grafana-Key: '; secret_value grafana-proxy-key; printf '\n'; } > "$TMP/key.header"
{ printf 'machine localhost login admin password '; secret_value grafana-admin-password; printf '\n'; } > "$TMP/netrc"
[ "$(wc -c < "$TMP/key.header")" -gt 52 ] || fail "no grafana-proxy-key in Secret $SECRET"
forward "$NAMESPACE" gateway "$GW_PORT" 8080 /health || exit 1
forward "$NAMESPACE" grafana "$GF_PORT" 3000 /_health || exit 1
# The pod's own ports, as anyone allowed pods/portforward reaches them: the sidecar's 8080 only
forward "$NAMESPACE" deploy/grafana "$GF_POD_PORT" 8080 /_health || exit 1
GW="http://localhost:$GW_PORT"
GF="http://localhost:$GF_PORT"
GF_POD="http://localhost:$GF_POD_PORT"

# status_of NAME WANT URL [curl args...] -- the status (and, for a redirect, the Location) URL answers
status_of() {
  local name="$1" want="$2" url="$3" got
  shift 3
  got="$(curl -s -o "$TMP/body" -D "$TMP/headers" -w '%{http_code}' --max-time 10 "$@" "$url")"
  if [ "${got:0:1}" = 3 ]; then
    got="$got $(sed -n 's/^[Ll]ocation: *//p' "$TMP/headers" | tr -d '\r')"
  fi
  case "$got" in
    $want) pass "$name: $got" ;;
    *) fail "$name: got '$got', want '$want'" ;;
  esac
}
# Through the gateway, nobody reaches Grafana without the qeos_grafana cookie, whatever headers the client forges
status_of "/grafana/ through the gateway without a cookie" "302 /monitoring?next=*" "$GW/grafana/"
status_of "/grafana/ through the gateway with a forged key and user header" "302 /monitoring?next=*" "$GW/grafana/" \
  -H @"$TMP/key.header" -H "X-QEOS-User-Email: admin@example.com"
# Service grafana is the sidecar: the key or a 403
status_of "Service grafana without the key" 403 "$GF/grafana/api/health"
grep -qxF '{"detail":"Forbidden"}' "$TMP/body" && pass "... answered {\"detail\":\"Forbidden\"}" || fail "... answered '$(head -c 200 "$TMP/body")'"
status_of "Service grafana with a wrong key" 403 "$GF/grafana/api/health" -H "X-QEOS-Grafana-Key: ci-not-the-key-0123456789abcdefghijklmn"
status_of "Service grafana with the key" 200 "$GF/grafana/api/health" -H @"$TMP/key.header"
# The gateway's two headers: the key opens the sidecar, X-QEOS-User-Email reaches Grafana's auth proxy over the unix
# socket only the sidecar shares, and Grafana signs that user in
status_of "the auth proxy signs in X-QEOS-User-Email through the sidecar" 200 "$GF/grafana/api/user" \
  -H @"$TMP/key.header" -H "X-QEOS-User-Email: qeos-k8s-check@example.com"
got="$(yq -p json -o yaml '.email' "$TMP/body" 2>/dev/null | tr -d '\r')"
[ "$got" = qeos-k8s-check@example.com ] && pass "... as qeos-k8s-check@example.com" || fail "... as '$got'"

# A port-forward to the pod past the gateway signs nobody in: Grafana listens on no TCP port (its unix socket only),
# so a forward to 3000 gets no HTTP answer, and the sidecar's 8080 wants the key whatever user header comes with it
kubectl -n "$NAMESPACE" port-forward deploy/grafana "$GF_DIRECT_PORT:3000" >"$TMP/forward-3000.log" 2>&1 &
forwards+=("$!")
for _ in $(seq 15); do
  grep -q "Forwarding from" "$TMP/forward-3000.log" && break
  sleep 1
done
status_of "a port-forward to the pod's 3000 with a forged user header gets no HTTP answer (nothing listens)" 000 \
  "http://localhost:$GF_DIRECT_PORT/grafana/api/user" -H "X-QEOS-User-Email: admin@example.com"
status_of "a port-forward to the pod's 8080 with a forged user header, without the key" 403 "$GF_POD/grafana/api/user" \
  -H "X-QEOS-User-Email: admin@example.com"

# Grafana itself, as the admin through the sidecar: Compose's dashboards provisioned, its data source reaching the
# cluster's Prometheus (its NetworkPolicy admits Grafana's pods), and the five services up as the overview shows them
status_of "the admin signs in through the sidecar (with the key)" 200 "$GF/grafana/api/search?type=dash-db" \
  -H @"$TMP/key.header" --netrc-file "$TMP/netrc"
got="$(yq -p json -o yaml '[.[] | .folderTitle + "/" + .uid] | sort | join(" ")' "$TMP/body" 2>/dev/null | tr -d '\r')"
want="$(for d in "$ROOT"/monitoring/grafana/dashboards/*.json; do printf 'QEOS/%s\n' "$(yq -p json -o yaml '.uid' "$d" | tr -d '\r')"; done | sort | xargs)"
[ -n "$want" ] && [ "$got" = "$want" ] && pass "Grafana provisioned Compose's dashboards: $got" || fail "Grafana's dashboards are '$got', want '$want'"
status_of "Grafana's data source reaches Prometheus" 200 "$GF/grafana/api/datasources/uid/prometheus/health" \
  -H @"$TMP/key.header" --netrc-file "$TMP/netrc"
got="$(yq -p json -o yaml '.status' "$TMP/body" 2>/dev/null | tr -d '\r')"
[ "$got" = OK ] && pass "... status OK" || fail "... status '$got': $(head -c 200 "$TMP/body")"
got="$(fetch "$by_job" "$GF/grafana/api/datasources/proxy/uid/prometheus/api/v1/query" -H @"$TMP/key.header" --netrc-file "$TMP/netrc" -G \
  --data-urlencode "query=count by (job) (up{namespace=\"$NAMESPACE\", job=~\"auth|organization|project|ingestion|test-management\"} == 1)")"
[ "$got" = "auth=2 ingestion=2 organization=2 project=2 test-management=2" ] && pass "the five services up, through Grafana's data source: $got" \
  || fail "the services up through Grafana's data source: '$got'"

if [ "$failures" -eq 0 ]; then
  echo "all monitoring checks passed"
  exit 0
fi
echo "$failures monitoring check(s) failed"
exit 1
