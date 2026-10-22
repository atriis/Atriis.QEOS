#!/usr/bin/env bash
# check-role-assignments.sh -- the Azure roles the two GitHub identities hold in an environment's resource group,
# against what Bicep gives them (ADR-038, deploy/azure/README.md section 3.2). Bicep deploys are incremental and never
# delete a role assignment, so a role Bicep stopped giving (the deploy identity's AcrPush before the build identity was
# split off) stays until someone removes it. This lists every assignment of either identity in the resource group and
# flags each one Bicep does not make; with --delete it removes the flagged ones.
#
# Usage: QEOS_BUILD_PRINCIPAL_ID=<object id> QEOS_DEPLOY_PRINCIPAL_ID=<object id> \
#          bash deploy/azure/check-role-assignments.sh <resource group> [--namespace <name>] [--delete]
# --namespace: the chart's namespace, main.bicep's `namespace` parameter (default qeos)
# Needs: az signed in with read access to role assignments (and User Access Administrator or Owner for --delete).
# Exit status: 0 when nothing is stale (or every stale one was deleted), 1 when a stale assignment remains.
set -euo pipefail

usage="usage: check-role-assignments.sh <resource group> [--namespace <name>] [--delete]"
rg="${1:?$usage}"
shift
namespace=qeos
delete=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --delete) delete=--delete ;;
    --namespace) namespace="${2:?$usage}"; shift ;;
    *) echo "unknown option $1; $usage" >&2; exit 2 ;;
  esac
  shift
done
[[ "$namespace" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { echo "not a namespace name: $namespace" >&2; exit 2; }
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
