#!/bin/sh
# wait-for-schema.sh <service dir> -- an API's init container (ADR-038): waits until its database carries this image's
# migration head, so a pod never serves an unmigrated schema. The migration hook Job does the migrating; this only
# watches. Gives up after SCHEMA_WAIT_SECONDS (300). A database AHEAD of the image (a newer release migrated it, and an
# older pod restarts) is accepted: migrations stay compatible with the previous release (expand, then contract).
# Runs in the API's own image, with the API's settings (the database comes from them, as for the app).
set -u

cd "$1" || { echo "wait-for-schema: no directory $1" >&2; exit 1; }
timeout="${SCHEMA_WAIT_SECONDS:-300}"
err="${TMPDIR:-/tmp}/wait-for-schema.err"

# Revision ids only, one per line, sorted: alembic prints "<rev> (head)" on stdout (its logging goes to stderr) and
# prints one line per head
revisions() { awk 'NF { print $1 }' | sort; }

if ! heads="$(alembic heads 2>"$err" | revisions)" || [ -z "$heads" ]; then
  echo "wait-for-schema: no migration head in $1: $(tail -n 3 "$err")" >&2
  exit 1
fi

start="$(date +%s)"
while :; do
  if out="$(alembic current 2>"$err")"; then
    current="$(printf '%s\n' "$out" | revisions)"
    if [ "$current" = "$heads" ]; then
      echo "wait-for-schema: database at" $heads
      exit 0
    fi
    state="at '$(echo $current)'"
  elif grep -q "Can't locate revision" "$err"; then
    echo "wait-for-schema: the database is ahead of this image (a newer release migrated it): compatible by the" \
      "expand/contract rule"
    exit 0
  else
    state="not readable ($(tail -n 1 "$err"))"
  fi
  if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
    echo "wait-for-schema: after ${timeout}s the database is $state; this image needs" $heads >&2
    exit 1
  fi
  sleep 5
done
