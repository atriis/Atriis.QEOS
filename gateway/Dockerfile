FROM nginx:1.27-alpine

# openssl: self-signed certificate on first start; gettext: envsubst for the config template;
# curl: the compose healthcheck
RUN apk add --no-cache openssl gettext curl

COPY nginx.conf.template /etc/qeos/nginx.conf.template
COPY grafana-on.conf grafana-off.conf /etc/qeos/
COPY entrypoint.sh /usr/local/bin/qeos-gateway-entrypoint
RUN chmod +x /usr/local/bin/qeos-gateway-entrypoint

EXPOSE 80 443

# Replaces the stock nginx entrypoint on purpose: it would otherwise also render
# /etc/nginx/templates/* into conf.d and run its own scripts.
ENTRYPOINT ["/usr/local/bin/qeos-gateway-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
