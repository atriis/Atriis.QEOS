import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, RouterProvider, createMemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { OverviewLayoutState } from "../api/overviewLayout";
import OverviewPage from "../pages/OverviewPage";
import type { StoredLayout, StoredWidget } from "./catalog";

/** Test helpers for the Overview: imported only by *.test.tsx files. */

export const RUN = {
  id: 61, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: "abcdef1234567890",
  branch: "main", environment: "staging", agent_version: "0.1.0", commit_author: "Ada Lovelace",
  commit_message: "fix(cart): keep totals stable", pr_number: null, base_branch: null,
  started_at: "2026-10-04T10:00:00Z", finished_at: "2026-10-04T10:04:00Z", duration_ms: 240000,
  total: 24, passed: 24, failed: 0, skipped: 0, errored: 0, change_base_ref: null, changed_files: null,
  additions: null, deletions: null, changes_truncated: null, created_at: "2026-10-04T10:05:00Z",
};
export const FAILING_RUN = { ...RUN, passed: 21, failed: 3 };

export const BUILTIN_STATE: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };

export function personalState(...widgets: StoredWidget[]): OverviewLayoutState {
  return { effective: { schema: 1, widgets }, source: "personal", personal: { version: 1, updated_at: "2026-10-10T10:00:00Z" }, project: null };
}

export function projectState(layout: StoredLayout, extra: Partial<OverviewLayoutState> = {}): OverviewLayoutState {
  return {
    effective: layout, source: "project", personal: null,
    project: { version: 2, updated_by: 7, updated_at: "2026-10-09T10:00:00Z", layout },
    ...extra,
  };
}

/** The project, its runs, its layout and its members (user 7 is ada@example.com). */
export function mockOverviewData({ role = "member", layout = BUILTIN_STATE, runs = [RUN] }: {
  role?: string; layout?: OverviewLayoutState; runs?: object[];
} = {}) {
  server.use(
    http.get("/api/v1/projects/42", () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })),
    http.get("/api/v1/projects/42/runs", () => HttpResponse.json(runs)),
    http.get("/api/v1/projects/42/overview-layout", () => HttpResponse.json(layout)),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([
      { id: 1, organization_id: 1, user_id: 7, email: "ada@example.com", role: "owner", status: "active", created_at: "2026-10-01T00:00:00Z" },
    ])),
  );
}

/** The Overview in a data router (so the unsaved-changes guard is active), beside a link away from it. */
export function renderOverview() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/projects/:projectId/overview", element: <><OverviewPage /><Link to="/elsewhere">Elsewhere</Link></> },
      { path: "/elsewhere", element: <p>Elsewhere page</p> },
    ],
    { initialEntries: ["/projects/42/overview"] },
  );
  render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
  return { qc };
}
