#!/bin/sh
# Renders the NGINX config, makes sure a TLS certificate exists, then runs the given command
# (nginx by default; `nginx -t` to validate the configuration).
set -eu

: "${GATEWAY_HTTPS_PORT:=8443}"
: "${GATEWAY_IMPORT_MAX_BODY:=25m}"
# Where the rendered files and the certificate go (ADR-038). The defaults are what compose has always used (the
# certificate volume is mounted on /etc/nginx/certs); on Kubernetes the root filesystem is read-only, so both point
# at writable directories (/tmp/nginx, and the certificate's own)
: "${NGINX_RENDER_DIR:=/etc/nginx}"
: "${NGINX_CERT_DIR:=/etc/nginx/certs}"
# Where the templates are: the image's copy; the template tests point it at the checkout
: "${GATEWAY_TEMPLATE_DIR:=/etc/qeos}"

# Kubernetes settings (ADR-038, gateway/README.md). The defaults render compose's configuration unchanged.
# Docker's embedded DNS, or the cluster's
: "${GATEWAY_RESOLVER:=127.0.0.11}"
# Appended to every service name: the namespace's ".<ns>.svc.cluster.local" on Kubernetes
: "${UPSTREAM_SUFFIX:=}"
: "${GRAFANA_UPSTREAM:=grafana:3000}"
# off: TLS ends at the edge in front of the gateway, which then serves everything over HTTP on 8080
: "${GATEWAY_TLS:=on}"
# The port clients reach: redirects are built from it (443 behind the edge)
: "${GATEWAY_PUBLIC_PORT:=$GATEWAY_HTTPS_PORT}"
# Per client IP, per gateway replica
: "${RATE_API:=20r/s}"
: "${RATE_AUTH:=5r/s}"
: "${RATE_COLLECT:=10r/s}"
: "${RATE_COLLECT_BLOBS:=50r/s}"
: "${RATE_COLLECT_ARTIFACTS:=10r/s}"

# The values land in nginx.conf as they are: refuse anything that could end a directive or add another
refuse() {
  echo "qeos-gateway: $1 must be $2, got '$3'" >&2
  exit 1
}
# valid VALUE ERE -- the whole value, a single line, matches
valid() {
  case "$1" in *'
'*) return 1 ;; esac
  printf '%s\n' "$1" | grep -Eqx "$2"
}
for rate in RATE_API RATE_AUTH RATE_COLLECT RATE_COLLECT_BLOBS RATE_COLLECT_ARTIFACTS; do
  eval "value=\$$rate"
  valid "$value" '[0-9]+r/[sm]' || refuse "$rate" "a rate such as 20r/s or 150r/m" "$value"
done
case "$GATEWAY_TLS" in on|off) ;; *) refuse GATEWAY_TLS "on or off" "$GATEWAY_TLS" ;; esac
valid "$GATEWAY_PUBLIC_PORT" '[0-9]{1,5}' || refuse GATEWAY_PUBLIC_PORT "a port number" "$GATEWAY_PUBLIC_PORT"
valid "$UPSTREAM_SUFFIX" '(\.[A-Za-z0-9-]+)*' \
  || refuse UPSTREAM_SUFFIX "empty or a domain suffix starting with a dot" "$UPSTREAM_SUFFIX"
valid "$GATEWAY_RESOLVER" '[A-Za-z0-9.:-]+' || refuse GATEWAY_RESOLVER "a host name or address" "$GATEWAY_RESOLVER"
valid "$GRAFANA_UPSTREAM" '[A-Za-z0-9.-]+:[0-9]+' || refuse GRAFANA_UPSTREAM "host:port" "$GRAFANA_UPSTREAM"

# Derived from GATEWAY_TLS, never set by hand. TLS_ONLY starts each line that only exists with TLS on: empty, or a
# "#" that comments the line out. FORWARDED_PROTO is the scheme the services are told: with TLS off, nginx's own
# $scheme is the edge's http hop, but the edge serves HTTPS only, so the services' redirects and secure cookies are
# built for https (a constant: no client-sent X-Forwarded-Proto is believed)
if [ "$GATEWAY_TLS" = on ]; then
  TLS_ONLY='' MAIN_LISTEN='8443 ssl' FORWARDED_PROTO='$scheme'
else
  TLS_ONLY='#' MAIN_LISTEN='8080' FORWARDED_PROTO='https'
fi

export GATEWAY_HTTPS_PORT GATEWAY_IMPORT_MAX_BODY NGINX_RENDER_DIR NGINX_CERT_DIR GATEWAY_RESOLVER UPSTREAM_SUFFIX \
  GRAFANA_UPSTREAM GATEWAY_PUBLIC_PORT RATE_API RATE_AUTH RATE_COLLECT RATE_COLLECT_BLOBS RATE_COLLECT_ARTIFACTS \
  TLS_ONLY MAIN_LISTEN FORWARDED_PROTO
mkdir -p "$NGINX_RENDER_DIR"

# Substitute ONLY these variables, so NGINX's own $host, $request_uri, ... are left alone. Lines starting with "#%"
# are notes on the template itself and are dropped
render() {
  # The pipe's status is sed's: a missing template must stop here
  [ -r "$GATEWAY_TEMPLATE_DIR/$1" ] || { echo "qeos-gateway: no template $GATEWAY_TEMPLATE_DIR/$1" >&2; exit 1; }
  envsubst '${GATEWAY_HTTPS_PORT} ${GATEWAY_IMPORT_MAX_BODY} ${NGINX_RENDER_DIR} ${NGINX_CERT_DIR}
    ${GATEWAY_RESOLVER} ${UPSTREAM_SUFFIX} ${GRAFANA_UPSTREAM} ${GATEWAY_PUBLIC_PORT} ${RATE_API} ${RATE_AUTH}
    ${RATE_COLLECT} ${RATE_COLLECT_BLOBS} ${RATE_COLLECT_ARTIFACTS} ${TLS_ONLY} ${MAIN_LISTEN} ${FORWARDED_PROTO}' \
    < "$GATEWAY_TEMPLATE_DIR/$1" | sed '/^[[:space:]]*#%/d' > "$NGINX_RENDER_DIR/$2"
}
render nginx.conf.template nginx.conf

# /grafana/ (ADR-027): the gated Grafana location when monitoring is on, a plain 404 when it is off.
# The same MONITORING_ENABLED value that makes auth-service offer the Monitoring item, read with the
# same true values as its settings (pydantic: 1, on, t, true, y, yes, any case).
: "${MONITORING_ENABLED:=false}"
case "$(printf '%s' "$MONITORING_ENABLED" | tr '[:upper:]' '[:lower:]')" in
  1|on|t|true|y|yes) render grafana-on.conf grafana.conf ;;
  *) render grafana-off.conf grafana.conf ;;
esac

# Behind a TLS edge proxy (deploy/ on a VM) every request arrives from the proxy's
# address, so per-IP rate limits would be shared by all users. GATEWAY_TRUSTED_PROXIES
# (space-separated CIDRs) names the proxies whose X-Forwarded-For is believed; nginx
# then takes the right-most address no trusted proxy added - the real client - so a
# client-supplied header can never pick its own bucket. Unset: the TCP peer, as before.
: "${GATEWAY_TRUSTED_PROXIES:=}"
REAL_IP="$NGINX_RENDER_DIR/real_ip.conf"
: > "$REAL_IP"
if [ -n "$GATEWAY_TRUSTED_PROXIES" ]; then
  for cidr in $GATEWAY_TRUSTED_PROXIES; do
    echo "set_real_ip_from $cidr;" >> "$REAL_IP"
  done
  echo "real_ip_header X-Forwarded-For;" >> "$REAL_IP"
  echo "real_ip_recursive on;" >> "$REAL_IP"
fi

# No certificate with TLS off: the edge holds the public one
CERT_DIR="$NGINX_CERT_DIR"
if [ "$GATEWAY_TLS" = on ] && { [ ! -s "$CERT_DIR/tls.crt" ] || [ ! -s "$CERT_DIR/tls.key" ]; }; then
  mkdir -p "$CERT_DIR"
  echo "qeos-gateway: generating a self-signed certificate for localhost"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,DNS:gateway,DNS:host.docker.internal" \
    -keyout "$CERT_DIR/tls.key" -out "$CERT_DIR/tls.crt" 2>/dev/null
fi

# nginx reads the rendered file wherever it is; `nginx -t` and the default command alike
if [ "${1:-}" = nginx ]; then
  shift
  set -- nginx -c "$NGINX_RENDER_DIR/nginx.conf" "$@"
fi
exec "$@"
