#!/usr/bin/env bash
# install.sh -- the cluster's kube-prometheus-stack (release qeos-monitoring), which the QEOS chart's ServiceMonitors,
# rules and Grafana rely on (ADR-038, deploy/monitoring/README.md). It needs CRDs and cluster roles, which the deploy
# identity cannot create, so a cluster admin runs it once per cluster and after every version bump; CI's kind job runs
# it too.
#
# Usage: bash deploy/monitoring/install.sh --env ci|staging|production --context <kubectl context>
#          [--qeos-namespace <name>] [--namespace <name>] [--enforce-restricted] [--allow-downgrade] [--template]
# --context names the cluster: every kubectl and helm call uses it, never the current context, and it is printed with
# its API server before anything changes.
# It creates or labels both namespaces for Pod Security: the monitoring namespace (--namespace, default
# qeos-monitoring) privileged, for node-exporter; the QEOS namespace (--qeos-namespace, default qeos) enforce baseline,
# warn and audit restricted, or enforce restricted with --enforce-restricted. A QEOS namespace that already enforces
# restricted is not lowered to baseline unless --allow-downgrade is given. Then it applies the pinned chart's CRDs
# server side (Helm never upgrades CRDs) and runs helm upgrade --install. --template prints what would be installed
# (helm template) and touches no cluster (no --context needed).
# Needs: helm 3, kubectl signed in as a cluster admin (not with --template), sha256sum or shasum, network access to the
# chart repository.
# Exit status: 0 when installed (or rendered), 1 when a step failed, 2 for a usage error.
set -euo pipefail

usage="usage: install.sh --env ci|staging|production --context <kubectl context> [--qeos-namespace <name>] [--namespace <name>] [--enforce-restricted] [--allow-downgrade] [--template]"
die_usage() { echo "install.sh: $1" >&2; echo "$usage" >&2; exit 2; }
die() { echo "install.sh: $1" >&2; exit 1; }
env=""
context=""
qeos_namespace=qeos
namespace=qeos-monitoring
enforce=baseline
template=""
allow_downgrade=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env) [ "$#" -ge 2 ] || die_usage "--env needs a value"; env="$2"; shift ;;
    --context) [ "$#" -ge 2 ] || die_usage "--context needs a value"; context="$2"; shift ;;
    --qeos-namespace) [ "$#" -ge 2 ] || die_usage "--qeos-namespace needs a value"; qeos_namespace="$2"; shift ;;
    --namespace) [ "$#" -ge 2 ] || die_usage "--namespace needs a value"; namespace="$2"; shift ;;
    --enforce-restricted) enforce=restricted ;;
    --template) template=1 ;;
    --allow-downgrade) allow_downgrade=1 ;;
    *) die_usage "unknown option $1" ;;
  esac
  shift
done
[ -n "$env" ] || die_usage "--env is required"
case "$env" in
  ci|staging|production) ;;
  *) die_usage "unknown environment '$env' (ci, staging or production)" ;;
esac
# A Kubernetes namespace is a DNS label: lowercase letters, digits and '-', starting and ending with one of the first
# two, 1 to 63 characters
for ns in "$qeos_namespace" "$namespace"; do
  [[ "$ns" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || die_usage "not a Kubernetes namespace name: '$ns'"
done
[ "$qeos_namespace" != "$namespace" ] \
  || die_usage "--qeos-namespace and --namespace must differ (Pod Security: restricted QEOS, privileged node-exporter)"
# Never the current context: an admin signed in to another cluster would change that one
if [ -z "$template" ]; then
  [ -n "$context" ] || die_usage "--context is required (the kubectl context of the cluster to install into)"
  [[ "$context" =~ ^[A-Za-z0-9][A-Za-z0-9._:@/-]*$ ]] || die_usage "not a kubectl context name: '$context'"
fi
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_values="$dir/values-$env.yaml"
if [ ! -f "$env_values" ]; then
  [ "$env" != production ] || die_usage "production arrives in Stage 3: there is no values-production.yaml yet"
  die_usage "no values file for $env: $env_values"
fi

command -v helm >/dev/null || die "helm is not on PATH"
if [ -z "$template" ]; then
  command -v kubectl >/dev/null || die "kubectl is not on PATH"
  kubectl config get-contexts "$context" >/dev/null 2>&1 || die "no kubectl context '$context' (kubectl config get-contexts)"
  kc=(kubectl --context "$context")
  server="$("${kc[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
  echo "context: $context" >&2
  echo "API server: $server" >&2
  echo "monitoring namespace: $namespace (Pod Security privileged); QEOS namespace: $qeos_namespace (enforce $enforce)" >&2
  # Pod Security is never lowered by accident: a re-run without --enforce-restricted on a restricted namespace
  current="$("${kc[@]}" get namespace "$qeos_namespace" --ignore-not-found \
    -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}')"
  if [ "$current" = restricted ] && [ "$enforce" != restricted ] && [ -z "$allow_downgrade" ]; then
    die "$qeos_namespace enforces Pod Security restricted; pass --enforce-restricted to keep it, or --allow-downgrade to lower it to $enforce"
  fi
fi
if command -v sha256sum >/dev/null; then
  sha256() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null; then
  sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  die "neither sha256sum nor shasum is on PATH"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ---- the pinned chart: Chart.yaml's dependency (version and repository) and its sha256 annotation. sed, not yq,
# which admins need not have: the dependency's are the only indented version and repository keys. Exactly one of
# each, or nothing is installed (tests/install_test.sh) ----
chart_value() {
  sed -n "s/^[[:space:]][[:space:]]*-\{0,1\}[[:space:]]*$1:[[:space:]]*[\"']\{0,1\}\([^\"'[:space:]]*\).*/\1/p" "$dir/Chart.yaml"
}
version="$(chart_value version)"
repository="$(chart_value repository)"
want_sha="$(chart_value 'qeos\.atriis\.com\/kube-prometheus-stack-sha256')"
for value in "$version" "$repository" "$want_sha"; do
  if [ -z "$value" ] || [ "$(printf '%s\n' "$value" | wc -l)" -ne 1 ]; then
    die "$dir/Chart.yaml: expected one dependency version, one repository and the sha256 annotation; got version '$version', repository '$repository', sha256 '$want_sha'"
  fi
done
# A repository configuration of its own: the admin's helm repositories are neither read nor changed
export HELM_REPOSITORY_CONFIG="$tmp/repositories.yaml" HELM_REPOSITORY_CACHE="$tmp/repository-cache"
echo "kube-prometheus-stack $version from $repository" >&2
helm repo add prometheus-community "$repository" >&2
helm dependency build "$dir" >&2
archive="$dir/charts/kube-prometheus-stack-$version.tgz"
[ -f "$archive" ] || die "helm dependency build left no $archive"
got_sha="$(sha256 "$archive")"
[ "$got_sha" = "$want_sha" ] \
  || die "$archive has sha256 $got_sha, Chart.yaml pins $want_sha: not the archive this repository was tested with (deploy/monitoring/README.md, \"Bumping the version\")"

# ---- what depends on the namespaces ----
cat >"$tmp/namespaces.yaml" <<EOF
kube-prometheus-stack:
  qeosNamespace: $qeos_namespace
  prometheus:
    prometheusSpec:
      # The QEOS chart's Alertmanager
      alertingEndpoints:
        - namespace: $qeos_namespace
          name: alertmanager
          port: http
          apiVersion: v2
      ruleNamespaceSelector:
        matchExpressions:
          - {key: kubernetes.io/metadata.name, operator: In, values: [$qeos_namespace, $namespace]}
      serviceMonitorNamespaceSelector:
        matchExpressions:
          - {key: kubernetes.io/metadata.name, operator: In, values: [$qeos_namespace, $namespace]}
      podMonitorNamespaceSelector:
        matchExpressions:
          - {key: kubernetes.io/metadata.name, operator: In, values: [$qeos_namespace, $namespace]}
      # This release's own rules and ServiceMonitors describe the whole cluster: their namespace label stays
      excludedFromEnforcement:
        - {group: monitoring.coreos.com, resource: prometheusrules, namespace: $namespace}
        - {group: monitoring.coreos.com, resource: servicemonitors, namespace: $namespace}
EOF
values=(-f "$dir/values.yaml" -f "$env_values" -f "$tmp/namespaces.yaml")

if [ -n "$template" ]; then
  helm template qeos-monitoring "$dir" --namespace "$namespace" "${values[@]}"
  exit 0
fi

# ---- namespaces and Pod Security ----
for ns in "$namespace" "$qeos_namespace"; do
  "${kc[@]}" create namespace "$ns" --dry-run=client -o yaml | "${kc[@]}" apply -f -
done
"${kc[@]}" label namespace "$namespace" --overwrite pod-security.kubernetes.io/enforce=privileged
"${kc[@]}" label namespace "$qeos_namespace" --overwrite pod-security.kubernetes.io/enforce="$enforce" \
  pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/audit=restricted

# ---- CRDs: from the verified archive, server side (they exceed the client-side apply annotation's size); conflicts
# forced, as an earlier install's field manager (helm's, on a cluster where helm installed them) owns their fields ----
tar -xzf "$archive" -C "$tmp" kube-prometheus-stack/charts/crds/crds
"${kc[@]}" apply --server-side --force-conflicts -f "$tmp/kube-prometheus-stack/charts/crds/crds"
"${kc[@]}" wait --for condition=Established --timeout 120s -f "$tmp/kube-prometheus-stack/charts/crds/crds"

# ---- the release ----
helm upgrade --install qeos-monitoring "$dir" --kube-context "$context" --namespace "$namespace" "${values[@]}" --skip-crds \
  --atomic --wait --timeout 10m
# helm's --wait ends before the operator has started Prometheus itself
"${kc[@]}" -n "$namespace" wait --for condition=Available --timeout 5m prometheus/qeos-monitoring-prometheus
"${kc[@]}" -n "$namespace" get prometheus
