#!/usr/bin/env bash
# Writes the production .env at the repository root with strong random secrets.
# Usage (from the repository root):  bash deploy/init-env.sh qeos.example.com ops@example.com
set -euo pipefail
cd "$(dirname "$0")/.."

domain="${1:?usage: deploy/init-env.sh <domain> <acme-email>}"
email="${2:?usage: deploy/init-env.sh <domain> <acme-email>}"

if [ -e .env ]; then
  echo "refusing to overwrite .env: changing SECRET_KEY signs everyone out, and a new"
  echo "POSTGRES_PASSWORD does not match an existing database. Edit it by hand instead."
  exit 1
fi

# Keep only [A-Za-z0-9]: URL-safe, and no stray \r from an openssl that ends lines with CRLF.
# Twice the bytes needed, so the filtering never leaves cut short.
secret() { openssl rand -base64 96 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }

# A Fernet key: 32 random bytes as url-safe base64 (+/ become -_).
tm_key="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\r\n')"

umask 077  # the file holds every secret of the deployment
cat > .env <<EOF
# QEOS production settings (git-ignored). Generated $(date -u +%Y-%m-%dT%H:%MZ).
QEOS_DOMAIN=$domain
ACME_EMAIL=$email
SECRET_KEY=$(secret 64)
INTERNAL_API_PASSWORD=$(secret 40)
POSTGRES_PASSWORD=$(secret 40)
TM_SECRETS_KEY=$tm_key
# Monitoring (Prometheus, Alertmanager, Grafana): uncomment the four lines below to turn it on. Left
# commented, no monitoring database role is created. MONITORING_ENABLED is for the QEOS sign-in to
# Grafana (not built yet). 8 GB RAM recommended. See deploy/README.md section 10.
#COMPOSE_PROFILES=monitoring
#MONITORING_ENABLED=true
#GRAFANA_ADMIN_PASSWORD=$(secret 32)
#MONITORING_DB_PASSWORD=$(secret 40)
EOF
echo "wrote .env for https://$domain (mode 600)"
