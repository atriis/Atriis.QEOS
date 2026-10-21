# QEOS Dashboard

React + Vite + TypeScript SPA for the analytics API. Served as static files
by nginx behind the platform gateway (`location /`), so the app and the API
share one origin.

## Develop

    cd dashboard
    npm install
    npm run dev      # Vite dev server; /api/* proxied to https://localhost:8443

Run the stack first (`docker compose up -d --build --wait gateway`) so the
API answers.

## Test / check

    npm run test       # Vitest + Testing Library + MSW
    npm run typecheck  # tsc --noEmit
    npm run lint       # eslint
    npm run build      # production build to dist/

## Shared files

The Overview widget catalogue (`shared/qeos_shared/overview_widgets.json`:
widget types, their settings and the layout limits) is one file for
project-service and the dashboard. `src/overview/catalog.ts` imports it from
outside `dashboard/`, so the image builds with the repository root as context
and the Dockerfile copies the file to `/shared/`. project-service validates
saved layouts against it; the dashboard only skips widget types it does not
know.

## SSO buttons

Google and Microsoft sign-in render only when their client ids are set. At
runtime the container environment wins: `GOOGLE_CLIENT_ID`, `MSAL_CLIENT_ID`
and optional `MSAL_AUTHORITY` (default `organizations`). At start,
`docker-entrypoint.d/40-qeos-config.sh` writes them to `/tmp/qeos-config/config.js`
(`window.__QEOS_CONFIG__`, served by nginx with `Cache-Control: no-store`, so the
root filesystem stays read-only), and `src/config/runtime.ts` reads it, so one
image serves every environment. A value containing `"`, `\`, `<`, `>` or a line
break stops the container with an error. A missing or empty key falls back to the
build-time value (`VITE_GOOGLE_CLIENT_ID`, `VITE_MSAL_CLIENT_ID`,
`VITE_MSAL_AUTHORITY`), which is what compose uses (it forwards them as build
args) and what `npm run dev` uses. The ids must match the auth-service
configuration (`GOOGLE_CLIENT_ID`, `AZURE_ALLOWED_TENANTS`). The SPA obtains an ID
token (Google Identity Services button / MSAL popup) and posts it to
`/api/v1/sso/{provider}`.

## Auth model

Access token in memory; the refresh token never reaches JavaScript — it lives
in the httpOnly `qeos_refresh` cookie (Secure, SameSite=Strict, scoped to
`/api/v1/auth`). App boot restores the session with one silent refresh. On
401 the client refreshes once and retries; a failed refresh returns to
/login. A 401 from the auth endpoints themselves (a failed login) is
surfaced as the API's own error detail.
