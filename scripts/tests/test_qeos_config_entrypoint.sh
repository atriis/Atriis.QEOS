#!/bin/sh
# The dashboard's start-up script refuses values that would need escaping and writes the rest. No Docker needed:
#   sh scripts/tests/test_qeos_config_entrypoint.sh
SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/dashboard/docker-entrypoint.d/40-qeos-config.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
failures=0

# run VAR VALUE -- the script's exit status with only that variable set
run() {
  env -u GOOGLE_CLIENT_ID -u MSAL_CLIENT_ID -u MSAL_AUTHORITY QEOS_CONFIG_DIR="$TMP/out" "$1=$2" sh "$SCRIPT" 2>"$TMP/err"
}
reject() {
  if run "$1" "$2" && true; then echo "FAIL  $1 accepted $3"; failures=$((failures + 1)); return; fi
  if grep -q "$1" "$TMP/err"; then echo "ok    $1 rejects $3"; else echo "FAIL  $1 rejected $3 without naming itself"; failures=$((failures + 1)); fi
}
accept() {
  if run "$1" "$2"; then echo "ok    $1 accepts $3"; else echo "FAIL  $1 rejected $3"; failures=$((failures + 1)); fi
}

for var in GOOGLE_CLIENT_ID MSAL_CLIENT_ID MSAL_AUTHORITY; do
  reject "$var" 'a"b' 'a double quote'
  reject "$var" 'a\b' 'a backslash'
  reject "$var" 'a<b' '<'
  reject "$var" 'a>b' '>'
  reject "$var" "$(printf 'a\nb')" 'a line feed'
  reject "$var" "$(printf 'a\rb')" 'a carriage return'
  accept "$var" '1234-abc.apps.googleusercontent.com' 'a Google id'
  accept "$var" '3f2a9c1e-5b7d-4c8e-9a10-2b6d4e8f0a12' 'a GUID'
  accept "$var" 'https://login.microsoftonline.com/3f2a9c1e-5b7d-4c8e-9a10-2b6d4e8f0a12' 'an https URL'
  accept "$var" 'ab*' 'an asterisk'
done

run GOOGLE_CLIENT_ID 'g-1' && grep -qx 'window.__QEOS_CONFIG__ = {"GOOGLE_CLIENT_ID":"g-1"};' "$TMP/out/config.js" \
  && echo "ok    config.js content" || { echo "FAIL  config.js content"; failures=$((failures + 1)); }

[ "$failures" -eq 0 ] || { echo "$failures failure(s)"; exit 1; }
echo "all entrypoint checks passed"
