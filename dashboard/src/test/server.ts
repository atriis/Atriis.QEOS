import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// App boot probes the cookie session; default to "no session" so tests that
// don't care never trip the unhandled-request guard. Tests override as needed.
export const server = setupServer(
  http.post("/api/v1/auth/refresh-token", () => new HttpResponse(null, { status: 401 })),
  // Run pages ask for failure groups; tests about them override this
  http.get("/api/v1/runs/:runId/failure-groups", () => HttpResponse.json({ total: 0, groups: [] })),
  // Run pages and failed-step tooltips ask for the run's failed steps; tests about them override this
  http.get("/api/v1/projects/:projectId/runs/:runId/failed-steps", () => HttpResponse.json({ steps: [] })),
  // The run page looks for the previous run to compare with
  http.get("/api/v1/projects/:projectId/runs", () => HttpResponse.json([])),
  // Run from QEOS: pages that show Play or the run panel ask for these; tests about them override
  http.get("/api/v1/projects/:projectId/ci-target", () =>
    HttpResponse.json({ available: true, configured: false, provider: null, repo: null, workflow: null, ref: null,
      token_last4: null, token_expires_at: null, updated_at: null, last_change: null })),
  http.get("/api/v1/projects/:projectId/run-requests", () => HttpResponse.json({ total: 0, items: [] })),
  // The shell's user menu asks who is signed in; tests about the account override
  http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "tester@example.com", mfa_enabled: false })),
  // Superusers' Microsoft roles approval card (ADR-033): nothing to approve; tests about it override
  http.get("/api/v1/organizations/entra-sync", () => HttpResponse.json([])),
  // Sign-in methods (ADR-031): password sign-in on, no SSO; SSO-only tests override
  http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: true, providers: [] })),
  // The Cases KPI tiles (and Overview) read these; tests about them override
  http.get("/api/v1/projects/:projectId/analytics/trends", () => HttpResponse.json({ tz: "UTC", bucket: "week", days: [] })),
  // The report's default branch reads the project's repositories; tests about it override
  http.get("/api/v1/projects/:projectId/repositories", () => HttpResponse.json([])),
  http.get("/api/v1/projects/:projectId/analytics/flaky", () => HttpResponse.json([])),
  http.get("/api/v1/projects/:projectId/analytics/latest-keys", () => HttpResponse.json({ keys: [] })),
  // Settings' Log values card (ADR-032): no patterns, no scan; tests about it override
  http.get("/api/v1/projects/:projectId/log-patterns", () =>
    HttpResponse.json({ patterns: [], scan: { state: "idle", since: null } })),
  // Play's duration estimate: no history unless a test says otherwise
  http.post("/api/v1/projects/:projectId/analytics/duration-estimate", () => HttpResponse.json({
    estimate_ms: null, upper_ms: null, tests_with_history: 0, tests_without_history: 0, environment_used: 0,
    model: { overhead_ms: 0, factor: 1, runs: 0, fitted: false } })),
  // The Overview's layout: nothing saved, so the built-in four cards; tests about layouts override
  http.get("/api/v1/projects/:projectId/overview-layout", () =>
    HttpResponse.json({ effective: null, source: "builtin", personal: null, project: null })),
  // Test impact: the run page's card and the Report's section ask for these; tests about them override
  http.get("/api/v1/projects/:projectId/runs/:runId/impact", ({ params }) => HttpResponse.json({
    run_id: Number(params.runId), state: "no_change_data", changed_paths: [], replayed: false, scored_at: null,
    suggestion: null, outcome: null })),
  http.get("/api/v1/projects/:projectId/analytics/impact-accuracy", ({ request }) => HttpResponse.json({
    days: Number(new URL(request.url).searchParams.get("days") ?? 30), caught: 0, missed: 0, rate: null,
    avg_suggested: null, includes_replayed: false, live: { runs: 0, caught: 0, missed: 0, suggested: 0 },
    replayed: { runs: 0, caught: 0, missed: 0, suggested: 0 }, misses: [], misses_total: 0 })),
  // Names of the people who ran or stopped something
  http.get("/api/v1/organizations/:orgId/members", () => HttpResponse.json([])),
);
