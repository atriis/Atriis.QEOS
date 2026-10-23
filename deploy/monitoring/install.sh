#!/usr/bin/env bash
# install.sh -- the cluster's kube-prometheus-stack (release qeos-monitoring), which the QEOS chart's ServiceMonitors,
# rules and Grafana rely on (ADR-038, deploy/monitoring/README.md). It needs CRDs and cluster roles, which the deploy
# identity cannot create, so a cluster admin runs it once per cluster and after every version bump; CI's kind job runs
# it too.
#
# Usage: bash deploy/monitoring/install.sh --env ci|staging|production [--qeos-namespace <name>] [--namespace <name>]
#          [--enforce-restricted] [--template]
# It creates or labels both namespaces for Pod Security: the monitoring namespace (--namespace, default
# qeos-monitoring) privileged, for node-exporter; the QEOS namespace (--qeos-namespace, default qeos) enforce baseline,
# warn and audit restricted, or enforce restricted with --enforce-restricted. Then it applies the pinned chart's CRDs
# server side (Helm never upgrades CRDs) and runs helm upgrade --install. --template prints what would be installed
# (helm template) and touches no cluster.
# Needs: helm 3, kubectl signed in as a cluster admin (not with --template), sha256sum or shasum, network access to the
# chart repository.
# Exit status: 0 when installed (or rendered), 1 when a step failed, 2 for a usage error.
set -euo pipefail

usage="usage: install.sh --env ci|staging|production [--qeos-namespace <name>] [--namespace <name>] [--enforce-restricted] [--template]"
die_usage() { echo "install.sh: $1" >&2; echo "$usage" >&2; exit 2; }
die() { echo "install.sh: $1" >&2; exit 1; }
env=""
qeos_namespace=qeos
namespace=qeos-monitoring
enforce=baseline
template=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env) [ "$#" -ge 2 ] || die_usage "--env needs a value"; env="$2"; shift ;;
    --qeos-namespace) [ "$#" -ge 2 ] || die_usage "--qeos-namespace needs a value"; qeos_namespace="$2"; shift ;;
    --namespace) [ "$#" -ge 2 ] || die_usage "--namespace needs a value"; namespace="$2"; shift ;;
    --enforce-restricted) enforce=restricted ;;
    --template) template=1 ;;
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
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_values="$dir/values-$env.yaml"
# Production has no values file yet (a later stage, like deploy-aks.yml's production)
[ -f "$env_values" ] || die_usage "no values file for $env: $env_values"

command -v helm >/dev/null || die "helm is not on PATH"
[ -n "$template" ] || command -v kubectl >/dev/null || die "kubectl is not on PATH"
if command -v sha256sum >/dev/null; then
  sha256() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null; then
  sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  die "neither sha256sum nor shasum is on PATH"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ---- the pinned chart: Chart.lock's version, from the repository Chart.yaml names, with Chart.yaml's digest ----
version="$(sed -n 's/^    version: *//p' "$dir/Chart.yaml")"
repository="$(sed -n 's/^    repository: *//p' "$dir/Chart.yaml")"
want_sha="$(sed -n 's/^  qeos.atriis.com\/kube-prometheus-stack-sha256: *//p' "$dir/Chart.yaml")"
[ -n "$version" ] && [ -n "$repository" ] && [ -n "$want_sha" ] \
  || die "$dir/Chart.yaml lacks the dependency's version or repository, or the sha256 annotation"
# A repository configuration of its own: the admin's helm repositories are neither read nor changed
export HELM_REPOSITORY_CONFIG="$tmp/repositories.yaml" HELM_REPOSITORY_CACHE="$tmp/repository-cache"
echo "kube-prometheus-stack $version from $repository" >&2
helm repo add prometheus-community "$repository" >&2
helm dependency build "$dir" >&2
archive="$dir/charts/kube-prometheus-stack-$version.tgz"
[ -f "$archive" ] || die "helm dependency build left no $archive"
got_sha="$(sha256 "$archive")"
[ "$got_sha" = "$want_sha" ] \
  || die "$archive has sha256 $got_sha, Chart.yaml pins $want_sha: not the archive this repository was tested with"

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
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done
kubectl label namespace "$namespace" --overwrite pod-security.kubernetes.io/enforce=privileged
kubectl label namespace "$qeos_namespace" --overwrite pod-security.kubernetes.io/enforce="$enforce" \
  pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/audit=restricted

# ---- CRDs: from the verified archive, server side (they exceed the client-side apply annotation's size); conflicts
# forced, as an earlier install's field manager (helm's, on a cluster where helm installed them) owns their fields ----
tar -xzf "$archive" -C "$tmp" kube-prometheus-stack/charts/crds/crds
kubectl apply --server-side --force-conflicts -f "$tmp/kube-prometheus-stack/charts/crds/crds"
kubectl wait --for condition=Established --timeout 120s -f "$tmp/kube-prometheus-stack/charts/crds/crds"

# ---- the release ----
helm upgrade --install qeos-monitoring "$dir" --namespace "$namespace" "${values[@]}" --skip-crds \
  --atomic --wait --timeout 10m
# helm's --wait ends before the operator has started Prometheus itself
kubectl -n "$namespace" wait --for condition=Available --timeout 5m prometheus/qeos-monitoring-prometheus
kubectl -n "$namespace" get prometheus
