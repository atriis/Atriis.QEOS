FROM node:24-alpine AS build
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
# The Overview widget catalogue is shared with project-service (spec 2026-10-11 §3.2). src/overview/catalog.ts
# imports ../../../shared/..., which from /app/src/overview resolves to /shared/.
COPY shared/qeos_shared/overview_widgets.json /shared/qeos_shared/overview_widgets.json
# SSO client ids baked at build time (Vite) are the fallback for the container environment (see config.js below);
# empty means the button is hidden.
ARG VITE_GOOGLE_CLIENT_ID=""
ARG VITE_MSAL_CLIENT_ID=""
ARG VITE_MSAL_AUTHORITY=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID \
    VITE_MSAL_CLIENT_ID=$VITE_MSAL_CLIENT_ID \
    VITE_MSAL_AUTHORITY=$VITE_MSAL_AUTHORITY
RUN npm run build

# Non-root (ADR-038): nginx (uid 101) on port 8080, pid and temporary files in /tmp, so the root filesystem can be
# read-only
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Sign-in settings from the container's environment (GOOGLE_CLIENT_ID, MSAL_CLIENT_ID, MSAL_AUTHORITY), written to
# /tmp/qeos-config/config.js at start; the VITE_* values baked above remain the fallback
COPY --chmod=755 dashboard/docker-entrypoint.d/40-qeos-config.sh /docker-entrypoint.d/40-qeos-config.sh
USER 101
EXPOSE 8080
