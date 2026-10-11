#!/bin/sh
# Renders alertmanager.yml.template under several environments and checks each result; amtool validates
# every file when it is on PATH (monitoring/check.sh runs this inside the alertmanager image). Spec §5, §8.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
failures=0

fail() { echo "FAIL $1"; failures=$((failures + 1)); }

# render NAME [VAR=value ...]: a clean environment plus the given variables
render() {
  name="$1"
  shift
  env -i PATH="$PATH" "$@" sh "$here/render.sh" "$out/$name.yml" 2>"$out/$name.err"
  if [ "${skip_amtool:-}" != 1 ] && command -v amtool >/dev/null 2>&1; then
    if ! amtool check-config "$out/$name.yml" >"$out/$name.amtool" 2>&1; then
      fail "$name: amtool rejected it"
      cat "$out/$name.amtool"
    fi
  fi
}

# expect NAME TEXT N: TEXT appears on N lines of NAME's rendered file
expect() {
  n="$(grep -cF -- "$2" "$out/$1.yml" || true)"
  if [ "$n" = "$3" ]; then echo "ok   $1: \"$2\" x$3"; else fail "$1: \"$2\" x$n, expected x$3"; fi
}

SMTP="SMTP_HOST=smtp.example.com"
SLACK="ALERT_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXX"
TEAMS="ALERT_TEAMS_WEBHOOK_URL=https://example.webhook.office.com/webhookb2/abc"

render none
expect none "email_configs:" 0
expect none "slack_configs:" 0
expect none "msteamsv2_configs:" 0

# email alone: critical and warning both go to email
render email_only "$SMTP" ALERT_EMAIL_TO=ops@example.com
expect email_only "email_configs:" 2
expect email_only "smtp_smarthost: 'smtp.example.com:587'" 1
expect email_only "smtp_require_tls: true" 1

# Ruling 11: no SMTP server, no email, a warning in the log
render email_without_smtp ALERT_EMAIL_TO=ops@example.com
expect email_without_smtp "email_configs:" 0
if grep -q "SMTP_HOST is empty" "$out/email_without_smtp.err"; then echo "ok   email_without_smtp: warned"; else fail "email_without_smtp: no warning"; fi

# with Slack, warnings stop going to email
render email_and_slack "$SMTP" ALERT_EMAIL_TO=ops@example.com "$SLACK"
expect email_and_slack "email_configs:" 1
expect email_and_slack "slack_configs:" 2

render all_three "$SMTP" ALERT_EMAIL_TO=ops@example.com "$SLACK" "$TEAMS"
expect all_three "email_configs:" 1
expect all_three "slack_configs:" 2
expect all_three "msteamsv2_configs:" 2

render teams_only "$TEAMS"
expect teams_only "msteamsv2_configs:" 2
expect teams_only "email_configs:" 0

# Review Focus 5: YAML-special characters stay verbatim, and never reach the log
render tricky "$SMTP" ALERT_EMAIL_TO=ops@example.com SMTP_USER=alerts "SMTP_PASSWORD=it's: #not' a comment" SMTP_TLS=false SMTP_PORT=2525
expect tricky "smtp_auth_password: 'it''s: #not'' a comment'" 1
expect tricky "smtp_smarthost: 'smtp.example.com:2525'" 1
expect tricky "smtp_require_tls: false" 1
if grep -qF "#not" "$out/tricky.err"; then fail "tricky: the password reached the log"; fi

# Webhook URLs with ':', '#' and a quote: valid file, value verbatim
render tricky_urls "ALERT_SLACK_WEBHOOK_URL=https://h.example/a:b#c'd" "ALERT_TEAMS_WEBHOOK_URL=https://h.example/t:u#v"
expect tricky_urls "api_url: 'https://h.example/a:b#c''d'" 2
expect tricky_urls "webhook_url: 'https://h.example/t:u#v'" 2
if grep -qF "h.example" "$out/tricky_urls.err"; then fail "tricky_urls: a webhook reached the log"; fi

# A newline in a URL: amtool rightly rejects such a URL, so only the YAML is checked; the value stays
# verbatim as a backslash-n escape and the entry stays on one line
skip_amtool=1
render newline_url "ALERT_TEAMS_WEBHOOK_URL=https://h.example/x
y"
skip_amtool=0
expect newline_url 'webhook_url: "https://h.example/x\ny"' 2
expect newline_url "send_resolved: true" 2

if [ "$failures" -eq 0 ]; then
  echo "render: all checks passed"
else
  echo "render: $failures failure(s)"
  exit 1
fi
