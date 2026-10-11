import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "./test/server";
import { setAccessToken } from "./auth/tokens";
import { AppRoutes } from "./App";

/** Every API call fails: the page's h1 must not wait for data. */
function renderAt(path: string) {
  setAccessToken("acc");
  server.use(http.all("/api/v1/*", () => HttpResponse.json({ detail: "not here" }, { status: 404 })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ROUTES: [string, string][] = [
  ["/", "Projects"],
  ["/account/security", "Security"],
  ["/monitoring", "Monitoring"],
  ["/organizations/1", "Organization 1"],
  ["/projects/42/overview", "Overview"],
  ["/projects/42/runs", "Runs"],
  ["/projects/42/runs/requested", "Requested runs"],
  ["/projects/42/runs/61", "Run #61"],
  ["/projects/42/runs/61/compare/60", "Run #61 compared with #60"],
  ["/projects/42/tests", "Test results"],
  ["/projects/42/tests/tests%2Fa.py", "Test history"],
  ["/projects/42/flaky", "Flaky tests"],
  ["/projects/42/branches", "Branches"],
  ["/projects/42/trends", "Trends"],
  ["/projects/42/report", "Report"],
  ["/projects/42/cases", "Test cases"],
  ["/projects/42/cases/new", "New test case"],
  ["/projects/42/cases/import", "Import from Gherkin"],
  ["/projects/42/cases/12", "TC-12"],
  ["/projects/42/cases/feature?path=features%2Flogin.feature", "login"],
  ["/projects/42/suites", "Suites"],
  ["/projects/42/suites/3", "Suite"],
  ["/projects/42/settings", "Settings"],
];

test.each(ROUTES)("%s renders exactly one h1, naming the page (%s)", async (path, name) => {
  renderAt(path);
  const main = screen.getByRole("main");
  expect(await within(main).findByRole("heading", { level: 1, name })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
});
