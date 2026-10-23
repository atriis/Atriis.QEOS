#!/usr/bin/env bash
# The chart's copies of Compose's monitoring files (files/monitoring/) are byte for byte the originals (ADR-038): Helm
# reads files inside the chart only, so the rules, Alertmanager's renderer and Grafana's dashboards are copied, and an
# edit to an original that misses its copy fails here. Copy the original over the copy to fix it:
#   cp monitoring/prometheus/alerts.yml deploy/helm/qeos/files/monitoring/prometheus/alerts.yml
#   bash deploy/helm/qeos/tests/monitoring_files_test.sh
set -uo pipefail

CHART="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$CHART/../../.." && pwd)"

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# copy (under files/monitoring/) : original (under the repository root)
PAIRS=(
  "prometheus/alerts.yml:monitoring/prometheus/alerts.yml"
  "prometheus/recording.yml:monitoring/prometheus/recording.yml"
  "alertmanager/alertmanager.yml.template:monitoring/alertmanager/alertmanager.yml.template"
  "alertmanager/render.sh:monitoring/alertmanager/render.sh"
  # Grafana's dashboards and their provider (the data source is rendered by the chart: its URL differs)
  "grafana/provisioning/dashboards/qeos.yml:monitoring/grafana/provisioning/dashboards/qeos.yml"
)
for dashboard in "$ROOT"/monitoring/grafana/dashboards/*.json; do
  PAIRS+=("grafana/dashboards/${dashboard##*/}:monitoring/grafana/dashboards/${dashboard##*/}")
done

listed=""
for pair in "${PAIRS[@]}"; do
  copy="$CHART/files/monitoring/${pair%%:*}"
  original="$ROOT/${pair#*:}"
  listed="$listed ${pair%%:*} "
  if [ ! -f "$original" ]; then
    fail "${pair#*:} does not exist"
  elif [ ! -f "$copy" ]; then
    fail "files/monitoring/${pair%%:*} is missing (a copy of ${pair#*:})"
  elif cmp -s "$copy" "$original"; then
    pass "files/monitoring/${pair%%:*} equals ${pair#*:}"
  else
    fail "files/monitoring/${pair%%:*} differs from ${pair#*:}: copy the original over it"
  fi
done

# Nothing in files/monitoring/ that is not a listed copy: an orphan would never be checked
if [ -d "$CHART/files/monitoring" ]; then
  while IFS= read -r f; do
    rel="${f#"$CHART/files/monitoring/"}"
    case "$listed" in *" $rel "*) ;; *) fail "files/monitoring/$rel is not a listed copy (PAIRS)" ;; esac
  done < <(find "$CHART/files/monitoring" -type f | sort)
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures monitoring file check(s) failed"
  exit 1
fi
echo "all monitoring file checks passed"
