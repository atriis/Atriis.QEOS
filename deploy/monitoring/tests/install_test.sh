#!/usr/bin/env bash
# install.sh's argument checks, and what it would install: `install.sh --template` renders the pinned
# kube-prometheus-stack with each environment's values and the namespaces install.sh passes in (ADR-038,
# deploy/monitoring/README.md). Needs helm 3, yq (mikefarah, v4) and network access to the chart repository; no cluster.
#   bash deploy/monitoring/tests/install_test.sh
set -uo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL="$DIR/install.sh"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
# check NAME COMMAND...: pass when COMMAND succeeds
check() {
  local name="$1"
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}

# ---- argument checks: exit 2 with a message, before anything touches a cluster ----
# usage_error NAME PATTERN ARGS...: install.sh ARGS exits 2 and its stderr matches PATTERN
usage_error() {
  local name="$1" pattern="$2" status=0
  shift 2
  bash "$INSTALL" "$@" >"$OUT/usage.out" 2>"$OUT/usage.err" || status=$?
  if [ "$status" = 2 ] && grep -qE -- "$pattern" "$OUT/usage.err"; then
    pass "$name"
  else
    fail "$name: exit $status, stderr: $(head -n 3 "$OUT/usage.err")"
  fi
}
usage_error "no --env" "--env" --qeos-namespace qeos
usage_error "an unknown --env" "unknown environment 'dev'" --env dev
usage_error "--env without a value" "--env needs a value" --env
usage_error "an unknown option" "unknown option --force" --env ci --force
usage_error "a QEOS namespace that is not a DNS label" "not a Kubernetes namespace name: 'QEOS_ns'" \
  --env ci --qeos-namespace QEOS_ns
usage_error "a monitoring namespace that is not a DNS label" "not a Kubernetes namespace name: '-mon'" \
  --env ci --namespace -mon
usage_error "the same namespace twice" "must differ" --env ci --namespace qeos
usage_error "production before its values file exists" "values-production.yaml" --env production

# ---- render ----
# render NAME ARGS...: install.sh --template ARGS into $OUT/NAME.yaml
render() {
  local name="$1"
  shift
  if bash "$INSTALL" --template "$@" >"$OUT/$name.yaml" 2>"$OUT/$name.err"; then
    pass "install.sh --template $*"
  else
    fail "install.sh --template $*: $(tail -n 5 "$OUT/$name.err")"
    : >"$OUT/$name.yaml"
  fi
}
render ci --env ci
render staging --env staging
render custom --env ci --qeos-namespace qa --namespace mon

# q FILE EXPR: yq over every document of FILE
q() { yq ea "$2" "$1"; }

# checks_for NAME QEOS_NAMESPACE MONITORING_NAMESPACE
checks_for() {
  local name="$1" qns="$2" mns="$3" f="$OUT/$1.yaml"
  local prom='select(.kind == "Prometheus")'
  check "$name: exactly one Prometheus" [ "$(q "$f" "[$prom] | length")" = 1 ]
  check "$name: the Prometheus is in $mns" [ "$(q "$f" "$prom | .metadata.namespace")" = "$mns" ]
  check "$name: enforcedNamespaceLabel namespace" [ "$(q "$f" "$prom | .spec.enforcedNamespaceLabel")" = namespace ]
  check "$name: alerts go to Service alertmanager, port http, in $qns" [ "$(q "$f" "[$prom | .spec.alerting.alertmanagers[]
    | select(.namespace == \"$qns\" and .name == \"alertmanager\" and .port == \"http\")] | length")" = 1 ]
  check "$name: no other alerting endpoint" [ "$(q "$f" "$prom | .spec.alerting.alertmanagers | length")" = 1 ]
  check "$name: no Alertmanager" [ "$(q "$f" '[select(.kind == "Alertmanager")] | length')" = 0 ]
  check "$name: no Grafana Deployment" \
    [ "$(q "$f" '[select(.kind == "Deployment" and (.metadata.name | test("grafana")))] | length')" = 0 ]
  check "$name: retention 15d" [ "$(q "$f" "$prom | .spec.retention")" = 15d ]
  # Rules and ServiceMonitors from the two namespaces only, any labels
  local sel
  for sel in ruleNamespaceSelector serviceMonitorNamespaceSelector podMonitorNamespaceSelector; do
    check "$name: $sel is {$qns, $mns}" [ "$(q "$f" "$prom | .spec.$sel.matchExpressions[]
      | select(.key == \"kubernetes.io/metadata.name\" and .operator == \"In\") | .values | sort | join(\",\")")" \
      = "$(printf '%s\n' "$qns" "$mns" | sort | paste -sd, -)" ]
  done
  for sel in ruleSelector serviceMonitorSelector podMonitorSelector; do
    check "$name: $sel matches any labels" [ "$(q "$f" "$prom | .spec.$sel")" = "{}" ]
  done
  # The monitoring namespace's own rules and ServiceMonitors keep their series' namespace label: all of them (no name;
  # the chart also lists its rules one by one)
  local res
  for res in prometheusrules servicemonitors; do
    check "$name: $mns's $res are excluded from the namespace enforcement" [ "$(q "$f" "[$prom
      | .spec.excludedFromEnforcement[] | select(.namespace == \"$mns\" and .resource == \"$res\"
      and .group == \"monitoring.coreos.com\" and has(\"name\") == false)] | length")" = 1 ]
  done
  # Alert noise: QEOS has its own Watchdog; overcommit is always true on a small pool
  local alert
  for alert in Watchdog InfoInhibitor KubeCPUOvercommit KubeMemoryOvercommit; do
    check "$name: no rule alerts $alert" \
      [ "$(q "$f" "[select(.kind == \"PrometheusRule\") | .spec.groups[].rules[] | select(.alert == \"$alert\")] | length")" = 0 ]
  done
  check "$name: other default rules stay (KubePodCrashLooping)" \
    [ "$(q "$f" '[select(.kind == "PrometheusRule") | .spec.groups[].rules[] | select(.alert == "KubePodCrashLooping")] | length')" = 1 ]
  # The control plane is not scrapable on AKS: neither its rules nor its ServiceMonitors
  local group
  for group in etcd kubernetes-system-scheduler kubernetes-system-controller-manager kubernetes-system-kube-proxy; do
    check "$name: no rule group $group" \
      [ "$(q "$f" "[select(.kind == \"PrometheusRule\") | .spec.groups[] | select(.name == \"$group\")] | length")" = 0 ]
  done
  local component
  for component in kube-controller-manager kube-scheduler kube-etcd kube-proxy; do
    check "$name: no $component ServiceMonitor or Service" [ "$(q "$f" "[select((.kind == \"ServiceMonitor\" or
      .kind == \"Service\") and (.metadata.name | test(\"$component\")))] | length")" = 0 ]
  done

  # Prometheus is not open to the cluster: 9090 from Grafana in the QEOS namespace and from the monitoring namespace
  local np="select(.kind == \"NetworkPolicy\" and .spec.podSelector.matchLabels.\"app.kubernetes.io/name\" == \"prometheus\")"
  check "$name: one NetworkPolicy selects the Prometheus pods" [ "$(q "$f" "[$np] | length")" = 1 ]
  check "$name: the NetworkPolicy is in $mns" [ "$(q "$f" "$np | .metadata.namespace")" = "$mns" ]
  check "$name: the NetworkPolicy is ingress only (scraping is outbound)" \
    [ "$(q "$f" "$np | .spec.policyTypes | join(\",\")")" = Ingress ]
  # Each source as <namespace>/<pod name label>, * for any pod
  check "$name: 9090 admits exactly Grafana in $qns and the namespace $mns" [ "$(q "$f" "$np | .spec.ingress[]
    | select(.ports[].port == 9090) | .from[]
    | ((.namespaceSelector.matchLabels.\"kubernetes.io/metadata.name\" // \"-\") + \"/\"
      + (.podSelector.matchLabels.\"app.kubernetes.io/name\" // \"*\"))" | sort | paste -sd, -)" \
    = "$(printf '%s\n' "$mns/*" "$qns/grafana" | sort | paste -sd, -)" ]
  check "$name: no rule admits everyone" \
    [ "$(q "$f" "[$np | .spec.ingress[] | select((.from // []) | length == 0)] | length")" = 0 ]

  # Every container with the restricted settings: node-exporter keeps its host namespaces (the privileged namespace
  # admits it), the rest is restricted
  local pods='select(.kind == "Deployment" or .kind == "DaemonSet" or .kind == "Job" or .kind == "StatefulSet")
    | .spec.template.spec as $pod | ($pod.containers + ($pod.initContainers // []))[] | {"pod": $pod, "c": .}'
  local bad
  # The check below must see containers at all: a yq error or an empty render would pass it
  check "$name: the workloads have containers" [ "$(q "$f" "[$pods] | length")" -ge 3 ]
  bad="$(q "$f" "[$pods | select((.c.securityContext.allowPrivilegeEscalation != false)
    or ((.c.securityContext.capabilities.drop // []) | contains([\"ALL\"]) | not)
    or (.c.securityContext.readOnlyRootFilesystem != true)
    or ((.c.securityContext.runAsNonRoot // .pod.securityContext.runAsNonRoot) != true)
    or ((.c.securityContext.seccompProfile.type // .pod.securityContext.seccompProfile.type) != \"RuntimeDefault\"))
    | .c.name] | join(\",\")")"
  check "$name: every workload container is restricted (bad: ${bad:-none})" [ -z "$bad" ]
  check "$name: the Prometheus pod is restricted at pod level" [ "$(q "$f" "$prom | .spec.securityContext
    | (.runAsNonRoot == true and .seccompProfile.type == \"RuntimeDefault\")")" = true ]
}
checks_for ci qeos qeos-monitoring
checks_for staging qeos qeos-monitoring
checks_for custom qa mon

# ---- per environment ----
prom='select(.kind == "Prometheus")'
check "staging: Prometheus keeps 20Gi on managed-csi" [ "$(q "$OUT/staging.yaml" "$prom | .spec.storage.volumeClaimTemplate.spec
  | .storageClassName + \"/\" + .resources.requests.storage")" = managed-csi/20Gi ]
check "ci: Prometheus has no persistent storage" [ "$(q "$OUT/ci.yaml" "$prom | .spec.storage")" = null ]
check "custom: nothing names the default namespaces" \
  [ "$(grep -cE '(namespace: |- )(qeos|qeos-monitoring)$' "$OUT/custom.yaml")" = 0 ]

# ---- the pin ----
# A downloaded chart whose digest differs from Chart.yaml's annotation is refused
cp -r "$DIR" "$OUT/tampered"
rm -rf "$OUT/tampered/charts"
sed -i 's/\(kube-prometheus-stack-sha256: \).*/\10000000000000000000000000000000000000000000000000000000000000000/' \
  "$OUT/tampered/Chart.yaml"
status=0
bash "$OUT/tampered/install.sh" --template --env ci >/dev/null 2>"$OUT/tampered.err" || status=$?
if [ "$status" = 1 ] && grep -q "sha256" "$OUT/tampered.err"; then
  pass "a chart archive with another digest is refused"
else
  fail "a chart archive with another digest is refused: exit $status, $(tail -n 3 "$OUT/tampered.err")"
fi
check "Chart.lock pins the version Chart.yaml names" [ "$(yq '.dependencies[0].version' "$DIR/Chart.lock")" \
  = "$(yq '.dependencies[0].version' "$DIR/Chart.yaml")" ]

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
