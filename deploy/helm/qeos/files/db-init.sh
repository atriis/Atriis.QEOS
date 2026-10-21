#!/bin/sh
# db-init.sh -- the migration hook's first step (ADR-038), run with the PostgreSQL admin login: creates each service's
# database and its login role <db>_app, and makes that role the owner of its own database only. Idempotent: it runs
# before every install and upgrade, and resets each role's password to the current secret.
# Connection: PGHOST, PGUSER, PGSSLMODE from the environment; the passwords are files in SECRETS_DIR (the Key Vault CSI
# mount or the qeos-secrets Secret): postgres-admin-password and <db>-db-password.
set -eu

SECRETS_DIR="${SECRETS_DIR:-/mnt/secrets}"
DATABASES="${DATABASES:-auth organization project ingestion testmgmt}"

secret() {
  [ -s "$SECRETS_DIR/$1" ] || { echo "db-init: no secret $1 in $SECRETS_DIR" >&2; exit 1; }
  cat "$SECRETS_DIR/$1"
}
PGPASSWORD="$(secret postgres-admin-password)"
export PGPASSWORD
export PGDATABASE=postgres

# The server may still be starting (the CI one is created moments earlier): up to 2 minutes
tries=0
until pg_isready -q; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "db-init: PostgreSQL at $PGHOST does not accept connections" >&2
    exit 1
  fi
  sleep 2
done

for db in $DATABASES; do
  # The password goes in as a psql variable read from the environment (\getenv), quoted as a literal by :'pw', so
  # it is on no command line and never spliced into the SQL text
  ROLE_PASSWORD="$(secret "$db-db-password")" psql -v ON_ERROR_STOP=1 -q -v role="${db}_app" -v db="${db}_db" <<'SQL'
\getenv pw ROLE_PASSWORD
SELECT format('CREATE ROLE %I LOGIN', :'role') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')\gexec
-- a server running with log_statement=ddl or all would log this password; the default is none
ALTER ROLE :"role" WITH LOGIN PASSWORD :'pw';
-- Flexible Server's admin is not a superuser: it must be a member of a role to give it a database
SELECT format('GRANT %I TO CURRENT_USER', :'role') WHERE NOT pg_has_role(current_user, :'role', 'MEMBER')\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'role') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db')\gexec
ALTER DATABASE :"db" OWNER TO :"role";
-- Only its owner (and the admin) connects: no service reaches another's database
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
SQL
  echo "db-init: database ${db}_db owned by ${db}_app"
done
