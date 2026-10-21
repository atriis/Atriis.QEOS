#!/bin/sh
# migrate.sh <db> -- one step of the migration hook (ADR-038): `alembic upgrade head` in a service's own image, against
# <db>_db as <db>_app. The hook runs before the chart's Secrets and ConfigMaps exist, so the passwords are read here
# from files in SECRETS_DIR (the Key Vault CSI mount or the qeos-secrets Secret), never from env in the manifest.
# POSTGRES_SERVER and PGSSLMODE come from the Job's environment.
set -eu

db="$1"
SECRETS_DIR="${SECRETS_DIR:-/mnt/secrets}"

secret() {
  [ -s "$SECRETS_DIR/$1" ] || { echo "migrate: no secret $1 in $SECRETS_DIR" >&2; exit 1; }
  cat "$SECRETS_DIR/$1"
}
POSTGRES_USER="${db}_app"
POSTGRES_DB="${db}_db"
POSTGRES_PASSWORD="$(secret "$db-db-password")"
# Every service's settings refuse to load without it
SECRET_KEY="$(secret secret-key)"
export POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD SECRET_KEY

echo "migrate: $POSTGRES_DB"
exec alembic upgrade head
