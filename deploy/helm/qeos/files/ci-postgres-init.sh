#!/bin/sh
# ci-postgres-init.sh -- kind in CI only (ci.backing): run once by the postgres image's entrypoint on a new data
# directory. It creates the admin login the chart uses (postgres.adminUser) the way Azure Database for PostgreSQL
# Flexible Server has it: not a superuser, only LOGIN CREATEROLE CREATEDB, so db-init runs in CI with the same rights it
# has on Azure (ADR-038). For monitoring it gives the admin what Flexible Server's azure_pg_admin has: pg_monitor to
# grant (to qeos_monitor), and pg_stat_statements, which the platform allows (azure.extensions) and the server here
# preloads (templates/ci-backing.yaml), already created. The superuser stays the image's own `postgres`. The entrypoint
# sources this file and stops on the first error.
psql -v ON_ERROR_STOP=1 -q --username "$POSTGRES_USER" --dbname postgres -v admin="$QEOS_ADMIN_USER" <<'SQL'
\getenv pw POSTGRES_PASSWORD
CREATE ROLE :"admin" LOGIN CREATEROLE CREATEDB NOSUPERUSER PASSWORD :'pw';
GRANT pg_monitor TO :"admin" WITH ADMIN OPTION;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
