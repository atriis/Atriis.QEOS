#!/usr/bin/env bash
# Every platform image starts as a non-root user with a read-only root filesystem and only /tmp writable, as it runs
# on AKS (ADR-038). Needs Docker and the images built first:
#   docker compose build auth-service organization-service project-service ingestion-service test-management-service dashboard gateway
#   bash scripts/check_readonly_images.sh
# IMAGE_PREFIX and IMAGE_TAG pick other builds (default qeos/<name>:local, the compose names).
set -uo pipefail
export MSYS_NO_PATHCONV=1

PREFIX="${IMAGE_PREFIX:-qeos/}"
TAG="${IMAGE_TAG:-local}"
# Placeholders the services' settings require; the databases are a throwaway postgres on a private network
API_ENV=(-e SECRET_KEY=readonly-check -e INTERNAL_API_PASSWORD=readonly-check -e ORGANIZATION_INTERNAL_API_PASSWORD=readonly-check)
# The read-only root and the one writable directory every pod gets
READONLY=(--read-only --tmpfs /tmp)

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# Every container this run starts carries the label, so cleanup removes them and nothing else
LABEL="qeos-readonly-check=$$"
NETWORK="qeos-readonly-check-$$"
cleanup() {
  docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f >/dev/null 2>&1
  docker network rm "$NETWORK" >/dev/null 2>&1
}
trap cleanup EXIT

# start NAME IMAGE [docker run args...] -- a detached container on the image's own user and command; its id in $id
start() {
  local name="$1" image="$2"
  shift 2
  if ! id="$(docker run -d --label "$LABEL" "${READONLY[@]}" "$@" "$image")"; then
    fail "$name: $image did not start"
    return 1
  fi
}

# not_root NAME CONTAINER -- the process runs as a uid other than 0
not_root() {
  local uid
  uid="$(docker exec "$2" id -u 2>/dev/null | tr -d '\r')"
  if [ -n "$uid" ] && [ "$uid" != 0 ]; then pass "$1 runs as uid $uid"; else fail "$1 runs as uid '${uid:-?}'"; fi
}

# probe NAME CONTAINER COMMAND... -- retried for up to 30 s while the server starts
probe() {
  local name="$1" id="$2"
  shift 2
  for _ in $(seq 1 30); do
    if docker exec "$id" "$@" >/dev/null 2>&1; then
      pass "$name answers on a read-only root"
      return 0
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$id" 2>/dev/null)" != true ]; then break; fi
    sleep 1
  done
  fail "$name does not answer on a read-only root; its log:"
  docker logs "$id" 2>&1 | tail -n 20 | sed 's/^/      /'
  return 1
}

# run_once NAME IMAGE [docker run args and command...] -- a one-shot container that must exit 0 on a read-only root
run_once() {
  local name="$1" out
  shift
  if out="$(docker run --rm --label "$LABEL" "${READONLY[@]}" "$@" 2>&1)"; then
    pass "$name on a read-only root"
  else
    fail "$name on a read-only root: $(printf '%s' "$out" | tail -n 5)"
    return 1
  fi
}

# A throwaway postgres on a private network for the APIs and their jobs; 0 when it accepts connections
start_postgres() {
  if ! docker network create --label "$LABEL" "$NETWORK" >/dev/null; then
    fail "could not create the docker network $NETWORK: the APIs and their jobs are not checked"
    return 1
  fi
  if ! docker run -d --label "$LABEL" --network "$NETWORK" --name "$NETWORK-pg" -e POSTGRES_PASSWORD=postgres \
      postgres:15 >/dev/null; then
    fail "could not start postgres:15: the APIs and their jobs are not checked"
    return 1
  fi
  for _ in $(seq 1 30); do
    docker exec "$NETWORK-pg" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1 && return 0
    sleep 1
  done
  fail "postgres did not become ready within 30 s: the APIs and their jobs are not checked"
  return 1
}

# Each API with its migrations first (the -migrate jobs run the same image), against its own database. The
# ingestion image also runs the platform's jobs: one pass of each, as compose and the cluster start them
if start_postgres; then
  for pair in auth-service:auth_db organization-service:organization_db project-service:project_db \
      ingestion-service:ingestion_db test-management-service:testmgmt_db; do
    IFS=: read -r svc db <<< "$pair"
    image="${PREFIX}${svc}:${TAG}"
    if ! docker exec "$NETWORK-pg" psql -U postgres -qc "CREATE DATABASE $db" >/dev/null 2>&1; then
      fail "$svc: could not create database $db"
      continue
    fi
    db_env=(--network "$NETWORK" -e "DATABASE_URL=postgresql://postgres:postgres@$NETWORK-pg:5432/$db")
    run_once "$svc migrations" "${db_env[@]}" "${API_ENV[@]}" "$image" alembic upgrade head || continue
    if [ "$svc" = ingestion-service ]; then
      # Retention reads project-service's internal feed: the project-service container started above
      job_env=(-e "PROJECT_SERVICE_INTERNAL_URL=http://ingestion-service:readonly-check@project-service:8000")
      for job in rollup impact_rollup weekly_summary "retention --dry-run"; do
        # shellcheck disable=SC2086 # the job's own arguments
        run_once "ingestion job $job" "${db_env[@]}" "${API_ENV[@]}" "${job_env[@]}" "$image" python -m src.ingestion.jobs.$job
      done
    fi
    # The service name as its address on the network, so the jobs above can reach project-service
    start "$svc" "$image" "${db_env[@]}" --network-alias "$svc" "${API_ENV[@]}" || continue
    probe "$svc /health" "$id" python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" && not_root "$svc" "$id"
  done
fi

# 127.0.0.1: busybox wget prefers ::1, and nginx listens on IPv4 only
if start dashboard "${PREFIX}dashboard:${TAG}"; then
  probe "dashboard /" "$id" wget -q -O /dev/null http://127.0.0.1:8080/ && not_root dashboard "$id"
  # The sign-in settings are written to /tmp at start and served uncached
  if docker exec "$id" wget -q -O - http://127.0.0.1:8080/config.js 2>/dev/null | grep -q 'window.__QEOS_CONFIG__'; then
    pass "dashboard /config.js is served"
  else
    fail "dashboard /config.js does not define window.__QEOS_CONFIG__"
  fi
fi

# The gateway renders its configuration and certificate into /tmp, as on Kubernetes
GATEWAY_TMP=(-e NGINX_RENDER_DIR=/tmp/nginx -e NGINX_CERT_DIR=/tmp/certs)
for monitoring in false true; do
  if out="$(docker run --rm "${READONLY[@]}" "${GATEWAY_TMP[@]}" -e MONITORING_ENABLED="$monitoring" \
      "${PREFIX}gateway:${TAG}" nginx -t 2>&1)"; then
    pass "gateway nginx -t (MONITORING_ENABLED=$monitoring)"
  else
    fail "gateway nginx -t (MONITORING_ENABLED=$monitoring): $out"
  fi
done
if start gateway "${PREFIX}gateway:${TAG}" "${GATEWAY_TMP[@]}"; then
  probe "gateway /health" "$id" curl -fsk https://127.0.0.1:8443/health && not_root gateway "$id"
fi
# The Kubernetes settings (ADR-038): TLS ends at the edge, so plain HTTP on 8080 serves every route. The cluster DNS
# name is pointed at 127.0.0.1 here, since nginx resolves its resolver at start and there is no cluster
GATEWAY_K8S=(--add-host kube-dns.kube-system.svc.cluster.local:127.0.0.1 -e GATEWAY_TLS=off
  -e GATEWAY_RESOLVER=kube-dns.kube-system.svc.cluster.local -e UPSTREAM_SUFFIX=.qeos.svc.cluster.local
  -e GATEWAY_PUBLIC_PORT=443 -e RATE_API=10r/s -e RATE_AUTH=150r/m -e RATE_COLLECT=5r/s -e RATE_COLLECT_BLOBS=25r/s
  -e RATE_COLLECT_ARTIFACTS=5r/s)
if out="$(docker run --rm "${READONLY[@]}" "${GATEWAY_TMP[@]}" "${GATEWAY_K8S[@]}" -e MONITORING_ENABLED=true \
    "${PREFIX}gateway:${TAG}" nginx -t 2>&1)"; then
  pass "gateway nginx -t (Kubernetes settings)"
else
  fail "gateway nginx -t (Kubernetes settings): $out"
fi
if start "gateway (Kubernetes settings)" "${PREFIX}gateway:${TAG}" "${GATEWAY_TMP[@]}" "${GATEWAY_K8S[@]}"; then
  probe "gateway (Kubernetes settings) http /health" "$id" curl -fs http://127.0.0.1:8080/health \
    && not_root "gateway (Kubernetes settings)" "$id"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures read-only image check(s) failed"
  exit 1
fi
echo "all read-only image checks passed"
