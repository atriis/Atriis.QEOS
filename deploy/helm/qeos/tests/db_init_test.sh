#!/usr/bin/env bash
# db-init.sh against stub psql and pg_isready (no server): a missing or blank role password stops it before any role is
# changed, and with every secret present each role gets its own password.
#   bash deploy/helm/qeos/tests/db_init_test.sh
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/files/db-init.sh"
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

# run CASE -- db-init.sh with the secrets in $WORK/CASE; its exit status, its stderr in $WORK/CASE.err
run() {
  : > "$WORK/$1.log"
  PATH="$WORK/bin:$PATH" PSQL_LOG="$WORK/$1.log" SECRETS_DIR="$WORK/$1" PGHOST=stub PGUSER=admin \
    sh "$SCRIPT" > /dev/null 2> "$WORK/$1.err"
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

if [ "$failures" -gt 0 ]; then
  echo "$failures db-init check(s) failed"
  exit 1
fi
echo "all db-init checks passed"
