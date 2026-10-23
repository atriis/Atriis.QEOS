#!/usr/bin/env bash
# Renders the QEOS chart with each values file and checks what Kubernetes would get (ADR-038, spec 5.3). Needs helm 3
# and yq (mikefarah, v4) on PATH; no cluster.
#   bash deploy/helm/qeos/tests/render_test.sh
set -uo pipefail

CHART="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE=qeos
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# The Azure values arrive from Bicep's outputs with --set in the deploy workflow (deploy-aks.yml); placeholders here
STAGING_HOST=qeos-staging-abc123.hash0123.westeurope.cloudapp.azure.com
STAGING_SET=(
  --set image.registry=example.azurecr.io --set image.tag=0123abc
  --set publicUrl=https://$STAGING_HOST
  --set edge.publicIp.name=pip-aks-qeos-staging-edge --set edge.publicIp.resourceGroup=rg-qeos-staging
  --set edge.acme.email=ops@example.com --set smtp.fromEmail=DoNotReply@example.azurecomm.net
  --set keyvault.name=kv-placeholder --set keyvault.tenantId=00000000-0000-0000-0000-000000000000
  --set keyvault.clientIds.services=11111111-1111-1111-1111-111111111111
  --set keyvault.clientIds.ingestion=22222222-2222-2222-2222-222222222222
  --set keyvault.clientIds.ingestion-retention=33333333-3333-3333-3333-333333333333
  --set keyvault.clientIds.migrate=44444444-4444-4444-4444-444444444444
  --set postgres.host=pg-placeholder.postgres.database.azure.com
  --set artifacts.azure.accountUrl=https://placeholder.blob.core.windows.net
  # auth-service's Entra app: must reach the pod as given, never replaced by a managed identity's id
  --set services.auth-service.env.AZURE_CLIENT_ID=entra-app-from-values
  # values-staging.yaml keeps monitoring off until Task 7 (Key Vault keys, deploy preflight): the staging renders check
  # it on, as it will run; staging-off and the lint turn it off again
  --set monitoring.enabled=true
)
# Compose settings the chart replaces on purpose: DATABASE_URL by POSTGRES_* (the password URL-escaped by the settings),
# GATEWAY_HTTPS_PORT by GATEWAY_PUBLIC_PORT (TLS ends at the edge). Anything else Compose sets must be set here too
COMPOSE_ONLY="DATABASE_URL GATEWAY_HTTPS_PORT"
COMPOSE="$CHART/../../../docker-compose.yml"
# Monitoring on (values-ci.yaml and values-staging.yaml) needs kube-prometheus-stack's CRDs: on a cluster Helm finds them
# itself; a render without a cluster is told they exist
CRDS=(--api-versions monitoring.coreos.com/v1/ServiceMonitor --api-versions monitoring.coreos.com/v1/PrometheusRule)

# ---- lint and render ----
# helm lint takes no --api-versions, so it sees no CRD and lints with monitoring off; the renders below cover monitoring
if helm lint "$CHART" -f "$CHART/values-ci.yaml" --set monitoring.enabled=false >"$OUT/lint-ci.txt" 2>&1; then
  pass "helm lint (values-ci.yaml)"
else
  fail "helm lint (values-ci.yaml): $(tail -n 5 "$OUT/lint-ci.txt")"
fi
if helm lint "$CHART" -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" --set monitoring.enabled=false >"$OUT/lint-staging.txt" 2>&1; then
  pass "helm lint (values-staging.yaml)"
else
  fail "helm lint (values-staging.yaml): $(tail -n 5 "$OUT/lint-staging.txt")"
fi
render() {
  local name="$1"
  shift
  if helm template qeos "$CHART" --namespace "$NAMESPACE" "$@" >"$OUT/$name.yaml" 2>"$OUT/$name.err"; then
    pass "helm template ($name)"
  else
    fail "helm template ($name): $(tail -n 5 "$OUT/$name.err")"
    : >"$OUT/$name.yaml"
  fi
}
# Both environments run with monitoring on (ADR-038 Stage 2)
render ci -f "$CHART/values-ci.yaml" "${CRDS[@]}"
render staging -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}"
# Once the ACS SMTP application exists, its secrets are in the vault and keyvault.absent drops them
render staging-email -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}" --set 'keyvault.absent={tm-secrets-key}'
render ci-nopolicy -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set networkPolicy.enabled=false
# Monitoring off: Stage 1's release, which needs no CRD
render ci-off -f "$CHART/values-ci.yaml" --set monitoring.enabled=false
render staging-off -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" --set monitoring.enabled=false
render ci-prometheus -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set networkPolicy.prometheus.namespace=mon \
  --set-json 'networkPolicy.prometheus.podLabels={"app.kubernetes.io/name":null,"app":"prom"}'
# values.yaml alone holds no environment: a render must stop on the settings each environment has to give
if helm template qeos "$CHART" --namespace "$NAMESPACE" >/dev/null 2>"$OUT/defaults.err"; then
  fail "values.yaml alone renders: the required settings are not enforced"
else
  grep -q 'is required' "$OUT/defaults.err" && pass "values.yaml alone refuses to render: $(grep -o '[a-zA-Z.-]* is required' "$OUT/defaults.err" | head -n 1)" \
    || fail "values.yaml alone fails for another reason: $(tail -n 3 "$OUT/defaults.err")"
fi

# q FILE EXPR -- yq over every document of a rendered file
q() { yq ea "$2" "$1"; }

# selects FILE NAME "k=v ..." [KIND SELECTOR] -- whether the NetworkPolicy's podSelector (or KIND's SELECTOR, such as a
# ServiceMonitor's .spec.selector) matches an object with these labels: matchLabels and matchExpressions (In, NotIn,
# Exists, DoesNotExist) evaluated as Kubernetes does, not compared as text
selects() {
  local sel kind key op vals l found v
  sel="$(q "$1" "select(.kind == \"${4:-NetworkPolicy}\" and .metadata.name == \"$2\") | ${5:-.spec.podSelector}
    | ((.matchLabels // {}) | to_entries | map(\"L \" + .key + \" \" + .value))
      + ((.matchExpressions // []) | map(\"E \" + .key + \" \" + .operator + \" \" + ((.values // []) | join(\",\"))))
    | .[]")"
  while read -r kind key op vals; do
    [ -n "$kind" ] || continue
    found=false
    v=""
    for l in $3; do
      if [ "${l%%=*}" = "$key" ]; then found=true; v="${l#*=}"; fi
    done
    if [ "$kind" = L ]; then
      { $found && [ "$v" = "$op" ]; } || return 1
      continue
    fi
    case "$op" in
      Exists) $found || return 1 ;;
      DoesNotExist) ! $found || return 1 ;;
      In) { $found && [[ ",$vals," == *",$v,"* ]]; } || return 1 ;;
      NotIn) { $found && [[ ",$vals," == *",$v,"* ]]; } && return 1 ;;
      *) return 1 ;;
    esac
  done <<< "$sel"
  return 0
}

APIS="auth-service organization-service project-service ingestion-service test-management-service"
WEB="dashboard gateway"
LOOPS="ingestion-retention analytics-rollup impact-rollup weekly-summary"

for env in ci staging; do
  f="$OUT/$env.yaml"
  [ -s "$f" ] || continue

  # ---- security context on every container of every pod spec, init containers included (PSA restricted) ----
  bad="$(q "$f" '[select(.spec.template.spec != null) | .spec.template.spec as $s
    | (($s.containers // []) + ($s.initContainers // []))[]
    | select(.securityContext.runAsNonRoot != true or .securityContext.readOnlyRootFilesystem != true
        or .securityContext.allowPrivilegeEscalation != false
        or ((.securityContext.capabilities.drop // []) | contains(["ALL"]) | not)
        or (.securityContext.seccompProfile.type // $s.securityContext.seccompProfile.type // "") != "RuntimeDefault")
    | .name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: every container is non-root, read-only, no escalation, no capabilities, RuntimeDefault seccomp" \
    || fail "$env: containers without the required securityContext: $bad"
  count="$(q "$f" '[select(.spec.template.spec != null)] | length')"
  [ "$count" -gt 0 ] || fail "$env: no pod spec rendered"

  # ---- NetworkPolicies (spec 5.3): every pod of the release denied by default, each Service open to its callers ----
  d="$(q "$f" 'select(.kind == "NetworkPolicy" and .metadata.name == "default-deny-ingress") | .spec
    | (.policyTypes | join(",")) + " " + ((.ingress // []) | length | tostring)')"
  pod="app.kubernetes.io/name=auth-service app.kubernetes.io/instance=qeos app.kubernetes.io/part-of=qeos"
  other="app.kubernetes.io/name=auth-service app.kubernetes.io/instance=other"
  [ "$d" = "Ingress 0" ] && selects "$f" default-deny-ingress "$pod" && ! selects "$f" default-deny-ingress "$other" \
    && pass "$env: default-deny-ingress closes every pod of the release, no other release's" \
    || fail "$env: default-deny-ingress is '$d', or selects the wrong pods"
  # The edge's proxy pods run in the Gateway's namespace, the release's, and Istio may copy the Gateway's labels onto
  # them (its instance label included): no QEOS policy may select them, or the default deny would close the site
  edge="gateway.networking.k8s.io/gateway-name=qeos-edge app.kubernetes.io/instance=qeos app.kubernetes.io/name=qeos-edge"
  edge="$edge $(q "$f" 'select(.kind == "Gateway") | .metadata.labels | to_entries | map(.key + "=" + .value) | join(" ")')"
  bad=""
  for p in $(q "$f" '[select(.kind == "NetworkPolicy") | .metadata.name] | join(" ")'); do
    selects "$f" "$p" "$edge" && bad="$bad $p"
  done
  [ -z "$bad" ] && pass "$env: no NetworkPolicy selects the edge's proxy pods, even with the Gateway's labels" \
    || fail "$env: policies selecting the edge's pods:$bad"
  bad="$(q "$f" '[select(.kind == "NetworkPolicy") | select(.spec.podSelector.matchLabels["app.kubernetes.io/instance"] != "qeos")
    | .metadata.name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: every NetworkPolicy selects this release's pods only" || fail "$env: policies beyond the release: $bad"
  # A source with no pod labels, an address block or a namespace selector naming no namespace would open a workload to
  # more than its callers
  bad=""
  for p in $(q "$f" '[select(.kind == "NetworkPolicy") | .metadata.name] | join(" ")'); do
    n="$(q "$f" "select(.kind == \"NetworkPolicy\" and .metadata.name == \"$p\") | ([.spec.ingress[] | select(.from == null)] | length)
      + ([.spec.ingress[].from[] | select(.ipBlock != null or (.podSelector.matchLabels // {} | length) == 0
          or (.namespaceSelector == null and .podSelector.matchLabels[\"app.kubernetes.io/instance\"] != \"qeos\")
          or (.namespaceSelector != null and (.namespaceSelector.matchLabels[\"kubernetes.io/metadata.name\"] // \"\") == \"\"))] | length)")"
    [ "$n" = 0 ] || bad="$bad $p"
  done
  [ -z "$bad" ] && pass "$env: every allowed source is a labelled pod of this release, or of one named namespace" \
    || fail "$env: policies with an open or unlabelled source: $bad"
  # callers POLICY PORT -- the in-namespace pods a policy admits on PORT, sorted
  callers() { q "$f" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"$1\") | .spec.ingress[]
    | select(.ports | map(.protocol + \"/\" + (.port | tostring)) | contains([\"TCP/$2\"])) | .from[]
    | select(.namespaceSelector == null) | .podSelector.matchLabels[\"app.kubernetes.io/name\"]] | sort | join(\" \")"; }
  # ports POLICY -- every protocol/port it opens
  ports() { q "$f" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"$1\") | .spec.ingress[].ports[] | .protocol + \"/\" + (.port | tostring)] | unique | join(\" \")"; }
  # outside POLICY -- its sources in other namespaces: "<namespace> <pod labels>"
  outside() { q "$f" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"$1\") | .spec.ingress[].from[] | select(.namespaceSelector != null)
    | .namespaceSelector.matchLabels[\"kubernetes.io/metadata.name\"] + \" \" + (.podSelector.matchLabels | to_entries | map(.key + \"=\" + .value) | sort | join(\",\"))] | unique | join(\";\")"; }
  # From services.<x>.urls, and the gateway, which proxies to every API and the dashboard
  for pair in "auth-service:gateway organization-service" \
      "organization-service:auth-service gateway project-service" \
      "project-service:analytics-rollup gateway impact-rollup ingestion-retention ingestion-service test-management-service weekly-summary" \
      "ingestion-service:gateway" \
      "test-management-service:gateway ingestion-retention"; do
    name="${pair%%:*}"
    want="${pair#*:}"
    got="$(callers "$name-ingress" 8000)"
    [ "$got" = "$want" ] && pass "$env: $name-ingress admits exactly its callers ($want)" \
      || fail "$env: $name-ingress admits '$got', want '$want'"
    [ "$(ports "$name-ingress")" = TCP/8000 ] && pass "$env: $name-ingress opens TCP 8000 only" \
      || fail "$env: $name-ingress opens '$(ports "$name-ingress")'"
    # From outside the namespace: Prometheus only (monitoring on in both environments; off below)
    [ "$(outside "$name-ingress")" = "qeos-monitoring app.kubernetes.io/name=prometheus" ] \
      && pass "$env: $name-ingress admits only Prometheus from outside the namespace" \
      || fail "$env: $name-ingress admits from outside: '$(outside "$name-ingress")'"
  done
  got="$(callers dashboard-ingress 8080)|$(ports dashboard-ingress)|$(outside dashboard-ingress)"
  [ "$got" = "gateway|TCP/8080|" ] && pass "$env: dashboard-ingress admits the gateway on TCP 8080 only" \
    || fail "$env: dashboard-ingress is '$got'"
  # Every Service the chart renders has a policy beyond the default deny that selects its pods
  for svc in $(q "$f" '[select(.kind == "Service") | .metadata.name] | join(" ")'); do
    labels="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$svc\") | .spec.template.metadata.labels | to_entries | map(.key + \"=\" + .value) | join(\" \")")"
    covered=""
    for p in $(q "$f" '[select(.kind == "NetworkPolicy" and .metadata.name != "default-deny-ingress") | .metadata.name] | join(" ")'); do
      selects "$f" "$p" "$labels" && covered="$p"
    done
    [ -n "$covered" ] && pass "$env: Service $svc's pods are opened by $covered" || fail "$env: Service $svc has no NetworkPolicy beyond the default deny"
  done

  # ---- replicas (Global Constraints) and a PDB for every 2-replica Deployment ----
  for name in $APIS $WEB; do
    r="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.replicas")"
    [ "$r" = 2 ] && pass "$env: $name has 2 replicas" || fail "$env: $name has replicas '${r:-missing}', want 2"
    pdb="$(q "$f" "select(.kind == \"PodDisruptionBudget\" and .metadata.name == \"$name\") | .spec.minAvailable")"
    [ "$pdb" = 1 ] && pass "$env: $name has a PDB (minAvailable 1)" || fail "$env: $name has no PDB with minAvailable 1"
  done
  for name in $LOOPS; do
    r="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.replicas")"
    [ "$r" = 1 ] && pass "$env: $name has 1 replica" || fail "$env: $name has replicas '${r:-missing}', want 1"
  done
  extra="$(q "$f" '[select(.kind == "PodDisruptionBudget") | .metadata.name] | join(" ")')"
  for name in $extra; do
    case " $APIS $WEB " in *" $name "*) ;; *) fail "$env: unexpected PDB $name" ;; esac
  done

  # ---- the migration hook: Job at weight 0, its ServiceAccount and scripts at -10 ----
  hook() { q "$f" "select(.kind == \"$1\" and .metadata.name == \"$2\") | .metadata.annotations[\"helm.sh/hook\"] + \"|\" + .metadata.annotations[\"helm.sh/hook-weight\"]"; }
  [ "$(hook Job qeos-migrate)" = "pre-install,pre-upgrade|0" ] && pass "$env: migration Job is a pre-install,pre-upgrade hook at weight 0" \
    || fail "$env: migration Job hook annotations are '$(hook Job qeos-migrate)'"
  [ "$(hook ServiceAccount qeos-migrate)" = "pre-install,pre-upgrade|-10" ] && pass "$env: migration ServiceAccount is a hook at weight -10" \
    || fail "$env: migration ServiceAccount hook annotations are '$(hook ServiceAccount qeos-migrate)'"
  [ "$(hook ConfigMap qeos-migrate-scripts)" = "pre-install,pre-upgrade|-10" ] && pass "$env: migration scripts are a hook at weight -10" \
    || fail "$env: migration scripts hook annotations are '$(hook ConfigMap qeos-migrate-scripts)'"
  inits="$(q "$f" 'select(.kind == "Job" and .metadata.name == "qeos-migrate") | [.spec.template.spec.initContainers[].name] | join(" ")')"
  [ "$inits" = "db-init auth-service organization-service project-service ingestion-service test-management-service" ] \
    && pass "$env: migration Job runs db-init, then each service's migrations in order" \
    || fail "$env: migration Job init containers are '$inits'"
  sa="$(q "$f" 'select(.kind == "Job" and .metadata.name == "qeos-migrate") | .spec.template.spec.serviceAccountName')"
  [ "$sa" = qeos-migrate ] && pass "$env: migration Job runs as qeos-migrate" || fail "$env: migration Job runs as '$sa'"

  # ---- each API waits for its schema before serving ----
  for name in $APIS; do
    w="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | [.spec.template.spec.initContainers[].name] | join(\" \")")"
    [ "$w" = wait-for-schema ] && pass "$env: $name waits for its schema" || fail "$env: $name init containers are '$w'"
  done
  # ---- a loop job waits for the services Compose's depends_on wants healthy (retention: project-service) ----
  for pair in "ingestion-retention:http://project-service.$NAMESPACE.svc.cluster.local:8000/health" analytics-rollup: \
      impact-rollup: weekly-summary:; do
    name="${pair%%:*}"
    want="${pair#*:}"
    w="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec | [(.initContainers // [])[]
      | .name + \" \" + .image + \" \" + (.command | join(\" \"))] | join(\";\")")"
    img="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[0].image")"
    if [ -z "$want" ]; then
      [ -z "$w" ] && pass "$env: $name waits for nothing (Compose: only the migration)" || fail "$env: $name init containers are '$w'"
    else
      [ "$w" = "wait-for $img python /opt/qeos/scripts/wait-for.py $want" ] \
        && pass "$env: $name waits for $want in its own image" || fail "$env: $name init containers are '$w'"
    fi
  done
  s="$(q "$f" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-scripts") | .data["wait-for.py"]')"
  [ "$s" = "$(cat "$CHART/files/wait-for.py")" ] && pass "$env: qeos-scripts carries files/wait-for.py" || fail "$env: qeos-scripts lacks wait-for.py"

  # ---- probes, grace period, preStop, spread on every long-running workload ----
  bad="$(q "$f" '[select(.kind == "Deployment" and .metadata.labels["app.kubernetes.io/part-of"] == "qeos")
    | select(.spec.template.spec.terminationGracePeriodSeconds != 30
        or (.spec.template.spec.topologySpreadConstraints[0].topologyKey // "") != "kubernetes.io/hostname"
        or (.spec.template.spec.containers[0].lifecycle.preStop.exec.command | join(" ")) != "sleep 5")
    | .metadata.name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: grace period 30 s, preStop sleep 5 and hostname spread everywhere" || fail "$env: missing on: $bad"
  for name in $APIS gateway; do
    p="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[0] | .readinessProbe.httpGet.path + \" \" + .livenessProbe.httpGet.path")"
    [ "$p" = "/health /health" ] && pass "$env: $name probes /health" || fail "$env: $name probes '$p'"
  done
  # Ready only once the start-up script has written config.js
  p="$(q "$f" 'select(.kind == "Deployment" and .metadata.name == "dashboard") | .spec.template.spec.containers[0] | .readinessProbe.httpGet.path + " " + .livenessProbe.httpGet.path')"
  [ "$p" = "/config.js /health" ] && pass "$env: dashboard is ready on /config.js, alive on /health" || fail "$env: dashboard probes '$p'"

  # ---- requests and limits on every container, the hook's included ----
  bad="$(q "$f" '[select(.kind == "Deployment" or .kind == "Job") | .spec.template.spec as $s
    | (($s.containers // []) + ($s.initContainers // []))[]
    | select(.resources.requests.memory == null or .resources.limits.memory == null or .resources.requests.cpu == null)
    | .name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: every container has requests and limits" || fail "$env: containers without resources: $bad"

  # ---- the workload identity webhook's label: only where the Azure SDK runs, never next to AZURE_* settings ----
  labelled="$(q "$f" '[select(.kind == "Deployment" or .kind == "Job")
    | select(.spec.template.metadata.labels["azure.workload.identity/use"] == "true") | .metadata.name] | sort | join(" ")')"
  [ "$labelled" = "ingestion-retention ingestion-service" ] && pass "$env: only ingestion and retention carry the workload identity label" \
    || fail "$env: pods with the workload identity label: '$labelled'"
  for name in $labelled; do
    clash="$(q "$f" "[(select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-$name-env\") | .data | keys | .[]),
      (select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[].env[].name)]
      | map(select(test(\"^AZURE_\"))) | join(\" \")")"
    [ -z "$clash" ] && pass "$env: $name sets no AZURE_* the webhook would override" || fail "$env: $name sets $clash next to the webhook"
  done
  n="$(q "$f" '[select(.kind == "Deployment" and .metadata.name == "auth-service") | .spec.template.spec.containers[].env[] | select(.name | test("^AZURE_"))] | length')"
  [ "$n" = 0 ] && pass "$env: auth-service's AZURE_* come from its ConfigMap only" || fail "$env: auth-service has $n AZURE_* env entries"

  # ---- the hook: each container sees only its own secret files ----
  mounts() { q "$f" "select(.kind == \"Job\" and .metadata.name == \"qeos-migrate\") | .spec.template.spec.initContainers[] | select(.name == \"$1\")
    | [.volumeMounts[] | select(.name == \"secrets\") | .mountPath] | sort | join(\" \")"; }
  want="/mnt/secrets/auth-db-password /mnt/secrets/ingestion-db-password /mnt/secrets/monitoring-db-password /mnt/secrets/organization-db-password /mnt/secrets/postgres-admin-password /mnt/secrets/project-db-password /mnt/secrets/testmgmt-db-password"
  [ "$(mounts db-init)" = "$want" ] && pass "$env: db-init sees the admin and role passwords only, qeos_monitor's included" || fail "$env: db-init mounts '$(mounts db-init)'"
  for pair in auth-service:auth organization-service:organization project-service:project ingestion-service:ingestion \
      test-management-service:testmgmt; do
    IFS=: read -r name db <<< "$pair"
    want="$(printf '/mnt/secrets/%s\n' "$db-db-password" secret-key | sort | xargs)"
    [ "$(mounts "$name")" = "$want" ] \
      && pass "$env: hook's $name sees its own role's password and SECRET_KEY only" || fail "$env: hook's $name mounts '$(mounts "$name")'"
  done

  # ---- the gateway's Kubernetes settings ----
  gw() { q "$f" "select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-gateway-env\") | .data.$1"; }
  [ "$(gw UPSTREAM_SUFFIX)" = ".$NAMESPACE.svc.cluster.local" ] && pass "$env: gateway UPSTREAM_SUFFIX follows the namespace" \
    || fail "$env: gateway UPSTREAM_SUFFIX is '$(gw UPSTREAM_SUFFIX)'"
  [ "$(gw GATEWAY_TLS)|$(gw GATEWAY_PUBLIC_PORT)|$(gw GATEWAY_RESOLVER)|$(gw MONITORING_ENABLED)" \
    = "off|443|kube-dns.kube-system.svc.cluster.local|true" ] && pass "$env: gateway TLS off, port 443, cluster DNS, monitoring on" \
    || fail "$env: gateway settings are '$(gw GATEWAY_TLS)|$(gw GATEWAY_PUBLIC_PORT)|$(gw GATEWAY_RESOLVER)|$(gw MONITORING_ENABLED)'"
  rates="$(gw RATE_AUTH) $(gw RATE_API) $(gw RATE_COLLECT) $(gw RATE_COLLECT_BLOBS) $(gw RATE_COLLECT_ARTIFACTS)"
  [ "$rates" = "3r/s 10r/s 5r/s 25r/s 5r/s" ] && pass "$env: gateway rates halved" || fail "$env: gateway rates are '$rates'"
  [ -n "$(gw GATEWAY_TRUSTED_PROXIES)" ] && pass "$env: gateway trusts the edge's range" || fail "$env: GATEWAY_TRUSTED_PROXIES is empty"
  t="$(q "$f" 'select(.kind == "Service" and .metadata.name == "gateway") | .spec.type')"
  [ "$t" = ClusterIP ] && pass "$env: gateway Service is ClusterIP" || fail "$env: gateway Service type is '$t'"

  # ---- internal URLs carry no password ----
  for name in ingestion-service ingestion-retention; do
    u="$(q "$f" "select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-$name-env\") | .data.PROJECT_SERVICE_INTERNAL_URL")"
    [ "$u" = "http://project-service.$NAMESPACE.svc.cluster.local:8000" ] && pass "$env: $name internal URL is bare" \
      || fail "$env: $name PROJECT_SERVICE_INTERNAL_URL is '$u'"
  done
  u="$(q "$f" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-ingestion-retention-env") | .data.TEST_MANAGEMENT_INTERNAL_URL')"
  [ "$u" = "http://test-management-service.$NAMESPACE.svc.cluster.local:8000" ] && pass "$env: retention's test-management URL is bare" \
    || fail "$env: TEST_MANAGEMENT_INTERNAL_URL is '$u'"

  # ---- secrets only by reference ----
  n="$(q "$f" '[select(.kind == "Secret")] | length')"
  [ "$n" = 0 ] && pass "$env: the chart renders no Secret" || fail "$env: the chart renders $n Secret(s)"
  bad="$(q "$f" '[select(.kind == "ConfigMap") | .data // {} | keys | .[] | select(test("PASSWORD|SECRET|_KEY$"))] | join(" ")')"
  [ -z "$bad" ] && pass "$env: no ConfigMap carries a secret-looking key" || fail "$env: ConfigMap keys: $bad"
  bad="$(q "$f" '[.. | select(has("name") and has("value")) | select(.name | test("PASSWORD|SECRET|_KEY$")) | .name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: no env var with a secret-looking name has a literal value" || fail "$env: literal env: $bad"
done

# ---- every setting Compose gives a service, the chart gives it too (CI: the S3 backend, as Compose) ----
n="$(yq 'explode(.) | .services["auth-service"].environment | keys | length' "$COMPOSE" | tr -d '\r')"
[ "${n:-0}" -gt 10 ] || fail "docker-compose.yml was not read ($COMPOSE)"
for name in $APIS $WEB $LOOPS; do
  compose="$(yq "explode(.) | .services[\"$name\"].environment // {} | keys | .[]" "$COMPOSE" | tr -d '\r')"
  chart="$(q "$OUT/ci.yaml" "(select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-$name-env\") | .data | keys | .[]),
    (select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[0].env[]?.name)" | tr -d '\r')"
  missing=""
  for key in $compose; do
    case " $COMPOSE_ONLY " in *" $key "*) continue ;; esac
    printf '%s\n' "$chart" | grep -qx -- "$key" || missing="$missing $key"
  done
  [ -z "$missing" ] && pass "ci: $name has every Compose setting" || fail "ci: $name lacks Compose's$missing"
done

# ---- Key Vault: one SecretProviderClass per workload, with only its own keys ----
st="$OUT/staging.yaml"
v="$(q "$st" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-auth-service-env") | .data.AZURE_CLIENT_ID')"
[ "$v" = entra-app-from-values ] && pass "staging: auth-service's AZURE_CLIENT_ID is the value given" || fail "staging: auth AZURE_CLIENT_ID is '$v'"
for name in $APIS $LOOPS; do
  user="$(q "$st" "select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-$name-env\") | .data.POSTGRES_USER")"
  db="${user%_app}"
  dbkeys="$(q "$st" "[select(.kind == \"SecretProviderClass\" and .metadata.name == \"qeos-$name\") | .spec.secretObjects[0].data[].key
    | select(test(\"-db-password$\") or . == \"postgres-admin-password\")] | join(\" \")")"
  [ "$dbkeys" = "$db-db-password" ] && pass "staging: qeos-$name holds its own database password only" \
    || fail "staging: qeos-$name holds '$dbkeys', want $db-db-password"
  vol="$(q "$st" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.volumes[] | select(.csi) | .csi.volumeAttributes.secretProviderClass")"
  refs="$(q "$st" "[select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[].env[].valueFrom.secretKeyRef.name] | unique | join(\" \")")"
  [ "$vol|$refs" = "qeos-$name|qeos-secrets-$name" ] && pass "staging: $name mounts qeos-$name and reads qeos-secrets-$name" \
    || fail "staging: $name mounts '$vol' and reads '$refs'"
done

# ---- the Grafana proxy key: only the gateway, only with monitoring on ----
gwkey() { q "$OUT/$1.yaml" 'select(.kind == "Deployment" and .metadata.name == "gateway") | .spec.template.spec.containers[0].env[] | select(.name == "GRAFANA_PROXY_KEY") | .valueFrom.secretKeyRef.name + "/" + .valueFrom.secretKeyRef.key'; }
gwspc() { q "$OUT/$1.yaml" 'select(.kind == "SecretProviderClass" and .metadata.name == "qeos-gateway") | [.spec.secretObjects[0].data[].key] | join(" ")'; }
for env in ci staging; do
  [ -z "$(gwkey "$env-off")" ] && pass "$env: monitoring off, the gateway reads no GRAFANA_PROXY_KEY" || fail "$env: gateway reads '$(gwkey "$env-off")' with monitoring off"
done
[ -z "$(gwspc staging-off)" ] && pass "staging: monitoring off, no SecretProviderClass for the gateway" || fail "staging: qeos-gateway holds '$(gwspc staging-off)' with monitoring off"
[ "$(gwkey ci)" = "qeos-secrets/grafana-proxy-key" ] && pass "ci: monitoring on, the gateway reads grafana-proxy-key from qeos-secrets"   || fail "ci: gateway GRAFANA_PROXY_KEY is '$(gwkey ci)'"
[ "$(gwkey staging)" = "qeos-secrets-gateway/grafana-proxy-key" ] && pass "staging: monitoring on, the gateway reads grafana-proxy-key from qeos-secrets-gateway"   || fail "staging: gateway GRAFANA_PROXY_KEY is '$(gwkey staging)'"
[ "$(gwspc staging)" = grafana-proxy-key ] && pass "staging: monitoring on, qeos-gateway holds grafana-proxy-key only"   || fail "staging: qeos-gateway holds '$(gwspc staging)'"
v="$(q "$OUT/staging.yaml" 'select(.kind == "Deployment" and .metadata.name == "gateway") | [.spec.template.spec.volumes[] | select(.csi) | .csi.volumeAttributes.secretProviderClass] | join(" ")')"
[ "$v" = qeos-gateway ] && pass "staging: monitoring on, the gateway pod mounts qeos-gateway (the driver syncs its Secret)" || fail "staging: gateway mounts '$v'"
v="$(q "$OUT/staging-off.yaml" 'select(.kind == "Deployment" and .metadata.name == "gateway") | [.spec.template.spec.volumes[] | select(.csi)] | length')"
[ "$v" = 0 ] && pass "staging: monitoring off, the gateway mounts no secrets volume" || fail "staging: the gateway mounts $v CSI volumes with monitoring off"
# A rendered ConfigMap never holds the key
[ "$(q "$OUT/staging.yaml" 'select(.kind == "ConfigMap") | .data | keys | .[] | select(. == "GRAFANA_PROXY_KEY")')" = "" ]   && pass "staging: GRAFANA_PROXY_KEY is in no ConfigMap" || fail "staging: a ConfigMap sets GRAFANA_PROXY_KEY"
# A gateway secret the vault does not hold (keyvault.absent): its reference stays, optional, but no SecretProviderClass
# renders, so the pod must not mount one (it would stay in ContainerCreating)
OPTIONAL='secrets.optional={tm-secrets-key,smtp-user,smtp-password,alert-slack-webhook-url,alert-teams-webhook-url,foo-key}'
ABSENT='keyvault.absent={tm-secrets-key,smtp-user,smtp-password,alert-slack-webhook-url,alert-teams-webhook-url,foo-key}'
render staging-gw-absent -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" --set monitoring.enabled=false \
  --set services.gateway.secretEnv.FOO=foo-key --set "$OPTIONAL" --set "$ABSENT"
render staging-gw-absent-mon -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}" \
  --set services.gateway.secretEnv.FOO=foo-key --set "$OPTIONAL" --set "$ABSENT"
gwpod() { q "$OUT/$1.yaml" 'select(.kind == "Deployment" and .metadata.name == "gateway") | .spec.template.spec
  | ([.volumes[] | select(.csi) | .csi.volumeAttributes.secretProviderClass] | join(",")) + "|" + .serviceAccountName + "|"
    + ([.containers[0].env[] | select(.valueFrom.secretKeyRef) | .name + ":" + .valueFrom.secretKeyRef.key + ":" + ((.valueFrom.secretKeyRef.optional // false) | tostring)] | join(","))'; }
got="$(gwpod staging-gw-absent)|$(gwspc staging-gw-absent)"
[ "$got" = "|qeos-services|FOO:foo-key:true|" ] \
  && pass "staging: an absent gateway key keeps an optional reference, and no SecretProviderClass or CSI volume" \
  || fail "staging: absent gateway key gives '$got'"
got="$(gwpod staging-gw-absent-mon)|$(gwspc staging-gw-absent-mon)"
[ "$got" = "qeos-gateway|qeos-services|FOO:foo-key:true,GRAFANA_PROXY_KEY:grafana-proxy-key:false|grafana-proxy-key" ] \
  && pass "staging: with monitoring on, the gateway mounts qeos-gateway, which holds grafana-proxy-key only" \
  || fail "staging: absent gateway key with monitoring on gives '$got'"
# The same for every workload (qeos.secretsVolume follows qeos.vaultMounted): a loop job whose every key is in
# keyvault.absent (here only the SMTP login, which staging's vault lacks) renders no SecretProviderClass and mounts none
render staging-loop-absent -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}" \
  --set services.weekly-summary.database=null --set services.weekly-summary.secretEnv.SECRET_KEY=null \
  --set services.weekly-summary.secretEnv.INTERNAL_API_PASSWORD=null
got="$(q "$OUT/staging-loop-absent.yaml" 'select(.kind == "Deployment" and .metadata.name == "weekly-summary") | .spec.template.spec
  | ([.volumes[] | select(.csi)] | length | tostring) + "|" + ([.containers[].volumeMounts[] | select(.name == "secrets-store")] | length | tostring)')"
got="$got|$(q "$OUT/staging-loop-absent.yaml" '[select(.kind == "SecretProviderClass" and .metadata.name == "qeos-weekly-summary")] | length')"
[ "$got" = "0|0|0" ] && pass "staging: a loop job whose every key is absent mounts no CSI volume and has no SecretProviderClass" \
  || fail "staging: a loop job with only absent keys gives CSI volumes|mounts|SecretProviderClasses '$got'"

# ---- environment-specific choices ----
backend() { q "$OUT/$1.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-ingestion-service-env") | .data.ARTIFACTS_BACKEND'; }
[ "$(backend ci)" = s3 ] && pass "ci: artifacts on S3 (MinIO)" || fail "ci: ARTIFACTS_BACKEND is '$(backend ci)'"
[ "$(backend staging)" = azure ] && pass "staging: artifacts on Azure Blob" || fail "staging: ARTIFACTS_BACKEND is '$(backend staging)'"
np() { q "$OUT/$1.yaml" '[select(.kind == "NetworkPolicy")] | length'; }
# kindnet enforces NetworkPolicies (kind 0.24 and later): CI runs with them
[ "$(np ci)" -gt 0 ] && pass "ci: NetworkPolicies rendered ($(np ci); kindnet enforces them)" || fail "ci: no NetworkPolicy rendered"
[ "$(np ci-nopolicy)" = 0 ] && pass "networkPolicy.enabled=false renders no NetworkPolicy" || fail "networkPolicy.enabled=false renders $(np ci-nopolicy)"
# Monitoring on: each API admits Prometheus (networkPolicy.prometheus) on 8000, nothing else does
for env in ci staging; do
  for name in $APIS; do
    o="$(q "$OUT/$env.yaml" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"$name-ingress\") | .spec.ingress[] | select(.from[0].namespaceSelector != null)
      | .from[0].namespaceSelector.matchLabels[\"kubernetes.io/metadata.name\"] + \" \" + (.from[0].podSelector.matchLabels | to_entries | map(.key + \"=\" + .value) | join(\",\"))
        + \" \" + (.from | length | tostring) + \" \" + (.ports | map(.protocol + \"/\" + (.port | tostring)) | join(\",\"))] | join(\";\")")"
    [ "$o" = "qeos-monitoring app.kubernetes.io/name=prometheus 1 TCP/8000" ] && pass "$env: $name-ingress admits Prometheus from qeos-monitoring on 8000" \
      || fail "$env: $name-ingress Prometheus rule is '$o'"
  done
  o="$(q "$OUT/$env.yaml" '[select(.kind == "NetworkPolicy" and (.metadata.name == "dashboard-ingress" or .metadata.name == "gateway-ingress"))
    | .spec.ingress[].from[] | select(.namespaceSelector.matchLabels["kubernetes.io/metadata.name"] == "qeos-monitoring")] | length')"
  [ "$o" = 0 ] && pass "$env: Prometheus reaches the APIs only" || fail "$env: $o Prometheus sources on the dashboard or gateway"
done
# Monitoring off: no API admits anything from outside the namespace, the gateway's MONITORING_ENABLED is false, and
# no Prometheus setting is needed at all
for env in ci-off staging-off; do
  f="$OUT/$env.yaml"
  bad=""
  for name in $APIS; do
    n="$(q "$f" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"$name-ingress\") | .spec.ingress[].from[] | select(.namespaceSelector != null)] | length")"
    [ "$n" = 0 ] || bad="$bad $name"
  done
  [ -z "$bad" ] && pass "$env: monitoring off, no API admits anything from outside the namespace" || fail "$env: outside sources on:$bad"
  v="$(q "$f" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-gateway-env") | .data.MONITORING_ENABLED')"
  [ "$v" = false ] && pass "$env: monitoring off, the gateway's MONITORING_ENABLED is false" || fail "$env: the gateway's MONITORING_ENABLED is '$v'"
done
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" --set monitoring.enabled=false --set networkPolicy.prometheus=null >/dev/null 2>"$OUT/promoff.err"; then
  pass "monitoring off: networkPolicy.prometheus is not required"
else
  fail "monitoring off still requires networkPolicy.prometheus: $(tail -n 2 "$OUT/promoff.err")"
fi
ns="$(q "$OUT/ci-prometheus.yaml" '[select(.kind == "NetworkPolicy" and .metadata.name == "auth-service-ingress") | .spec.ingress[].from[]
  | select(.namespaceSelector != null) | .namespaceSelector.matchLabels["kubernetes.io/metadata.name"] + " "
  + (.podSelector.matchLabels | to_entries | map(.key + "=" + .value) | join(","))] | join(";")')"
[ "$ns" = "mon app=prom" ] && pass "networkPolicy.prometheus sets the scraper's namespace and pod labels" \
  || fail "networkPolicy.prometheus override gives '$ns'"
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set networkPolicy.prometheus.podLabels=null >/dev/null 2>"$OUT/promlabels.err"; then
  fail "empty networkPolicy.prometheus.podLabels renders (it would admit every pod of that namespace)"
else
  grep -q "podLabels" "$OUT/promlabels.err" && pass "empty networkPolicy.prometheus.podLabels is refused" \
    || fail "empty podLabels failed for another reason: $(tail -n 2 "$OUT/promlabels.err")"
fi
# The CI backing services: PostgreSQL for every workload with a database and the migration hook, MinIO for those
# that store artifacts (and the bucket Job); nothing else, and not on AKS
bk() { q "$OUT/ci.yaml" "[select(.kind == \"NetworkPolicy\" and .metadata.name == \"ci-backing-ingress\") | .spec.ingress[]
  | select(.ports[0].port == $1) | .from[].podSelector.matchLabels[\"app.kubernetes.io/name\"]] | sort | join(\" \")"; }
want="analytics-rollup auth-service impact-rollup ingestion-retention ingestion-service organization-service postgres-exporter project-service qeos-migrate test-management-service weekly-summary"
[ "$(bk 5432)" = "$want" ] && pass "ci: postgres admits the workloads with a database, the migration hook and postgres-exporter" \
  || fail "ci: postgres admits '$(bk 5432)', want '$want'"
[ "$(bk 9000)" = "ingestion-retention ingestion-service minio-init" ] && pass "ci: MinIO admits ingestion, retention and the bucket Job" \
  || fail "ci: MinIO admits '$(bk 9000)'"
sel="$(q "$OUT/ci.yaml" 'select(.kind == "NetworkPolicy" and .metadata.name == "ci-backing-ingress") | .spec.podSelector.matchLabels | to_entries | map(.key + "=" + .value) | sort | join(",")')"
[ "$sel" = "app.kubernetes.io/component=ci-backing,app.kubernetes.io/instance=qeos" ] && pass "ci: ci-backing-ingress selects the CI backing pods" \
  || fail "ci: ci-backing-ingress selects '$sel'"
n="$(q "$OUT/staging.yaml" '[select(.kind == "NetworkPolicy" and .metadata.name == "ci-backing-ingress")] | length')"
[ "$n" = 0 ] && pass "staging: no ci-backing-ingress" || fail "staging: ci-backing-ingress rendered"
# The add-on runs the Gateway's proxy pods in the Gateway's namespace, labelled by Istio's gateway template
src="$(q "$OUT/staging.yaml" 'select(.kind == "NetworkPolicy" and .metadata.name == "gateway-ingress") | .spec.ingress as $i
  | ($i | length | tostring) + " " + ($i[0].from | length | tostring) + " "
    + $i[0].from[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"] + " "
    + ($i[0].from[0].podSelector.matchLabels | to_entries | map(.key + "=" + .value) | sort | join(","))')"
[ "$src" = "1 1 $NAMESPACE gateway.networking.k8s.io/gateway-name=qeos-edge" ] \
  && pass "staging: gateway accepts traffic only from the edge's proxy pods (Gateway qeos-edge, namespace $NAMESPACE)" \
  || fail "staging: gateway-ingress allows '$src'"

# ---- the edge (spec 5.4): Gateway, routes, Issuer and Certificate on AKS only ----
st="$OUT/staging.yaml"
for kind in Gateway HTTPRoute Issuer Certificate; do
  n="$(q "$OUT/ci.yaml" "[select(.kind == \"$kind\")] | length")"
  [ "$n" = 0 ] && pass "ci: no $kind (edge.enabled off on kind)" || fail "ci: $n $kind rendered"
done
n="$(q "$st" '[select(.kind == "Gateway" and .metadata.name == "qeos-edge" and .spec.gatewayClassName == "approuting-istio")] | length')"
[ "$n" = 1 ] && pass "staging: Gateway qeos-edge of class approuting-istio" || fail "staging: $n Gateway qeos-edge of class approuting-istio"
hosts="$(q "$st" '[(select(.kind == "Gateway") | .spec.listeners[].hostname), (select(.kind == "HTTPRoute") | .spec.hostnames[]),
  (select(.kind == "Certificate") | .spec.dnsNames[])] | unique | join(" ")')"
[ "$hosts" = "$STAGING_HOST" ] && pass "staging: every listener, route and the certificate name publicUrl's host" \
  || fail "staging: edge host names '$hosts', want $STAGING_HOST"
l="$(q "$st" 'select(.kind == "Gateway") | [.spec.listeners[] | .name + ":" + (.port | tostring) + ":" + .protocol + ":" + (.tls.certificateRefs[0].name // "")] | join(" ")')"
[ "$l" = "http:80:HTTP: https:443:HTTPS:qeos-edge-tls" ] && pass "staging: listeners http 80 and https 443 with qeos-edge-tls" \
  || fail "staging: listeners are '$l'"
a="$(q "$st" 'select(.kind == "Gateway") | .spec.infrastructure.annotations | .["service.beta.kubernetes.io/azure-pip-name"] + " " + .["service.beta.kubernetes.io/azure-load-balancer-resource-group"]')"
[ "$a" = "pip-aks-qeos-staging-edge rg-qeos-staging" ] && pass "staging: the Gateway's Service takes Bicep's static public IP" \
  || fail "staging: infrastructure annotations are '$a'"
p="$(q "$st" 'select(.kind == "Gateway") | .spec.infrastructure.parametersRef.name' )"
etp="$(q "$st" "select(.kind == \"ConfigMap\" and .metadata.name == \"$p\") | .data.service | from_yaml | .spec.externalTrafficPolicy")"
[ "$etp" = Local ] && pass "staging: the edge's Service keeps client IPs (externalTrafficPolicy Local via $p)" \
  || fail "staging: externalTrafficPolicy through parametersRef '$p' is '$etp'"
probes="$(q "$st" "select(.kind == \"ConfigMap\" and .metadata.name == \"$p\") | .data.service | from_yaml | .metadata.annotations
  | to_entries | map(select(.value == null) | .key) | length")"
[ "$probes" = 6 ] && pass "staging: the Cluster-only health-probe annotations are unset" || fail "staging: $probes probe annotations unset, want 6"
r="$(q "$st" 'select(.kind == "HTTPRoute" and .metadata.name == "qeos") | .spec | .parentRefs[0].sectionName + " "
  + .rules[0].backendRefs[0].name + ":" + (.rules[0].backendRefs[0].port | tostring) + " " + .rules[0].timeouts.request')"
[ "$r" = "https gateway:8080 0s" ] && pass "staging: HTTPS goes to the gateway Service, no edge timeout" || fail "staging: route qeos is '$r'"
r="$(q "$st" 'select(.kind == "HTTPRoute" and .metadata.name == "qeos-https-redirect") | .spec | .parentRefs[0].sectionName + " "
  + .rules[0].filters[0].requestRedirect.scheme + " " + (.rules[0].filters[0].requestRedirect.statusCode | tostring)')"
[ "$r" = "http https 301" ] && pass "staging: plain HTTP redirects to HTTPS" || fail "staging: redirect route is '$r'"
# AKS's Managed Gateway API installs the standard channel only, from bundle v1.2.1 (Kubernetes 1.26-1.33) to v1.5.1
# (1.36; learn.microsoft.com/azure/aks/managed-gateway-api). Gateway.spec.infrastructure (annotations, parametersRef)
# and HTTPRoute rules[].timeouts are standard since v1.2.0, so the chart keeps to these fields; CI's helm-kind job applies
# the rendered objects with server-side dry run against the v1.2.1 standard CRDs
k="$(q "$st" 'select(.kind == "Gateway") | (.spec | keys | join(",")) + " " + (.spec.infrastructure | keys | join(","))
  + " " + (.spec.infrastructure.parametersRef | keys | join(","))')"
[ "$k" = "gatewayClassName,infrastructure,listeners annotations,parametersRef group,kind,name" ]   && pass "staging: the Gateway uses standard-channel v1.2 fields only" || fail "staging: the Gateway's fields are '$k'"
k="$(q "$st" '[select(.kind == "HTTPRoute") | .spec.rules[] | keys | .[]] + [select(.kind == "HTTPRoute") | .spec.rules[].timeouts // {} | keys | .[]] | sort | unique | join(",")')"
[ "$k" = "backendRefs,filters,matches,request,timeouts" ] && pass "staging: the HTTPRoutes use standard-channel v1.2 fields only"   || fail "staging: the HTTPRoutes' rule fields are '$k'"
v="$(q "$st" '[select(.kind == "Gateway" or .kind == "HTTPRoute") | .apiVersion] | unique | join(",")')"
[ "$v" = "gateway.networking.k8s.io/v1" ] && pass "staging: Gateway API v1 (standard) only" || fail "staging: Gateway API versions '$v'"
c="$(q "$st" 'select(.kind == "Certificate") | .spec.secretName + " " + .spec.issuerRef.kind + "/" + .spec.issuerRef.name')"
[ "$c" = "qeos-edge-tls Issuer/qeos-letsencrypt" ] && pass "staging: Certificate from the namespaced Issuer into qeos-edge-tls" \
  || fail "staging: Certificate is '$c'"
i="$(q "$st" 'select(.kind == "Issuer") | .spec.acme | .server + " " + .solvers[0].http01.gatewayHTTPRoute.parentRefs[0].name + "/" + .solvers[0].http01.gatewayHTTPRoute.parentRefs[0].sectionName')"
[ "$i" = "https://acme-v02.api.letsencrypt.org/directory qeos-edge/http" ] && pass "staging: Let's Encrypt HTTP-01 through the Gateway's http listener" \
  || fail "staging: Issuer is '$i'"
# The deploy identity administers the namespace only: nothing cluster-scoped, nothing aimed at another namespace
for env in ci staging; do
  bad="$(q "$OUT/$env.yaml" '[select(.kind != null) | select((.kind | test("^(Deployment|Service|ConfigMap|ServiceAccount|Job|PodDisruptionBudget|NetworkPolicy|SecretProviderClass|Gateway|HTTPRoute|Issuer|Certificate|ServiceMonitor|PrometheusRule)$") | not)
    or (.metadata.namespace // "") != "") | .kind + "/" + .metadata.name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: only namespaced kinds, none with a namespace of its own" || fail "$env: cluster-scoped or foreign: $bad"
done
smtp() { q "$OUT/$1.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-auth-service-env") | .data.SMTP_HOST + " " + .data.SMTP_PORT + " " + .data.SMTP_TLS'; }
# Belt and braces with the empty SMTP_HOST above: the services themselves log the links when a server that wants a
# sign-in has no credentials (qeos_shared.mail)
login="$(q "$OUT/staging-email.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-auth-service-env") | .data.SMTP_REQUIRE_LOGIN')"
[ "$login" = true ] && pass "staging: SMTP_REQUIRE_LOGIN is on (no sending without the SMTP credentials)"   || fail "staging: SMTP_REQUIRE_LOGIN is '$login'"
[ "$(smtp staging)" = " 587 true" ] && pass "staging: no SMTP_HOST while the vault lacks the SMTP credentials (links logged)" \
  || fail "staging: SMTP settings are '$(smtp staging)'"
[ "$(smtp staging-email)" = "smtp.azurecomm.net 587 true" ] && pass "staging: Communication Services SMTP once the credentials exist" \
  || fail "staging (email): SMTP settings are '$(smtp staging-email)'"
u="$(q "$st" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-auth-service-env") | .data.BASE_URL')"
[ "$u" = "https://$STAGING_HOST" ] && pass "staging: BASE_URL is publicUrl" || fail "staging: BASE_URL is '$u'"
spc="$(q "$OUT/staging.yaml" 'select(.kind == "SecretProviderClass" and .metadata.name == "qeos-migrate") | .metadata.annotations["helm.sh/hook-weight"]')"
[ "$spc" = -10 ] && pass "staging: migration SecretProviderClass is a hook at weight -10" || fail "staging: its hook weight is '$spc'"
n="$(q "$OUT/ci.yaml" '[select(.kind == "SecretProviderClass")] | length')"
[ "$n" = 0 ] && pass "ci: no SecretProviderClass (secrets from qeos-secrets)" || fail "ci: $n SecretProviderClass rendered"
n="$(q "$OUT/staging.yaml" '[select(.metadata.labels["app.kubernetes.io/component"] == "ci-backing")] | length')"
[ "$n" = 0 ] && pass "staging: no in-cluster postgres or MinIO" || fail "staging: $n CI backing resources rendered"
n="$(q "$OUT/ci.yaml" '[select(.kind == "Deployment" and (.metadata.name == "postgres" or .metadata.name == "minio"))] | length')"
[ "$n" = 2 ] && pass "ci: in-cluster postgres and MinIO" || fail "ci: $n of postgres/MinIO rendered"
# The CI server is what Flexible Server is: the same major, and db-init's admin is a CREATEROLE CREATEDB login created
# by the init script, not the superuser
pgdeploy='select(.kind == "Deployment" and .metadata.name == "postgres") | .spec.template.spec'
major="$(sed -n "s/^param version string = '\([0-9]*\)'.*/\1/p" "$CHART/../../azure/modules/postgres.bicep")"
img="$(q "$OUT/ci.yaml" "$pgdeploy | .containers[0].image")"
[ -n "$major" ] && [[ "$img" == postgres:"$major".* ]] && pass "ci: the in-cluster server is PostgreSQL $major, as Flexible Server ($img)" \
  || fail "ci: the in-cluster server is '$img', Flexible Server is '$major'"
super="$(q "$OUT/ci.yaml" "$pgdeploy | .containers[0].env[] | select(.name == \"POSTGRES_USER\") | .value")"
admin="$(q "$OUT/ci.yaml" "$pgdeploy | .containers[0].env[] | select(.name == \"QEOS_ADMIN_USER\") | .value")"
pguser="$(q "$OUT/ci.yaml" 'select(.kind == "Job" and .metadata.name == "qeos-migrate") | .spec.template.spec.initContainers[] | select(.name == "db-init") | .env[] | select(.name == "PGUSER") | .value')"
[ "$super" = postgres ] && [ "$admin" = qeosadmin ] && [ "$pguser" = qeosadmin ] \
  && pass "ci: db-init connects as qeosadmin, which the init script creates; the superuser is postgres" \
  || fail "ci: superuser '$super', init script admin '$admin', db-init PGUSER '$pguser'"
# Non-root under PSA restricted: the image's postgres user (999) owns the data directory, which lives on an emptyDir
pg="$(q "$OUT/ci.yaml" "$pgdeploy | (.securityContext.runAsUser | tostring) + \" \" + (.securityContext.fsGroup | tostring) + \" \"
  + (.containers[0].env[] | select(.name == \"PGDATA\") | .value)")"
data="$(q "$OUT/ci.yaml" "$pgdeploy | (.containers[0].volumeMounts[] | select(.name == \"data\") | .mountPath) + \" \" + (.volumes[] | select(.name == \"data\") | .emptyDir != null | tostring)")"
[ "${pg% *}" = "999 999" ] && [[ "${pg##* }/" == "${data% *}"/* ]] && [ "${data#* }" = true ] \
  && pass "ci: postgres runs as uid 999 (fsGroup 999) with PGDATA on its emptyDir" || fail "ci: postgres is '$pg', data '$data'"
mnt="$(q "$OUT/ci.yaml" "$pgdeploy | (.containers[0].volumeMounts[] | select(.name == \"init\") | .mountPath) + \" \" + (.volumes[] | select(.name == \"init\") | .configMap.name)")"
[ "$mnt" = "/docker-entrypoint-initdb.d postgres-init" ] && pass "ci: the init script is mounted for the entrypoint" \
  || fail "ci: the init volume is '$mnt'"
w="$(q "$OUT/ci.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "postgres-init") | .metadata.annotations["helm.sh/hook-weight"] + " " + (.data["ci-postgres-init.sh"] | test("CREATEROLE CREATEDB NOSUPERUSER") | tostring)')"
[ "$w" = "-20 true" ] && pass "ci: the postgres-init ConfigMap is a hook with the server (-20) and creates a non-superuser admin" \
  || fail "ci: postgres-init is '$w'"
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set postgres.adminUser=postgres >/dev/null 2>"$OUT/super.err"; then
  fail "ci: postgres.adminUser=postgres renders (db-init would run as the superuser)"
else
  grep -q "must not be postgres" "$OUT/super.err" && pass "ci: postgres.adminUser=postgres is refused" \
    || fail "ci: adminUser=postgres failed for another reason: $(tail -n 2 "$OUT/super.err")"
fi
# kind's images are tagged :kind, never Compose's :local: a local kind build must not replace the dev stack's images
bad="$(q "$OUT/ci.yaml" '[.spec.template.spec | (.containers // []) + (.initContainers // []) | .[].image | select(test("^qeos/") and (test(":kind$") | not))] | unique | join(",")' | tr -d "[:space:]")"
[ -z "$bad" ] && pass "ci: every qeos/ image is tagged :kind" || fail "ci: images not tagged :kind: $bad"

# ---- monitoring (ADR-038 Stage 2): ServiceMonitors, PrometheusRules, postgres-exporter and Alertmanager ----
MONITORING="$CHART/../../../monitoring"
# The rule groups: Compose's alerts.yml and recording.yml without qeos-host (node-exporter's, Compose only) and
# qeos-containers (a restarted pod's container is a new series on Kubernetes, so its restart count never rises: the
# alert could never fire; KubePodCrashLooping covers it), and the threshold that Compose's entrypoint.sh renders
want_groups="$( { yq '.groups[].name' "$MONITORING/prometheus/alerts.yml"; yq '.groups[].name' "$MONITORING/prometheus/recording.yml";
  echo qeos-thresholds; } | tr -d '\r' | grep -vx -e qeos-host -e qeos-containers | sort | xargs)"
[[ " $want_groups " == *" qeos-services "* ]] || fail "monitoring/prometheus/alerts.yml was not read"
# The Compose job names: Prometheus's job label of each scraped Service
want_jobs="alertmanager=alertmanager auth-service=auth ingestion-service=ingestion organization-service=organization postgres-exporter=postgres project-service=project test-management-service=test-management"
for env in ci staging; do
  f="$OUT/$env.yaml"
  [ -s "$f" ] || continue
  got="$(q "$f" '[select(.kind == "PrometheusRule") | .spec.groups[].name] | sort | join(" ")')"
  [ "$got" = "$want_groups" ] && pass "$env: the PrometheusRules hold Compose's groups but qeos-host, and qeos-thresholds" \
    || fail "$env: PrometheusRule groups are '$got', want '$want_groups'"
  [[ " $got " == *" qeos-services "* && " $got " != *" qeos-host "* ]] && pass "$env: qeos-services rendered, qeos-host left out" \
    || fail "$env: qeos-services missing or qeos-host present: '$got'"
  t="$(q "$f" 'select(.kind == "PrometheusRule") | .spec.groups[] | select(.name == "qeos-thresholds") | .rules[0].record + " " + .rules[0].expr')"
  [ "$t" = "postgresql_database_size_alert_bytes vector(20 * 1e9)" ] && pass "$env: qeos-thresholds records vector(20 * 1e9)" \
    || fail "$env: qeos-thresholds is '$t'"
  # The rules themselves, unchanged: the chart's copies through fromYaml and back
  for src in alerts recording; do
    # Keys sorted on both sides: Helm's toYaml sorts them
    a="$(yq -o json -I0 '.groups | map(select(.name != "qeos-host" and .name != "qeos-containers")) | sort_keys(..)' "$MONITORING/prometheus/$src.yml" | tr -d '\r')"
    b="$(yq ea -o json -I0 "select(.kind == \"PrometheusRule\" and .metadata.name == \"qeos-$src\") | .spec.groups | sort_keys(..)" "$f" | tr -d '\r')"
    [ -n "$a" ] && [ "$a" = "$b" ] && pass "$env: PrometheusRule qeos-$src equals monitoring/prometheus/$src.yml (but the skipped groups)" \
      || fail "$env: PrometheusRule qeos-$src differs from $src.yml"
  done

  # ServiceMonitors: the Compose job names from each Service's qeos.io/metrics-job label; ingestion honours its labels
  # (the loop jobs' heartbeats carry their own job); every one drops the operator's `service` target label, which would
  # otherwise rename the services' own `service` label to exported_service
  got="$(q "$f" '[select(.kind == "ServiceMonitor") | .metadata.name + "=" + ((.spec.endpoints[0].honorLabels // false) | tostring)] | sort | join(" ")')"
  [ "$got" = "qeos-alertmanager=false qeos-apis=false qeos-ingestion=true qeos-postgres=false" ] \
    && pass "$env: ServiceMonitors qeos-apis, qeos-ingestion (honorLabels), qeos-postgres, qeos-alertmanager" \
    || fail "$env: ServiceMonitors are '$got'"
  got="$(q "$f" '[select(.kind == "ServiceMonitor") | .spec.jobLabel + " " + (.spec.endpoints | length | tostring) + " " + .spec.endpoints[0].port
    + " " + (.spec.endpoints[0].path // "/metrics") + " " + ((.spec.endpoints[0].relabelings // []) | map(select(.action == "labeldrop") | .regex) | join(","))] | unique | join(";")')"
  [ "$got" = "qeos.io/metrics-job 1 http /metrics service" ] \
    && pass "$env: every ServiceMonitor takes job from qeos.io/metrics-job, scrapes port http /metrics and drops the service target label" \
    || fail "$env: ServiceMonitor settings are '$got'"
  got=""
  for svc in $(q "$f" '[select(.kind == "Service") | .metadata.name] | join(" ")'); do
    job="$(q "$f" "select(.kind == \"Service\" and .metadata.name == \"$svc\") | .metadata.labels[\"qeos.io/metrics-job\"] // \"\"")"
    [ -n "$job" ] && got="$got $svc=$job"
  done
  got="$(printf '%s\n' $got | sort | xargs)"
  [ "$got" = "$want_jobs" ] && pass "$env: the scraped Services carry Compose's job names" || fail "$env: qeos.io/metrics-job labels are '$got'"
  for pair in "qeos-apis:auth-service organization-service project-service test-management-service" "qeos-ingestion:ingestion-service" \
      "qeos-postgres:postgres-exporter" "qeos-alertmanager:alertmanager"; do
    sm="${pair%%:*}"
    picked=""
    for svc in $(q "$f" '[select(.kind == "Service") | .metadata.name] | sort | join(" ")'); do
      labels="$(q "$f" "select(.kind == \"Service\" and .metadata.name == \"$svc\") | .metadata.labels | to_entries | map(.key + \"=\" + .value) | join(\" \")")"
      selects "$f" "$sm" "$labels" ServiceMonitor .spec.selector && picked="$picked $svc"
    done
    [ "${picked# }" = "${pair#*:}" ] && pass "$env: $sm scrapes exactly ${pair#*:}" || fail "$env: $sm selects '${picked# }', want '${pair#*:}'"
  done

  # The two workloads: one replica each, Compose's images, Services named as in Compose
  dep() { q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$1\") | $2"; }
  for pair in alertmanager:9093 postgres-exporter:9187; do
    name="${pair%%:*}"
    port="${pair#*:}"
    [ "$(dep "$name" .spec.replicas)" = 1 ] && pass "$env: $name has 1 replica" || fail "$env: $name has replicas '$(dep "$name" .spec.replicas)'"
    s="$(q "$f" "select(.kind == \"Service\" and .metadata.name == \"$name\") | .spec.ports[0].name + \":\" + (.spec.ports[0].port | tostring)")"
    [ "$s" = "http:$port" ] && pass "$env: Service $name is port http $port" || fail "$env: Service $name is '$s'"
    img="$(yq ".services[\"$name\"].image" "$COMPOSE" | tr -d '\r')"
    imgs="$(dep "$name" '[.spec.template.spec | (.containers // []) + (.initContainers // []) | .[].image] | unique | join(" ")')"
    [ -n "$img" ] && [ "$imgs" = "$img" ] && pass "$env: $name runs $img, as Compose" || fail "$env: $name runs '$imgs', Compose '$img'"
    # Only Prometheus reaches it, on its own port
    np="$name-ingress"
    o="$(outside "$np")|$(callers "$np" "$port")|$(ports "$np")"
    [ "$o" = "qeos-monitoring app.kubernetes.io/name=prometheus||TCP/$port" ] && pass "$env: $np admits only Prometheus, on $port" \
      || fail "$env: $np is '$o'"
  done
  bad="$(q "$f" '[select(.kind == "Deployment" and (.metadata.name == "alertmanager" or .metadata.name == "postgres-exporter"))
    | .spec.template.spec as $s | (($s.containers // []) + ($s.initContainers // []))[]
    | select(.resources.requests.cpu == null or .resources.requests.memory == null or .resources.limits.cpu == null or .resources.limits.memory == null)
    | .name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: alertmanager's and postgres-exporter's containers have cpu and memory requests and limits" \
    || fail "$env: monitoring containers without full resources: $bad"
  lim="$(dep alertmanager '.spec.template.spec.containers[0].resources.limits.memory') $(dep postgres-exporter '.spec.template.spec.containers[0].resources.limits.memory')"
  [ "$lim" = "64Mi 64Mi" ] && pass "$env: memory limits start from Compose's mem_limit (64m each)" || fail "$env: memory limits are '$lim'"

  # postgres-exporter: as Compose's, but to postgres.host with postgres.sslmode
  a="$(dep postgres-exporter '.spec.template.spec.containers[0] | (.command // []) + (.args // []) | join(" ")')"
  [[ " $a " == *" --collector.stat_statements "* ]] && pass "$env: postgres-exporter runs with --collector.stat_statements" \
    || fail "$env: postgres-exporter runs '$a'"
  pe() { dep postgres-exporter ".spec.template.spec.containers[0].env[] | select(.name == \"$1\") | $2"; }
  case "$env" in
    ci) uri="postgres:5432/postgres?sslmode=disable"; ref="qeos-secrets/monitoring-db-password" ;;
    *) uri="pg-placeholder.postgres.database.azure.com:5432/postgres?sslmode=require"; ref="qeos-secrets-postgres-exporter/monitoring-db-password" ;;
  esac
  got="$(pe DATA_SOURCE_URI .value) $(pe DATA_SOURCE_USER .value) $(pe DATA_SOURCE_PASS '.valueFrom.secretKeyRef.name + "/" + .valueFrom.secretKeyRef.key')"
  [ "$got" = "$uri qeos_monitor $ref" ] && pass "$env: postgres-exporter connects as qeos_monitor to $uri" || fail "$env: postgres-exporter's connection is '$got'"

  # Alertmanager: render.sh in an init container writes the configuration the server reads; the channels' secrets from
  # the synced Secret, optional (no channel: the null receiver)
  init="$(dep alertmanager '.spec.template.spec.initContainers[0].command | join(" ")')"
  cfg="$(dep alertmanager '.spec.template.spec.containers[0].args[] | select(test("^--config.file="))')"
  [[ "$init" == "sh /etc/qeos/alertmanager/render.sh "* ]] && [ "--config.file=${init##* }" = "$cfg" ] \
    && pass "$env: the init container renders ${init##* }, which Alertmanager reads" || fail "$env: init '$init', server '$cfg'"
  am() { dep alertmanager ".spec.template.spec.initContainers[0].env[] | select(.name == \"$1\") | $2"; }
  got=""
  for var in ALERT_SLACK_WEBHOOK_URL:alert-slack-webhook-url ALERT_TEAMS_WEBHOOK_URL:alert-teams-webhook-url SMTP_USER:smtp-user SMTP_PASSWORD:smtp-password; do
    got="$got $(am "${var%%:*}" '.valueFrom.secretKeyRef.key + ":" + (.valueFrom.secretKeyRef.optional | tostring)')"
  done
  [ "$got" = " alert-slack-webhook-url:true alert-teams-webhook-url:true smtp-user:true smtp-password:true" ] \
    && pass "$env: Alertmanager's webhooks and SMTP login are optional secret references" || fail "$env: Alertmanager's secret env is '$got'"
  got="$(am ALERT_EMAIL_TO .value)|$(am SMTP_PORT .value)|$(am SMTP_TLS .value)"
  [ "$got" = "|587|true" ] && pass "$env: ALERT_EMAIL_TO empty by default, SMTP settings from smtp" || fail "$env: Alertmanager's settings are '$got'"
  v="$(dep alertmanager '.spec.template.spec.containers[0].args | join(" ")')"
  [[ " $v " == *" --cluster.listen-address= "* ]] && pass "$env: Alertmanager runs without clustering (one replica)" || fail "$env: Alertmanager args '$v'"
  for file in render.sh alertmanager.yml.template; do
    [ "$(q "$f" "select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-alertmanager\") | .data[\"$file\"]")" = "$(cat "$CHART/files/monitoring/alertmanager/$file")" ] \
      && pass "$env: ConfigMap qeos-alertmanager carries $file" || fail "$env: ConfigMap qeos-alertmanager's $file differs from the chart's copy"
  done
  # ---- Grafana (Task 6): Compose's grafana, on 127.0.0.1:3000 behind the grafana-proxy sidecar ----
  gf() { dep grafana ".spec.template.spec.containers[] | select(.name == \"$1\") | $2"; }
  gfenv() { gf grafana ".env[] | select(.name == \"$1\") | $2"; }
  [ "$(dep grafana .spec.replicas)" = 1 ] && pass "$env: grafana has 1 replica" || fail "$env: grafana has replicas '$(dep grafana .spec.replicas)'"
  got="$(dep grafana '[.spec.template.spec.containers[].name] | join(" ")')"
  [ "$got" = "grafana grafana-proxy" ] && pass "$env: grafana's pod runs grafana and the grafana-proxy sidecar" \
    || fail "$env: grafana's containers are '$got'"
  img="$(yq '.services.grafana.image' "$COMPOSE" | tr -d '\r')"
  [ -n "$img" ] && [ "$(gf grafana .image)" = "$img" ] && pass "$env: grafana runs $img, as Compose" \
    || fail "$env: grafana runs '$(gf grafana .image)', Compose '$img'"
  img="$(sed -n 's/^FROM //p' "$CHART/../../../gateway/Dockerfile" | tr -d '\r')"
  [[ "$img" == *@sha256:* ]] && [ "$(gf grafana-proxy .image)" = "$img" ] && pass "$env: grafana-proxy runs the gateway's image and digest" \
    || fail "$env: grafana-proxy runs '$(gf grafana-proxy .image)', the gateway '$img'"
  # Every setting of Compose's grafana, with Compose's value but for those Kubernetes changes
  bad=""
  while IFS='=' read -r key value; do
    [ -n "$key" ] || continue
    case "$key" in GF_SERVER_ROOT_URL|GF_SECURITY_ADMIN_PASSWORD|GF_AUTH_PROXY_WHITELIST) continue ;; esac
    [ "$(gfenv "$key" .value)" = "$value" ] || bad="$bad $key"
  done < <(yq '.services.grafana.environment | to_entries | .[] | .key + "=" + .value' "$COMPOSE" | tr -d '\r')
  [ -z "$bad" ] && pass "$env: grafana has every Compose setting, with Compose's value" || fail "$env: grafana's settings differ from Compose's:$bad"
  case "$env" in
    ci) root="https://localhost/grafana/"; secret=qeos-secrets ;;
    *) root="https://$STAGING_HOST/grafana/"; secret=qeos-secrets-grafana ;;
  esac
  # No TCP listener (a port-forward reaches TCP ports only): a unix socket on an emptyDir only the sidecar shares, which
  # is why the auth proxy needs no whitelist (Grafana 12 refuses every socket peer when one is set)
  socket="$(gfenv GF_SERVER_SOCKET .value)"
  got="$(gfenv GF_SERVER_ROOT_URL .value)|$(gfenv GF_SERVER_PROTOCOL .value)|$(gfenv GF_SERVER_SOCKET_MODE .value)"
  got="$got|$(gf grafana '[.env[] | select(.name == "GF_AUTH_PROXY_WHITELIST")] | length')=$(gfenv GF_AUTH_PROXY_WHITELIST .value)"
  got="$got|$(gf grafana '[.env[] | select(.name == "GF_SERVER_HTTP_ADDR" or .name == "GF_SERVER_HTTP_PORT")] | length')"
  [ "$got" = "$root|socket|0660|1=|0" ] && [[ "$socket" == /*.sock ]] \
    && pass "$env: grafana serves on the unix socket $socket only (mode 0660), no auth proxy whitelist; root $root" \
    || fail "$env: grafana's root, protocol, socket mode, whitelist and TCP settings are '$got', socket '$socket'"
  sockvol="$(gf grafana ".volumeMounts[] | select(.mountPath == \"${socket%/*}\") | .name")"
  got="$(dep grafana "[.spec.template.spec.containers[] | select(.volumeMounts[] | .name == \"$sockvol\") | .name] | join(\" \")")"
  got="$got|$(dep grafana ".spec.template.spec.volumes[] | select(.name == \"$sockvol\") | (.emptyDir != null) | tostring")"
  [ -n "$sockvol" ] && [ "$got" = "grafana grafana-proxy|true" ] \
    && pass "$env: the socket's directory is an emptyDir shared by grafana and grafana-proxy only" \
    || fail "$env: the socket's volume '$sockvol' is mounted by and emptyDir: '$got'"
  grep -qF "proxy_pass http://unix:$socket:" "$CHART/files/grafana-proxy.conf.template" \
    && pass "$env: grafana-proxy proxies to that socket" || fail "$env: files/grafana-proxy.conf.template does not proxy to unix:$socket"
  got="$(gfenv GF_SECURITY_ADMIN_PASSWORD '.valueFrom.secretKeyRef.name + "/" + .valueFrom.secretKeyRef.key + ":" + ((.valueFrom.secretKeyRef.optional // false) | tostring)')"
  [ "$got" = "$secret/grafana-admin-password:false" ] && pass "$env: grafana's admin password is $secret/grafana-admin-password" \
    || fail "$env: GF_SECURITY_ADMIN_PASSWORD is '$got'"
  # Grafana's process sees the admin password only: the key reaches the sidecar alone (env), and with Key Vault the CSI
  # volume, whose files hold both secrets, is mounted in the sidecar, never in Grafana
  got="$(gf grafana '[.volumeMounts[] | select(.name == "secrets-store")] | length')"
  case "$env" in
    ci) want="0|0" ;;
    *) want="0|1" ;;
  esac
  got="$got|$(gf grafana-proxy '[.volumeMounts[] | select(.name == "secrets-store")] | length')"
  [ "$got" = "$want" ] && pass "$env: the Key Vault CSI volume is the sidecar's only (Grafana|sidecar: $got)" \
    || fail "$env: secrets-store mounts (Grafana|sidecar) are '$got', want '$want'"
  got="$(gf grafana '[.env[] | select(.valueFrom.secretKeyRef) | .valueFrom.secretKeyRef.key] | join(" ")')"
  got="$got|$(gf grafana-proxy '[.env[] | select(.valueFrom.secretKeyRef) | .name + ":" + .valueFrom.secretKeyRef.name + "/" + .valueFrom.secretKeyRef.key] | join(" ")')"
  [ "$got" = "grafana-admin-password|GRAFANA_PROXY_KEY:$secret/grafana-proxy-key" ] \
    && pass "$env: grafana reads the admin password only, grafana-proxy the key only" || fail "$env: grafana's and grafana-proxy's secrets are '$got'"
  # Compose's entrypoint: no start without the admin password (an empty one would mean admin/admin)
  c="$(gf grafana '.command | join(" ")')"
  [[ "$c" == *'[ -z "$GF_SECURITY_ADMIN_PASSWORD" ]'*"exit 1"*"exec /run.sh"* ]] && pass "$env: grafana refuses to start without the admin password" \
    || fail "$env: grafana's command is '$c'"
  # A SIGKILL leaves the socket in its emptyDir: the command removes it before Grafana binds again
  [[ "$c" == *'rm -f "$GF_SERVER_SOCKET";'*"exec /run.sh"* ]] && pass "$env: grafana removes a stale socket before it starts" \
    || fail "$env: grafana's command keeps a stale socket: '$c'"
  got="$(gf grafana '[.volumeMounts[] | .mountPath + ((.readOnly // false) | tostring)] | sort | join(" ")')"
  [ "$got" = "/etc/qeos/grafana/dashboardstrue /etc/qeos/grafana/provisioningtrue /tmpfalse /var/lib/grafanafalse ${socket%/*}false" ] \
    && pass "$env: grafana mounts the dashboards and provisioning read-only where Compose does, /var/lib/grafana and /tmp writable" \
    || fail "$env: grafana mounts '$got'"
  got="$(dep grafana '[.spec.template.spec.volumes[] | select(.name == "data" or .name == "tmp") | .name + ":" + ((.emptyDir != null) | tostring)] | sort | join(" ")')"
  [ "$got" = "data:true tmp:true" ] && pass "$env: /var/lib/grafana and /tmp are emptyDirs" || fail "$env: grafana's writable volumes are '$got'"
  # The Service: port 3000, to the sidecar's port only (Grafana has no port)
  s="$(q "$f" 'select(.kind == "Service" and .metadata.name == "grafana") | (.spec.ports | length | tostring) + " " + (.spec.ports[0].port | tostring) + " " + .spec.ports[0].targetPort')"
  pp="$(gf grafana-proxy '[.ports[] | .name + "=" + (.containerPort | tostring)] | join(" ")')"
  gp="$(gf grafana '[(.ports // [])[] | .name] | join(" ")')"
  [ "$s" = "1 3000 http" ] && [ "$pp" = "http=8080" ] && [ -z "$gp" ] \
    && pass "$env: Service grafana port 3000 targets grafana-proxy's http (8080), never Grafana" \
    || fail "$env: Service grafana is '$s', grafana-proxy's ports '$pp', grafana's '$gp'"
  # Probes: the sidecar is ready on its /_health; Grafana starts and stays alive on its own socket, so a broken sidecar
  # never restarts a healthy Grafana
  got="$(gf grafana-proxy '.readinessProbe.httpGet.path + " " + (.readinessProbe.httpGet.port | tostring)')"
  for probe in startupProbe livenessProbe; do
    got="$got|$(gf grafana ".$probe | ((.httpGet != null) | tostring) + \" \" + (.exec.command | join(\" \"))")"
  done
  want="curl -sf -o /dev/null -m 2 --unix-socket $socket http://localhost/grafana/api/health"
  [ "$got" = "/_health http|false $want|false $want" ] \
    && pass "$env: grafana-proxy is ready on /_health; grafana starts and lives on its own socket (curl)" \
    || fail "$env: grafana's probes are '$got'"
  # The sidecar: nginx renders its template into an emptyDir (NGINX_ENVSUBST_OUTPUT_DIR), substituting GRAFANA_PROXY_KEY only
  out="$(gf grafana-proxy '.env[] | select(.name == "NGINX_ENVSUBST_OUTPUT_DIR") | .value')"
  vol="$(gf grafana-proxy ".volumeMounts[] | select(.mountPath == \"$out\") | .name")"
  ed="$(dep grafana ".spec.template.spec.volumes[] | select(.name == \"$vol\") | (.emptyDir != null) | tostring")"
  [ -n "$out" ] && [ "$ed" = true ] && pass "$env: grafana-proxy renders its configuration into an emptyDir ($out)" \
    || fail "$env: NGINX_ENVSUBST_OUTPUT_DIR '$out' is on '$vol' (emptyDir: $ed)"
  [ "$(gf grafana-proxy '.env[] | select(.name == "NGINX_ENVSUBST_FILTER") | .value')" = '^GRAFANA_PROXY_KEY$' ] \
    && pass "$env: grafana-proxy substitutes GRAFANA_PROXY_KEY only" || fail "$env: grafana-proxy's NGINX_ENVSUBST_FILTER is wrong"
  c="$(gf grafana-proxy '.command | join(" ")')"
  [[ "$c" == *'GRAFANA_PROXY_KEY'*"exit 1"*"exec /docker-entrypoint.sh nginx"* ]] && [[ "$c" != *'echo "$GRAFANA_PROXY_KEY'* ]] \
    && pass "$env: grafana-proxy checks the key before nginx starts" || fail "$env: grafana-proxy's command is '$c'"
  [[ "$c" == *"nginx -c $out/grafana-proxy.conf "* ]] && pass "$env: nginx runs with the rendered template alone ($out/grafana-proxy.conf)" \
    || fail "$env: grafana-proxy's nginx does not run $out/grafana-proxy.conf: '$c'"
  # The configuration: the dashboards and their provider are Compose's (files/monitoring/grafana, byte copies); the data
  # source is Compose's with the cluster's Prometheus; the sidecar's template is files/grafana-proxy.conf.template
  cm() { q "$f" "select(.kind == \"ConfigMap\" and .metadata.name == \"$1\") | .data[\"$2\"]"; }
  bad=""
  n=0
  for d in "$MONITORING"/grafana/dashboards/*.json; do
    n=$((n + 1))
    [ "$(cm qeos-grafana-dashboards "${d##*/}" | tr -d '\r')" = "$(tr -d '\r' < "$d")" ] || bad="$bad ${d##*/}"
  done
  extra="$(q "$f" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-grafana-dashboards") | .data | keys | length')"
  [ "$n" -gt 0 ] && [ "$extra" = "$n" ] && [ -z "$bad" ] && pass "$env: ConfigMap qeos-grafana-dashboards holds Compose's $n dashboards" \
    || fail "$env: dashboards: $n files, $extra keys, differing:$bad"
  [ "$(cm qeos-grafana-provisioning dashboards.yml)" = "$(tr -d '\r' < "$MONITORING/grafana/provisioning/dashboards/qeos.yml")" ] \
    && pass "$env: the dashboards provider is Compose's" || fail "$env: the dashboards provider differs from Compose's qeos.yml"
  a="$(yq -o json -I0 '.datasources[0] | del(.url)' "$MONITORING/grafana/provisioning/datasources/prometheus.yml" | tr -d '\r')"
  b="$(cm qeos-grafana-provisioning datasources.yml | yq -o json -I0 '.datasources[0] | del(.url)' | tr -d '\r')"
  u="$(cm qeos-grafana-provisioning datasources.yml | yq '.datasources[0].url + " " + (.datasources | length | tostring)' | tr -d '\r')"
  [ -n "$a" ] && [ "$a" = "$b" ] && [ "$u" = "http://qeos-monitoring-prometheus.qeos-monitoring.svc.cluster.local:9090 1" ] \
    && pass "$env: the data source is Compose's (uid prometheus), on the cluster's Prometheus" || fail "$env: the data source is '$b' at '$u'"
  [ "$(cm qeos-grafana-proxy grafana-proxy.conf.template)" = "$(tr -d '\r' < "$CHART/files/grafana-proxy.conf.template")" ] \
    && pass "$env: ConfigMap qeos-grafana-proxy carries files/grafana-proxy.conf.template" || fail "$env: qeos-grafana-proxy differs from the template"
  # Only the gateway reaches it, on the sidecar's port; Prometheus does not scrape it (Compose does not either)
  o="$(outside grafana-ingress)|$(callers grafana-ingress 8080)|$(ports grafana-ingress)"
  [ "$o" = "|gateway|TCP/8080" ] && pass "$env: grafana-ingress admits only the gateway, on the sidecar's 8080" || fail "$env: grafana-ingress is '$o'"
  bad="$(q "$f" '[select(.kind == "Deployment" and .metadata.name == "grafana") | .spec.template.spec.containers[]
    | select(.resources.requests.cpu == null or .resources.requests.memory == null or .resources.limits.cpu == null or .resources.limits.memory == null)
    | .name] | join(" ")')"
  [ -z "$bad" ] && [ "$(gf grafana .resources.limits.memory)" = 256Mi ] \
    && pass "$env: grafana's containers have requests and limits (Grafana's memory: Compose's mem_limit, 256m)" \
    || fail "$env: grafana's resources: missing on '$bad', Grafana's memory limit '$(gf grafana .resources.limits.memory)'"
  # db-init creates qeos_monitor
  v="$(q "$f" 'select(.kind == "Job" and .metadata.name == "qeos-migrate") | .spec.template.spec.initContainers[] | select(.name == "db-init") | .env[] | select(.name == "MONITORING_ENABLED") | .value')"
  [ "$v" = true ] && pass "$env: db-init creates qeos_monitor (MONITORING_ENABLED)" || fail "$env: db-init MONITORING_ENABLED is '$v'"
done
st="$OUT/staging.yaml"
spc() { q "$OUT/$1.yaml" "select(.kind == \"SecretProviderClass\" and .metadata.name == \"$2\") | [.spec.secretObjects[0].data[].key] | join(\" \")"; }
[ "$(spc staging qeos-postgres-exporter)" = monitoring-db-password ] && pass "staging: qeos-postgres-exporter holds monitoring-db-password only" \
  || fail "staging: qeos-postgres-exporter holds '$(spc staging qeos-postgres-exporter)'"
[[ " $(q "$st" 'select(.kind == "SecretProviderClass" and .metadata.name == "qeos-migrate") | .spec.parameters.objects') " == *"objectName: monitoring-db-password"* ]] \
  && pass "staging: the migration hook reads monitoring-db-password" || fail "staging: qeos-migrate lacks monitoring-db-password"
# Grafana: its own SecretProviderClass with the admin password and the sidecar's key, mounted by the pod
[ "$(spc staging qeos-grafana)" = "grafana-admin-password grafana-proxy-key" ] && pass "staging: qeos-grafana holds grafana-admin-password and grafana-proxy-key only" \
  || fail "staging: qeos-grafana holds '$(spc staging qeos-grafana)'"
v="$(q "$st" 'select(.kind == "Deployment" and .metadata.name == "grafana") | .spec.template.spec | .serviceAccountName + " " + ([.volumes[] | select(.csi) | .csi.volumeAttributes.secretProviderClass] | join(","))')"
[ "$v" = "qeos-services qeos-grafana" ] && pass "staging: grafana runs as qeos-services and mounts qeos-grafana" || fail "staging: grafana's account and CSI volume are '$v'"
# Staging's vault holds no webhook and no SMTP login yet (keyvault.absent): Alertmanager mounts nothing; once it has them
# (staging-email treats every optional key but tm-secrets-key as present) its own SecretProviderClass holds exactly those
n="$(q "$st" '[select(.kind == "SecretProviderClass" and .metadata.name == "qeos-alertmanager")] | length')/$(q "$st" '[select(.kind == "Deployment" and .metadata.name == "alertmanager") | .spec.template.spec.volumes[] | select(.csi)] | length')"
[ "$n" = 0/0 ] && pass "staging: no Alertmanager secret in the vault, no SecretProviderClass and no CSI volume" || fail "staging: Alertmanager SPC/CSI is $n"
[ "$(spc staging-email qeos-alertmanager)" = "alert-slack-webhook-url alert-teams-webhook-url smtp-password smtp-user" ] \
  && pass "staging (email): qeos-alertmanager holds the webhooks and the SMTP login only" || fail "staging (email): qeos-alertmanager holds '$(spc staging-email qeos-alertmanager)'"
v="$(q "$OUT/staging-email.yaml" 'select(.kind == "Deployment" and .metadata.name == "alertmanager") | .spec.template.spec.initContainers[0].env[] | select(.name == "SMTP_HOST") | .value')"
[ "$v" = smtp.azurecomm.net ] && pass "staging (email): Alertmanager sends through smtp.host" || fail "staging (email): Alertmanager's SMTP_HOST is '$v'"
# Monitoring off: none of it, and db-init leaves qeos_monitor alone
f="$OUT/ci-off.yaml"
n="$(q "$f" '[select(.kind == "ServiceMonitor" or .kind == "PrometheusRule" or (.metadata.name // "" | test("alertmanager|postgres-exporter|grafana")))] | length')"
[ "$n" = 0 ] && pass "ci-off: monitoring off renders no ServiceMonitor, PrometheusRule, Alertmanager, postgres-exporter or Grafana" || fail "ci-off: $n monitoring objects rendered"
v="$(q "$f" '[select(.kind == "Job" and .metadata.name == "qeos-migrate") | .spec.template.spec.initContainers[] | select(.name == "db-init") | (.env[] | select(.name == "MONITORING_ENABLED") | .value), (.volumeMounts[] | select(.mountPath == "/mnt/secrets/monitoring-db-password") | .mountPath)] | join(" ")')"
[ "$v" = false ] && pass "ci-off: db-init neither creates qeos_monitor nor sees its password" || fail "ci-off: db-init has '$v'"
n="$(q "$f" '[select(.kind == "Service") | select(.metadata.labels["qeos.io/metrics-job"] != null)] | length')"
[ "$n" = 0 ] && pass "ci-off: no Service carries qeos.io/metrics-job" || fail "ci-off: $n Services carry qeos.io/metrics-job"
# Monitoring on without kube-prometheus-stack's CRDs: a clear failure, not a half-applied release (Review Focus 2)
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" >/dev/null 2>"$OUT/nocrds.err"; then
  fail "monitoring on renders without the ServiceMonitor CRD"
else
  grep -q "deploy/monitoring/install.sh" "$OUT/nocrds.err" && pass "monitoring on without the CRDs fails naming deploy/monitoring/install.sh" \
    || fail "without the CRDs it fails for another reason: $(tail -n 2 "$OUT/nocrds.err")"
fi
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" --api-versions monitoring.coreos.com/v1/ServiceMonitor >/dev/null 2>"$OUT/norules.err"; then
  fail "monitoring on renders without the PrometheusRule CRD"
else
  grep -q "deploy/monitoring/install.sh" "$OUT/norules.err" && pass "monitoring on without the PrometheusRule CRD fails naming deploy/monitoring/install.sh" \
    || fail "without PrometheusRule it fails for another reason: $(tail -n 2 "$OUT/norules.err")"
fi
# monitoring-db-password is required with monitoring on: listed as absent, the render stops naming it
if helm template qeos "$CHART" -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}" \
    --set 'keyvault.absent={tm-secrets-key,smtp-user,smtp-password,monitoring-db-password}' >/dev/null 2>"$OUT/nomonpw.err"; then
  fail "monitoring-db-password in keyvault.absent renders (postgres-exporter could never start)"
else
  grep -q "monitoring-db-password" "$OUT/nomonpw.err" && pass "monitoring-db-password in keyvault.absent is refused" \
    || fail "absent monitoring-db-password failed for another reason: $(tail -n 2 "$OUT/nomonpw.err")"
fi
# So is grafana-admin-password (Grafana refuses to start without it)
if helm template qeos "$CHART" -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" "${CRDS[@]}" \
    --set 'keyvault.absent={tm-secrets-key,smtp-user,smtp-password,grafana-admin-password}' >/dev/null 2>"$OUT/nogfpw.err"; then
  fail "grafana-admin-password in keyvault.absent renders (Grafana could never start)"
else
  grep -q "grafana-admin-password is required" "$OUT/nogfpw.err" && pass "grafana-admin-password in keyvault.absent is refused" \
    || fail "absent grafana-admin-password failed for another reason: $(tail -n 2 "$OUT/nogfpw.err")"
fi
# monitoring.prometheusUrl replaces the data source's URL
render ci-promurl -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set monitoring.prometheusUrl=http://prom.example:9090
u="$(q "$OUT/ci-promurl.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-grafana-provisioning") | .data["datasources.yml"]' | yq '.datasources[0].url' | tr -d '\r')"
[ "$u" = http://prom.example:9090 ] && pass "monitoring.prometheusUrl is Grafana's data source" || fail "monitoring.prometheusUrl gives '$u'"
# Grafana's checksum/config covers the data source, the dashboard provider and the sidecar's template: a change to any
# of them restarts the pod (a copy of the chart with one file changed at a time)
gfsum() { q "$1" 'select(.kind == "Deployment" and .metadata.name == "grafana") | .spec.template.metadata.annotations["checksum/config"]'; }
base="$(gfsum "$OUT/ci.yaml")"
bad=""
for changed in files/monitoring/grafana/provisioning/dashboards/qeos.yml files/grafana-proxy.conf.template; do
  rm -rf "$OUT/chartcopy" && cp -r "$CHART" "$OUT/chartcopy" && printf '# changed\n' >> "$OUT/chartcopy/$changed"
  helm template qeos "$OUT/chartcopy" --namespace "$NAMESPACE" -f "$CHART/values-ci.yaml" "${CRDS[@]}" > "$OUT/sum.yaml" 2>/dev/null
  s="$(gfsum "$OUT/sum.yaml")"
  { [ -n "$s" ] && [ "$s" != "$base" ]; } || bad="$bad $changed"
done
s="$(gfsum "$OUT/ci-promurl.yaml")"
{ [ -n "$s" ] && [ "$s" != "$base" ]; } || bad="$bad prometheusUrl"
[ -n "$base" ] && [ -z "$bad" ] && pass "grafana's checksum/config changes with the provider, the proxy template and the data source" \
  || fail "grafana's checksum/config ignores:$bad"
# The threshold: a number of GB, as Compose's entrypoint.sh takes it
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set monitoring.postgresDbSizeAlertGb=abc >/dev/null 2>"$OUT/gb.err"; then
  fail "monitoring.postgresDbSizeAlertGb=abc renders"
else
  grep -q "postgresDbSizeAlertGb" "$OUT/gb.err" && pass "monitoring.postgresDbSizeAlertGb must be a number" \
    || fail "postgresDbSizeAlertGb=abc failed for another reason: $(tail -n 2 "$OUT/gb.err")"
fi
render ci-tuned -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set monitoring.postgresDbSizeAlertGb=35.5 --set 'monitoring.skipRuleGroups=null' \
  --set monitoring.alertEmailTo=ops@example.com
f="$OUT/ci-tuned.yaml"
t="$(q "$f" 'select(.kind == "PrometheusRule") | .spec.groups[] | select(.name == "qeos-thresholds") | .rules[0].expr')"
[ "$t" = "vector(35.5 * 1e9)" ] && pass "monitoring.postgresDbSizeAlertGb sets the threshold" || fail "postgresDbSizeAlertGb=35.5 gives '$t'"
n="$(q "$f" '[select(.kind == "PrometheusRule") | .spec.groups[] | select(.name == "qeos-host")] | length')"
[ "$n" = 1 ] && pass "monitoring.skipRuleGroups empty keeps qeos-host" || fail "skipRuleGroups empty: $n qeos-host groups"
# 8: with no API left to qeos-apis (each honours its labels, or has no metricsJob) the ServiceMonitor is left out, not
# rendered with an empty In list
render ci-noapis -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set services.auth-service.metricsJob=null \
  --set services.organization-service.metricsJob=null --set services.project-service.metricsJob=null \
  --set services.test-management-service.metricsHonorLabels=true
got="$(q "$OUT/ci-noapis.yaml" '[select(.kind == "ServiceMonitor") | .metadata.name] | sort | join(" ")')"
[ "$got" = "qeos-alertmanager qeos-ingestion qeos-postgres qeos-test-management" ] \
  && pass "no plain API left: no qeos-apis ServiceMonitor (never an empty In list)" || fail "ServiceMonitors without plain APIs: '$got'"
# 1+3: values-staging.yaml alone leaves monitoring off until Task 7
v="$(yq '.monitoring.enabled' "$CHART/values-staging.yaml" | tr -d '\r')"
[ "$v" = false ] && pass "values-staging.yaml keeps monitoring off (Task 7 turns it on)" || fail "values-staging.yaml's monitoring.enabled is '$v'"
v="$(q "$f" 'select(.kind == "Deployment" and .metadata.name == "alertmanager") | .spec.template.spec.initContainers[0].env[] | select(.name == "ALERT_EMAIL_TO") | .value')"
[ "$v" = ops@example.com ] && pass "monitoring.alertEmailTo is Alertmanager's ALERT_EMAIL_TO" || fail "ALERT_EMAIL_TO is '$v'"
# The CI server is Flexible Server's equivalent for monitoring too: pg_stat_statements preloaded and allowed, and an
# admin that may grant pg_monitor
pgargs="$(q "$OUT/ci.yaml" 'select(.kind == "Deployment" and .metadata.name == "postgres") | .spec.template.spec.containers[0].args | join(" ")')"
[[ "$pgargs" == *"shared_preload_libraries=pg_stat_statements"* ]] && pass "ci: the in-cluster server preloads pg_stat_statements" \
  || fail "ci: the in-cluster server's args are '$pgargs'"
init="$(q "$OUT/ci.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "postgres-init") | .data["ci-postgres-init.sh"]')"
[[ "$init" == *"GRANT pg_monitor TO :\"admin\" WITH ADMIN OPTION"* && "$init" == *"CREATE EXTENSION IF NOT EXISTS pg_stat_statements"* ]] \
  && pass "ci: the init script lets the admin grant pg_monitor and creates pg_stat_statements" || fail "ci: the init script lacks the pg_monitor grant or the extension"

# A loop job may wait only for a service its urls name: its NetworkPolicy admits it nowhere else
if helm template qeos "$CHART" -f "$CHART/values-ci.yaml" "${CRDS[@]}" --set 'services.weekly-summary.waitFor={auth-service}' >/dev/null 2>"$OUT/waitfor.err"; then
  fail "a waitFor service outside the job's urls renders (the job would wait for ever)"
else
  grep -q "waitFor names auth-service" "$OUT/waitfor.err" && pass "a waitFor service outside the job's urls is refused" \
    || fail "waitFor auth-service failed for another reason: $(tail -n 2 "$OUT/waitfor.err")"
fi

# ---- Review Focus 3: none of the CI dummy secrets reaches any rendered manifest ----
mapfile -t dummies < <(yq '.ciSecrets | to_entries | .[].value' "$CHART/values-ci.yaml" | tr -d '\r')
if [ "${#dummies[@]}" -lt 5 ]; then
  fail "values-ci.yaml lists ${#dummies[@]} dummy secrets under ciSecrets; expected every key"
fi
leaks=0
for secret in "${dummies[@]}"; do
  [ -n "$secret" ] || continue
  for env in ci staging; do
    if grep -qF -- "$secret" "$OUT/$env.yaml"; then
      fail "$env: the rendered output contains the dummy secret '$secret'"
      leaks=$((leaks + 1))
    fi
  done
done
[ "$leaks" = 0 ] && [ "${#dummies[@]}" -ge 5 ] && pass "no dummy secret in any rendered manifest (${#dummies[@]} checked)"

# RENDER_OUT=DIR keeps the rendered manifests (CI's helm-kind job checks the edge against Gateway API's CRDs)
if [ -n "${RENDER_OUT:-}" ]; then
  mkdir -p "$RENDER_OUT" && cp "$OUT"/*.yaml "$RENDER_OUT"/
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures chart check(s) failed"
  exit 1
fi
echo "all chart checks passed"
