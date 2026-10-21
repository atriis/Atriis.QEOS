#!/bin/sh
# Writes the sign-in settings the SPA reads at start (window.__QEOS_CONFIG__, served as /config.js), so one image
# serves every environment. Empty or unset variables are left out and the build-time values apply.
set -eu

DIR=/tmp/qeos-config
OUT="$DIR/config.js"

# Values go into a JS string inside a script: refuse anything that would need escaping (real ids and URLs never do)
check() {
  name="$1"
  value="$2"
  nl='
'
  case "$value" in
    *\"* | *\* | *'<'* | *'>'* | *"$nl"* | *"$(printf '\r')"*)
      echo "qeos-config: $name contains a double quote, backslash, angle bracket or line break; refusing to start" >&2
      exit 1
      ;;
  esac
}

body=""
add() {
  name="$1"
  value="$2"
  [ -n "$value" ] || return 0
  check "$name" "$value"
  [ -z "$body" ] || body="$body,"
  body="$body\"$name\":\"$value\""
}

add GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID:-}"
add MSAL_CLIENT_ID "${MSAL_CLIENT_ID:-}"
add MSAL_AUTHORITY "${MSAL_AUTHORITY:-}"

mkdir -p "$DIR"
printf 'window.__QEOS_CONFIG__ = {%s};\n' "$body" > "$OUT"
