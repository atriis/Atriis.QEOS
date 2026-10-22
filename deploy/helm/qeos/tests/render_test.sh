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
)
# Compose settings the chart replaces on purpose: DATABASE_URL by POSTGRES_* (the password URL-escaped by the settings),
# GATEWAY_HTTPS_PORT by GATEWAY_PUBLIC_PORT (TLS ends at the edge). Anything else Compose sets must be set here too
COMPOSE_ONLY="DATABASE_URL GATEWAY_HTTPS_PORT"
COMPOSE="$CHART/../../../docker-compose.yml"

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
# Once the ACS SMTP application exists, its secrets are in the vault and keyvault.absent drops them
render staging-email -f "$CHART/values-staging.yaml" "${STAGING_SET[@]}" --set 'keyvault.absent={tm-secrets-key}'
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
  want="/mnt/secrets/auth-db-password /mnt/secrets/ingestion-db-password /mnt/secrets/organization-db-password /mnt/secrets/postgres-admin-password /mnt/secrets/project-db-password /mnt/secrets/testmgmt-db-password"
  [ "$(mounts db-init)" = "$want" ] && pass "$env: db-init sees the admin and role passwords only" || fail "$env: db-init mounts '$(mounts db-init)'"
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

# ---- environment-specific choices ----
backend() { q "$OUT/$1.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-ingestion-service-env") | .data.ARTIFACTS_BACKEND'; }
[ "$(backend ci)" = s3 ] && pass "ci: artifacts on S3 (MinIO)" || fail "ci: ARTIFACTS_BACKEND is '$(backend ci)'"
[ "$(backend staging)" = azure ] && pass "staging: artifacts on Azure Blob" || fail "staging: ARTIFACTS_BACKEND is '$(backend staging)'"
np() { q "$OUT/$1.yaml" '[select(.kind == "NetworkPolicy")] | length'; }
[ "$(np ci)" = 0 ] && pass "ci: no NetworkPolicy (kind does not enforce them)" || fail "ci: $(np ci) NetworkPolicy rendered"
# The add-on runs the Gateway's proxy pods in the Gateway's namespace, labelled by Istio's gateway template
src="$(q "$OUT/staging.yaml" 'select(.kind == "NetworkPolicy" and .metadata.name == "gateway-ingress") | .spec.ingress as $i
  | ($i | length | tostring) + " " + ($i[0].from | length | tostring) + " "
    + $i[0].from[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"] + " "
    + ($i[0].from[0].podSelector.matchLabels | to_entries | map(.key + "=" + .value) | sort | join(","))')"
[ "$src" = "1 1 $NAMESPACE gateway.networking.k8s.io/gateway-class-name=approuting-istio,gateway.networking.k8s.io/gateway-name=qeos-edge" ] \
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
c="$(q "$st" 'select(.kind == "Certificate") | .spec.secretName + " " + .spec.issuerRef.kind + "/" + .spec.issuerRef.name')"
[ "$c" = "qeos-edge-tls Issuer/qeos-letsencrypt" ] && pass "staging: Certificate from the namespaced Issuer into qeos-edge-tls" \
  || fail "staging: Certificate is '$c'"
i="$(q "$st" 'select(.kind == "Issuer") | .spec.acme | .server + " " + .solvers[0].http01.gatewayHTTPRoute.parentRefs[0].name + "/" + .solvers[0].http01.gatewayHTTPRoute.parentRefs[0].sectionName')"
[ "$i" = "https://acme-v02.api.letsencrypt.org/directory qeos-edge/http" ] && pass "staging: Let's Encrypt HTTP-01 through the Gateway's http listener" \
  || fail "staging: Issuer is '$i'"
# The deploy identity administers the namespace only: nothing cluster-scoped, nothing aimed at another namespace
for env in ci staging; do
  bad="$(q "$OUT/$env.yaml" '[select(.kind != null) | select((.kind | test("^(Deployment|Service|ConfigMap|ServiceAccount|Job|PodDisruptionBudget|NetworkPolicy|SecretProviderClass|Gateway|HTTPRoute|Issuer|Certificate)$") | not)
    or (.metadata.namespace // "") != "") | .kind + "/" + .metadata.name] | join(" ")')"
  [ -z "$bad" ] && pass "$env: only namespaced kinds, none with a namespace of its own" || fail "$env: cluster-scoped or foreign: $bad"
done
smtp() { q "$OUT/$1.yaml" 'select(.kind == "ConfigMap" and .metadata.name == "qeos-auth-service-env") | .data.SMTP_HOST + " " + .data.SMTP_PORT + " " + .data.SMTP_TLS'; }
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
# kind's images are tagged :kind, never Compose's :local: a local kind build must not replace the dev stack's images
bad="$(q "$OUT/ci.yaml" '[.spec.template.spec | (.containers // []) + (.initContainers // []) | .[].image | select(test("^qeos/") and (test(":kind$") | not))] | unique | join(",")' | tr -d "[:space:]")"
[ -z "$bad" ] && pass "ci: every qeos/ image is tagged :kind" || fail "ci: images not tagged :kind: $bad"

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
