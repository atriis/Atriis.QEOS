#!/usr/bin/env bash
# init-secrets.sh -- the Key Vault secrets Bicep does not write (ADR-038, deploy/azure/README.md). Generates each
# missing one once, with a random value, and never changes one that exists: rerunning it is safe. With SMTP_PASSWORD
# in the environment it also sets smtp-password (the ACS SMTP application's client secret), replacing any older value.
# Bicep writes postgres-admin-password, and smtp-user once the SMTP application exists.
#
# Usage: KEYVAULT_NAME=<Bicep output keyVaultName> [SMTP_PASSWORD=...] bash deploy/azure/init-secrets.sh
# Needs: az signed in as someone with Key Vault Secrets Officer on the vault, from an address in operatorIpRanges.
set -euo pipefail

: "${KEYVAULT_NAME:?KEYVAULT_NAME is required (the Bicep output keyVaultName)}"

# The keys the chart reads (deploy/helm/README.md, "Secrets"). scripts/tests/test_azure_bicep.py keeps this list, the
# secrets in modules/keyvault.bicep and the chart's keys equal
GENERATED=(
  secret-key
  internal-api-password
  auth-db-password
  organization-db-password
  project-db-password
  ingestion-db-password
  testmgmt-db-password
)

# Values go through a private file, never a command line
umask 077
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# set_secret NAME -- the value is in $workdir/value
set_secret() {
  az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "$1" --file "$workdir/value" --encoding utf-8 \
    --content-type text/plain --output none
}

# One listing up front: a failed lookup (network rule, missing role) stops the script instead of reading as "missing"
# and replacing a secret that exists (pipefail). tr: az on Windows ends its lines with CR
existing="$(az keyvault secret list --vault-name "$KEYVAULT_NAME" --query '[].name' --output tsv | tr -d '\r')"

for name in "${GENERATED[@]}"; do
  if grep -qxF "$name" <<< "$existing"; then
    echo "init-secrets: $name exists, kept"
    continue
  fi
  # 32 random bytes as hex: no character that needs escaping in a URL, a shell or SQL
  openssl rand -hex 32 | tr -d '\n' > "$workdir/value"
  set_secret "$name"
  echo "init-secrets: $name created"
done

if [ -n "${SMTP_PASSWORD:-}" ]; then
  printf '%s' "$SMTP_PASSWORD" > "$workdir/value"
  set_secret smtp-password
  echo "init-secrets: smtp-password set"
fi
