# nginx 1.30.6 on Alpine 3.24.2 (stable), pinned by digest; Dependabot's docker ecosystem proposes the bumps
FROM nginxinc/nginx-unprivileged:1.31-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e

# Packages are installed as root; the image itself runs as nginx (uid 101) below
USER root

# openssl: self-signed certificate on first start; gettext: envsubst for the config template;
# curl: the compose healthcheck
# apk upgrade: stopgap between base image bumps, as in the dashboard image
RUN apk upgrade --no-cache && apk add --no-cache openssl gettext curl

COPY nginx.conf.template /etc/qeos/nginx.conf.template
COPY grafana-on.conf grafana-off.conf /etc/qeos/
COPY entrypoint.sh /usr/local/bin/qeos-gateway-entrypoint
# /etc/nginx is already nginx's in this image; the certificate directory a new compose volume copies from is too
RUN chmod +x /usr/local/bin/qeos-gateway-entrypoint \
    && install -d -o 101 -g 0 -m 775 /etc/nginx/certs

# Non-root (ADR-038), so it listens on 8080/8443 inside the container. With a read-only root filesystem, point
# NGINX_RENDER_DIR and NGINX_CERT_DIR at writable directories (entrypoint.sh)
USER 101
EXPOSE 8080 8443

# Replaces the stock nginx entrypoint on purpose: it would otherwise also render
# /etc/nginx/templates/* into conf.d and run its own scripts.
ENTRYPOINT ["/usr/local/bin/qeos-gateway-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
