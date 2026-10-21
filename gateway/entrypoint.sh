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
export GATEWAY_HTTPS_PORT GATEWAY_IMPORT_MAX_BODY NGINX_RENDER_DIR NGINX_CERT_DIR
mkdir -p "$NGINX_RENDER_DIR"

# Substitute ONLY these variables, so NGINX's own $host, $request_uri, ... are left alone
envsubst '${GATEWAY_HTTPS_PORT} ${GATEWAY_IMPORT_MAX_BODY} ${NGINX_RENDER_DIR} ${NGINX_CERT_DIR}' \
  < /etc/qeos/nginx.conf.template > "$NGINX_RENDER_DIR/nginx.conf"

# /grafana/ (ADR-027): the gated Grafana location when monitoring is on, a plain 404 when it is off.
# The same MONITORING_ENABLED value that makes auth-service offer the Monitoring item, read with the
# same true values as its settings (pydantic: 1, on, t, true, y, yes, any case).
: "${MONITORING_ENABLED:=false}"
case "$(printf '%s' "$MONITORING_ENABLED" | tr '[:upper:]' '[:lower:]')" in
  1|on|t|true|y|yes) cp /etc/qeos/grafana-on.conf "$NGINX_RENDER_DIR/grafana.conf" ;;
  *) cp /etc/qeos/grafana-off.conf "$NGINX_RENDER_DIR/grafana.conf" ;;
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

CERT_DIR="$NGINX_CERT_DIR"
mkdir -p "$CERT_DIR"
if [ ! -s "$CERT_DIR/tls.crt" ] || [ ! -s "$CERT_DIR/tls.key" ]; then
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
