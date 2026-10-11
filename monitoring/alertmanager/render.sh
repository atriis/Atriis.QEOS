#!/bin/sh
# Renders alertmanager.yml from alertmanager.yml.template and the environment (monitoring spec §5).
# A channel whose settings are missing is left out, so a missing value never stops start-up; with no
# channel at all every alert goes to the "null" receiver and is visible in Grafana only. Secrets go
# into the output file only, never to the log.
#   usage: render.sh OUTPUT
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: render.sh OUTPUT}"
umask 077
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

nl="$(printf '\nx')"
nl="${nl%x}"

# A YAML scalar holding the value verbatim. Normally single-quoted with quotes doubled; a value with a
# line break (which a single-quoted scalar would fold into a space) is double-quoted with escapes instead.
q() {
  case "$1" in
    *"$nl"*|*"$(printf '\r')"*)
      rest="$1"
      res=""
      while [ -n "$rest" ]; do
        c="${rest%"${rest#?}"}"
        rest="${rest#?}"
        case "$c" in
          "$nl") res="$res\n" ;;
          "$(printf '\r')") res="$res\r" ;;
          '\') res="$res\\\\" ;;
          '"') res="$res\\\"" ;;
          *) res="$res$c" ;;
        esac
      done
      printf '"%s"' "$res"
      ;;
    *)
      printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"
      ;;
  esac
}

email=""
slack=""
teams=""
if [ -n "${ALERT_EMAIL_TO:-}" ]; then
  if [ -n "${SMTP_HOST:-}" ]; then
    email=on
  else
    echo "alertmanager: ALERT_EMAIL_TO is set but SMTP_HOST is empty; email alerts are off" >&2
  fi
fi
if [ -n "${ALERT_SLACK_WEBHOOK_URL:-}" ]; then slack=on; fi
if [ -n "${ALERT_TEAMS_WEBHOOK_URL:-}" ]; then teams=on; fi

email_receiver() {
  echo "    email_configs:"
  echo "      - to: $(q "$ALERT_EMAIL_TO")"
  echo "        send_resolved: true"
}
slack_receiver() {
  echo "    slack_configs:"
  echo "      - api_url: $(q "$ALERT_SLACK_WEBHOOK_URL")"
  echo "        send_resolved: true"
}
teams_receiver() {
  echo "    msteamsv2_configs:"
  echo "      - webhook_url: $(q "$ALERT_TEAMS_WEBHOOK_URL")"
  echo "        send_resolved: true"
}

: > "$tmp/global"
if [ -n "$email" ]; then
  case "${SMTP_TLS:-true}" in
    true|True|TRUE|1|yes) tls=true ;;
    *) tls=false ;;
  esac
  {
    echo "  smtp_smarthost: $(q "${SMTP_HOST}:${SMTP_PORT:-587}")"
    echo "  smtp_from: $(q "${EMAILS_FROM_EMAIL:-no-reply@example.com}")"
    if [ -n "${SMTP_USER:-}" ] && [ -n "${SMTP_PASSWORD:-}" ]; then
      echo "  smtp_auth_username: $(q "$SMTP_USER")"
      echo "  smtp_auth_password: $(q "$SMTP_PASSWORD")"
    fi
    echo "  smtp_require_tls: $tls"
  } > "$tmp/global"
fi

# critical: every configured channel
: > "$tmp/critical"
if [ -n "$email" ]; then email_receiver >> "$tmp/critical"; fi
if [ -n "$slack" ]; then slack_receiver >> "$tmp/critical"; fi
if [ -n "$teams" ]; then teams_receiver >> "$tmp/critical"; fi

# warning: Slack and Teams; email only when it is the only channel
: > "$tmp/warning"
if [ -n "$slack" ]; then slack_receiver >> "$tmp/warning"; fi
if [ -n "$teams" ]; then teams_receiver >> "$tmp/warning"; fi
if [ -n "$email" ] && [ -z "$slack" ] && [ -z "$teams" ]; then email_receiver >> "$tmp/warning"; fi

awk -v g="$tmp/global" -v c="$tmp/critical" -v w="$tmp/warning" '
  function dump(file,   line) { while ((getline line < file) > 0) print line; close(file) }
  $0 == "@@GLOBAL@@"   { dump(g); next }
  $0 == "@@CRITICAL@@" { dump(c); next }
  $0 == "@@WARNING@@"  { dump(w); next }
  { print }
' "$here/alertmanager.yml.template" > "$out"
echo "alertmanager: channels email=${email:-off} slack=${slack:-off} teams=${teams:-off}" >&2
