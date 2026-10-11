#!/bin/sh
# Creates each service database that does not exist yet. The root docker-compose stack runs this
# on EVERY `up` (job `db-init`): Postgres's own /docker-entrypoint-initdb.d scripts run only on an
# empty volume, so a database added for a new service would otherwise never be created on an
# existing one. Connection comes from PGHOST / PGUSER / PGPASSWORD.
set -eu

for db in auth_db organization_db project_db ingestion_db testmgmt_db; do
  if psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'" | grep -q 1; then
    echo "database $db exists"
  else
    psql -c "CREATE DATABASE \"$db\""
    echo "database $db created"
  fi
done

# Monitoring (spec 2026-10-10 section 7): role qeos_monitor with pg_monitor only, which reads statistics and
# settings but no table data. This script runs on every `up`, so the same step creates the role on a
# new install and on one made before monitoring existed, and keeps its password equal to
# MONITORING_DB_PASSWORD. Skipped while the password is unset (monitoring off). The password goes in as
# a psql variable (:'pw' quotes it as a literal), never spliced into the SQL text.
if [ -n "${MONITORING_DB_PASSWORD:-}" ]; then
  psql -v ON_ERROR_STOP=1 -q -d postgres -v pw="$MONITORING_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE qeos_monitor LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qeos_monitor')\gexec
ALTER ROLE qeos_monitor WITH LOGIN PASSWORD :'pw';
GRANT pg_monitor TO qeos_monitor;
-- the PostgreSQL dashboard's slowest statements (Ruling 10)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
  echo "role qeos_monitor ready"
fi
