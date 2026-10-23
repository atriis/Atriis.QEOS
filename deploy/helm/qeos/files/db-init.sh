#!/bin/sh
# db-init.sh -- the migration hook's first step (ADR-038), run with the PostgreSQL admin login: creates each service's
# database and its login role <db>_app, and makes that role the owner of its own database only. Idempotent: it runs
# before every install and upgrade, and resets each role's password to the current secret.
# Connection: PGHOST, PGUSER, PGSSLMODE from the environment; the passwords are files in SECRETS_DIR (the Key Vault CSI
# mount or the qeos-secrets Secret): postgres-admin-password and <db>-db-password. With MONITORING_ENABLED=true it also
# makes postgres-exporter's role qeos_monitor, with the password monitoring-db-password.
set -eu

SECRETS_DIR="${SECRETS_DIR:-/mnt/secrets}"
DATABASES="${DATABASES:-auth organization project ingestion testmgmt}"
MONITORING_ENABLED="${MONITORING_ENABLED:-false}"

# secret KEY -- the key's file content; exits (naming the key) when the file is missing or blank
secret() {
  if [ ! -s "$SECRETS_DIR/$1" ] || [ -z "$(tr -d '[:space:]' < "$SECRETS_DIR/$1")" ]; then
    echo "db-init: no secret $1 in $SECRETS_DIR" >&2
    exit 1
  fi
  cat "$SECRETS_DIR/$1"
}
PGPASSWORD="$(secret postgres-admin-password)"
# Every role's password must be there before any role is touched: a missing one changes nothing
for db in $DATABASES; do
  secret "$db-db-password" >/dev/null
done
if [ "$MONITORING_ENABLED" = true ]; then
  secret monitoring-db-password >/dev/null
fi
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
  # On a line of its own: as a prefix of the psql command below, a failing `secret` would not stop the script, and an
  # empty password would clear the role's (locking out its running pods on an upgrade)
  ROLE_PASSWORD="$(secret "$db-db-password")"
  [ -n "$ROLE_PASSWORD" ] || { echo "db-init: secret $db-db-password is empty" >&2; exit 1; }
  export ROLE_PASSWORD
  # The password goes in as a psql variable read from the environment (\getenv), quoted as a literal by :'pw', so
  # it is on no command line and never spliced into the SQL text
  psql -v ON_ERROR_STOP=1 -q -v role="${db}_app" -v db="${db}_db" <<'SQL'
\getenv pw ROLE_PASSWORD
SELECT format('CREATE ROLE %I LOGIN', :'role') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')\gexec
-- a server running with log_statement=ddl or all would log this password; the default is none
ALTER ROLE :"role" WITH LOGIN PASSWORD :'pw';
-- Flexible Server's admin is not a superuser: to give the role a database it must be able to SET ROLE to it, and to
-- revoke on that database it must hold the role's privileges (INHERIT). PostgreSQL 16 already makes the role's creator
-- a member WITH ADMIN only (no INHERIT, no SET), for which 'MEMBER' is true: check USAGE (and SET on 16), not MEMBER.
-- A superuser passes every check and is never granted anything
SELECT :SERVER_VERSION_NUM >= 160000 AS pg16 \gset
\if :pg16
SELECT format('GRANT %I TO CURRENT_USER WITH INHERIT TRUE, SET TRUE', :'role')
  WHERE NOT (pg_has_role(current_user, :'role', 'USAGE') AND pg_has_role(current_user, :'role', 'SET'))\gexec
\else
SELECT format('GRANT %I TO CURRENT_USER', :'role') WHERE NOT pg_has_role(current_user, :'role', 'USAGE')\gexec
\endif
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'role') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db')\gexec
ALTER DATABASE :"db" OWNER TO :"role";
-- Only its owner (and the admin) connects: no service reaches another's database
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
SQL
  echo "db-init: database ${db}_db owned by ${db}_app"
done

# Monitoring on: postgres-exporter's login role qeos_monitor with pg_monitor only (statistics and settings, no table
# data), as scripts/postgres-init.sh makes it for Compose, and pg_stat_statements in the postgres database for the
# slowest-statements panel. Flexible Server lets its admin grant pg_monitor and create the extension, which Bicep allows
# in azure.extensions; the CI server's init script gives its admin the same (files/ci-postgres-init.sh). With
# monitoring off an existing qeos_monitor is left as it is
if [ "$MONITORING_ENABLED" = true ]; then
  ROLE_PASSWORD="$(secret monitoring-db-password)"
  [ -n "$ROLE_PASSWORD" ] || { echo "db-init: secret monitoring-db-password is empty" >&2; exit 1; }
  export ROLE_PASSWORD
  psql -v ON_ERROR_STOP=1 -q <<'SQL'
\getenv pw ROLE_PASSWORD
SELECT 'CREATE ROLE qeos_monitor LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qeos_monitor')\gexec
-- a server running with log_statement=ddl or all would log this password; the default is none
ALTER ROLE qeos_monitor WITH LOGIN PASSWORD :'pw';
-- Granting pg_monitor needs ADMIN OPTION on it (PostgreSQL 16, a non-superuser admin). Without it the role still
-- logs in and postgres-exporter runs with fewer statistics: a warning, never a failed deploy (ADR-038)
SELECT pg_has_role('qeos_monitor', 'pg_monitor', 'MEMBER') AS has_monitor,
       pg_has_role(current_user, 'pg_monitor', 'MEMBER WITH ADMIN OPTION') AS can_grant \gset
\if :has_monitor
\elif :can_grant
GRANT pg_monitor TO qeos_monitor;
\else
\warn 'db-init: WARNING: the admin login cannot grant pg_monitor (no ADMIN OPTION on it): qeos_monitor exists without it and monitoring is degraded; as a server admin run GRANT pg_monitor TO qeos_monitor'
\endif
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
  echo "db-init: role qeos_monitor (pg_monitor) for postgres-exporter"
fi
