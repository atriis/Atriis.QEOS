import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, mockOverviewData, personalState, renderOverview } from "../testing";

const headingLink = async (name: string) => within(await screen.findByRole("heading", { name })).getByRole("link");

const cause = (i: number) => ({
  signature: `s${i}`, headline: `Cause ${i}`, count: 1, failed: 1, errored: 0,
  tests: [{ id: i, test_key: `k${i}`, suite: "s", class_name: "c", name: `test ${i}`, status: "failed" }],
  history: { window: 10, seen_in: 2, streak: 2, since_run_id: 60, since_started_at: "2026-10-03T10:00:00Z" },
});

test("each of the first four widgets links its title to the full view with the same filters", async () => {
  mockOverviewData({ layout: personalState(
    { id: "a", type: "latest_run", size: "wide" },
    { id: "b", type: "failing_now", size: "normal" },
    { id: "c", type: "pass_rate_week", size: "normal", settings: { branch: "main" } },
    { id: "d", type: "flaky_count", size: "normal", settings: { period: 30 } },
  ) });
  renderOverview();
  expect(await headingLink("Latest run")).toHaveAttribute("href", "/projects/42/runs");
  expect(await headingLink("Failing in latest run")).toHaveAttribute("href", "/projects/42/runs?status=failing");
  expect(await headingLink("Pass rate this week")).toHaveAttribute("href", "/projects/42/trends?bucket=week&branch=main");
  // The card foot opens the same filtered view as the title
  expect(await screen.findByRole("link", { name: "Trends" })).toHaveAttribute("href", "/projects/42/trends?bucket=week&branch=main");
  expect(await headingLink("Flaky tests, last 30 days")).toHaveAttribute("href", "/projects/42/flaky?window=30");
});

test("settings reach the requests: a branch for the weekly pass rate, a window for flaky tests", async () => {
  const trends: URLSearchParams[] = [];
  const flaky: URLSearchParams[] = [];
  mockOverviewData({ layout: personalState(
    { id: "c", type: "pass_rate_week", size: "normal", settings: { branch: "main" } },
    { id: "d", type: "flaky_count", size: "normal", settings: { period: 30 } },
  ) });
  server.use(
    http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
      trends.push(new URL(request.url).searchParams);
      return HttpResponse.json({ tz: "UTC", bucket: "week", days: [] });
    }),
    http.get("/api/v1/projects/42/analytics/flaky", ({ request }) => {
      flaky.push(new URL(request.url).searchParams);
      return HttpResponse.json([]);
    }),
  );
  renderOverview();
  await waitFor(() => expect(trends.length).toBeGreaterThan(0));
  await waitFor(() => expect(flaky.length).toBeGreaterThan(0));
  expect(trends[0].get("branch")).toBe("main");
  expect(trends[0].get("bucket")).toBe("week");
  expect(flaky[0].get("window_days")).toBe("30");
  expect(flaky[0].get("include_muted")).toBeNull();
});

test("Failing in latest run lists up to ten causes when its rows are 10", async () => {
  mockOverviewData({ runs: [FAILING_RUN], layout: personalState({ id: "b", type: "failing_now", size: "normal", settings: { rows: 10 } }) });
  server.use(http.get("/api/v1/runs/61/failure-groups", () =>
    HttpResponse.json({ total: 7, groups: Array.from({ length: 7 }, (_, i) => cause(i)) })));
  renderOverview();
  expect(await screen.findByText("Cause 6")).toBeInTheDocument();
});

test("without a branch setting the weekly pass rate covers every branch: no branch in the link or the request", async () => {
  const trends: URLSearchParams[] = [];
  mockOverviewData({ layout: personalState({ id: "c", type: "pass_rate_week", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
    trends.push(new URL(request.url).searchParams);
    return HttpResponse.json({ tz: "UTC", bucket: "week", days: [] });
  }));
  renderOverview();
  expect(await headingLink("Pass rate this week")).toHaveAttribute("href", "/projects/42/trends?bucket=week");
  await waitFor(() => expect(trends.length).toBeGreaterThan(0));
  expect(trends[0].has("branch")).toBe(false);
});
