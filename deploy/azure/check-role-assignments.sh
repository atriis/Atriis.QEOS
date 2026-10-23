#!/usr/bin/env bash
# check-role-assignments.sh -- the Azure roles the two GitHub identities hold in an environment's resource group,
# against what Bicep gives them (ADR-038, deploy/azure/README.md section 3.2). Bicep deploys are incremental and never
# delete a role assignment, so a role Bicep stopped giving (the deploy identity's AcrPush before the build identity was
# split off) stays until someone removes it. This lists every assignment of either identity in the resource group and
# flags each one Bicep does not make; with --delete it removes the flagged ones.
#
# Usage: QEOS_BUILD_PRINCIPAL_ID=<object id> QEOS_DEPLOY_PRINCIPAL_ID=<object id> \
#          bash deploy/azure/check-role-assignments.sh <resource group> [--params <file.bicepparam>] [--namespace <name>]
#          [--delete]
# The chart's namespace (where the deploy identity is RBAC Admin) is, first to last: --namespace; the `namespace` of the
# --params file, the parameter file the environment was deployed with; main.bicep's default.
# Needs: az signed in with read access to role assignments (and User Access Administrator or Owner for --delete).
# Exit status: 0 when nothing is stale (or every stale one was deleted), 1 when a stale assignment remains, 2 for a
# usage error.
set -euo pipefail

usage="usage: check-role-assignments.sh <resource group> [--params <file.bicepparam>] [--namespace <name>] [--delete]"
die_usage() { echo "check-role-assignments.sh: $1" >&2; echo "$usage" >&2; exit 2; }
# The resource group comes first: never a run without one, which would judge no assignment at all
[ "$#" -ge 1 ] || die_usage "no resource group"
rg="$1"
shift
case "$rg" in ""|-*) die_usage "the first argument must be the resource group, got '$rg'" ;; esac
namespace=""
params=""
delete=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --delete) delete=--delete ;;
    --namespace) [ "$#" -ge 2 ] || die_usage "--namespace needs a value"; namespace="$2"; shift ;;
    --params) [ "$#" -ge 2 ] || die_usage "--params needs a file"; params="$2"; shift ;;
    *) die_usage "unknown option $1" ;;
  esac
  shift
done

# The namespace: --namespace, else the parameter file's, else main.bicep's default
main_bicep="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/main.bicep"
if [ -n "$namespace" ]; then
  source_of_namespace="--namespace"
else
  if [ -n "$params" ]; then
    [ -f "$params" ] || die_usage "no parameter file $params"
    namespace="$(sed -n "s/^param namespace = '\([^']*\)'.*/\1/p" "$params")"
    source_of_namespace="$params"
  fi
  if [ -z "$namespace" ]; then
    namespace="$(sed -n "s/^param namespace string = '\([^']*\)'.*/\1/p" "$main_bicep")"
    source_of_namespace="main.bicep's default"
  fi
fi
# A Kubernetes namespace is a DNS label: lowercase letters, digits and '-', starting and ending with one of the first
# two, 1 to 63 characters
[[ "$namespace" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
  || die_usage "not a Kubernetes namespace name: '$namespace' (from $source_of_namespace)"
echo "namespace: $namespace (from $source_of_namespace)"
: "${QEOS_BUILD_PRINCIPAL_ID:?QEOS_BUILD_PRINCIPAL_ID is required (the build identity: its service principal object id)}"
: "${QEOS_DEPLOY_PRINCIPAL_ID:?QEOS_DEPLOY_PRINCIPAL_ID is required (the deploy identity: its service principal object id)}"

# expected WHO ROLE SCOPE -- whether Bicep makes this assignment (modules/acr.bicep, modules/aks.bicep). SCOPE is
# matched by the resource it names, case-insensitively, as Azure returns scopes in mixed case
expected() {
  local who="$1" role="$2" scope="${3,,}"
  local acr='/providers/microsoft.containerregistry/registries/[^/]+$'
  local aks='/providers/microsoft.containerservice/managedclusters/[^/]+$'
  local ns="/providers/microsoft.containerservice/managedclusters/[^/]+/namespaces/${namespace}\$"
  case "$who|$role" in
    "build|AcrPush") [[ "$scope" =~ $acr ]] ;;
    "deploy|AcrPull") [[ "$scope" =~ $acr ]] ;;
    "deploy|Azure Kubernetes Service Cluster User Role") [[ "$scope" =~ $aks ]] ;;
    "deploy|Azure Kubernetes Service Contributor Role") [[ "$scope" =~ $aks ]] ;;
    "deploy|Azure Kubernetes Service RBAC Admin") [[ "$scope" =~ $ns ]] ;;
    *) return 1 ;;
  esac
}

stale=0
for who in build deploy; do
  if [ "$who" = build ]; then principal="$QEOS_BUILD_PRINCIPAL_ID"; else principal="$QEOS_DEPLOY_PRINCIPAL_ID"; fi
  # Every assignment of the principal, at any scope; only those inside the resource group are Bicep's to judge
  rows="$(az role assignment list --assignee "$principal" --all \
    --query "[].[id, roleDefinitionName, scope]" -o tsv)"
  while IFS=$'\t' read -r id role scope; do
    [ -n "$id" ] || continue
    [[ "${scope,,}" == */resourcegroups/"${rg,,}"/* ]] || continue
    if expected "$who" "$role" "$scope"; then
      echo "ok     $who  $role  $scope"
    elif [ "$delete" = --delete ]; then
      az role assignment delete --ids "$id"
      echo "DELETED $who  $role  $scope"
    else
      echo "STALE  $who  $role  $scope"
      echo "         remove: az role assignment delete --ids $id"
      stale=$((stale + 1))
    fi
  done <<< "$rows"
done

if [ "$stale" -gt 0 ]; then
  echo "$stale stale role assignment(s): rerun with --delete, or delete each as shown"
  exit 1
fi
echo "no stale role assignment"
