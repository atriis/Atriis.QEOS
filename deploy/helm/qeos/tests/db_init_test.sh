#!/usr/bin/env bash
# db-init.sh against stub psql and pg_isready (no server): a missing or blank role password stops it before any role is
# changed, and with every secret present each role gets its own password. Then, with docker, against a real PostgreSQL
# 16 set up as the CI server is (a CREATEROLE CREATEDB admin, as on Flexible Server): with monitoring on, qeos_monitor
# logs in with pg_monitor, and still does after a second run. Without docker that part is skipped, except in CI.
#   bash deploy/helm/qeos/tests/db_init_test.sh
set -uo pipefail

CHART="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$CHART/files/db-init.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# The stubs: pg_isready always ready; psql records the role password it was given and the SQL it read
mkdir -p "$WORK/bin"
printf '#!/bin/sh\nexit 0\n' > "$WORK/bin/pg_isready"
cat > "$WORK/bin/psql" <<'STUB'
#!/bin/sh
{ printf 'password=%s\n' "${ROLE_PASSWORD:-}"; cat; } >> "$PSQL_LOG"
STUB
chmod +x "$WORK/bin/pg_isready" "$WORK/bin/psql"

# run CASE -- db-init.sh with the secrets in $WORK/CASE (and MONITORING_ENABLED from the caller's MONITORING); its exit
# status, its stderr in $WORK/CASE.err
run() {
  : > "$WORK/$1.log"
  PATH="$WORK/bin:$PATH" PSQL_LOG="$WORK/$1.log" SECRETS_DIR="$WORK/$1" PGHOST=stub PGUSER=admin \
    MONITORING_ENABLED="${MONITORING:-false}" sh "$SCRIPT" > /dev/null 2> "$WORK/$1.err"
}
# secrets CASE -- every secret db-init reads, with distinct values
secrets() {
  mkdir -p "$WORK/$1"
  printf 'admin-pw' > "$WORK/$1/postgres-admin-password"
  for db in auth organization project ingestion testmgmt; do printf '%s-pw' "$db" > "$WORK/$1/$db-db-password"; done
}

secrets complete
if run complete; then
  n="$(grep -c 'ALTER ROLE' "$WORK/complete.log")"
  [ "$n" = 5 ] && pass "every secret present: five roles set" || fail "every secret present: $n ALTER ROLE, want 5"
  grep -qx 'password=testmgmt-pw' "$WORK/complete.log" && pass "each role gets its own password" \
    || fail "testmgmt's password did not reach psql"
  # PostgreSQL 16 makes a role's creator a member WITH ADMIN only, for which pg_has_role(..., 'MEMBER') is already
  # true: guarding on MEMBER skips the grant and CREATE DATABASE ... OWNER fails with "must be able to SET ROLE".
  # The real server path runs in CI's helm-kind job (PostgreSQL 16, a CREATEROLE CREATEDB admin)
  if grep -q "'MEMBER')" "$WORK/complete.log"; then
    fail "the admin's grant is guarded by MEMBER, which PostgreSQL 16's implicit ADMIN-only membership satisfies"
  elif [ "$(grep -c "GRANT %I TO CURRENT_USER WITH INHERIT TRUE, SET TRUE" "$WORK/complete.log")" = 5 ] \
    && [ "$(grep -c "pg_has_role(current_user, :'role', 'SET')" "$WORK/complete.log")" = 5 ] \
    && [ "$(grep -c "pg_has_role(current_user, :'role', 'USAGE')" "$WORK/complete.log")" = 10 ]; then
    pass "each role is granted to the admin WITH INHERIT, SET unless it has USAGE (and SET on 16)"
  else
    fail "the admin's grant is not checked by USAGE and SET"
  fi
else
  fail "every secret present: exit non-zero: $(cat "$WORK/complete.err")"
fi

# check CASE KEY -- db-init exits non-zero, names KEY, and changed no role
check() {
  if run "$1"; then
    fail "$1: exit 0"
  elif ! grep -q "$2" "$WORK/$1.err"; then
    fail "$1: the error does not name $2: $(cat "$WORK/$1.err")"
  elif [ -s "$WORK/$1.log" ]; then
    fail "$1: psql ran before the failure"
  else
    pass "$1: exit non-zero naming $2, before any ALTER ROLE"
  fi
}
grep -q qeos_monitor "$WORK/complete.log" && fail "monitoring off: qeos_monitor is touched" \
  || pass "monitoring off: qeos_monitor is not touched, monitoring-db-password not needed"

# Monitoring on: qeos_monitor gets its own password and pg_monitor, after the five roles
secrets monitoring
printf 'monitoring-pw' > "$WORK/monitoring/monitoring-db-password"
if MONITORING=true run monitoring; then
  grep -qx 'password=monitoring-pw' "$WORK/monitoring.log" && grep -q 'GRANT pg_monitor TO qeos_monitor' "$WORK/monitoring.log" \
    && grep -q 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements' "$WORK/monitoring.log" \
    && pass "monitoring on: qeos_monitor gets monitoring-db-password and pg_monitor; pg_stat_statements exists" \
    || fail "monitoring on: no qeos_monitor password, pg_monitor grant or extension in the SQL"
  [ "$(grep -c 'ALTER ROLE' "$WORK/monitoring.log")" = 6 ] && pass "monitoring on: five roles and qeos_monitor set" \
    || fail "monitoring on: $(grep -c 'ALTER ROLE' "$WORK/monitoring.log") ALTER ROLE, want 6"
else
  fail "monitoring on: exit non-zero: $(cat "$WORK/monitoring.err")"
fi

secrets missing-last
rm "$WORK/missing-last/testmgmt-db-password"
check missing-last testmgmt-db-password
secrets blank-first
printf '\n' > "$WORK/blank-first/auth-db-password"
check blank-first auth-db-password
secrets empty-file
: > "$WORK/empty-file/project-db-password"
check empty-file project-db-password
secrets no-admin
rm "$WORK/no-admin/postgres-admin-password"
check no-admin postgres-admin-password
# Monitoring on without qeos_monitor's password: nothing changes, not even the five roles
secrets no-monitoring
MONITORING=true check no-monitoring monitoring-db-password

# ---- a real PostgreSQL 16 (docker) ----
real_server() {
  local image
  # Globals: the EXIT trap removes the containers after this function returned
  image="$(sed -n 's/^  postgresImage: *//p' "$CHART/values.yaml" | tr -d '\r')"
  id="qeos-dbinit-test-$$"
  server="$id-server"
  client="$id-client"
  # Git Bash would rewrite the container paths below into Windows paths
  export MSYS_NO_PATHCONV=1
  trap 'docker rm -f "$server" "$client" >/dev/null 2>&1; docker network rm "$id" >/dev/null 2>&1; rm -rf "$WORK"' EXIT
  docker network create "$id" >/dev/null || { fail "docker network create"; return; }
  # The CI server (templates/ci-backing.yaml): superuser postgres, pg_stat_statements preloaded, and ci-postgres-init.sh
  # creating the admin qeosadmin. Password logins over the network (scram): the client is another container
  docker create --name "$server" --network "$id" -e POSTGRES_PASSWORD=admin-pw -e QEOS_ADMIN_USER=qeosadmin \
    "$image" postgres -c shared_preload_libraries=pg_stat_statements >/dev/null || { fail "docker create $image"; return; }
  tar -C "$CHART/files" -cf - ci-postgres-init.sh | docker cp - "$server:/docker-entrypoint-initdb.d/" || { fail "docker cp"; return; }
  docker start "$server" >/dev/null
  docker run -d --name "$client" --network "$id" "$image" sleep 600 >/dev/null || { fail "docker run client"; return; }
  secrets real
  printf 'monitoring-pw' > "$WORK/real/monitoring-db-password"
  printf 'admin-pw' > "$WORK/real/postgres-admin-password"
  docker exec "$client" mkdir -p /tmp/qeos/secrets
  tar -C "$WORK/real" -cf - . | docker cp - "$client:/tmp/qeos/secrets/"
  tar -C "$CHART/files" -cf - db-init.sh | docker cp - "$client:/tmp/qeos/"
  for _ in $(seq 60); do
    docker exec "$client" pg_isready -q -h "$server" && break
    sleep 1
  done
  dbinit() {
    docker exec -e PGHOST="$server" -e PGUSER=qeosadmin -e PGSSLMODE=disable -e SECRETS_DIR=/tmp/qeos/secrets \
      -e MONITORING_ENABLED=true "$client" sh /tmp/qeos/db-init.sh > "$WORK/real.out" 2>&1
  }
  # q PASSWORD DB SQL -- as qeos_monitor over the network
  q() { docker exec -e PGPASSWORD="$1" "$client" psql -h "$server" -U qeos_monitor -d "$2" -tAc "$3" 2>&1; }
  if dbinit; then
    pass "real server: db-init with monitoring on, as the CREATEROLE CREATEDB admin"
  else
    fail "real server: db-init failed: $(tail -n 5 "$WORK/real.out")"
    return
  fi
  [ "$(q monitoring-pw postgres "SELECT pg_has_role('qeos_monitor', 'pg_monitor', 'MEMBER')")" = t ] \
    && pass "real server: qeos_monitor logs in with its password and has pg_monitor" || fail "real server: qeos_monitor: $(q monitoring-pw postgres 'SELECT 1')"
  [ "$(q monitoring-pw postgres "SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname = 'qeos_monitor'")" = f ] \
    && pass "real server: qeos_monitor is no superuser and creates neither roles nor databases" || fail "real server: qeos_monitor has more rights"
  [ "$(q monitoring-pw postgres "SELECT count(*) >= 0 FROM pg_stat_statements")" = t ] \
    && pass "real server: qeos_monitor reads pg_stat_statements" || fail "real server: pg_stat_statements: $(q monitoring-pw postgres 'SELECT 1 FROM pg_stat_statements LIMIT 1')"
  # Matched as strings: under pipefail, psql's own failure would fail a pipe into grep
  [[ "$(q wrong-pw postgres "SELECT 1")" == *"password authentication failed"* ]] \
    && pass "real server: a wrong password is refused (the login is checked)" || fail "real server: a wrong password was not refused"
  [[ "$(q monitoring-pw auth_db "SELECT 1")" == *"permission denied"* ]] \
    && pass "real server: qeos_monitor cannot connect to a service's database" || fail "real server: qeos_monitor reaches auth_db"
  if dbinit; then
    [ "$(q monitoring-pw postgres "SELECT pg_has_role('qeos_monitor', 'pg_monitor', 'MEMBER')")" = t ] \
      && pass "real server: a second run keeps qeos_monitor working" || fail "real server: after a second run: $(q monitoring-pw postgres 'SELECT 1')"
  else
    fail "real server: the second run failed: $(tail -n 5 "$WORK/real.out")"
  fi
  # A new secret is the new password on the next run (rotation)
  docker exec "$client" sh -c 'printf rotated-pw > /tmp/qeos/secrets/monitoring-db-password'
  if dbinit && [ "$(q rotated-pw postgres "SELECT 1")" = 1 ] \
      && [[ "$(q monitoring-pw postgres "SELECT 1")" == *"password authentication failed"* ]]; then
    pass "real server: a rotated monitoring-db-password replaces the old one"
  else
    fail "real server: rotation: $(tail -n 3 "$WORK/real.out")"
  fi
}
if docker info >/dev/null 2>&1; then
  real_server
elif [ -n "${CI:-}" ]; then
  fail "docker is not available: the real-server checks must run in CI"
else
  echo "skip  real-server checks: docker is not available"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures db-init check(s) failed"
  exit 1
fi
echo "all db-init checks passed"
