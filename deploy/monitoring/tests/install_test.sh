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
# Kubernetes' own namespaces are never relabelled
for ns in default kube-system kube-public kube-node-lease; do
  usage_error "--namespace $ns is refused" "'$ns' is Kubernetes' own namespace" --env ci --namespace "$ns"
  usage_error "--qeos-namespace $ns is refused" "'$ns' is Kubernetes' own namespace" --env ci --qeos-namespace "$ns"
done
usage_error "a QEOS release that is not a release name" "not a Helm release name: 'Qeos'" --env ci --qeos-release Qeos
usage_error "--qeos-release without a value" "--qeos-release needs a value" --env ci --qeos-release
usage_error "production before its values file exists" "production arrives in Stage 3.*values-production.yaml" \
  --env production --context kind-qeos-kind
# Never the current context
usage_error "no --context" "--context is required" --env ci
usage_error "--context without a value" "--context needs a value" --env ci --context
usage_error "a context that is not a context name" "not a kubectl context name: 'a b'" --env ci --context "a b"

# ---- against a cluster: a kubectl stub on PATH (and a helm stub, so nothing is downloaded or installed) ----
# The stub knows one context, stub-ctx; it answers the API server, the monitoring namespace's
# <name>/<qeos.atriis.com/monitoring label> ($STUB_MARKER, empty: no such namespace) and the QEOS namespace's enforce
# label ($STUB_ENFORCE), and logs every other call to $OUT/kubectl.log
mkdir -p "$OUT/stub"
cat >"$OUT/stub/kubectl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "config get-contexts stub-ctx") exit 0 ;;
  "config get-contexts "*) exit 1 ;;
  "--context stub-ctx config view --minify "*) echo https://stub.example:443 ;;
  "--context stub-ctx get namespace "*"qeos\.atriis\.com/monitoring"*) echo "${STUB_MARKER:-}" ;;
  "--context stub-ctx get namespace "*) echo "${STUB_ENFORCE:-}" ;;
  *) echo "$*" >>"$STUB_LOG" ;;
esac
EOF
# shellcheck disable=SC2016 # the stub's own variables
printf '#!/usr/bin/env bash\necho "helm $*" >>"$STUB_LOG"\n' >"$OUT/stub/helm"
chmod +x "$OUT/stub/kubectl" "$OUT/stub/helm"
# A copy without a downloaded chart: past the checks, the script stops at the archive the helm stub never fetched
cp -r "$DIR" "$OUT/clean"
rm -rf "$OUT/clean/charts"
# stubbed STATUS PATTERN ENFORCE ARGS...: install.sh ARGS against the stub, the QEOS namespace enforcing ENFORCE (and
# the monitoring namespace as $marker says)
marker=""
stubbed() {
  local want="$1" pattern="$2" enforce="$3" status=0
  shift 3
  : >"$OUT/kubectl.log"
  STUB_LOG="$OUT/kubectl.log" STUB_ENFORCE="$enforce" STUB_MARKER="$marker" PATH="$OUT/stub:$PATH" bash "$OUT/clean/install.sh" "$@" \
    >"$OUT/stub.out" 2>"$OUT/stub.err" || status=$?
  [ "$status" = "$want" ] && grep -qE -- "$pattern" "$OUT/stub.err"
}
check "an unknown context exits 1 before any change" \
  stubbed 1 "no kubectl context 'other-ctx'" "" --env ci --context other-ctx
check "... and nothing was called" [ ! -s "$OUT/kubectl.log" ]
check "the context, its API server and both namespaces are printed first" \
  stubbed 1 "" restricted --env staging --context stub-ctx
check "... context" grep -q "^context: stub-ctx$" "$OUT/stub.err"
check "... API server" grep -q "^API server: https://stub.example:443$" "$OUT/stub.err"
check "... namespaces" grep -q "monitoring namespace: qeos-monitoring .*QEOS namespace: qeos " "$OUT/stub.err"
check "a restricted QEOS namespace is not lowered to baseline" \
  stubbed 1 "qeos enforces Pod Security restricted; pass --enforce-restricted to keep it, or --allow-downgrade" \
  restricted --env staging --context stub-ctx
check "... and nothing was changed" [ ! -s "$OUT/kubectl.log" ]
check "--allow-downgrade lowers it" stubbed 1 "left no .*kube-prometheus-stack" restricted \
  --env staging --context stub-ctx --allow-downgrade
check "--enforce-restricted keeps it" stubbed 1 "left no .*kube-prometheus-stack" restricted \
  --env staging --context stub-ctx --enforce-restricted
check "a baseline namespace needs no flag" stubbed 1 "left no .*kube-prometheus-stack" baseline \
  --env staging --context stub-ctx
# The monitoring namespace becomes privileged: only one install.sh created (its label), unless --allow-downgrade
marker=qeos-monitoring/
check "an existing namespace install.sh did not create is not made privileged" \
  stubbed 1 "qeos-monitoring exists and was not created by install.sh .*--allow-downgrade" "" --env staging --context stub-ctx
check "... and nothing was changed" [ ! -s "$OUT/kubectl.log" ]
check "... unless --allow-downgrade" stubbed 1 "left no .*kube-prometheus-stack" "" \
  --env staging --context stub-ctx --allow-downgrade
marker=qeos-monitoring/true
check "the namespace install.sh created is reused" stubbed 1 "left no .*kube-prometheus-stack" "" \
  --env staging --context stub-ctx
marker=""

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
render custom --env ci --qeos-namespace qa --namespace mon --qeos-release qa-rel
# The QEOS chart names the monitoring namespace itself: another one needs its value set
check "another monitoring namespace: a note names the QEOS chart's value" \
  grep -q "set networkPolicy.prometheus.namespace=mon in the QEOS chart's values" "$OUT/custom.err"
check "the default monitoring namespace: no note" [ "$(grep -c "networkPolicy.prometheus.namespace" "$OUT/ci.err")" = 0 ]

# q FILE EXPR: yq over every document of FILE
q() { yq ea "$2" "$1"; }

# checks_for NAME QEOS_NAMESPACE MONITORING_NAMESPACE QEOS_RELEASE
checks_for() {
  local name="$1" qns="$2" mns="$3" release="$4" f="$OUT/$1.yaml"
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
  # Each source as <namespace>/<pod name label>@<pod instance label>, * for any; Grafana only of release $release
  check "$name: 9090 admits exactly $release's Grafana in $qns and the namespace $mns" [ "$(q "$f" "$np | .spec.ingress[]
    | select(.ports[].port == 9090) | .from[]
    | ((.namespaceSelector.matchLabels.\"kubernetes.io/metadata.name\" // \"-\") + \"/\"
      + (.podSelector.matchLabels.\"app.kubernetes.io/name\" // \"*\") + \"@\"
      + (.podSelector.matchLabels.\"app.kubernetes.io/instance\" // \"*\"))" | sort | paste -sd, -)" \
    = "$(printf '%s\n' "$mns/*@*" "$qns/grafana@$release" | sort | paste -sd, -)" ]
  check "$name: no rule admits everyone" \
    [ "$(q "$f" "[$np | .spec.ingress[] | select((.from // []) | length == 0)] | length")" = 0 ]

  # Every container with the restricted settings: node-exporter keeps its host namespaces (the privileged namespace
  # admits it), the rest is restricted
  # shellcheck disable=SC2016 # yq's variables
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
checks_for ci qeos qeos-monitoring qeos
checks_for staging qeos qeos-monitoring qeos
checks_for custom qa mon qa-rel

# ---- per environment ----
prom='select(.kind == "Prometheus")'
check "staging: Prometheus keeps 20Gi on managed-csi" [ "$(q "$OUT/staging.yaml" "$prom | .spec.storage.volumeClaimTemplate.spec
  | .storageClassName + \"/\" + .resources.requests.storage")" = managed-csi/20Gi ]
check "ci: Prometheus has no persistent storage" [ "$(q "$OUT/ci.yaml" "$prom | .spec.storage")" = null ]
check "custom: nothing names the default namespaces" \
  [ "$(grep -cE '(namespace: |- )(qeos|qeos-monitoring)$' "$OUT/custom.yaml")" = 0 ]

# ---- the pin ----
# edited_copy NAME SED_SCRIPT: deploy/monitoring copied to $OUT/NAME (no downloaded charts), Chart.yaml edited (no
# sed -i: BSD and GNU sed disagree on it)
edited_copy() {
  cp -r "$DIR" "$OUT/$1"
  rm -rf "$OUT/$1/charts"
  sed "$2" "$DIR/Chart.yaml" >"$OUT/$1/Chart.yaml"
}
# refused NAME COPY PATTERN: install.sh --template in the copy exits 1 and its stderr matches PATTERN
refused() {
  local status=0
  bash "$OUT/$2/install.sh" --template --env ci >/dev/null 2>"$OUT/$2.err" || status=$?
  if [ "$status" = 1 ] && grep -qE -- "$3" "$OUT/$2.err"; then
    pass "$1"
  else
    fail "$1: exit $status, $(tail -n 3 "$OUT/$2.err")"
  fi
}
# A downloaded chart whose digest differs from Chart.yaml's annotation is refused, pointing to the bump procedure
edited_copy tampered 's/\(kube-prometheus-stack-sha256: \).*/\10000000000000000000000000000000000000000000000000000000000000000/'
refused "a chart archive with another digest is refused" tampered "sha256 .*Bumping the version"
# Chart.yaml is read with sed: a dependency it cannot parse stops the script, never an empty version
edited_copy no-version '/^    version:/d'
refused "a Chart.yaml without the dependency's version is refused" no-version "expected one dependency version"
edited_copy no-sha '/kube-prometheus-stack-sha256:/d'
refused "a Chart.yaml without the sha256 annotation is refused" no-sha "expected one dependency version"
edited_copy two-versions '/^    version:/p'
refused "a Chart.yaml with two indented versions is refused" two-versions "expected one dependency version"
check "Chart.lock pins the version Chart.yaml names" [ "$(yq '.dependencies[0].version' "$DIR/Chart.lock")" \
  = "$(yq '.dependencies[0].version' "$DIR/Chart.yaml")" ]

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
