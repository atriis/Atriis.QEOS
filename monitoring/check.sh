#!/usr/bin/env bash
# Static checks of the monitoring configuration, the same locally and in CI (spec §8). Needs Docker only.
#   bash monitoring/check.sh
set -euo pipefail
cd "$(dirname "$0")"
# Git Bash on Windows: a path Docker Desktop understands, and no MSYS rewriting of container paths
here="$(pwd -W 2>/dev/null || pwd)"
export MSYS_NO_PATHCONV=1

PROMETHEUS=prom/prometheus:v3.5.0

run() { docker run --rm -v "$here:/etc/qeos:ro" -w /etc/qeos "$@"; }

echo "== promtool: rules"
run --entrypoint promtool "$PROMETHEUS" check rules prometheus/recording.yml prometheus/alerts.yml prometheus/tests/thresholds.yml
echo "== promtool: rule unit tests"
run --entrypoint promtool "$PROMETHEUS" test rules prometheus/tests/alerts.test.yml
echo "== promtool: configuration (with the thresholds entrypoint.sh renders)"
run --entrypoint /bin/sh "$PROMETHEUS" -c 'sh prometheus/entrypoint.sh --version >/dev/null && promtool check config prometheus/prometheus.yml'
ALERTMANAGER=prom/alertmanager:v0.28.1
echo "== alertmanager: render and amtool check-config"
run --entrypoint /bin/sh "$ALERTMANAGER" alertmanager/test_render.sh
echo "== grafana: dashboard lint"
run python:3.11-slim python grafana/check_dashboards.py
echo "monitoring: all checks passed"
