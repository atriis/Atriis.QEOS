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

# The Azure values arrive from Bicep's outputs with --set in the deploy workflow (Task 10); placeholders here
STAGING_SET=(
  --set image.registry=example.azurecr.io --set image.tag=0123abc
  --set keyvault.name=kv-placeholder --set keyvault.tenantId=00000000-0000-0000-0000-000000000000
  --set keyvault.clientIds.services=11111111-1111-1111-1111-111111111111
  --set keyvault.clientIds.ingestion=22222222-2222-2222-2222-222222222222
  --set keyvault.clientIds.ingestion-retention=33333333-3333-3333-3333-333333333333
  --set keyvault.clientIds.migrate=44444444-4444-4444-4444-444444444444
  --set postgres.host=pg-placeholder.postgres.database.azure.com
  --set artifacts.azure.accountUrl=https://placeholder.blob.core.windows.net
)

# ---- lint and render ----
if helm lint "$CHART" -f "$CHART/values-ci.yaml" >"$OUT/lint-ci.txt" 2>&1; then
  pass "helm lint (values-ci.yaml)"
else
  fail "helm lint (values-ci.yaml): $(tail -n 5 "$OUT/lint-ci.txt")"
fi
if helm lint "$CHART" -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" >"$OUT/lint-staging.txt" 2>&1; then
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
render ci -f "$CHART/values-ci.yaml"
render staging -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}"
# values.yaml alone holds no environment: a render must stop on the settings each environment has to give
if helm template qeos "$CHART" --namespace "$NAMESPACE" >/dev/null 2>"$OUT/defaults.err"; then
  fail "values.yaml alone renders: the required settings are not enforced"
else
  grep -q 'is required' "$OUT/defaults.err" && pass "values.yaml alone refuses to render: $(grep -o '[a-zA-Z.-]* is required' "$OUT/defaults.err" | head -n 1)" \
    || fail "values.yaml alone fails for another reason: $(tail -n 3 "$OUT/defaults.err")"
fi

# q FILE EXPR -- yq over every document of a rendered file
q() { yq ea "$2" "$1"; }

APIS="auth-service organization-service project-service ingestion-service test-management-service"
WEB="dashboard gateway"
LOOPS="ingestion-retention analytics-rollup impact-rollup weekly-summary"

for env in ci staging; do
  f="$OUT/$env.yaml"
  [ -s "$f" ] || continue

  # ---- security context on every container, init containers included ----
  bad="$(q "$f" '[select(.kind == "Deployment" or .kind == "Job") | .spec.template.spec as $s
    | (($s.containers // []) + ($s.initContainers // []))[]
    | select(.securityContext.runAsNonRoot != true or .securityContext.readOnlyRootFilesystem != true
        or .securityContext.allowPrivilegeEscalation != false
        or ((.securityContext.capabilities.drop // []) | contains(["ALL"]) | not))
    | .name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: every container is non-root, read-only, no escalation, no capabilities" \
    || fail "$env: containers without the required securityContext: $bad"
  count="$(q "$f" '[select(.kind == "Deployment" or .kind == "Job")] | length')"
  [ "$count" -gt 0 ] || fail "$env: no Deployment or Job rendered"

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

  # ---- probes, grace period, preStop, spread on every long-running workload ----
  bad="$(q "$f" '[select(.kind == "Deployment" and .metadata.labels["app.kubernetes.io/part-of"] == "qeos")
    | select(.spec.template.spec.terminationGracePeriodSeconds != 30
        or (.spec.template.spec.topologySpreadConstraints[0].topologyKey // "") != "kubernetes.io/hostname"
        or (.spec.template.spec.containers[0].lifecycle.preStop.exec.command | join(" ")) != "sleep 5")
    | .metadata.name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: grace period 30 s, preStop sleep 5 and hostname spread everywhere" || fail "$env: missing on: $bad"
  for name in $APIS $WEB; do
    p="$(q "$f" "select(.kind == \"Deployment\" and .metadata.name == \"$name\") | .spec.template.spec.containers[0] | .readinessProbe.httpGet.path + \" \" + .livenessProbe.httpGet.path")"
    [ "$p" = "/health /health" ] && pass "$env: $name probes /health" || fail "$env: $name probes '$p'"
  done

  # ---- the gateway's Kubernetes settings ----
  gw() { q "$f" "select(.kind == \"ConfigMap\" and .metadata.name == \"qeos-gateway-env\") | .data.$1"; }
  [ "$(gw UPSTREAM_SUFFIX)" = ".$NAMESPACE.svc.cluster.local" ] && pass "$env: gateway UPSTREAM_SUFFIX follows the namespace" \
    || fail "$env: gateway UPSTREAM_SUFFIX is '$(gw UPSTREAM_SUFFIX)'"
  [ "$(gw GATEWAY_TLS)|$(gw GATEWAY_PUBLIC_PORT)|$(gw GATEWAY_RESOLVER)|$(gw MONITORING_ENABLED)" \
    = "off|443|kube-dns.kube-system.svc.cluster.local|false" ] && pass "$env: gateway TLS off, port 443, cluster DNS, monitoring off" \
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

# ---- environment-specific choices ----
backend() { q "$OUT/$1.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-ingestion-service-env") | .data.ARTIFACTS_BACKEND'; }
[ "$(backend ci)" = s3 ] && pass "ci: artifacts on S3 (MinIO)" || fail "ci: ARTIFACTS_BACKEND is '$(backend ci)'"
[ "$(backend staging)" = azure ] && pass "staging: artifacts on Azure Blob" || fail "staging: ARTIFACTS_BACKEND is '$(backend staging)'"
np() { q "$OUT/$1.yaml" '[select(.kind == "NetworkPolicy")] | length'; }
[ "$(np ci)" = 0 ] && pass "ci: no NetworkPolicy (kind does not enforce them)" || fail "ci: $(np ci) NetworkPolicy rendered"
src="$(q "$OUT/staging.yaml" 'select(.kind == "NetworkPolicy" and .metadata.name == "gateway-ingress")
  | .spec.ingress[0].from[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"]')"
[ "$src" = app-routing-system ] && pass "staging: gateway accepts traffic only from the edge's namespace" \
  || fail "staging: gateway-ingress allows '$src'"
spc="$(q "$OUT/staging.yaml" 'select(.kind == "SecretProviderClass" and .metadata.name == "qeos-migrate") | .metadata.annotations["helm.sh/hook-weight"]')"
[ "$spc" = -10 ] && pass "staging: migration SecretProviderClass is a hook at weight -10" || fail "staging: its hook weight is '$spc'"
n="$(q "$OUT/ci.yaml" '[select(.kind == "SecretProviderClass")] | length')"
[ "$n" = 0 ] && pass "ci: no SecretProviderClass (secrets from qeos-secrets)" || fail "ci: $n SecretProviderClass rendered"
n="$(q "$OUT/staging.yaml" '[select(.metadata.labels["app.kubernetes.io/component"] == "ci-backing")] | length')"
[ "$n" = 0 ] && pass "staging: no in-cluster postgres or MinIO" || fail "staging: $n CI backing resources rendered"
n="$(q "$OUT/ci.yaml" '[select(.kind == "Deployment" and (.metadata.name == "postgres" or .metadata.name == "minio"))] | length')"
[ "$n" = 2 ] && pass "ci: in-cluster postgres and MinIO" || fail "ci: $n of postgres/MinIO rendered"

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

if [ "$failures" -gt 0 ]; then
  echo "$failures chart check(s) failed"
  exit 1
fi
echo "all chart checks passed"
